"""Extract the real sponsor logos from the Predator League source graphics.

Run:  python assets/extract_sponsor_logos.py

Crops the four sponsor marks out of assets/typo-check/bracket_1.png and writes
them to assets/sponsors/ as the reference templates SponsorAuditCheck matches
against. bracket_1 is the source because its logos sit on a plain dark field —
match_announcement_2 shows the same marks at the SAME pixel size (verified:
every logo matches it at scale 1.00, score 0.97-0.99), so one crop serves both.

Why crops are saved at NATIVE size
----------------------------------
These logos appear in the graphics at exactly the size cropped here, i.e. a
template-to-graphic ratio of 1.0. SponsorAuditCheck.SCALES therefore has to
include 1.0 — the original pyramid stopped at 0.84 and could never have found
them. Upscaling the crops to dodge that gap would only add resampling blur, so
the pyramid was extended instead.

Templates are written as opaque RGB: the check loads them with cv2.IMREAD_COLOR,
which discards alpha, so a transparent PNG would compare as black-backed art.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "typo-check" / "bracket_1.png"
OUT_DIR = ROOT / "sponsors"

# Generous regions around each mark; the exact box is then tightened to the
# bright ink inside, so small hand-measuring errors don't matter.
REGIONS = {
    "predator.png": (25, 40, 370, 130),
    "intel.png": (845, 40, 1085, 140),
    "intel_core.png": (735, 1145, 1070, 1285),
    "valorant.png": (30, 1290, 360, 1370),
}
INK_THRESHOLD = 70  # grayscale value above which a pixel counts as logo ink
PAD = 4


def tighten(crop: Image.Image) -> Image.Image:
    """Shrink a generous crop to the bounding box of its bright pixels."""
    gray = np.asarray(crop.convert("L"))
    ys, xs = np.where(gray > INK_THRESHOLD)
    if len(xs) == 0:
        return crop
    x0, x1 = max(0, xs.min() - PAD), min(crop.width, xs.max() + 1 + PAD)
    y0, y1 = max(0, ys.min() - PAD), min(crop.height, ys.max() + 1 + PAD)
    return crop.crop((x0, y0, x1, y1))


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Source graphic not found: {SOURCE}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    src = Image.open(SOURCE).convert("RGB")
    canvas_area = src.width * src.height
    print(f"source {SOURCE.name} {src.width}x{src.height}\n")

    for name, box in REGIONS.items():
        logo = tighten(src.crop(box))
        logo.save(OUT_DIR / name)  # RGB -> opaque by construction
        area_pct = logo.width * logo.height / canvas_area * 100
        flag = "" if area_pct >= 1.0 else "   <- under the 1% visibility floor"
        print(f"{name:<17} {logo.width:>4}x{logo.height:<4} "
              f"{area_pct:>5.2f}% of source canvas{flag}")


if __name__ == "__main__":
    main()
