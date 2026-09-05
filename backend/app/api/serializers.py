"""ORM -> API serializers, kept in one place so every route returns the same shape."""
from __future__ import annotations

from app.db.models import Graphic, Review
from app.schemas import CheckRunOut, FindingOut, GraphicOut, ReviewOut


def graphic_out(g: Graphic) -> GraphicOut:
    return GraphicOut(
        id=g.id, filename=g.filename, graphic_type=g.graphic_type, platform=g.platform,
        canvas_w=g.canvas_w, canvas_h=g.canvas_h, version=g.version,
        version_group_id=g.version_group_id,
        image_url=f"/static/{g.stored_path}",
    )


def review_out(review: Review) -> ReviewOut:
    return ReviewOut(
        id=review.id, verdict=review.verdict, reasoning=review.reasoning,
        pipeline_status=review.pipeline_status, graphic=graphic_out(review.graphic),
        findings=[FindingOut.from_orm_finding(f) for f in review.findings],
        check_runs=[CheckRunOut.model_validate(c) for c in review.check_runs],
        created_at=review.created_at,
    )
