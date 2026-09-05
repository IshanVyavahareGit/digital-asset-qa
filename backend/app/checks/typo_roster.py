"""Typo & roster check — Gemini OCR + deterministic cross-reference.

Split of responsibilities (deliberate, and easy to defend):
  - Gemini does PURE extraction: every text element, verbatim, classified as
    handle/team/time/cta/other, with a 0..1000 box. It never sees the roster, so
    it cannot silently "auto-correct" a seeded typo.
  - Python does the cross-reference against roster.json using fuzzy matching, and
    decides severity. This logic is deterministic and unit-testable.

Also contributes the located critical text elements (handles/times/teams/CTAs) that
SafeZoneCheck needs.
"""
from __future__ import annotations

import difflib

from pydantic import BaseModel, Field

from app.checks.base import Check, CheckContext, CheckResult, LocatedElement, RawFinding
from app.core.enums import CheckStatus, CheckType, FindingSource, Severity
from app.services import assets
from app.services.gemini import GeminiUnavailable, box2d_to_bbox, gemini

# --- Gemini response schema (pure OCR, no correction) ------------------------


class TextElement(BaseModel):
    text: str = Field(description="Exact text, verbatim. Do NOT fix spelling.")
    kind: str = Field(description="one of: handle, team, time, cta, other")
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax], 0..1000")


class TextExtraction(BaseModel):
    readable: bool = Field(description="false if the image has no legible text")
    elements: list[TextElement]


_PROMPT = (
    "You are a precise OCR and layout extractor for an esports marketing graphic.\n"
    "Extract EVERY distinct line of text you can read. For each, return:\n"
    "  - text: the exact characters, VERBATIM. Never correct spelling or spacing.\n"
    "  - kind: one of 'handle' (a player gamer-tag/username, often stylised with "
    "digits/symbols), 'team' (a team name), 'time' (a match time or date), "
    "'cta' (a call to action like 'Watch Live'), or 'other' (titles, 'VS', event "
    "names, labels, sponsor names).\n"
    "  - box_2d: bounding box as [ymin, xmin, ymax, xmax] normalized to 0-1000.\n"
    "If there is no legible text at all, set readable=false and return an empty list.\n"
    "Do not invent text that is not visibly present."
)

_CRITICAL_KINDS = {"handle", "team", "time", "cta"}


class TypoRosterCheck(Check):
    check_type = CheckType.typo_roster

    async def run(self, ctx: CheckContext) -> CheckResult:
        if not gemini.available:
            return CheckResult.failed(
                self.check_type, "AI OCR unavailable (GEMINI_API_KEY not set)."
            )
        try:
            result = await gemini.generate(
                prompt=_PROMPT, image_bytes=ctx.image_bytes,
                mime_type=ctx.mime_type, schema=TextExtraction,
            )
        except GeminiUnavailable as exc:
            return CheckResult.failed(self.check_type, f"AI OCR failed: {exc}")

        extraction: TextExtraction = result.parsed  # type: ignore[assignment]

        # Honest failure: model says nothing legible -> surface it, emit no findings.
        if not extraction.readable or not extraction.elements:
            return CheckResult(
                self.check_type, CheckStatus.failed,
                detail="OCR returned no legible text — cannot verify handles/timings.",
                usage=result.usage, confidence=0.0,
            )

        findings: list[RawFinding] = []
        located: list[LocatedElement] = []
        handles = assets.known_handles()
        teams = assets.known_team_names()
        valid_times = _valid_time_tokens()

        for el in extraction.elements:
            bbox = box2d_to_bbox(el.box_2d)
            text = el.text.strip()
            if el.kind in _CRITICAL_KINDS:
                located.append(LocatedElement(label=text, kind=el.kind, bbox=bbox))

            if el.kind == "handle":
                findings.extend(_check_member(text, handles, bbox, "player handle"))
            elif el.kind == "team":
                findings.extend(_check_member(text, teams, bbox, "team name"))
            elif el.kind == "time":
                findings.extend(_check_time(text, valid_times, bbox))

        return CheckResult(
            self.check_type, CheckStatus.ok, findings=findings,
            detail=f"Read {len(extraction.elements)} text element(s).",
            confidence=0.9, usage=result.usage, located_elements=located,
        )


# --- deterministic cross-reference helpers -----------------------------------


def _check_member(text: str, known: tuple[str, ...], bbox, label: str) -> list[RawFinding]:
    """Exact match -> ok. Close match -> typo. No close match -> unrecognized.

    Matching is case-insensitive: graphics routinely upper-case names ("VOID
    REAPERS") while the roster stores title case ("Void Reapers"); casing is a
    styling choice, not a spelling error.
    """
    lowered = {k.lower(): k for k in known}   # lowercase -> canonical spelling
    t = text.lower()
    if t in lowered:
        return []
    close = difflib.get_close_matches(t, list(lowered), n=1, cutoff=0.6)
    if close:
        canonical = lowered[close[0]]
        ratio = difflib.SequenceMatcher(None, t, close[0]).ratio()
        return [RawFinding(
            check_type=CheckType.typo_roster, severity=Severity.critical,
            message=f"Misspelled {label}: '{text}' — did you mean '{canonical}'?",
            suggested_fix=f"Correct '{text}' to '{canonical}'.",
            bbox=bbox, confidence=round(ratio, 3),
        )]
    return [RawFinding(
        check_type=CheckType.typo_roster, severity=Severity.warning,
        message=f"Unrecognized {label}: '{text}' is not in the roster.",
        suggested_fix=f"Verify '{text}' against the official roster.",
        bbox=bbox, confidence=0.5,
    )]


def _check_time(text: str, valid_times: set[str], bbox) -> list[RawFinding]:
    norm = text.lower().replace(" ", "")
    if any(v in norm or norm in v for v in valid_times):
        return []
    return [RawFinding(
        check_type=CheckType.typo_roster, severity=Severity.warning,
        message=f"Match time '{text}' does not match any scheduled match in the roster.",
        suggested_fix="Confirm the match time against roster.json.",
        bbox=bbox, confidence=0.6,
    )]


def _valid_time_tokens() -> set[str]:
    tokens: set[str] = set()
    for m in assets.roster()["matches"]:
        tokens.add(m["time_label"].lower().replace(" ", ""))  # e.g. "7:00pm"
        if m.get("time_utc"):  # skip empty: "" is a substring of everything -> matches all
            tokens.add(m["time_utc"][:10])                    # e.g. "2026-07-18"
    return tokens
