#!/usr/bin/env python3
"""Measure BITMAP4331 roller references and build a source-derived panel preview.

This is intentionally source-derived internal UI work. It preserves the measured
85x16 E-mu frame structure instead of trying to hand-recreate it.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


FRAMES = 129
SRC_FRAME_W = 85
SRC_FRAME_H = 16
OUT_FRAME_W = 96
OUT_FRAME_H = 17
OUT_FRAME_H_JUCE = 14


def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def find_best_source_match(source: Image.Image, ref: Image.Image) -> dict:
    source_arr = np.asarray(source.convert("RGB")).astype(np.int16)
    candidates = []

    for sy in range(1, 10):
        if ref.height % sy:
            continue
        h = ref.height // sy
        if h != SRC_FRAME_H:
            continue
        for sx in range(1, 10):
            if ref.width % sx:
                continue
            w = ref.width // sx
            if w > source.width:
                continue
            small = ref.resize((w, h), Image.Resampling.BOX)
            small_arr = np.asarray(small.convert("RGB")).astype(np.int16)
            best_mse = float("inf")
            best_x = 0
            for x0 in range(0, source.width - w + 1):
                crop = source_arr[:, x0 : x0 + w, :]
                mse = float(np.mean((crop - small_arr) ** 2))
                if mse < best_mse:
                    best_mse = mse
                    best_x = x0
                    if mse == 0.0:
                        break
            candidates.append(
                {
                    "mse": best_mse,
                    "scale_x": sx,
                    "scale_y": sy,
                    "downscaled_width": w,
                    "downscaled_height": h,
                    "source_x": int(best_x),
                    "source_frame": best_x / SRC_FRAME_W,
                }
            )
            if best_mse == 0.0:
                return candidates[-1]

    if not candidates:
        raise ValueError(f"no integer 16px-high source match for {ref.size}")
    return sorted(candidates, key=lambda c: c["mse"])[0]


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
            q = deque([(x0, y)])
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


def remap_source_strip(source: Image.Image, frame_h: int) -> Image.Image:
    strip = Image.new("RGBA", (FRAMES * OUT_FRAME_W, frame_h), (0, 0, 0, 0))
    for i in range(FRAMES):
        src_frame = source.crop((i * SRC_FRAME_W, 0, (i + 1) * SRC_FRAME_W, SRC_FRAME_H))
        frame = src_frame.resize((OUT_FRAME_W, frame_h), Image.Resampling.NEAREST).convert("RGBA")
        strip.alpha_composite(frame, (i * OUT_FRAME_W, 0))
    return strip


def make_contact(strip: Image.Image, frame_w: int, frame_h: int) -> Image.Image:
    picks = list(range(0, FRAMES, 8))
    if picks[-1] != FRAMES - 1:
        picks.append(FRAMES - 1)
    cols = 4
    scale = 5
    gap = 8
    cell_w = frame_w * scale
    cell_h = frame_h * scale
    rows = math.ceil(len(picks) / cols)
    sheet = Image.new("RGBA", (cols * cell_w + (cols - 1) * gap, rows * cell_h + (rows - 1) * gap), (18, 18, 18, 255))
    for n, idx in enumerate(picks):
        frame = strip.crop((idx * frame_w, 0, (idx + 1) * frame_w, frame_h))
        frame = frame.resize((cell_w, cell_h), Image.Resampling.NEAREST)
        sheet.alpha_composite(frame, ((n % cols) * (cell_w + gap), (n // cols) * (cell_h + gap)))
    return sheet


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    w, h = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    return mask


def wheel_frame(source: Image.Image, index: int, size: tuple[int, int]) -> Image.Image:
    idx = max(0, min(FRAMES - 1, index))
    src = source.crop((idx * SRC_FRAME_W, 0, (idx + 1) * SRC_FRAME_W, SRC_FRAME_H))
    frame = src.resize(size, Image.Resampling.NEAREST).convert("RGBA")

    # Rounded clipping keeps the source rolloff but prevents a pasted rectangle.
    mask = rounded_mask(size, max(7, min(size) // 5)).filter(ImageFilter.GaussianBlur(0.35))
    frame.putalpha(mask)
    return frame


def drop_shadow(size: tuple[int, int]) -> Image.Image:
    w, h = size
    shadow = Image.new("RGBA", (w + 34, h + 34), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.rounded_rectangle((18, 20, 18 + w - 1, 20 + h - 1), radius=max(8, h // 5), fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(7))
    return shadow


def composite_panel(panel: Image.Image, source: Image.Image, out_path: Path) -> dict:
    canvas = panel.convert("RGBA")
    rects = connected_black_rects(panel)
    long_wells = []
    for area, x1, y1, x2, y2 in rects:
        width = x2 - x1
        height = y2 - y1
        if 360 <= width <= 520 and 70 <= height <= 120 and y1 > 500:
            long_wells.append((x1, y1, x2, y2, area))
    long_wells = sorted(long_wells, key=lambda r: r[1])[:2]
    if len(long_wells) != 2:
        raise RuntimeError(f"expected two lower long wells, found {long_wells}")

    placements = []
    for n, (x1, y1, x2, y2, area) in enumerate(long_wells):
        well_w = x2 - x1
        well_h = y2 - y1
        wheel_w = well_w - 30
        wheel_h = min(46, well_h - 48)
        wheel_x = x1 + 15
        wheel_y = y1 + (well_h - wheel_h) // 2 + 2
        idx = 58 if n == 0 else 72

        sh = drop_shadow((wheel_w, wheel_h))
        canvas.alpha_composite(sh, (wheel_x - 17, wheel_y - 8))

        wheel = wheel_frame(source, idx, (wheel_w, wheel_h))
        canvas.alpha_composite(wheel, (wheel_x, wheel_y))
        placements.append(
            {
                "well": [x1, y1, x2, y2],
                "wheel": [wheel_x, wheel_y, wheel_w, wheel_h],
                "source_frame": idx,
            }
        )

    canvas.convert("RGB").save(out_path)
    return {"long_wells": placements}


def write_measurements(out_dir: Path, source: Image.Image, refs: list[Path], panel: Image.Image, placements: dict) -> None:
    def json_default(value):
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        raise TypeError(f"{type(value).__name__} is not JSON serializable")

    rows = []
    measurements = {
        "source": {
            "size": list(source.size),
            "frames": FRAMES,
            "frame_size": [SRC_FRAME_W, SRC_FRAME_H],
        },
        "references": [],
        "panel_black_rects": [
            {"area": a, "rect": [x1, y1, x2, y2], "size": [x2 - x1, y2 - y1]}
            for a, x1, y1, x2, y2 in connected_black_rects(panel)[:10]
        ],
        "placements": placements,
    }

    for ref_path in refs:
        ref = Image.open(ref_path).convert("RGB")
        match = find_best_source_match(source, ref)
        down = ref.resize((match["downscaled_width"], match["downscaled_height"]), Image.Resampling.BOX)
        gray = np.asarray(down.convert("L"))
        row_luma = [int(round(v)) for v in gray.mean(axis=1)]
        measurements["references"].append(
            {
                "path": str(ref_path),
                "size": list(ref.size),
                "match": match,
                "row_luma": row_luma,
            }
        )
        rows.append(
            {
                "path": str(ref_path),
                "width": ref.width,
                "height": ref.height,
                "scale_x": match["scale_x"],
                "scale_y": match["scale_y"],
                "source_x": match["source_x"],
                "source_frame": f'{match["source_frame"]:.4f}',
                "mse": f'{match["mse"]:.6f}',
            }
        )

    (out_dir / "measurements.json").write_text(json.dumps(measurements, indent=2, default=json_default), encoding="utf-8")
    with (out_dir / "measurements.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    md = [
        "# BITMAP4331 Roller Measurements",
        "",
        f"- Source: {source.size[0]}x{source.size[1]}, {FRAMES} frames of {SRC_FRAME_W}x{SRC_FRAME_H}.",
        "- `roller_frames_17px.png` matches source frame 0 exactly at 6x.",
        "- `roller_start.png` matches source x 0..199 exactly at 6x.",
        "- `BITMAP4331_1_mid.png` matches source x 5232..5731 exactly at 4x.",
        "- Generated outputs are source-derived internal previews, not clean-room shipping assets.",
        "",
        "## Outputs",
        "",
        "- `measured_strip_129_96x17.png`",
        "- `measured_strip_129_96x14.png`",
        "- `contact_sheet_every8.png`",
        "- `panel_measured_4331_rollers.png`",
    ]
    (out_dir / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=r"C:\Users\hooki\do-it\emu-x3-bitmap-dump\BITMAP4331_1.bmp")
    parser.add_argument("--panel", default=r"C:\Users\hooki\Downloads\ChatGPT Image May 30, 2026, 12_45_47 AM - grid seated rounded.png")
    parser.add_argument("--out-dir", default=r"C:\Users\hooki\df2\dev\tmp\thumbwheel_4331_measured")
    parser.add_argument("--install-panel", default=r"C:\Users\hooki\df2\juce-shell\assets\ui\df2_panel_shadow.png")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    source_path = Path(args.source)
    source = Image.open(source_path).convert("RGB")
    if source.size != (FRAMES * SRC_FRAME_W, SRC_FRAME_H):
        raise ValueError(f"expected {FRAMES * SRC_FRAME_W}x{SRC_FRAME_H}, got {source.size}")

    refs = [
        Path(r"C:\Users\hooki\OneDrive\Pictures\Screenshots\roller_frames_17px.png"),
        Path(r"C:\Users\hooki\OneDrive\Pictures\Screenshots\roller_start.png"),
        Path(r"C:\Users\hooki\OneDrive\Pictures\Screenshots\BITMAP4331_1_mid.png"),
    ]
    for ref in refs:
        if not ref.exists():
            raise FileNotFoundError(ref)

    strip17 = remap_source_strip(source, OUT_FRAME_H)
    strip14 = remap_source_strip(source, OUT_FRAME_H_JUCE)
    strip17.save(out_dir / "measured_strip_129_96x17.png")
    strip14.save(out_dir / "measured_strip_129_96x14.png")
    make_contact(strip17, OUT_FRAME_W, OUT_FRAME_H).save(out_dir / "contact_sheet_every8.png")
    for i in (0, 58, 64, 72, 128):
        strip17.crop((i * OUT_FRAME_W, 0, (i + 1) * OUT_FRAME_W, OUT_FRAME_H)).resize((OUT_FRAME_W * 6, OUT_FRAME_H * 6), Image.Resampling.NEAREST).save(out_dir / f"frame_{i:03d}_96x17_6x.png")

    panel = Image.open(args.panel).convert("RGB")
    panel_out = out_dir / "panel_measured_4331_rollers.png"
    placements = composite_panel(panel, source, panel_out)
    write_measurements(out_dir, source, refs, panel, placements)

    install_panel = Path(args.install_panel)
    install_panel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(panel_out, install_panel)
    print(json.dumps({"out_dir": str(out_dir), "installed_panel": str(install_panel), **placements}, indent=2, default=lambda v: int(v) if isinstance(v, np.integer) else v))


if __name__ == "__main__":
    main()
