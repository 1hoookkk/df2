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
# LIGHT PATTERN (X3 dump): a stationary warm pool left-of-centre the teeth
# scroll through, ends falling dark, gentle facet contrast. Restrained —
# "too much light shining" killed the first pass.
#
# GLOW (X3 dump law): ONE continuous travelling packet that follows the value
# 0-100 — crisp front, short tail, centred exactly at the value position,
# shining through the fin gaps. The Blender diode pass is only the per-frame
# gap GATE; its discrete cells and baked long tail are discarded. Dark at
# v=0; the packet rides to the right cap at v=1. A light horizontal bloom
# binds the gap cells into one body of light — never discrete LEDs, never a
# dull halo.
#
# ROTATION LAW: the authored drum turns in the same perceived left-to-right
# direction as the value packet. The Blender batch's frame order is opposite
# to that screen-space travel, so source frames are read in reverse while the
# parameter/glow head continues forward from v=0 to v=1.
import numpy as np
from PIL import Image, ImageFilter
from pathlib import Path

NF = 257
FW, FH = 150, 34
DRUM_H = 30
GAP_TOP = 3

GLOW_ON = True
# The glow is DEEP SAGE/TEAL — light living in the fin gaps, not a pale stripe.
# Pixels lerp toward a dark chromatic lamp colour, never add toward white.
# MEASURED off the real X3 roller sheet (BITMAP4331): the glow is true CYAN
# (G == B; mean 43,118,118, hot cores toward 229,255,255) lighting WHOLE
# tooth-cells as units — never a wash, never malachite.
GLOW_DEEP = np.array([0.17, 0.46, 0.46], dtype=np.float32)
GLOW_CORE = np.array([0.30, 0.55, 0.55], dtype=np.float32)   # additive hot centre
GAIN = 0.92                      # strong colour replacement, restrained luminance
TEETH_VISIBLE = 14               # teeth across the front face — the trail math anchor

BATCH = Path(r"C:\Users\hooki\df2\dev\tmp\roller_batch_az90")
OUT = Path(r"C:\Users\hooki\df2-workstation\plugin\assets")

def load(p):
    return np.array(Image.open(p).convert("RGBA")).astype(np.float32)

def xblur(arr, sigma):
    im = Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8))
    im = im.resize((im.width, 1), Image.BILINEAR).filter(ImageFilter.GaussianBlur(sigma))
    row = np.array(im).astype(np.float32)[0] / 255.0
    return np.tile(row, (arr.shape[0], 1))

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

# Diode-cell ROW profile, once: union of glow frames says which rows carry
# light. The per-frame GAP mask now comes from the clean frame itself, so the
# glow and the visible tooth rotation can never desync again ("the glow and
# tooth rotate are out of sync", 2026-07-17 — the old code read the Blender
# glow pass with the REVERSED source index while the packet ran forward).
row_profile = None
if GLOW_ON:
    acc = None
    for j in (32, 96, 160, 224):
        gj = np.array(Image.open(BATCH / "glow" / f"f{j:03d}.png").convert("L")).astype(np.float32)
        acc = gj if acc is None else np.maximum(acc, gj)
    row_profile = acc.max(axis=1)
    row_profile = np.clip(row_profile / max(row_profile.max(), 1e-4), 0.0, 1.0) ** 0.5

frames = []
glow_centroids = []
glow_peak_rgb = []
for i in range(NF):
    v = i / (NF - 1)
    source_i = NF - 1 - i
    c = load(BATCH / "clean" / f"f{source_i:03d}.png")
    rgb = c[..., :3]
    H, W = rgb.shape[:2]

    # Fixed material shine: the reference's lamp sits decisively over the left
    # shoulder, not across the wheel centre. This is independent of the teal
    # value packet, which still travels with the parameter.
    xn = np.arange(W, dtype=np.float32) / W
    # METALLIC (Tyson 2026-07-17): a tighter, hotter lamp pool and harder
    # facet contrast — iron reads as sharp light/dark breaks, not soft plastic.
    env = 0.60 + 0.95 * np.exp(-((xn - 0.18) ** 2) / (2 * 0.11 ** 2))
    env *= 0.45 + 0.55 * np.minimum(np.minimum(xn, 1 - xn) / 0.06, 1.0)
    n = np.clip((rgb * env[None, :, None] / 255.0 - 0.04) * 1.38, 0, 1) ** 0.84
    rgb = n * 255.0

    if GLOW_ON:
        # Gate = THIS clean frame's own tooth gaps (dark slots), confined to the
        # diode rows. Glow and tooth rotation share one source, so they cannot
        # desync; the packet centre IS the value position, 0 -> 100.
        # DISCRETE CELLS, not a wash: only the deep tooth-gap slots pass light
        # (hard threshold, then a soft knee), confined to the diode rows. The
        # loose 1-1.6*lum mask lit every mid-dark pixel — "just a spray".
        lum = c[..., :3].mean(axis=2) / 255.0
        a_mask = c[..., 3] / 255.0
        gaps = np.clip((0.30 - lum) / 0.26, 0.0, 1.0) * a_mask
        gate = gaps * (row_profile[:, None] ** 1.5)
        gate = gate / max(gate.max(), 1e-4)
        gate = np.clip((gate - 0.30) / 0.45, 0.0, 1.0)
        # The X3 law (BITMAP4331 sheet): whole cells switch on as units — a
        # run of lit cells ending at the value position, one cell long near
        # zero, widening with the value. Binary per cell, hard-edged.
        head = x0 + v * raw_w
        x = np.arange(W, dtype=np.float32)
        # Cells are the spaces BETWEEN TEETH (bright fin tops in the diode
        # rows), never runs of darkness — dark runs merge across the whole
        # drum and flood the fill. Long tooth-less stretches split at the
        # authored tooth pitch so no cell exceeds one pitch.
        band_rows = row_profile > 0.35
        colbright = (lum * a_mask)[band_rows, :].max(axis=0)
        toothcol = colbright > 0.42
        pitch = raw_w / float(TEETH_VISIBLE)
        cells = []
        run_start = None
        for xx in range(W + 1):
            inside = xx < W and (x0 <= xx <= x1) and not toothcol[xx]
            if inside and run_start is None:
                run_start = xx
            elif not inside and run_start is not None:
                a = run_start
                while xx - a > pitch * 1.3:          # split oversized runs
                    cells.append((a, int(a + pitch)))
                    a = int(a + pitch)
                cells.append((a, xx))
                run_start = None
        lit = np.zeros(W, dtype=np.float32)
        tail = (0.06 + 0.30 * v) * raw_w
        if cells:
            # the cell nearest the head is ALWAYS lit (the value marker)...
            near = min(cells, key=lambda c: abs(0.5 * (c[0] + c[1] - 1) - head))
            lit[near[0]:near[1]] = 1.0
            # ...and the run behind it fills in as the value rises
            for a, b in cells:
                cctr = 0.5 * (a + b - 1)
                if head - tail <= cctr <= head:
                    fall = 1.0 - 0.45 * max(0.0, (head - cctr) / max(tail, 1e-3))
                    lit[a:b] = max(lit[a:b].max(), fall)
        amp = min(1.0, v * 12.0)                                       # frame 0 = no glow
        caps = np.clip(np.minimum(x - x0, x1 - x) / (0.06 * raw_w), 0.0, 1.0) ** 2
        E = gate * lit[None, :] * amp * caps[None, :]
        # a whisper of bloom binds each cell's edges; cells stay discrete
        E = np.clip(E + xblur(E.max(axis=0, keepdims=True) * np.ones_like(E), 3) * gate * 0.10, 0, 1)
        # lerp toward the lamp colour, then an additive hot core where a cell
        # is fully lit — the real sheet's centres run toward white-cyan.
        k = (E * GAIN)[..., None]
        rgb = rgb * (1.0 - k) + GLOW_DEEP[None, None] * 255.0 * k
        rgb = np.clip(rgb + (E ** 3)[..., None] * GLOW_CORE[None, None] * 255.0, 0, 255)
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

# Law checks: no glow at v=0; the teal packet tracks value and its brightest
# pixels stay chromatic instead of clipping toward white.
print(f"v=0 glow energy {glow_peak_rgb[0].max():.2f} (law: 0, dark at rest)")
for f in (64, 128, 192, 256):
    centroid = (glow_centroids[f] - x0) / raw_w
    peak = glow_peak_rgb[f]
    chroma = peak.max() - peak.min()
    print(f"v={f/(NF-1):.2f}  lit centroid={centroid:.2f}  "
          f"bright RGB={peak.round().astype(int)} chroma={chroma:.0f}")
