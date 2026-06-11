#!/usr/bin/env python3
"""Simulate the runtime two-layer composite: ultraviolet back-light behind the
static mask, at several value positions. Lets us judge the look before a C++
rebuild. This mirrors the math in TrenchThumbwheel.h drawBackLight()."""
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
mask = Image.open(HERE / "_preview" / "native_strip_129_96x14.png").convert("RGBA")
FW, FH = 96, 14
frame = mask.crop((0, 0, FW, FH))  # all frames identical

# ultraviolet tokens
CORE = (229, 220, 255)   # 0xffe5dcff lavender-white hot core
DIM = (159, 143, 200)    # 0xff9f8fc8 deeper violet

PANEL = (26, 25, 30, 255)   # dark faceplate behind the recess (cast-shadow zone)
SCALE = 8


def lerp(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def back_light(norm):
    """Return an RGB light field (FW x FH) of the violet source behind the mask.
    Tight leading edge, short trailing tail, vertically centred on clearance."""
    img = Image.new("RGB", (FW, FH), PANEL[:3])
    if norm <= 0.0 or norm >= 1.0:
        return img  # frames 0 and 128 unlit
    px = img.load()
    lx = norm * (FW - 1)
    lead = 3.0     # px ahead of value (almost nothing)
    tail = 14.0    # px behind value (short tail)
    cy = 6.2       # clearance band centre row
    for y in range(FH):
        vy = max(0.0, 1.0 - abs(y - cy) / 3.8)  # soft vertical band over clearance
        if vy <= 0:
            continue
        for x in range(FW):
            dx = x - lx
            if dx >= 0:
                hx = max(0.0, 1.0 - dx / lead)
            else:
                hx = max(0.0, 1.0 - (-dx) / tail)
            inten = (hx ** 1.25) * vy
            if inten <= 0.01:
                continue
            col = lerp(DIM, CORE, min(1.0, inten * 1.6))
            base = px[x, y]
            k = min(1.0, inten * 1.7)
            px[x, y] = tuple(int(base[i] * (1 - k) + col[i] * k) for i in range(3))
    return img


def composite(norm):
    light = back_light(norm).convert("RGBA")
    out = Image.new("RGBA", (FW, FH), PANEL)
    out.alpha_composite(light)
    out.alpha_composite(frame)  # semi-transparent mask over the light
    return out


norms = [0.0, 0.12, 0.5, 0.78, 0.97, 1.0]
gap = 3
cols = len(norms)
sheet = Image.new("RGBA", (cols * FW * SCALE + (cols - 1) * gap, FH * SCALE), (60, 60, 64, 255))
for i, n in enumerate(norms):
    cell = composite(n).resize((FW * SCALE, FH * SCALE), Image.Resampling.NEAREST)
    sheet.alpha_composite(cell, (i * (FW * SCALE + gap), 0))
sheet.save(HERE / "_preview" / "composite_row.png")
print("wrote _preview/composite_row.png   norms:", norms)

# also a single bare mask, big
frame.resize((FW * SCALE, FH * SCALE), Image.Resampling.NEAREST).save(HERE / "_preview" / "mask_big.png")
print("wrote _preview/mask_big.png")
