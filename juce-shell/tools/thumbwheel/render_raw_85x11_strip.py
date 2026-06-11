#!/usr/bin/env python3
"""Render the active 129-frame TRENCH thumbwheel strips.

Fixed asset contract:
- raw frame: 85x11, strip: 10965x11
- runtime frame: 149x36, strip: 19221x36
- frame 0 == frame 128, with no cyan endpoint glow

Clean-room renderer.  The material/body layer is fixed across all frames:
continuous dirty bone ABS, shallow carved grooves, dark aperture, end rolloff,
and contact depth.  Motion comes only from a recessed cyan emitter moving behind
the aperture mask.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageFilter


FRAMES = 129
RAW_W = 85
RAW_H = 11
RUNTIME_W = 149
RUNTIME_H = 36
PERIOD = float(RAW_W)
RUNTIME_PERIOD = float(RUNTIME_W)


def clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def lerp(a: float, b: float, t: float) -> float:
    return a * (1.0 - t) + b * t


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge0 == edge1:
        return 1.0 if x >= edge1 else 0.0
    t = clamp01((x - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def hash01(a: int, b: int = 0, c: int = 0, seed: int = 4331) -> float:
    n = (a * 73856093) ^ (b * 19349663) ^ (c * 83492791) ^ seed
    n = (n ^ (n >> 13)) * 1274126177
    return ((n ^ (n >> 16)) & 65535) / 65535.0


def loop_noise(s: float, cells: int, seed: int) -> float:
    """Periodic value noise over the 85 px wheel face."""
    pos = (s % PERIOD) / PERIOD * cells
    i0 = math.floor(pos)
    i1 = (i0 + 1) % cells
    t = smoothstep(0.0, 1.0, pos - i0)
    return lerp(hash01(i0, seed), hash01(i1, seed), t)


def fbm(s: float, seed: int) -> float:
    return (
        0.52 * loop_noise(s, 7, seed)
        + 0.28 * loop_noise(s + 11.3, 17, seed + 13)
        + 0.15 * loop_noise(s + 3.7, 29, seed + 29)
        + 0.05 * loop_noise(s + 19.1, 43, seed + 41)
    )


def sparse_nick(s: float, y: int, seed: int) -> float:
    n = loop_noise(s + y * 5.7, 23, seed)
    return smoothstep(0.72, 0.94, n)


def wrap_distance(a: float, b: float) -> float:
    d = abs((a - b) % PERIOD)
    return min(d, PERIOD - d)


def runtime_wrap_distance(a: float, b: float) -> float:
    d = abs((a - b) % RUNTIME_PERIOD)
    return min(d, RUNTIME_PERIOD - d)


def fin_pattern(y: int) -> tuple[tuple[float, ...], float, float] | None:
    if y not in (1, 2, 3, 7, 8):
        return None

    top_centers = (4.8, 11.7, 19.4, 28.2, 36.9, 45.8, 55.0, 64.3, 73.1, 81.0)
    bottom_centers = (7.1, 15.3, 24.0, 32.6, 41.4, 50.7, 59.8, 68.5, 77.4, 83.4)
    centers = top_centers if y in (1, 2, 3) else bottom_centers
    row_shift = {1: -0.55, 2: 0.0, 3: 0.42, 7: -0.35, 8: 0.38}[y]
    row_weight = {1: 0.22, 2: 0.60, 3: 0.38, 7: 0.42, 8: 0.24}[y]
    return centers, row_shift, row_weight


def groove_depth(s: float, y: int) -> float:
    """Fixed molded fin rows. No full-height stitching through the middle."""
    pattern = fin_pattern(y)
    if pattern is None:
        return 0.0

    centers, row_shift, row_weight = pattern
    depth = 0.0

    for i, center in enumerate(centers):
        width = 1.12 + 0.34 * hash01(i, y, seed=6101)
        local = math.exp(-((wrap_distance(s, center + row_shift) / width) ** 2))
        depth = max(depth, local * (0.62 + 0.24 * hash01(i, seed=6113)))

    return clamp01(depth * row_weight)


def bead_lobe(s: float, y: int) -> float:
    """Rounded top/bottom fin beads, separated from the open middle."""
    pattern = fin_pattern(y)
    if pattern is None:
        return 0.0

    centers, row_shift, row_weight = pattern
    depth = 0.0

    for i, center in enumerate(centers):
        width = 1.46 + 0.24 * hash01(i, y, seed=6203)
        local = math.exp(-((wrap_distance(s, center + row_shift) / width) ** 2))
        depth = max(depth, local * (0.76 + 0.20 * hash01(i, seed=6217)))

    row_gain = {1: 0.28, 2: 1.00, 3: 0.36, 7: 0.72, 8: 0.34}.get(y, 0.0)
    return clamp01(depth * row_gain * (0.74 + 0.26 * row_weight))


def material_rgb(v: float) -> tuple[int, int, int]:
    deep = (5.0, 5.0, 4.0)
    low = (35.0, 32.0, 27.0)
    mid = (132.0, 125.0, 103.0)
    high = (224.0, 216.0, 188.0)

    if v < 52.0:
        t = smoothstep(0.0, 52.0, v)
        return (
            clamp(lerp(deep[0], low[0], t)),
            clamp(lerp(deep[1], low[1], t)),
            clamp(lerp(deep[2], low[2], t)),
        )
    if v < 132.0:
        t = smoothstep(52.0, 132.0, v)
        return (
            clamp(lerp(low[0], mid[0], t)),
            clamp(lerp(low[1], mid[1], t)),
            clamp(lerp(low[2], mid[2], t)),
        )
    t = smoothstep(132.0, 232.0, v)
    return (
        clamp(lerp(mid[0], high[0], t)),
        clamp(lerp(mid[1], high[1], t)),
        clamp(lerp(mid[2], high[2], t)),
    )


def end_rolloff(fx: float) -> float:
    edge = min(fx, RAW_W - 1.0 - fx)
    return 0.50 + 0.50 * smoothstep(0.0, 7.0, edge)


def surface_luma(x: int, y: int, phase: float) -> tuple[float, float]:
    fx = float(x) + 0.5
    s = (fx + phase) % PERIOD

    broad = fbm(s, 1001)
    fine = fbm(s * 1.7 + y * 6.1, 2003)
    nick = sparse_nick(s, y, 3001)
    groove = groove_depth(s, y)
    bead = bead_lobe(s, y)
    scratch = hash01(x, y, int(phase * 10.0), 4001) - 0.5

    worn_flash = smoothstep(0.58, 0.86, broad) * (0.55 + 0.45 * fine)

    if y == 0:
        v = 28.0 + 28.0 * broad + 10.0 * worn_flash - 16.0 * groove
        alpha = 102.0
    elif y == 1:
        v = 90.0 + 34.0 * broad + 24.0 * worn_flash + 34.0 * bead - 28.0 * groove - 10.0 * nick
        alpha = 218.0
    elif y == 2:
        v = 116.0 + 36.0 * broad + 36.0 * worn_flash + 78.0 * bead - 32.0 * groove - 12.0 * nick
        alpha = 252.0
    elif y == 3:
        under_shadow = smoothstep(0.38, 0.82, fine)
        v = 82.0 + 28.0 * broad + 22.0 * worn_flash + 24.0 * bead - 42.0 * groove - 30.0 * under_shadow
        alpha = 248.0
    elif y == 4:
        v = 54.0 + 20.0 * broad + 8.0 * worn_flash - 42.0 * groove - 13.0 * nick
        alpha = 246.0
    elif y == 5:
        v = 35.0 + 15.0 * broad - 38.0 * groove - 13.0 * sparse_nick(s + 9.0, y, 3017)
        alpha = 242.0
    elif y == 6:
        v = 48.0 + 18.0 * broad + 5.0 * worn_flash - 40.0 * groove - 11.0 * sparse_nick(s + 17.0, y, 3029)
        alpha = 236.0
    elif y == 7:
        lower = fbm(s + 22.0, 5003)
        v = 74.0 + 22.0 * lower + 12.0 * broad + 52.0 * bead - 32.0 * groove - 14.0 * sparse_nick(s + 31.0, y, 5101)
        alpha = 206.0
    elif y == 8:
        lower = fbm(s + 29.0, 5011)
        v = 42.0 + 15.0 * lower + 6.0 * broad + 28.0 * bead - 18.0 * groove - 10.0 * sparse_nick(s + 43.0, y, 5113)
        alpha = 142.0
    elif y == 9:
        v = 18.0 + 8.0 * fbm(s + 36.0, 5021) - 7.0 * groove
        alpha = 70.0
    else:
        v = 5.0 + 3.0 * broad
        alpha = 34.0

    v *= end_rolloff(fx)
    v += scratch * 7.0
    return v, alpha


def render_frame(frame: int) -> Image.Image:
    img = Image.new("RGBA", (RAW_W, RAW_H), (0, 0, 0, 0))
    px = img.load()

    body_phase = 0.0
    has_cyan = frame not in (0, FRAMES - 1)
    # The X3-style read is a full travel cycle through the aperture, not a
    # bead clamped inside the visible slot. Frames 1..127 move from offscreen
    # left to offscreen right; 0 and 128 stay identical and unlit.
    cyan_tip = -15.0 + ((frame - 1) / float(FRAMES - 3)) * (RAW_W + 30.0) if has_cyan else -100.0

    for y in range(RAW_H):
        for x in range(RAW_W):
            fx = float(x) + 0.5
            s = (fx + body_phase) % PERIOD
            v, row_alpha = surface_luma(x, y, body_phase)
            r, g, b = material_rgb(v)

            if has_cyan and 3 <= y <= 7:
                dx = fx - cyan_tip
                if -28.0 <= dx <= 28.0:
                    halo = math.exp(-((dx / 9.7) ** 2))
                    tail_distance = cyan_tip - fx
                    tail = smoothstep(0.0, 7.0, tail_distance) * (max(0.0, 1.0 - tail_distance / 25.0) ** 1.35)
                    hot = math.exp(-((dx / 1.75) ** 2))
                    lead = math.exp(-(((dx + 1.8) / 3.0) ** 2))
                    row_weight = {3: 0.12, 4: 0.56, 5: 0.76, 6: 0.62, 7: 0.18}[y]
                    aperture_mask = 0.88 - 0.58 * groove_depth(s, y)
                    broken = 0.82 + 0.18 * (1.0 - sparse_nick(s + 12.0, y, 7001))
                    amount = clamp01((0.58 * halo + 0.24 * tail + 0.58 * hot + 0.16 * lead)
                                     * row_weight * aperture_mask * broken)
                    if amount > 0.0:
                        r = clamp(r * (1.0 - 0.82 * amount) + 4.0 * amount)
                        g = clamp(g + 202.0 * amount)
                        b = clamp(b + 190.0 * amount)

            if has_cyan and y in (1, 2, 3, 7, 8):
                bead = bead_lobe(s, y)
                if bead > 0.03:
                    dx = fx - cyan_tip
                    if -29.0 <= dx <= 29.0:
                        glow = math.exp(-((dx / 8.2) ** 2))
                        hot = math.exp(-((dx / 2.35) ** 2))
                        trail_distance = cyan_tip - fx
                        trail = smoothstep(0.0, 6.0, trail_distance) * (max(0.0, 1.0 - trail_distance / 22.0) ** 1.42)
                        row_weight = {1: 0.58, 2: 1.35, 3: 0.72, 7: 1.02, 8: 0.48}[y]
                        amount = clamp01((0.92 * glow + 0.68 * hot + 0.34 * trail) * bead * row_weight * 1.28)
                        if amount > 0.0:
                            r = clamp(r * (1.0 - 0.76 * amount) + 10.0 * amount)
                            g = clamp(g + 218.0 * amount)
                            b = clamp(b + 208.0 * amount)

            edge_x = min(fx, RAW_W - fx)
            alpha_scale = max(0.22, smoothstep(0.0, 2.5, edge_x))
            px[x, y] = (r, g, b, clamp(row_alpha * alpha_scale))

    return img


def render_strip(frame_w: int, frame_h: int) -> Image.Image:
    base = render_frame(0)
    strip = Image.new("RGBA", (FRAMES * frame_w, frame_h), (0, 0, 0, 0))
    for i in range(FRAMES):
        frame = base.copy() if i in (0, FRAMES - 1) else render_frame(i)
        if (frame_w, frame_h) != (RAW_W, RAW_H):
            frame = frame.resize((frame_w, frame_h), Image.Resampling.NEAREST)
        strip.alpha_composite(frame, (i * frame_w, 0))
    return strip


def runtime_bead_lobe(x: float, y: float, row: str) -> float:
    if row == "top":
        centers = (16.0, 25.0, 34.0, 43.0, 52.0, 61.0, 70.0, 79.0, 88.0, 97.0, 106.0, 115.0, 124.0, 133.0)
        row_y = 8.8
    else:
        centers = (18.5, 28.0, 37.5, 47.0, 56.5, 66.0, 75.5, 85.0, 94.5, 104.0, 113.5, 123.0, 132.5)
        row_y = 25.6

    lobe = 0.0
    for i, center in enumerate(centers):
        sx = 1.35 + 0.18 * hash01(i, seed=7301)
        sy = 3.45 if row == "top" else 3.30
        local = math.exp(-(((x - center) / sx) ** 2 + ((y - row_y) / sy) ** 2))
        lobe = max(lobe, local * (0.78 + 0.18 * hash01(i, seed=7309)))

    return clamp01(lobe)


def runtime_groove_depth(x: float, y: float) -> float:
    """Short row-local fin edge shadows, never full-height vertical teeth."""
    centers = (9.0, 16.0, 23.5, 31.0, 39.2, 47.6, 56.1, 64.8,
               73.0, 81.5, 90.1, 98.8, 107.0, 115.6, 124.1, 132.2, 140.0)
    depth = 0.0
    for i, center in enumerate(centers):
        width = 0.62 + 0.24 * hash01(i, seed=9101)
        wobble = (hash01(i, int(y), seed=9113) - 0.5) * 0.42
        local = math.exp(-((runtime_wrap_distance(x, center + wobble) / width) ** 2))
        depth = max(depth, local * (0.62 + 0.20 * hash01(i, seed=9127)))

    top_reach = smoothstep(5.2, 7.3, y) * (1.0 - smoothstep(11.2, 14.0, y))
    bottom_reach = smoothstep(21.3, 23.0, y) * (1.0 - smoothstep(27.7, 30.1, y))
    return clamp01(depth * max(top_reach, bottom_reach))


def runtime_fin_bead(x: float, y: float, row: str) -> float:
    """Raised tactile fins/beads like the 17 px reference: short and staggered."""
    if row == "top":
        centers = (7.0, 15.5, 25.0, 36.0, 47.5, 59.0, 70.0,
                   82.5, 94.0, 106.0, 118.5, 131.0, 141.5)
        ys = (6.8, 8.3, 10.0)
        row_gain = 1.0
    else:
        centers = (10.2, 20.8, 32.0, 43.2, 55.0, 67.0, 78.6,
                   90.5, 102.4, 114.6, 126.0, 137.6)
        ys = (22.7, 24.7, 26.4)
        row_gain = 0.72

    bead = 0.0
    for i, center in enumerate(centers):
        cx = center + (hash01(i, seed=9201) - 0.5) * 1.4
        sx = 2.45 + 2.25 * hash01(i, seed=9209)
        for j, cy in enumerate(ys):
            if hash01(i, j, seed=9217) < (0.20 if row == "top" else 0.30):
                continue
            sy = 1.05 + 0.38 * hash01(i, j, seed=9221)
            local = math.exp(-((runtime_wrap_distance(x, cx) / sx) ** 4 + ((y - cy) / sy) ** 4))
            chip = 0.64 + 0.36 * hash01(int((x % RUNTIME_PERIOD) // 2), i, j, seed=9233)
            bead = max(bead, local * chip * row_gain * (0.50 + 0.44 * hash01(i, j, seed=9227)))

    return clamp01(bead)


def runtime_center_fragment(x: float, y: float) -> float:
    centers = (6.0, 13.4, 20.2, 28.0, 35.1, 43.0, 51.3, 59.0, 67.5,
               75.2, 83.0, 91.8, 99.4, 107.6, 116.0, 123.5, 132.4, 140.1)
    frag = 0.0
    for i, center in enumerate(centers):
        width = 0.75 + 0.65 * hash01(i, seed=9301)
        x_part = math.exp(-((runtime_wrap_distance(x, center) / width) ** 2))
        y_center = 15.0 + 5.4 * hash01(i, seed=9307)
        y_part = math.exp(-(((y - y_center) / (1.2 + 1.8 * hash01(i, seed=9311))) ** 2))
        frag = max(frag, x_part * y_part * (0.52 + 0.42 * hash01(i, seed=9319)))

    center_reach = smoothstep(11.4, 13.4, y) * (1.0 - smoothstep(21.0, 23.6, y))
    return clamp01(frag * center_reach)


def runtime_rounded_rect_mask(x: float, y: float, left: float, top: float, right: float, bottom: float, radius: float, feather: float) -> float:
    cx = (left + right) * 0.5
    cy = (top + bottom) * 0.5
    hx = (right - left) * 0.5 - radius
    hy = (bottom - top) * 0.5 - radius
    dx = abs(x - cx) - hx
    dy = abs(y - cy) - hy
    outside_x = max(dx, 0.0)
    outside_y = max(dy, 0.0)
    outside = math.hypot(outside_x, outside_y)
    inside = min(max(dx, dy), 0.0)
    signed = outside + inside - radius
    return 1.0 - smoothstep(-feather, feather, signed)


def render_runtime_frame(frame: int) -> Image.Image:
    img = Image.new("RGBA", (RUNTIME_W, RUNTIME_H), (0, 0, 0, 0))
    px = img.load()

    has_cyan = frame not in (0, FRAMES - 1)
    cyan_tip = -26.0 + ((frame - 1) / float(FRAMES - 3)) * (RUNTIME_W + 52.0) if has_cyan else -1000.0

    for y in range(RUNTIME_H):
        for x in range(RUNTIME_W):
            fx = float(x) + 0.5
            fy = float(y) + 0.5

            edge_x = min(fx, RUNTIME_W - fx)
            end = smoothstep(0.0, 10.0, edge_x)
            top_field = smoothstep(3.8, 5.6, fy) * (1.0 - smoothstep(12.2, 14.2, fy))
            bottom_field = smoothstep(21.0, 23.0, fy) * (1.0 - smoothstep(29.4, 31.4, fy))
            center_backing = smoothstep(11.0, 14.5, fy) * (1.0 - smoothstep(20.6, 24.0, fy))
            end_mass = (1.0 - smoothstep(9.0, 18.0, edge_x)) * smoothstep(4.0, 7.0, fy) * (1.0 - smoothstep(28.0, 31.5, fy))
            outer = clamp01((max(top_field, bottom_field) + 0.24 * center_backing + 0.50 * end_mass) * end)
            if outer <= 0.01:
                continue

            slot = runtime_rounded_rect_mask(fx, fy, 12.0, 13.0, 136.0, 21.8, 2.2, 0.9)
            top_bead = runtime_bead_lobe(fx, fy, "top")
            bottom_bead = runtime_bead_lobe(fx, fy, "bottom")
            bead = max(top_bead, bottom_bead)

            n1 = fbm(fx * RAW_W / RUNTIME_W, 8101)
            n2 = fbm(fx * 0.41 + fy * 0.22, 8201)
            dirt = hash01(x // 2, y // 2, seed=8301) - 0.5

            top_light = math.exp(-(((fy - 7.4) / 3.7) ** 2))
            lower_light = math.exp(-(((fy - 25.0) / 3.5) ** 2))
            center_dust = math.exp(-(((fy - 17.4) / 7.0) ** 2))
            side_burn = 0.66 + 0.34 * smoothstep(0.0, 15.0, edge_x)

            # A shallow flat thumbwheel surface, not a tube. The molded fin
            # fields are top/bottom relief around a recessed central aperture.
            luma = 58.0 + 64.0 * outer + 20.0 * top_light + 9.0 * lower_light + 6.0 * center_dust
            luma += 18.0 * bead * (0.38 + 0.62 * max(top_light, lower_light))
            luma += 12.0 * n1 + 7.0 * n2 + 9.0 * dirt
            luma *= side_burn
            r, g, b = material_rgb(luma)

            if slot > 0.0:
                slot_dark = clamp01(slot * (0.84 + 0.16 * smoothstep(0.0, 7.0, min(fx - 16.0, 134.0 - fx))))
                r = clamp(r * (1.0 - 0.92 * slot_dark) + 1.0 * slot_dark)
                g = clamp(g * (1.0 - 0.88 * slot_dark) + 5.0 * slot_dark)
                b = clamp(b * (1.0 - 0.82 * slot_dark) + 5.0 * slot_dark)

            if has_cyan:
                dx = fx - cyan_tip
                if -48.0 <= dx <= 48.0:
                    halo = math.exp(-((dx / 16.2) ** 2))
                    hot = math.exp(-((dx / 4.0) ** 2))
                    tail_distance = cyan_tip - fx
                    tail = smoothstep(0.0, 11.0, tail_distance) * (max(0.0, 1.0 - tail_distance / 39.0) ** 1.35)
                    center_row = slot * (0.70 + 0.30 * math.exp(-(((fy - 17.5) / 3.2) ** 2)))
                    center_amount = clamp01((0.82 * halo + 0.48 * hot + 0.28 * tail) * center_row)
                    bead_amount = clamp01((0.48 * halo + 0.46 * hot + 0.16 * tail) * bead)
                    amount = clamp01(center_amount + bead_amount)
                    if amount > 0.0:
                        r = clamp(r * (1.0 - 0.72 * amount) + 4.0 * amount)
                        g = clamp(g + 202.0 * amount)
                        b = clamp(b + 194.0 * amount)

            alpha = clamp((34.0 + 218.0 * outer) * (1.0 - 0.18 * slot))
            px[x, y] = (r, g, b, alpha)

    return img.filter(ImageFilter.GaussianBlur(radius=0.14))


def build_runtime_base_and_masks() -> tuple[Image.Image, list[list[float]], list[list[float]]]:
    base = Image.new("RGBA", (RUNTIME_W, RUNTIME_H), (0, 0, 0, 0))
    px = base.load()
    slot_mask: list[list[float]] = [[0.0 for _ in range(RUNTIME_W)] for _ in range(RUNTIME_H)]
    ridge_mask: list[list[float]] = [[0.0 for _ in range(RUNTIME_W)] for _ in range(RUNTIME_H)]

    for y in range(RUNTIME_H):
        for x in range(RUNTIME_W):
            fx = float(x) + 0.5
            fy = float(y) + 0.5
            edge_x = min(fx, RUNTIME_W - fx)
            end = smoothstep(0.0, 8.0, edge_x)
            end_burn = 0.30 + 0.70 * smoothstep(4.0, 24.0, edge_x)

            face = smoothstep(4.2, 6.2, fy) * (1.0 - smoothstep(30.3, 32.5, fy))
            top_land = smoothstep(5.0, 6.4, fy) * (1.0 - smoothstep(13.2, 15.8, fy))
            bottom_land = smoothstep(20.0, 21.7, fy) * (1.0 - smoothstep(29.4, 31.6, fy))
            center_web = smoothstep(10.4, 12.8, fy) * (1.0 - smoothstep(22.4, 25.2, fy))
            underside = smoothstep(26.0, 29.6, fy) * (1.0 - smoothstep(31.1, 33.0, fy))

            # Flat side-lying disc face: long molded lands with dark end rolloff.
            # Avoid a lens/saucer outline; depth comes from carved grooves and
            # contact shadow, not from pinching the silhouette into a capsule.
            body = clamp01((0.44 * face + 0.28 * max(top_land, bottom_land) + 0.30 * center_web + 0.12 * underside) * end)
            if body <= 0.01:
                continue

            center_gap = smoothstep(10.8, 13.3, fy) * (1.0 - smoothstep(22.0, 24.7, fy))
            ragged = 0.76 + 0.24 * fbm(fx * 0.74 + fy * 2.1, 9141)
            slot = runtime_rounded_rect_mask(fx, fy, 7.5, 13.0, 140.5, 22.6, 0.8, 0.85) * center_gap * ragged
            slot *= smoothstep(8.0, 22.0, edge_x)
            slot_mask[y][x] = slot
            ridge_mask[y][x] = body

            n1 = fbm(fx * RAW_W / RUNTIME_W, 8101)
            n2 = fbm(fx * 0.41 + fy * 0.22, 8201)
            dirt = hash01(x // 2, y // 2, seed=8301) - 0.5
            top_light = math.exp(-(((fy - 8.2) / 4.6) ** 2))
            lower_light = math.exp(-(((fy - 25.0) / 4.7) ** 2))
            center_dust = math.exp(-(((fy - 17.4) / 7.0) ** 2))
            mid_shadow = math.exp(-(((fy - 17.2) / 4.2) ** 2))
            contact_dark = 1.0 - 0.34 * underside - 0.16 * smoothstep(28.0, 32.0, fy)
            luma = 16.0 + 32.0 * body + 5.0 * top_light + 3.0 * lower_light + 2.0 * center_dust
            luma -= 54.0 * mid_shadow * (0.42 + 0.58 * slot)
            luma += 12.0 * n1 + 7.0 * n2 + 9.0 * dirt
            luma *= end_burn * contact_dark
            r, g, b = material_rgb(luma)

            if slot > 0.0:
                slot_dark = clamp01(slot * (0.92 + 0.08 * smoothstep(0.0, 7.0, min(fx - 16.0, 134.0 - fx))))
                r = clamp(r * (1.0 - 0.92 * slot_dark) + 1.0 * slot_dark)
                g = clamp(g * (1.0 - 0.88 * slot_dark) + 5.0 * slot_dark)
                b = clamp(b * (1.0 - 0.82 * slot_dark) + 5.0 * slot_dark)

            alpha = clamp((30.0 + 222.0 * body) * (1.0 - 0.16 * slot) * (0.50 + 0.50 * end))
            px[x, y] = (r, g, b, alpha)

    return base.filter(ImageFilter.GaussianBlur(radius=0.14)), slot_mask, ridge_mask


def render_runtime_frame_fast(frame: int,
                              base: Image.Image,
                              slot_mask: list[list[float]],
                              ridge_mask: list[list[float]]) -> Image.Image:
    img = base.copy()
    px = img.load()
    phase = (float(frame) / float(FRAMES - 1)) * RUNTIME_PERIOD
    has_cyan = frame not in (0, FRAMES - 1)
    cyan_center = 92.0

    for y in range(RUNTIME_H):
        fy = float(y) + 0.5
        for x in range(RUNTIME_W):
            visible = ridge_mask[y][x]
            if visible <= 0.01:
                continue

            fx = float(x) + 0.5
            moving_x = fx + phase
            edge_x = min(fx, RUNTIME_W - fx)
            top_light = math.exp(-(((fy - 8.2) / 4.6) ** 2))
            lower_light = math.exp(-(((fy - 25.0) / 4.7) ** 2))
            fixed_light = max(top_light, lower_light)
            edge_hold = smoothstep(8.0, 24.0, edge_x)

            fin = max(runtime_fin_bead(moving_x, fy, "top"), runtime_fin_bead(moving_x, fy, "bottom")) * edge_hold
            groove = runtime_groove_depth(moving_x - 0.5, fy) * edge_hold
            center_frag = runtime_center_fragment(moving_x, fy) * edge_hold
            if fin > 0.01 or groove > 0.01 or center_frag > 0.01:
                r, g, b, a = px[x, y]
                dark = clamp01(0.54 * groove + 0.82 * center_frag)
                if dark > 0.0:
                    r = clamp(r * (1.0 - 0.72 * dark))
                    g = clamp(g * (1.0 - 0.72 * dark))
                    b = clamp(b * (1.0 - 0.68 * dark))

                bead_amount = clamp01(fin * (0.66 + 0.34 * fixed_light))
                if bead_amount > 0.0:
                    target = material_rgb(88.0 + 58.0 * fixed_light + 22.0 * hash01(int((moving_x % RUNTIME_PERIOD) // 3), int(fy), seed=9401))
                    blend = 0.72 * bead_amount
                    r = clamp(lerp(r, target[0], blend))
                    g = clamp(lerp(g, target[1], blend))
                    b = clamp(lerp(b, target[2], blend))

                px[x, y] = (r, g, b, a)

            slot = slot_mask[y][x]
            if slot <= 0.0:
                continue

            if not has_cyan:
                continue

            dx = fx - cyan_center
            if dx < -32.0 or dx > 26.0:
                continue

            halo = math.exp(-((dx / 13.8) ** 2))
            hot = math.exp(-((dx / 4.2) ** 2))
            tail = smoothstep(0.0, 10.0, -dx) * (max(0.0, 1.0 - (-dx) / 31.0) ** 1.35)
            slot_row = slot * (0.70 + 0.30 * math.exp(-(((fy - 17.5) / 3.2) ** 2)))
            dynamic_occluder = clamp01(0.46 * runtime_groove_depth(moving_x, fy) + 0.72 * runtime_center_fragment(moving_x, fy))
            center_amount = (0.74 * halo + 0.44 * hot + 0.18 * tail) * slot_row
            amount = clamp01(center_amount * (1.0 - 0.70 * dynamic_occluder))
            if amount <= 0.0:
                continue

            r, g, b, a = px[x, y]
            px[x, y] = (
                clamp(r * (1.0 - 0.72 * amount) + 4.0 * amount),
                clamp(g + 202.0 * amount),
                clamp(b + 194.0 * amount),
                a,
            )

    return img


def runtime_strip_from_raw(raw_strip: Image.Image) -> Image.Image:
    out = Image.new("RGBA", (FRAMES * RUNTIME_W, RUNTIME_H), (0, 0, 0, 0))
    for i in range(FRAMES):
        frame = render_reference_thumbwheel_frame(i)
        out.alpha_composite(frame, (i * RUNTIME_W, 0))
    return out


def reference_rect_alpha(x: float, y: float, left: float, top: float, right: float, bottom: float, feather: float = 1.0) -> float:
    inside_x = smoothstep(left - feather, left + feather, x) * (1.0 - smoothstep(right - feather, right + feather, x))
    inside_y = smoothstep(top - feather, top + feather, y) * (1.0 - smoothstep(bottom - feather, bottom + feather, y))
    return clamp01(inside_x * inside_y)


def reference_lip_mask(x: float, y: float, top: bool) -> float:
    cy = 10.0 if top else 25.0
    edge = min(x, RUNTIME_W - x)
    end = smoothstep(0.0, 11.0, edge)
    barrel = math.exp(-(((y - cy) / 5.2) ** 4))
    face = smoothstep(5.6 if top else 20.2, 7.0 if top else 21.5, y)
    face *= 1.0 - smoothstep(14.8 if top else 29.5, 16.3 if top else 31.2, y)
    return clamp01(max(barrel * 0.78, face * 0.58) * end)


def reference_opening_mask(x: float, y: float) -> float:
    centers = (17.5, 30.3, 43.2, 56.8, 70.9, 84.0, 97.7, 111.4, 125.2, 137.6)
    mask = 0.0
    for i, center in enumerate(centers):
        width = 1.85 + 0.80 * hash01(i, seed=12001)
        height = 3.4 + 1.15 * hash01(i, seed=12017)
        ymid = 18.0 + (hash01(i, seed=12031) - 0.5) * 1.2
        oval = math.exp(-(((x - center) / width) ** 4 + ((y - ymid) / height) ** 4))
        nick = 0.72 + 0.28 * fbm(x * 0.33 + i * 2.0, 12043)
        mask = max(mask, oval * nick)
    return clamp01(mask)


def reference_tooth_shadow(x: float, y: float, top: bool) -> tuple[float, float]:
    centers = (13.0, 25.5, 38.2, 51.0, 64.4, 78.1, 91.0, 104.5, 117.6, 131.0, 142.0)
    groove = 0.0
    glint = 0.0
    for i, center in enumerate(centers):
        cx = center + (hash01(i, seed=12101) - 0.5) * 2.8
        y_bend = (hash01(i, seed=12107) - 0.5) * 0.55
        reach_top = smoothstep(5.8, 7.4, y) * (1.0 - smoothstep(14.2, 16.2, y))
        reach_bottom = smoothstep(20.8, 22.4, y) * (1.0 - smoothstep(29.0, 31.4, y))
        reach = reach_top if top else reach_bottom
        local_x = x - cx - y_bend * (y - (9.0 if top else 25.5))
        vertical = math.exp(-((local_x / (0.78 + 0.42 * hash01(i, seed=12113))) ** 2))
        broken = 0.58 + 0.42 * fbm(x * 0.22 + y * 0.71 + i, 12123)
        groove = max(groove, vertical * reach * broken * (0.34 + 0.18 * hash01(i, seed=12119)))
        highlight = math.exp(-(((local_x - 1.0) / 0.85) ** 2))
        glint = max(glint, highlight * reach * broken * (0.20 + 0.12 * hash01(i, seed=12127)))
    return clamp01(groove), clamp01(glint)


def render_reference_thumbwheel_frame(frame: int) -> Image.Image:
    """Reference-shaped runtime frame: two molded roller lips and broken center mechanics."""
    img = Image.new("RGBA", (RUNTIME_W, RUNTIME_H), (0, 0, 0, 0))
    px = img.load()
    has_cyan = frame not in (0, FRAMES - 1)
    cyan_center = -18.0 + ((frame - 1) / float(FRAMES - 3)) * (RUNTIME_W + 36.0) if has_cyan else -1000.0

    for y in range(RUNTIME_H):
        fy = float(y) + 0.5
        for x in range(RUNTIME_W):
            fx = float(x) + 0.5
            edge = min(fx, RUNTIME_W - fx)
            end_falloff = smoothstep(0.0, 11.0, edge)
            side_burn = 0.38 + 0.62 * smoothstep(0.0, 24.0, edge)

            top_body = reference_lip_mask(fx, fy, True)
            bottom_body = reference_lip_mask(fx, fy, False)
            center_band = reference_rect_alpha(fx, fy, 11.0, 14.2, 138.0, 22.6, 1.2)
            center_rag = 0.66 + 0.28 * fbm(fx * 0.36 + fy * 1.2, 12503)
            middle_hardware = clamp01(center_band * center_rag * 0.88)
            opening = reference_opening_mask(fx, fy)
            body = clamp01(max(top_body, bottom_body) * end_falloff)
            hardware = clamp01(middle_hardware * end_falloff)

            if body <= 0.01 and hardware <= 0.01:
                continue

            n = fbm(fx * 0.47 + fy * 0.33, 12203)
            grit = hash01(x // 2, y // 2, seed=12217) - 0.5

            if body > hardware * 0.65:
                top_curve = math.exp(-(((fy - 8.0) / 5.3) ** 2))
                bottom_curve = math.exp(-(((fy - 25.2) / 5.4) ** 2))
                crown = max(top_curve, bottom_curve)
                groove_top, glint_top = reference_tooth_shadow(fx, fy, True)
                groove_bottom, glint_bottom = reference_tooth_shadow(fx, fy, False)
                groove = max(groove_top, groove_bottom)
                glint = max(glint_top, glint_bottom)
                luma = 45.0 + 62.0 * crown + 17.0 * n + 16.0 * grit
                luma += 28.0 * glint
                luma -= 46.0 * groove
                luma *= side_burn
                r, g, b = material_rgb(luma)
                alpha = clamp((50.0 + 198.0 * body) * end_falloff)
            else:
                pillar = 1.0 - opening
                block_noise = 0.78 + 0.22 * fbm(fx * 0.51 + fy * 0.79, 12301)
                shelf_shadow = 1.0 - 0.24 * math.exp(-(((fy - 18.0) / 2.7) ** 2))
                luma = (17.0 + 54.0 * pillar + 14.0 * n + 9.0 * grit) * side_burn * block_noise * shelf_shadow
                r, g, b = material_rgb(luma)
                if opening > 0.10:
                    darkness = clamp01(opening * 1.08)
                    r = clamp(r * (1.0 - 0.95 * darkness))
                    g = clamp(g * (1.0 - 0.92 * darkness))
                    b = clamp(b * (1.0 - 0.88 * darkness))
                alpha = clamp((44.0 + 158.0 * hardware) * (1.0 - 0.20 * opening) * end_falloff)

            if has_cyan and hardware > 0.01 and opening > 0.08:
                dx = fx - cyan_center
                row = math.exp(-(((fy - 18.2) / 2.8) ** 2))
                halo = math.exp(-((dx / 8.0) ** 2))
                hot = math.exp(-((dx / 2.1) ** 2))
                tail = smoothstep(0.0, 6.0, -dx) * (max(0.0, 1.0 - (-dx) / 15.0) ** 1.7)
                speckle = 0.36 + 0.44 * hash01(int(fx // 4), int(fy // 2), frame, seed=12401)
                amount = clamp01((0.22 * halo + 0.48 * hot + 0.07 * tail) * row * opening * speckle)
                if amount > 0.0:
                    r = clamp(r * (1.0 - 0.76 * amount) + 2.0 * amount)
                    g = clamp(g + 160.0 * amount)
                    b = clamp(b + 150.0 * amount)

            px[x, y] = (r, g, b, alpha)

    return img.filter(ImageFilter.GaussianBlur(radius=0.18))


def render(out_path: Path, runtime_out_path: Path | None = None) -> None:
    raw = render_strip(RAW_W, RAW_H)
    assert raw.size == (10965, 11), raw.size
    assert raw.crop((0, 0, RAW_W, RAW_H)).tobytes() == raw.crop(((FRAMES - 1) * RAW_W, 0, raw.width, RAW_H)).tobytes()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw.save(out_path)
    print(out_path)

    if runtime_out_path is not None:
        runtime = runtime_strip_from_raw(raw)
        assert runtime.size == (19221, 36), runtime.size
        assert runtime.crop((0, 0, RUNTIME_W, RUNTIME_H)).tobytes() == runtime.crop(((FRAMES - 1) * RUNTIME_W, 0, runtime.width, RUNTIME_H)).tobytes()
        runtime_out_path.parent.mkdir(parents=True, exist_ok=True)
        runtime.save(runtime_out_path)
        print(runtime_out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=r"C:\Users\hooki\df2\juce-shell\assets\ui\thumbwheel_strip_129_85x11.png",
        help="Output PNG path for the raw 10965x11 strip.",
    )
    parser.add_argument(
        "--runtime-out",
        default=None,
        help="DEPRECATED. The runtime strip is owned by render_runtime_149x36_strip.py; "
             "this script only maintains the legacy raw 85x11 strip.",
    )
    args = parser.parse_args()
    render(Path(args.out), Path(args.runtime_out) if args.runtime_out else None)


if __name__ == "__main__":
    main()
