"""Asset repository — the single gateway to the asset pack.

Checks never read files directly; they ask this module for the roster, sponsor
manifest, brand guide, safe-zone spec, or a sponsor logo image. The JSON files are
cached in memory (they don't change at runtime). Swapping in the *real* asset pack
later is just replacing the files under assets/.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.config import settings


def _load(name: str) -> dict:
    return json.loads((settings.assets_dir / name).read_text())


@lru_cache
def roster() -> dict:
    return _load("roster.json")


@lru_cache
def sponsor_manifest() -> dict:
    return _load("sponsor_manifest.json")


@lru_cache
def brand_guide() -> dict:
    return _load("brand_guide.json")


@lru_cache
def safe_zones() -> dict:
    return _load("safe_zones.json")


@lru_cache
def known_handles() -> tuple[str, ...]:
    """Flat, deduped tuple of every correct player handle (for typo checks)."""
    handles = {p for t in roster()["teams"] for p in t["players"]}
    return tuple(sorted(handles))


@lru_cache
def known_team_names() -> tuple[str, ...]:
    """Every accepted spelling of a team: full name + tag + any aliases.

    Graphics refer to a team by its full name ("S8UL Esports") in one place and its
    short tag ("S8UL") in another (e.g. brackets); both are correct.
    """
    names: set[str] = set()
    for t in roster()["teams"]:
        names.add(t["name"])
        if t.get("tag"):
            names.add(t["tag"])
        names.update(t.get("aliases", []) or [])
    return tuple(sorted(names))


@lru_cache
def _team_lookup() -> dict[str, str]:
    """lowercased name / tag / alias -> canonical team name."""
    lut: dict[str, str] = {}
    for t in roster()["teams"]:
        canon = t["name"]
        lut[t["name"].strip().lower()] = canon
        if t.get("tag"):
            lut[t["tag"].strip().lower()] = canon
        for alias in t.get("aliases", []) or []:
            lut[alias.strip().lower()] = canon
    return lut


def resolve_team(text: str) -> str | None:
    """Map any written team name/tag/alias to its canonical roster name (exact,
    case-insensitive). Returns None for unknown teams or placeholders like
    'Winner of Upper Bracket Final' — the matchup check skips those."""
    return _team_lookup().get(text.strip().lower())


@lru_cache
def scheduled_pairings() -> dict[frozenset, set]:
    """Unordered {teamA, teamB} -> set of scheduled time tokens.

    Only pairings where BOTH sides resolve to a known team are included (TBD /
    'Winner of…' placeholders are skipped). Time tokens are normalized like the
    typo check ('7:00 PM' -> '7:00pm'); empty when the match has no listed time.
    """
    pairings: dict[frozenset, set] = {}
    for m in roster()["matches"]:
        a, b = resolve_team(m["team_a"]), resolve_team(m["team_b"])
        if a is None or b is None or a == b:
            continue
        key = frozenset({a, b})
        pairings.setdefault(key, set())
        if m.get("time_label"):
            pairings[key].add(m["time_label"].lower().replace(" ", ""))
    return pairings


def mandatory_sponsors(graphic_type: str) -> list[dict]:
    """Sponsor records mandatory for a graphic type, in manifest order."""
    manifest = sponsor_manifest()
    by_id = {s["id"]: s for s in manifest["sponsors"]}
    return [by_id[sid] for sid in manifest["mandatory_by_type"].get(graphic_type, [])]


def sponsor_logo_path(logo_filename: str) -> Path:
    return settings.assets_dir / "sponsors" / logo_filename


@lru_cache
def sponsor_logo_bgr(logo_filename: str) -> "np.ndarray":
    """Load a sponsor logo as an OpenCV BGR array (cached; used as a template).

    Transparent PNGs are alpha-composited rather than read with IMREAD_COLOR.
    IMREAD_COLOR *discards* alpha, which leaves every anti-aliased edge pixel at
    full intensity instead of its blended value — and those edges are what drives
    correlation. Measured on the real logo pack, that cost ~0.08 of match score
    (Predator 0.974 -> 0.899) and halved the gap to spurious matches. Compositing
    restores it. The fill colour makes no measurable difference (black, brand
    navy and dark grey all scored identically), so black is used.
    """
    import cv2  # local import keeps cv2 out of the import path for non-CV code

    img = cv2.imread(str(sponsor_logo_path(logo_filename)), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Sponsor logo not found: {logo_filename}")
    if img.ndim == 2:  # grayscale
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:  # BGRA -> premultiply over black
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        return (img[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return img
