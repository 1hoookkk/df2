#!/usr/bin/env python3
"""Composite a protruding white roller face into the clean panel wells.

The supplied visual target shows the roller body, not a full pre-framed module:
white ABS cylinder, rounded end rolloff, central dark aperture, teeth/ribs, and
purple light behind the openings. This script lets the existing panel well remain
the frame and draws only the wheel face plus contact shadow.
"""

from __future__ import annotations

import argparse
import math
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


def rounded_mask(size: tuple[int, int], radius: int, blur: float = 0.8) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(blur))


def lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def draw_roller(size: tuple[int, int], glow_pos: float) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    px = img.load()
    radius = h / 2.0
    cx_left = radius
    cx_right = w - radius
    cy = h / 2.0

    mask = rounded_mask(size, int(radius), 0.5)
    mask_px = mask.load()

    for y in range(h):
        yn = (y + 0.5 - cy) / radius
        cyl = max(0.0, 1.0 - yn * yn)
        base = 118 + 118 * (cyl ** 0.36)
        if y < h * 0.18:
            base += 18
        if y > h * 0.72:
            base -= 28
        for x in range(w):
            a = mask_px[x, y]
            if a == 0:
                continue
            edge = min(x, w - 1 - x)
            edge_t = max(0.0, min(1.0, edge / (h * 0.55)))
            edge_roll = 0.45 + 0.55 * (edge_t * edge_t * (3 - 2 * edge_t))
            grain = ((x * 17 + y * 31) % 19 - 9) * 0.8
            v = max(35, min(246, base * edge_roll + grain))
            px[x, y] = (int(v * 1.03), int(v * 1.00), int(v * 0.93), a)

    draw = ImageDraw.Draw(img, "RGBA")

    # Central black aperture/channel, where the glow is visible.
    aperture_y1 = int(h * 0.40)
    aperture_y2 = int(h * 0.61)
    draw.rounded_rectangle((int(h * 0.18), aperture_y1, w - int(h * 0.18), aperture_y2), radius=max(2, h // 16), fill=(8, 8, 7, 225))

    # Teeth/ribs: rounded raised lips above and below the aperture, with dark
    # gaps falling through the central channel.
    pitch = max(18, int(w / 18))
    rib_w = max(6, int(pitch * 0.42))
    start = int(h * 0.45)
    for x in range(int(h * 0.35), w - int(h * 0.25), pitch):
        skew = int(math.sin(x * 0.043) * 2)
        top_poly = [
            (x + skew, int(h * 0.17)),
            (x + rib_w + skew, int(h * 0.18)),
            (x + rib_w // 2 + skew, aperture_y1 + 3),
        ]
        bot_poly = [
            (x + skew, int(h * 0.83)),
            (x + rib_w + skew, int(h * 0.82)),
            (x + rib_w // 2 + skew, aperture_y2 - 2),
        ]
        draw.polygon(top_poly, fill=(214, 211, 199, 145))
        draw.line((x + skew + 1, int(h * 0.21), x + rib_w // 2 + skew, aperture_y1), fill=(96, 94, 88, 115), width=max(1, h // 34))
        draw.polygon(bot_poly, fill=(172, 168, 156, 150))
        draw.line((x + skew + rib_w - 1, int(h * 0.78), x + rib_w // 2 + skew, aperture_y2), fill=(55, 54, 51, 125), width=max(1, h // 34))
        gap_x = x + rib_w // 2 + skew
        draw.rounded_rectangle((gap_x - 3, aperture_y1 + 1, gap_x + 4, aperture_y2 - 1), radius=1, fill=(2, 2, 2, 195))

    # Purple internal light behind the aperture and transmitted through nearby ribs.
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gx = int(w * glow_pos)
    for r, alpha in ((w // 10, 24), (w // 18, 54), (w // 34, 115)):
        gd.ellipse((gx - r, int(h * 0.24), gx + r, int(h * 0.79)), fill=(140, 88, 255, alpha))
    gd.rounded_rectangle((gx - w // 15, aperture_y1, gx + w // 23, aperture_y2), radius=4, fill=(222, 204, 255, 150))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(1.7)))

    # Specular top streak and lower contact darkening on the wheel itself.
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay, "RGBA")
    od.rounded_rectangle((int(h * 0.5), int(h * 0.12), w - int(h * 0.55), int(h * 0.22)), radius=5, fill=(255, 255, 246, 62))
    od.rounded_rectangle((int(h * 0.28), int(h * 0.79), w - int(h * 0.28), int(h * 0.95)), radius=7, fill=(0, 0, 0, 50))
    img = Image.alpha_composite(img, overlay)
    img.putalpha(mask)
    return img


def composite(panel_path: Path, out_path: Path, install_path: Path | None) -> None:
    panel = Image.open(panel_path).convert("RGBA")
    canvas = panel.copy()
    wells = []
    for _, x1, y1, x2, y2 in connected_black_rects(panel):
        width = x2 - x1
        height = y2 - y1
        if 360 <= width <= 520 and 70 <= height <= 120 and y1 > 500:
            wells.append((x1, y1, x2, y2))
    wells = sorted(wells, key=lambda r: r[1])[:2]
    if len(wells) != 2:
        raise RuntimeError(f"expected two lower long wells, found {wells}")

    for i, (x1, y1, x2, y2) in enumerate(wells):
        well_w = x2 - x1
        well_h = y2 - y1
        wheel_w = well_w + 18
        wheel_h = int(well_h * 0.73)
        wheel_x = x1 - 9
        wheel_y = y1 + (well_h - wheel_h) // 2

        shadow = Image.new("RGBA", (wheel_w + 52, wheel_h + 52), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((24, 29, 24 + wheel_w - 1, 29 + wheel_h - 1), radius=wheel_h // 2, fill=(0, 0, 0, 135))
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        canvas.alpha_composite(shadow, (wheel_x - 24, wheel_y - 18))

        wheel = draw_roller((wheel_w, wheel_h), 0.42 if i == 0 else 0.60)
        canvas.alpha_composite(wheel, (wheel_x, wheel_y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path)
    if install_path is not None:
        install_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(install_path)
    print(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", default=r"C:\Users\hooki\Downloads\ChatGPT Image May 30, 2026, 12_45_47 AM - grid seated rounded.png")
    parser.add_argument("--out", default=r"C:\Users\hooki\df2\dev\tmp\thumbwheel_white_depth\panel_white_depth_roller.png")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    install = Path(r"C:\Users\hooki\df2\juce-shell\assets\ui\df2_panel_shadow.png") if args.install else None
    composite(Path(args.panel), Path(args.out), install)


if __name__ == "__main__":
    main()
