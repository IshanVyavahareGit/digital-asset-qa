# Automated Visual QA & Review for Esports Media

## Context

TEC Productions' media/design teams manually review hundreds of tournament graphics per week for
misspelled player handles, missing sponsor logos, unsafe text placement, and theme violations. This
is a bottleneck and error-prone. The take-home asks for a working prototype that **automates the first
QA pass** on esports graphics and gives managers a **visual review + human-in-the-loop feedback**
interface, with a Designer (read-only) and Manager (reviewer) role split.

We are implementing **all three tiers** (Tier 1 mandatory; Tier 2 + Tier 3), **excluding only the
cheap-model-first cascade** from Tier 3's "confidence and cost controls" (we keep per-check confidence
scores). Grading weights: AI correctness 30%, pipeline design 25%, review/HITL UI 20%, code quality &
reproducibility 15%, judgement/communication 10%.

Decisions locked with the user:
- **Mock asset pack** generated now (swap in real pack later).
- **Gemini 2.5 Flash** as the vision model (native 0–1000 bounding boxes, strong OCR, cheapest).
- **Lightweight JWT auth** with seeded Designer/Manager accounts + hashed passwords.
- **In-process async queue** for batch mode (no Celery/Redis).

## Key research finding — why Gemini + a hybrid pipeline

- **Gemini 2.5** natively returns `box_2d` as `[ymin, xmin, ymax, xmax]` normalized to **0–1000**,
  trivially converted to pixels/percentages. Claude/GPT-5 localize poorly (mean IoU ~0.16, <10% of
  boxes reach 0.5 IoU); Qwen3-VL is strong but needs GPU self-hosting.
- **Do not route everything through the VLM.** Use the right tool per check — this is more accurate,
  cheaper, and defensible in the live walkthrough:
  | Check | Engine | Why |
  |---|---|---|
  | Typo / roster + text boxes | Gemini 2.5 Flash (OCR + reasoning, structured JSON) | Needs semantic cross-ref to roster.json |
  | Sponsor logo presence/visibility | **OpenCV** feature matching (ORB/SIFT + multi-scale template) vs the exact provided logo PNGs | Deterministic; gives precise box + size/brightness visibility metrics |
  | Safe-zones | Pure geometry (§4 danger rects ∩ critical-element boxes) | No AI needed |
  | Palette / contrast / clutter / off-theme | **Gemini 2.5 Flash** (given brand-guide palette + fonts + tone in the prompt) | One VLM design-review pass returns off-palette regions, low-contrast text, clutter, theme deviations — each with a box, severity, message; no color math |

- **Coordinate storage = normalized percentages (0–1) + original canvas W×H.** Frontend overlays boxes
  with `%` positioning over the displayed image → responsive on any screen size.

### Coordinate normalization — how 0–1000 works across 1080×1920 / 1920×1080 / 1080×1080

Gemini's `box_2d` is **not pixels**. It normalizes **each axis independently** to a 0–1000 scale, so
aspect ratio is irrelevant — a tall image is not squashed into a square. Convert per-axis by the real
length of that axis:

```
box_2d = [ymin, xmin, ymax, xmax]        # each 0–1000
x_px = (xmin / 1000) * canvas_width       # x-axis → real width
y_px = (ymin / 1000) * canvas_height      # y-axis → real height
```

We store **0–1 fractions** (`box_2d / 1000`) + `canvas_w`/`canvas_h`. Fractions are aspect-independent,
so the frontend positions boxes purely in `%` over the rendered `<img>` (which preserves aspect ratio) →
responsive on any display size, identical logic for all three canvas dimensions.

Caveats handled in code: integer 0–1000 → ~0.1% granularity (~1.9px worst case at 1920px, fine);
Gemini localization can drift on extreme aspect ratios, which is *why sponsor-logo boxes come from
pixel-exact OpenCV* and every box carries a visible `confidence`.

## Architecture (parallel evaluation pipeline)

The user's "parallel agents" instinct maps to **concurrent check modules** rather than an LLM-per-check.
An orchestrator fans out all applicable checks with `asyncio.gather`, each emitting a common `Finding`
schema; a verdict aggregator reduces findings → Pass / Needs Changes / Fail.

```
Upload ─▶ Ingestion (store image, read canvas dims, resolve platform + graphic type)
             │
             ▼
     Orchestrator (asyncio.gather — runs checks concurrently)
       ├─ TypoRosterCheck      (Gemini: OCR + roster cross-ref)      ─┐
       ├─ SponsorAuditCheck    (OpenCV template/feature match)        │
       ├─ SafeZoneCheck        (geometry, uses text/logo boxes)       ├─▶ List[Finding]
       └─ DesignThemeCheck     (Gemini: palette/contrast/clutter)    ─┘
             │
             ▼
     Verdict aggregator (severity-weighted) ─▶ persist Review + Findings (SQLite)
             │
             ▼
     Manager review UI (overlay + side panel, override flow) / Designer read-only view
```

**Honest failure handling (explicit requirement):** each check returns a `status` of
`ok | low_confidence | failed`. If Gemini/OCR returns unparseable or empty output, the check reports
`failed` with a human-readable reason and the UI shows a "could not evaluate" banner for that check —
**never fabricates findings.** Structured output is enforced via Gemini `response_schema` (Pydantic),
with a retry + schema-validation guard.

## Tech stack

- **Backend:** Python + **FastAPI** (async — ideal for parallel LLM/CV calls; matches their internal stack).
- **AI:** `google-genai` SDK → **Gemini 2.5 Flash** with `response_schema` for structured findings.
- **CV / imaging:** OpenCV, Pillow, NumPy, `scikit-image` (ΔE color distance).
- **DB:** **SQLite** via SQLAlchemy 2.0 + Alembic (or `create_all` for demo).
- **Auth:** JWT (`python-jose`) + `passlib[bcrypt]`; seeded designer/manager users; role-gated routes.
- **Frontend:** **Next.js (App Router) + TypeScript + TailwindCSS**, targeting a modern, flawless,
  highly-polished UI. Details below.
- **Run:** `docker compose up` (backend + frontend + shared volume for uploads/db). `.env` for `GEMINI_API_KEY`.

### Frontend UX & animation (must feel flawless and smooth)

- **Framework:** Next.js 15 App Router, TypeScript, TailwindCSS, **shadcn/ui** for a consistent modern
  component system, **Framer Motion** for animation, **Lucide** icons. Dark/neon aesthetic that nods to
  the esports brand tone.
- **Marker/overlay system (the centerpiece):** absolutely-positioned `%`-based boxes/pins over the
  rendered `<img>` in a responsive container. Interactions must be buttery:
  - Boxes animate in with staggered spring transitions; hover raises/glows the box and highlights its
    side-panel row (and vice-versa) — bi-directional hover sync.
  - Click a finding → smooth pan/zoom-to-region and a pulsing focus ring on the marker.
  - Manager annotation: draw-a-box (drag) and drop-a-pin, both with live rubber-band feedback and a
    popover comment editor; springy enter/exit.
  - Severity-coded colors (info/warning/critical) with subtle motion, not garish.
- **Motion polish elsewhere:** page/route transitions, upload dropzone with drag-over state and progress,
  animated verdict badge reveal, skeleton/shimmer loaders while the pipeline runs, toast feedback on
  override actions, animated triage dashboard cards. Respect `prefers-reduced-motion`.
- **Data layer:** TanStack Query for fetching/caching + optimistic updates on manager overrides so the
  UI feels instant; typed API client consuming the backend's structured `Finding` JSON (no regex parsing).
- **Responsiveness:** overlays stay pixel-aligned across breakpoints because positioning is `%`-based;
  layout adapts image + side-panel from stacked (mobile) to split (desktop).

## Data model (SQLite)

- `User(id, email, hashed_password, role[designer|manager])`
- `Graphic(id, filename, path, graphic_type, platform, canvas_w, canvas_h, uploaded_by, version_group_id, parent_graphic_id, created_at)`
- `Review(id, graphic_id, verdict[pass|needs_changes|fail], reasoning, status, created_at)`
- `Finding(id, review_id, check_type, severity[info|warning|critical], message, suggested_fix,
   bbox_x, bbox_y, bbox_w, bbox_h (all 0–1 normalized), confidence, source[ai|manager],
   status[open|dismissed|edited], is_pin)`
- `ReferenceGraphic(id, image_path, label)` — for Tier 3 theme learning.
- Batch tracked via `version_group_id` / a lightweight `BatchJob(id, status, counts)` row.

## Implementation phases

**0. Mock asset pack** (`assets/`): 15 PNGs at 1080×1920 and 1920×1080 (some seeded with typos /
missing logo / unsafe text / off-palette), `roster.json`, 4 sponsor logo PNGs + `sponsor_manifest.json`,
`brand_guide.json` (palette hex, fonts, tone), `safe_zones.json` encoding §4.

**1. Tier 1 — Core**
- FastAPI app skeleton, SQLite models, `Finding`/`Review` Pydantic schemas.
- `TypoRosterCheck` (Gemini structured OCR + roster cross-ref) and `SponsorAuditCheck` (OpenCV).
- Orchestrator + verdict aggregator.
- Upload endpoint (`POST /graphics` with type) → runs pipeline → returns review + findings.
- Next.js: animated upload dropzone + graphic-type select; **image with bounding-box/pin overlay** +
  side panel (finding, severity, suggested fix) with bi-directional hover sync; animated verdict badge
  with reasoning.

**2. Tier 2 — Full eval + HITL**
- `SafeZoneCheck` (geometry from `safe_zones.json`) and `DesignThemeCheck` — a single Gemini design-review
  pass that receives the brand guide (palette hex, approved fonts, tone) and returns findings for
  off-palette colours, poor text contrast, cluttered layout, and theme-spec deviation, each with a box +
  severity + suggested fix. No color math / WCAG computation.
- Manager override flow: dismiss / edit text / change severity; add finding by drawing a box or
  dropping a pin with a comment (persisted, `source=manager`).
- JWT auth + role gating; **Designer read-only view** showing final reviewed feedback (which findings
  stand, manager edits, manager notes). Persistence survives refresh (DB-backed).

**3. Tier 3 — Stretch (all except model cascade)**
- **Batch mode:** `POST /batch` accepts 10+ graphics → in-process asyncio queue (bounded concurrency)
  → **triage dashboard** sorted by verdict with progress.
- **Re-check loop:** designer uploads a revised version tied to `version_group_id`; system re-runs
  checks and **diffs findings** (resolved / persisting / new).
- **Per-check confidence scores** surfaced in UI (cascade explicitly out of scope).
- **Theme learning:** feed 3 approved reference graphics as few-shot image context to `DesignThemeCheck`
  so it calibrates against them in addition to the written brand guide.

**4. Deliverables**
- `README.md` (setup, tiers completed, limitations, **API cost of a demo run**).
- `ARCHITECTURE.md` (1–2 pp: visual-data pipeline, structured-output contract, frontend wiring,
  production-scale changes; diagram).
- Demo-video script covering happy path + one failure case.

## Structured AI output contract (they read this closely)

Gemini returns, per check, a list conforming to a Pydantic `Finding` schema — `check_type`, `severity`,
`message`, `suggested_fix`, `box_2d` (0–1000, converted server-side to normalized 0–1), `confidence`.
No regex parsing on the frontend; the frontend consumes typed JSON only.

## Estimated API cost

Gemini 2.5 Flash ≈ $0.30/M input, $2.50/M output. Each graphic ≈ 2 Gemini calls (~1.5k in / ~0.7k out
tokens each incl. image tiles). Full 15-graphic demo ≈ **well under $0.50** — comfortably inside the
₹1,500 cap.

## Verification

1. `docker compose up` from a clean checkout → backend + frontend reachable (README first-run test).
2. Log in as manager, upload a **seeded-error** graphic → confirm the correct findings appear with
   boxes on the right regions, sensible severity, and a Needs Changes / Fail verdict.
3. Upload a **clean** graphic → Pass with no false positives.
4. Manager override: dismiss a finding, edit one, add a pinned note → refresh → state persists.
5. Log in as designer → read-only view reflects the manager's final feedback.
6. Batch-upload 10+ → triage dashboard sorts by verdict; re-upload a fixed version → diff marks
   resolved findings.
7. **Failure path:** feed a garbage/non-graphic image → UI shows "could not evaluate", no hallucinated
   findings.
8. Confirm coordinate mapping is responsive: resize the browser → overlays stay aligned (they're `%`-based).

## Sources (VLM research)
- Gemini image understanding / bounding boxes: https://ai.google.dev/gemini-api/docs/image-understanding
- Roboflow — Gemini 2.5 zero-shot detection/segmentation: https://blog.roboflow.com/gemini-2-5-object-detection-segmentation/
- Qwen3-VL grounding: https://qwen.ai/blog?id=99f0335c4ad9ff6153e517418d48535ab6d8afef
- OSS VLM landscape 2026: https://www.bentoml.com/blog/multimodal-ai-a-guide-to-open-source-vision-language-models
- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
