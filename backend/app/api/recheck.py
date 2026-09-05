"""Re-check loop (Tier 3): upload a revised version against an existing review.

The revision is stored as a new Graphic version in the same version group, then
re-evaluated. We diff the AI findings so the UI can mark what's resolved / still
present / newly introduced.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.serializers import review_out
from app.core.security import get_current_user
from app.db.models import Review, User
from app.db.session import get_db
from app.pipeline.diff import diff_findings
from app.schemas import FindingOut, ReviewOut
from app.services.evaluation import evaluate_and_store

router = APIRouter(prefix="/reviews", tags=["recheck"])


class RecheckResult(BaseModel):
    review: ReviewOut                    # the new version's review
    previous_review_id: str
    resolved: list[FindingOut]           # were present before, gone now
    persisting: list[FindingOut]         # still present
    new_findings: list[FindingOut]       # newly introduced


@router.post("/{review_id}/recheck", response_model=RecheckResult)
async def recheck(
    review_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),   # designers may submit revisions
) -> RecheckResult:
    original = db.get(Review, review_id)
    if original is None:
        raise HTTPException(404, "Review not found")
    og = original.graphic

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(422, "Empty file")

    new_review = await evaluate_and_store(
        db, image_bytes=image_bytes, filename=file.filename or "revision.png",
        graphic_type=og.graphic_type, platform=og.platform, user_id=user.id,
        version_group_id=og.version_group_id, parent_graphic_id=og.id,
        version=og.version + 1,
    )

    resolved, persisting, new_only = diff_findings(original.findings, new_review.findings)
    return RecheckResult(
        review=review_out(new_review), previous_review_id=original.id,
        resolved=[FindingOut.from_orm_finding(f) for f in resolved],
        persisting=[FindingOut.from_orm_finding(f) for f in persisting],
        new_findings=[FindingOut.from_orm_finding(f) for f in new_only],
    )
