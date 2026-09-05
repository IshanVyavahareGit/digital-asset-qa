# Typo & Roster Check — Complete Flow

The check that answers one question:

> **Is every name printed on this graphic spelled exactly the way the roster spells it?**

Everything below is traced from a real run against `assets/typo-check/match_announcement_2.png`
(1108 × 1396 px). The Gemini output, the coordinates, and the `difflib` numbers are all
captured values, not illustrations.

---

## Contents

1. [Files involved](#1-files-involved)
2. [The flow at a glance](#2-the-flow-at-a-glance)
3. [Step 1 — the input](#3-step-1--the-input)
4. [Step 2 — the prompt](#4-step-2--the-prompt)
5. [Step 3 — forcing structured output](#5-step-3--forcing-structured-output)
6. [Step 4 — what Gemini actually returned](#6-step-4--what-gemini-actually-returned)
7. [Step 5 — coordinates, explained fully](#7-step-5--coordinates-explained-fully)
8. [Step 6 — fuzzy matching, calculated](#8-step-6--fuzzy-matching-calculated)
9. [Step 7 — the time check](#9-step-7--the-time-check)
10. [Step 8 — feeding the Safe Zone check](#10-step-8--feeding-the-safe-zone-check)
11. [Step 9 — the CheckResult](#11-step-9--the-checkresult)
12. [Step 10 — saved to the database](#12-step-10--saved-to-the-database)
13. [Step 11 — drawn in the browser](#13-step-11--drawn-in-the-browser)
14. [Honest failure paths](#14-honest-failure-paths)
15. [Every knob in one table](#15-every-knob-in-one-table)

---

## 1. Files involved

| File | Its job in this check |
|---|---|
| `backend/app/checks/typo_roster.py` | **The check itself.** Prompt, schema, and all the judgement logic. |
| `backend/app/services/gemini.py` | Calls the model, enforces the schema, and converts `box_2d` → `BBox`. |
| `backend/app/services/assets.py` | Loads `roster.json` and flattens it into lookup tuples. |
| `assets/roster.json` | The source of truth: teams, tags, aliases, players, matches. |
| `backend/app/checks/base.py` | The `CheckContext` / `CheckResult` / `RawFinding` types. |
| `backend/app/schemas.py` | `BBox` and `FindingOut` — the shapes sent to the browser. |
| `backend/app/db/models.py` | The `Finding` table the result is written into. |
| `frontend/components/ImageOverlay.tsx` | Turns the stored box into a marker on the image. |
| `frontend/components/FindingsPanel.tsx` | The text of the finding in the side list. |

---

## 2. The flow at a glance

```
 CheckContext (image bytes, mime, canvas W x H, graphic_type, platform)
        |
        v
 [1] Is GEMINI_API_KEY set?  ---- no ---->  CheckResult.failed(...)  STOP
        | yes
        v
 [2] gemini.generate(prompt, image, schema=TextExtraction)
        |            temperature 0.0, response_schema enforced, 1 retry
        v
 [3] readable == false  OR  elements == []  ---- yes ---->  status=failed  STOP
        | no
        v
 [4] for each element:
        box_2d [0-1000]  --box2d_to_bbox-->  BBox (0-1 fractions)
        kind in {handle, team, time, cta}    -> append to located_elements
        kind == "handle"  -> _check_member(text, known_handles())
        kind == "team"    -> _check_member(text, known_team_names())
        kind == "time"    -> _check_time(text, valid_time_tokens)
        kind == "other"   -> ignored entirely
        |
        v
 [5] CheckResult(status=ok, findings=[...], detail="Read N text element(s).",
                 confidence=0.9, located_elements=[...], usage=...)
```

Note that `other` is a real, useful bucket. Titles, "VS", event names and sponsor
wordmarks all land there and are never compared against anything — which is why
"MATCH SCHEDULE" and "VALORANT" don't get flagged as unrecognized teams.

---

## 3. Step 1 — the input

The check receives the same `CheckContext` every check receives:

```python
CheckContext(
    image_bytes  = b'\x89PNG\r\n\x1a\n...',   # the raw uploaded file
    mime_type    = "image/png",
    canvas_w     = 1108,      # read by PIL during ingestion
    canvas_h     = 1396,
    graphic_type = "match_announcement",
    platform     = "x_post",
)
```

It also reads the roster, but **separately, in Python** — never through the prompt:

```python
handles     = assets.known_handles()      # 13 player handles
teams       = assets.known_team_names()   # 37 accepted spellings
valid_times = _valid_time_tokens()
```

`known_team_names()` is deliberately generous. For every team it collects the **full name**,
the **tag**, and any **aliases**:

```json
{ "name": "S8UL Esports",    "tag": "S8UL",  "aliases": [] }
{ "name": "Talent 7 Nation", "tag": "37N",   "aliases": ["X9"] }
{ "name": "4KOB",            "tag": "4KOB",  "aliases": ["4KIDSN18ABY"] }
```

A bracket that says `S8UL` and a match card that says `S8UL Esports` are both correct, so
both must be accepted. That's why 19 teams produce 37 accepted spellings.

> **The single most important design point:** the roster is loaded into *Python*, not into
> the prompt. Gemini never sees the correct spellings, so it physically cannot
> "helpfully" fix a typo before you get to see it.

---

## 4. Step 2 — the prompt

From `checks/typo_roster.py`, verbatim:

```
You are a precise OCR and layout extractor for an esports marketing graphic.
Extract EVERY distinct line of text you can read. For each, return:
  - text: the exact characters, VERBATIM. Never correct spelling or spacing.
  - kind: one of 'handle' (a player gamer-tag/username, often stylised with
    digits/symbols), 'team' (a team name), 'time' (a match time or date),
    'cta' (a call to action like 'Watch Live'), or 'other' (titles, 'VS', event
    names, labels, sponsor names).
  - box_2d: bounding box as [ymin, xmin, ymax, xmax] normalized to 0-1000.
If there is no legible text at all, set readable=false and return an empty list.
Do not invent text that is not visibly present.
```

Three phrases are doing real work:

- **"VERBATIM. Never correct spelling"** — without this, a model asked to read
  `ALLENTOWNN` will often write `ALLENTOWN`, silently destroying the very error you are
  looking for.
- **"set readable=false"** — gives the model an explicit way to say *"I can't read this"*,
  so the check can fail honestly instead of receiving a hallucinated list.
- **"Do not invent text that is not visibly present"** — guards against the model padding
  the output with plausible esports words.

---

## 5. Step 3 — forcing structured output

The response is bound to a Pydantic schema, so it is validated JSON before any of our code
touches it. No regex, no string parsing.

```python
class TextElement(BaseModel):
    text: str    = Field(description="Exact text, verbatim. Do NOT fix spelling.")
    kind: str    = Field(description="one of: handle, team, time, cta, other")
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax], 0..1000")

class TextExtraction(BaseModel):
    readable: bool
    elements: list[TextElement]
```

`services/gemini.py` sends it with:

```python
config = types.GenerateContentConfig(
    response_mime_type = "application/json",
    response_schema    = schema,     # TextExtraction
    temperature        = 0.0,        # deterministic QA
)
```

`temperature=0.0` matters for a QA tool: the same graphic should produce the same reading
twice. If `resp.parsed` comes back `None` — meaning the output didn't bind to the schema —
that counts as a failure, and the call is retried **once** before raising `GeminiUnavailable`.

---

## 6. Step 4 — what Gemini actually returned

Real run. 31 elements, 1,263 input tokens, 1,826 output tokens.

```json
{
  "readable": true,
  "elements": [
    { "text": "PREDATOR",       "kind": "other", "box_2d": [ 41, 101,  71, 318] },
    { "text": "intel.",         "kind": "other", "box_2d": [ 30, 780,  88, 951] },
    { "text": "MATCH",          "kind": "other", "box_2d": [413, 355, 463, 644] },
    { "text": "SCHEDULE",       "kind": "other", "box_2d": [463, 325, 513, 674] },
    { "text": "HEAVEN ESPORTS", "kind": "team",  "box_2d": [665, 268, 677, 385] },
    { "text": "VS",             "kind": "other", "box_2d": [596, 458, 627, 526] },
    { "text": "3:00 PM",        "kind": "time",  "box_2d": [634, 461, 645, 524] },
    { "text": "LAST HOPE",      "kind": "team",  "box_2d": [665, 595, 677, 684] },
    { "text": "GANGAN GALAXY",  "kind": "team",  "box_2d": [782, 273, 794, 393] },
    { "text": "7:00 PM",        "kind": "time",  "box_2d": [753, 461, 764, 524] },
    { "text": "4KOB",           "kind": "team",  "box_2d": [782, 625, 794, 654] },
    { "text": "VALORANT",       "kind": "other", "box_2d": [938,  41, 971, 312] }
  ]
}
```

Of the 31 elements: **4 teams**, **2 times**, and 25 `other`. So 6 elements are of a
"critical kind" and get passed on to the Safe Zone check. All four team names matched the
roster exactly, so this graphic produced **zero findings** — which is the correct result,
since it is one of the clean source images.

---

## 7. Step 5 — coordinates, explained fully

This is the part worth understanding properly, because it's where most of the confusion
lives.

### 7.1 What `box_2d` actually is

Gemini does **not** return pixels. It returns a position on an imaginary **1000 × 1000
grid** laid over the image, regardless of the image's real size.

Picture the image with a ruler down the left edge and another along the top. Both rulers
are marked 0 at the start and 1000 at the end — **no matter how long the edge actually is**.
`box_2d` is just four readings off those two rulers.

```
        xmin=268                    xmax=385
  0 ......|...........................|.............................. 1000   (top ruler)
  .
  .
665 -     +---------------------------+          <- ymin = 665
  .       |      HEAVEN ESPORTS       |
677 -     +---------------------------+          <- ymax = 677
  .
1000
 (left ruler)
```

### 7.2 The order is `[ymin, xmin, ymax, xmax]` — y comes first

This is the classic trap. Almost every other graphics API you have used puts x first.
Gemini puts **y first**.

```
box_2d = [ 665 ,  268 ,  677 ,  385 ]
            |      |      |      |
          ymin   xmin   ymax   xmax
           top   left  bottom  right
```

Read it as **top, left, bottom, right** and you will never get it backwards.

### 7.3 Why 0–1000?

Because the model has no reliable idea how many pixels wide your image is. Asking for
pixels would mean asking it to also estimate the image's dimensions, and it would be wrong.

A fixed 0–1000 grid removes that problem: the model only has to say *"about two-thirds of
the way down"*, and we — who know the exact pixel size — do the multiplication. It's the
same reason a map uses percentages of a page rather than centimetres.

1000 is granular enough: one step is 0.1% of the edge. On a 1920 px wide image that's
1.9 px of precision, which is finer than the boxes need to be.

### 7.4 Why each axis is normalized **independently**

This is what makes the whole scheme work on any shape of image.

The 1000 steps down the left edge and the 1000 steps along the top are **not the same
physical length** unless the image happens to be square. On a 1080 × 1920 story, one
vertical step is 1.92 px while one horizontal step is 1.08 px.

That sounds wrong but is exactly right: the grid **stretches with the image**. The value
`500` always means "halfway", whether the edge is 1080 px or 1920 px long. Aspect ratio
becomes irrelevant, and the same code handles portrait, landscape and square with no
branching.

### 7.5 The conversion, worked line by line

`services/gemini.py:box2d_to_bbox`:

```python
ymin, xmin, ymax, xmax = (float(v) / 1000.0 for v in box_2d)
x, y = min(xmin, xmax), min(ymin, ymax)
w, h = abs(xmax - xmin), abs(ymax - ymin)
```

Taking `HEAVEN ESPORTS` = `[665, 268, 677, 385]`:

```
ymin = 665 / 1000 = 0.665
xmin = 268 / 1000 = 0.268
ymax = 677 / 1000 = 0.677
xmax = 385 / 1000 = 0.385

x = min(0.268, 0.385) = 0.268      left edge
y = min(0.665, 0.677) = 0.665      top edge
w = |0.385 - 0.268|   = 0.117      width
h = |0.677 - 0.665|   = 0.012      height
```

Result: `BBox(x=0.268, y=0.665, w=0.117, h=0.012)`

Read in plain English: *the box starts 26.8% across and 66.5% down, and is 11.7% of the
width wide and 1.2% of the height tall.*

### 7.6 Why divide by 1000 at all?

To turn a **count of grid steps** into a **fraction of the edge**.

`0.268` is a ratio that means something on its own — "just over a quarter of the way
across". `268` is meaningless until you also say "…out of 1000". Storing fractions means
every downstream consumer can multiply by whatever size it cares about, without needing to
know that Gemini's grid happened to be 1000 steps.

It also decouples us from the model. If a future model returns a 0–100 or 0–4096 grid, only
`box2d_to_bbox` changes. The database, the API and the whole frontend are untouched.

### 7.7 Checking the fractions against real pixels

This graphic's canvas is **1108 × 1396**. Multiply the fractions back:

```
x_px = 0.268 x 1108 = 296.9  ->  297
y_px = 0.665 x 1396 = 928.3  ->  928
w_px = 0.117 x 1108 = 129.6  ->  130
h_px = 0.012 x 1396 =  16.8  ->   17
```

So `HEAVEN ESPORTS` sits at pixel (297, 928) and is 130 × 17 px. That is exactly where the
team label appears on the graphic — a short, wide strip of small text under the team logo.

**Notice which dimension each fraction is multiplied by.** `x` and `w` always use the
**width**; `y` and `h` always use the **height**. Mixing those up is the other classic
coordinate bug, and it's why per-axis normalization has to stay per-axis all the way through.

### 7.8 The same box on three different canvases

Take that identical `box_2d` and drop it on three canvas shapes:

| Canvas | x px | y px | w px | h px |
|---|---|---|---|---|
| 1108 × 1396 (this graphic) | 297 | 928 | 130 | 17 |
| 1080 × 1920 (Instagram story) | 289 | 1277 | 126 | 23 |
| 1920 × 1080 (YouTube thumbnail) | 515 | 718 | 225 | 13 |

Wildly different pixel numbers — but on **every** canvas the box sits 26.8% across and
66.5% down, and covers the same proportion of the frame. That is the property we want.

### 7.9 Why the frontend converts *again* — and why we don't store pixels

Here is the crucial bit. **The canvas size is not the displayed size.**

The graphic's canvas is 1108 px wide. But in the review workspace the browser renders that
image at whatever width the layout gives it — measured in the running app, **737 px**.
Tomorrow, on a wider monitor or a collapsed sidebar, it might be 1100 px.

If we had stored pixels, the marker would be wrong:

```
stored x = 297 px  ->  drawn 297 px from the left of a 737 px image
                   ->  297 / 737 = 40.3% across
                   ->  but it should be 26.8%
                   ->  the box lands on the wrong side of "VS"
```

Storing fractions avoids this completely, because the frontend converts to **percentages**,
which the browser resolves against whatever size the image happens to be right now:

```jsx
// frontend/components/ImageOverlay.tsx
style={{
  left:   `${g.x * 100}%`,   // 26.8%
  top:    `${g.y * 100}%`,   // 66.5%
  width:  `${g.w * 100}%`,   // 11.7%
  height: `${g.h * 100}%`,   //  1.2%
}}
```

At a 737 px rendered width (and 929 px rendered height) the browser computes:

```
left   = 26.8% of 737 = 197 px
top    = 66.5% of 929 = 618 px
width  = 11.7% of 737 =  86 px
height =  1.2% of 929 =  11 px
```

Resize the window and **the percentages never change** — only the pixels the browser
derives from them. That is the entire reason boxes stay glued to the artwork.

### 7.10 The full chain

```
Gemini        [665, 268, 677, 385]        grid steps, 0-1000, y first
   |  ÷ 1000                              -> a fraction of each edge
   v
Backend       x .268  y .665  w .117  h .012
   |  stored in SQLite as bbox_x, bbox_y, bbox_w, bbox_h
   |  (canvas_w and canvas_h stored alongside, for reference)
   v
API           "bbox": { "x": 0.268, "y": 0.665, "w": 0.117, "h": 0.012 }
   |  × 100                               -> a percentage
   v
Browser       left: 26.8%  top: 66.5%  width: 11.7%  height: 1.2%
   |  browser resolves % against the CURRENT rendered size
   v
Screen        197 px, 618 px, 86 x 11 px   (at a 737 px wide render)
```

Three representations of one rectangle: **grid steps → fraction → percent**. The fraction
is the stable, stored one because it is the only one that depends on neither the model's
grid nor the viewer's screen.

### 7.11 Defences inside `box2d_to_bbox`

```python
if len(box_2d) != 4:
    return BBox(x=0.0, y=0.0, w=0.0, h=0.0)
```

Gemini occasionally emits a malformed box with three values. Without this guard it raises a
`ValueError` and the *entire check* dies — 79 good elements lost because of one bad box.
Instead it degrades to a zero-size box, which the frontend renders as a pin.

```python
x, y = min(xmin, xmax), min(ymin, ymax)
w, h = abs(xmax - xmin), abs(ymax - ymin)
```

Uses `min` and `abs` rather than assuming `xmin < xmax`. If the model ever swaps the corners
you still get a valid rectangle instead of a negative width.

```python
x, y = max(0.0, x), max(0.0, y)
w, h = min(w, 1.0 - x), min(h, 1.0 - y)
```

Clamps into the canvas. This also keeps the values inside the `ge=0, le=1` constraints on
`BBox` in `schemas.py`, which would otherwise reject the payload.

```python
return BBox(x=round(x, 5), ...)
```

Rounds to 5 decimal places — far finer than the 3 decimals the 0–1000 grid can express, so
nothing is lost, but it keeps the stored numbers tidy.

---

## 8. Step 6 — fuzzy matching, calculated

Only `handle` and `team` elements reach this. It all happens in
`_check_member()` in `checks/typo_roster.py`.

### 8.1 First, lowercase everything

```python
lowered = {k.lower(): k for k in known}   # lowercase -> canonical spelling
t = text.lower()
```

This builds a map from a lowercase key back to the **properly cased** roster spelling:

```python
{ "allentown": "Allentown", "s8ul": "S8UL", "s8ul esports": "S8UL Esports", ... }
```

Graphics shout — `HEAVEN ESPORTS` — while the roster stores `Heaven Esports`. Casing is a
**styling choice, not a spelling error**, so comparing case-sensitively would flag every
single team name on every graphic. Keeping the canonical value in the map means the
suggested fix can still say "did you mean **Allentown**?" with the right capitalisation.

### 8.2 Exact match wins immediately

```python
if t in lowered:
    return []          # no finding
```

`"HEAVEN ESPORTS".lower()` = `"heaven esports"`, which is a key. Done — no finding, no
fuzzy work. This is the path all four teams took on our example graphic.

### 8.3 Otherwise, look for the closest spelling

```python
close = difflib.get_close_matches(t, list(lowered), n=1, cutoff=0.6)
```

`get_close_matches` scores `t` against all 37 keys and returns the single best one, but
**only if it scores at least 0.6**.

### 8.4 How the score is actually computed

`difflib` uses the ratio:

```
              2 x M
  ratio  =  ---------
                T

  M = total number of matching characters
  T = length of both strings added together
```

**Worked example — `ALLENTOWNN` (a doubled final N):**

```
a = "allentownn"   (10 characters)
b = "allentown"    ( 9 characters)

matching blocks: one run of 9 characters, starting at position 0 in both
                 -> "allentown" matches, the trailing extra "n" does not

M = 9
T = 10 + 9 = 19

ratio = (2 x 9) / 19 = 18 / 19 = 0.947368...
```

**Worked example — `HARISBURG` (a missing R):**

```
a = "harisburg"    ( 9 characters)
b = "harrisburg"   (10 characters)

matching blocks: "ha" (2 chars) + "risburg" (7 chars) = two runs
                 the extra "r" in the middle of b is skipped

M = 2 + 7 = 9
T = 9 + 10 = 19

ratio = (2 x 9) / 19 = 0.947368...
```

Both land on 0.947 — a single-character error in a ten-character word.

**Worked example — a name that is genuinely unknown:**

```
a = "zzz team"
best candidate = "team raise"

matching blocks: "team" (4 chars)
M = 4
T = 8 + 10 = 18
ratio = 8 / 18 = 0.4444
```

0.444 is below the 0.6 cutoff, so `get_close_matches` returns nothing at all.

### 8.5 The two outcomes

```python
if close:
    canonical = lowered[close[0]]
    ratio = difflib.SequenceMatcher(None, t, close[0]).ratio()
    -> CRITICAL   "Misspelled team name: 'X' — did you mean 'Y'?"   confidence = ratio
else:
    -> WARNING    "Unrecognized team name: 'X' is not in the roster."  confidence = 0.5
```

**Why the severities differ.** A close match means you can *name the correction*, so it is
almost certainly a typo — critical, fix it. No close match might be a legitimately new team
that hasn't been added to the roster yet, so it only asks a human to verify — warning.

**Where the confidence number comes from.** For a typo it is the real `difflib` ratio,
rounded to 3 places. The `90%` you see in the UI is a genuine measurement, not a made-up
score. For an unrecognized name it is a flat `0.5`, which is honest: we have no evidence
either way.

### 8.6 Real results against the actual roster

| Text on graphic | Closest roster key | Ratio | Outcome |
|---|---|---|---|
| `HEAVEN ESPORTS` | exact | — | no finding |
| `S8UL` | exact (matches the **tag**) | — | no finding |
| `4KOB` | exact | — | no finding |
| `KNIGHTSTOW` | `knightstown` | **0.9524** | **critical** — did you mean Knightstown? |
| `ALLENTOWNN` | `allentown` | **0.9474** | **critical** — did you mean Allentown? |
| `HARISBURG` | `harrisburg` | **0.9474** | **critical** — did you mean Harrisburg? |
| `BOX OWT` | `box out` | **0.8571** | **critical** — did you mean Box Out? |
| `ZZZ TEAM` | best was `team raise` at 0.4444 | below cutoff | **warning** — unrecognized |

### 8.7 The cutoff is the tuning knob

`cutoff=0.6` is the one dial worth understanding:

- **Lower it** (say 0.4) and more real typos get caught — but `ZZZ TEAM` would start
  matching `Team Raise` and suggesting a nonsense correction.
- **Raise it** (say 0.8) and only very close typos are flagged; a badly mangled name would
  fall through to a mere warning.

0.6 catches single- and double-character errors while rejecting unrelated words.

### 8.8 A real finding, produced this way

From `roster_update_complex_1.png`:

```json
{
  "check_type": "typo_roster",
  "severity": "warning",
  "message": "Unrecognized player handle: '@YOURSPORTEVENT' is not in the roster.",
  "suggested_fix": "Verify '@YOURSPORTEVENT' against the official roster.",
  "bbox": { "x": 0.6079, "y": 0.9053, "w": 0.2000, "h": 0.0500 },
  "is_pin": false,
  "confidence": 0.5,
  "source": "ai",
  "status": "open"
}
```

Gemini classified a social-media handle in the footer as a player handle. Nothing in the
roster is close to it, so it became a warning with confidence 0.5 — the check correctly
declining to guess.

---

## 9. Step 7 — the time check

`time` elements go to `_check_time()`, compared against a pooled set of every time in the
roster:

```python
def _valid_time_tokens() -> set[str]:
    tokens = set()
    for m in assets.roster()["matches"]:
        tokens.add(m["time_label"].lower().replace(" ", ""))   # "7:00 PM" -> "7:00pm"
        if m.get("time_utc"):
            tokens.add(m["time_utc"][:10])                     # "2026-07-18"
    return tokens
```

Comparison is bidirectional substring, so `"3:00 PM"` normalizes to `"3:00pm"` and matches
whether the roster stores `3:00pm` or `3:00pm ist`.

### ⚠ This check is currently dead

`time_label` is added **unconditionally**, while only `time_utc` is guarded. Older rows in
`roster.json` still have `"time_label": ""`, so the pooled set is:

```python
{'', '1:00pm', '2:00pm', '3:00pm', '4:00pm', '5:00pm', '6:00pm', '7:00pm', '8:00pm'}
```

And `_check_time` asks `if any(v in norm or norm in v for v in valid_times)`. **The empty
string is a substring of every string**, so every time passes — including `"total garbage"`.
The fix is one line:

```python
if m.get("time_label"):                                   # add this guard
    tokens.add(m["time_label"].lower().replace(" ", ""))
```

Two further caveats even once fixed: the pool is **global**, so it only answers "is this a
time that appears somewhere in the schedule", never "is this the right time for *this*
pairing" (that's the Matchup check's job); and substring matching is loose — `1:00pm` is a
substring of `11:00pm`.

---

## 10. Step 8 — feeding the Safe Zone check

Alongside findings, this check emits **located elements** — the boxes it found, labelled by
what they are:

```python
_CRITICAL_KINDS = {"handle", "team", "time", "cta"}

if el.kind in _CRITICAL_KINDS:
    located.append(LocatedElement(label=text, kind=el.kind, bbox=bbox))
```

On our example graphic that's **6 of 31** elements — four teams and two times. Titles,
"VS", sponsor wordmarks and the mascot text are all `other` and excluded, because nobody
cares if a decorative title clips the edge.

The orchestrator pools these from Typo and Sponsor, then hands them to Safe Zone:

```python
ctx.located_elements = [el for r in analyzer_results for el in r.located_elements]
```

Safe Zone has **no detector of its own** — this is where all its input comes from. Which
is also why, if this check fails, Safe Zone honestly reports `low_confidence` rather than
pretending everything is fine.

---

## 11. Step 9 — the CheckResult

```python
CheckResult(
    check_type       = CheckType.typo_roster,
    status           = CheckStatus.ok,
    findings         = [],                            # clean graphic
    detail           = "Read 31 text element(s).",
    confidence       = 0.9,                           # fixed, see below
    usage            = Usage(input_tokens=1263, output_tokens=1826, calls=1),
    located_elements = [6 LocatedElement objects],
)
```

The `0.9` is a hard-coded, check-level confidence meaning "OCR generally works". It is not
derived from anything. The **per-finding** confidences are the real measurements. Worth
knowing so you don't over-claim it.

---

## 12. Step 10 — saved to the database

`services/evaluation.py` writes each `RawFinding` into the `findings` table, flattening the
box into four columns:

```python
Finding(
    review_id   = review_id,
    check_type  = "typo_roster",
    severity    = "critical",
    message     = "Misspelled team name: 'ALLENTOWNN' — did you mean 'Allentown'?",
    suggested_fix = "Correct 'ALLENTOWNN' to 'Allentown'.",
    bbox_x = 0.268, bbox_y = 0.665, bbox_w = 0.117, bbox_h = 0.012,
    is_pin = False, confidence = 0.947,
    source = "ai", status = "open",
)
```

The box is stored as **four separate float columns**, not JSON, so it can be queried and
updated directly — which is what a manager dragging the marker does.

---

## 13. Step 11 — drawn in the browser

`api/serializers.py` reassembles the four columns into a `bbox` object, and the frontend
consumes it as typed JSON:

```json
{
  "id": "a1b2c3...",
  "check_type": "typo_roster",
  "severity": "critical",
  "message": "Misspelled team name: 'ALLENTOWNN' — did you mean 'Allentown'?",
  "suggested_fix": "Correct 'ALLENTOWNN' to 'Allentown'.",
  "bbox": { "x": 0.268, "y": 0.665, "w": 0.117, "h": 0.012 },
  "is_pin": false, "confidence": 0.947, "source": "ai", "status": "open"
}
```

| Field | Where it appears |
|---|---|
| `bbox` | position and size of the box, in `%` — `ImageOverlay.tsx` |
| `severity` | `critical` → red `#FF4D5E` outline and pill — `utils.ts:SEVERITY_META` |
| `check_type` | the label "Typo & Roster" — `utils.ts:CHECK_LABEL` |
| `message` | the finding text in the side panel — `FindingsPanel.tsx` |
| `suggested_fix` | the wand-icon line beneath it — `FindingsPanel.tsx` |
| `confidence` | the `95%` badge on the right of the row |
| `source` | `ai` keeps the severity colour; `manager` would force purple |
| `status` | `dismissed` greys and strikes the row, and drops it from the overlay |

Hovering the box highlights its row and vice versa, and a manager can drag the box to
reposition it — which writes `bbox` back via `PATCH /findings/{id}`, leaving `w` and `h`
untouched and rewriting only `x` and `y`.

---

## 14. Honest failure paths

The check has three ways to give up, and **none of them invent findings**.

| Situation | What it returns |
|---|---|
| `GEMINI_API_KEY` not set | `status=failed`, detail *"AI OCR unavailable (GEMINI_API_KEY not set)."* — no API call made |
| Gemini errors, or fails schema binding twice | `status=failed`, detail *"AI OCR failed: …"* |
| `readable=false` or an empty element list | `status=failed`, detail *"OCR returned no legible text — cannot verify handles/timings."*, `confidence=0.0` |

In all three cases `findings` is **empty**. That matters downstream: a failed check sets
`pipeline_status` to `partial`, and the guardrail in `pipeline/verdict.py` refuses to
certify a clean Pass:

```python
if verdict == Verdict.passed and pipeline_status != "ok":
    verdict = Verdict.needs_changes    # can't certify what you didn't evaluate
```

Feed the system a photo of a cat and you get "could not evaluate" — never a fabricated
list of misspelled players.

---

## 15. Every knob in one table

| Constant | Value | File | What it controls |
|---|---|---|---|
| `cutoff` | `0.6` | `typo_roster.py` | How close a spelling must be to count as a typo rather than an unknown name |
| unrecognized confidence | `0.5` | `typo_roster.py` | Flat confidence when nothing is close |
| time confidence | `0.6` | `typo_roster.py` | Flat confidence on a time mismatch |
| check confidence | `0.9` | `typo_roster.py` | Hard-coded "OCR generally works" |
| `_CRITICAL_KINDS` | `handle, team, time, cta` | `typo_roster.py` | Which kinds are handed to Safe Zone |
| `temperature` | `0.0` | `gemini.py` | Determinism — same graphic, same reading |
| retries | `1` | `gemini.py` | One retry before failing honestly |
| grid scale | `1000` | `gemini.py` | Gemini's normalized coordinate range |
| rounding | `5` dp | `gemini.py` | Precision of the stored fractions |

### Severity summary

| Situation | Severity | Confidence |
|---|---|---|
| Exact match (any casing) | *no finding* | — |
| Close match above cutoff | **critical** | the real difflib ratio |
| No match above cutoff | **warning** | 0.5 |
| Time not in the roster pool | **warning** | 0.6 |
| Kind is `other` | *never checked* | — |

---

## The one-paragraph summary

Gemini reads every line of text on the graphic and reports it **verbatim**, tagged by what
kind of thing it is, with a box given as four readings off a 1000-step ruler on each edge.
The backend divides those by 1000 to get plain fractions of the canvas, which are stored.
Python — which alone has the roster — lowercases each name and looks for an exact match,
then a fuzzy one using `difflib`'s `2M/T` ratio with a 0.6 cutoff: a close match is a typo
(critical, with the real ratio as its confidence), no close match is an unrecognized name
(warning). The frontend multiplies the stored fractions by 100 and positions the marker in
CSS percent, so it stays aligned at any window size. If the model can't read the image, the
check says so and emits nothing.
