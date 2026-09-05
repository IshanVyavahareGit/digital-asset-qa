# Database Schema — Structure and Justification

Eight tables, SQLite, defined in `backend/app/db/models.py` via SQLAlchemy 2.0.

Every example below is a real row read out of `backend/data/app.db`. Where a design
decision is defended, the defence is backed by something visible in the data rather than
by assertion.

---

## Contents

1. [The shape at a glance](#1-the-shape-at-a-glance)
2. [Table by table](#2-table-by-table)
3. [The eight decisions worth defending](#3-the-eight-decisions-worth-defending)
4. [Indexes, and what's missing](#4-indexes-and-whats-missing)
5. [Migrations](#5-migrations)
6. [What changes at production scale](#6-what-changes-at-production-scale)

---

## 1. The shape at a glance

```
                          users
                            |
              +-------------+--------------+
              |                            |
        (uploaded_by)                (created_by)
              |                            |
              v                            v
          graphics  <---- batch_id ---- batch_jobs
            |   ^
            |   +-- parent_graphic_id  (self-reference: "I revise that one")
            |   +-- version_group_id   (INDEXED: groups a revision lineage)
            |
       (1:1, enforced by UNIQUE)
            |
            v
         reviews
            |
            +-----< findings      cascade delete
            +-----< check_runs    cascade delete


   usage_events         <- deliberately connected to NOTHING
   reference_graphics   <- built for Tier 3, currently 0 rows
```

Current contents: 2 users, 8 graphics, 8 reviews, 14 findings, 28 check runs,
38 usage events, 3 batch jobs.

Two things in that diagram are unusual and both are deliberate: `usage_events` has no
foreign keys at all, and `graphics` points at itself. Sections 3.6 and 3.7 explain why.

---

## 2. Table by table

### 2.1 `users`

```sql
CREATE TABLE users (
    id              VARCHAR NOT NULL PRIMARY KEY,
    email           VARCHAR NOT NULL,          -- UNIQUE INDEX
    hashed_password VARCHAR NOT NULL,
    role            VARCHAR NOT NULL,          -- "designer" | "manager"
    created_at      DATETIME NOT NULL
);
```

```python
{'id': 'daa4020a-d531-45f4-99f1-4e2205b81595', 'email': 'manager@tec.dev', 'role': 'manager'}
{'id': '356fc497-2ea3-43f8-8e01-cc9ee9450e1c', 'email': 'designer@tec.dev', 'role': 'designer'}
```

Deliberately minimal. Two seeded accounts, bcrypt hashes, no password reset, no email
verification, no sessions table — authentication is stateless JWT, so there is nothing to
store per login. `role` is a plain string rather than a join to a roles table because there
are exactly two roles and they are baked into the product's meaning.

### 2.2 `graphics`

```sql
CREATE TABLE graphics (
    id                VARCHAR NOT NULL PRIMARY KEY,
    filename          VARCHAR NOT NULL,   -- what the user called it
    stored_path       VARCHAR NOT NULL,   -- what it's called on disk
    graphic_type      VARCHAR NOT NULL,   -- match_announcement | bracket | roster_update
    platform          VARCHAR NOT NULL,   -- instagram_story | youtube_thumbnail | x_post | instagram_post
    canvas_w          INTEGER NOT NULL,
    canvas_h          INTEGER NOT NULL,
    uploaded_by       VARCHAR NOT NULL REFERENCES users(id),
    version_group_id  VARCHAR NOT NULL,   -- INDEXED
    parent_graphic_id VARCHAR REFERENCES graphics(id),
    version           INTEGER NOT NULL,
    batch_id          VARCHAR REFERENCES batch_jobs(id),
    created_at        DATETIME NOT NULL
);
```

Real rows, showing the two interesting columns:

```
filename                     stored_path                              canvas    version_group  parent    version
bracket_1_wrong.png          3219d0bef0674522a11177c93ca5cc37.png     1129x1393  3296919d      None      1
bracket_1.png                011c929cfef7405bae7939746d6462bb.png     1112x1370  3296919d      8032ed1c  2
bracket_2.png                7bac4a7375004fd0be0c38e3b7981a63.png     2418x1362  4a9650d5      None      1
match_announcement_1.png     8db5fbb2a84f456fae5b9b50f74ee8aa.png     1132x1396  efe7983a      None      1   batch=75c53e59
```

`filename` and `stored_path` are separate on purpose — see 3.2. The lineage columns are
explained in 3.7. Note `canvas_w` / `canvas_h` are stored even though the image file also
carries them: reading dimensions means decoding the image, and the API returns them on
every review. Storing them once at ingestion turns a decode into a column read.

### 2.3 `reviews`

```sql
CREATE TABLE reviews (
    id              VARCHAR NOT NULL PRIMARY KEY,
    graphic_id      VARCHAR NOT NULL UNIQUE REFERENCES graphics(id),
    verdict         VARCHAR NOT NULL,   -- pass | needs_changes | fail
    reasoning       TEXT NOT NULL,
    pipeline_status VARCHAR NOT NULL,   -- ok | partial | failed
    created_at      DATETIME NOT NULL
);
```

```
id        graphic   verdict        pipeline_status  reasoning
76bdcf3c  8032ed1c  fail           ok               Found 2 critical issues.
0695228e  fd72abdd  pass           ok               Found no issues.
a02b3326  ec43ccb0  fail           partial          Found 1 critical issue, 1 warning; note: some checks...
d6166ac9  75c4515f  needs_changes  ok               Found 1 warning.
```

`UNIQUE (graphic_id)` enforces one review per graphic at the database level, not just by
convention. A revision does not add a second review — it creates a **new graphic** in the
same version group, which then gets its own review. The constraint makes that rule
impossible to violate by accident.

`pipeline_status` is a separate column from `verdict` because they answer different
questions: *"how bad is this graphic"* versus *"how much of it did we actually manage to
check"*. Row `a02b3326` shows why — it is `partial` because the sponsor check failed on
that run, and the reasoning text carries the caveat. Without that column the verdict
guardrail in `pipeline/verdict.py` would have nothing to test.

`reasoning` is stored rather than recomputed because it is generated alongside the verdict
and is cheap to keep. It is regenerated on every override, so it never goes stale.

### 2.4 `findings`

The core table. One row per issue.

```sql
CREATE TABLE findings (
    id            VARCHAR NOT NULL PRIMARY KEY,
    review_id     VARCHAR NOT NULL REFERENCES reviews(id),
    check_type    VARCHAR NOT NULL,   -- which of the five produced it
    severity      VARCHAR NOT NULL,   -- info | warning | critical
    message       TEXT NOT NULL,
    suggested_fix TEXT NOT NULL,
    bbox_x        FLOAT,              -- nullable: not every finding is spatial
    bbox_y        FLOAT,
    bbox_w        FLOAT,
    bbox_h        FLOAT,
    is_pin        BOOLEAN NOT NULL,
    confidence    FLOAT,              -- nullable: manager findings have none
    source        VARCHAR NOT NULL,   -- ai | manager
    status        VARCHAR NOT NULL,   -- open | dismissed | edited
    created_at    DATETIME NOT NULL,
    updated_at    DATETIME NOT NULL   -- onupdate=now
);
```

An AI finding and a manager finding side by side, both real:

```python
# AI — matchup check
{'source': 'ai', 'check_type': 'matchup', 'severity': 'critical', 'confidence': 0.9,
 'is_pin': 0, 'bbox_x': 0.285, 'bbox_y': 0.444, 'bbox_w': 0.18, 'bbox_h': 0.051,
 'message': "'S8UL Esports' vs 'Last Hope' is not a scheduled match in the roster."}

# Manager — drawn by hand in the UI
{'source': 'manager', 'check_type': 'design_theme', 'severity': 'warning', 'confidence': None,
 'is_pin': 0, 'bbox_x': 0.46133429155966776, 'bbox_y': 0.6593436020753368,
 'bbox_w': 0.09206349206349201, 'bbox_h': 0.054092125651500234,
 'message': 'Match time should be bolder for readability'}
```

Two things are legible just from the numbers. The AI box has clean three-decimal values
because it came from Gemini's 0–1000 grid divided by 1000. The manager box carries full
float precision because it came from a pointer position in a browser. And `confidence` is
`NULL` for the manager row — a human doesn't have a confidence score, so the column is
nullable rather than being faked with `1.0`.

### 2.5 `check_runs`

One row per check, per review — *whether or not it produced findings*.

```sql
CREATE TABLE check_runs (
    id            VARCHAR NOT NULL PRIMARY KEY,
    review_id     VARCHAR NOT NULL REFERENCES reviews(id),
    check_type    VARCHAR NOT NULL,
    status        VARCHAR NOT NULL,   -- ok | low_confidence | failed
    detail        TEXT NOT NULL,
    confidence    FLOAT,
    duration_ms   INTEGER NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL
);
```

```
check_type     status  detail                                  conf  ms      tok_in  tok_out
typo_roster    ok      Read 100 text element(s).               0.9   14151   1300    5132
matchup        ok      Validated 12 matchup(s) ...             0.85   5105   1250     787
sponsor_audit  ok      Checked 2 mandatory sponsor(s).         0.716 13231      0       0
design_theme   ok      Brand deviations found.                 0.8    4987   1675     132
safe_zone      ok      Tested 46 critical element(s) ...       0.95      0      0       0
```

This table is what makes honest failure possible. A check that finds nothing and a check
that *couldn't run* both produce zero findings — without this table they would be
indistinguishable, and the UI would show a reassuring empty list either way. Section 3.5
has the evidence for why it is a table rather than columns on `reviews`.

Note `sponsor_audit` and `safe_zone` record `0` tokens: they use no LLM, and the schema
represents that naturally rather than needing a nullable "is this an AI check" flag.

### 2.6 `usage_events`

An append-only cost ledger.

```sql
CREATE TABLE usage_events (
    id            VARCHAR NOT NULL PRIMARY KEY,
    model         VARCHAR NOT NULL,
    gemini_calls  INTEGER NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    estimated_usd FLOAT NOT NULL,
    created_at    DATETIME NOT NULL
);
```

**No foreign keys. Not one.** That is the entire point — see 3.6.

```
model                   calls   input_tokens  output_tokens  usd
gemini-3.1-flash-lite      67         88,231        105,924  0.18095
gemini-3.5-flash            9         13,415          2,628  0.04378
```

### 2.7 `batch_jobs`

```sql
CREATE TABLE batch_jobs (
    id         VARCHAR NOT NULL PRIMARY KEY,
    status     VARCHAR NOT NULL,   -- queued | processing | done
    total      INTEGER NOT NULL,
    completed  INTEGER NOT NULL,
    failed     INTEGER NOT NULL,
    created_by VARCHAR NOT NULL REFERENCES users(id),
    created_at DATETIME NOT NULL
);
```

```
id        status  total  completed  failed
bb97a9ee  done        4          4       0
635e78b2  done        5          5       0
75c53e59  done        2          2       0
```

The three counters are **denormalised on purpose**. They could be derived by counting
graphics with that `batch_id`, but the client polls this row every 1.5 seconds, and each
poll would then become an aggregate over a growing table. The background worker bumps a
counter in a short commit; the poll reads one row by primary key.

Honest caveat visible in the column names: `completed` actually counts *attempted*, because
`_bump()` increments it on failure too. `failed` is the subset that errored.

### 2.8 `reference_graphics`

```sql
CREATE TABLE reference_graphics (
    id          VARCHAR NOT NULL PRIMARY KEY,
    stored_path VARCHAR NOT NULL,
    label       VARCHAR NOT NULL,
    uploaded_by VARCHAR NOT NULL REFERENCES users(id),
    created_at  DATETIME NOT NULL
);
```

Currently **0 rows**. Built for Tier 3 theme calibration — a manager uploads approved
graphics and the design check receives them as extra visual context. The API is complete;
no frontend calls it yet. Worth mentioning rather than hiding: it is a built-but-unwired
feature, not a mistake.

---

## 3. The eight decisions worth defending

### 3.1 String UUID primary keys, not autoincrement integers

Every table uses a `VARCHAR` id holding a UUID. The usual objection is that integers are
smaller and faster. Here the reason is architectural, not aesthetic.

`services/evaluation.py` runs the entire ~20 second pipeline **with no database
transaction open**, then writes everything in one short commit:

```python
graphic_id = uuid.uuid4().hex        # generated BEFORE any DB work
review_id  = uuid.uuid4().hex

outcome = await evaluate(ctx)        # ~20s, no DB connection held

db.add_all([graphic, review])
db.add_all([CheckRun(review_id=review_id, ...) for r in outcome.check_results])
db.add_all([Finding(review_id=review_id, ...) for f in outcome.findings])
db.commit()                          # ONE short write
```

With autoincrement integers this is impossible. The child rows need the parent's id, and
the only way to learn an autoincrement id is to `flush()` — which on SQLite takes a
**write lock**. The original version did exactly that, held the lock across the whole
pipeline, and three concurrent batch items blocked each other to the 30-second lock
timeout. The batch appeared frozen.

Client-generated UUIDs remove the dependency entirely: ids exist before the work starts, so
children can reference parents with no round trip. **The primary key type is what makes the
concurrency fix possible.**

### 3.2 Image bytes on disk, only a pointer in the database

```
filename    = "bracket_1.png"                                 what the user called it
stored_path = "011c929cfef7405bae7939746d6462bb.png"          what it's called on disk
```

Three benefits from splitting these:

- **The database stays small.** Eight graphics would otherwise be ~14 MB of BLOBs. Backups,
  reads and the WAL all stay cheap.
- **Collisions become impossible.** Two designers both uploading `bracket.png` get distinct
  UUID filenames. The original name is preserved for display only.
- **Images never travel through Python.** They are served by `StaticFiles` straight from
  `/static`, so fetching an image costs no ORM session and no request handler.

The cost is that the filesystem and the database can drift, which is handled explicitly:
`delete_graphic_and_file()` unlinks the file first with `missing_ok=True`, then deletes the
row, so a missing file never blocks cleanup.

### 3.3 The bounding box as four float columns, not JSON

```sql
bbox_x FLOAT, bbox_y FLOAT, bbox_w FLOAT, bbox_h FLOAT, is_pin BOOLEAN NOT NULL
```

A single JSON column would look tidier. Four columns win for a concrete reason: **the box
is mutated by itself, constantly.** Every time a manager drags or resizes a marker,
`api/findings.py` runs:

```python
finding.bbox_x, finding.bbox_y = body.bbox.x, body.bbox.y
finding.bbox_w, finding.bbox_h = body.bbox.w, body.bbox.h
```

That is a plain column update. With JSON it becomes read–parse–modify–serialise–write, and
the values stop being queryable — no `WHERE bbox_w > 0.5`, no index, no ability to find
"all full-canvas findings" in SQL.

They are **nullable** because not every finding is spatial, and `is_pin` is an explicit
boolean rather than being inferred from `w == h == 0`. Inference would conflate two
different things: a deliberate pin, and a box that collapsed to zero because
`box2d_to_bbox` rejected a malformed response. The flag records intent.

### 3.4 Coordinates as 0–1 fractions, with the canvas size alongside

Storing pixels would be wrong twice over. The canvas is 2418 px wide but the browser might
render it at 737 px, so stored pixels would put the marker in the wrong place; and every
consumer would need to know which canvas the number referred to.

Fractions are self-describing — `0.285` means "28.5% across" on any image, at any display
size. `canvas_w` / `canvas_h` sit on `graphics` for when a real pixel value *is* needed, so
the conversion is always available but never baked in.

### 3.5 Checks as rows, not columns — and here is the proof

The tempting shortcut is to put check results on `reviews`: `typo_status`,
`matchup_status`, and so on. This project has direct evidence of why that would have hurt.

The pipeline originally ran **two** checks. Three more were switched on later. Look at what
the same table holds:

```
bracket_1_wrong.png          2026-07-11   2 checks: typo_roster, matchup
bracket_1.png                2026-07-11   2 checks: typo_roster, matchup
match_announcement_1.png     2026-07-11   2 checks: typo_roster, matchup
roster_update_complex_1.png  2026-07-11   2 checks: typo_roster, matchup
bracket_2_wrong.png          2026-08-10   5 checks: typo_roster, matchup, sponsor_audit, design_theme, safe_zone
sponsors_missing.png         2026-08-17   5 checks: typo_roster, matchup, sponsor_audit, design_theme, safe_zone
bracket_2.png                2026-08-17   5 checks: typo_roster, matchup, sponsor_audit, design_theme, safe_zone
roster_update.png            2026-08-24   5 checks: typo_roster, matchup, sponsor_audit, design_theme, safe_zone
```

Adding three checks required **no schema change, no migration, and no backfill**. Old
reviews honestly record that only two checks ran; new ones record five. The history stays
truthful.

With columns you would have needed `ALTER TABLE` three times, plus three nullable columns
forever, plus a decision about what `NULL` means for a July review — did the check pass, or
did it not exist yet? The row-per-check design answers that question by simply not having
the row.

This is also what makes the `Check` interface's promise real: adding a sixth check is three
files and zero database work.

### 3.6 The cost ledger is deliberately disconnected

`usage_events` has no foreign key to anything. That looks like an oversight and is the
opposite.

**Evidence: 38 usage events, 8 reviews.** Thirty of those events belong to graphics that
have since been deleted. Had the ledger been linked with a cascade, deleting a test upload
would have erased the record of money already spent. Spend is a fact about the past; it
should not be revisable by tidying up the dashboard.

The second half of the decision is that `estimated_usd` is a **stored column, not a
computed one**. Prices differ sharply between models:

| model | calls | output tokens | USD | per 1k output |
|---|---|---|---|---|
| `gemini-3.1-flash-lite` | 67 | 105,924 | $0.18095 | $0.001708 |
| `gemini-3.5-flash` | 9 | 2,628 | $0.04378 | $0.016659 |

Nearly a **10× difference**. If USD were recomputed at read time using whatever model is
configured *today*, those nine historical `gemini-3.5-flash` calls would be repriced at
flash-lite rates and the reported spend would be badly wrong. Freezing the dollar figure at
the moment of the call keeps history accurate across model switches.

Lifetime total across both models: **$0.22472**.

### 3.7 Versioning by lineage, not by overwrite

Three columns carry it:

```
version_group_id   all revisions of one graphic share this   (INDEXED)
parent_graphic_id  self-reference: which graphic I revise
version            1, 2, 3 ...
```

The real lineage in this database:

```
version  filename              verdict  parent
      1  bracket_1_wrong.png   fail     None
      2  bracket_1.png         pass     8032ed1c
```

A designer submitted a revision, the pipeline re-ran, and the verdict went **fail → pass**.
Both rows survive.

The alternative — updating the graphic in place — would have destroyed the evidence that
anything was ever wrong, and with it the entire point of a QA tool. It also makes the
re-check diff possible: `pipeline/diff.py` compares the two reviews' findings to report
what was resolved, what persists and what is new.

`version_group_id` earns the only non-unique index in the schema because two hot paths hit
it: the dashboard collapses each lineage to its latest version, and `/reviews/{id}/versions`
fetches the whole chain for the timeline.

### 3.8 AI findings are dismissed, never deleted

```
source    status     count
ai        open          11
manager   open           2
manager   edited         1
```

Note what is absent: no AI finding has ever been deleted, and none can be.
`api/findings.py` refuses:

```python
if finding.source != FindingSource.manager.value:
    raise HTTPException(400, "AI findings can be dismissed but not deleted.")
```

Dismissing sets `status = "dismissed"`, which removes the finding from the verdict
calculation and greys it in the UI — but the row stays. So the record of *what the AI
reported* is permanent, while a manager's own annotations remain theirs to remove. For a
tool whose job is review, that audit trail is the product.

`status` also distinguishes `edited` from `open`, so you can tell an untouched AI finding
from one a human reworded. Repositioning deliberately does **not** set `edited` — moving a
box isn't changing what it says.

---

## 4. Indexes, and what's missing

The entire schema has two indexes:

```sql
CREATE UNIQUE INDEX ix_users_email          ON users (email);
CREATE INDEX        ix_graphics_version_group_id ON graphics (version_group_id);
```

Plus the implicit primary keys and the `UNIQUE (graphic_id)` on `reviews`.

`email` is unique because login looks up by it. `version_group_id` is indexed because the
dashboard and the version timeline both scan by it on every page load.

**What is deliberately missing, and would not be at scale:** there is no index on
`findings.review_id` or `check_runs.review_id`, even though every review fetch filters on
them. With 14 findings and 28 check runs a full scan is free. At tens of thousands of rows
those two indexes would be the first thing to add, along with `graphics.batch_id` — the
batch status endpoint currently loads every review and filters in Python, which is the
worst offender in the codebase.

---

## 5. Migrations

There is no Alembic. Tables are created with `Base.metadata.create_all()`, plus a small
idempotent helper in `db/session.py`:

```python
def ensure_schema() -> None:
    added = {"check_runs": [("input_tokens", "INTEGER DEFAULT 0"),
                            ("output_tokens", "INTEGER DEFAULT 0")]}
    for table, columns in added.items():
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        for name, ddl in columns:
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
```

`create_all` never alters an existing table, so a database created before the token columns
existed would silently lack them. This adds them in place and preserves stored data —
which mattered, because that data included the accumulated cost ledger.

This is the right call for a single-node prototype and the wrong one for production. It
handles added columns only: no renames, no type changes, no data migrations, no down
migrations, and no version history. Alembic is the answer the moment more than one
environment exists.

### Two engine-level settings that belong in this conversation

```python
cur.execute("PRAGMA journal_mode=WAL")
cur.execute("PRAGMA busy_timeout=30000")
```

WAL lets the dashboard read while a batch writes, instead of readers and writers blocking
each other. `busy_timeout` makes a contended write **wait** up to 30 seconds rather than
immediately raising "database is locked". Both exist because of the batch concurrency work
described in 3.1.

---

## 6. What changes at production scale

The schema itself mostly survives; the engine and the storage do not.

| Concern | Now | Production |
|---|---|---|
| Engine | SQLite, single file | Postgres — real concurrent writers, proper types |
| Images | local disk + `StaticFiles` | S3 or equivalent; `stored_path` becomes an object key |
| Migrations | `create_all` + `ensure_schema` | Alembic with versioned, reversible migrations |
| Indexes | 2 | add `findings.review_id`, `check_runs.review_id`, `graphics.batch_id` |
| Batch state | `batch_jobs` row polled every 1.5s | a real queue owns job state; the table becomes a projection |
| Enums | `VARCHAR` | stay `VARCHAR` — Postgres enum types are painful to alter |
| Cost ledger | unchanged | unchanged; append-only and unlinked is already the right shape |

**What does not change** is the part that matters: `findings` and `check_runs` keep their
shape, because they encode the structured finding contract the API and frontend are built
on. New checks add rows, never columns. That is the same property that let three checks be
switched on without a migration, and it is the reason to trust the design under change.
