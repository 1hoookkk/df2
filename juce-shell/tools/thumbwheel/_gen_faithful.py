#!/usr/bin/env python3
"""FAITHFUL thumbwheel filmstrip generator (clean-room, structure-matched).

Object: a horizontal cylinder thumbwheel lying axis L<->R in a recessed slot,
protruding through the faceplate. Cylinder curvature splits its visible face into
THREE horizontal bands of evenly-pitched MOLDED TEETH (bone-white, neutral):

  TOP band   : a row of bright FLAT TOOTH-CAPS (light/bone rectangles, dark
               grooves between) -- top tooth faces catching light near the crest.
  MID band   : darkest -- the foreshortened tooth SIDE-WALLS compressed into thin
               dark diagonal slivers where the surface turns away fastest. The
               internal UV light glows in/around this band.
  BOTTOM band: a dimmer second row of tooth faces curving down into slot shadow.

Measured from E-mu BITMAP4331 (10965x16 = 129 frames of 85x16), clean-room
(numbers measured, NO source pixels copied):
  - tooth pitch ~6.5px, ~13 teeth across the 85px face (FFT dominant = 13 cyc).
  - per-row band structure (16px): caps peak y4 (luma ~88), mid trough y6-7
    (luma ~48, darkest), bottom band peak y11 (luma ~70), slot floor y14-15.
  - band fractions: top ~5/16, mid ~4/16, bottom ~5/16, slot ~2/16.

Output spec (shared by all variants):
  - native frame 96 x 14, strip = 129 identical frames = 12384 x 14, RGBA.
  - teeth do NOT move frame-to-frame; only a runtime light animates value.
  - FRONT bone MASK: tooth BODIES semi-transparent in alpha (internal light
    transmits through the body height); bright CAPS + top/bottom slot LIPS opaque.
  - UV tokens (PREVIEW composite only): hot core 0xffe5dcff, dim 0xff9f8fc8.
    Fully unlit at value 0 and value 1.

Faithful pitch chosen = 6 px (cap 4 + groove 2) -> 16 teeth across 96px, which
maps the measured 6.5px/13-teeth density onto the wider 96px frame (96*13/85 ~ 15).
"""
import math
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "_preview"
OUT.mkdir(exist_ok=True)

FRAMES = 129
FW, FH = 96, 14

# ---- bone-white neutral plastic ramp (peak is BONE, not pure white) ----------
BONE_DEEP   = (52, 51, 49)
BONE_SHADOW = (96, 95, 91)
BONE_BASE   = (150, 150, 145)
BONE_MID    = (192, 192, 187)
BONE_HIGH   = (224, 223, 218)

UV_CORE = (229, 220, 255)   # 0xffe5dcff
UV_DIM  = (159, 143, 200)   # 0xff9f8fc8
SLOT    = (20, 18, 23)
PANEL   = (196, 186, 166)

# ---- faithful geometry (measured) -------------------------------------------
PITCH = 6              # tooth pitch px: cap 4 + groove 2 -> 16 teeth across 96
CAP_W = 4              # width of the flat lit cap
SEED  = 4331

# Vertical band structure on 14 rows, derived from the measured 16-row profile
# (top caps / dark mid crest / bottom band / slot lips). The MID band is the
# darkest (foreshortened side-walls); the internal light glows there.
#  rows 0-1  : top slot lip (occluding, opaque, dark)
#  rows 2-4  : TOP band bright flat caps
#  rows 5-7  : MID band -- darkest, foreshortened crest side-walls
#  rows 8-10 : BOTTOM band -- dimmer second row of tooth faces
#  rows 11   : curving into shadow
#  rows 12-13: bottom slot lip (occluding, opaque, dark)
#  rows 0-1  : top slot lip (occluding, opaque, dark)
#  rows 2-4  : TOP band bright flat caps
#  rows 5-7  : MID band -- DARKEST, foreshortened crest side-walls (thin dark)
#  rows 8-10 : BOTTOM band -- dimmer second row of tooth faces
#  rows 11   : curving into shadow
#  rows 12-13: bottom slot lip (occluding, opaque, dark)
# Mid band is pushed genuinely dark so the crest reads as turning away.
ROW_BASE = (26, 64, 230, 248, 222, 74, 52, 64, 168, 150, 122, 86, 44, 24)
# Transmission per row: the light shows through the tooth BODY -- strongest in
# the mid/crest band (where the real internal light glows) tapering to the caps
# and the bottom. Lips and bright caps stay opaque (low transmission).
ROW_TRANS = (0.00, 0.00, 0.05, 0.03, 0.16, 0.70, 0.88, 0.82,
             0.40, 0.28, 0.16, 0.08, 0.00, 0.00)
LIP_ROWS  = (0, 1, 12, 13)
# Cylinder cross-section shading: a smooth top-lit -> bottom-shadow multiplier
# applied to every row. Crown (top caps) catches most light; the lower band rolls
# into shadow. This is what makes the flat strip read as a round cylinder.
CURVE_SHADE = (0.78, 0.90, 1.06, 1.08, 1.04, 0.96, 0.90, 0.86,
               0.84, 0.80, 0.74, 0.66, 0.58, 0.52)
# The dark mid band carries thin diagonal slivers. Keep the skew SUBTLE (a few
# px across the 3 rows) so it reads as a foreshortened side-wall, not a bowtie.
MID_ROWS  = (5, 6, 7)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def smooth(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def noise01(a, b, c, s):
    n = (a * 73856093) ^ (b * 19349663) ^ (c * 83492791) ^ s
    n = (n ^ (n >> 13)) * 1274126177
    return ((n ^ (n >> 16)) & 255) / 255.0


def lerp(a, b, t):
    return tuple(int(round(a[i] * (1.0 - t) + b[i] * t)) for i in range(3))


def bone(v):
    v = clamp(v, 0, 255)
    if v < 80:
        return lerp(BONE_DEEP, BONE_SHADOW, v / 80.0)
    if v < 150:
        return lerp(BONE_SHADOW, BONE_BASE, (v - 80.0) / 70.0)
    if v < 200:
        return lerp(BONE_BASE, BONE_MID, (v - 150.0) / 50.0)
    return lerp(BONE_MID, BONE_HIGH, (v - 200.0) / 55.0)


def tooth_at(x, row_shift=0):
    """Tooth column structure. row_shift skews the groove phase so the mid-band
    side-walls read as diagonal slivers rather than vertical bars."""
    xs = x + row_shift
    local = xs % PITCH
    idx = xs // PITCH
    is_groove = local >= CAP_W            # the 2px recess between caps
    return idx, local, is_groove


def end_rolloff(x):
    """Cylinder turns away at the L/R edges of the visible face -> dims + fades."""
    e = min(x, FW - 1 - x)
    return 0.55 + 0.45 * smooth(e / 12.0)


def corner_alpha(x):
    e = min(x, FW - 1 - x)
    return clamp(smooth((e + 0.4) / 2.4), 0.0, 1.0)


def surface_luma(x, y):
    base = float(ROW_BASE[y])
    in_mid = y in MID_ROWS
    idx, local, is_groove = tooth_at(x, 0)

    v = base
    # per-tooth molded variation (some proud, some worn) -- keyed to the cap idx
    cap_idx = idx
    v += (noise01(cap_idx, 0, 0, SEED) - 0.5) * 18.0

    if y in (2, 3, 4):                     # TOP cap band -- bright flat caps
        if is_groove:
            v -= 95.0 + 30.0 * noise01(cap_idx, 7, 0, SEED + 5)   # dark groove
        else:
            if local == 0:
                v += 16.0                  # left edge of cap catches light
            elif local == CAP_W - 1:
                v -= 16.0                  # right edge falls to shadow
            if y == 2:
                v += 12.0                  # crisp top of cap
            if y == 4:
                v -= 22.0                  # under-cap shadow -> caps read as proud
    elif in_mid:                           # MID band -- uniformly DARK crest.
        # The whole band stays dark (the cylinder surface turning away). A thin
        # diagonal dark sliver per tooth LEANS across the band (its x-position
        # advances with y) -> the foreshortened side-wall marks. It sits OFF the
        # cap-groove phase so it never bridges cap->bottom into a bowtie.
        sliver = (x + (y - 5) * 2) % PITCH   # lean: +2px per row down
        if sliver == 0 or sliver == PITCH - 1:
            v -= 14.0                        # the dark diagonal sliver
        else:
            v += 16.0                        # dim lit face between slivers (visible)
    elif y in (8, 9, 10, 11):              # BOTTOM band -- dim second tooth row.
        # Defined dimmer faces with real grooves so the lower teeth read, but the
        # whole band stays clearly darker than the crown (curvature shading does
        # the rest).
        if is_groove:
            v -= 44.0 + 16.0 * noise01(cap_idx, 9, 0, SEED + 11)
        else:
            if local == 0:
                v += 12.0                  # lit left edge of lower face
            elif local == CAP_W - 1:
                v -= 10.0                  # right edge into shadow
            if y == 8:
                v += 8.0                   # brighter top of the lower face

    # fine surface grain
    v += (noise01(x, y + 31, 0, SEED + 7) - 0.5) * 6.0
    # cylinder curvature shading: lit toward the top crown, falling into shadow
    # toward the bottom as the surface rolls away -> sells the round cross-section.
    v *= CURVE_SHADE[y]
    v *= end_rolloff(x)
    return v


def row_alpha(x, y):
    a = 255.0 * corner_alpha(x)
    tr = ROW_TRANS[y]
    if tr <= 0.0:
        return int(a)
    in_mid = y in MID_ROWS
    row_shift = (y - 6) if in_mid else 0
    _, _, is_groove = tooth_at(x, row_shift)
    # grooves transmit MORE (the light leaks between teeth); cap faces less.
    factor = 1.0 - tr * (0.30 if is_groove else 0.92)
    return int(a * clamp(factor, 0.04, 1.0))


def make_mask():
    img = Image.new("RGBA", (FW, FH), (0, 0, 0, 0))
    px = img.load()
    for y in range(FH):
        is_lip = y in LIP_ROWS
        for x in range(FW):
            v = surface_luma(x, y)
            rgb = bone(v)
            if is_lip:
                rgb = lerp(rgb, BONE_DEEP, 0.65)   # occluding slot lip
            px[x, y] = (*rgb, row_alpha(x, y))
    return img


# ---- PREVIEW back-light (the real light is runtime) -------------------------
def back_light(norm):
    """UV field behind the mask. Sweeps L->R with value, leading-edge bright +
    short trailing tail, FILLS the tooth-body height (concentrated on the mid
    crest band where the real light glows). Unlit at 0.0 and 1.0."""
    img = Image.new("RGB", (FW, FH), SLOT)
    if norm <= 0.0 or norm >= 1.0:
        return img
    px = img.load()
    lx = (0.06 + 0.80 * norm) * (FW - 1)   # body cx ~0.06 -> 0.86
    lead, tail = 5.0, 17.0
    cy, vh = 6.5, 6.0                      # centred on the dark mid crest band
    for y in range(FH):
        vy = smooth(clamp(1.0 - abs(y - cy) / vh, 0.0, 1.0))
        if vy <= 0:
            continue
        for x in range(FW):
            dx = x - lx
            hx = max(0.0, 1.0 - dx / lead) if dx >= 0 else max(0.0, 1.0 - (-dx) / tail)
            inten = (hx ** 1.2) * vy
            if inten <= 0.02:
                continue
            col = lerp(UV_DIM, UV_CORE, min(1.0, inten * 1.7))
            base = px[x, y]
            k = min(1.0, inten * 2.0)
            px[x, y] = tuple(int(base[i] * (1 - k) + col[i] * k) for i in range(3))
    return img


def recessed_well(fw, fh, S):
    """Draw the slot: rounded dark recess + soft lip shadow top/bottom so the
    cylinder protrusion / depth reads."""
    mx, my = 9, 8
    CW, CH = (FW + 2 * mx) * S, (FH + 2 * my) * S
    canvas = Image.new("RGB", (CW, CH), PANEL)
    cv = canvas.load()
    fx, fy = mx * S, my * S
    for yy in range(CH):
        for xx in range(CW):
            inside = (fx - S) <= xx < (fx + fw + S) and (fy - S) <= yy < (fy + fh + S)
            if inside:
                # vertical gradient inside the slot -> deep recess
                ty = (yy - (fy - S)) / (fh + 2 * S)
                # rounded ends: darken near L/R extremes of the opening
                tx = clamp(min(xx - (fx - S), (fx + fw + S) - 1 - xx) / (3.0 * S), 0.0, 1.0)
                shade = lerp((8, 7, 10), SLOT, smooth(ty))
                cv[xx, yy] = lerp((4, 3, 6), shade, smooth(tx))
            else:
                near_top = (fy - 3 * S) <= yy < (fy - S)
                near_bot = (fy + fh + S) <= yy < (fy + fh + 3 * S)
                if (fx - 3 * S) <= xx < (fx + fw + 3 * S):
                    if near_top:
                        t = ((fy - S) - yy) / (2.0 * S)
                        cv[xx, yy] = lerp((232, 224, 208), PANEL, smooth(t))   # lit top lip
                    elif near_bot:
                        t = (yy - (fy + fh + S)) / (2.0 * S)
                        cv[xx, yy] = lerp((118, 110, 96), PANEL, smooth(t))    # shadow bottom lip
    return canvas, fx, fy


def scene_cell(norm, S=7):
    fw, fh = FW * S, FH * S
    canvas, fx, fy = recessed_well(fw, fh, S)
    # back-light behind the mask
    light = back_light(norm).resize((fw, fh), Image.Resampling.NEAREST)
    canvas.paste(light, (fx, fy))
    # bone mask over the light
    mask = make_mask().resize((fw, fh), Image.Resampling.NEAREST)
    canvas.paste(mask, (fx, fy), mask)
    # protrusion cues: bright crown catch on the top of the cylinder + cast shadow
    crown = Image.new("RGBA", (fw, S), (255, 250, 242, 60))
    canvas.paste(crown, (fx, fy + S), crown)
    shadow = Image.new("RGBA", (fw + 2 * S, 2 * S), (0, 0, 0, 120))
    canvas.paste(shadow, (fx - S, fy + fh - S), shadow)
    return canvas


def build_scene():
    norms = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    cells = [scene_cell(n) for n in norms]
    gap = 12
    W = sum(c.width for c in cells) + gap * (len(cells) - 1)
    H = max(c.height for c in cells)
    sheet = Image.new("RGB", (W, H), (64, 64, 68))
    x = 0
    for c in cells:
        sheet.paste(c, (x, 0))
        x += c.width + gap
    return sheet


def build_strip():
    frame = make_mask()
    strip = Image.new("RGBA", (FRAMES * FW, FH), (0, 0, 0, 0))
    for i in range(FRAMES):
        strip.alpha_composite(frame, (i * FW, 0))
    return strip, frame


def main():
    strip, frame = build_strip()
    strip.save(OUT / "strip_faithful.png")
    frame.resize((FW * 8, FH * 8), Image.Resampling.NEAREST).save(OUT / "frame_faithful_8x.png")
    build_scene().save(OUT / "scene_faithful.png")
    print(f"strip_faithful.png  {strip.width}x{strip.height}  ({FRAMES} x {FW}x{FH})")
    print(f"PITCH={PITCH} CAP_W={CAP_W} -> {FW // PITCH} teeth across {FW}px face")
    print("wrote scene_faithful.png + frame_faithful_8x.png")


if __name__ == "__main__":
    main()
