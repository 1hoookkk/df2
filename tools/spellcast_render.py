#!/usr/bin/env python3
"""spellcast_render.py — render the spellcast_fx animation to a real video file.

The terminal version only animates on a live screen (a TTY); piping/capturing it
just dumps escape codes. This draws the SAME frames (truecolor braille silhouette,
glitch title, flow-field crystallize, morph-sweep, strike) straight to image
frames and encodes an MP4 you can open and drop into a reel.

  python tools/spellcast_render.py cavern
  python tools/spellcast_render.py morph_worlds --green --out reel.mp4
"""
from __future__ import annotations
import argparse, math, os, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio.v2 as imageio
import matplotlib

import importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "physical_corners", ROOT / ".claude" / "skills" / "physical-corners" / "physical_corners.py")
pc = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(pc)   # type: ignore
SR = pc.SR

W, H = 56, 16
PX, PY = W * 2, H * 4
DOTS = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]
THEMES = {
    "amber": ((120, 38, 4), (255, 244, 198)),
    "green": ((10, 90, 28), (190, 255, 205)),
    "mono":  ((70, 70, 78), (250, 250, 255)),
}
FS = 24
FONT = ImageFont.truetype(
    os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf", "DejaVuSansMono.ttf"), FS)

def lerp(a, b, t): return a + (b - a) * t

# ── real physics: magnitude curve of a corner ────────────────────────────────────
def corner_curve(corner, nbins=PX):
    mags = []
    for i in range(nbins):
        f = 40.0 * (16000.0 / 40.0) ** (i / (nbins - 1))
        w = 2 * math.pi * f / SR
        m = 1.0
        for s in corner:
            m *= pc._section_mag(s, w)
        mags.append(m)
    mx = max(mags) or 1.0
    return [(v / mx) ** 0.6 for v in mags]

def heights_from(curve, scale=1.0):
    return [max(0, min(PY, int(v * PY * scale))) for v in curve]

def braille_rows(heights):
    """-> list of H strings (the silhouette as braille sub-pixels)."""
    rows = []
    for cy in range(H):
        line = []
        for cx in range(W):
            mask = 0
            for r in range(4):
                py = 4 * cy + r
                for c in range(2):
                    x = 2 * cx + c
                    if py >= PY - heights[x]:
                        mask |= DOTS[r][c]
            line.append(chr(0x2800 + mask) if mask else " ")
        rows.append("".join(line))
    return rows

# ── frame -> PIL image ────────────────────────────────────────────────────────────
CW = int(round(FONT.getlength("⣿")))           # cell width
LH = int(FS * 1.18)                              # line height
MX, MY = CW * 3, LH                              # margins
IMG_W = (MX * 2 + CW * W + 1) // 2 * 2            # even dims for h264
IMG_H = (MY * 2 + LH * (H + 4) + 1) // 2 * 2

def new_frame():
    return Image.new("RGB", (IMG_W, IMG_H), (6, 5, 8))

def draw_title(img, text, split=0, jitter=0):
    d = ImageDraw.Draw(img)
    y = MY
    x = MX + jitter
    if split:
        d.text((x - split, y), text, font=FONT, fill=(0, 120, 255))
        d.text((x + split, y), text, font=FONT, fill=(255, 40, 60))
    d.text((x, y), text, font=FONT, fill=(245, 245, 255))

def draw_canvas(img, heights, pal, glow=1.0):
    d = ImageDraw.Draw(img)
    lo, hi = pal
    rows = braille_rows(heights)
    y0 = MY + LH * 2
    for cy, row in enumerate(rows):
        t = 1.0 - cy / (H - 1)
        dim = 1.0 if cy % 2 == 0 else 0.62           # CRT scanline
        col = tuple(min(255, max(0, int(lerp(lo[k], hi[k], t) * dim * glow))) for k in range(3))
        d.text((MX, y0 + cy * LH), row, font=FONT, fill=col)

def draw_puck(img, u, pal):
    d = ImageDraw.Draw(img)
    lo, hi = pal
    y = MY + LH * (H + 2)
    p = int(u * (W - 1))
    d.text((MX, y), "─" * W, font=FONT, fill=lo)
    d.text((MX + p * CW, y), "◆", font=FONT, fill=hi)

def draw_lock(img, word, pal):
    d = ImageDraw.Draw(img)
    _, hi = pal
    d.text((MX, MY + LH * (H + 2)), f"● {word.upper()}", font=FONT, fill=hi)

# ── build the frame sequence (mirrors spellcast_fx) ──────────────────────────────
def frames(word, pal):
    specs   = pc.PRESETS[word]
    corners = [pc.corner_from_spec(s) for s in specs]
    curves  = [corner_curve(c) for c in corners]
    seq = []

    title = f"▓▒░  S U M M O N   {word.upper()}  ░▒▓"
    # glitch title in
    for f in range(12):
        s = f / 11
        im = new_frame()
        draw_title(im, title, split=max(0, int((1 - s) * 4)),
                   jitter=0 if random.random() < s else random.randint(-2, 2))
        seq.append(im)

    # flow-field noise crystallizing into corner 0
    tgt = heights_from(curves[0])
    for f in range(30):
        p = (f / 29) ** 1.6
        t = f * 0.22
        hs = []
        for x in range(PX):
            if random.random() < p:
                hs.append(tgt[x])
            else:
                v = math.sin(x * 0.18 + t) + math.sin(x * 0.07 - t * 1.7) + random.random() * 1.2
                hs.append(int((v + 2.4) / 4.8 * PY * 0.55))
        im = new_frame(); draw_title(im, title); draw_canvas(im, hs, pal, glow=0.8 + 0.2 * p)
        seq.append(im)

    # morph sweep through all four corners
    NF = 90
    for f in range(NF):
        u = f / (NF - 1)
        pos = u * 3.0
        i = min(2, int(pos)); frac = pos - i
        cur = [lerp(curves[i][x], curves[i + 1][x], frac) for x in range(PX)]
        strike = 1.0 + 0.16 * math.exp(-((u * 6) % 1.0) * 5)
        im = new_frame(); draw_title(im, title)
        draw_canvas(im, heights_from(cur, strike), pal); draw_puck(im, u, pal)
        seq.append(im)

    # strike flash + hold
    for g in (1.8, 1.4, 1.1, 1.0):
        im = new_frame(); draw_title(im, title)
        draw_canvas(im, heights_from(curves[-1]), pal, glow=g); draw_lock(im, word, pal)
        seq.append(im)
    last = seq[-1]
    seq += [last] * 24                                # ~0.8s hold

    pc.write_cartridge(corners, f"phys_{word}")        # still author the body
    return seq

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("body", nargs="?", default="cavern")
    ap.add_argument("--green", action="store_true")
    ap.add_argument("--mono", action="store_true")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    word = a.body.lower().strip()
    if word not in pc.PRESETS:
        print("bodies:", "  ".join(sorted(pc.PRESETS))); return
    pal = THEMES["green"] if a.green else THEMES["mono"] if a.mono else THEMES["amber"]
    out = a.out or str(ROOT / f"spellcast_{word}.mp4")
    print(f"rendering {word} ({IMG_W}x{IMG_H}) …")
    seq = frames(word, pal)
    with imageio.get_writer(out, fps=a.fps, codec="libx264", quality=8,
                            macro_block_size=None) as w:
        for im in seq:
            w.append_data(np.asarray(im))
    print(f"wrote {out}  ({len(seq)} frames, {len(seq)/a.fps:.1f}s)")

if __name__ == "__main__":
    main()
