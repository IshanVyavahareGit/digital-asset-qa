"""Reference graphics (Tier 3 theme learning).

A manager uploads approved graphics; the design/theme check can then calibrate
against them (passed to Gemini as extra visual context) in addition to the written
brand guide. Kept small: upload + list + fetch bytes helper.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_manager
from app.db.models import ReferenceGraphic, User
from app.db.session import get_db

router = APIRouter(prefix="/reference-graphics", tags=["references"])


class ReferenceOut(BaseModel):
    id: str
    label: str
    image_url: str


@router.post("", response_model=list[ReferenceOut])
async def upload_references(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
) -> list[ReferenceOut]:
    out: list[ReferenceOut] = []
    for f in files:
        data = await f.read()
        stored = f"ref_{uuid.uuid4().hex}.png"
        (settings.upload_dir / stored).write_bytes(data)
        ref = ReferenceGraphic(stored_path=stored, label=f.filename or "reference",
                               uploaded_by=user.id)
        db.add(ref); db.flush()
        out.append(ReferenceOut(id=ref.id, label=ref.label, image_url=f"/static/{stored}"))
    db.commit()
    return out


@router.get("", response_model=list[ReferenceOut])
def list_references(
    db: Session = Depends(get_db), user: User = Depends(require_manager),
) -> list[ReferenceOut]:
    refs = db.scalars(select(ReferenceGraphic)).all()
    return [ReferenceOut(id=r.id, label=r.label, image_url=f"/static/{r.stored_path}")
            for r in refs]


def _delete_ref_file(ref: ReferenceGraphic) -> None:
    try:
        (settings.upload_dir / ref.stored_path).unlink(missing_ok=True)
    except OSError:
        pass


@router.delete("/{ref_id}")
def delete_reference(
    ref_id: str, db: Session = Depends(get_db), user: User = Depends(require_manager),
) -> dict:
    ref = db.get(ReferenceGraphic, ref_id)
    if ref is None:
        raise HTTPException(404, "Reference graphic not found")
    _delete_ref_file(ref)
    db.delete(ref)
    db.commit()
    return {"deleted": ref_id}


@router.delete("", status_code=200)
def delete_all_references(
    db: Session = Depends(get_db), user: User = Depends(require_manager),
) -> dict:
    refs = db.scalars(select(ReferenceGraphic)).all()
    for ref in refs:
        _delete_ref_file(ref)
        db.delete(ref)
    db.commit()
    return {"deleted": len(refs)}


def load_reference_images(db: Session, limit: int = 3) -> list[tuple[bytes, str]]:
    """Load up to `limit` reference images as (bytes, mime) for the theme check."""
    refs = db.scalars(select(ReferenceGraphic).limit(limit)).all()
    images: list[tuple[bytes, str]] = []
    for r in refs:
        path = settings.upload_dir / r.stored_path
        if path.exists():
            images.append((path.read_bytes(), "image/png"))
    return images
