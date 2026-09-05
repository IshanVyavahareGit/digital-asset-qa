Fair — I threw four bare numbers at you. Let me label them properly and show the whole calculation in pixels you can picture.

## The four numbers are always `(x, y, w, h)`

```
bbox = (0.35, 0.80, 0.30, 0.04)
         │      │      │     │
         │      │      │     └─ h = HEIGHT   how tall it is
         │      │      └─────── w = WIDTH    how wide it is
         │      └────────────── y = TOP      how far DOWN it starts
         └───────────────────── x = LEFT     how far ACROSS it starts
```

They are **fractions of the canvas**, never pixels. `0.35` means "35% of the way across". `0.04` means "4% of the height tall".

The rule for converting: **`x` and `w` multiply by the WIDTH; `y` and `h` multiply by the HEIGHT.**

## What that button actually is, in pixels

On an Instagram Story canvas of **1080 × 1920**:

| | fraction | × canvas | pixels |
|---|---|---|---|
| `x` = left edge | 0.35 | × 1080 (width) | **378 px** from the left |
| `y` = top edge | 0.80 | × 1920 (height) | **1536 px** from the top |
| `w` = width | 0.30 | × 1080 (width) | **324 px** wide |
| `h` = height | 0.04 | × 1920 (height) | **77 px** tall |

So the WATCH LIVE button is a box that spans **378 → 702 px** horizontally and **1536 → 1612.8 px** vertically. Roughly a third of the way across, near the bottom, about the size of a chunky button.

Note `w` and `h` are *sizes*, not positions. To get the right and bottom edges you add:

```
right edge  = x + w = 0.35 + 0.30 = 0.65   (702 px)
bottom edge = y + h = 0.80 + 0.04 = 0.84   (1612.8 px)
```

That `bottom edge = y + h` is the number the overlap test hinges on.

## Where it collides

```
          0                                             1080
          │                                                │
          │            378                702              │
  1536 ───┼─────────────┌──────────────────┐───────────────┤ ← button TOP     (y = 0.80)
          │             │                  │               │
          │             │   WATCH LIVE     │   77 px tall  │
          │             │                  │               │
  1600 ═══╪═════════════╪══════════════════╪═══════════════╡ ← ZONE TOP       (0.8333)
          │▓▓▓▓▓▓▓▓▓▓▓▓▓└──────────────────┘▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ← button BOTTOM  (1612.8)
          │▓▓▓▓▓▓▓▓▓▓▓  BOTTOM UI  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
          │▓▓▓▓▓▓  caption / reply bar  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│
  1920 ───┴────────────────────────────────────────────────┘
```

The button's bottom edge lands at **1612.8 px**. The danger zone starts at **1600 px**. So the bottom **12.8 px** of the button pokes into the caption bar.

## The calculation, step by step

**Step 1 — how much do they overlap vertically?**

```
button bottom edge  =  y + h  =  0.80 + 0.04  =  0.8400      (1612.8 px)
zone top edge       =                            0.8333      (1600 px)

vertical overlap    =  0.8400 - 0.8333  =  0.00667           (12.8 px)
```

**Step 2 — how much do they overlap horizontally?**

The bottom UI zone spans the *entire* width of the canvas, so the button overlaps it across its full width:

```
horizontal overlap  =  0.30                                   (324 px)
```

**Step 3 — the overlapping area**

```
overlapping area  =  0.30  ×  0.00667  =  0.00200
```

**Step 4 — compare it to the button's own area**

```
button's own area =  w × h  =  0.30 × 0.04  =  0.01200

fraction covered  =  0.00200 / 0.01200  =  0.1667  =  16.7%
```

Sanity check in plain pixels: **12.8 px** of a **76.8 px** tall button is 12.8 ÷ 76.8 = **16.7%**. Same answer. The fractions are just a units-free way of doing the same sum.

**Step 5 — which band is that?**

```
below 0.12          ignore
0.12 → 0.45         WARNING      ←  0.1667 lands here
0.45 and above      CRITICAL
```

Result: **warning** — *"Cta 'WATCH LIVE' sits inside the 'bottom UI' danger zone (17% overlap)."*

## Why fractions instead of just storing pixels

Because the same graphic gets viewed at different sizes. Store `1536 px` and you have to also remember *"…out of 1920"*, and every consumer has to know that. Store `0.80` and it means "80% down" on a 1920 px export, a 3840 px export, or a 400 px thumbnail in the review panel.

It's the difference between saying *"the button is 1536 px down"* and *"the button is four-fifths of the way down"*. The second one survives being resized; the first doesn't.