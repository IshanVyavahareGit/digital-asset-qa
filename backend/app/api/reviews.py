"""Review read routes.

Both roles can read reviews (the designer view is read-only; the manager view adds
override controls in the frontend). Listing powers the dashboard / batch triage.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import review_out
from app.core.enums import Verdict
from app.core.security import get_current_user, require_manager
from app.db.models import Review, User
from app.db.session import get_db
from app.schemas import ReviewOut
from app.services.evaluation import delete_graphic_and_file

router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewSummary(BaseModel):
    """Lightweight row for the triage dashboard — one per version lineage."""
    id: str                    # the LATEST review in the lineage
    graphic_id: str
    filename: str
    graphic_type: str
    platform: str
    verdict: Verdict
    image_url: str
    critical_count: int
    warning_count: int
    version: int               # latest version number
    versions: int = 1          # how many versions exist in this lineage
    version_group_id: str = ""


class VersionItem(BaseModel):
    """One entry in a graphic's revision history (parent + revisions)."""
    review_id: str
    version: int
    verdict: Verdict
    is_latest: bool            # older versions render as REVISED (superseded)
    critical_count: int
    warning_count: int
    created_at: datetime


def _counts(r: Review) -> tuple[int, int]:
    active = [f for f in r.findings if f.status != "dismissed"]
    return (
        sum(f.severity == "critical" for f in active),
        sum(f.severity == "warning" for f in active),
    )


def _summary(r: Review, versions: int = 1) -> ReviewSummary:
    crit, warn = _counts(r)
    return ReviewSummary(
        id=r.id, graphic_id=r.graphic_id, filename=r.graphic.filename,
        graphic_type=r.graphic.graphic_type, platform=r.graphic.platform,
        verdict=r.verdict, image_url=f"/static/{r.graphic.stored_path}",
        critical_count=crit, warning_count=warn,
        version=r.graphic.version, versions=versions,
        version_group_id=r.graphic.version_group_id,
    )


@router.get("", response_model=list[ReviewSummary])
def list_reviews(
    batch_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ReviewSummary]:
    stmt = select(Review).join(Review.graphic).order_by(Review.created_at.desc())
    reviews = db.scalars(stmt).all()
    if batch_id:
        reviews = [r for r in reviews if r.graphic.batch_id == batch_id]

    # Collapse each version lineage to a single card: the LATEST version, plus a
    # count of how many versions exist. Revisions no longer appear as separate,
    # confusable entries on the dashboard.
    groups: dict[str, list[Review]] = {}
    for r in reviews:
        groups.setdefault(r.graphic.version_group_id, []).append(r)

    summaries = [
        _summary(max(revs, key=lambda r: r.graphic.version), versions=len(revs))
        for revs in groups.values()
    ]
    # Sort worst-first so the triage dashboard surfaces failures at the top.
    order = {Verdict.fail.value: 0, Verdict.needs_changes.value: 1, Verdict.passed.value: 2}
    return sorted(summaries, key=lambda s: order[s.verdict.value])


@router.get("/{review_id}/versions", response_model=list[VersionItem])
def review_versions(
    review_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[VersionItem]:
    """Full revision history for the lineage this review belongs to (v1..vN)."""
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "Review not found")
    vgid = review.graphic.version_group_id

    lineage = [
        r for r in db.scalars(select(Review).join(Review.graphic)).all()
        if r.graphic.version_group_id == vgid
    ]
    lineage.sort(key=lambda r: r.graphic.version)
    latest_v = max((r.graphic.version for r in lineage), default=1)

    items: list[VersionItem] = []
    for r in lineage:
        crit, warn = _counts(r)
        items.append(VersionItem(
            review_id=r.id, version=r.graphic.version, verdict=r.verdict,
            is_latest=(r.graphic.version == latest_v),
            critical_count=crit, warning_count=warn, created_at=r.created_at,
        ))
    return items


@router.get("/{review_id}", response_model=ReviewOut)
def get_review(
    review_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReviewOut:
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "Review not found")
    return review_out(review)


@router.delete("/{review_id}")
def delete_review(
    review_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
) -> dict:
    """Delete a review by id — removes its graphic, image file and findings."""
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "Review not found")
    delete_graphic_and_file(db, review.graphic)  # cascade removes the review
    db.commit()
    return {"deleted": review_id}
