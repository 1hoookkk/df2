# Assemble the TRENCH roller filmstrip at the compact editor's true aperture
# size from the 4x headless batch passes (df2/dev/tmp/roller_batch_az90 — the
# clean-side arc). No Blender needed for re-size / re-light / re-glow.
#
# SEAT (Tyson 2026-07-16, measured from the 07-13 reference): 150x34 frame =
# the well bounds; drum 145x30 sits LOW — 3px dark socket above the crown,
# bottom melting into the contact shadow, ends 2px inside the rounded mouth.
# Union alpha>128 hard-crop first (the invisible-padding trap); uniform scale
# only (never squash).
#
# GLOW LAW (Tyson 2026-07-18, restated): the glow FOLLOWS the wheel — head
# tracks the value exactly; the lit run reaches ~50% of the width at v=1;
# frame 0 is completely dark. Cells light as units on the seated 3D drum.
#
# ROTATION LAW: the authored drum turns in the same perceived left-to-right
# direction as the value packet. The Blender batch's frame order is opposite
# to that screen-space travel, so source frames are read in reverse while the
# parameter/glow head continues forward from v=0 to v=1.
import numpy as np
from PIL import Image, ImageFilter
from pathlib import Path

NF = 257
# 2x-authored frames (drawn at half size with high-quality resampling in
# WheelControl): downscale-only everywhere kills the DPI aliasing.
FW, FH = 300, 68
DRUM_H = 60
GAP_TOP = 6

GLOW_ON = True
# The lit cell is EXTRACTED from the real X3 sheet (BITMAP4331 frame 096) —
# real centre-bright profile, nothing invented.
SHEET = Path(r"C:\Users\hooki\df2\dev\tmp\emu_bitmap_inspect\BITMAP4331_1_frame_096_85x16_8x.png")
TEETH_VISIBLE = 14               # teeth across the front face — the trail math anchor

BATCH = Path(r"C:\Users\hooki\df2\dev\tmp\roller_batch_az90")
OUT = Path(r"C:\Users\hooki\df2-workstation\plugin\assets")

def load(p):
    return np.array(Image.open(p).convert("RGBA")).astype(np.float32)

# union hard-crop box across sample frames
boxes = []
for i in (0, 64, 128, 192, 256):
    a = load(BATCH / "clean" / f"f{i:03d}.png")
    ys, xs = np.where(a[..., 3] > 128)
    boxes.append((xs.min(), xs.max(), ys.min(), ys.max()))
x0 = min(b[0] for b in boxes); x1 = max(b[1] for b in boxes)
y0 = min(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
raw_w, raw_h = x1 - x0 + 1, y1 - y0 + 1
s = DRUM_H / raw_h
drum_w = round(raw_w * s)
print(f"raw drum {raw_w}x{raw_h} -> {drum_w}x{DRUM_H}, seat top {GAP_TOP}, "
      f"ends {(FW-drum_w)//2}px inside, frame {FW}x{FH}")

# Diode-cell ROW profile, once: union of glow frames says which rows carry light.
row_profile = None
sprite_rgb = sprite_wt = None
if GLOW_ON:
    acc = None
    for j in (32, 96, 160, 224):
        gj = np.array(Image.open(BATCH / "glow" / f"f{j:03d}.png").convert("L")).astype(np.float32)
        acc = gj if acc is None else np.maximum(acc, gj)
    row_profile = acc.max(axis=1)
    row_profile = np.clip(row_profile / max(row_profile.max(), 1e-4), 0.0, 1.0) ** 0.5

    # Extract the single HEAD cell from the real sheet at 8x resolution:
    # cyanness = min(G,B)-R; cell bounds = the local separator dips either
    # side of the brightest column (measured pitch ~6px native, 14 across).
    sh = np.array(Image.open(SHEET).convert("RGB")).astype(np.float32)
    cyan = np.clip(np.minimum(sh[..., 1], sh[..., 2]) - sh[..., 0], 0, None)
    colc = cyan.max(axis=0)
    p = int(colc.argmax())
    half = 4 * 8                                      # < one native pitch, at 8x
    ra = p - half + int(colc[max(0, p - half):p].argmin())
    rb = p + 1 + int(colc[p:p + half + 1].argmin())
    # ...then crop to the SOLID core (>=50% of peak): the separator falloff
    # is re-created by the resize at stamp time.
    core = np.where(colc[ra:rb] >= 0.5 * colc[p])[0]
    ra, rb = ra + int(core.min()), ra + int(core.max()) + 1
    rowc = cyan[:, ra:rb].max(axis=1)
    rows = np.where(rowc > 0.25 * rowc.max())[0]
    sr0, sr1 = int(rows.min()), int(rows.max()) + 1
    sprite_rgb = sh[sr0:sr1, ra:rb]
    # Plateau normalization: the sheet cell is a SOLID low-contrast square —
    # mapping 55%-of-peak to full keeps the face solid to the cell edge.
    sprite_wt = np.clip(cyan[sr0:sr1, ra:rb] / (0.55 * max(cyan[sr0:sr1, ra:rb].max(), 1e-4)), 0.0, 1.0)
    # ONE LIT VOICE: the X3 sheet gives the STRUCTURE (cell profile, hot
    # core); the COLOUR is the face's own accent (#2BD8C3 = rollerIllumination
    # in UiLayout) so screen curve, active states and wheel lamp all speak
    # the same light. Hot cores still bleach toward white like the sheet.
    ACCENT = np.array([0x2b, 0xd8, 0xc3], dtype=np.float32) / 255.0
    inten = sprite_rgb.max(axis=2, keepdims=True) / 255.0
    wmix = np.clip((sprite_rgb[..., 0:1] / 255.0 - 0.15) / 0.45, 0.0, 1.0)
    sprite_rgb = 255.0 * np.clip(inten ** 0.75 * 1.10, 0, 1) * (ACCENT[None, None] * (1.0 - wmix) + wmix)
    print(f"sprite: head cell x{ra/8:.1f}-{rb/8:.1f} rows {sr0/8:.1f}-{sr1/8:.1f} (native), "
          f"peak RGB {sprite_rgb.reshape(-1,3)[sprite_wt.ravel().argmax()].round().astype(int)}")

frames = []
glow_centroids = []
glow_peak_rgb = []
for i in range(NF):
    v = i / (NF - 1)
    source_i = NF - 1 - i
    c = load(BATCH / "clean" / f"f{source_i:03d}.png")
    rgb = c[..., :3]
    H, W = rgb.shape[:2]

    xn = np.arange(W, dtype=np.float32) / W
    # Dialled back toward the reference face (2026-07-18): even metallic
    # light, a shade quieter than the full sheet match.
    # PUNCHY GLOSS (measured off the real X3 filter page 2026-07-18: roller
    # median 43, p90 104, speculars to 247): dark body, fins FLASH. The old
    # highlight knee crushed exactly this — removed.
    env = 0.86 + 0.28 * np.exp(-((xn - 0.22) ** 2) / (2 * 0.24 ** 2))
    env *= 0.45 + 0.55 * np.minimum(np.minimum(xn, 1 - xn) / 0.06, 1.0)
    n = np.clip((rgb * env[None, :, None] / 255.0 - 0.015) * 1.30, 0, 1) ** 0.86
    # SEATED cylinder ("seems to stick out", 2026-07-18): crown rolls into the
    # socket shadow, belly melts into the contact shadow.
    yn = np.clip((np.arange(rgb.shape[0], dtype=np.float32) - y0) / max(raw_h - 1, 1), 0, 1)
    vshade = 0.24 + 0.76 * np.clip(np.sin(np.pi * (0.02 + 0.90 * yn)), 0.0, 1.0) ** 1.5
    # "Hanging out a bit": near-point specular band just above centre.
    vshade += 0.65 * np.exp(-((yn - 0.42) ** 2) / (2 * 0.075 ** 2))
    n *= vshade[:, None, None]
    rgb = n * 255.0

    if GLOW_ON:
        a_mask = c[..., 3] / 255.0
        # Cells sit on a UNIFORM pitch grid; whole cells light as units.
        head = x0 + v * raw_w
        x = np.arange(W, dtype=np.float32)
        pitch = raw_w / float(TEETH_VISIBLE)
        cells = []
        for kc in range(TEETH_VISIBLE):
            a = int(round(x0 + kc * pitch))
            b = int(round(x0 + (kc + 1) * pitch))
            if b - a > 2:
                cells.append((a, b))
        # Span law (Tyson 2026-07-18): the run reaches from ZERO up to the
        # head, saturating at ~0.49 of the drum at v=1. Dark at v=0.
        tail = min(0.49, v + 0.04) * raw_w
        levels = {}
        near = min(cells, key=lambda cc: abs(0.5 * (cc[0] + cc[1] - 1) - head))
        levels[near] = 1.0                                # the value marker cell
        for a, b in cells:
            cctr = 0.5 * (a + b - 1)
            if head - tail <= cctr <= head:
                # Measured ramp (frame 096 cell peaks 21..156): near-linear
                # rise from ~13% at the tail tip to 100% at the head.
                lv = 1.0 - 0.87 * max(0.0, (head - cctr) / max(tail, 1e-3))
                levels[(a, b)] = max(levels.get((a, b), 0.0), lv)
        # Stamp the REAL sheet cell into each lit slot, scaled to the diode
        # row band — colour and centre-bright profile come from the bitmap.
        band = np.where(row_profile > 0.35)[0]
        by0, by1 = int(band.min()), int(band.max()) + 1
        E = np.zeros((H, W), dtype=np.float32)
        C = np.tile(sprite_rgb.reshape(-1, 3).mean(axis=0) * 0.55, (H, W, 1)).astype(np.float32)
        for (a, b), lv in levels.items():
            # THIN OUT (Tyson 2026-07-18): the run tapers like a comet —
            # full band height at the head, thinning toward the tail. Kills
            # the square-block read; dim cells become slivers of light.
            ch_full = by1 - by0
            ch = max(2, int(round(ch_full * (0.30 + 0.70 * lv))))
            cy0 = by0 + (ch_full - ch) // 2
            cw = b - a
            sw = np.array(Image.fromarray((sprite_wt * 255).astype(np.uint8))
                          .resize((cw, ch), Image.LANCZOS)).astype(np.float32) / 255.0
            sc = np.array(Image.fromarray(sprite_rgb.astype(np.uint8))
                          .resize((cw, ch), Image.LANCZOS)).astype(np.float32)
            # Measured separator: a SHALLOW dip (~50% depth, ~1 final px) at
            # each cell boundary — cells read as units but never fuse.
            xs_c = np.arange(cw, dtype=np.float32)
            edge = 0.60 + 0.40 * np.clip(np.minimum(xs_c, cw - 1 - xs_c) / (0.10 * pitch), 0.0, 1.0)
            # A dim diode is dim TEAL, not transparent: the ramp lives mostly
            # in the COLOUR; coverage stays near-solid so tail cells read as
            # lit units instead of stains on the metal.
            E[cy0:cy0 + ch, a:b] = sw * edge[None, :] * (0.88 + 0.12 * lv)
            C[cy0:cy0 + ch, a:b] = sc * (0.30 + 0.70 * lv)
        # Real diode light blooms — a soft halo melts each cell's hard edge
        # without erasing the separators.
        Eim = Image.fromarray(np.clip(E * 255, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.3))
        E = np.maximum(E * 0.95, np.array(Eim).astype(np.float32) / 255.0)
        # EMBEDDED, not pasted (Tyson 2026-07-18): the drum owns the light.
        # THIS frame's teeth ride dark over the glow (the fins occlude the
        # lamp and scroll through it as the wheel turns), and the cylinder's
        # own seat shading dims the glow into the socket/contact shadows.
        lum = c[..., :3].mean(axis=2) / 255.0
        band_rows = row_profile > 0.35
        colbright = (lum * a_mask)[band_rows, :].max(axis=0)
        toothness = np.clip(colbright / max(float(colbright.max()), 1e-4), 0.0, 1.0)
        # RELIGHT, don't composite (method change 2026-07-18, 'still pasted'):
        # the lamp is UNDER the drum. Gaps TRANSMIT the light; fin tops facing
        # it CATCH a dimmer teal reflection scaled by the metal's own specular
        # (lum) — so the drum's geometry modulates the light both ways and the
        # metal texture always survives underneath (screen blend, not replace).
        E_trans = E * (1.0 - 0.62 * toothness)[None, :]
        E_refl = E * (toothness[None, :] * lum * 0.50)
        Eall = (E_trans + E_refl) * np.clip(vshade, 0.25, 1.0)[:, None]
        amp = 0.88 * min(1.0, v * 12.0)                                # frame 0 = no glow
        caps = np.clip(np.minimum(x - x0, x1 - x) / (0.06 * raw_w), 0.0, 1.0) ** 2
        E = Eall * amp * caps[None, :] * a_mask
        k = E[..., None]
        rgb = np.clip(rgb + C * k * (1.0 - rgb / 255.0), 0, 255)  # screen: add light, keep metal
        cols = E.sum(axis=0)
        glow_centroids.append(float((cols * np.arange(W)).sum() / max(cols.sum(), 1e-6)))
        lit = E > 0.75
        glow_peak_rgb.append(rgb[lit].mean(axis=0) if np.any(lit) else np.zeros(3))

    a = np.dstack([np.clip(rgb, 0, 255), c[..., 3:4]])
    img = Image.fromarray(a.astype(np.uint8))
    img = img.crop((x0, y0, x1 + 1, y1 + 1))
    img = img.resize((drum_w, DRUM_H), Image.LANCZOS)
    fr = Image.new("RGBA", (FW, FH), (0, 0, 0, 0))
    fr.paste(img, ((FW - drum_w) // 2, GAP_TOP), img)
    frames.append(np.array(fr))

strip = np.concatenate(frames, axis=1)
Image.fromarray(strip).save(OUT / "trench_roller_strip.png")
print("strip:", strip.shape, "->", OUT / "trench_roller_strip.png")

# Law checks: no glow at v=0; the packet tracks value; brightest pixels
# stay chromatic instead of clipping toward white.
print(f"v=0 glow energy {glow_peak_rgb[0].max():.2f} (law: 0, dark at rest)")
for f in (64, 128, 192, 256):
    centroid = (glow_centroids[f] - x0) / raw_w
    peak = glow_peak_rgb[f]
    chroma = peak.max() - peak.min()
    print(f"v={f/(NF-1):.2f}  lit centroid={centroid:.2f}  "
          f"bright RGB={peak.round().astype(int)} chroma={chroma:.0f}")
