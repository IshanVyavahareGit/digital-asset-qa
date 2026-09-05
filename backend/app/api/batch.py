"""Batch mode (Tier 3) — upload many graphics, process through a bounded async
queue, and poll a triage view.

The upload handler reads every file into memory (the request's UploadFiles are only
valid during the request), creates a BatchJob row, then fires a background task that
evaluates items concurrently with a semaphore. The client polls GET /batch/{id}.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.reviews import ReviewSummary, _summary
from app.core.enums import GraphicType, Platform, Verdict
from app.core.security import get_current_user, require_manager
from app.db.models import BatchJob, Review, User
from app.db.session import SessionLocal, get_db
from app.services.evaluation import evaluate_and_store, validate_aspect_ratio

router = APIRouter(prefix="/batch", tags=["batch"])

MAX_CONCURRENCY = 3  # cap parallel evaluations (each may call Gemini)


class BatchStatus(BaseModel):
    id: str
    status: str
    total: int
    completed: int
    failed: int
    reviews: list[ReviewSummary]


async def _process(batch_id: str, items: list[dict], user_id: str) -> None:
    """Background worker: evaluate items concurrently, updating progress."""
    _set_status(batch_id, "processing")
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _one(item: dict) -> None:
        async with sem:
            db = SessionLocal()
            try:
                await evaluate_and_store(
                    db, image_bytes=item["bytes"], filename=item["filename"],
                    graphic_type=item["graphic_type"], platform=item["platform"],
                    user_id=user_id, batch_id=batch_id,
                )
                _bump(batch_id, ok=True)
            except Exception:  # noqa: BLE001 — one bad graphic must not sink the batch
                _bump(batch_id, ok=False)
            finally:
                db.close()

    await asyncio.gather(*(_one(i) for i in items))
    _set_status(batch_id, "done")


def _set_status(batch_id: str, status: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(BatchJob, batch_id)
        if job:
            job.status = status
            db.commit()
    finally:
        db.close()


def _bump(batch_id: str, ok: bool) -> None:
    db = SessionLocal()
    try:
        job = db.get(BatchJob, batch_id)
        if job:
            job.completed += 1
            if not ok:
                job.failed += 1
            db.commit()
    finally:
        db.close()


@router.post("", response_model=BatchStatus)
async def create_batch(
    files: list[UploadFile] = File(...),
    graphic_types: list[str] = Form(...),
    platforms: list[str] = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
) -> BatchStatus:
    if not (len(files) == len(graphic_types) == len(platforms)):
        raise HTTPException(422, "files, graphic_types and platforms must be aligned")

    valid_types = {t.value for t in GraphicType}
    valid_plats = {p.value for p in Platform}
    items: list[dict] = []
    for f, gt, pl in zip(files, graphic_types, platforms):
        if gt not in valid_types or pl not in valid_plats:
            raise HTTPException(422, f"Invalid type/platform for {f.filename}")
            
        file_bytes = await f.read()
        
        try:
            validate_aspect_ratio(file_bytes, pl)
        except HTTPException as e:
            raise HTTPException(422, f"File {f.filename}: {e.detail}")
            
        items.append({
            "bytes": file_bytes, "filename": f.filename or "upload.png",
            "graphic_type": gt, "platform": pl,
        })

    job = BatchJob(status="queued", total=len(items), created_by=user.id)
    db.add(job); db.commit(); db.refresh(job)

    # Fire-and-forget on the event loop (concurrent with future requests).
    asyncio.create_task(_process(job.id, items, user.id))
    return _status(db, job)


@router.get("/{batch_id}", response_model=BatchStatus)
def get_batch(
    batch_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> BatchStatus:
    job = db.get(BatchJob, batch_id)
    if job is None:
        raise HTTPException(404, "Batch not found")
    return _status(db, job)


def _status(db: Session, job: BatchJob) -> BatchStatus:
    reviews = [r for r in db.query(Review).join(Review.graphic).all()
               if r.graphic.batch_id == job.id]
    order = {Verdict.fail.value: 0, Verdict.needs_changes.value: 1, Verdict.passed.value: 2}
    summaries = sorted((_summary(r) for r in reviews), key=lambda s: order[s.verdict.value])
    return BatchStatus(
        id=job.id, status=job.status, total=job.total,
        completed=job.completed, failed=job.failed, reviews=summaries,
    )
