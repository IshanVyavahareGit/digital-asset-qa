Things to do:
1. Read prompts
2. Schema design
2. Understand importance of confidence scoring compared to assigning direct verdict
3. How exactly is gemini able to do the box2d ocr, how does it work for all resolutions consistently
4. For production what changes will have to be made

# Esports Visual QA — Project Handbook

A manager uploads a tournament graphic. Five independent checks run against it, each
returning structured findings with coordinates. A pure function reduces those to
Pass / Needs Changes / Fail, and the findings are painted back onto the image as boxes
and pins that a human can override.

- **Backend** FastAPI, 3,139 lines across 29 modules
- **Frontend** Next.js 15 (App Router), TypeScript, TanStack Query, Framer Motion
- **Vision** Gemini (OCR + design review) and OpenCV (logo matching)
- **Store** SQLite in WAL mode, images on disk

Every number and every JSON example in this document was taken from a live run or read
out of the database. Nothing is invented.

---

## Contents

1. [The core idea](#1-the-core-idea)
2. [Architecture](#2-architecture)
3. [One upload, traced end to end](#3-one-upload-traced-end-to-end)
4. [The five checks — inputs and outputs](#4-the-five-checks--inputs-and-outputs)
5. [Sponsors, in depth](#5-sponsors-in-depth)
6. [Batch mode](#6-batch-mode)
7. [From finding to pixel — the frontend mapping](#7-from-finding-to-pixel--the-frontend-mapping)
8. [File map](#8-file-map)
9. [How to hold this in your head](#9-how-to-hold-this-in-your-head)
10. [Known gaps](#10-known-gaps)

---

## 1. The core idea

If you remember one sentence, make it this one — every design decision descends from it.

> **The LLM extracts. Python judges.**

Gemini is never asked "is this graphic correct?" It is asked to read text verbatim and
report where it found it. The decision about whether a name is misspelled, whether a
matchup is legitimate, or what the verdict should be is made by ordinary deterministic
Python you can unit-test and step through in a debugger.

This matters for three reasons that come up the moment anyone probes the design:

- **The model can't hide a bug.** The roster is never in the prompt, so the model
  physically cannot "helpfully" auto-correct a misspelled team name before you see it.
- **Findings are defensible.** Every finding traces to a comparison you can point at —
  a `difflib` ratio, a set membership test, an area fraction.
- **Failure is honest.** A check that cannot run reports `failed` and emits *zero*
  findings. It never guesses. And a graphic can't be certified Pass if part of the
  pipeline didn't run.

There is exactly one place this principle is *not* followed — the Design & Theme check,
where the model both finds and judges. That is also, not coincidentally, the check that
produces duplicate and debatable findings. Name it yourself rather than being caught by it.

---

## 2. Architecture

Four checks run concurrently. The fifth runs afterwards, because it consumes what the
first four located — it has no detector of its own.

```
  POST /graphics                          api/graphics.py — manager role required
        |
        v
  Ingestion                               services/evaluation.py
  - validate graphic_type + platform + aspect ratio
  - write bytes to data/uploads/{uuid}.png
  - read canvas W x H with PIL
        |
        v
  PHASE A — four checks, concurrently     pipeline/orchestrator.py (asyncio.gather)
  +---------------------------------------------------------------+
  |  Typo & Roster    Gemini OCR     -> findings + located elems   |
  |  Matchup          Gemini         -> findings                   |
  |  Sponsor Audit    OpenCV         -> findings + located elems   |
  |  Design & Theme   Gemini         -> findings                   |
  +---------------------------------------------------------------+
        |
        |  located elements pooled: handles, teams, times, CTAs, logos
        v
  PHASE B — Safe Zone                     checks/safe_zone.py
  - pure geometry, ~1 ms
  - tests the pooled elements against the platform's danger zones
        |
        v
  compute_verdict()                       pipeline/verdict.py (pure function)
  any critical -> Fail | any warning -> Needs Changes | else Pass
  guardrail: a would-be Pass is downgraded if any check failed
        |
        +--> SQLite          one short commit
        +--> ReviewOut JSON  typed, straight to the browser
```

**Why Safe Zone is separate.** The four analyzers are independent, so they run together
and the wall-clock cost is the slowest one, not the sum. Safe Zone cannot join them: it
has no detector, and only tests boxes that Typo and Sponsor already located. Running it
afterwards costs nothing measurable — it completes in about 1 ms.

### The uniform contract

Every check implements one interface in `checks/base.py`:

```python
class Check(ABC):
    check_type: CheckType
    async def run(self, ctx: CheckContext) -> CheckResult: ...
```

**Input — the same object for all five checks:**

```python
CheckContext(
    image_bytes = b'\x89PNG\r\n...',   # the raw upload
    mime_type   = "image/png",
    canvas_w    = 2418,                # read by PIL at ingestion
    canvas_h    = 1362,
    graphic_type= "bracket",           # drives Sponsor + Matchup
    platform    = "x_post",            # drives Safe Zone
    reference_images = [],             # optional, Tier 3 theme calibration
    located_elements = [],             # filled by the orchestrator before Phase B
)
```

**Output — the same object from all five checks:**

```python
CheckResult(
    check_type       = CheckType.typo_roster,
    status           = CheckStatus.ok,      # ok | low_confidence | failed
    findings         = [RawFinding, ...],   # may be empty
    detail           = "Read 79 text element(s).",
    confidence       = 0.9,
    usage            = Usage(input_tokens=1290, output_tokens=4095, calls=1),
    duration_ms      = 25005,               # filled in by _timed()
    located_elements = [LocatedElement, ...] # only Typo and Sponsor populate this
)
```

That uniformity is the whole trick: an LLM call, an OpenCV routine and pure arithmetic
are **indistinguishable** to the orchestrator. Adding a sixth check is a three-file
change — write the class, add an enum value, add it to `ANALYZERS`. The API and the
frontend don't change at all.

### Two safety nets

- `_timed()` wraps every check, records its duration, and converts *any* exception into
  an honest `failed` result. One crashing check cannot take down the request or invent data.
- `_pipeline_status()` rolls the five statuses into `ok` / `partial` / `failed`, and the
  verdict function refuses to certify a clean Pass when anything is worse than `ok`.

---

## 3. One upload, traced end to end

This is the walkthrough to have ready. Nine steps, each in one file.

| # | What happens | Where |
|---|---|---|
| 1 | `require_manager` decodes the JWT and checks the role. A designer gets 403 here. | `core/security.py` |
| 2 | Graphic type and platform validated against the enums; image bytes read. | `api/graphics.py` |
| 3 | Aspect ratio checked against the platform's expected shape. Wrong shape → 422, nothing runs. | `services/evaluation.py` |
| 4 | PIL reads canvas W×H; bytes written to `data/uploads/{uuid}.png`. **Metadata in DB, bytes on disk.** | `services/evaluation.py` |
| 5 | A `CheckContext` is built and `evaluate()` awaited. **No DB transaction is open during this.** | `pipeline/orchestrator.py` |
| 6 | Four analyzers via `asyncio.gather`; located elements pooled; Safe Zone runs on the pool. | `pipeline/orchestrator.py` |
| 7 | All findings plus pipeline health reduce to a verdict and a reasoning sentence. | `pipeline/verdict.py` |
| 8 | Graphic, Review, CheckRuns, Findings, UsageEvent written with **pre-generated UUIDs in one commit**. | `services/evaluation.py` |
| 9 | Serialized to `ReviewOut` and returned. | `api/serializers.py` |

### Why step 5 is emphasised — the bug worth telling

The first version flushed the Graphic row early, to get an id to attach children to. On
SQLite that flush takes a **write lock**, and it was being held across the entire ~20
second pipeline. Three concurrent batch items then blocked each other to the 30 second
lock timeout and the whole batch appeared frozen.

**The fix:** generate the UUIDs in Python up front, run the whole DB-free pipeline, then
write every row in one short commit. Children can reference parents because the ids
already exist. WAL mode was enabled so the dashboard can read while a batch writes, and
`busy_timeout` set to 30s so contention waits instead of erroring.

### Coordinates — the other thing you'll be asked

```
Gemini      box_2d = [ymin, xmin, ymax, xmax]     each axis 0-1000
   |  divide by 1000
   v
SQLite      bbox_x, bbox_y, bbox_w, bbox_h        0-1 fractions of canvas
            + canvas_w, canvas_h
   |  multiply by 100
   v
Browser     left: 75.38%   top: 5.88%             CSS percent over the <img>
```

Gemini normalizes **each axis independently** to 0–1000, so aspect ratio is irrelevant.
Dividing by 1000 gives an aspect-independent fraction; the frontend positions markers
purely in `%`. A 1080×1920 story and a 1920×1080 thumbnail use identical logic, and boxes
stay aligned when you resize the browser because nothing is recalculated.

Converted in `services/gemini.py:box2d_to_bbox`, which also guards against the malformed
three-value box Gemini occasionally emits.

---

## 4. The five checks — inputs and outputs

Right tool per job. Two checks read, one matches pixels, one measures, one critiques.

| Check | Engine | Question it answers | Who decides |
|---|---|---|---|
| **Typo & Roster** | Gemini OCR | Is every name spelled the way the roster spells it? | Python (`difflib`) |
| **Matchup** | Gemini | Are these two teams actually scheduled to play? | Python (set membership) |
| **Sponsor Audit** | OpenCV | Is each required logo present, big enough, visible? | Python (thresholds) |
| **Safe Zone** | Geometry | Will platform UI cover anything important? | Python (area overlap) |
| **Design & Theme** | Gemini | Does this look like it belongs to the brand? | **the model** |

Each check below follows the same four beats: what goes **in**, what the engine gives
**back**, what Python **decides**, and the **finding** that reaches the browser.

---

### 4.1 Typo & Roster

**IN** — the image, plus `roster.json` loaded separately by Python (never sent to Gemini).

The prompt, in essence: *extract every distinct line of text; return the exact characters
verbatim, never correct spelling; classify each as handle / team / time / cta / other;
give a box_2d as [ymin, xmin, ymax, xmax] on a 0–1000 scale.*

**OUT of Gemini** — schema-bound JSON (`TextExtraction`), abridged from a real 79-element run:

```json
{
  "readable": true,
  "elements": [
    { "text": "GANGAN GALAXY", "kind": "team",  "box_2d": [325,  60, 350, 205] },
    { "text": "GGEZ",          "kind": "team",  "box_2d": [352,  60, 377, 140] },
    { "text": "S8UL",          "kind": "team",  "box_2d": [598,  62, 620, 140] },
    { "text": "3:00 PM",       "kind": "time",  "box_2d": [612, 470, 634, 560] },
    { "text": "UPPER BRACKET", "kind": "other", "box_2d": [205,  60, 222, 195] }
  ]
}
```

**Python decides** — for each element, case-insensitively:

| Text | Compared against | Outcome |
|---|---|---|
| `GANGAN GALAXY` | exact roster name | no finding |
| `S8UL` | matches the team **tag** | no finding |
| `ALLENTOWNN` | difflib ratio **0.947** vs `Allentown` | **critical** — "did you mean Allentown?" |
| `HARISBURG` | difflib ratio **0.947** vs `Harrisburg` | **critical** |
| `@YOURSPORTEVENT` | nothing above cutoff **0.6** | **warning** — unrecognized |

Elements of kind `handle` / `team` / `time` / `cta` are *also* appended to
`located_elements` for Safe Zone — 46 of the 79 on that bracket.

**CheckResult:**

```
status=ok  detail="Read 79 text element(s)."  confidence=0.9
tokens=1290 in / 4095 out   duration=25005 ms
```

**Finding produced** (real row from `roster_update_complex_1.png`):

```json
{
  "check_type": "typo_roster",
  "severity": "warning",
  "message": "Unrecognized player handle: '@YOURSPORTEVENT' is not in the roster.",
  "suggested_fix": "Verify '@YOURSPORTEVENT' against the official roster.",
  "bbox": { "x": 0.6079, "y": 0.9053, "w": 0.2000, "h": 0.0500 },
  "is_pin": false, "confidence": 0.5, "source": "ai", "status": "open"
}
```

The severity split is deliberate. A *close* match is almost certainly a typo and you can
name the correction, so it's critical. *No* match might be a legitimately new team, so it
only asks a human to verify. `confidence` is the real `difflib` ratio, not an invented number.

---

### 4.2 Matchup

**IN** — the image, plus `scheduled_pairings()` built from `roster.json`. Skipped entirely
(no Gemini call at all) unless `graphic_type` is `match_announcement` or `bracket`.

**OUT of Gemini** — `MatchupExtraction`:

```json
{
  "has_matchups": true,
  "matchups": [
    { "team_a": "GANGAN GALAXY", "team_b": "GGEZ",      "time": "", "box_2d": [325,  60, 375, 215] },
    { "team_a": "S8UL",          "team_b": "LAST HOPE", "time": "", "box_2d": [444, 285, 495, 465] },
    { "team_a": "Winner of Upper Bracket Final",
      "team_b": "TBD",                                  "time": "", "box_2d": [455, 800, 505, 980] }
  ]
}
```

**Python decides**, per pairing:

```
resolve_team("S8UL")      -> "S8UL Esports"      canonical
resolve_team("LAST HOPE") -> "Last Hope"         canonical
frozenset({"S8UL Esports","Last Hope"}) in scheduled_pairings ?  -> NO  -> CRITICAL

resolve_team("Winner of Upper Bracket Final") -> None  -> SKIP ENTIRELY
```

Two behaviours worth knowing. If either side fails to resolve the pairing is **skipped** —
an unknown name is a spelling problem and Typo already owns it, so nothing is double-flagged,
and bracket placeholders self-skip. And a `reported` set dedupes, because a bracket shows
the same pairing in every round a team survives.

**CheckResult:** `status=ok  detail="Validated 15 matchup(s)."  confidence=0.85  1240 in / 1201 out`

**Findings produced** (two real rows from `bracket_1_wrong.png`):

```json
{
  "check_type": "matchup", "severity": "critical",
  "message": "'S8UL Esports' vs 'Last Hope' is not a scheduled match in the roster.",
  "suggested_fix": "Verify the matchup — 'S8UL Esports' and 'Last Hope' are not scheduled to play each other.",
  "bbox": { "x": 0.2850, "y": 0.4440, "w": 0.1800, "h": 0.0510 },
  "is_pin": false, "confidence": 0.9, "source": "ai", "status": "open"
}
```

**Dedupe, demonstrated.** `bracket_2_wrong.png` swapped Rainier for Allentown at seeds 7
and 15, so "Allentown vs Turner Point" appears three times. The first hit produces one
critical; the other two are skipped. Detail line says *"Validated 15 matchup(s)"* — one
finding, not three.

---

### 4.3 Sponsor Audit

**IN** — the image, `sponsor_manifest.json`, and the logo PNGs from `assets/sponsors/`.
No LLM involved at all.

**OUT of OpenCV** — for each mandatory sponsor, a best score plus a pixel box:

```
Predator  best score 0.793  at scale 0.10  box (1841, 1204, 32, 9)
Intel     best score 0.636  at scale 0.10  box (  12, 1150, 32, 9)
```

**Python decides** — three independent gates, in order (full detail in section 5).

**CheckResult:** `status=ok  detail="Checked 2 mandatory sponsor(s)."  confidence=0.716  0 tokens`

**Findings produced** (real rows from `bracket_2.png`):

```json
{
  "check_type": "sponsor_audit", "severity": "critical",
  "message": "Mandatory sponsor 'Predator' is missing from this graphic.",
  "suggested_fix": "Add the Predator logo to the sponsor row before publishing.",
  "bbox": { "x": 0.5009, "y": 0.9007, "w": 0.0, "h": 0.0 },
  "is_pin": true, "confidence": 0.205, "source": "ai", "status": "open"
}
```

Two details to notice. The box is **zero-sized with `is_pin: true`** — you cannot draw a
rectangle around something that isn't there, so it drops a marker at the bottom-centre
sponsor row instead. And `confidence` here is `1.0 − score` (0.205 from a score of 0.795),
because the claim being made is *absence*, so the confidence is how sure we are it's absent.

---

### 4.4 Safe Zone

**IN** — no image at all. Just `ctx.located_elements` (pooled from Phase A) and the
platform's zone spec:

```python
# from safe_zones.json, for platform "instagram_story"
canvas = { "w": 1080, "h": 1920 }
danger_zones = [
  { "label": "top UI (username, camera icons)", "x": 0, "y": 0,    "w": 1080, "h": 250 },
  { "label": "bottom UI (caption, CTA, reply bar)", "x": 0, "y": 1600, "w": 1080, "h": 320 },
  { "label": "right rail (like/share/comment)", "x": 960, "y": 600, "w": 120, "h": 1000 },
]
```

Zones are authored in **pixels on a reference canvas** and divided by that canvas to become
0–1 fractions — which is what makes the test resolution-independent.

**Python decides** — worked example. Handle `Zyol` located at `(0.30, 0.04, 0.25, 0.05)`,
top danger zone normalized to y `0 → 0.130`:

```
x overlap    = 0.25                                   (element fully inside horizontally)
y overlap    = min(0.09, 0.130) - max(0.04, 0) = 0.05
intersection = 0.25 x 0.05 = 0.0125
element area = 0.25 x 0.05 = 0.0125
fraction     = 1.00   ->  100% of the element sits in the zone
```

| Fraction of the element inside a zone | Result |
|---|---|
| under `0.12` | ignored — a pixel of overlap isn't a problem |
| `0.12` – `0.45` | **warning** |
| `0.45` and up | **critical** |

**Finding it would produce:**

```json
{
  "check_type": "safe_zone", "severity": "critical",
  "message": "Handle 'Zyol' sits inside the 'top UI (username, camera icons)' danger zone (100% overlap).",
  "suggested_fix": "Move 'Zyol' out of the top UI area.",
  "bbox": { "x": 0.30, "y": 0.04, "w": 0.25, "h": 0.05 },
  "is_pin": false, "confidence": 1.0, "source": "ai", "status": "open"
}
```

Note the box is the **element's own box**, reused — Safe Zone never computes geometry of
its own, it just re-reports what Typo or Sponsor located.

> This is the one worked example in the document rather than a captured row: across all
> nine test graphics Safe Zone has produced **zero** findings, because nothing in them
> intrudes. Real result on `bracket_2.png`: `ok`, *"Tested 46 critical element(s) against
> 4 danger zone(s)"*, 0 ms, no findings.

**Its honest-failure case is distinctive.** If nothing was located — because OCR failed
upstream — it returns `low_confidence` (not `ok`, not `failed`) with confidence 0.3 and the
detail *"No critical elements were located, so safe-zones could not be fully verified."*
The check is only as good as its inputs and says so.

---

### 4.5 Design & Theme

**IN** — the image plus `brand_guide.json` injected into the prompt as JSON:

```json
{ "tone": ["dark","neon","high-contrast","futuristic"],
  "palette": { "background":"#0A0E1A", "primary":"#00E5FF", "secondary":"#FF2E97", ... },
  "approved_fonts": ["Rajdhani","Orbitron","Chakra Petch"],
  "rules": ["Backgrounds must be dark (near-black navy), never light.", ...] }
```

Two exemptions are hard-coded into the prompt, both learned from real false positives:
brand neon on dark navy is the *intended* look, and sponsor logos are allowed their own colours.

**OUT of Gemini** — `DesignReview`:

```json
{
  "on_brand": false,
  "findings": [
    { "issue": "off_palette",
      "severity": "warning",
      "message": "The mascot illustration uses brown, orange, and light blue tones that deviate from the neon cyan, magenta, and purple palette.",
      "suggested_fix": "Recolor the mascot illustration to align with the neon brand palette.",
      "box_2d": [59, 754, 326, 924] }
  ]
}
```

**Python decides — almost nothing.** It maps the severity string to the enum and converts
the box. The category, wording and severity all come straight from the model:

```
box_2d [59, 754, 326, 924]
  y = 59/1000            = 0.059
  x = 754/1000           = 0.754
  h = (326 - 59)/1000    = 0.267
  w = (924 - 754)/1000   = 0.170
```

**CheckResult:** `status=ok  detail="Brand deviations found."  confidence=0.8 (hard-coded)  1675 in / 132 out`

**Finding produced** — and this is the row worth studying, because it has been round-tripped
through the UI:

```json
{
  "check_type": "design_theme", "severity": "warning",
  "message": "The mascot illustration uses brown, orange, and light blue tones ...",
  "bbox": { "x": 0.753805711447203, "y": 0.05880513790327111, "w": 0.17, "h": 0.267 },
  "is_pin": false, "confidence": 0.8, "source": "ai", "status": "open"
}
```

Look at the precision. `w` and `h` are exactly `0.17` and `0.267` — the clean three-decimal
values that came out of `box_2d`. But `x` and `y` carry full float precision, and
`updated_at` is a week later than `created_at`. **A manager dragged this marker.** A move
rewrites `x` and `y` from the pointer position and leaves `w`/`h` untouched, which is
exactly the fingerprint in this row. Section 7 follows that loop in both directions.

**Volunteer its weakness.** Unlike the other four, there is no dedupe and no Python
judgement. On `bracket_2_wrong.png` it returned two findings — one **warning**, one
**info** — describing the same problem at both severities, both boxed at the full canvas
`(0,0,1,1)`. The model classified them as different categories (`off_palette` vs
`off_theme`), but the `issue` field is collected and then **never read**, so the UI renders
both as a generic "Design & Theme" and they look like duplicates.

---

## 5. Sponsors, in depth

### 5.1 The four sponsors

All four were cropped out of the real source graphics by `assets/extract_sponsor_logos.py`
— they are the actual marks on the Predator League artwork, not stand-ins.

| Logo | File | Size | % of canvas | Mandatory? |
|---|---|---|---|---|
| Predator | `predator.png` | 320×90 | 1.89% | **yes** |
| Intel | `intel.png` | 223×98 | 1.43% | **yes** |
| Intel Core Ultra | `intel_core.png` | 286×121 | 2.27% | registered only |
| Valorant | `valorant.png` | 309×41 | 0.83% | registered only |

Valorant is left optional on purpose: at 0.83% it sits under the 1% visibility floor, so
promoting it into the mandatory list gives you a ready-made *too small* test case without
touching any code.

### 5.2 Yes — it depends on the graphic type

`mandatory_by_type` in `sponsor_manifest.json` is the entire mapping:

```json
"mandatory_by_type": {
  "match_announcement": ["predator", "intel"],
  "bracket":            ["predator", "intel"],
  "roster_update":      []
}
```

`roster_update` is empty **deliberately** — the three roster graphics are three unrelated
tournaments (Zeus Esports/PUBG, Team Raise/BGMI) sharing no sponsor at all, so anything
mandatory there would be a guaranteed false "missing".

Be precise about this, because **two different fields drive different checks**:

| Check | Varies by | How |
|---|---|---|
| Sponsor Audit | **graphic type** | `mandatory_by_type` picks which logos are required |
| Matchup | **graphic type** | only `match_announcement` and `bracket` have pairings; a roster update skips the Gemini call entirely |
| Safe Zone | **platform** | each platform has its own danger-zone rectangles |
| Typo & Roster | neither | runs identically on everything |
| Design & Theme | neither | runs identically on everything |

### 5.3 How the matching works

```
  template (alpha composited, opaque)
        |
        v
  resize across 17 scales:  0.10x  0.12  0.14  0.18  0.22  0.28  0.36
                            0.45   0.55  0.62  0.70  0.76  0.80  0.84
                            0.90   1.00  1.10x
        |
        v
  cv2.matchTemplate(TM_CCOEFF_NORMED) at each scale, keep the single best
        |
        v
  +------------------------+
  |   score >= 0.88 ?      |---- no ---->  CRITICAL — sponsor missing
  +-----------+------------+               pin at (0.5, 0.9), w=h=0
              | yes                        confidence = 1.0 - score
              v
  +------------------------+
  | area >= 1% of canvas ? |---- no ---->  WARNING — present but too small
  +-----------+------------+               box = the matched region
              | yes
              v
  +------------------------+
  |  contrast >= 22.0 ?    |---- no ---->  WARNING — faint / low contrast
  +-----------+------------+               box = the matched region
              | yes
              v
        no finding
```

Three **independent** gates, not one. Presence, size and visibility are separate questions
with separate thresholds, and the order matters: you cannot ask whether a logo is too small
until you know it is there at all.

The check also runs inside `asyncio.to_thread` — OpenCV is CPU-bound and would otherwise
stall the three concurrent Gemini calls.

### 5.4 Why contrast is measured separately — the best detail to volunteer

`TM_CCOEFF_NORMED` is **invariant to brightness and contrast**. Normally that's a feature.
Here it means a logo watermarked down to 10% opacity — effectively invisible — still scored
**0.967** in testing.

The match score fundamentally cannot tell you whether a human can see the logo. So
visibility is judged by the region's own internal contrast: grayscale standard deviation.
The faint logo measured **5.1** against a floor of 22.0 and was correctly flagged. If anyone
asks why you didn't just threshold the match score, that's the answer with a number attached.

### 5.5 Two things the real assets forced

**The pyramid had to reach past 1.0.** Logos cropped from a source graphic appear at exactly
the size they were cropped at — a template-to-graphic ratio of 1.0. The original pyramid
stopped at 0.84 and only ever downscales, so those logos were *structurally impossible* to
find. Extended to 1.10; upscaling the crops instead would only have added resampling blur.

**Transparency is a trap.** `cv2.IMREAD_COLOR` discards the alpha channel, which leaves
every anti-aliased edge pixel at full intensity instead of its blended value — and those
edges are what drives correlation. Measured cost: Predator fell from 0.974 to 0.899 and the
safety margin halved. `sponsor_logo_bgr` now composites the alpha properly, which restores
it. The fill colour turned out not to matter — black, brand navy and dark grey all scored
identically, which proves the loss was in the edges, not the transparent regions.

### 5.6 Measured results across all nine graphics

| Graphic | Type | Predator | Intel | Outcome |
|---|---|---|---|---|
| `bracket_1` | bracket | 0.997 | 0.996 | clean |
| `bracket_1_wrong` | bracket | 0.972 | 0.988 | clean |
| `bracket_2` | bracket | 0.793 | 0.636 | **2 critical** |
| `bracket_2_wrong` | bracket | 0.711 | 0.555 | **2 critical** |
| `match_announcement_2` | match ann. | 0.988 | 0.989 | clean |
| `match_announcement_2_wrong` | match ann. | 0.986 | 0.989 | clean |
| `roster_update` ×3 | roster | — | — | no mandatory sponsors |

The two `bracket_2` files are the Owls Invitational, a different tournament that genuinely
carries neither logo — two criticals each is the correct answer, not a bug.

Every true positive lands at **0.972 or above**; the highest spurious match is **0.793**.
The threshold sits at **0.88**, almost exactly centred in that gap.

**Why 0.88 and not the original 0.70.** At 0.70, the pyramid's smallest scales — a 320×90
template shrunk to about 32×9 pixels — threw spurious matches up to 0.795 on graphics with
no Predator logo at all. The check reported "present but too small" for a logo that wasn't
there. Retuning to 0.88 turned that into the correct "missing".

---

## 6. Batch mode

```
POST /batch (12 files)
   |
   +- read every file into memory   (UploadFile is only valid during the request)
   +- validate all of them          (one bad file rejects the WHOLE batch, 422)
   +- create BatchJob row           (queued, total=12)
   +- asyncio.create_task(...)  --------------------+
   |                                                |
   v                                                v
HTTP 200 returns NOW                        background worker
reviews list still empty                    Semaphore(3)
                                     +---------------------------------+
                                     | slot 1  item -> pipeline ~20s   |
                                     |                -> short commit  |
                                     | slot 2  item -> pipeline ~20s   |
                                     | slot 3  item -> pipeline ~20s   |
                                     +---------------------------------+
                                     items 4..12 wait for a free slot
                                     each item gets its OWN DB session
                                     one failure cannot sink the batch
                                                    |
client polls GET /batch/{id} every 1.5s ------------+
   +- status flips to "done" -> refetchInterval returns false -> polling stops itself
```

**The response beats the work.** Files must be read into memory during the request because
FastAPI's `UploadFile` objects are only valid while it is alive — the actual processing
happens after the response is sent.

**The semaphore caps concurrency at 3** because every item makes three Gemini calls, and
twelve unbounded items would fire thirty-six simultaneous requests and hit rate limits.

**Input** — three parallel arrays, one entry per file:

```
files          = [bracket_1.png, bracket_2.png, ...]
graphic_types  = ["bracket", "bracket", ...]
platforms      = ["x_post", "x_post", ...]
```

**Output** — polled repeatedly, the same shape each time:

```json
{ "id": "8f3c...", "status": "processing", "total": 12, "completed": 5, "failed": 1,
  "reviews": [ /* ReviewSummary objects, sorted fail -> needs_changes -> pass */ ] }
```

### A twelve-file batch, minute by minute

| t | What happens |
|---|---|
| 0s | All 12 read and validated. `BatchJob` created as `queued, total=12`. Response returns instantly with an empty reviews list. |
| 0s | Frontend navigates to `/batch/{id}` and starts polling. Worker sets `processing`; items 1–3 take the three slots. |
| ~20s | Item 1 finishes, `completed=1`, item 4 takes the freed slot. Progress bar animates to 8%, first card appears. |
| ~45s | Item 7 is corrupt → exception caught → `completed=5, failed=1`. Header shows "1 failed". Batch continues. |
| ~80s | All settle, status becomes `done`. Next poll stops polling and refreshes the dashboard once. |

### Limitations — the interesting part

- `asyncio.create_task` is fire-and-forget with no stored handle, so a **server restart
  mid-batch strands the job at `processing` forever**, with no recovery.
- `completed` actually counts *attempted* — it increments on failure too.
- Validation is all-or-nothing: one bad file rejects the entire upload before any work starts.
- `_status` re-queries every review in the table on every 1.5s poll and filters in Python.
- The UI forces one type/platform for all files, though the API supports per-file values.

The production answer to all of it is a real queue — Celery/Redis or SQS with a worker pool.
The pipeline is already stateless per graphic, so it ports directly.

---

## 7. From finding to pixel — the frontend mapping

The frontend does **no interpretation**. It never parses text, never infers severity from
wording, never computes a verdict. It receives typed JSON and positions it.

### 7.1 The payload

One request — `GET /reviews/{id}` — returns everything the workspace needs:

```json
{
  "id": "1e1b69aa...",
  "verdict": "fail",
  "pipeline_status": "ok",
  "reasoning": "Found 3 critical issues, 1 warning.",
  "graphic": {
    "filename": "bracket_2.png",
    "graphic_type": "bracket",
    "platform": "x_post",
    "canvas_w": 2418,
    "canvas_h": 1362,
    "version": 1,
    "image_url": "/static/8db5fbb2a84f456fae5b9b50f74ee8aa.png"
  },
  "findings": [ /* see below */ ],
  "check_runs": [
    { "check_type": "typo_roster",   "status": "ok",     "detail": "Read 79 text element(s).",
      "confidence": 0.9,  "duration_ms": 25005 },
    { "check_type": "sponsor_audit", "status": "failed", "detail": "Sponsor logo assets missing...",
      "confidence": null, "duration_ms": 526 }
  ]
}
```

### 7.2 Where every field lands

| JSON field | Rendered as | Component |
|---|---|---|
| `verdict` | the Pass / Needs Changes / Fail pill, top right | `VerdictBadge.tsx` |
| `reasoning` | the "Verdict reasoning" panel | `reviews/[id]/page.tsx` |
| `graphic.image_url` | the `<img>` the markers sit on | `ImageOverlay.tsx` |
| `graphic.canvas_w/h` | the "2418×1362" caption in the header | `reviews/[id]/page.tsx` |
| `check_runs[].status` | green tick / amber ? / red ! per check | `CheckHealth.tsx` |
| `check_runs[].detail` | the grey text beside it (truncated, full text on hover) | `CheckHealth.tsx` |
| `check_runs[].duration_ms` | the `17.1s` on the right | `CheckHealth.tsx` |
| `findings[].bbox` | the box or pin position, in CSS `%` | `ImageOverlay.tsx` |
| `findings[].severity` | marker colour + the coloured pill in the list | `utils.ts:SEVERITY_META` |
| `findings[].source` | `manager` overrides the colour to purple | `ImageOverlay.tsx` |
| `findings[].check_type` | the "Matchup" / "Sponsor Audit" label | `utils.ts:CHECK_LABEL` |
| `findings[].message` | the finding text in the side panel | `FindingsPanel.tsx` |
| `findings[].suggested_fix` | the wand-icon line beneath it | `FindingsPanel.tsx` |
| `findings[].confidence` | the `90%` on the right of the row | `FindingsPanel.tsx` |
| `findings[].status` | `dismissed` greys and strikes the row | `FindingsPanel.tsx` |

### 7.3 bbox → CSS, with real numbers

Take the real design_theme finding on `bracket_2.png`:

```json
"bbox": { "x": 0.7538, "y": 0.0588, "w": 0.17, "h": 0.267 }
```

`ImageOverlay` multiplies by 100 and writes percentages — nothing else:

```jsx
style={{
  left:   `${g.x * 100}%`,   // 75.38%
  top:    `${g.y * 100}%`,   //  5.88%
  width:  `${g.w * 100}%`,   // 17.00%
  height: `${g.h * 100}%`,   // 26.70%
}}
```

On a browser where the image happens to render 737 × 415 CSS pixels:

```
left   = 0.7538 x 737 = 555.5 px
top    = 0.0588 x 415 =  24.4 px
width  = 0.1700 x 737 = 125.3 px
height = 0.2670 x 415 = 110.8 px
```

Resize the window and the *percentages never change* — the browser recomputes the pixels.
That is the whole reason boxes stay glued to the artwork, and why the same code handles a
2418×1362 bracket and a 1080×1920 story with no branching.

### 7.4 Box vs pin

```javascript
const isPin = (f) => f.is_pin || !f.bbox || (f.bbox.w < 0.005 && f.bbox.h < 0.005);
```

A **box** is drawn for a finding with real extent — a misspelled team name, an off-palette
region. A **pin** is drawn for a finding with no extent, which in practice means *"this
thing is missing"*: the sponsor check emits `{x: 0.5, y: 0.9, w: 0, h: 0}` with
`is_pin: true`, dropping a teardrop marker at the bottom-centre sponsor row. You can't
box what isn't there.

### 7.5 Which colour, and why

```
severity critical  -> #FF4D5E   red
severity warning   -> #FFB020   amber
severity info      -> #38BDF8   blue
source   manager   -> #A855F7   purple   (overrides severity)
```

Manager-added findings are purple regardless of severity, so at a glance you can tell what
the AI found from what a human added. Manager findings also carry `confidence: null`, so the
percentage badge simply doesn't render for them — visible in the three real manager rows in
this database, all with `source: "manager"` and no confidence.

### 7.6 Stacking, so a big finding can't bury a small one

Design & Theme regularly returns findings boxed at the entire canvas `(0,0,1,1)`. Two rules
keep those from swallowing everything underneath:

- **z-index is derived from area** — `10 + (1 − area) × 10`. A full-canvas box gets 10, a
  tiny one gets 20, so smaller markers always sit on top.
- **the interior is click-through** — a marker's container is `pointer-events: none`, and
  only the label chip, a 12px border band and eight resize grips accept input. Whatever sits
  inside a big box stays reachable.

### 7.7 The override loop, both directions

This is where the design_theme row from section 4.5 comes from.

```
manager drags a marker
   |
   v
optimistic cache write            useQueryClient().setQueryData(...)
   marker stays where dropped, no flash back
   |
   v
PATCH /findings/{id}  { "bbox": { "x": 0.7538057..., "y": 0.0588051..., "w": 0.17, "h": 0.267 } }
   |
   v
api/findings.py  writes bbox_x/y/w/h  ->  _recompute()  ->  compute_verdict()
   |
   v
returns the WHOLE updated ReviewOut
   |
   v
setQueryData(review) + invalidate the dashboard list
   verdict badge, counts and cards all update together
```

Three consequences worth stating out loud:

- **The verdict is recomputed on every override.** Dismiss the last critical and the badge
  flips from Fail to Needs Changes immediately, because `compute_verdict` is pure and gets
  re-run rather than being stored as a decision.
- **A move is not an edit.** Repositioning writes coordinates but deliberately does *not*
  flip `status` to `edited` — only a change to text or severity does that.
- **AI findings can be dismissed but never deleted.** `DELETE /findings/{id}` rejects
  anything with `source: "ai"`, so the audit trail of what the AI reported stays intact.
  Only manager-added findings can be removed.

### 7.8 Role gating

`canEdit = user.role === "manager"` is computed once and threaded down. For a designer the
overrides, the drag handles and the resize grips are simply never rendered — the same page
becomes read-only, without a second code path.

---

## 8. File map

Files marked **★** are the ones to know cold — if someone opens the repo and starts
clicking, it will be those.

```
backend/app/
├── main.py                app + CORS + static mount + routers. A table of
│                          contents, no logic.
├── schemas.py             the typed contract with the frontend.
│                          BBox, FindingOut, CheckRunOut, ReviewOut.
│
├── api/                   THIN HTTP ONLY — validate, delegate, serialize
│   ├── auth.py            login, /me
│   ├── graphics.py        upload + evaluate, delete
│   ├── reviews.py         list (collapses version lineages), get, versions
│   ├── findings.py        the HITL overrides — dismiss, edit, add, reposition
│   ├── batch.py           batch upload + background worker + polling
│   ├── recheck.py         upload a revision, diff against the original
│   ├── references.py      reference graphics (built, not wired to the UI)
│   └── serializers.py     ORM -> API, so every route returns the same shape
│
├── pipeline/              ORCHESTRATION AND PURE REDUCTION
│   ├── orchestrator.py  ★ the parallel fan-out, ANALYZERS / COMPOSER, _timed
│   ├── verdict.py       ★ the 3-line verdict rule + failed-pipeline guardrail
│   └── diff.py            resolved / persisting / new, by message or IoU 0.4
│
├── checks/                ONE MODULE PER CHECK, ALL THE SAME INTERFACE
│   ├── base.py          ★ Check, CheckContext, CheckResult, RawFinding
│   ├── typo_roster.py     Gemini extraction + difflib cross-reference
│   ├── matchup.py         pairing extraction + frozenset membership + dedupe
│   ├── sponsor_audit.py   OpenCV pyramid, PRESENT / CONTRAST_MIN / SCALES
│   ├── safe_zone.py       overlap arithmetic, OVERLAP_FLAG / OVERLAP_CRITICAL
│   └── design_theme.py    brand-guide prompt + structured design review
│
├── services/              THE WORK BETWEEN HTTP AND THE CHECKS
│   ├── evaluation.py    ★ DB-free pipeline, then ONE commit. The batch-lock fix.
│   ├── gemini.py        ★ response_schema, retry, box2d_to_bbox, pricing
│   └── assets.py          the only gateway to assets/ — roster, sponsors, zones
│
├── db/
│   ├── models.py          User, Graphic, Review, Finding, CheckRun,
│   │                      UsageEvent, BatchJob
│   └── session.py         engine, WAL + busy_timeout pragmas, tiny migration
│
└── core/
    ├── enums.py         ★ the shared vocabulary — roles, types, severities
    ├── config.py          one typed settings object; nothing else reads env
    └── security.py        bcrypt, JWT, require_manager, seeded demo users

frontend/
├── app/                   ROUTES
│   └── login · dashboard · reviews/[id] · reviews/[id]/recheck · batch/[id]
├── components/
│   ├── ImageOverlay.tsx ★ the centrepiece — % markers, move, resize,
│   │                      click-through interiors, 8 resize grips
│   ├── FindingsPanel.tsx  the side list, hover-synced with the overlay
│   ├── CheckHealth.tsx    per-check validated / could-not-evaluate
│   └── UploadDropzone · BatchUpload · ReviewCard · VerdictBadge
│      · VersionTimeline
└── lib/
    ├── types.ts           mirrors schemas.py exactly — no regex parsing
    ├── api.ts             one place owns base URL, auth header, error shape
    └── hooks.ts         ★ TanStack Query cache keys + useReviewSync

assets/                    SWAP THESE FILES, NOT CODE, TO CHANGE TOURNAMENT
├── roster.json            teams, tags, aliases, players, 29 scheduled matches
├── sponsor_manifest.json  sponsors + mandatory_by_type + visibility rules
├── brand_guide.json       palette, fonts, tone, rules -> injected into prompt
├── safe_zones.json        danger-zone rectangles per platform
├── sponsors/              the four logo templates
├── extract_sponsor_logos.py
└── typo-check/            nine test graphics, each with a _wrong variant
```

---

## 9. How to hold this in your head

Don't memorise files. Memorise one sentence, one ladder, one mnemonic and four numbers —
then derive the rest out loud.

### The ladder — say it in this order, every time

> **api** takes the request → **services** do the work → **pipeline** fans it out →
> **checks** judge → **db** stores it.

Five rungs, and every backend file belongs to exactly one. If you're asked where something
lives, walk the ladder aloud instead of guessing a filename — you'll land on the right
directory every time, and it demonstrates the structure is intentional.

### The mnemonic — five checks, four engines

> **Two readers, one matcher, one ruler, one critic.**

| | Checks | Why |
|---|---|---|
| **Readers** | Typo & Roster, Matchup | Gemini reads; Python decides. Spelling and relationships. |
| **Matcher** | Sponsor Audit | OpenCV. Pixel-exact, no AI, because you have the real logos. |
| **Ruler** | Safe Zone | Pure arithmetic. Overlap as a fraction of the element's own area. |
| **Critic** | Design & Theme | The only one where the model judges — and the only one producing noisy findings. |

That last row is the payoff. The mnemonic doesn't just list the checks, it encodes the
architecture's central claim *and* its one honest exception. Deliver it that way and the
follow-up question you get is the one you already have an answer for.

### The data shape — one sentence covers the whole frontend

> Everything is a **Finding**: a box in 0–1 fractions, a severity, a message, a source.
> The browser multiplies by 100 and paints it.

If you can say that, you have explained the overlay, the side panel, the colours and the
override loop in one breath — they are all the same object rendered four ways.

### Four numbers worth having ready

| | Value | Why it matters |
|---|---|---|
| Coordinates | `1000 → 1 → %` | Gemini's per-axis 0–1000, stored as 0–1 fractions, rendered as CSS percent. |
| Sponsor threshold | `0.88` | True positives 0.972+, spurious matches peak at 0.793. Centred in the gap. |
| Batch concurrency | `3` | Three Gemini calls per item; twelve unbounded would be thirty-six requests. |
| Fuzzy cutoff | `0.6` | Lower flags more typos and more false positives. Know the trade-off, not just the value. |

### Three stories to have loaded

1. **The batch lock bug.** An early flush held a SQLite write lock across the whole
   pipeline and froze concurrent items. Fixed with pre-generated UUIDs and a single commit.
   This is the strongest one — it shows debugging, not just building.
2. **The invisible logo.** A logo at 10% opacity still scored 0.967, because the matcher is
   contrast-invariant. That's why visibility is a separate grayscale-std test.
3. **The impossible template.** Logos cropped from a graphic appear at ratio 1.0, but the
   scale pyramid only downscaled to 0.84 — they could never be found. Extending the pyramid
   beat upscaling the crops, which would have added blur.

### If you go blank

Fall back to the trace in section 3 and narrate an upload from the top. Nine steps, each in
one file. It's nearly impossible to get lost, it naturally surfaces the interesting
decisions, and it buys you time to recover.

---

## 10. Known gaps

Say these before you're asked. Naming your own limitations reads as judgement; being caught
by them reads as the opposite.

| Gap | What's actually true |
|---|---|
| **Time validation is dead** | `_valid_time_tokens()` adds `time_label` unguarded, and older roster rows have `""`. The empty string is a substring of everything, so every time passes — even `"total garbage"`. One `if` fixes it. The matchup check's per-pairing time test is unaffected and does work. |
| **Four graphics can't be uploaded** | `bracket_1`, `bracket_1_wrong`, `match_announcement_2`, `match_announcement_2_wrong` are ~0.80 aspect (4:5 portrait) and match no platform, so they 422. These are the only ones containing the sponsor logos, so the clean sponsor path is currently verifiable only offline. Adding an `instagram_portrait` platform would unblock it. |
| **Design & Theme duplicates** | No dedupe, and the `issue` category is collected then discarded, so distinct findings render identically. |
| **Brand guide mismatch** | `brand_guide.json` describes the "Neon Circuit Championship" while the graphics are Owls Invitational / Predator League / Zeus / Team Raise. The check is correct against the wrong spec. |
| **Roster players mostly empty** | Only three teams list handles, so handles on other graphics flag as unrecognized. Honest behaviour, incomplete data. |
| **Loose time matching** | Bidirectional substring: `1:00pm` matches inside `11:00pm`. |
| **Safe Zone never fires** | Across all nine test graphics it has produced zero findings. Correct, but untested against a real intrusion. |
| **No tests** | The pure functions — fuzzy matcher, `scheduled_pairings`, `compute_verdict`, overlap — are all trivially testable and none are tested yet. |
| **Thresholds tuned to this pack** | New logos, especially thin stylised wordmarks, will need `PRESENT` recalibrated. |
| **Stale docs** | `WALKTHROUGH_PREP.md` still says sponsor / design-theme / safe-zone are paused — they're live. `postman/README.md` says port 8000 and references files that don't exist. |

### What you'd change for production

- **Storage** — Postgres, and object storage for images instead of local disk.
- **Queue** — Celery/Redis or SQS with a worker pool, replacing the in-process asyncio queue.
- **Cost** — a cheap-model-first cascade: extract with a light model, escalate only
  ambiguous findings.
- **Observability** — per-check timings and confidence are already recorded on `CheckRun`;
  add tracing on top.
- **What does not change** — the `Check` interface and the structured finding contract. New
  checks and new models plug in without touching the API or the frontend. That is the entire
  point of the design, and it's the right note to end on.

---

## Running it

Backend must be on port 8001, because `frontend/.env.local` sets
`NEXT_PUBLIC_API_BASE=http://localhost:8001`.

```bash
cd backend && ./.venv/bin/uvicorn app.main:app --reload --port 8001
```

```bash
cd frontend && npm run dev
```

Then open http://localhost:3000 and sign in as `manager@tec.dev` / `manager123`
(designer: `designer@tec.dev` / `designer123`).

- Health check: http://localhost:8001/health
- Interactive API docs: http://localhost:8001/docs
