#!/usr/bin/env python3
import argparse
import math
from pathlib import Path

from PIL import Image, ImageFilter


FRAMES = 129
SRC_FRAME_W = 85
SRC_FRAME_H = 11
OUT_FRAME_W = 340
OUT_FRAME_H = 44
SRC_W = FRAMES * SRC_FRAME_W
SRC_H = SRC_FRAME_H
DEFAULT_SOURCE = r"C:\Users\hooki\OneDrive\Pictures\Screenshots\BITMAP4332_1.bmp"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def is_source_illumination(r, g, b):
    cyan = g > r + 18 and b > r + 18 and (g > 55 or b > 55)
    magenta = r > g + 18 and b > g + 10 and (r > 65 or b > 55)
    return cyan or magenta


def is_source_cyan(r, g, b):
    return g > r + 18 and b > r + 18 and (g > 55 or b > 55)


def luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def remap_body(r, g, b, edge_scale):
    y = luma(r, g, b)
    chroma = max(r, g, b) - min(r, g, b)
    highlight = max(0.0, (y - 72.0) / 120.0)
    shadow = max(0.0, (42.0 - y) / 42.0)
    v = 10 + y * 0.47 + highlight * 42 - shadow * 16
    v *= edge_scale
    if chroma < 14:
        return (
            int(clamp(v * 0.88, 0, 255)),
            int(clamp(v * 0.92, 0, 255)),
            int(clamp(v * 0.94, 0, 255)),
            255,
        )
    return (
        int(clamp(v * 0.80, 0, 255)),
        int(clamp(v * 0.85, 0, 255)),
        int(clamp(v * 0.88, 0, 255)),
        255,
    )


def remap_cyan(r, g, b, edge_scale, source_is_cyan):
    y = luma(r, g, b)
    chroma = max(r, g, b) - min(r, g, b)
    strength = clamp(chroma / 135.0, 0.0, 1.0)
    intensity = clamp((y - 28.0) / 128.0, 0.0, 1.0) * strength
    if not source_is_cyan:
        intensity *= 0.62

    body_r, body_g, body_b, _ = remap_body(r, g, b, edge_scale)
    target_g = 116 + 88 * intensity
    target_b = 124 + 78 * intensity
    return (
        int(clamp(body_r * (1.0 - 0.74 * intensity), 0, 255)),
        int(clamp(body_g * (1.0 - 0.45 * intensity) + target_g * intensity, 0, 255)),
        int(clamp(body_b * (1.0 - 0.38 * intensity) + target_b * intensity, 0, 255)),
        255,
    )


def edge_scale(x, w):
    edge = min(x, w - 1 - x)
    t = clamp(edge / 36.0, 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)
    return 0.58 + 0.42 * t


def remaster_frame(src_frame, add_bloom=True):
    up = src_frame.convert("RGBA").resize((OUT_FRAME_W, OUT_FRAME_H), Image.Resampling.NEAREST)
    out = Image.new("RGBA", up.size, (0, 0, 0, 0))
    src_px = up.load()
    out_px = out.load()
    cyan_mask = Image.new("L", up.size, 0)
    mask_px = cyan_mask.load()

    for y in range(OUT_FRAME_H):
        row_shadow = 1.0
        if y >= 36:
            row_shadow = 0.62
        elif y >= 28:
            row_shadow = 0.78
        elif 20 <= y <= 27:
            row_shadow = 0.64

        for x in range(OUT_FRAME_W):
            r, g, b, a = src_px[x, y]
            scale = edge_scale(x, OUT_FRAME_W) * row_shadow
            if is_source_illumination(r, g, b):
                source_is_cyan = is_source_cyan(r, g, b)
                out_px[x, y] = remap_cyan(r, g, b, scale, source_is_cyan)
                chroma = max(r, g, b) - min(r, g, b)
                intensity = clamp((luma(r, g, b) - 28.0) / 128.0, 0.0, 1.0) * clamp(chroma / 135.0, 0.0, 1.0)
                if not source_is_cyan:
                    intensity *= 0.62
                mask_px[x, y] = int(78 * intensity)
            else:
                out_px[x, y] = remap_body(r, g, b, scale)

    if add_bloom:
        bloom = Image.new("RGBA", up.size, (0, 0, 0, 0))
        bloom_px = bloom.load()
        blurred = cyan_mask.filter(ImageFilter.GaussianBlur(radius=1.2))
        blur_px = blurred.load()
        for y in range(OUT_FRAME_H):
            for x in range(OUT_FRAME_W):
                a = int(blur_px[x, y] * 0.12)
                if a:
                    bloom_px[x, y] = (0, 235, 222, a)
        out = Image.alpha_composite(bloom, out)

    return out


def verify_source(source):
    if source.size != (SRC_W, SRC_H):
        raise ValueError(f"expected source {SRC_W}x{SRC_H}, got {source.size[0]}x{source.size[1]}")


def make_contact(frames):
    picks = list(range(0, FRAMES, 8))
    if picks[-1] != FRAMES - 1:
        picks.append(FRAMES - 1)
    cols = 4
    gap = 4
    rows = math.ceil(len(picks) / cols)
    sheet = Image.new(
        "RGBA",
        (cols * OUT_FRAME_W + (cols - 1) * gap, rows * OUT_FRAME_H + (rows - 1) * gap),
        (0, 0, 0, 0),
    )
    for i, idx in enumerate(picks):
        sheet.alpha_composite(frames[idx], ((i % cols) * (OUT_FRAME_W + gap), (i // cols) * (OUT_FRAME_H + gap)))
    return sheet


def write_readme(out_dir, source_path):
    text = f"""TRENCH thumbwheel remaster from E-mu / X3 bitmap source

Source:
- {source_path}
- Verified size: {SRC_W} x {SRC_H} px
- Frames: {FRAMES}
- Source frame: {SRC_FRAME_W} x {SRC_FRAME_H} px

Outputs:
- trench_thumbwheel_from_emu_129_strip.png
- frame_000.png
- frame_064.png
- frame_128.png
- contact_sheet_every8.png
- README.txt
- JuceThumbwheelFilmstrip.h

Method:
1. Crop each exact 85 x 11 source frame.
2. Convert to RGBA.
3. Upscale to 340 x 44 with nearest-neighbour.
4. Remaster colors while preserving source ridge, highlight, shadow, and illumination shapes.
5. Add subtle bloom derived only from source illumination pixels.
6. Stitch 129 processed frames into one horizontal strip.
"""
    (out_dir / "README.txt").write_text(text, encoding="utf-8")


def write_juce_helper(out_dir):
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

    int frame = juce::jlimit(
        0,
        numFrames - 1,
        (int) std::round(normalisedValue * (numFrames - 1))
    );

    juce::Rectangle<int> src {
        frame * frameWidth,
        0,
        frameWidth,
        frameHeight
    };

    g.drawImage(strip,
                dst.getX(), dst.getY(), dst.getWidth(), dst.getHeight(),
                src.getX(), src.getY(), src.getWidth(), src.getHeight());
}
"""
    (out_dir / "JuceThumbwheelFilmstrip.h").write_text(code, encoding="utf-8")


def render(args):
    source_path = Path(args.source)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    source = Image.open(source_path).convert("RGBA")
    verify_source(source)

    frames = []
    for i in range(FRAMES):
        left = i * SRC_FRAME_W
        src_frame = source.crop((left, 0, left + SRC_FRAME_W, SRC_FRAME_H))
        frames.append(remaster_frame(src_frame, add_bloom=not args.no_bloom))

    strip = Image.new("RGBA", (FRAMES * OUT_FRAME_W, OUT_FRAME_H), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        strip.alpha_composite(frame, (i * OUT_FRAME_W, 0))
    strip.save(out_dir / "trench_thumbwheel_from_emu_129_strip.png")

    frames[0].save(out_dir / "frame_000.png")
    frames[64].save(out_dir / "frame_064.png")
    frames[128].save(out_dir / "frame_128.png")
    make_contact(frames).save(out_dir / "contact_sheet_every8.png")
    write_readme(out_dir, source_path)
    write_juce_helper(out_dir)


def parse_args():
    parser = argparse.ArgumentParser(description="Remaster E-mu / X3 129-frame thumbwheel bitmap into a TRENCH-compatible filmstrip.")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--out", required=True)
    parser.add_argument("--no-bloom", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    render(parse_args())
