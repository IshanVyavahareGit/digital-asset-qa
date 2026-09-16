# Digital Asset QA

**Automated first-pass QA for esports tournament graphics, with a human-in-the-loop review interface.**

Media teams review hundreds of tournament graphics a week, looking for misspelled player
handles, unscheduled matchups, missing sponsor logos, text that will be covered by platform
UI, and off-brand design. It's slow and error-prone.

This prototype automates that first pass. A manager uploads a graphic; five independent
checks run against it; each returns **structured findings with coordinates**; a pure
function reduces them to Pass / Needs Changes / Fail. Findings are drawn onto the image as
draggable boxes and pins that a reviewer can dismiss, edit, reposition or add to — and the
verdict recomputes live as they do.

```
Upload ──▶ 4 checks in parallel ──▶ safe-zone composition ──▶ verdict ──▶ review UI
             Gemini · OpenCV · geometry                        pure fn      overlay + overrides
```

---

## The design principle

> **The LLM extracts. Python judges.**

Gemini is never asked *"is this graphic correct?"* It is asked to read text verbatim and
report where it found it. Whether a name is misspelled, whether a matchup is legitimate,
and what the verdict should be are all decided by deterministic Python.

Three consequences that shaped the whole codebase:

- **The model can't mask a bug.** The roster is never in the prompt, so Gemini physically
  cannot "helpfully" auto-correct a seeded typo before a human sees it.
- **Every finding is traceable** to a comparison you can point at — a `difflib` ratio, a set
  membership test, an area fraction.
- **Failure is honest.** A check that can't run reports `failed` and emits *zero* findings.
  A graphic can never be certified Pass if part of the pipeline didn't execute.

---

## Quick start

Requires a [Gemini API key](https://aistudio.google.com/apikey) for the three model-backed
checks. Without one, those checks honestly report "could not evaluate" and the two
deterministic checks still run.

### Docker

```bash
cp .env.example .env     # paste your GEMINI_API_KEY
docker compose up --build
```

### Native

```bash
# backend — must be port 8001
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env  # paste your GEMINI_API_KEY
uvicorn app.main:app --reload --port 8001
```

```bash
# frontend, second terminal
cd frontend && npm install && npm run dev
```

Open **http://localhost:3000**. Two accounts are seeded on first boot:

| Role | Email | Password | Can do |
|---|---|---|---|
| Manager | `manager@tec.dev` | `manager123` | upload, evaluate, override findings |
| Designer | `designer@tec.dev` | `designer123` | read-only, submit revisions |

Sample graphics live in `assets/typo-check/`. Each has a `_wrong` variant with seeded
errors. Start with **`bracket_2.png`** as *Bracket · X Post* — it's 16:9 and exercises the
matchup and sponsor checks.

> Uploads are validated against the platform's aspect ratio. The four ~4:5 portrait samples
> don't match any supported platform and will return 422 — see [Known limitations](#known-limitations).

---

## The five checks

Right tool per job, rather than routing everything through a vision model.

| Check | Engine | Question | Who decides |
|---|---|---|---|
| **Typo & Roster** | Gemini OCR | Is every name spelled as the roster spells it? | Python (`difflib`, cutoff 0.6) |
| **Matchup** | Gemini | Are these two teams actually scheduled to play? | Python (frozenset membership) |
| **Sponsor Audit** | OpenCV | Is each required logo present, large enough, visible? | Python (three thresholds) |
| **Safe Zone** | Pure geometry | Will platform UI cover anything important? | Python (area overlap) |
| **Design & Theme** | Gemini | Does this look like it belongs to the brand? | the model |

Four run concurrently via `asyncio.gather`. Safe Zone runs last because it has no detector
of its own — it tests the elements Typo and Sponsor already located, and completes in ~1 ms.

Every check implements the same interface in [`checks/base.py`](backend/app/checks/base.py),
so an LLM call, an OpenCV routine and pure arithmetic are indistinguishable to the
orchestrator. Adding a sixth check is a three-file change; the API and frontend don't move.

---

## Engineering decisions worth reviewing

### Right tool per check, not one model for everything
Sponsor logos are matched with OpenCV template matching rather than the VLM, because the
exact logo files exist — that's a measurement problem, not a perception problem, and it
yields a pixel-exact box instead of an approximate one.
→ [`checks/sponsor_audit.py`](backend/app/checks/sponsor_audit.py)

### Thresholds tuned against measured data, not guessed
`PRESENT = 0.88` sits in the middle of a measured gap: genuinely present logos score
**0.972–1.000**, while the scale pyramid's smallest steps throw spurious matches up to
**0.793** on graphics with no logo at all. The original 0.70 produced false positives.

Visibility is judged *separately* from the match score, because `TM_CCOEFF_NORMED` is
invariant to brightness — a logo watermarked to 10% opacity still scored **0.967**. The
match score cannot tell you whether a human can see the logo, so local grayscale standard
deviation does that job.

### A concurrency bug worth the story
The first version flushed the `Graphic` row to obtain an id *before* the ~20 s pipeline —
taking a SQLite write lock and holding it throughout. Three concurrent batch items then
blocked each other to the 30 s lock timeout.

Fixed by generating UUIDs in Python up front, running the entire DB-free pipeline, then
writing every row in **one short commit**. The primary-key type is what makes the fix
possible. WAL mode and `busy_timeout` were added alongside.
→ [`services/evaluation.py`](backend/app/services/evaluation.py)

### Resolution-independent coordinates
Gemini returns `box_2d` on a per-axis 0–1000 grid. That's divided by 1000 and stored as
**0–1 fractions**; the frontend multiplies by 100 and positions markers in CSS percent. The
same code handles 1080×1920, 1920×1080 and 1080×1080 with no branching, and overlays stay
aligned when the window resizes.
→ [`services/gemini.py:box2d_to_bbox`](backend/app/services/gemini.py)

### Honest failure, enforced by the verdict
Each check reports `ok | low_confidence | failed`, persisted per-run in `check_runs`. A
failed check emits nothing, and the aggregator downgrades a would-be Pass:

```python
if verdict == Verdict.passed and pipeline_status != "ok":
    verdict = Verdict.needs_changes    # can't certify what you didn't evaluate
```

Feed it a photo of a cat and the UI shows "could not evaluate" per check — never a
fabricated finding.
→ [`pipeline/verdict.py`](backend/app/pipeline/verdict.py)

### Checks coordinate so findings don't duplicate
Typo owns spelling; Matchup deliberately uses **exact** lookup with no fuzzy fallback. A
misspelled team name resolves to `None` and the pairing is skipped rather than double-flagged.
One typo produces one finding. The same rule makes bracket placeholders like
*"Winner of Upper Bracket Final"* self-skip with no special case.

### Human-in-the-loop that actually closes
Managers dismiss, edit, reposition and resize markers; every mutation recomputes the verdict
server-side and returns the whole review, which TanStack Query writes straight into cache.
AI findings can be **dismissed but never deleted**, preserving the audit trail of what the
model reported. Designers can't override, but they *can* submit a revision — which becomes a
new version in the same lineage and produces a resolved / persisting / new diff.

---

## Project structure

```
backend/app/
├── api/         thin HTTP — validate, delegate, serialize
├── pipeline/    orchestrator (parallel fan-out), verdict (pure), diff
├── checks/      one module per check, all the same interface
├── services/    evaluation (persistence), gemini (structured output), assets
├── db/          SQLAlchemy models + session (WAL, busy_timeout)
└── core/        enums, typed config, JWT + bcrypt security

frontend/
├── app/         login · dashboard · review · recheck · batch
├── components/  ImageOverlay (the centrepiece), FindingsPanel, CheckHealth
└── lib/         typed API client, TanStack Query hooks, types mirroring the backend

assets/          swap these files, not code, to change tournament
├── roster.json            teams, tags, aliases, 29 scheduled matches
├── sponsor_manifest.json  which logos are mandatory per graphic type
├── brand_guide.json       palette, fonts, tone → injected into the prompt
├── safe_zones.json        platform UI danger zones
└── typo-check/            test graphics, each with a _wrong variant
```

**Stack** — FastAPI · SQLAlchemy 2.0 · SQLite · Gemini · OpenCV · Next.js 15 (App Router) ·
TypeScript · TanStack Query · Tailwind · Framer Motion.

---

## Features

- **Parallel check pipeline** with per-check health, timing and token accounting
- **Interactive overlay** — boxes and pins, drag to move, eight grips to resize,
  bi-directional hover sync with the findings panel
- **Role-gated HITL** — manager overrides vs designer read-only, from one code path
- **Batch mode** — bounded-concurrency queue (3 workers), live progress, triage board
  sorted worst-first
- **Re-check loop** — revisions form a version lineage; findings diff into
  resolved / persisting / new
- **Cost ledger** — append-only, deliberately unlinked from graphics so spend history
  survives deletions, with USD frozen at each call's model price

---

## Known limitations

Stated deliberately — these are scoping decisions and open bugs, not omissions.

- **No test suite.** The pure functions (`compute_verdict`, fuzzy matcher,
  `scheduled_pairings`, overlap arithmetic) are designed to be trivially testable and
  aren't yet tested. This is the first thing I'd add.
- **Aspect-ratio validation is too narrow.** Only 9:16, 16:9 and 1:1 are recognised, so
  four of the nine sample graphics (~4:5 portrait) are rejected on upload. Needs an
  `instagram_portrait` platform.
- **Time validation in the typo check is inert.** `_valid_time_tokens()` adds `time_label`
  unguarded, and older roster rows carry `""` — the empty string is a substring of
  everything, so every time passes. One `if` fixes it. (The matchup check's per-pairing
  time test is unaffected and does work.)
- **Design & Theme has no dedupe** and discards the model's `issue` category, so two
  findings describing the same problem at different severities render identically. It's
  also the one check where the model both finds and judges — and not coincidentally the
  noisiest.
- **Batch jobs can strand.** `asyncio.create_task` is fire-and-forget with no stored
  handle, so a restart mid-batch leaves the job at `processing` forever.
- **Thresholds are tuned to this asset pack.** New logos — especially thin stylised
  wordmarks — will need `PRESENT` recalibrated.
- **VLM boxes aren't pixel-perfect.** Mitigated by draggable markers and by using OpenCV
  where precision actually matters.

---

## What I'd change for production

| Concern | Now | Production |
|---|---|---|
| Database | SQLite (single file) | Postgres |
| Images | local disk + `StaticFiles` | object storage, `stored_path` becomes a key |
| Queue | in-process `asyncio` + semaphore | Celery/Redis or SQS with a worker pool |
| Migrations | `create_all` + a small helper | Alembic, versioned and reversible |
| Model cost | one model for every call | cheap-model-first cascade, escalate only ambiguous findings |
| Observability | per-check timing + confidence on `CheckRun` | tracing on top of what's already recorded |

**What wouldn't change** is the `Check` interface and the structured finding contract. New
checks and new models plug in without touching the API or the frontend — which is the point
of the design, and why switching three checks on mid-project required no migration and no
frontend work.
