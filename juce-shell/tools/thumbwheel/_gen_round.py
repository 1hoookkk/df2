#!/usr/bin/env python3
"""ROUND variant: a 3D bone cylinder thumbwheel bulging out of a recessed slot,
with medium-pitch molded teeth riding over the curvature.

Clean-room: STRUCTURE measured from the E-mu X3 roller BITMAP4331 (a rolled
cylinder showing three foreshortened bands of molded teeth). No source pixels
are loaded, traced, or copied. Every pixel is authored from a parametric
cylinder model.

THE OBJECT: a horizontal cylinder (axis left<->right) seated in a recessed slot,
protruding through the faceplate. Across its 14px height the curvature gives
THREE bands:
  TOP    (rows ~2-5)  : bright FLAT tooth-CAPS catching light near the crest.
  MIDDLE (rows ~6-8)  : darkest band, foreshortened tooth SIDE-WALLS as thin
                        dark slivers where the surface turns away fastest; the
                        internal UV glows through here.
  BOTTOM (rows ~9-12) : a dimmer second row of tooth faces curving down into
                        the slot shadow.

The HERO is the roundness: a strong smooth vertical bright-crest gradient that
reads as a cylinder bulging out. Teeth are secondary texture on the curve.

Two-layer model (this strip = FRONT bone MASK):
  - Tooth/body BODIES are semi-transparent in alpha so the runtime internal
    light transmits through the body height.
  - Bright CAPS and top/bottom slot LIPS are opaque.
Output RGBA, 96x14 native, 129 identical frames (12384x14).

UV tokens for the PREVIEW composite only (real light is runtime):
  hot core 0xffe5dcff, dim 0xff9f8fc8. UNLIT at value 0.0 and 1.0.
"""
import math
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "_preview"
OUT.mkdir(exist_ok=True)

FRAMES = 129
FW, FH = 96, 14

# Bone-white NEUTRAL palette (peak is bone, never pure white -> no glowing slats)
BONE_DEEP = (54, 53, 51)
BONE_SHADOW = (96, 95, 91)
BONE_BASE = (158, 158, 152)
BONE_MID = (200, 200, 194)
BONE_HIGH = (232, 231, 225)

UV_CORE = (229, 220, 255)   # 0xffe5dcff
UV_DIM = (159, 143, 200)    # 0xff9f8fc8
PANEL = (196, 186, 166)
SLOT = (22, 20, 24)

SEED = 4331

# -------- cylinder geometry (the HERO) ----------------------------------------
# Map row y -> surface angle phi about the cylinder axis. phi=0 at the crest
# (front, facing viewer), +/- toward the slot lips. The visible arc is roughly
# +/- 78 deg; the rest is occluded by the slot. cos(phi) drives both the
# diffuse brightness (Lambert, light from top) and the foreshortening that
# compresses the lower bands.
ARC_DEG = 74.0                 # half-arc visible above the slot
LIGHT_PHI = math.radians(-14)  # light comes from above-front -> crest-bright band sits high

# Tooth pitch: medium. Teeth ride the curve; circumferential, so the visible
# tooth FACE height is foreshortened by the local cos(phi).
PITCH = 5                       # px between tooth centres (cap 3 + groove 2)


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
    if v < 84:
        return lerp(BONE_DEEP, BONE_SHADOW, v / 84.0)
    if v < 150:
        return lerp(BONE_SHADOW, BONE_BASE, (v - 84.0) / 66.0)
    if v < 202:
        return lerp(BONE_BASE, BONE_MID, (v - 150.0) / 52.0)
    return lerp(BONE_MID, BONE_HIGH, (v - 202.0) / 30.0)


# Vertical-axis cylinder parameterisation, precomputed per row -------------------
# yc in [-1, 1] across the visible arc; phi = yc * ARC. We bias the crest a touch
# above centre so the bright band reads near the top, dropping into slot shadow.
def row_geometry():
    rows = []
    for y in range(FH):
        # y normalised so the crest (phi=0, brightest) sits around row 4-5,
        # the dark side-wall band around row 7, slot shadow at the bottom.
        t = (y + 0.5) / FH                 # 0..1 top->bottom
        # nonlinear: top lip, then arc, then bottom lip
        # map t through the arc: crest (phi=0) lands near row 5 (t~0.40)
        yc = (t - 0.40) / 0.60             # -0.67 (top) .. 1.0 (bottom)
        yc = clamp(yc, -1.0, 1.0)
        phi = yc * math.radians(ARC_DEG)
        cphi = math.cos(phi)               # foreshortening + base shading
        # Lambert diffuse from the light direction (top-front)
        lam = math.cos(phi - LIGHT_PHI)
        lam = clamp(lam, 0.0, 1.0)
        rows.append((phi, cphi, lam, yc))
    return rows


ROWG = row_geometry()


def is_lip(y):
    return y <= 0 or y >= FH - 1


def band_of(y):
    """0=top caps, 1=dark side-wall middle, 2=bottom faces, -1=lip/slot."""
    phi_deg = math.degrees(ROWG[y][0])
    if is_lip(y):
        return -1
    if phi_deg < -14:
        return 0
    if phi_deg < 22:
        return 1
    return 2


band_first1 = next(y for y in range(FH) if band_of(y) == 1)
band_first2 = next(y for y in range(FH) if band_of(y) == 2)


def end_rolloff(x):
    e = min(x, FW - 1 - x)
    return 0.55 + 0.45 * smooth(e / 10.0)


def corner_alpha(x):
    e = min(x, FW - 1 - x)
    return clamp(smooth((e + 0.4) / 2.4), 0.0, 1.0)


def surface_luma(x, y):
    phi, cphi, lam, yc = ROWG[y]
    idx = x // PITCH
    local = x % PITCH
    is_groove = local >= PITCH - 2          # 2px groove between caps

    # --- HERO: cylinder body shading. Strong smooth crest gradient. ----------
    # Base curvature brightness: Lambert + ambient, peaks at the crest band.
    # Keep ambient up so bone never crushes to slot-black, but give the crest
    # a strong bulge so the roundness is unmistakable.
    v = 70.0 + 168.0 * (lam ** 1.25)
    # Extra crest bloom: a soft bright stripe right at the front of the roll.
    crest = math.exp(-((math.degrees(phi) + 2.0) ** 2) / (2 * 15.0 ** 2))
    v += 60.0 * crest
    # Slot shadow: the bottom of the arc dives into the recess; the top edge
    # also rolls away into a softer shadow under the upper lip.
    if math.degrees(phi) > 30:
        v -= (math.degrees(phi) - 30) * 2.4
    if math.degrees(phi) < -30:
        v -= (-30 - math.degrees(phi)) * 1.1

    # --- SECONDARY: molded teeth riding the curve. ---------------------------
    # Tooth structure only where the surface faces us enough to show a face.
    # Foreshortening: tooth modulation amplitude scales with cos(phi) (faces
    # turning away show only thin slivers -> the dark middle band).
    fs = clamp(cphi, 0.0, 1.0)
    proud = (noise01(idx, 0, 0, SEED) - 0.5) * 14.0   # per-tooth molded variance
    v += proud * fs * 0.6

    b = band_of(y)
    if b == 0:
        # TOP band = bright FLAT tooth-CAPS, dark grooves between. The caps are
        # the brightest hardware in the frame; deep grooves give crisp teeth.
        if is_groove:
            v -= 46.0
        else:
            v += 30.0                                  # flat lit cap
            if local == 0:
                v += 10.0                              # left edge light catch
            if local == PITCH - 3:
                v -= 8.0                               # right edge falloff
    elif b == 1:
        # MIDDLE band = DARKEST. Foreshortened tooth SIDE-WALLS read as a hard
        # dark trough across the whole band; teeth are only fine dark slivers at
        # the grooves (surface turning away fastest). Pull the band-mean down to
        # a fixed dark target so it separates hard from the bright caps above.
        v = 0.45 * v + 0.55 * 66.0                     # collapse toward dark target
        sliver = math.exp(-((local - (PITCH - 1.5)) ** 2) / (2 * 0.85 ** 2))
        v -= 26.0 * sliver
        # bright cap-lip glint right at the top edge of the dark band (the very
        # bottom rim of the caps catching light before the surface turns away)
        if y == band_first1 and not is_groove and local <= 1:
            v += 30.0
    elif b == 2:
        # BOTTOM band = a dimmer SECOND ROW of tooth faces curving down into the
        # slot shadow. Lighter than the dark middle, darker than the caps.
        v = 0.5 * v + 0.5 * 120.0
        # face shading darkens toward the bottom (deeper into the slot)
        v -= (y - band_first2) * 4.0
        if is_groove:
            v -= 20.0
        else:
            v += 12.0 * fs
            if local == 0:
                v += 6.0                               # face left-edge catch

    # fine plastic grain
    v += (noise01(x, y + 31, 0, SEED + 7) - 0.5) * 6.0
    v *= end_rolloff(x)
    return v, b, is_groove


# Transmission profile: the internal light fills the body height through the
# mid/lower bands (where the body is); caps + lips block it.
def transmission(y, b, is_groove):
    if is_lip(y):
        return 0.0
    if b == 0:
        return 0.04 if not is_groove else 0.16    # caps opaque
    if b == 1:
        return 0.46 if not is_groove else 0.66    # dark band glows most
    if b == 2:
        return 0.26 if not is_groove else 0.44
    return 0.0


def draw_native_frame():
    img = Image.new("RGBA", (FW, FH), (0, 0, 0, 0))
    px = img.load()
    for y in range(FH):
        lip = is_lip(y)
        for x in range(FW):
            v, b, is_groove = surface_luma(x, y)
            rgb = bone(v)
            if lip:
                rgb = lerp(rgb, BONE_DEEP, 0.62)      # opaque occluding slot lip
            a = 255.0 * corner_alpha(x)
            tr = transmission(y, b, is_groove)
            if tr > 0:
                a *= clamp(1.0 - tr, 0.18, 1.0)
            px[x, y] = (*rgb, int(a))
    return img


def write_strip():
    frame = draw_native_frame()
    strip = Image.new("RGBA", (FRAMES * FW, FH), (0, 0, 0, 0))
    for i in range(FRAMES):
        strip.alpha_composite(frame, (i * FW, 0))
    path = OUT / "strip_round.png"
    strip.save(path)
    return frame, path


# -------- preview-only UV back-light & recessed well ---------------------------
def back_light(norm):
    """UV field behind the mask: swept L->R, leading-edge bright + short trailing
    tail, fills the mid/lower body height. UNLIT at 0.0 and 1.0."""
    img = Image.new("RGB", (FW, FH), SLOT)
    if norm <= 0.0 or norm >= 1.0:
        return img
    px = img.load()
    cx = (0.06 + 0.80 * norm) * (FW - 1)
    lead, tail = 4.0, 18.0
    # the glow lives in the dark middle band where the body transmits most,
    # bleeding down into the lower face row; tucked under the bright caps.
    cy, vh = 6.6, 4.4
    for y in range(FH):
        vy = smooth(clamp(1.0 - abs(y - cy) / vh, 0.0, 1.0))
        if vy <= 0:
            continue
        for x in range(FW):
            dx = x - cx
            hx = max(0.0, 1.0 - dx / lead) if dx >= 0 else max(0.0, 1.0 - (-dx) / tail)
            inten = (hx ** 1.2) * vy
            if inten <= 0.02:
                continue
            col = lerp(UV_DIM, UV_CORE, min(1.0, inten * 1.6))
            base = px[x, y]
            k = min(1.0, inten * 1.95)
            px[x, y] = tuple(int(base[i] * (1 - k) + col[i] * k) for i in range(3))
    return img


def draw_well(canvas, fx, fy, fw, fh, S):
    """Recessed rounded slot: dark interior gradient + soft top/bottom lip
    shadows so the cylinder reads as protruding from depth."""
    cv = canvas.load()
    CW, CH = canvas.size
    rad = 2 * S
    for yy in range(CH):
        for xx in range(CW):
            inside_x = (fx - S) <= xx < (fx + fw + S)
            inside_y = (fy - S) <= yy < (fy + fh + S)
            if inside_x and inside_y:
                # vertical dark gradient inside the slot (top darker lip shadow,
                # lighter centre where the wheel sits, dark again at bottom)
                ty = (yy - (fy - S)) / (fh + 2 * S)
                shade = SLOT
                top = lerp((8, 7, 10), SLOT, smooth(clamp(ty / 0.5, 0, 1)))
                bot = lerp(SLOT, (6, 5, 8), smooth(clamp((ty - 0.5) / 0.5, 0, 1)))
                cv[xx, yy] = top if ty < 0.5 else bot
            else:
                near = (fx - 4 * S) <= xx < (fx + fw + 4 * S)
                if not near:
                    continue
                # lit top lip (emboss) + shadow bottom lip
                if (fy - 3 * S) <= yy < (fy - S):
                    d = (yy - (fy - 3 * S)) / (2 * S)
                    cv[xx, yy] = lerp(PANEL, (238, 230, 214), 0.55 * smooth(d))
                elif (fy + fh + S) <= yy < (fy + fh + 3 * S):
                    d = (yy - (fy + fh + S)) / (2 * S)
                    cv[xx, yy] = lerp((116, 108, 94), PANEL, 0.5 * smooth(d))


def scene_cell(norm, mask, S=7):
    mx, my = 9, 8
    CW, CH = (FW + 2 * mx) * S, (FH + 2 * my) * S
    canvas = Image.new("RGB", (CW, CH), PANEL)
    fx, fy = mx * S, my * S
    fw, fh = FW * S, FH * S
    draw_well(canvas, fx, fy, fw, fh, S)
    # UV behind mask
    light = back_light(norm).resize((fw, fh), Image.Resampling.NEAREST)
    canvas.paste(light, (fx, fy))
    # bone mask over light
    canvas.paste(mask.resize((fw, fh), Image.Resampling.NEAREST), (fx, fy),
                 mask.resize((fw, fh), Image.Resampling.NEAREST))
    # protrusion cues -----------------------------------------------------------
    # 1) thin bright specular crown line right at the top crest of the cylinder
    #    (the rounded face catching the room light as it bulges out).
    cvp = canvas.load()
    crown_y = fy + int(0.6 * S)
    for dy in range(int(1.4 * S)):
        yy = crown_y + dy
        if not (0 <= yy < canvas.height):
            continue
        a = (1.0 - dy / (1.4 * S)) * 0.42
        for xx in range(fx, fx + fw):
            base = cvp[xx, yy]
            cvp[xx, yy] = tuple(int(base[i] * (1 - a) + (255, 251, 242)[i] * a) for i in range(3))
    # 2) soft inner shadow under the top lip + curving down the bottom into the
    #    slot, so the cylinder reads as seated below the faceplate.
    for dy in range(int(2.2 * S)):
        yy = fy + fh - 1 - dy
        if not (0 <= yy < canvas.height):
            continue
        a = (1.0 - dy / (2.2 * S)) * 0.55
        for xx in range(fx, fx + fw):
            base = cvp[xx, yy]
            cvp[xx, yy] = tuple(int(base[i] * (1 - a)) for i in range(3))
    # 3) cast shadow on the panel just below the well lip
    shadow = Image.new("RGBA", (fw + 2 * S, 3 * S), (0, 0, 0, 110))
    canvas.paste(shadow, (fx - S, fy + fh - S), shadow)
    return canvas


def write_scene(mask):
    norms = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    cells = [scene_cell(n, mask) for n in norms]
    gap = 12
    W = sum(c.width for c in cells) + gap * (len(cells) - 1)
    H = max(c.height for c in cells)
    sheet = Image.new("RGB", (W, H), (66, 66, 70))
    x = 0
    for c in cells:
        sheet.paste(c, (x, 0))
        x += c.width + gap
    path = OUT / "scene_round.png"
    sheet.save(path)
    return path


def main():
    frame, strip_path = write_strip()
    scene_path = write_scene(frame)
    print("strip:", strip_path)
    print("scene:", scene_path)
    # report band rows
    bands = {0: [], 1: [], 2: [], -1: []}
    for y in range(FH):
        bands[band_of(y)].append(y)
    print("bands rows:", {k: v for k, v in bands.items()})
    print("pitch:", PITCH)


if __name__ == "__main__":
    main()
