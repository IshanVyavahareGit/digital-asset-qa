"""ORM models — the persistent shape of the domain.

Relationship map:
    User 1─* Graphic 1─1 Review 1─* Finding
                         Review 1─* CheckRun   (per-check health, for honest failures)
    User 1─* ReferenceGraphic                  (Tier 3 theme learning)
    BatchJob 1─* Graphic                       (Tier 3 batch mode)

Images are stored on disk (Graphic.stored_path); only the pointer + metadata live
in the DB. Bounding boxes are stored as 0..1 fractions of the canvas so the
frontend can position markers in %, independent of display size.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    CheckStatus,
    CheckType,
    FindingSource,
    FindingStatus,
    GraphicType,
    Platform,
    Role,
    Severity,
    Verdict,
)
from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    role: Mapped[Role] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Graphic(Base):
    __tablename__ = "graphics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)         # relative to upload_dir
    graphic_type: Mapped[GraphicType] = mapped_column(String)
    platform: Mapped[Platform] = mapped_column(String)
    canvas_w: Mapped[int] = mapped_column(Integer)
    canvas_h: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))

    # Versioning (Tier 3 re-check loop): revisions share a version_group_id and
    # point back to the graphic they revise.
    version_group_id: Mapped[str] = mapped_column(String, index=True, default=_uuid)
    parent_graphic_id: Mapped[str | None] = mapped_column(
        ForeignKey("graphics.id"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)

    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batch_jobs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    review: Mapped["Review | None"] = relationship(
        back_populates="graphic", uselist=False, cascade="all, delete-orphan"
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    graphic_id: Mapped[str] = mapped_column(ForeignKey("graphics.id"), unique=True)
    verdict: Mapped[Verdict] = mapped_column(String)
    reasoning: Mapped[str] = mapped_column(Text, default="")

    # Rolls up CheckRun health: "ok" | "partial" (some checks failed) | "failed".
    pipeline_status: Mapped[str] = mapped_column(String, default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    graphic: Mapped[Graphic] = relationship(back_populates="review")
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )
    check_runs: Mapped[list["CheckRun"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"))

    check_type: Mapped[CheckType] = mapped_column(String)
    severity: Mapped[Severity] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    suggested_fix: Mapped[str] = mapped_column(Text, default="")

    # Bounding box as 0..1 fractions of the canvas (None for non-spatial findings).
    # A pin is a point: is_pin=True with bbox_w == bbox_h == 0.
    bbox_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_h: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_pin: Mapped[bool] = mapped_column(Boolean, default=False)

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    source: Mapped[FindingSource] = mapped_column(String, default=FindingSource.ai)
    status: Mapped[FindingStatus] = mapped_column(String, default=FindingStatus.open)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    review: Mapped[Review] = relationship(back_populates="findings")


class CheckRun(Base):
    """Per-check execution record — powers honest failure handling in the UI."""
    __tablename__ = "check_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"))
    check_type: Mapped[CheckType] = mapped_column(String)
    status: Mapped[CheckStatus] = mapped_column(String)
    detail: Mapped[str] = mapped_column(Text, default="")     # e.g. "OCR returned no text"
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # Persisted token usage -> cost survives restarts (see /meta/cost).
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)

    review: Mapped[Review] = relationship(back_populates="check_runs")


class ReferenceGraphic(Base):
    """Approved reference graphic used to calibrate the theme check (Tier 3)."""
    __tablename__ = "reference_graphics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    stored_path: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String, default="")
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UsageEvent(Base):
    """Append-only cost ledger — one row per evaluation's Gemini usage.

    Deliberately NOT linked to Graphic/Review, so deleting graphics never erases
    spend history. `estimated_usd` is frozen at the price of the model actually
    used, so switching models later doesn't distort past cost.
    """
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    model: Mapped[str] = mapped_column(String)
    gemini_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BatchJob(Base):
    """A batch upload run (Tier 3) — drives the triage dashboard."""
    __tablename__ = "batch_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String, default="queued")  # queued|processing|done
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
