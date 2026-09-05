# Walkthrough Prep — Automated Visual QA

Your goal in the 60 min: sound like the person who **designed** this, not who generated it.
That means leading with the *why*, being honest about what's paused and why, and being fast
when they ask you to change something. This doc is your study guide + defense cheatsheet.

---

## 0. The 30-second pitch (memorize)

> "It's a visual-QA pipeline for esports graphics. A manager uploads a graphic; the backend
> runs a set of **independent checks in parallel**, each returning **structured findings with
> coordinates**, and aggregates them into a Pass / Needs-Changes / Fail verdict. The findings
> are mapped onto the image as draggable boxes and pins, and a manager can override them —
> dismiss, edit, reposition, or add their own — while a designer sees the reviewed result.
> The core design principle is **the LLM extracts, deterministic Python judges** — so the AI
> never invents a verdict and every finding is defensible."

---

## 1. Architecture mental model

```
Next.js (App Router)                    FastAPI
  Login / Auth ─ JWT ───────────────▶  /auth        JWT + bcrypt, seeded users, role gating
  Dashboard (TanStack Query cache) ──▶  /reviews     list (deduped per version lineage)
  Upload ───────────────────────────▶  /graphics    ─┐
  Batch ────────────────────────────▶  /batch        │  evaluate_and_store()
  Re-check ─────────────────────────▶  /reviews/{}/recheck   │
  Overlay + HITL overrides ─────────▶  /findings     │        ▼
                                                      │   Orchestrator (asyncio.gather)
                                                      │     ├ TypoRosterCheck   (Gemini OCR + roster xref)
                                                      │     └ MatchupCheck      (Gemini pairings vs roster.matches)
                                                      │     [paused: SponsorAudit(OpenCV), SafeZone(geo), DesignTheme(Gemini)]
                                                      │        ▼
                                                      │   verdict aggregator → Pass/Needs/Fail
                                                      ▼        ▼
                                              SQLite (SQLAlchemy)  +  images on disk (/static)
```

**Layering (say this):** `api/` (thin HTTP) → `services/` (evaluation, gemini, assets) →
`pipeline/` (orchestrator, verdict, diff) → `checks/` (one module per check) → `db/` + `core/`.
Every check implements the same `Check` interface, so the orchestrator treats an LLM call, a
CV routine, or pure geometry identically.

---

## 2. Trace ONE upload end-to-end (they love this)

`POST /graphics` →
1. **`require_manager`** (`core/security.py`) decodes JWT, checks role → 403 for designers.
2. **`api/graphics.py`** validates `graphic_type`/`platform` against enums, reads bytes.
3. **`services/evaluation.py:evaluate_and_store`**:
   - `_store_image` — PIL reads canvas W×H, writes bytes to `data/uploads/{uuid}.ext`. **Metadata in DB, bytes on disk.**
   - Builds a `CheckContext` (bytes, dims, type, platform).
   - `await evaluate(ctx)` — **no DB connection is held during the pipeline** (this matters, see §5 batch).
   - Persists `Graphic → Review → CheckRun[] → Finding[]` with **explicit UUIDs in one commit**.
   - Records a `UsageEvent` (append-only cost ledger).
4. **`pipeline/orchestrator.py:evaluate`**: `asyncio.gather` over analyzers; each wrapped in
   `_timed` which records duration and converts any crash into an honest `failed` result.
5. **verdict aggregator** reduces findings + pipeline health → verdict + reasoning.
6. **`api/serializers.py`** → `ReviewOut`: findings with **0–1 fraction boxes**, per-check health, verdict.

---

## 3. Design decisions & how to defend them  ← THE CORE OF THE INTERVIEW

For each: the decision, the one-line defense, and the trade-off you consciously accepted.

### 3.1 Hybrid pipeline: "LLM extracts, Python judges"
- **Decision:** Gemini only does OCR / pairing *extraction*; the roster cross-reference and
  severity are **deterministic Python** (`difflib` fuzzy match, set membership).
- **Defense:** The LLM never sees the roster, so it can't silently "auto-correct" a seeded typo,
  and the judgment logic is unit-testable and reproducible. It also keeps the AI output auditable.
- **Trade-off:** More code than "ask the LLM if it's correct," but far more defensible and stable.

### 3.2 Why Gemini (and why 3.5-flash)
- **Decision:** Gemini for the vision calls; model is a one-line config (`GEMINI_MODEL`).
- **Defense:** Gemini natively returns bounding boxes (`box_2d`, 0–1000, per-axis normalized) as
  structured JSON — Claude/GPT localize poorly (mean IoU ~0.16). We need coordinates for the
  overlay. 3.5-flash: strong OCR + reasoning at low cost; the box format is identical across 2.5/3.x
  so switching is a config change, zero code.
- **Trade-off:** VLM localization still isn't pixel-perfect — which is *why* logo detection uses
  OpenCV (paused now), and why coordinates are draggable.

### 3.3 Coordinates as 0–1 fractions (+ canvas W×H)
- **Decision:** Store every box as fractions of the canvas, not pixels.
- **Defense:** `box_2d` is per-axis normalized, so it's aspect-independent; storing fractions lets
  the frontend position markers purely in `%` over the rendered `<img>` — responsive on any screen,
  identical logic for 1080×1920 / 1920×1080 / 1080×1080. Convert to pixels only if needed (× canvas).
- **Where:** `services/gemini.py:box2d_to_bbox` (÷1000, clamp, malformed-box guard).

### 3.4 Structured outputs (Pydantic `response_schema`)
- **Decision:** Gemini is called with a Pydantic `response_schema`; the frontend consumes typed JSON.
- **Defense:** The brief demanded "structured data, not regex-parsed text." Schema-enforced JSON +
  a retry + a malformed-box fallback means the frontend never parses free text.
- **Where:** `services/gemini.py:generate` (config `response_mime_type=application/json`, retry loop).

### 3.5 Honest failure handling (no hallucinated findings)
- **Decision:** Each check returns a health status `ok | low_confidence | failed`. If Gemini is
  unavailable or OCR returns nothing legible, the check reports `failed` and emits **zero** findings;
  the verdict can't be a clean Pass if a check couldn't run.
- **Defense:** Directly answers the brief's "honest failure" requirement. The UI shows a per-check
  "could not evaluate" state instead of pretending.
- **Where:** `checks/base.py:CheckResult.failed`, `CheckHealth.tsx`, verdict guard in `verdict.py`.

### 3.6 Separate `MatchupCheck` (not folded into typo)
- **Decision:** A distinct check validates that "A vs B" is a *scheduled* pairing.
- **Defense:** Different concern (relational vs spelling) and different extraction shape (pairs, not
  flat tokens). Clean separation → independently testable, toggleable, and it no-ops (skips the API
  call) for `roster_update`. Typo owns spelling; if a team name is misspelled, matchup skips it (no
  double-flag).
- **Where:** `checks/matchup.py`, `services/assets.py:scheduled_pairings/resolve_team`.

### 3.7 Async orchestration + the batch-DB bug you fixed
- **Decision:** Analyzers run concurrently via `asyncio.gather`; batch uses a bounded semaphore.
- **The bug you found (tell this story — it shows depth):** the first version flushed the Graphic
  row to get its id *before* the ~15s pipeline, holding a SQLite write lock for the whole pipeline.
  Three concurrent batch items then blocked each other to the 30s lock timeout and froze the event
  loop. **Fix:** run the whole DB-free pipeline first, then persist in one short commit with
  pre-generated UUIDs; enabled WAL + busy_timeout.
- **Where:** `services/evaluation.py`, `db/session.py` pragmas, `api/batch.py`.

### 3.8 Persistence choices
- **SQLite + SQLAlchemy 2.0 (sync):** simplest thing that works for a single-node demo; the
  concurrency that matters is the *pipeline* (async), not the DB. WAL lets the dashboard read while a
  batch writes.
- **Bytes on disk, metadata in DB:** keeps the DB small/fast; images served from `/static`.
- **Explicit UUIDs + single commit:** avoids mid-pipeline flushes (see §3.7).

### 3.9 Verdict aggregation (pure, recomputable)
- **Rule:** any active critical → Fail; else any warning → Needs Changes; else Pass. Guardrail: a
  would-be Pass is downgraded if a check failed (can't certify what you didn't evaluate).
- **Defense:** Pure and side-effect-free, so it's recomputed on every override — dismiss a critical
  and the verdict updates live. Dismissed findings don't count.
- **Where:** `pipeline/verdict.py`, re-run in `api/findings.py` after every mutation.

### 3.10 Versioning / revision lineage
- **Decision:** Revisions are new Graphic rows sharing a `version_group_id`; the dashboard collapses
  a lineage to one card (latest), older versions marked REVISED; a version timeline lives on the
  review page.
- **Defense:** Without this, a designer's revision looked like an unrelated graphic. Grouping + the
  timeline keep parent and revisions together.
- **Where:** `api/reviews.py` (dedupe + `/versions`), `VersionTimeline.tsx`.

### 3.11 Cost ledger
- **Decision:** Append-only `UsageEvent` table; USD frozen at each call's model price.
- **Defense:** Survives restarts *and* data deletion; model-aware pricing. Honest caveat: it's a
  list-price **estimate**, not the billed amount (no request overhead / free-tier credits).

### 3.12 Frontend
- **`%`-based overlay:** markers positioned in `%`, so they stay aligned at any size (see §3.3).
- **TanStack Query cache + invalidation:** mutations write the server's returned review straight into
  the cache (instant UI) and invalidate the list; drag-to-reposition uses an **optimistic** cache
  write so the marker doesn't flash back.
- **Drag disambiguation:** small movement = select (click); real movement = reposition (`PATCH bbox`).
- **Role gating:** `canEdit = role === manager` hides overrides/drag for designers.

---

## 4. Files most likely to be opened — know these cold

| File | What to say |
|---|---|
| `pipeline/orchestrator.py` | The parallel fan-out; analyzers vs composer; `_timed` safety net; how to add a check |
| `checks/base.py` | The `Check` interface, `CheckContext`, `CheckResult`, `RawFinding` — the contract |
| `checks/typo_roster.py` | Gemini extraction schema + `_check_member` fuzzy logic (case-insensitive, `difflib` cutoff 0.6) |
| `checks/matchup.py` | Pairing extraction + `scheduled_pairings` set membership + dedupe + placeholder skip |
| `services/gemini.py` | `response_schema`, retry, `box2d_to_bbox`, pricing table, `usd_for` |
| `services/evaluation.py` | The DB-free-pipeline-then-single-commit pattern (the batch fix) |
| `pipeline/verdict.py` | The 3-line verdict rule + failed-pipeline guardrail |
| `components/ImageOverlay.tsx` | `%` positioning, pointer-drag, click-vs-drag, canEdit gating |
| `lib/hooks.ts` | Cache keys + `useReviewSync` (setQueryData + invalidate) |

**Non-obvious lines to pre-explain:**
- `box2d_to_bbox`: the `if len(box_2d) != 4: return zero-box` guard — Gemini occasionally emits a
  malformed 3-value box; without this it crashed the whole check.
- `_valid_time_tokens`: the `if m.get("time_utc")` skip — an empty string is a substring of
  everything, which would make *every* time "valid."
- `known_team_names`: includes name + tag + aliases — brackets say "S8UL", roster says "S8UL Esports."
- `evaluation.py` explicit UUIDs — so children reference parents without a mid-pipeline flush.

---

## 5. Rapid-fire Q&A (rehearse out loud)

- **"Why not a real object detector (YOLO)?"** For a 12–18h build with arbitrary graphics and no
  training data, a VLM's zero-shot boxes + OCR are the pragmatic choice; where precision matters
  (logos) I use OpenCV template matching. And boxes are draggable, so a human corrects the last mile.
- **"What stops the AI hallucinating a finding?"** The LLM only *extracts*; Python decides. On
  garbage input the check reports `failed` and emits nothing. Verdict can't Pass if a check failed.
- **"How are coordinates accurate across resolutions?"** Per-axis 0–1000 → stored as 0–1 fractions →
  `%` positioning. Resolution-independent by construction.
- **"Why SQLite? Production?"** Fine for single-node demo. For hundreds/day: Postgres, object storage
  (S3) for images, a real queue (Celery/Redis or SQS) instead of the in-process asyncio queue, and a
  worker pool; the check interface and structured contract don't change.
- **"How does batch avoid DB locks?"** (Tell the flush-lock story from §3.7.)
- **"Cost accuracy?"** Token-accurate from `usage_metadata`, list-price estimate, not the billed
  invoice — that lives in the Google console.
- **"Why is sponsor/design/safe-zone off?"** Scoping decision: they need inputs you deferred (real
  sponsor logos, a brand guide, per-platform danger zones matched to real dimensions). They're coded
  and re-enable by adding them back to `ANALYZERS`/`COMPOSER` — one line each. *(This is a judgment
  story the brief rewards — say it confidently, don't apologize.)*

---

## 6. "Modify one small thing on the spot" — rehearsed drills

Practice each until it's muscle memory. Know the file + the exact edit.

1. **Change the verdict rule** ("make 2 warnings = Needs Changes"):
   `pipeline/verdict.py` — add `elif len(warnings) >= 2:` branch. One function, pure, no restart of
   logic needed beyond uvicorn reload.
2. **Add a platform / graphic type:** `core/enums.py` add an enum value; the upload select and safe
   zones read from there. (Note `instagram_post` was already added this way.)
3. **Tune the typo sensitivity:** `checks/typo_roster.py` — `difflib.get_close_matches(..., cutoff=0.6)`.
   Lower = more typos flagged, more false positives. Explain the trade-off.
4. **Add a new check:** create `checks/foo.py` implementing `Check` (set `check_type`, return
   `CheckResult`), add `CheckType.foo` to enums, add `FooCheck()` to `ANALYZERS`. Emphasize the
   uniform interface is what makes this a 3-file change.
5. **Change a severity:** e.g., make "unrecognized handle" critical — one line in `_check_member`.
6. **Hide low-confidence findings:** frontend filter `findings.filter(f => (f.confidence ?? 1) > 0.5)`
   in the review page, or a backend query param.
7. **Add a dashboard filter by verdict:** `useReviews` data + a client-side filter chip.
8. **Re-enable a check live:** uncomment `SponsorAuditCheck()` in `ANALYZERS` — but only if the
   sponsor assets exist; otherwise explain why it'd report `failed` (honest failure, on purpose).

Golden rule during the live edit: **narrate as you go** ("I'll change X here because Y; this is
pure so nothing else is affected; let me reload and show it"). That's the whole test.

---

## 7. Live demo script (happy path + failure)

**Setup before the call:** backend on the port `.env.local` expects (currently 8001), frontend `npm run dev`,
`GEMINI_API_KEY` set, a couple of graphics pre-uploaded so the dashboard isn't empty.

1. **Login** as manager → point out role gating (designer can't upload/override).
2. **Upload** a match announcement → narrate the live pipeline steps → land on the workspace.
3. **Overlay:** hover a finding ↔ box highlight (bidirectional sync); note the "% of canvas" caption.
4. **Check health:** show the per-check "validated / could not evaluate" — the honest-failure story.
5. **HITL:** dismiss a finding → verdict recomputes live; add a pin/box (click vs drag); **drag** an AI
   box and reload → it persisted.
6. **Failure case (required by brief):** temporarily unset `GEMINI_API_KEY` (or upload a garbage/non-
   graphic image) → checks report `failed`, no fabricated findings, verdict downgraded. This is your
   strongest "we thought about honesty" moment.
7. **Batch:** upload several → triage board sorts worst-first with live progress.
8. **Re-check:** submit a corrected version → resolved/persisting/new diff; show the version timeline.
9. **Designer view:** log in as designer → read-only, sees the reviewed feedback.

---

## 8. Say these limitations BEFORE they ask (signals judgment)

- Sponsor/design/safe-zone are built but paused pending real assets; re-enable = one line.
- Thresholds (fuzzy cutoff, OpenCV scores) are tuned to the demo pack; real assets need recalibration.
- VLM boxes aren't pixel-perfect — mitigated by draggable markers + OpenCV for logos.
- Roster is the single source of truth: if it's incomplete (e.g., an event's matches aren't loaded),
  matchup correctly flags those pairings — that's honest behavior, not a bug.
- Heavily stylized wordmark logos challenge OCR (the "37N/Talent 7 Nation" case) — surfaced, not hidden.
- Cost is a list-price estimate, not the billed amount.
- Auth is lightweight (seeded users, JWT) — deliberately not a full account lifecycle for a demo.

---

## 9. Production-scale answers (the brief asks this explicitly)

- **Storage:** Postgres + S3/object storage for images (not local disk).
- **Queue:** replace the in-process asyncio queue with Celery/Redis or SQS + a worker pool;
  the pipeline is already stateless per graphic.
- **Model cost at scale:** cheap-model-first cascade (extract with flash-lite, escalate ambiguous
  findings to a stronger model) — intentionally *not* built (scoped out), but you can describe it.
- **Throughput:** the checks are independent and IO-bound; scale horizontally by worker count.
- **Observability:** per-check timings + confidence are already recorded (`CheckRun`); add tracing.
- **What does NOT change:** the `Check` interface and the structured `Finding` contract — new checks
  and new models plug in without touching the API or frontend. That's the point of the design.

---

### Final mindset
Lead with *why*, own the scoping decisions, tell the batch-lock debugging story, and when they ask
you to change something — narrate the reasoning while you type. You built this; talk like it.
