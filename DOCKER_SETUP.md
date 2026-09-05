# Running This On Someone Else's Machine

Two ways to hand this over:

- **Docker** — `docker compose up --build`, one command, no Python or Node needed on their machine. Best for anyone who just wants to *see* it.
- **Native** — a venv and an npm install. Faster to iterate on, needs the right runtimes.

Both are covered below. The Docker path has four files, already written into this repo.

> ### Status: written, not yet built
> I wrote and reviewed these files but **could not run the build** — the Docker daemon
> wasn't running on this machine (only the CLI responded). Treat them as carefully
> reviewed, not verified. First thing to do is:
>
> ```bash
> docker compose build
> ```
>
> If it fails, the [troubleshooting table](#5-if-something-breaks) covers the failures
> I'd expect.

---

## 1. What's genuinely tricky about *this* project

A generic "FastAPI + Next.js in Docker" recipe breaks here in five specific places. These
are the parts worth understanding — the files themselves are boilerplate around them.

### 1.1 The build context must be the repo root, not `backend/`

`backend/app/core/config.py` derives its paths by walking *up* from itself:

```python
BACKEND_DIR = Path(__file__).resolve().parents[2]   # -> /app/backend
REPO_ROOT   = BACKEND_DIR.parent                    # -> /app
assets_dir  = REPO_ROOT / "assets"                  # -> /app/assets
```

So the asset pack lives *outside* `backend/`. Build with `context: ./backend` and copy only
that directory, and the image will start fine — then every check that reads
`roster.json`, `sponsor_manifest.json`, `brand_guide.json` or `safe_zones.json` will crash
on the first upload, because `/app/assets` won't exist.

The fix is to build from the repo root and copy **both** directories, preserving the same
relative layout:

```dockerfile
COPY backend/app  backend/app
COPY assets       assets
WORKDIR /app/backend      # so BACKEND_DIR=/app/backend and REPO_ROOT=/app
```

### 1.2 `NEXT_PUBLIC_API_BASE` is baked in at build time — and must point at the *host*

Two separate traps in one variable.

**It's a build-time value.** Next.js inlines every `NEXT_PUBLIC_*` variable into the
client bundle during `next build`. Setting it as a runtime `environment:` entry in compose
does nothing — the string is already compiled into the JavaScript. It has to be a
`build.args` entry.

**It must be reachable from the browser, not from the container.** This is the one people
get wrong. The fetch to `/reviews` doesn't happen inside the frontend container — it
happens in the user's browser, on their machine. So:

```yaml
NEXT_PUBLIC_API_BASE: http://localhost:8001    # correct — the browser can reach this
NEXT_PUBLIC_API_BASE: http://backend:8001      # WRONG — only resolves inside Docker's network
```

`http://backend:8001` looks more "correct" and fails with an unhelpful DNS error in the
browser console. Container hostnames only matter for server-to-server calls, and this app
makes none.

### 1.3 The volume has to sit at `/app/backend/data`

Both the database and the uploaded images live there:

```python
database_url = f"sqlite:///{BACKEND_DIR / 'data' / 'app.db'}"
upload_dir   = BACKEND_DIR / "data" / "uploads"
```

Mount the volume anywhere else and every `docker compose up --build` starts from an empty
database with no images — including losing the append-only cost ledger, which is the one
table specifically designed to survive deletions.

A **named volume** is used rather than a bind mount. SQLite over a bind mount on macOS or
Windows can hit file-locking problems, and this app runs in WAL mode which adds `-wal` and
`-shm` sidecar files that need to live on the same filesystem as the database.

### 1.4 Port 8001 isn't arbitrary

`frontend/.env.local` sets `NEXT_PUBLIC_API_BASE=http://localhost:8001`, and the backend's
`cors_origins` allows `localhost:3000` and `:3001`. Change one port and you must change
both, or you get a CORS failure that looks like a network error.

### 1.5 The secret goes in a root `.env` — which is *not* the one you use locally

`config.py` reads two env files, `<repo root>/.env` **then** `backend/.env`, and the later
one wins. Locally your key lives in `backend/.env`.

Docker compose does **not** read `backend/.env` — its `env_file:` points at the repo root.
And `.dockerignore` excludes all `.env*` files so no secret is ever baked into an image;
the values arrive as environment variables at runtime instead.

So for Docker you need a **root** `.env`. Copy the template and paste your key in:

```bash
cp .env.example .env
```

*(I verified the precedence: with both files present, `backend/.env` still wins for native
runs, so adding a root `.env` won't break your local setup.)*

---

## 2. The files

Four files, all at the paths shown.

### `backend/Dockerfile`

```dockerfile
FROM python:3.11-slim

# opencv-python-headless needs libglib even though it skips the GUI stack.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app  backend/app
COPY assets       assets

WORKDIR /app/backend
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

`--host 0.0.0.0` is required. Uvicorn's default binds to loopback *inside* the container,
which the port mapping can't reach.

`curl` is installed only so the compose healthcheck has something to call.

`opencv-python-headless` is already the right choice in `requirements.txt` — plain
`opencv-python` would pull in a GUI stack the container has no use for.

### `frontend/Dockerfile`

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ARG NEXT_PUBLIC_API_BASE=http://localhost:8001
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
EXPOSE 3000
CMD ["npm", "run", "start"]
```

Dependencies are copied and installed **before** the source, so editing a component
doesn't re-run `npm ci`.

There's no `COPY public` line because this project has no `frontend/public` directory —
adding one would fail the build.

### `docker-compose.yml`

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    ports:
      - "8001:8001"
    env_file:
      - .env
    volumes:
      - qa-data:/app/backend/data
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8001/health"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 5s

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
      args:
        NEXT_PUBLIC_API_BASE: http://localhost:8001
    ports:
      - "3000:3000"
    depends_on:
      backend:
        condition: service_healthy

volumes:
  qa-data:
```

`condition: service_healthy` uses the existing `GET /health` endpoint, so the frontend only
starts once the backend has finished creating tables and seeding the demo users. Without it
the first page load can race the schema creation.

### `.dockerignore`

Two jobs: keep secrets and local state out of the images, and keep the build fast by not
shipping `node_modules` or a 30 MB `data/` directory into the build context.

```
**/.env
**/.env.*
backend/data/
backend/.venv/
**/node_modules/
frontend/.next/
frontend/out/
frontend/tsconfig.tsbuildinfo
**/__pycache__/
**/*.py[cod]
.git/
.gitignore
*.md
postman/
```

`assets/` is deliberately **not** excluded — the backend needs it (see 1.1).

---

## 3. First run

```bash
cp .env.example .env        # then paste your GEMINI_API_KEY into it
docker compose up --build
```

Then open **http://localhost:3000** and sign in:

| Role | Email | Password |
|---|---|---|
| Manager — upload, evaluate, override | `manager@tec.dev` | `manager123` |
| Designer — read-only | `designer@tec.dev` | `designer123` |

The users are seeded automatically on first boot by the app's lifespan hook, so there's no
migration or setup step.

Expect the first build to take several minutes — installing OpenCV plus NumPy, and running
`next build`. Rough image sizes: backend around 500–600 MB, frontend around 500–700 MB.
Subsequent builds are much faster thanks to layer caching.

Everyday commands:

```bash
docker compose up                 # start (no rebuild)
docker compose logs -f backend    # tail backend logs
docker compose down               # stop, keep the database
docker compose down -v            # stop AND wipe the volume (fresh start)
```

### Two things to warn people about

**Without a Gemini key**, the three model-backed checks (typo/roster, matchup,
design/theme) honestly report `failed` and the UI shows "could not evaluate". Sponsor audit
and safe zone still run, so the app is usable but most findings won't appear.

**Most of the sample graphics can't be uploaded.** `validate_aspect_ratio` only knows 9:16,
16:9 and 1:1, and four of the nine test images are roughly 4:5 portrait, so they return
422. Point people at `bracket_2.png` (16:9 → X Post) or `roster_update.png`
(1:1 → Instagram Post).

---

## 4. The native fallback

Faster for development, and it's what actually runs today.

```bash
# backend — must be port 8001
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example ../.env          # or put the key in backend/.env
uvicorn app.main:app --reload --port 8001
```

```bash
# frontend, in a second terminal
cd frontend
npm install
npm run dev
```

Requires Python 3.11+ and Node 18.18+ (this repo is developed on 3.11.5 and Node 22).

---

## 5. If something breaks

| Symptom | Cause | Fix |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop isn't running | start it, then retry |
| `env file .env not found` | root `.env` missing | `cp .env.example .env` |
| Findings load but images are broken | `NEXT_PUBLIC_API_BASE` wrong, or backend not on 8001 | it must be host-reachable — `http://localhost:8001` |
| Browser console: failed to fetch / DNS error | built with `http://backend:8001` | rebuild the frontend with `localhost` (see 1.2) |
| CORS error in the console | frontend served from an origin the backend doesn't allow | add it via `CORS_ORIGINS=["http://localhost:3000"]` in `.env` |
| `FileNotFoundError: roster.json` on upload | `assets/` not in the image | build from the repo root and `COPY assets assets` (see 1.1) |
| `ImportError: libGL.so.1` | plain `opencv-python` instead of headless | keep `opencv-python-headless` in `requirements.txt` |
| Database empty after every rebuild | volume not mounted at `/app/backend/data` | fix the volume path (see 1.3) |
| `Sponsor logo assets missing` | `assets/sponsors/*.png` absent | they're committed; confirm `.dockerignore` isn't excluding them |
| Every upload returns 422 | aspect ratio doesn't match the chosen platform | use a 16:9 or 1:1 graphic (see the warning in §3) |
| Changing `NEXT_PUBLIC_API_BASE` has no effect | it's compiled into the bundle | `docker compose build frontend --no-cache` |

---

## 6. What I deliberately left out

- **`output: 'standalone'` in `next.config.mjs`.** It would cut the frontend image to
  roughly 150 MB by shipping only the traced dependencies instead of all of `node_modules`.
  It needs a config change and a different set of `COPY` lines, so it's a worthwhile
  follow-up rather than part of a first pass.
- **A reverse proxy.** Nginx or Caddy in front of both services would remove the
  build-time-API-base problem entirely, because everything would sit on one origin. Right
  for a real deployment, overkill for handing someone a demo.
- **Multi-architecture builds.** These build natively on whatever machine runs them.
  `docker buildx` with `--platform linux/amd64,linux/arm64` is only needed if you publish
  the images to a registry for mixed Intel/ARM users.
- **Pinned base image digests.** `python:3.11-slim` and `node:22-alpine` are moving tags.
  Pinning by digest makes builds reproducible and is the right call before anything
  resembling production.
