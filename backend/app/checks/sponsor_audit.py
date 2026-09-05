"""Sponsor audit — OpenCV multi-scale template matching (deterministic).

We have the *exact* sponsor logo PNGs, so this is a matching problem, not a VLM
problem. For each mandatory sponsor we slide its logo (resized across a scale
pyramid) over the graphic and take the best normalized-correlation score:

    score < PRESENT         -> missing (best correlation too low to be a real logo)
    score >= PRESENT        -> located; then judge *visibility* two ways:
        area_fraction < min      -> too small
        local contrast < CONTRAST_MIN -> faint / low-contrast / buried

Note: TM_CCOEFF_NORMED is invariant to brightness/contrast, so a faint logo still
scores high — that's why visibility is judged by the region's own local contrast
(grayscale std), not by the match score. Output is a pixel-exact box (0..1
fractions) + confidence. Thresholds are tuned for the demo pack and documented.
"""
from __future__ import annotations

import asyncio

import numpy as np

from app.checks.base import Check, CheckContext, CheckResult, LocatedElement, RawFinding
from app.core.enums import CheckStatus, CheckType, Severity
from app.schemas import BBox
from app.services import assets

PRESENT = 0.88          # min match score for a logo to count as present.
                        # Measured on the real logo pack: genuinely present logos
                        # score 0.974-1.000, while the pyramid's smallest scales
                        # (a 320x90 template shrunk to ~32x9) throw spurious
                        # matches up to 0.795 on graphics that lack the logo
                        # entirely. 0.88 sits in the middle of that gap.
CONTRAST_MIN = 22.0     # min grayscale std in the logo region (below -> faint/buried)
# Dense enough that thin logos (e.g. a bolt) match at their true scale; the tiny
# seeded logo sits at ~0.14 and normal logos at ~0.80. (Correctness over speed:
# a coarser pyramid mismatches scale-sensitive shapes.)
# Reaches past 1.0 because templates cropped from a source graphic appear at
# exactly the size they were cropped at (ratio 1.0); stopping at 0.84 made those
# impossible to find. 1.10 leaves headroom for a logo used slightly larger than
# the reference file.
SCALES = [0.10, 0.12, 0.14, 0.18, 0.22, 0.28, 0.36, 0.45, 0.55, 0.62, 0.70, 0.76,
          0.80, 0.84, 0.90, 1.00, 1.10]


class SponsorAuditCheck(Check):
    check_type = CheckType.sponsor_audit

    async def run(self, ctx: CheckContext) -> CheckResult:
        # CPU-bound OpenCV work runs in a thread so the event loop stays free.
        return await asyncio.to_thread(self._run_sync, ctx)

    def _run_sync(self, ctx: CheckContext) -> CheckResult:
        import cv2

        graphic = cv2.imdecode(
            np.frombuffer(ctx.image_bytes, np.uint8), cv2.IMREAD_COLOR
        )
        if graphic is None:
            return CheckResult.failed(
                self.check_type, "Could not decode the uploaded image for logo detection."
            )

        mandatory = assets.mandatory_sponsors(ctx.graphic_type)
        if not mandatory:
            return CheckResult(
                self.check_type,
                CheckStatus.ok,
                detail="No mandatory sponsors for this graphic type.",
                confidence=1.0,
            )

        # Template matching needs the actual logo PNGs. Report the gap honestly
        # instead of letting a FileNotFoundError surface as "Unexpected error".
        missing = [
            s["logo"] for s in mandatory
            if not assets.sponsor_logo_path(s["logo"]).exists()
        ]
        if missing:
            return CheckResult.failed(
                self.check_type,
                f"Sponsor logo assets missing from assets/sponsors/: {', '.join(missing)}. "
                "Add the reference logo PNGs to enable logo detection.",
            )

        min_area = assets.sponsor_manifest()["visibility_rules"]["min_area_fraction"]
        canvas_area = ctx.canvas_w * ctx.canvas_h
        findings: list[RawFinding] = []
        located: list[LocatedElement] = []
        scores: list[float] = []

        for sponsor in mandatory:
            template = assets.sponsor_logo_bgr(sponsor["logo"])
            score, box = _best_match(cv2, graphic, template)
            scores.append(score)
            name = sponsor["name"]

            if score < PRESENT:
                # Missing: anchor a pin in the expected sponsor row for spatial context.
                findings.append(RawFinding(
                    check_type=self.check_type, severity=Severity.critical,
                    message=f"Mandatory sponsor '{name}' is missing from this graphic.",
                    suggested_fix=f"Add the {name} logo to the sponsor row before publishing.",
                    bbox=BBox(x=0.5, y=0.9, w=0.0, h=0.0), is_pin=True,
                    confidence=round(1.0 - score, 3),
                ))
                continue

            x, y, w, h = box
            bbox = BBox(x=x / graphic.shape[1], y=y / graphic.shape[0],
                        w=w / graphic.shape[1], h=h / graphic.shape[0])
            area_frac = (w * h) / canvas_area
            contrast = _region_contrast(cv2, graphic, box)
            # A located logo is a critical element for the safe-zone check.
            located.append(LocatedElement(label=name, kind="logo", bbox=bbox, critical=True))

            if area_frac < min_area:
                findings.append(RawFinding(
                    check_type=self.check_type, severity=Severity.warning,
                    message=(f"Sponsor '{name}' is present but too small "
                             f"({area_frac * 100:.1f}% of canvas; min {min_area * 100:.0f}%)."),
                    suggested_fix=f"Enlarge the {name} logo so it is clearly legible.",
                    bbox=bbox, confidence=round(score, 3),
                ))
            elif contrast < CONTRAST_MIN:
                findings.append(RawFinding(
                    check_type=self.check_type, severity=Severity.warning,
                    message=(f"Sponsor '{name}' is faint / low-contrast against its "
                             f"background and may not be clearly visible."),
                    suggested_fix=f"Increase the {name} logo's opacity/contrast against its background.",
                    bbox=bbox, confidence=round(score, 3),
                ))
            # else: clearly present and visible -> no finding

        overall_conf = round(float(np.mean(scores)), 3) if scores else 1.0
        return CheckResult(
            self.check_type, CheckStatus.ok, findings=findings,
            detail=f"Checked {len(mandatory)} mandatory sponsor(s).",
            confidence=overall_conf, located_elements=located,
        )


def _region_contrast(cv2, graphic: np.ndarray, box: tuple[int, int, int, int]) -> float:
    """Local contrast (grayscale std) of the matched region.

    A crisp, opaque logo has high internal contrast (dark plate + bright icon/text);
    a faint or buried logo blends into its background and has low contrast.
    """
    x, y, w, h = box
    region = graphic[y : y + h, x : x + w]
    if region.size == 0:
        return 0.0
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    return float(gray.std())


def _best_match(cv2, graphic: np.ndarray, template: np.ndarray) -> tuple[float, tuple[int, int, int, int]]:
    """Return (best_score, (x, y, w, h)) across the scale pyramid."""
    gh, gw = graphic.shape[:2]
    th0, tw0 = template.shape[:2]
    best_score, best_box = -1.0, (0, 0, 0, 0)
    for s in SCALES:
        tw, th = int(tw0 * s), int(th0 * s)
        if tw < 12 or th < 8 or tw > gw or th > gh:
            continue
        resized = cv2.resize(template, (tw, th))
        res = cv2.matchTemplate(graphic, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score, best_box = float(max_val), (max_loc[0], max_loc[1], tw, th)
    return best_score, best_box
