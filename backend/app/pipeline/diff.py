"""Finding diff for the re-check loop (Tier 3).

Compares the AI findings of an original review with those of a revised upload and
buckets them into resolved / persisting / new. Two findings "correspond" when they
share a check type and either the same message or overlapping boxes (IoU > 0.4).
Manager annotations are ignored — we only diff what the AI reported.
"""
from __future__ import annotations

from app.db.models import Finding

IOU_MATCH = 0.4


def _iou(a: Finding, b: Finding) -> float:
    if None in (a.bbox_x, b.bbox_x):
        return 0.0
    ax2, ay2 = a.bbox_x + (a.bbox_w or 0), a.bbox_y + (a.bbox_h or 0)
    bx2, by2 = b.bbox_x + (b.bbox_w or 0), b.bbox_y + (b.bbox_h or 0)
    ix = max(0.0, min(ax2, bx2) - max(a.bbox_x, b.bbox_x))
    iy = max(0.0, min(ay2, by2) - max(a.bbox_y, b.bbox_y))
    inter = ix * iy
    union = (a.bbox_w or 0) * (a.bbox_h or 0) + (b.bbox_w or 0) * (b.bbox_h or 0) - inter
    return inter / union if union > 0 else 0.0


def _corresponds(a: Finding, b: Finding) -> bool:
    return a.check_type == b.check_type and (
        a.message.strip().lower() == b.message.strip().lower() or _iou(a, b) >= IOU_MATCH
    )


def diff_findings(old: list[Finding], new: list[Finding]):
    """Return (resolved, persisting, new_only) — all AI findings."""
    old_ai = [f for f in old if f.source == "ai"]
    new_ai = [f for f in new if f.source == "ai"]

    matched: set[str] = set()
    resolved: list[Finding] = []
    persisting: list[Finding] = []
    for o in old_ai:
        hit = next((n for n in new_ai if n.id not in matched and _corresponds(o, n)), None)
        if hit is not None:
            persisting.append(hit)
            matched.add(hit.id)
        else:
            resolved.append(o)
    new_only = [n for n in new_ai if n.id not in matched]
    return resolved, persisting, new_only
