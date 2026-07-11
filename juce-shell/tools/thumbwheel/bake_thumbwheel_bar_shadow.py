#!/usr/bin/env python3
"""Bake bar-shaped thumbwheel contact shadows into the DF2 panel asset.

This does not draw the thumbwheel body or glow. It only adds the faceplate
shadow that a shallow protruding horizontal thumbwheel bar would cast.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


PANEL_DEFAULT = Path(r"C:\Users\hooki\Downloads\ChatGPT Image May 30, 2026, 12_45_47 AM.png")
INSTALL_DEFAULT = Path(r"C:\Users\hooki\df2\juce-shell\assets\ui\df2_panel_shadow.png")

# Source-space well bounds used by PluginEditor.cpp.
WELLS = (
    (127.0, 694.0, 423.0, 101.0),
    (127.0, 871.0, 423.0, 101.0),
)


def thumbwheel_rect(well: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x, y, w, h = well
    # PluginEditor draws a 149x40 runtime frame centered in the source-space well
    # after converting through the 360x560 editor coordinate system.
    wheel_w = 149.0 * (1024.0 / 360.0)
    wheel_h = 40.0 * (1591.0 / 560.0)
    wheel_x = x + (w - wheel_w) * 0.5
    wheel_y = y + (h - wheel_h) * 0.5
    return (
        round(wheel_x),
        round(wheel_y),
        round(wheel_x + wheel_w),
        round(wheel_y + wheel_h),
    )


def add_shadow(canvas: Image.Image, rect: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = rect
    w = x2 - x1
    bite_w = max(1, w - 28)
    bite = Image.new("RGBA", (bite_w + 34, 22), (0, 0, 0, 0))
    bite_mask = Image.new("L", bite.size, 0)
    bd = ImageDraw.Draw(bite_mask)
    bd.rounded_rectangle((17, 4, 17 + bite_w - 1, 10), radius=5, fill=92)
    bite_mask = bite_mask.filter(ImageFilter.GaussianBlur(2))
    bite.putalpha(bite_mask)
    canvas.alpha_composite(bite, (x1 + (w - bite_w) // 2 - 17, y2 - 4))

    falloff_w = max(1, w - 52)
    falloff_h = 24
    falloff = Image.new("RGBA", (falloff_w + 60, falloff_h + 30), (0, 0, 0, 0))
    falloff_mask = Image.new("L", falloff.size, 0)
    fd = ImageDraw.Draw(falloff_mask)

    # Hand-painted half oval. Its top sits under the wheel, then dies quickly
    # so the faceplate keeps the X3 "resting on metal" read.
    fd.ellipse((30, -10, 30 + falloff_w, -10 + falloff_h), fill=118)
    fd.rectangle((0, 0, falloff.size[0], 2), fill=0)

    # Soften the sides more than the contact edge.
    falloff_mask = falloff_mask.filter(ImageFilter.GaussianBlur(4))
    falloff.putalpha(falloff_mask)
    canvas.alpha_composite(falloff, (x1 + (w - falloff_w) // 2 - 30, y2 - 1))


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
