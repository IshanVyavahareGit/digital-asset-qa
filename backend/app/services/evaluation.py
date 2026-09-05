"""Evaluation service — the bridge between the pipeline and the database.

Given an uploaded image, it: (1) stores the bytes on disk, (2) reads the canvas
dimensions, (3) runs the check pipeline, and (4) persists Graphic + Review +
Findings + CheckRuns in one transaction. Both the single-upload route and the
batch worker call this, so persistence logic lives in exactly one place.
"""
from __future__ import annotations

import io
import uuid

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import HTTPException

def validate_aspect_ratio(image_bytes: bytes, platform: str) -> None:
    """Validate that the uploaded image matches the expected aspect ratio for the platform."""
    # Expected ratios (width / height)
    TARGETS = {
        "instagram_story": 1080 / 1920,
        "youtube_thumbnail": 1920 / 1080,
        "x_post": 1920 / 1080,
        "instagram_post": 1.0,
    }
    
    if platform not in TARGETS:
        return
        
    target_ratio = TARGETS[platform]
    
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
    except Exception:
        raise HTTPException(422, "Invalid image file")
        
    actual_ratio = w / h
    if abs(actual_ratio - target_ratio) > 0.05:
        expected = {
            "instagram_story": "9:16",
            "youtube_thumbnail": "16:9",
            "x_post": "16:9",
            "instagram_post": "1:1"
        }.get(platform, "the correct aspect ratio")
        
        import math
        divisor = math.gcd(w, h)
        fraction_str = f"{w // divisor}:{h // divisor}"
        
        raise HTTPException(
            422, 
            f"You selected {platform} which expects {expected}, "
            f"but uploaded an image that is {fraction_str}."
        )

from app.checks.base import CheckContext
from app.core.config import settings
from app.db.models import CheckRun, Finding, Graphic, Review, UsageEvent
from app.pipeline.orchestrator import evaluate
from app.services.gemini import Usage, usd_for

# Runtime-populated marker so the API/README can surface the demo's total cost.
_SESSION_USAGE = Usage()


def session_usage() -> Usage:
    return _SESSION_USAGE


def _record_usage(db: Session, usage: Usage) -> None:
    """Append one ledger row if this evaluation used Gemini (called before commit)."""
    if usage.calls == 0 and usage.input_tokens == 0:
        return  # deterministic-only run (e.g. no API key) — nothing to bill
    db.add(UsageEvent(
        model=settings.gemini_model or "(unset)",
        gemini_calls=usage.calls,
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        estimated_usd=usage.usd,   # frozen at the current model's price
    ))


def persisted_cost(db: Session) -> dict:
    """Lifetime Gemini usage + cost from the append-only ledger.

    Survives both service restarts AND deletion of graphics/reviews, and sums the
    per-row USD that was frozen at each call's model price (accurate across model
    switches).
    """
    calls, in_tok, out_tok, usd = db.execute(
        select(
            func.coalesce(func.sum(UsageEvent.gemini_calls), 0),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.estimated_usd), 0.0),
        )
    ).one()
    return {
        "current_model": settings.gemini_model or "(unset)",
        "gemini_calls": int(calls),
        "input_tokens": int(in_tok),
        "output_tokens": int(out_tok),
        "estimated_usd": round(float(usd), 6),
        "note": "Lifetime total from an append-only ledger; survives restarts and "
                "data deletion. USD frozen at each call's model price.",
    }


def delete_graphic_and_file(db: Session, graphic: Graphic) -> None:
    """Delete a graphic's image file, then the row.

    The ORM cascade removes the attached Review -> Findings/CheckRuns. The caller
    is responsible for committing (so bulk deletes can batch into one commit).
    """
    try:
        (settings.upload_dir / graphic.stored_path).unlink(missing_ok=True)
    except OSError:
        pass  # file already gone / unreadable — the DB row still gets removed
    db.delete(graphic)


def _store_image(image_bytes: bytes, filename: str) -> tuple[str, int, int, str]:
    """Persist bytes to the upload dir; return (stored_path, w, h, mime)."""
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    ext = (img.format or "PNG").lower()
    mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    (settings.upload_dir / stored_name).write_bytes(image_bytes)
    return stored_name, w, h, mime


async def evaluate_and_store(
    db: Session,
    *,
    image_bytes: bytes,
    filename: str,
    graphic_type: str,
    platform: str,
    user_id: str,
    version_group_id: str | None = None,
    parent_graphic_id: str | None = None,
    version: int = 1,
    batch_id: str | None = None,
    reference_images: list[tuple[bytes, str]] | None = None,
) -> Review:
    """Run the (DB-free) pipeline, then persist everything in ONE short commit.

    Important: we do NOT open a DB transaction while the pipeline runs. A mid-
    pipeline flush would hold a SQLite write lock for the pipeline's whole duration
    and serialize the batch to a crawl. Instead we generate ids up front, analyze,
    then write all rows at once.
    """
    stored_name, w, h, mime = _store_image(image_bytes, filename)

    ctx = CheckContext(
        image_bytes=image_bytes, mime_type=mime, canvas_w=w, canvas_h=h,
        graphic_type=graphic_type, platform=platform,
        reference_images=reference_images or [],
    )
    outcome = await evaluate(ctx)          # no DB connection held here
    _SESSION_USAGE.add(outcome.usage)
    _record_usage(db, outcome.usage)       # append-only ledger (survives deletes)

    # Explicit ids so children can reference parents without an intermediate flush.
    graphic_id = uuid.uuid4().hex
    review_id = uuid.uuid4().hex

    graphic = Graphic(
        id=graphic_id, filename=filename, stored_path=stored_name,
        graphic_type=graphic_type, platform=platform,
        canvas_w=w, canvas_h=h, uploaded_by=user_id,
        version_group_id=version_group_id or uuid.uuid4().hex,
        parent_graphic_id=parent_graphic_id, version=version, batch_id=batch_id,
    )
    review = Review(
        id=review_id, graphic_id=graphic_id, verdict=outcome.verdict.value,
        reasoning=outcome.reasoning, pipeline_status=outcome.pipeline_status,
    )
    db.add_all([graphic, review])
    db.add_all([
        CheckRun(
            review_id=review_id, check_type=r.check_type.value,
            status=r.status.value, detail=r.detail,
            confidence=r.confidence, duration_ms=r.duration_ms,
            input_tokens=r.usage.input_tokens, output_tokens=r.usage.output_tokens,
        )
        for r in outcome.check_results
    ])
    db.add_all([
        Finding(
            review_id=review_id, check_type=f.check_type.value,
            severity=f.severity.value, message=f.message, suggested_fix=f.suggested_fix,
            bbox_x=f.bbox.x if f.bbox else None, bbox_y=f.bbox.y if f.bbox else None,
            bbox_w=f.bbox.w if f.bbox else None, bbox_h=f.bbox.h if f.bbox else None,
            is_pin=f.is_pin, confidence=f.confidence,
            source=f.source.value, status="open",
        )
        for f in outcome.findings
    ])
    db.commit()          # single, short write transaction
    db.refresh(review)
    return review
