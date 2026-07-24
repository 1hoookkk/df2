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

# The bright emission teal sampled from the roller illumination token (#2bd8c3 / #4dfff9).
target = np.array((0x2B, 0xD8, 0xC3), dtype=np.float32)
# Normalize glow brightness so center core hits bright emission peak
value = source[..., :3].max(axis=2, keepdims=True).astype(np.float32)
max_val = np.max(value[glow]) if np.any(glow) else 255.0
norm_val = np.clip(value / max_val * 1.25, 0.0, 1.0)
result[..., :3][glow] = np.rint(target * norm_val[glow]).astype(np.uint8)

pending = assets / "trench_roller_strip.next.png"
Image.fromarray(result, "RGBA").save(pending)
pending.replace(assets / "trench_roller_strip.png")
print(f"retinted {int(glow.sum())} glow pixels to bright emission teal #2bd8c3")
