"""Graphic upload + evaluate (Tier 1 core entrypoint).

A manager uploads one graphic and selects its type + platform; the pipeline runs
and the persisted review (findings + boxes + verdict) is returned for the workspace.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import review_out
from app.core.enums import GraphicType, Platform
from app.core.security import require_manager
from app.db.models import Graphic, User
from app.db.session import get_db
from app.schemas import ReviewOut
from app.services.evaluation import delete_graphic_and_file, evaluate_and_store, validate_aspect_ratio

router = APIRouter(prefix="/graphics", tags=["graphics"])


def _validate(graphic_type: str, platform: str) -> None:
    if graphic_type not in {t.value for t in GraphicType}:
        raise HTTPException(422, f"Invalid graphic_type '{graphic_type}'")
    if platform not in {p.value for p in Platform}:
        raise HTTPException(422, f"Invalid platform '{platform}'")


@router.post("", response_model=ReviewOut)
async def upload_and_evaluate(
    file: UploadFile = File(...),
    graphic_type: str = Form(...),
    platform: str = Form(...),
    use_reference_theme: bool = Form(False),   # Tier 3: calibrate theme vs references
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
) -> ReviewOut:
    _validate(graphic_type, platform)
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(422, "Empty file")
        
    validate_aspect_ratio(image_bytes, platform)

    reference_images = None
    if use_reference_theme:
        from app.api.references import load_reference_images
        reference_images = load_reference_images(db) or None

    review = await evaluate_and_store(
        db, image_bytes=image_bytes, filename=file.filename or "upload.png",
        graphic_type=graphic_type, platform=platform, user_id=user.id,
        reference_images=reference_images,
    )
    return review_out(review)


@router.delete("/{graphic_id}")
def delete_graphic(
    graphic_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
) -> dict:
    """Delete one graphic + its image file + its review/findings (cascade)."""
    graphic = db.get(Graphic, graphic_id)
    if graphic is None:
        raise HTTPException(404, "Graphic not found")
    delete_graphic_and_file(db, graphic)
    db.commit()
    return {"deleted": graphic_id}


@router.delete("", status_code=200)
def delete_all_graphics(
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
) -> dict:
    """Wipe all graphics/reviews/findings + their image files (test reset)."""
    graphics = db.scalars(select(Graphic)).all()
    for g in graphics:
        delete_graphic_and_file(db, g)
    db.commit()
    return {"deleted": len(graphics)}
