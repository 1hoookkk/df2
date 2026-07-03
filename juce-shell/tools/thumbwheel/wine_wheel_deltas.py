"""Shipped wheel as base + Tyson's material deltas (2026-07-03), in post.

Base = proper_violet_glow_257_298x80.png (the approved wheel), de-lamped by the
approved G-R law. Deltas ONLY:
  - soften black gaps to dark graphite grey (shadow-floor lift => ribs read
    20-30% shallower at plugin scale)
  - subtle satin grey highlights on the top/bottom curve (light-on-object,
    from the wheel's own alpha geometry)
  - faint ruby emission INSIDE the trench only: gated by the gap mask x trench
    band — physically impossible for it to read as a flat band across the front
  - body stays dark smoked graphite; no ice/glass, no silver, no transparency
Then the approved travelling wine lamp (apply_wine_glow_257 recipe) on top.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

SRC = Path(r"C:\Users\hooki\df2\dev\tmp\thumbwheel_blender\proper_violet_glow_257_298x80.png")
OUT = Path(r"C:\Users\hooki\df2\dev\tmp\thumbwheel_blender\proper_wine_deltas_257_298x80.png")

FW, FH = 298, 80
GLOW = np.array([164.0, 38.0, 60.0])
CORE = np.array([214.0, 92.0, 112.0])

a = np.asarray(Image.open(SRC).convert("RGBA")).astype(np.float64)
n = a.shape[1] // FW

# wheel band + trench channel from frame geometry
al0 = a[:, :FW, 3]
rows = np.nonzero(al0.max(axis=1) > 8)[0]
Y0, Y1 = int(rows.min()), int(rows.max()) + 1
CH_Y = (Y0 + Y1) / 2.0
WH = Y1 - Y0
yv = np.arange(FH, dtype=np.float64)
trench_band = np.exp(-0.5 * ((yv - CH_Y) / (WH * 0.10)) ** 2)          # narrow
crown_top = np.exp(-0.5 * ((yv - (Y0 + WH * 0.10)) / (WH * 0.07)) ** 2)
crown_bot = np.exp(-0.5 * ((yv - (Y1 - WH * 0.12)) / (WH * 0.08)) ** 2)
xs = np.arange(FW, dtype=np.float64)
limb = np.clip(1.0 - ((xs - FW / 2) / (FW * 0.55)) ** 2, 0.0, 1.0)      # fade at ends

strip = Image.new("RGBA", (FW * n, FH), (0, 0, 0, 0))
for i in range(n):
    fr = a[:, i * FW:(i + 1) * FW]
    r, g, b, al = fr[:, :, 0], fr[:, :, 1], fr[:, :, 2], fr[:, :, 3]
    alpha = al / 255.0
    base = np.dstack([r, np.minimum(g, r), np.minimum(b, r)])           # de-lamp (approved)

    # 1) soften black gaps -> dark graphite grey (lifts only the deep shadows)
    L = base.mean(axis=2)
    lift = np.clip(26.0 - L, 0.0, None) * 0.55 * alpha
    base = np.clip(base + lift[:, :, None] * np.array([0.95, 1.0, 1.15])[None, None, :], 0, 255)

    # 2) subtle satin grey highlights on the top/bottom curve
    satin = (crown_top * 10.0 + crown_bot * 6.5)[:, None] * limb[None, :] * alpha
    base = np.clip(base + satin[:, :, None] * np.array([0.9, 0.95, 1.0])[None, None, :], 0, 255)

    # 3) faint ruby inside the trench ONLY: through the dark gaps, never a band
    L2 = base.mean(axis=2) / 255.0
    ref = max(np.percentile(L2[alpha > 0.5], 85), 1e-3)
    gap = np.clip(1.0 - L2 / ref, 0.0, 1.0) ** 1.6
    ember = trench_band[:, None] * gap * alpha * 0.16
    base = np.clip(base + GLOW[None, None, :] * ember[:, :, None], 0, 255)

    # 4) the approved travelling wine lamp (apply_wine_glow_257 recipe)
    lamp = np.clip(g - r, 0.0, None)
    Li = Image.fromarray(np.clip(lamp, 0, 255).astype(np.uint8), "L")
    bloom = np.asarray(Li.filter(ImageFilter.GaussianBlur(7.0))).astype(np.float64)
    halo = np.asarray(Li.filter(ImageFilter.GaussianBlur(16.0))).astype(np.float64)
    glint = np.asarray(Li.filter(ImageFilter.GaussianBlur(1.2))).astype(np.float64)
    e = np.clip(bloom * 2.6 + halo * 1.6 + glint * 0.55, 0, 255) / 255.0
    col = GLOW[None, None, :] * (1 - e[:, :, None] * 0.5) + CORE[None, None, :] * (e[:, :, None] * 0.5)
    rgb = np.clip(base + col * e[:, :, None] * 1.5 * alpha[:, :, None], 0, 255)

    out = np.dstack([rgb, fr[:, :, 3:4]]).astype(np.uint8)
    strip.paste(Image.fromarray(out, "RGBA"), (i * FW, 0))

strip.save(OUT)
print("wrote", OUT, strip.size)
