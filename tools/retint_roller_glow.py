"""Retint only the established roller glow without changing its frames or body."""

from pathlib import Path

import numpy as np
from PIL import Image


assets = Path(__file__).resolve().parents[1] / "plugin" / "assets"
source = np.asarray(
    Image.open(assets / "trench_roller_strip_cyan_backup.png").convert("RGBA"),
    dtype=np.uint8,
)
result = source.copy()
red, green, blue = (source[..., index] for index in range(3))
glow = (
    (source[..., 3] > 200)
    & (green > red * 1.35)
    & (blue > red * 1.35)
    & (green > 50)
)
if not np.any(glow):
    raise RuntimeError("The established cyan glow mask is empty")

# Coral #c96a54, the locked signal colour, applied to the ACCEPTED shipping body.
# A Blender-rebuilt body was tried on 2026-07-25 and rejected in the plugin: it
# came out light and chunky and lost the dark drum the glow needs to sit against.
target = np.array((0xC9, 0x6A, 0x54), dtype=np.float32)
# Normalize glow brightness so center core hits bright emission peak
value = source[..., :3].max(axis=2, keepdims=True).astype(np.float32)
max_val = np.max(value[glow]) if np.any(glow) else 255.0
norm_val = np.clip(value / max_val * 1.25, 0.0, 1.0)
result[..., :3][glow] = np.rint(target * norm_val[glow]).astype(np.uint8)

pending = assets / "trench_roller_strip.next.png"
Image.fromarray(result, "RGBA").save(pending)
pending.replace(assets / "trench_roller_strip.png")
print(f"retinted {int(glow.sum())} glow pixels to coral #c96a54")
