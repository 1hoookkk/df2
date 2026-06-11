#!/usr/bin/env python3
"""Render the TRENCH 96x14 horizontal thumbwheel filmstrip (front mask layer).

Clean-room: structure measured from the E-mu X3 roller BITMAP4331 (a row of
molded notch-blocks; bright flat caps on top, graduated bodies, recessed grooves
between keys). Every pixel here is authored — no E-mu source pixels are copied.

Two-layer model:
  FRONT (this file) : one static 96x14 bone-white notch-block mask, repeated x129.
                      The block BODIES are semi-transparent so the internal light
                      shows through their full height (NOT a thin centre slot).
                      The top/bottom slot lips and the bright caps stay opaque.
  BACK  (runtime)   : ultraviolet light drawn behind this mask at the value
                      x-position, sweeping L->R, filling the block bodies, unlit
                      at frames 0 and 128.
"""
import argparse
import math
from pathlib import Path

from PIL import Image


FRAMES = 129
NATIVE_W = 96
NATIVE_H = 14
SCALE = 4
OUT_W = NATIVE_W * SCALE
OUT_H = NATIVE_H * SCALE

# bone-white neutral palette (peak is bone, NOT pure white -> no glowing slats)
BONE_DEEP = (62, 61, 58, 255)
BONE_SHADOW = (108, 107, 103, 255)
BONE_BASE = (170, 170, 165, 255)
BONE_MID = (206, 206, 201, 255)
BONE_HIGH = (234, 233, 228, 255)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def smoothstep(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def noise01(a, b, c, seed):
    n = (a * 73856093) ^ (b * 19349663) ^ (c * 83492791) ^ seed
    n = (n ^ (n >> 13)) * 1274126177
    return ((n ^ (n >> 16)) & 255) / 255.0


def mix_color(a, b, t):
    return tuple(int(round(a[i] * (1.0 - t) + b[i] * t)) for i in range(4))


def bone_plastic(v):
    v = clamp(v, 0, 255)
    if v < 88:
        return mix_color(BONE_DEEP, BONE_SHADOW, v / 88.0)
    if v < 150:
        return mix_color(BONE_SHADOW, BONE_BASE, (v - 88.0) / 62.0)
    if v < 200:
        return mix_color(BONE_BASE, BONE_MID, (v - 150.0) / 50.0)
    return mix_color(BONE_MID, BONE_HIGH, (v - 200.0) / 30.0)


# Vertical block profile: bright flat CAP (rows 2-3) over a smooth top-down
# gradient body to a dark base. No dark centre line. Lips (0-1, 12-13) occlude.
ROW_BASE = (30, 92, 242, 212, 176, 156, 138, 122, 106, 90, 74, 56, 36, 24)
# Transmission fills the whole body so the glow lights the block height.
ROW_TRANS = (0.00, 0.00, 0.08, 0.20, 0.50, 0.66, 0.78, 0.82,
             0.78, 0.64, 0.42, 0.16, 0.00, 0.00)
LIP_ROWS = (0, 1, 12, 13)

PITCH = 4   # block pitch: key width 3 + 1px recess groove


def block_at(x):
    local = x % PITCH
    return x // PITCH, local, (local == PITCH - 1)


def end_rolloff(x):
    e = min(x, NATIVE_W - 1 - x)
    return 0.50 + 0.50 * smoothstep(e / 11.0)


def corner_alpha(x):
    e = min(x, NATIVE_W - 1 - x)
    return clamp(smoothstep((e + 0.4) / 2.6), 0.0, 1.0)


def surface_luma(x, y, args):
    """A row of raised, beveled molded keys (lit from top-left): bright flat cap,
    left-edge light catch + right-edge/groove shadow (3D relief), recessed grooves
    between keys -> protruding blocks, not flat teeth, never a dark centre line."""
    idx, local, is_groove = block_at(x)
    v = float(ROW_BASE[y])
    # per-block molded tone (some keys proud, some worn)
    v += (noise01(idx, 0, 0, args.seed) - 0.5) * args.noise

    if 2 <= y <= 11:                      # key bevel only on the key face
        if is_groove:
            gdepth = 30.0 + 26.0 * noise01(idx, 7, 0, args.seed + 5)
            if y in (2, 3):
                gdepth *= 0.45            # caps stay bright -> reads as keys
            elif y >= 10:
                gdepth *= 0.6
            v -= gdepth
        elif local == 0:
            v += 24.0                     # left wall catches light
        elif local == PITCH - 2:
            v -= 16.0                     # right wall in shadow
    if y == 2 and not is_groove:
        v += 18.0                         # crisp bright flat cap
    if y == 4 and not is_groove:
        v -= 8.0                          # under-cap shadow defines the relief

    v += (noise01(x, y + 31, 0, args.seed + 7) - 0.5) * 7.0
    v *= end_rolloff(x)
    return v


def row_alpha(x, y, args):
    """Opacity of the mask. Block bodies are semi-transparent (light fills the
    whole body height); caps, grooves and lips are more opaque."""
    base = 255.0 * corner_alpha(x)
    tr = ROW_TRANS[y]
    if tr <= 0.0:
        return int(base)
    _, _, is_groove = block_at(x)
    striate = 1.0 - tr * (0.40 if is_groove else 0.96)
    return int(base * clamp(striate, 0.05, 1.0))


def draw_native_frame(args):
    img = Image.new("RGBA", (NATIVE_W, NATIVE_H), (0, 0, 0, 0))
    px = img.load()
    for y in range(NATIVE_H):
        is_lip = y in LIP_ROWS
        for x in range(NATIVE_W):
            v = surface_luma(x, y, args)
            rgb = bone_plastic(v)
            if is_lip:
                rgb = mix_color(rgb, BONE_DEEP, 0.6)   # occluding slot lip
            px[x, y] = (*rgb[:3], row_alpha(x, y, args))
    return img


def make_contact_sheet(native_frames):
    picks = list(range(0, FRAMES, 8))
    if picks[-1] != FRAMES - 1:
        picks.append(FRAMES - 1)
    cols = 4
    gap = 4
    rows = math.ceil(len(picks) / cols)
    sheet = Image.new("RGBA", (cols * OUT_W + (cols - 1) * gap, rows * OUT_H + (rows - 1) * gap), (40, 40, 44, 255))
    for i, frame_idx in enumerate(picks):
        cell = native_frames[frame_idx].resize((OUT_W, OUT_H), Image.Resampling.NEAREST)
        sheet.alpha_composite(cell, ((i % cols) * (OUT_W + gap), (i // cols) * (OUT_H + gap)))
    return sheet


def write_readme(out_dir):
    text = """TRENCH production thumbwheel bitmap filmstrip (front mask layer)

Source status:
- Original generated asset. Structure measured from the E-mu X3 roller BITMAP4331;
  no E-mu source pixels are loaded, cropped, traced, or copied.
- Native 96 x 14 px frames, 4x nearest-neighbour export.
- One fixed bone-white notch-block mask repeated across all 129 frames.

Two-layer runtime model:
- This bitmap is the static front mask (bone-white molded keys; bright flat caps,
  recessed grooves, opaque top/bottom slot lips, semi-transparent block bodies).
- The ultraviolet light is drawn at runtime BEHIND this mask, sweeping L->R with
  the value, and shows through the block bodies (full height, not a centre slot).
"""
    (out_dir / "README.txt").write_text(text, encoding="utf-8")


def write_juce(out_dir):
    code = """#pragma once

#include <JuceHeader.h>
#include <cmath>

inline void drawThumbwheelFilmstrip(juce::Graphics& g,
                                    const juce::Image& strip,
                                    juce::Rectangle<int> dst,
                                    float normalisedValue)
{
    constexpr int numFrames = 129;
    int frameWidth = strip.getWidth() / numFrames;
    int frameHeight = strip.getHeight();
    int frame = juce::jlimit(0, numFrames - 1, (int) std::round(normalisedValue * (numFrames - 1)));
    juce::Rectangle<int> src { frame * frameWidth, 0, frameWidth, frameHeight };
    g.drawImage(strip, dst.getX(), dst.getY(), dst.getWidth(), dst.getHeight(),
                src.getX(), src.getY(), src.getWidth(), src.getHeight());
}
"""
    (out_dir / "JuceThumbwheelFilmstrip.h").write_text(code, encoding="utf-8")


def render(args):
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    fixed_frame = draw_native_frame(args)
    native_frames = [fixed_frame.copy() for _ in range(FRAMES)]

    native_strip = Image.new("RGBA", (FRAMES * NATIVE_W, NATIVE_H), (0, 0, 0, 0))
    for i, frame in enumerate(native_frames):
        native_strip.alpha_composite(frame, (i * NATIVE_W, 0))
    native_strip.save(out_dir / "native_strip_129_96x14.png")

    upscaled_strip = native_strip.resize((FRAMES * OUT_W, OUT_H), Image.Resampling.NEAREST)
    upscaled_strip.save(out_dir / "upscaled_strip_129_384x56.png")

    for i in (0, 64, 128):
        native_frames[i].resize((OUT_W, OUT_H), Image.Resampling.NEAREST).save(out_dir / f"frame_{i:03d}.png")

    make_contact_sheet(native_frames).save(out_dir / "contact_sheet_every8.png")
    write_readme(out_dir)
    write_juce(out_dir)


def parse_args():
    parser = argparse.ArgumentParser(description="Render the TRENCH 96x14 notch-block thumbwheel filmstrip.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--noise", type=float, default=26.0)
    parser.add_argument("--seed", type=int, default=9027)
    return parser.parse_args()


if __name__ == "__main__":
    render(parse_args())
