#!/usr/bin/env python3
"""Recolor the X3 128-frame thumbwheel strip.

Colour remapping only — no geometry changes, no procedural drawing.

Changes:
  - Cyan glow  -> saturated coral-peach (pale peach hot core)
  - Neutral grey roller -> warm off-white ABS plastic
  - Everything else  -> byte-for-byte identical

Usage:
  python recolor_x3_thumbwheel.py --source <bmp> --out <native.png> [--plugin-out <plugin.png>]
"""

import argparse
import sys
from pathlib import Path

from PIL import Image

# ── geometry constants ──────────────────────────────────────────────────────

FRAMES = 128
FRAME_W = 85
FRAME_H = 11
NATIVE_W = FRAMES * FRAME_W           # 10880
NATIVE_H = FRAME_H                    # 11
PLUGIN_FRAME_W = 129
PLUGIN_FRAME_H = 28
PLUGIN_W = FRAMES * PLUGIN_FRAME_W    # 16512
PLUGIN_H = PLUGIN_FRAME_H             # 28

# Luma threshold below which a pixel is treated as slot/shadow/clearance and
# is never warmed, even if it passes the neutral-grey chroma test.
DARK_THRESHOLD = 38.0


# ── pixel classification ────────────────────────────────────────────────────

def luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def is_source_cyan(r, g, b):
    """True for the original cyan LED glow pixels."""
    return g > r + 18 and b > r + 18 and (g > 55 or b > 55)


def is_neutral_grey(r, g, b):
    """True for the grey roller body (low chroma, not cyan)."""
    return max(r, g, b) - min(r, g, b) <= 16


# ── colour remapping ─────────────────────────────────────────────────────────

def _clamp(v):
    return max(0, min(255, int(v)))


def recolor_cyan(r, g, b):
    """Map cyan glow -> ultraviolet: deep violet with pale lavender-white hot core.

    Preserves the source glow mask and local brightness structure.
    """
    y = luma(r, g, b)
    chroma = max(r, g, b) - min(r, g, b)
    strength = min(chroma / 120.0, 1.0)
    # Hot core (high y, low chroma) -> pale lavender-white.
    # Saturated edge (high chroma) -> deep violet.
    return (
        _clamp(y * 0.72 + 72.0 * strength),
        _clamp(y * 0.52 + 12.0 * strength),
        _clamp(y * 1.05 + 148.0 * strength),
    )


def recolor_neutral(r, g, b):
    """Map neutral grey -> full plastic ABS bone white (old moulded sampler).

    Dark pixels (slot, shadow, clearance, bitmap dirt) pass through byte-for-byte.
    Material pixels are pushed hard toward bright warm white, not left grey.
    """
    y = luma(r, g, b)
    if y <= DARK_THRESHOLD:
        return (r, g, b)
    # Normalise material range and apply mild gamma lift toward white.
    t = min((y - DARK_THRESHOLD) / (220.0 - DARK_THRESHOLD), 1.0)
    lifted = DARK_THRESHOLD + (220.0 - DARK_THRESHOLD) * (t ** 0.72)
    return (
        _clamp(lifted + 32.0 * t),
        _clamp(lifted + 20.0 * t),
        _clamp(lifted + 4.0 * t),
    )


# ── pixel remapping with audit tracking ──────────────────────────────────────

def remap_pixel(r, g, b, audit):
    if is_source_cyan(r, g, b):
        new = recolor_cyan(r, g, b)
        if new != (r, g, b):
            audit["cyan_changed"] += 1
        else:
            audit["cyan_unchanged"] += 1
        return new
    elif is_neutral_grey(r, g, b):
        y = luma(r, g, b)
        if y <= DARK_THRESHOLD:
            audit["dark_preserved"] += 1
            return (r, g, b)
        new = recolor_neutral(r, g, b)
        if new != (r, g, b):
            audit["grey_changed"] += 1
        else:
            audit["grey_unchanged"] += 1
        return new
    else:
        audit["chromatic_preserved"] += 1
        return (r, g, b)


# ── frame export ─────────────────────────────────────────────────────────────

def export_frames(strip, out_path, frame_w, frame_h):
    frames_dir = out_path.parent / f"{out_path.stem}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for i in range(FRAMES):
        x0 = i * frame_w
        strip.crop((x0, 0, x0 + frame_w, frame_h)).save(frames_dir / f"frame_{i:03d}.png")


# ── plugin-size scaling ───────────────────────────────────────────────────────

def scale_to_plugin(native_strip):
    """Scale each 85x11 frame independently to 129x28 via nearest-neighbour."""
    plugin_strip = Image.new("RGB", (PLUGIN_W, PLUGIN_H))
    for i in range(FRAMES):
        x0 = i * FRAME_W
        frame = native_strip.crop((x0, 0, x0 + FRAME_W, FRAME_H))
        scaled = frame.resize((PLUGIN_FRAME_W, PLUGIN_FRAME_H), Image.Resampling.NEAREST)
        plugin_strip.paste(scaled, (i * PLUGIN_FRAME_W, 0))
    return plugin_strip


# ── validation ────────────────────────────────────────────────────────────────

def validate(native_strip, plugin_strip, audit):
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"  FAIL  {label}: got {got}, want {want}")
        else:
            print(f"  OK    {label}: {got}")

    print("\n-- dimension checks --")
    check("native strip width",   native_strip.width,  NATIVE_W)
    check("native strip height",  native_strip.height, NATIVE_H)
    check("native frame count",   NATIVE_W // FRAME_W, FRAMES)
    check("native frame width",   FRAME_W,             85)
    check("native frame height",  FRAME_H,             11)

    if plugin_strip is not None:
        check("plugin strip width",   plugin_strip.width,  PLUGIN_W)
        check("plugin strip height",  plugin_strip.height, PLUGIN_H)
        check("plugin frame count",   PLUGIN_W // PLUGIN_FRAME_W, FRAMES)
        check("plugin frame width",   PLUGIN_FRAME_W,      129)
        check("plugin frame height",  PLUGIN_FRAME_H,      28)

    print("\n-- pixel audit --")
    print(f"  cyan changed:        {audit['cyan_changed']}")
    print(f"  cyan unchanged:      {audit['cyan_unchanged']}")
    print(f"  grey changed:        {audit['grey_changed']}")
    print(f"  grey unchanged:      {audit['grey_unchanged']}")
    print(f"  dark preserved:      {audit['dark_preserved']}")
    print(f"  chromatic preserved: {audit['chromatic_preserved']}")

    if failures:
        for msg in failures:
            print(msg, file=sys.stderr)
        sys.exit(1)
    print("\nAll checks passed.")


# ── main ──────────────────────────────────────────────────────────────────────

def render(source_path, out_path, plugin_out_path):
    source = Image.open(source_path).convert("RGB")
    if source.height != FRAME_H or source.width < NATIVE_W:
        raise ValueError(
            f"source too small: need at least {NATIVE_W}x{FRAME_H}, "
            f"got {source.width}x{source.height}"
        )

    source = source.crop((0, 0, NATIVE_W, FRAME_H))
    src_px = source.load()

    native = Image.new("RGB", (NATIVE_W, NATIVE_H))
    out_px = native.load()

    audit = dict(
        cyan_changed=0, cyan_unchanged=0,
        grey_changed=0, grey_unchanged=0,
        dark_preserved=0, chromatic_preserved=0,
    )

    for y in range(FRAME_H):
        for x in range(NATIVE_W):
            out_px[x, y] = remap_pixel(*src_px[x, y], audit)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    native.save(out_path)
    export_frames(native, out_path, FRAME_W, FRAME_H)
    print(f"Native strip -> {out_path}")

    plugin_strip = None
    if plugin_out_path is not None:
        plugin_strip = scale_to_plugin(native)
        plugin_out_path.parent.mkdir(parents=True, exist_ok=True)
        plugin_strip.save(plugin_out_path)
        export_frames(plugin_strip, plugin_out_path, PLUGIN_FRAME_W, PLUGIN_FRAME_H)
        print(f"Plugin strip -> {plugin_out_path}")

    validate(native, plugin_strip, audit)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source",     required=True,  help="Source BMP strip path")
    p.add_argument("--out",        required=True,  help="Native 10880x11 output PNG")
    p.add_argument("--plugin-out", dest="plugin_out", help="Plugin 16512x28 output PNG (optional)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    render(
        Path(args.source),
        Path(args.out),
        Path(args.plugin_out) if args.plugin_out else None,
    )
