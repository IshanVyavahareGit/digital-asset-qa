"""Database engine + session wiring (SQLAlchemy 2.0, sync).

We use synchronous SQLAlchemy against SQLite because it is the simplest thing that
works for a single-node demo and is trivial to explain. The concurrency that
matters here is the *check pipeline* (parallel Gemini/OpenCV calls via asyncio),
not the database, so async DB drivers would add complexity for no real benefit.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# check_same_thread=False: FastAPI may touch the session from a threadpool worker.
# timeout: wait (not error) on a locked DB — matters for concurrent batch writes.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    """WAL lets the dashboard read while a batch writes; busy_timeout avoids
    'database is locked' errors under the batch's concurrent commits."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    """Tiny idempotent migration for columns added after a DB already exists.

    `create_all` never ALTERs existing tables, so a pre-existing app.db would be
    missing newer columns. This adds them in place, preserving stored data (e.g.
    accumulated cost). Extend the map when new columns are introduced.
    """
    added = {"check_runs": [("input_tokens", "INTEGER DEFAULT 0"),
                            ("output_tokens", "INTEGER DEFAULT 0")]}
    with engine.begin() as conn:
        for table, columns in added.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, ddl in columns:
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
