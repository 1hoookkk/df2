"""Package the pitch-wheel render into the runtime strip.

Frames: dev/tmp/thumbwheel_blender/spin_pitchwheel (128 x 596x160, transparent).
Per frame: resize to 298x80, dissolve the last ~8% of each end into the well
floor colour (sampled from the panel art), capsule alpha (corner radius 34% of
band height) for the disc read. Lamp/trail/scatter are BAKED in the render
(embedded light under the channel fins, X3 measured envelope) — no post glow.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

FRAMES = Path(r"C:\Users\hooki\df2\dev\tmp\thumbwheel_blender\spin_pitchwheel")
PANEL = Path(r"C:\Users\hooki\df2\juce-shell\assets\ui\df2_panel_shadow.png")
OUT = Path(r"C:\Users\hooki\df2\dev\tmp\thumbwheel_blender\thumbwheel_pitchwheel_128_298x80.png")

FW, FH = 298, 80
pa = np.asarray(Image.open(PANEL).convert("RGBA"))
floor = pa[735:745, 128:140, :3].reshape(-1, 3).mean(axis=0)

files = sorted(FRAMES.glob("f*.png"))
assert len(files) == 128, len(files)

xs = np.arange(FW) / (FW - 1) * 2 - 1
fade = np.clip((1.0 - np.abs(xs)) / 0.06, 0, 1)   # edges out a touch: shorter dissolve
fade = fade * fade * (3 - 2 * fade)

strip = Image.new("RGBA", (FW * len(files), FH), (0, 0, 0, 0))
mask_cache = None
for i, p in enumerate(files):
    fr = np.asarray(Image.open(p).convert("RGBA").resize((FW, FH), Image.LANCZOS)).astype(np.float64)
    rgb, al = fr[:, :, :3], fr[:, :, 3]
    rgb = floor[None, None, :] * (1 - fade[None, :, None]) + rgb * fade[None, :, None]
    if mask_cache is None:
        rows = np.nonzero(al.max(axis=1) > 8)[0]
        y0, y1 = int(rows.min()), int(rows.max()) + 1
        rad = max(6, int(0.20 * 98 * (298.0 / 422.0)))   # corners match the well clip
        m = Image.new("L", (FW * 4, FH * 4), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, y0 * 4, FW * 4 - 1, y1 * 4 - 1], radius=rad * 4, fill=255)
        mask_cache = np.asarray(m.resize((FW, FH), Image.LANCZOS)).astype(np.float64) / 255.0
    al2 = al * mask_cache
    out = np.dstack([np.clip(rgb, 0, 255), al2[:, :, None]]).astype(np.uint8)
    strip.paste(Image.fromarray(out, "RGBA"), (i * FW, 0))

strip.save(OUT)
print("wrote", OUT, strip.size)
