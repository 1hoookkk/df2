import numpy as np
from PIL import Image
from pathlib import Path

S = 2  # C++ consumes the complete 12x94 source frame and fits it at draw time.
FW, FH, NF = 6 * S, 47 * S, 64   # a tad thinner again (true 4386 slimness)

frames = []
for i in range(NF):
    v = i / (NF - 1)
    f = np.zeros((FH, FW, 3), dtype=np.float32)

    # Band center marches from bottom to top
    yb = (0.85 - 0.765 * v) * FH
    core, shoulder = 2.5 * S, 5.0 * S

    # THE REFERENCE SPINS: measured off BITMAP4388, the rib phase alternates
    # one source pixel per frame (even-lit / odd-lit), so dragging reads as
    # real drum rotation while the band marches.
    rib_offset = (i % 2) * S
    for ry in range(rib_offset, FH, 2 * S):
        t = (ry + 0.5 * S) / FH

        # Envelope (brightness of ribs from top to bottom)
        # Sharp catch-light in the top 3rd, fading into deep shadow
        if t < 0.1:
            e = 0.2 + 0.8 * (t / 0.1)
        elif t < 0.4:
            e = 1.0 - 0.5 * ((t - 0.1) / 0.3)
        else:
            e = 0.5 - 0.45 * ((t - 0.4) / 0.6)

        # Travelling dark band (value marker)
        dy = abs((ry + 0.5 * S) - yb)
        if dy <= core:
            e *= 0.05
        elif dy <= shoulder:
            fade = (dy - core) / (shoulder - core)
            e *= fade + 0.05 * (1.0 - fade)

        # Bright metallic silver with a very slight warm tint
        lum = 230.0 / 255.0 * e

        # Draw the ribbed drum
        for x in range(1 * S, 4 * S):
            k = 1.0 - 0.4 * ((x - 1*S) / (3*S)) # Curve shading to right
            if x == 1 * S: k *= 0.75 # Separate from the left rim
            f[ry:ry + S, x] = (lum * k, lum * k * 0.98, lum * k * 0.92)

    # Left rim highlight (plastic cutout edge/bevel)
    for y in range(FH):
        t = y / FH
        rim_lum = 0.4 + 0.4 * np.sin(t * np.pi)
        if t < 0.05: rim_lum *= (t / 0.05)
        if t > 0.95: rim_lum *= ((1.0 - t) / 0.05)
        f[y, 0:S] = (rim_lum, rim_lum * 0.96, rim_lum * 0.90)

    # Right-side dark shadow column (cutout depth)
    f[:, 4*S:FW] = (0.02, 0.02, 0.02)

    # Inner top and bottom caps of the cutout (darkening the edges)
    f[0:S, :] *= 0.2
    f[FH-S:, :] *= 0.2

    frames.append((np.clip(f, 0, 1) * 255).astype(np.uint8))

strip = np.concatenate(frames, axis=1)
# Solid alpha channel so it completely blocks the beige plate!
rgba = np.dstack([strip, np.full(strip.shape[:2], 255, np.uint8)])

OUT = Path(r"C:\Users\hooki\df2-workstation\plugin\assets\thin_wheel_strip.png")
Image.fromarray(rgba).save(OUT)
print("Saved thin wheel strip", OUT)
