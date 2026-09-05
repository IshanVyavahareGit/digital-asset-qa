"""Safe-zone check — pure geometry (brief §4).

Takes the critical elements located by the analyzer checks (handles, timings,
CTAs, logos) and tests each against the platform's danger zones. Danger zones are
specified in pixels on a reference canvas; we normalize both to 0..1 fractions and
compute overlap, so the test is resolution-independent and needs no AI.
"""
from __future__ import annotations

from app.checks.base import Check, CheckContext, CheckResult, RawFinding
from app.core.enums import CheckStatus, CheckType, Severity
from app.schemas import BBox
from app.services import assets

OVERLAP_FLAG = 0.12       # fraction of the element inside a zone that counts as intrusion
OVERLAP_CRITICAL = 0.45   # deep intrusion -> critical


class SafeZoneCheck(Check):
    check_type = CheckType.safe_zone

    async def run(self, ctx: CheckContext) -> CheckResult:
        spec = assets.safe_zones()["platforms"].get(ctx.platform)
        if spec is None:
            return CheckResult(
                self.check_type, CheckStatus.ok,
                detail=f"No safe-zone spec for platform '{ctx.platform}'.", confidence=1.0,
            )

        cw, ch = spec["canvas"]["w"], spec["canvas"]["h"]
        zones = [
            (z["label"], BBox(x=z["x"] / cw, y=z["y"] / ch, w=z["w"] / cw, h=z["h"] / ch))
            for z in spec["danger_zones"]
        ]

        critical = [e for e in ctx.located_elements if e.critical]
        if not critical:
            # Honest: we had nothing located to test (e.g. OCR failed upstream).
            return CheckResult(
                self.check_type, CheckStatus.low_confidence,
                detail="No critical elements were located, so safe-zones could not be fully verified.",
                confidence=0.3,
            )

        findings: list[RawFinding] = []
        for el in critical:
            for label, zone in zones:
                frac = _overlap_fraction(el.bbox, zone)
                if frac < OVERLAP_FLAG:
                    continue
                severity = Severity.critical if frac >= OVERLAP_CRITICAL else Severity.warning
                findings.append(RawFinding(
                    check_type=self.check_type, severity=severity,
                    message=(f"{el.kind.capitalize()} '{el.label}' sits inside the "
                             f"'{label}' danger zone ({frac * 100:.0f}% overlap)."),
                    suggested_fix=f"Move '{el.label}' out of the {label} area.",
                    bbox=el.bbox, confidence=round(min(1.0, frac + 0.4), 3),
                ))

        return CheckResult(
            self.check_type, CheckStatus.ok, findings=findings,
            detail=f"Tested {len(critical)} critical element(s) against {len(zones)} danger zone(s).",
            confidence=0.95,
        )


def _overlap_fraction(el: BBox, zone: BBox) -> float:
    """Area of (el ∩ zone) as a fraction of el's own area."""
    ix = max(0.0, min(el.x + el.w, zone.x + zone.w) - max(el.x, zone.x))
    iy = max(0.0, min(el.y + el.h, zone.y + zone.h) - max(el.y, zone.y))
    inter = ix * iy
    el_area = el.w * el.h
    return inter / el_area if el_area > 0 else 0.0
