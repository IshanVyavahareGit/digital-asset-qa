"""Base types shared by every check.

A check is a small, self-contained unit that receives a `CheckContext` (the image
plus its metadata) and returns a `CheckResult` (a health status + a list of
`RawFinding`s). Checks are deliberately uniform so the orchestrator can run them
all concurrently and treat their outputs identically — whether the check is an
LLM call, an OpenCV routine, or pure geometry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.enums import CheckStatus, CheckType, FindingSource, Severity
from app.schemas import BBox
from app.services.gemini import Usage


@dataclass
class LocatedElement:
    """A located, classified element on the graphic (handle/time/cta/logo).

    Produced by the analyzer checks and consumed by SafeZoneCheck, which is pure
    geometry and has no detector of its own.
    """
    label: str
    kind: str                # "handle" | "time" | "cta" | "team" | "logo"
    bbox: BBox
    critical: bool = True    # only critical elements must avoid danger zones


@dataclass
class CheckContext:
    image_bytes: bytes
    mime_type: str
    canvas_w: int
    canvas_h: int
    graphic_type: str        # GraphicType value
    platform: str            # Platform value
    # Optional reference images (Tier 3 theme learning); (bytes, mime) tuples.
    reference_images: list[tuple[bytes, str]] = field(default_factory=list)
    # Filled by the orchestrator (from analyzer artifacts) before SafeZoneCheck runs.
    located_elements: list[LocatedElement] = field(default_factory=list)


@dataclass
class RawFinding:
    """A finding before it is persisted (no DB ids yet)."""
    check_type: CheckType
    severity: Severity
    message: str
    suggested_fix: str = ""
    bbox: BBox | None = None
    is_pin: bool = False
    confidence: float | None = None
    source: FindingSource = FindingSource.ai


@dataclass
class CheckResult:
    check_type: CheckType
    status: CheckStatus
    findings: list[RawFinding] = field(default_factory=list)
    detail: str = ""                       # human-readable health note
    confidence: float | None = None
    usage: Usage = field(default_factory=Usage)
    duration_ms: int = 0                   # filled in by the orchestrator
    # Located elements this check contributes to SafeZoneCheck (e.g. handle boxes).
    located_elements: list[LocatedElement] = field(default_factory=list)

    @classmethod
    def failed(cls, check_type: CheckType, detail: str) -> "CheckResult":
        """Honest failure: report the check couldn't run, emit NO findings."""
        return cls(check_type=check_type, status=CheckStatus.failed, detail=detail)


class Check(ABC):
    """Interface every check implements."""

    check_type: CheckType

    @abstractmethod
    async def run(self, ctx: CheckContext) -> CheckResult: ...
