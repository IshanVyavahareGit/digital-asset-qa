"""Design & theme check — Gemini visual design review.

The brand guide (palette hex, approved fonts, tone, rules) is passed in the prompt
and Gemini returns structured findings for off-palette colours, poor text contrast,
cluttered layout and theme-spec deviation — each with a box, severity and fix. No
colour math or WCAG computation (a deliberate product decision).

Tier 3 "theme learning": if approved reference graphics are supplied, they are
passed as extra visual context so the review calibrates against real examples in
addition to the written guide.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.checks.base import Check, CheckContext, CheckResult, RawFinding
from app.core.enums import CheckStatus, CheckType, Severity
from app.services import assets
from app.services.gemini import GeminiUnavailable, box2d_to_bbox, gemini

_ISSUE_KINDS = "off_palette | low_contrast | clutter | off_theme"


class DesignFinding(BaseModel):
    issue: str = Field(description=f"one of: {_ISSUE_KINDS}")
    severity: str = Field(description="one of: info, warning, critical")
    message: str
    suggested_fix: str
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax], 0..1000")


class DesignReview(BaseModel):
    on_brand: bool = Field(description="true if the graphic broadly follows the brand guide")
    findings: list[DesignFinding]


def _build_prompt(brand: dict, calibrated: bool) -> str:
    guide = json.dumps(
        {k: brand[k] for k in ("tone", "palette", "approved_fonts", "rules")}, indent=2
    )
    calib = (
        "You are also given APPROVED reference graphics first — treat them as the "
        "gold standard for on-brand look and calibrate your judgement to them.\n"
        if calibrated else ""
    )
    return (
        "You are an art director doing a brand QA pass on an esports graphic.\n"
        f"{calib}"
        "Here is the brand guide:\n"
        f"{guide}\n\n"
        "IMPORTANT — the brand's neon palette colours (cyan, magenta, purple) used as "
        "text or accents ON the dark navy background are the INTENDED, on-brand, "
        "high-contrast look. Never flag brand-palette colours on a dark background as "
        "off_palette or low_contrast. They are correct by design.\n\n"
        "ALSO IMPORTANT — DO NOT flag sponsor logos for being off_palette or off_theme. "
        "Sponsor logos are permitted to use their own brand colors and do not need to "
        "match the esports brand guide.\n\n"
        "Flag ONLY clear, obvious deviations in these categories:\n"
        "- off_palette: prominent colours that are clearly NOT in the palette and not "
        "close to it.\n"
        "- low_contrast: text and its immediate background are so close in luminance "
        "that it is genuinely hard to read (e.g. dark text on a dark area, or light "
        "text on a light/washed-out area). Do NOT flag otherwise.\n"
        "- clutter: crowded layout with no clear focal hierarchy.\n"
        "- off_theme: breaks the stated dark & neon tone, e.g. a light/washed-out "
        "background.\n\n"
        "Be conservative: prefer FEW, high-confidence findings over many weak ones. "
        "When in doubt, do NOT flag. If the graphic broadly follows the guide, set "
        "on_brand=true and return an empty findings list.\n"
        "For each finding give a box_2d [ymin, xmin, ymax, xmax] (0-1000) around the "
        "offending region, a severity, a short message and a concrete fix."
    )


_SEVERITY = {"info": Severity.info, "warning": Severity.warning, "critical": Severity.critical}


class DesignThemeCheck(Check):
    check_type = CheckType.design_theme

    async def run(self, ctx: CheckContext) -> CheckResult:
        if not gemini.available:
            return CheckResult.failed(
                self.check_type, "AI design review unavailable (GEMINI_API_KEY not set)."
            )
        brand = assets.brand_guide()
        calibrated = bool(ctx.reference_images)
        try:
            result = await gemini.generate(
                prompt=_build_prompt(brand, calibrated),
                image_bytes=ctx.image_bytes, mime_type=ctx.mime_type,
                schema=DesignReview, extra_images=ctx.reference_images or None,
            )
        except GeminiUnavailable as exc:
            return CheckResult.failed(self.check_type, f"AI design review failed: {exc}")

        review: DesignReview = result.parsed  # type: ignore[assignment]
        findings = [
            RawFinding(
                check_type=self.check_type,
                severity=_SEVERITY.get(f.severity.lower(), Severity.warning),
                message=f.message, suggested_fix=f.suggested_fix,
                bbox=box2d_to_bbox(f.box_2d), confidence=0.8,
            )
            for f in review.findings
        ]
        detail = "Calibrated against reference graphics. " if calibrated else ""
        return CheckResult(
            self.check_type, CheckStatus.ok, findings=findings,
            detail=detail + ("On-brand." if review.on_brand else "Brand deviations found."),
            confidence=0.8, usage=result.usage,
        )
