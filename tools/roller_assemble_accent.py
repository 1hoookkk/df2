# Assemble the TRENCH roller filmstrip from the ACCENT diode batch
# (df2/dev/tmp/roller_batch_accent, rendered by roller_accent_batch.py).
#
# Successor to roller_assemble_compact.py: the glow is no longer painted —
# it is REAL Cycles light from emissive diodes inside the drum, fins gating,
# in the face accent #2BD8C3, already driven by the measured X3 4331 laws
# (saturating span, tail->head ramp) at render time. This script only:
#   seat + metal tone (the approved 07-18 passes) -> additive glow -> crop.
# Rotation reversal is baked into the batch (clean f_i uses the reversed
# source rotation), so clean and glow share index i — desync impossible.
import os

import numpy as np
from PIL import Image
from pathlib import Path

NF = 257
SOURCE_SCALE = 2
FW, FH = 150 * SOURCE_SCALE, 34 * SOURCE_SCALE
DRUM_H = 30 * SOURCE_SCALE
GAP_TOP = 3 * SOURCE_SCALE

BATCH = Path (os.environ.get ("TRENCH_ROLLER_BATCH",
                              r"C:\Users\hooki\df2\dev\tmp\roller_batch_accent"))
OUT = Path (os.environ.get ("TRENCH_ROLLER_OUT",
                            r"C:\Users\hooki\df2-workstation\plugin\assets"))

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
print(f"raw drum {raw_w}x{raw_h} -> {drum_w}x{DRUM_H}, frame {FW}x{FH}")

frames = []
glow_centroids = []
glow_peak_rgb = []
for i in range(NF):
    v = i / (NF - 1)
    c = load(BATCH / "clean" / f"f{i:03d}.png")
    rgb = c[..., :3].copy()
    H, W = rgb.shape[:2]

    # Keep the rendered clean layer's own material.  It already contains the
    # authored body lighting; rebuilding a second plate-lighting ramp here
    # makes the drum sink into the black aperture and hides its front face.

    # REAL glow, additive: the pass already carries span/ramp/occlusion.
    # amp gates the always-lit head diode to zero at rest (X3: dark at v=0);
    # caps keep the end caps dark like the reference drum.
    g = load(BATCH / "glow" / f"f{i:03d}.png")[..., :3]
    amp = min(1.0, v * 12.0)
    x = np.arange(W, dtype=np.float32)
    caps = np.clip(np.minimum(x - x0, x1 - x) / (0.06 * raw_w), 0.0, 1.0) ** 2
    g = g * amp * caps[None, :, None] * (c[..., 3:4] / 255.0)
    rgb = np.clip(rgb + g, 0, 255)

    E = g.max(axis=2) / 255.0
    cols = E.sum(axis=0)
    glow_centroids.append(float((cols * np.arange(W)).sum() / max(cols.sum(), 1e-6)))
    lit = E > 0.45
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

print(f"v=0 glow energy {glow_peak_rgb[0].max():.2f} (law: 0, dark at rest)")
for f in (64, 128, 192, 256):
    centroid = (glow_centroids[f] - x0) / raw_w
    peak = glow_peak_rgb[f]
    print(f"v={f/(NF-1):.2f}  lit centroid={centroid:.2f}  "
          f"bright RGB={peak.round().astype(int)} chroma={peak.max()-peak.min():.0f}")
