"""Domain vocabulary shared across the whole system.

These string enums are the single source of truth for roles, graphic/platform
types, check types, severities and verdicts. Using str-enums means they serialize
straight to JSON (e.g. "critical") and read cleanly in the API and the frontend.
"""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    designer = "designer"      # read-only: sees the final reviewed feedback
    manager = "manager"        # reviewer: runs QA, overrides findings, adds notes


class GraphicType(str, Enum):
    match_announcement = "match_announcement"
    bracket = "bracket"
    roster_update = "roster_update"


class Platform(str, Enum):
    """Drives which safe-zone (danger-zone) spec applies (brief §4)."""
    instagram_story = "instagram_story"    # 1080x1920
    youtube_thumbnail = "youtube_thumbnail"# 1920x1080
    x_post = "x_post"                      # 1920x1080
    instagram_post = "instagram_post"      # 1080x1080


class CheckType(str, Enum):
    typo_roster = "typo_roster"        # Gemini: OCR + roster cross-reference (spelling)
    matchup = "matchup"                # Gemini: VS pairings validated vs roster.matches
    sponsor_audit = "sponsor_audit"    # OpenCV: logo presence + visibility
    safe_zone = "safe_zone"            # geometry: critical elements vs danger zones
    design_theme = "design_theme"      # Gemini: palette / contrast / clutter / theme


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class Verdict(str, Enum):
    passed = "pass"                    # value is "pass"; name avoids the Python keyword
    needs_changes = "needs_changes"
    fail = "fail"


class FindingSource(str, Enum):
    ai = "ai"
    manager = "manager"


class FindingStatus(str, Enum):
    open = "open"            # stands as-is
    dismissed = "dismissed"  # manager rejected the AI finding
    edited = "edited"        # manager changed text/severity


class CheckStatus(str, Enum):
    """Honest failure handling — a check reports how well it actually ran."""
    ok = "ok"
    low_confidence = "low_confidence"
    failed = "failed"        # OCR/vision returned garbage -> surface, do NOT hallucinate
