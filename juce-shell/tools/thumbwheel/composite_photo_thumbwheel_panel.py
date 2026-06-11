#!/usr/bin/env python3
"""Composite the existing old-style thumbwheel preview into the clean panel."""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def connected_black_rects(panel: Image.Image) -> list[tuple[int, int, int, int, int]]:
    arr = np.asarray(panel.convert("RGB"))
    mask = (arr[..., 0] < 20) & (arr[..., 1] < 20) & (arr[..., 2] < 20)
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    rects: list[tuple[int, int, int, int, int]] = []

    for y in range(h):
        xs = np.where(mask[y] & ~seen[y])[0]
        for x0 in xs:
            if seen[y, x0] or not mask[y, x0]:
                continue
            q = deque([(int(x0), y)])
            seen[y, x0] = True
            px: list[int] = []
            py: list[int] = []
            while q:
                x, yy = q.popleft()
                px.append(x)
                py.append(yy)
                for nx, ny in ((x + 1, yy), (x - 1, yy), (x, yy + 1), (x, yy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((nx, ny))
            if len(px) > 100:
                rects.append((len(px), min(px), min(py), max(px) + 1, max(py) + 1))

    return sorted(rects, reverse=True)


def old_style_row(sheet: Image.Image, row: int) -> Image.Image:
    # strip_contact_large.png is six 320px rows separated on a 70px pitch.
    y = row * 70
    # Use only the roller face. The full preview row includes a black outer
    # socket; pasting that into the already-black panel well creates a doubled
    # capsule shape.
    return sheet.crop((20, y + 18, 300, min(y + 50, sheet.height))).convert("RGBA")


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(0.35))


def composite(panel_path: Path, strip_path: Path, out_path: Path, install_path: Path | None) -> None:
    panel = Image.open(panel_path).convert("RGBA")
    strip = Image.open(strip_path).convert("RGBA")
    canvas = panel.copy()

    long_wells = []
    for area, x1, y1, x2, y2 in connected_black_rects(panel):
        width = x2 - x1
        height = y2 - y1
        if 360 <= width <= 520 and 70 <= height <= 120 and y1 > 500:
            long_wells.append((x1, y1, x2, y2))
    long_wells = sorted(long_wells, key=lambda r: r[1])[:2]
    if len(long_wells) != 2:
        raise RuntimeError(f"expected two lower long wells, found {long_wells}")

    for n, (x1, y1, x2, y2) in enumerate(long_wells):
        well_w = x2 - x1
        well_h = y2 - y1
        wheel_w = well_w - 20
        wheel_h = 50
        wheel_x = x1 + 10
        wheel_y = y1 + (well_h - wheel_h) // 2

        row = old_style_row(strip, 2 + n).resize((wheel_w, wheel_h), Image.Resampling.LANCZOS)
        row.putalpha(rounded_mask((wheel_w, wheel_h), 5))

        shadow = Image.new("RGBA", (wheel_w + 24, wheel_h + 24), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((12, 17, 12 + wheel_w - 1, 17 + wheel_h - 1), radius=7, fill=(0, 0, 0, 70))
        shadow = shadow.filter(ImageFilter.GaussianBlur(4))
        canvas.alpha_composite(shadow, (wheel_x - 12, wheel_y - 10))
        canvas.alpha_composite(row, (wheel_x, wheel_y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path)
    if install_path is not None:
        install_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(install_path)
    print(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", default=r"C:\Users\hooki\Downloads\ChatGPT Image May 30, 2026, 12_45_47 AM - grid seated rounded.png")
    parser.add_argument("--strip", default=r"C:\Users\hooki\df2\juce-shell\tools\thumbwheel\_preview\photo\strip_contact_large.png")
    parser.add_argument("--out", default=r"C:\Users\hooki\df2\dev\tmp\thumbwheel_photo_fit\panel_photo_thumbwheels.png")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    install_path = Path(r"C:\Users\hooki\df2\juce-shell\assets\ui\df2_panel_shadow.png") if args.install else None
    composite(Path(args.panel), Path(args.strip), Path(args.out), install_path)


if __name__ == "__main__":
    main()
