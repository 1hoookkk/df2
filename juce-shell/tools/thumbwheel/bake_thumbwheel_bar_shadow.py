#!/usr/bin/env python3
"""Bake bar-shaped thumbwheel contact shadows into the DF2 panel asset.

This does not draw the thumbwheel body or glow. It only adds the faceplate
shadow that a shallow protruding horizontal thumbwheel bar would cast.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


PANEL_DEFAULT = Path(
    r"C:\Users\hooki\Downloads\ChatGPT Image May 30, 2026, 12_45_47 AM - grid seated rounded.png"
)
INSTALL_DEFAULT = Path(r"C:\Users\hooki\df2\juce-shell\assets\ui\df2_panel_shadow.png")

# Source-space well bounds used by PluginEditor.cpp.
WELLS = (
    (127.0, 694.0, 423.0, 101.0),
    (127.0, 871.0, 423.0, 101.0),
)


def thumbwheel_rect(well: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x, y, w, h = well
    # Exact source coordinates corresponding to well.reduced(4.0f, 3.7f).translated(0.0f, 0.2f) in C++
    reduced_x = 4.0 * (1024.0 / 360.0)
    reduced_y = 3.7 * (1591.0 / 560.0)
    y_nudge = 0.2 * (1591.0 / 560.0)

    wheel_x = x + reduced_x
    wheel_y = y + reduced_y + y_nudge
    wheel_w = w - 2.0 * reduced_x
    wheel_h = h - 2.0 * reduced_y
    return (
        round(wheel_x),
        round(wheel_y),
        round(wheel_x + wheel_w),
        round(wheel_y + wheel_h),
    )


def add_shadow(canvas: Image.Image, rect: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = rect
    w = x2 - x1
    h = y2 - y1
    radius = max(8, h // 4)

    # Broad cast shadow on the faceplate. Offset down and a touch left, matching
    # the existing panel light direction.
    broad = Image.new("RGBA", (w + 90, h + 90), (0, 0, 0, 0))
    bd = ImageDraw.Draw(broad)
    bd.rounded_rectangle((34, 42, 34 + w - 1, 42 + h - 1), radius=radius, fill=(0, 0, 0, 88))
    broad = broad.filter(ImageFilter.GaussianBlur(15))
    canvas.alpha_composite(broad, (x1 - 42, y1 - 22))

    # Tighter contact shadow just below the lower edge of the protruding bar.
    contact = Image.new("RGBA", (w + 42, h + 42), (0, 0, 0, 0))
    cd = ImageDraw.Draw(contact)
    cd.rounded_rectangle((18, 23, 18 + w - 1, 23 + h - 1), radius=radius, fill=(0, 0, 0, 96))
    contact = contact.filter(ImageFilter.GaussianBlur(6))
    canvas.alpha_composite(contact, (x1 - 20, y1 - 8))


def bake(panel_path: Path, out_path: Path) -> None:
    canvas = Image.open(panel_path).convert("RGBA")
    for well in WELLS:
        add_shadow(canvas, thumbwheel_rect(well))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path)
    print(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", default=str(PANEL_DEFAULT))
    parser.add_argument("--out", default=str(INSTALL_DEFAULT))
    args = parser.parse_args()
    bake(Path(args.panel), Path(args.out))


if __name__ == "__main__":
    main()
