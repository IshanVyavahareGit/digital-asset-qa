"""Finding mutation routes — the manager override / HITL flow (Tier 2).

A manager can dismiss an AI finding, edit its text/severity, or add their own
finding by dropping a pin or drawing a box with a comment. Any change recomputes
the review verdict so the badge always reflects the current state. Designers have
read-only access (these routes require the manager role).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.serializers import review_out
from app.core.enums import FindingSource, FindingStatus
from app.core.security import require_manager
from app.db.models import Finding, Review, User
from app.db.session import get_db
from app.pipeline.verdict import compute_verdict
from app.schemas import FindingUpdate, ManagerFindingCreate, ReviewOut

router = APIRouter(tags=["findings"])


def _recompute(db: Session, review: Review) -> None:
    """Re-derive the verdict from the current findings after any override."""
    verdict, reasoning = compute_verdict(review.findings, review.pipeline_status)
    review.verdict = verdict.value
    review.reasoning = reasoning


@router.patch("/findings/{finding_id}", response_model=ReviewOut)
def update_finding(
    finding_id: str, body: FindingUpdate,
    db: Session = Depends(get_db), user: User = Depends(require_manager),
) -> ReviewOut:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(404, "Finding not found")

    edited = False
    if body.message is not None:
        finding.message = body.message; edited = True
    if body.severity is not None:
        finding.severity = body.severity.value; edited = True
    if body.suggested_fix is not None:
        finding.suggested_fix = body.suggested_fix; edited = True
    if body.bbox is not None:
        # Reposition (manager drag). Persists the new coords; not a content edit,
        # so it doesn't flip an AI finding's status to "edited".
        finding.bbox_x, finding.bbox_y = body.bbox.x, body.bbox.y
        finding.bbox_w, finding.bbox_h = body.bbox.w, body.bbox.h
    if body.status is not None:
        finding.status = body.status.value
    elif edited and finding.status != FindingStatus.dismissed.value:
        # A content edit (without an explicit status) marks the finding as edited.
        finding.status = FindingStatus.edited.value

    review = finding.review
    _recompute(db, review)
    db.commit(); db.refresh(review)
    return review_out(review)


@router.post("/reviews/{review_id}/findings", response_model=ReviewOut)
def add_manager_finding(
    review_id: str, body: ManagerFindingCreate,
    db: Session = Depends(get_db), user: User = Depends(require_manager),
) -> ReviewOut:
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "Review not found")

    bbox = body.bbox
    finding = Finding(
        review_id=review.id, check_type=body.check_type.value,
        severity=body.severity.value, message=body.message,
        suggested_fix=body.suggested_fix,
        bbox_x=bbox.x if bbox else None, bbox_y=bbox.y if bbox else None,
        bbox_w=bbox.w if bbox else None, bbox_h=bbox.h if bbox else None,
        is_pin=body.is_pin, confidence=None,
        source=FindingSource.manager.value, status=FindingStatus.open.value,
    )
    db.add(finding)
    db.flush()
    _recompute(db, review)
    db.commit(); db.refresh(review)
    return review_out(review)


@router.delete("/findings/{finding_id}", response_model=ReviewOut)
def delete_finding(
    finding_id: str,
    db: Session = Depends(get_db), user: User = Depends(require_manager),
) -> ReviewOut:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(404, "Finding not found")
    # Only manager-added findings can be deleted; AI findings are dismissed, not removed
    # (keeps an audit trail of what the AI reported).
    if finding.source != FindingSource.manager.value:
        raise HTTPException(400, "AI findings can be dismissed but not deleted.")
    review = finding.review
    db.delete(finding)
    db.flush()
    _recompute(db, review)
    db.commit(); db.refresh(review)
    return review_out(review)
