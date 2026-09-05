"""FastAPI application entrypoint.

Responsibilities kept deliberately thin:
  - create the app + CORS
  - create tables and seed demo users on startup
  - serve uploaded images as static files
  - mount the API routers (auth, graphics/evaluate, reviews, findings, batch)

All real logic lives in checks/, pipeline/, services/ and api/ so this file stays
a readable table of contents for the whole backend.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import Base, engine, ensure_schema, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure data dirs exist, create tables, seed demo accounts.
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    ensure_schema()  # add columns to pre-existing DBs (preserves stored data)

    from app.core.security import seed_demo_users  # local import avoids cycles
    seed_demo_users()

    yield
    # (no shutdown work needed for the demo)


app = FastAPI(title="Esports Visual QA", version="1.0.0", lifespan=lifespan)

# The StaticFiles mount below is evaluated at import time, so the upload dir must
# already exist here (lifespan startup runs later). ensure_dirs() is idempotent.
settings.ensure_dirs()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Uploaded graphics are served straight from disk (metadata-in-DB, bytes-on-disk).
app.mount("/static", StaticFiles(directory=settings.upload_dir), name="static")


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# Routers.
from app.api import (  # noqa: E402
    auth as auth_routes,
    batch as batch_routes,
    findings as findings_routes,
    graphics as graphics_routes,
    recheck as recheck_routes,
    references as references_routes,
    reviews as reviews_routes,
)

app.include_router(auth_routes.router)
app.include_router(graphics_routes.router)
app.include_router(reviews_routes.router)
app.include_router(findings_routes.router)
app.include_router(batch_routes.router)
app.include_router(recheck_routes.router)
app.include_router(references_routes.router)


@app.get("/meta/cost", tags=["meta"])
def demo_cost(db: Session = Depends(get_db)) -> dict:
    """Gemini token usage / estimated cost.

    `total` is persisted from the stored evaluations and survives restarts;
    `since_restart` is the in-memory counter for the current process.
    """
    from app.services.evaluation import persisted_cost, session_usage

    u = session_usage()
    return {
        "total": persisted_cost(db),
        "since_restart": {
            "gemini_calls": u.calls, "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens, "estimated_usd": u.usd,
        },
    }
