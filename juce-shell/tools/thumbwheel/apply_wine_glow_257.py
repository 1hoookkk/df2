"""Wine glow pass over the 257-frame violet-glow strip.

Recipe: WINE_WHEEL_HANDOFF_2026-07-03.md (verbatim, approved by Tyson).
Input : proper_violet_glow_257_298x80.png  (76586x80 RGBA)
Output: proper_wine_broadglow_257_298x80.png (76586x80 RGBA, alpha passthrough)
"""
import numpy as np
from PIL import Image, ImageFilter
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "proper_violet_glow_257_298x80.png")
DST = os.path.join(HERE, "proper_wine_broadglow_257_298x80.png")

FRAME_W, FRAME_H, N = 298, 80, 257
GLOW = np.array([164.0, 38.0, 60.0])
CORE = np.array([214.0, 92.0, 112.0])

src = Image.open(SRC).convert("RGBA")
assert src.size == (FRAME_W * N, FRAME_H), src.size
arr = np.asarray(src).astype(np.float32)

out = np.zeros_like(arr)

def blur(l_arr, radius):
    im = Image.fromarray(np.clip(l_arr, 0, 255).astype(np.uint8), "L")
    return np.asarray(im.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32)

for f in range(N):
    x0 = f * FRAME_W
    fr = arr[:, x0:x0 + FRAME_W, :]
    R, G, B, A = fr[..., 0], fr[..., 1], fr[..., 2], fr[..., 3]

    lamp = np.clip(G - R, 0, None)                      # baked lamp is green-dominant
    baseG = G - lamp
    base = np.stack([R, baseG, np.minimum(B, np.maximum(R, baseG))], axis=-1)

    bloom = blur(lamp, 7.0)
    halo = blur(lamp, 16.0)
    glint = blur(lamp, 1.2)
    e = np.clip(bloom * 2.6 + halo * 1.6 + glint * 0.55, 0, 255) / 255.0
    e3 = e[..., None]

    col = GLOW[None, None, :] * (1 - e3 * 0.5) + CORE[None, None, :] * (e3 * 0.5)
    alpha = (A / 255.0)[..., None]
    rgb = np.clip(base + col * e3 * 1.5 * alpha, 0, 255)

    out[:, x0:x0 + FRAME_W, :3] = rgb
    out[:, x0:x0 + FRAME_W, 3] = A                       # alpha passthrough

Image.fromarray(out.astype(np.uint8), "RGBA").save(DST)
print("wrote", DST, Image.open(DST).size)

# sanity crops
for f in (0, 128, 218):
    crop = Image.open(DST).crop((f * FRAME_W, 0, (f + 1) * FRAME_W, FRAME_H))
    p = os.path.join(HERE, f"wine_sanity_frame_{f}.png")
    crop.save(p)
    print("crop", p)
