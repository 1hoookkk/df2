#!/usr/bin/env python3
"""Render the canonical 129-frame TRENCH thumbwheel runtime strip.

PHOTO-DERIVED method: the wheel material comes from the bone-white reference
render (`reference_bone_wheel.png`, Tyson's own generated art — clean to ship).
Texture/lighting separation:
- detail  = reference / horizontal-lowpass(reference)  -> scrolls with value
- lighting = the reference's own vertical 3D profile + our fixed horizontal
  envelope and end rolloff                              -> never moves
- glow     = painted behind the aperture rows: hot core, halo, short trail,
  bulging bleed around the bead; fades as it travels

Asset contract (the only strip the plugin loads):
- runtime frame: 149x40 (the measured true well opening), strip: 19221x40
  (129 frames, crop x = frame * 149)
- frame 0 == frame 128, byte-identical, no cyan
- drawn 1:1 filling the whole well opening of df2_panel_shadow.png
- the fin surface scrolls exactly one full period over the 128 steps
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

HERE = Path(__file__).parent
REFERENCE = HERE / "reference_bone_wheel.png"

FRAMES = 129
W = 149
H = 40                 # measured true well opening: ~149 x 40 editor px
CORE_H = 31            # wheel occupies frame rows 5..36 — seated in the
CORE_Y = 5             # well, the lip overhanging the top
PERIOD = float(W)
N_FINS = 15


def clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def smoothstep(e0: float, e1: float, x: float) -> float:
    if e0 == e1:
        return 1.0 if x >= e1 else 0.0
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def hash01(a: int, b: int = 0, seed: int = 4331) -> float:
    n = (a * 73856093) ^ (b * 19349663) ^ (seed * 83492791)
    n = (n ^ (n >> 13)) * 1274126177
    return ((n ^ (n >> 16)) & 65535) / 65535.0


# ------------------------------------------------- derive material from photo

def derive_material() -> tuple[Image.Image, list[float], int, int]:
    """Build the 149px seamless detail loop + vertical lighting profile."""
    im = Image.open(REFERENCE).convert("RGB")
    px = im.load()

    rowmean = []
    for y in range(im.height):
        s, n = 0.0, 0
        for x in range(150, 950, 4):
            r, g, b = px[x, y]
            s += (r + g + b) / 3.0
            n += 1
        rowmean.append(s / n)
    ys = [y for y in range(200, 620) if rowmean[y] > 60]
    y0, y1 = min(ys), max(ys)

    crop = im.crop((150, y0, 950, y1 + 1))
    tile_w = int(crop.width * CORE_H / crop.height)
    # two-step downscale with a smoothing pass: the brutal vertical squash
    # otherwise aliases every photo feature into every row and the bands
    # clump into one dense texture mass
    mid = crop.resize((tile_w * 3, CORE_H * 3), Image.LANCZOS)
    mid = mid.filter(ImageFilter.GaussianBlur(radius=1.3))
    tile = mid.resize((tile_w, CORE_H), Image.LANCZOS)

    # horizontal-only lowpass keeps the vertical 3D profile intact
    blur = tile.resize((max(2, tile_w // 14), CORE_H), Image.BILINEAR) \
               .resize((tile_w, CORE_H), Image.BILINEAR)
    bp = blur.load()

    rowlight = []
    for y in range(CORE_H):
        s = sum(sum(bp[x, y]) / 3.0 for x in range(8, tile_w - 8))
        rowlight.append(s / (tile_w - 16))

    tp = tile.load()
    detail = Image.new("RGB", (tile_w, CORE_H))
    dp = detail.load()
    for y in range(CORE_H):
        for x in range(tile_w):
            r, g, b = tp[x, y]
            br, bg, bb = bp[x, y]
            dp[x, y] = (
                min(255, int(r / max(8, br) * 170)),
                min(255, int(g / max(8, bg) * 170)),
                min(255, int(b / max(8, bb) * 170)),
            )

    # fin pitch from autocorrelation over the crest rows
    colmean = []
    for x in range(tile_w):
        s = sum(sum(dp[x, y]) / 3.0 for y in range(2, 9))
        colmean.append(s / 7.0)
    mean_all = sum(colmean) / len(colmean)
    cm = [v - mean_all for v in colmean]
    best_p, best_v = 4, -1e18
    for p in range(4, 16):
        v = sum(cm[x] * cm[x + p] for x in range(tile_w - p))
        if v > best_v:
            best_v, best_p = v, p

    # exact-period 149px loop assembled fin-by-fin: slice the source at the
    # REAL groove positions (local minima of the column profile, not an
    # integer-pitch lattice — that drifted and cut through fins). Every
    # joint, including the scroll wrap at x=0, lands inside a groove.
    sm = [
        (colmean[max(0, x - 1)] + colmean[x] + colmean[min(tile_w - 1, x + 1)]) / 3.0
        for x in range(tile_w)
    ]
    minima = []
    for x in range(2, tile_w - 2):
        if sm[x] <= sm[x - 1] and sm[x] <= sm[x + 1] and sm[x] < mean_all:
            if not minima or x - minima[-1] >= best_p * 0.6:
                minima.append(x)
    slices = [(minima[i], minima[i + 1]) for i in range(len(minima) - 1)
              if (minima[i + 1] - minima[i]) >= best_p * 0.6]
    if len(slices) < 2:
        slices = [(0, tile_w)]
    s4 = 4
    band4 = detail.resize((tile_w * s4, CORE_H * s4), Image.LANCZOS)
    loop4 = Image.new("RGB", (W * s4, CORE_H * s4))
    for k in range(N_FINS):
        a, b = slices[k % len(slices)]
        dx0 = int(round(k * W * s4 / N_FINS))
        dx1 = int(round((k + 1) * W * s4 / N_FINS))
        fin = band4.crop((a * s4, 0, b * s4, CORE_H * s4))
        loop4.paste(fin.resize((dx1 - dx0, CORE_H * s4), Image.LANCZOS), (dx0, 0))
    loop = loop4.resize((W, CORE_H), Image.LANCZOS)
    loop = ImageEnhance.Contrast(loop).enhance(1.08)
    loop = loop.filter(ImageFilter.UnsharpMask(radius=2, percent=38, threshold=2))

    # deepen the lighting contrast so the aperture valley clearly separates
    # the two bands instead of mushing into them
    mean_l = sum(rowlight) / len(rowlight)
    rowlight = [mean_l + (v - mean_l) * 1.30 for v in rowlight]

    ap_rows = sorted(range(10, 23), key=lambda y: rowlight[y])[:6]
    return loop, rowlight, min(ap_rows), max(ap_rows)


_MATERIAL: tuple[Image.Image, list[float], int, int] | None = None


def material() -> tuple[Image.Image, list[float], int, int]:
    global _MATERIAL
    if _MATERIAL is None:
        _MATERIAL = derive_material()
    return _MATERIAL


# ------------------------------------------------------------------ lighting

def xenv(fx: float) -> float:
    # the wheel continues past the slot: fins stay crisp to the edge and the
    # next tile is implied beyond it — only a short dip where the well wall
    # cuts the light, never a smoky vignette
    edge = min(fx, PERIOD - fx)
    end = 0.34 + 0.66 * smoothstep(0.0, 4.0, edge)
    sheen = 0.82 + 0.18 * math.exp(-(((fx - 62.0) / 52.0) ** 2))
    return end * sheen


# ------------------------------------------------------------------ the frame

def render_frame(frame: int) -> Image.Image:
    loop, rowlight, ap_top, ap_bot = material()

    phase = (frame % (FRAMES - 1)) * PERIOD / float(FRAMES - 1)
    has_cyan = frame not in (0, FRAMES - 1)
    bead_x = -16.0 + (frame / float(FRAMES - 1)) * (PERIOD + 32.0)
    travel = (smoothstep(0.5, 4.0, float(frame))
              * (max(0.0, 1.0 - (frame - 1) / 127.0) ** 0.8)) if has_cyan else 0.0

    doubled = Image.new("RGB", (W * 2, CORE_H))
    doubled.paste(loop, (0, 0))
    doubled.paste(loop, (W, 0))
    shifted = doubled.transform((W, CORE_H), Image.AFFINE,
                                (1, 0, phase % PERIOD, 0, 1, 0), Image.BILINEAR)
    sp = shifted.load()

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fp = img.load()
    ap_mid = (ap_top + ap_bot) / 2.0

    for y in range(CORE_H):
        fy = y + CORE_Y
        rl = rowlight[y] / 170.0
        for x in range(W):
            r, g, b = sp[x, y]
            e = xenv(x + 0.5)
            rr = r * rl * e
            gg = g * rl * e
            bb = b * rl * e

            if has_cyan:
                dx = (x + 0.5) - bead_x
                if -38.0 <= dx <= 26.0:
                    hot = math.exp(-((dx / 3.2) ** 2))
                    halo = math.exp(-((dx / 16.0) ** 2))
                    trail = 0.0
                    if dx < 0:
                        behind = -dx
                        flick = 0.6 + 0.4 * hash01(int((x + phase) * 2) % 512, y, seed=8443)
                        trail = (smoothstep(0.0, 3.0, behind)
                                 * (max(0.0, 1.0 - behind / 32.0) ** 1.4) * flick)
                    amt = (1.0 * hot + 0.7 * halo + 0.55 * trail) * travel
                    in_ap = 1.0 if ap_top <= y <= ap_bot else 0.0
                    near_ap = math.exp(-(((y - ap_mid) / 5.0) ** 2))
                    dark = 1.0 - (r + g + b) / 765.0   # holes let more light out
                    bulge = (hot + 0.55 * halo) * travel
                    a = min(1.0, amt * in_ap * (0.35 + 0.65 * dark) + 0.30 * bulge * near_ap)
                    if a > 0.01:
                        rr = rr * (1.0 - 0.8 * a) + 10.0 * a
                        gg = gg + 212.0 * a
                        bb = bb + 200.0 * a
                        if a > 0.5:
                            rr += 175.0 * (a - 0.5) / 0.5   # hot core goes white

            fp[x, fy] = (clamp(rr), clamp(gg), clamp(bb), 255)

    # lip shadow, contact shadow, rounded disc corners
    bottom = CORE_Y + CORE_H
    ovl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ovl)
    # the well's top lip overhangs the wheel: firm occlusion fading down
    for row in range(CORE_Y, CORE_Y + 5):
        a = int(190 * (1.0 - smoothstep(CORE_Y, CORE_Y + 5.0, row + 0.5)))
        od.rectangle((0, row, W, row), fill=(0, 0, 0, a))
    # the wheel presses into the well floor: tight contact shadow
    for row in range(bottom - 4, bottom):
        a = int(200 * smoothstep(bottom - 4.0, bottom, row + 0.5))
        od.rectangle((0, row, W, row), fill=(0, 0, 0, a))
    # tiny corner round only — the well's own rounded corners do the cutting
    r_c = 2.5
    for cx, sx in ((0, 1), (W, -1)):
        for col in range(int(r_c)):
            dxx = r_c - col
            dy = r_c - math.sqrt(max(0.0, r_c * r_c - dxx * dxx))
            hgt = int(dy)
            if hgt > 0:
                x = cx + sx * col
                od.rectangle((x, CORE_Y, x, CORE_Y + hgt), fill=(0, 0, 0, 255))
                od.rectangle((x, bottom - hgt, x, bottom), fill=(0, 0, 0, 255))
    img.alpha_composite(ovl)
    return img


def render_strip() -> Image.Image:
    strip = Image.new("RGBA", (FRAMES * W, H), (0, 0, 0, 0))
    frame0 = render_frame(0)
    for i in range(FRAMES):
        frame = frame0 if i in (0, FRAMES - 1) else render_frame(i)
        strip.alpha_composite(frame, (i * W, 0))
    return strip


def composite_into_panel(frame_img: Image.Image) -> Image.Image:
    """Paste a frame into the actual panel art at the morph well, 4x zoom."""
    panel = Image.open(r"C:\Users\hooki\df2\juce-shell\assets\ui\df2_panel_shadow.png").convert("RGBA")
    editor = panel.resize((360, 560), Image.Resampling.LANCZOS)
    editor.alpha_composite(frame_img, (45, 242))
    crop = editor.crop((25, 220, 225, 300))
    return crop.resize((crop.width * 4, crop.height * 4), Image.Resampling.NEAREST)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=r"C:\Users\hooki\df2\juce-shell\assets\ui\thumbwheel_runtime_strip_129_149x40.png",
        help="Output PNG path for the 19221x40 runtime strip.",
    )
    parser.add_argument("--preview", action="store_true",
                        help="Render single frames composited into the real panel art.")
    parser.add_argument("--frames", default="0,32,64",
                        help="Comma-separated frame list for --preview.")
    parser.add_argument("--preview-dir", default=r"C:\Users\hooki\df2\dev\tmp\thumbwheel_now")
    args = parser.parse_args()

    if args.preview:
        out = Path(args.preview_dir)
        out.mkdir(parents=True, exist_ok=True)
        for fr in (int(f) for f in args.frames.split(",")):
            im = render_frame(fr)
            composite_into_panel(im).save(out / f"in_ui_f{fr:03d}.png")
        print(out)
        return

    strip = render_strip()
    assert strip.size == (19221, 40), strip.size
    f0 = strip.crop((0, 0, W, H)).tobytes()
    f128 = strip.crop(((FRAMES - 1) * W, 0, FRAMES * W, H)).tobytes()
    assert f0 == f128, "frame 0 and frame 128 must be byte-identical"
    assert render_frame(FRAMES - 1).tobytes() == render_frame(0).tobytes(), \
        "scroll must complete exactly one period over 128 steps"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    strip.save(out_path)
    print(out_path)


if __name__ == "__main__":
    main()
