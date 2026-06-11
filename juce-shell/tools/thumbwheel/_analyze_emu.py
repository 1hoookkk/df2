#!/usr/bin/env python3
"""Measure the real E-mu X3 thumbwheel strip (clean-room: measure, do not ship pixels).

Outputs to _emu_analysis/:
  - bigframe_XXX.png   : 8x nearest upscale of representative frames (for visual read)
  - contact_all.png    : every frame, 2x upscale, stacked grid
  - row/col luma + glow report printed to stdout
"""
from pathlib import Path
from PIL import Image

SRC = Path(r"C:\Users\hooki\do-it\BITMAP4332_1.bmp")
OUT = Path(__file__).parent / "_emu_analysis"
OUT.mkdir(exist_ok=True)

FRAME_W = 85
FRAME_H = 11
FRAMES = 129

img = Image.open(SRC).convert("RGB")
W, H = img.size
print(f"source: {SRC.name}  {W}x{H}  (expect {FRAME_W*FRAMES}x{FRAME_H} = {FRAME_W*FRAMES}x{FRAME_H})")
print(f"derived frame width = {W/FRAMES:.4f}  (int {W//FRAMES})")
px = img.load()


def frame_rect(i):
    x0 = round(i * W / FRAMES)
    return (x0, 0, x0 + FRAME_W, FRAME_H)


# --- big upscales of representative frames ---
reps = [0, 1, 16, 32, 64, 96, 112, 127, 128]
SCALE = 10
for i in reps:
    x0, y0, x1, y1 = frame_rect(i)
    f = img.crop((x0, 0, x0 + FRAME_W, FRAME_H))
    f.resize((FRAME_W * SCALE, FRAME_H * SCALE), Image.Resampling.NEAREST).save(OUT / f"bigframe_{i:03d}.png")
print(f"wrote {len(reps)} big frames: {reps}")

# --- contact sheet: all frames, 2x, stacked in a grid ---
CS = 3
cols = 8
gap = 2
import math
rows = math.ceil(FRAMES / cols)
cw, ch = FRAME_W * CS, FRAME_H * CS
sheet = Image.new("RGB", (cols * cw + (cols - 1) * gap, rows * ch + (rows - 1) * gap), (40, 40, 40))
for i in range(FRAMES):
    x0, _, _, _ = frame_rect(i)
    f = img.crop((x0, 0, x0 + FRAME_W, FRAME_H)).resize((cw, ch), Image.Resampling.NEAREST)
    sheet.paste(f, ((i % cols) * (cw + gap), (i // cols) * (ch + gap)))
sheet.save(OUT / "contact_all.png")
print("wrote contact_all.png")


# --- per-row luma profile, averaged over a mid frame (64) and an unlit frame (0) ---
def luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def is_cyan(r, g, b):
    return g > r + 14 and b > r + 14 and (g > 45 or b > 45)


def row_profile(frame_idx):
    x0, _, _, _ = frame_rect(frame_idx)
    prof = []
    for y in range(FRAME_H):
        vals = [luma(*px[x0 + x, y]) for x in range(FRAME_W)]
        prof.append(sum(vals) / len(vals))
    return prof


print("\n-- per-row mean luma (frame 0 = should be unlit, 64 = mid) --")
p0 = row_profile(0)
p64 = row_profile(64)
print(" y  | frame0 | frame64")
for y in range(FRAME_H):
    print(f" {y:2d} | {p0[y]:6.1f} | {p64[y]:6.1f}")

# --- glow: where are cyan pixels per frame, and what's their x-centroid? ---
print("\n-- glow (cyan) per frame: count, x-centroid(0..1), rows-hit --")
for i in [0, 1, 8, 16, 32, 48, 64, 80, 96, 112, 120, 127, 128]:
    x0, _, _, _ = frame_rect(i)
    cnt = 0
    sx = 0.0
    rows_hit = set()
    maxc = (0, 0, 0)
    for y in range(FRAME_H):
        for x in range(FRAME_W):
            r, g, b = px[x0 + x, y]
            if is_cyan(r, g, b):
                cnt += 1
                sx += x
                rows_hit.add(y)
                if luma(*maxc) < luma(r, g, b):
                    maxc = (r, g, b)
    cx = (sx / cnt / FRAME_W) if cnt else -1
    print(f" frame {i:3d}: cyan={cnt:4d}  x-centroid={cx:5.2f}  rows={sorted(rows_hit)}  brightest={maxc}")

# --- sample the brightest material (ABS) and darkest (clearance/slot) colors ---
print("\n-- material color sampling (frame 0, non-cyan) --")
x0, _, _, _ = frame_rect(0)
brightest = (0, 0, 0)
darkest = (255, 255, 255)
for y in range(FRAME_H):
    for x in range(FRAME_W):
        r, g, b = px[x0 + x, y]
        if is_cyan(r, g, b):
            continue
        if luma(r, g, b) > luma(*brightest):
            brightest = (r, g, b)
        if luma(r, g, b) < luma(*darkest):
            darkest = (r, g, b)
print(f" brightest ABS pixel: {brightest}  luma={luma(*brightest):.0f}")
print(f" darkest pixel:       {darkest}  luma={luma(*darkest):.0f}")
print("\nDone.")
