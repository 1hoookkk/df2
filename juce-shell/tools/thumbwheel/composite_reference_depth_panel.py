#!/usr/bin/env python3
"""Composite protruding roller modules from the supplied depth reference."""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


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


def rounded_mask(size: tuple[int, int], radius: int, blur: float = 0.55) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(blur))


def module_from_reference(ref: Image.Image, top: bool) -> Image.Image:
    # Measured from rrrrr (2).jpg with dark connected-component bbox.
    box = (55, 410, 350, 486) if top else (52, 527, 350, 603)
    module = ref.crop(box).convert("RGB")
    # Bring the old silver control toward the warmer panel without destroying
    # the dark wheel relief or cyan light.
    module = ImageEnhance.Contrast(module).enhance(1.08)
    module = ImageEnhance.Color(module).enhance(0.82)
    return module.convert("RGBA")


def composite(panel_path: Path, ref_path: Path, out_path: Path, install_path: Path | None) -> None:
    panel = Image.open(panel_path).convert("RGBA")
    ref = Image.open(ref_path).convert("RGBA")
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
        module_w = well_w + 26
        module_h = int(round(module_w / 4.22))
        module_x = x1 - 13
        module_y = y1 + (well_h - module_h) // 2 + 2

        module = module_from_reference(ref, top=(n == 0)).resize((module_w, module_h), Image.Resampling.LANCZOS)
        module.putalpha(rounded_mask((module_w, module_h), max(10, module_h // 5)))

        shadow = Image.new("RGBA", (module_w + 42, module_h + 42), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((20, 25, 20 + module_w - 1, 25 + module_h - 1), radius=max(10, module_h // 5), fill=(0, 0, 0, 120))
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        canvas.alpha_composite(shadow, (module_x - 20, module_y - 16))
        canvas.alpha_composite(module, (module_x, module_y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path)
    if install_path is not None:
        install_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(install_path)
    print(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", default=r"C:\Users\hooki\Downloads\ChatGPT Image May 30, 2026, 12_45_47 AM - grid seated rounded.png")
    parser.add_argument("--reference", default=r"C:\Users\hooki\Downloads\rrrrr (2).jpg")
    parser.add_argument("--out", default=r"C:\Users\hooki\df2\dev\tmp\thumbwheel_reference_depth\panel_reference_depth.png")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    install = Path(r"C:\Users\hooki\df2\juce-shell\assets\ui\df2_panel_shadow.png") if args.install else None
    composite(Path(args.panel), Path(args.reference), Path(args.out), install)


if __name__ == "__main__":
    main()
