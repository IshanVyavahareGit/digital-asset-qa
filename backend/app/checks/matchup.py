"""Matchup check — validates VS pairings against roster.matches.

Distinct from the typo check: that one verifies each NAME is spelled correctly in
isolation; this one verifies the RELATIONSHIP — that the two teams shown as
"A VS B" are actually a scheduled match, and (when a time is shown) that it matches
that pairing's scheduled time.

Same split as the typo check: Gemini extracts the pairings (structure), Python
judges them against the roster (deterministic). Skips the Gemini call entirely for
graphic types that have no matchups (e.g. roster_update).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.checks.base import Check, CheckContext, CheckResult, RawFinding
from app.core.enums import CheckStatus, CheckType, Severity
from app.services import assets
from app.services.gemini import GeminiUnavailable, box2d_to_bbox, gemini

# Graphic types that actually contain head-to-head pairings.
_MATCHUP_TYPES = {"match_announcement", "bracket"}


class Matchup(BaseModel):
    team_a: str = Field(description="First team name exactly as written")
    team_b: str = Field(description="Second team name exactly as written")
    time: str = Field(default="", description="Match time if shown next to the pairing, else ''")
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax] 0..1000 around the pairing")


class MatchupExtraction(BaseModel):
    has_matchups: bool
    matchups: list[Matchup]


_PROMPT = (
    "This is an esports match/bracket graphic. Identify every head-to-head matchup "
    "shown (two teams facing each other, usually joined by 'VS').\n"
    "For each, return: team_a and team_b exactly as written (verbatim, do not fix "
    "spelling); time (the match time shown for that pairing, or '' if none); and "
    "box_2d [ymin, xmin, ymax, xmax] (0-1000) around the pairing.\n"
    "Include placeholder slots like 'TBD' or 'Winner of ...' as written. "
    "If there are no matchups at all, set has_matchups=false and return an empty list."
)


class MatchupCheck(Check):
    check_type = CheckType.matchup

    async def run(self, ctx: CheckContext) -> CheckResult:
        # No matchups on rosters etc. -> skip the API call entirely.
        if ctx.graphic_type not in _MATCHUP_TYPES:
            return CheckResult(
                self.check_type, CheckStatus.ok,
                detail=f"No matchups expected for '{ctx.graphic_type}'.", confidence=1.0,
            )
        if not gemini.available:
            return CheckResult.failed(
                self.check_type, "AI matchup extraction unavailable (GEMINI_API_KEY not set)."
            )
        try:
            result = await gemini.generate(
                prompt=_PROMPT, image_bytes=ctx.image_bytes,
                mime_type=ctx.mime_type, schema=MatchupExtraction,
            )
        except GeminiUnavailable as exc:
            return CheckResult.failed(self.check_type, f"AI matchup extraction failed: {exc}")

        extraction: MatchupExtraction = result.parsed  # type: ignore[assignment]
        if not extraction.has_matchups or not extraction.matchups:
            return CheckResult(
                self.check_type, CheckStatus.ok, detail="No matchups detected.",
                confidence=0.8, usage=result.usage,
            )

        pairings = assets.scheduled_pairings()
        findings: list[RawFinding] = []
        reported: set[frozenset] = set()   # dedupe: a pairing can recur across bracket rounds
        validated = 0

        for mu in extraction.matchups:
            a, b = assets.resolve_team(mu.team_a), assets.resolve_team(mu.team_b)
            # Skip pairings we can't ground: unknown team (typo check owns spelling)
            # or a placeholder like "Winner of ...".
            if a is None or b is None or a == b:
                continue
            validated += 1
            bbox = box2d_to_bbox(mu.box_2d)
            key = frozenset({a, b})
            if key in reported:      # already flagged this pairing once
                continue

            if key not in pairings:
                reported.add(key)
                findings.append(RawFinding(
                    check_type=self.check_type, severity=Severity.critical,
                    message=f"'{a}' vs '{b}' is not a scheduled match in the roster.",
                    suggested_fix=f"Verify the matchup — '{a}' and '{b}' are not scheduled to play each other.",
                    bbox=bbox, confidence=0.9,
                ))
                continue

            # Pairing is valid — if a time is shown and the roster has a scheduled
            # time for this pairing, check they agree.
            shown = mu.time.strip().lower().replace(" ", "")
            scheduled = pairings[key]
            if shown and scheduled and not any(shown in s or s in shown for s in scheduled):
                reported.add(key)
                nice = " / ".join(sorted(scheduled))
                findings.append(RawFinding(
                    check_type=self.check_type, severity=Severity.warning,
                    message=f"'{a}' vs '{b}' shows time '{mu.time}' but is scheduled for {nice}.",
                    suggested_fix=f"Correct the match time for '{a}' vs '{b}'.",
                    bbox=bbox, confidence=0.7,
                ))

        return CheckResult(
            self.check_type, CheckStatus.ok, findings=findings,
            detail=f"Validated {validated} matchup(s).",
            confidence=0.85, usage=result.usage,
        )
