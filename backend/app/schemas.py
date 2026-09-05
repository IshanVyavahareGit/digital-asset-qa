"""API schemas — the typed contract between backend and frontend.

Everything the frontend renders (findings, boxes, verdict, per-check health) is
defined here as Pydantic models. The frontend consumes this JSON directly; it
never regex-parses free text. Bounding boxes are 0..1 fractions of the canvas.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

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

# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    role: Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --------------------------------------------------------------------------- #
# Findings (the core visual-QA unit)
# --------------------------------------------------------------------------- #


class BBox(BaseModel):
    """Bounding box as fractions of the canvas (0..1). A pin has w == h == 0."""
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(ge=0, le=1)
    h: float = Field(ge=0, le=1)


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    check_type: CheckType
    severity: Severity
    message: str
    suggested_fix: str
    bbox: BBox | None = None
    is_pin: bool
    confidence: float | None
    source: FindingSource
    status: FindingStatus

    @classmethod
    def from_orm_finding(cls, f) -> "FindingOut":
        bbox = None
        if f.bbox_x is not None and f.bbox_y is not None:
            bbox = BBox(x=f.bbox_x, y=f.bbox_y, w=f.bbox_w or 0.0, h=f.bbox_h or 0.0)
        return cls(
            id=f.id,
            check_type=f.check_type,
            severity=f.severity,
            message=f.message,
            suggested_fix=f.suggested_fix,
            bbox=bbox,
            is_pin=f.is_pin,
            confidence=f.confidence,
            source=f.source,
            status=f.status,
        )


class ManagerFindingCreate(BaseModel):
    """Manager draws a box or drops a pin and adds a comment (Tier 2 HITL)."""
    message: str
    severity: Severity = Severity.warning
    suggested_fix: str = ""
    bbox: BBox | None = None
    is_pin: bool = False
    check_type: CheckType = CheckType.design_theme


class FindingUpdate(BaseModel):
    """Manager override: edit text, change severity, dismiss, or reposition (Tier 2 HITL)."""
    message: str | None = None
    severity: Severity | None = None
    suggested_fix: str | None = None
    status: FindingStatus | None = None
    bbox: BBox | None = None       # new position after a manager drag (AI or manager marker)


# --------------------------------------------------------------------------- #
# Checks & reviews
# --------------------------------------------------------------------------- #


class CheckRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    check_type: CheckType
    status: CheckStatus
    detail: str
    confidence: float | None
    duration_ms: int


class GraphicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    graphic_type: GraphicType
    platform: Platform
    canvas_w: int
    canvas_h: int
    version: int
    version_group_id: str
    image_url: str


class ReviewOut(BaseModel):
    """Full review payload for the workspace: image meta + findings + health."""
    id: str
    verdict: Verdict
    reasoning: str
    pipeline_status: str
    graphic: GraphicOut
    findings: list[FindingOut]
    check_runs: list[CheckRunOut]
    created_at: datetime
