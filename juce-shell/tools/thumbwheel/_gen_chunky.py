#!/usr/bin/env python3
"""CHUNKY thumbwheel filmstrip generator (front bone MASK, RGBA).

Clean-room: STRUCTURE measured from the E-mu X3 roller BITMAP4331 (a horizontal
cylinder thumbwheel of molded teeth seated in a recessed slot). No source pixels
copied — every pixel authored here.

THE OBJECT: a horizontal cylinder lying axis L<->R, protruding through a recessed
faceplate slot, rolled by the thumb. Three horizontal bands from the curvature:
  TOP    : bright FLAT tooth-CAPS (bone rectangles, dark grooves between) catching
           light near the top of the roll.
  MIDDLE : darkest — foreshortened tooth SIDE-WALLS compressed into thin dark
           slivers at the crest where the surface turns away fastest; the internal
           UV glows in/around this band.
  BOTTOM : a dimmer second row of tooth faces curving down into the slot shadow.

CHUNKY variant: FEWER, WIDER teeth, bold flat bright caps, deep grooves — heavier
molded relief, the boldest read, still a credible rolling cylinder.

Two-layer model: this strip is the FRONT bone mask. Tooth BODIES are
semi-transparent in alpha (internal light transmits through body height); bright
CAPS and top/bottom slot LIPS are opaque. The UV light is drawn at runtime BEHIND
this mask (here we composite a preview using the UV tokens).
"""
import math
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "_preview"
OUT.mkdir(exist_ok=True)

FRAMES = 129
FW, FH = 96, 14

# ---- bone palette (neutral, NOT warm; peak is bone, not pure white) ----
BONE_DEEP = (54, 53, 50)
BONE_SHADOW = (98, 97, 93)
BONE_BASE = (158, 158, 153)
BONE_MID = (200, 200, 195)
BONE_HIGH = (232, 231, 226)

# ---- UV tokens (preview only; real light is runtime) ----
UV_CORE = (229, 220, 255)   # 0xffe5dcff hot core
UV_DIM = (159, 143, 200)    # 0xff9f8fc8 dim
SLOT = (22, 20, 25)
PANEL = (196, 186, 166)

# ---- CHUNKY geometry ----
PITCH = 8           # tooth pitch: cap 6px + groove 2px  -> 12 teeth across 96px
CAP_W = 6
GROOVE_W = PITCH - CAP_W
N_TEETH = FW // PITCH
SEED = 4331

# Three-band vertical layout (rows 0..13):
#   rows 0..1   : top slot LIP (opaque occluder)
#   rows 2..4   : TOP band  -> bright flat tooth CAPS
#   rows 5..7   : MIDDLE band-> dark foreshortened crest slivers (UV glows here)
#   rows 8..11  : BOTTOM band-> dimmer second row of curving-down faces
#   rows 12..13 : bottom slot LIP (opaque occluder, deepest shadow)
LIP_ROWS = (0, 1, 12, 13)
TOP_BAND = (2, 3, 4)
MID_BAND = (5, 6, 7)
BOT_BAND = (8, 9, 10, 11)

# Base luma per row: bright caps, dark crest valley in the middle, mid-dim bottom
# faces falling into the slot.  This is the cylinder cross-section brightness.
ROW_BASE = (
    26,   # 0  lip
    36,   # 1  lip
    222,  # 2  cap (bright flat)
    238,  # 3  cap (brightest, top-lit)
    206,  # 4  cap underside
    78,   # 5  crest sliver (turning away)
    52,   # 6  crest sliver (darkest, fastest turn)
    62,   # 7  crest sliver bottom (still dark) -> faces begin
    150,  # 8  bottom face top (catches a second highlight)
    128,  # 9  bottom face
    92,   # 10 bottom face dimming
    58,   # 11 bottom face into slot shadow
    38,   # 12 lip
    24,   # 13 lip
)

# Transmission: how much the runtime UV shows through the body at each row.
# Peaks in the MIDDLE band (the dark crest slivers glow) and stays high through
# the bottom faces; caps & lips are opaque.
ROW_TRANS = (
    0.00,  # 0  lip opaque
    0.00,  # 1  lip opaque
    0.04,  # 2  cap nearly opaque
    0.02,  # 3  cap opaque (bright flat)
    0.10,  # 4  cap underside
    0.62,  # 5  crest glows
    0.88,  # 6  crest glows brightest
    0.78,  # 7  crest
    0.56,  # 8  bottom face transmits
    0.46,  # 9
    0.30,  # 10
    0.14,  # 11 face into shadow
    0.00,  # 12 lip opaque
    0.00,  # 13 lip opaque
)


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
    return tuple(int(round(a[i] * (1.0 - t) + b[i] * t)) for i in range(len(a)))


def bone(v):
    v = clamp(v, 0, 255)
    if v < 88:
        return lerp(BONE_DEEP, BONE_SHADOW, v / 88.0)
    if v < 150:
        return lerp(BONE_SHADOW, BONE_BASE, (v - 88.0) / 62.0)
    if v < 200:
        return lerp(BONE_BASE, BONE_MID, (v - 150.0) / 50.0)
    return lerp(BONE_MID, BONE_HIGH, (v - 200.0) / 30.0)


def tooth_at(x):
    """Return (idx, local, is_groove). local 0..CAP_W-1 = cap face; rest = groove."""
    idx = x // PITCH
    local = x % PITCH
    is_groove = local >= CAP_W
    return idx, local, is_groove


def end_rolloff(x):
    """Cylinder ends curve away -> darken near the L/R extremes."""
    e = min(x, FW - 1 - x)
    return 0.55 + 0.45 * smooth(e / 10.0)


def corner_alpha(x):
    e = min(x, FW - 1 - x)
    return clamp(smooth((e + 0.4) / 2.4), 0.0, 1.0)


def surface_luma(x, y):
    """Bone luma of the front mask at (x,y): a wide molded tooth with a bright
    flat cap (top-left lit), a foreshortened dark crest sliver, and a dimmer
    bottom face curving into the slot.  Grooves between teeth are deep + dark."""
    idx, local, is_groove = tooth_at(x)
    v = float(ROW_BASE[y])

    # per-tooth molding variation (some teeth proud, some worn) — kept modest so
    # the CHUNKY caps read clean and bold.
    v += (noise01(idx, 0, 0, SEED) - 0.5) * 16.0

    if y in LIP_ROWS:
        return v * end_rolloff(x)

    if is_groove:
        # DEEP groove between wide teeth -> strong dark relief carried through all
        # three bands so the teeth read as discrete molded units, not a flat comb.
        if y in TOP_BAND:
            depth = 110.0           # crisp dark gap between bright caps
        elif y in MID_BAND:
            depth = 44.0            # crest band already dark; keep some separation
        else:
            depth = 70.0            # bottom groove falls into shadow
        # the right edge of the groove (start of next tooth's lit wall) is darkest
        gpos = (local - CAP_W) / max(1, GROOVE_W - 1) if GROOVE_W > 1 else 0.0
        v -= depth * (0.7 + 0.3 * (1.0 - abs(gpos - 0.5) * 2.0))
        v *= end_rolloff(x)
        return v

    # ---- on a tooth cap face ----
    capf = local / max(1, CAP_W - 1)   # 0 = left edge, 1 = right edge

    if y in TOP_BAND:
        # bright FLAT cap; gentle left-light/right-shade bevel keeps it molded
        edge = (1.0 - capf) * 8.0 - capf * 7.0
        v += edge
        if y == TOP_BAND[0]:
            v += 5.0                # crisp top rim of cap
        if y == TOP_BAND[-1]:
            v -= 26.0              # strong under-cap shadow -> the crest turn
    elif y in MID_BAND:
        # foreshortened crest side-wall: compressed DARK sliver, darkest mid-band.
        # keep it almost flat-dark so it reads as the receding crest, not a face.
        v -= 8.0
        v += (1.0 - abs(capf - 0.5) * 2.0) * 3.0   # faint molded spec
    else:  # BOT_BAND
        # second row of faces curving down into the slot: a fresh highlight at the
        # top of the band, then steadily dimming -> the cylinder rolling away
        if y == BOT_BAND[0]:
            v += 8.0               # second-row catch
        v += (1.0 - capf) * 7.0 - capf * 5.0

    # fine surface grain
    v += (noise01(x, y + 31, 0, SEED + 7) - 0.5) * 6.0
    v *= end_rolloff(x)
    return v


def row_alpha(x, y):
    """Mask opacity. Bodies (crest + bottom faces) semi-transparent so runtime UV
    transmits; caps, grooves, lips more opaque."""
    base = 255.0 * corner_alpha(x)
    tr = ROW_TRANS[y]
    if tr <= 0.0:
        return int(base)
    _, _, is_groove = tooth_at(x)
    # grooves transmit less than tooth bodies (they're solid molded valleys)
    striate = 1.0 - tr * (0.45 if is_groove else 0.95)
    return int(base * clamp(striate, 0.05, 1.0))


def draw_native_frame():
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


def make_strip():
    frame = draw_native_frame()
    strip = Image.new("RGBA", (FRAMES * FW, FH), (0, 0, 0, 0))
    for i in range(FRAMES):
        strip.alpha_composite(frame, (i * FW, 0))
    return strip, frame


# ---------------------------------------------------------------------------
# PREVIEW: runtime UV back-light (tokens) + recessed well composite
# ---------------------------------------------------------------------------
def back_light(norm):
    """UV field behind the mask: leading-edge-bright + short trailing tail, swept
    L->R with value (cx ~0.06->0.86), filling the body height, UNLIT at 0 and 1."""
    img = Image.new("RGB", (FW, FH), SLOT)
    if norm <= 0.0 or norm >= 1.0:
        return img
    px = img.load()
    lx = (0.06 + 0.80 * norm) * (FW - 1)
    lead, tail = 4.0, 18.0
    # vertical glow centred on the crest (MIDDLE) band, falling through the body
    cy, vh = 6.5, 5.5
    for y in range(FH):
        vy = smooth(clamp(1.0 - abs(y - cy) / vh, 0.0, 1.0))
        # weight by transmission so the glow lives where the body lets it through
        vy *= clamp(ROW_TRANS[y] * 1.3, 0.0, 1.0)
        if vy <= 0.0:
            continue
        for x in range(FW):
            dx = x - lx
            hx = max(0.0, 1.0 - dx / lead) if dx >= 0 else max(0.0, 1.0 - (-dx) / tail)
            inten = (hx ** 1.2) * vy
            if inten <= 0.02:
                continue
            col = lerp(UV_DIM, UV_CORE, min(1.0, inten * 1.7))
            base = px[x, y]
            k = min(1.0, inten * 1.9)
            px[x, y] = tuple(int(base[i] * (1 - k) + col[i] * k) for i in range(3))
    return img


def scene_cell(norm, S=7):
    """One value position: UV glow BEHIND the bone mask, seated in a recessed
    well (rounded dark slot + soft top/bottom lip shadow)."""
    mx, my = 8, 8
    CW, CH = (FW + 2 * mx) * S, (FH + 2 * my) * S
    canvas = Image.new("RGB", (CW, CH), PANEL)
    cv = canvas.load()
    fx, fy = mx * S, my * S
    fw, fh = FW * S, FH * S

    # recessed well: dark rounded slot + lip embossing on the panel
    for yy in range(CH):
        for xx in range(CW):
            inside = (fx - S) <= xx < (fx + fw + S) and (fy - S) <= yy < (fy + fh + S)
            if inside:
                ty = (yy - (fy - S)) / (fh + 2 * S)
                # darker toward top & bottom edges -> a cylindrical well
                edge = abs(ty - 0.5) * 2.0
                base = lerp((10, 9, 12), SLOT, smooth(1.0 - edge))
                cv[xx, yy] = base
            else:
                near_top = (fy - 3 * S) <= yy < (fy - S)
                near_bot = (fy + fh + S) <= yy < (fy + fh + 3 * S)
                near_x = (fx - 3 * S) <= xx < (fx + fw + 3 * S)
                if near_x and near_top:
                    cv[xx, yy] = lerp(PANEL, (238, 230, 214), 0.6)   # lit top lip
                elif near_x and near_bot:
                    cv[xx, yy] = lerp(PANEL, (116, 108, 94), 0.6)    # shadow bottom lip

    # UV light behind the mask
    light = back_light(norm).resize((fw, fh), Image.Resampling.NEAREST)
    canvas.paste(light, (fx, fy))

    # bone mask over the light
    mask = draw_native_frame().resize((fw, fh), Image.Resampling.NEAREST)
    canvas.paste(mask, (fx, fy), mask)

    # protrusion cues: bright crown catch on the top of the cylinder + cast shadow
    crown = Image.new("RGBA", (fw, int(1.6 * S)), (255, 251, 242, 64))
    canvas.paste(crown, (fx, fy + int(0.6 * S)), crown)
    shadow = Image.new("RGBA", (fw + 2 * S, 3 * S), (0, 0, 0, 140))
    canvas.paste(shadow, (fx - S, fy + fh - S), shadow)
    return canvas


def make_scene():
    norms = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    cells = [scene_cell(n) for n in norms]
    gap = 12
    W = sum(c.width for c in cells) + gap * (len(cells) - 1)
    H = max(c.height for c in cells)
    sheet = Image.new("RGB", (W, H), (66, 66, 70))
    x = 0
    for c in cells:
        sheet.paste(c, (x, 0))
        x += c.width + gap
    return sheet


def main():
    strip, _ = make_strip()
    strip.save(OUT / "strip_chunky.png")
    make_scene().save(OUT / "scene_chunky.png")
    print(f"wrote strip_chunky.png ({strip.width}x{strip.height}) + scene_chunky.png")
    print(f"teeth={N_TEETH}  pitch={PITCH} (cap {CAP_W}+groove {GROOVE_W})")
    print(f"bands: lip 0-1 | TOP caps {TOP_BAND} | MID crest {MID_BAND} | BOT faces {BOT_BAND} | lip 12-13")


if __name__ == "__main__":
    main()
