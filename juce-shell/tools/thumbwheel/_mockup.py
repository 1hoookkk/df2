#!/usr/bin/env python3
"""MOCKUP: notch-block bone-white thumbwheel + ultraviolet back-light, composited
in a recessed slot with depth. Iteration surface BEFORE touching the plugin.

Target = E-mu BITMAP4331 (row of molded notch-blocks; bright flat caps on top,
graduated bodies, light sweeps L->R through the full body height, unlit at the
ends). Colours = bone-white + the ultraviolet tokens the user gave (NOT cyan/grey).
"""
import math
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "_preview"
OUT.mkdir(exist_ok=True)

FW, FH = 96, 14

BONE = {
    "deep": (58, 57, 54),
    "shadow": (100, 99, 95),
    "base": (152, 152, 147),
    "mid": (190, 190, 185),
    "high": (216, 215, 210),   # bone, distinctly not white
}
UV_CORE = (229, 220, 255)   # 0xffe5dcff
UV_DIM = (159, 143, 200)    # 0xff9f8fc8
PANEL = (196, 186, 166)
SLOT = (24, 22, 26)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def smooth(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def noise01(a, b, c, s):
    n = (a * 73856093) ^ (b * 19349663) ^ (c * 83492791) ^ s
    n = (n ^ (n >> 13)) * 1274126177
    return ((n ^ (n >> 16)) & 255) / 255.0


def lerp(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def bone(v):
    v = clamp(v, 0, 255)
    if v < 88:
        return lerp(BONE["deep"], BONE["shadow"], v / 88.0)
    if v < 150:
        return lerp(BONE["shadow"], BONE["base"], (v - 88) / 62.0)
    if v < 200:
        return lerp(BONE["base"], BONE["mid"], (v - 150) / 50.0)
    return lerp(BONE["mid"], BONE["high"], (v - 200) / 30.0)


# Vertical block profile: bright flat CAP (rows 2-3) over a smooth top-down
# gradient body to a dark base. No dark centre line. Lips occlude top/bottom.
ROW_BASE = (30, 92, 242, 212, 176, 156, 138, 122, 106, 90, 74, 56, 36, 24)
# Transmission fills the whole body so the glow lights the block height, not a line.
ROW_TRANS = (0.00, 0.00, 0.08, 0.20, 0.50, 0.66, 0.78, 0.82,
             0.78, 0.64, 0.42, 0.16, 0.00, 0.00)

PITCH = 4   # block pitch: key width 3 + 1px recess groove
SEED = 9027


def block_at(x):
    local = x % PITCH
    idx = x // PITCH
    is_groove = (local == PITCH - 1)
    return idx, local, is_groove


def end_rolloff(x):
    e = min(x, FW - 1 - x)
    return 0.50 + 0.50 * smooth(e / 11.0)


def corner_a(x):
    e = min(x, FW - 1 - x)
    return clamp(smooth((e + 0.4) / 2.6), 0.0, 1.0)


def make_mask():
    """A knurled bone band of molded keys with depth (not a comb of teeth). The
    grooves are SUBTLE striations, the cap tops are STAGGERED (woven edge), and a
    strong top-down gradient carries the 3D. Light fills the body behind it."""
    img = Image.new("RGBA", (FW, FH), (0, 0, 0, 0))
    px = img.load()
    for y in range(FH):
        for x in range(FW):
            idx, local, is_groove = block_at(x)
            # woven top edge: each key's cap starts at row 1 or 2
            cap_top = 1 if noise01(idx, 5, 0, SEED) > 0.5 else 2
            v = float(ROW_BASE[y])
            if 1 <= y < cap_top:                 # occlude shorter keys' tops
                v = float(ROW_BASE[1]) * 0.7
            # per-key molded tone (some proud, some worn)
            v += (noise01(idx, 0, 0, SEED) - 0.5) * 30.0

            if 2 <= y <= 11:
                if is_groove:
                    v -= 9.0 + 7.0 * noise01(idx, 7, 0, SEED + 5)   # SUBTLE striation
                elif local == 0:
                    v += 12.0                    # left wall light catch
                elif local == PITCH - 2:
                    v -= 9.0                      # right wall shadow
            # bright flat cap at the key's staggered top
            if y in (cap_top, cap_top + 1) and not is_groove:
                v += 16.0
            if y == cap_top + 2 and not is_groove:
                v -= 7.0                          # under-cap shadow = relief

            v += (noise01(x, y + 31, 0, SEED + 7) - 0.5) * 8.0
            v *= end_rolloff(x)
            rgb = bone(v)
            a = 255.0 * corner_a(x)
            tr = ROW_TRANS[y]
            if tr > 0:
                striate = 1.0 - tr * (0.50 if is_groove else 0.96)
                a *= clamp(striate, 0.05, 1.0)
            px[x, y] = (*rgb, int(a))
    return img


def back_light(norm):
    """Ultraviolet field behind the mask: sweeps L->R with value, FILLS the body
    height, tight lead, short tail, unlit at the ends."""
    img = Image.new("RGB", (FW, FH), SLOT)
    if norm <= 0.0 or norm >= 1.0:
        return img
    px = img.load()
    lx = (0.08 + 0.84 * norm) * (FW - 1)
    lead, tail = 4.0, 16.0
    cy, vh = 6.8, 6.4   # tall band -> fills the block bodies
    for y in range(FH):
        vy = smooth(clamp(1.0 - abs(y - cy) / vh, 0.0, 1.0))
        if vy <= 0:
            continue
        for x in range(FW):
            dx = x - lx
            hx = max(0.0, 1.0 - dx / lead) if dx >= 0 else max(0.0, 1.0 - (-dx) / tail)
            inten = (hx ** 1.15) * vy
            if inten <= 0.02:
                continue
            col = lerp(UV_DIM, UV_CORE, min(1.0, inten * 1.6))
            base = px[x, y]
            k = min(1.0, inten * 1.9)
            px[x, y] = tuple(int(base[i] * (1 - k) + col[i] * k) for i in range(3))
    return img


def scene(norm, S=7):
    mx, my = 8, 7
    CW, CH = (FW + 2 * mx) * S, (FH + 2 * my) * S
    canvas = Image.new("RGB", (CW, CH), PANEL)
    cv = canvas.load()
    fx, fy = mx * S, my * S
    fw, fh = FW * S, FH * S
    # raised panel surround: bright emboss rim above/left, shadow rim below/right
    for yy in range(CH):
        for xx in range(CW):
            # distance into the slot opening
            inside = (fx - S) <= xx < (fx + fw + S) and (fy - S) <= yy < (fy + fh + S)
            if inside:
                ty = (yy - (fy - S)) / (fh + 2 * S)
                cv[xx, yy] = lerp((12, 11, 14), SLOT, smooth(ty))
            else:
                # emboss the panel edge around the well
                near_top = (fy - 3 * S) <= yy < (fy - S)
                near_bot = (fy + fh + S) <= yy < (fy + fh + 3 * S)
                if (fx - 3 * S) <= xx < (fx + fw + 3 * S):
                    if near_top:
                        cv[xx, yy] = lerp(PANEL, (236, 228, 212), 0.6)  # lit top lip
                    elif near_bot:
                        cv[xx, yy] = lerp(PANEL, (120, 112, 98), 0.6)   # shadow bottom lip
    # back-light behind the mask
    light = back_light(norm).resize((fw, fh), Image.Resampling.NEAREST)
    canvas.paste(light, (fx, fy))
    # mask over the light
    mask = make_mask().resize((fw, fh), Image.Resampling.NEAREST)
    canvas.paste(mask, (fx, fy), mask)
    # protrusion cues: bright catch on the wheel's top crown + cast shadow below
    crown = Image.new("RGBA", (fw, S), (255, 250, 240, 70))
    canvas.paste(crown, (fx, fy), crown)
    shadow = Image.new("RGBA", (fw + 2 * S, 3 * S), (0, 0, 0, 130))
    canvas.paste(shadow, (fx - S, fy + fh - S), shadow)
    return canvas


def main():
    make_mask().resize((FW * 8, FH * 8), Image.Resampling.NEAREST).save(OUT / "mock_mask.png")
    norms = [0.0, 0.18, 0.42, 0.68, 0.92, 1.0]
    cells = [scene(n) for n in norms]
    gap = 10
    W = sum(c.width for c in cells) + gap * (len(cells) - 1)
    H = max(c.height for c in cells)
    sheet = Image.new("RGB", (W, H), (70, 70, 74))
    x = 0
    for c in cells:
        sheet.paste(c, (x, 0))
        x += c.width + gap
    sheet.save(OUT / "mock_scene.png")
    print("wrote mock_mask.png + mock_scene.png  norms:", norms)


if __name__ == "__main__":
    main()
