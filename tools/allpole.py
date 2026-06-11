#!/usr/bin/env python3
"""allpole — mathematically exact ALL-POLE bodies (zeros banished: zero_r=0 ->
b1=b2=0, pure 2nd-order resonators). Three clean designs, packed + audited + plotted.

    python tools/allpole.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.author_lanes import lane_words            # noqa: E402
from pyruntime import trench_ffi                      # noqa: E402
from pyruntime.packed_interp import kernel_to_biquad  # noqa: E402

SR = 39062.5
NY = SR / 2.0
FREQS = np.logspace(math.log10(30.0), math.log10(18000.0), 512)
LABELS = (("A", "M0_Q0"), ("B", "M100_Q0"), ("C", "M0_Q100"), ("D", "M100_Q100"))


def P(p_hz, p_r, gain=1.0):
    """One ALL-POLE section: zero radius 0 -> pure resonator, no zero."""
    return {"pole_hz": float(max(20.0, min(NY * 0.99, p_hz))), "pole_r": float(min(p_r, 0.9985)),
            "zero_hz": NY, "zero_r": 0.0, "gain": float(gain)}


def r_from_bw(bw_hz):
    return math.exp(-math.pi * bw_hz / SR)


def _mag(lanes):
    w = 2 * math.pi * FREQS / SR; z1 = np.exp(-1j * w); z2 = z1 * z1
    h = np.ones_like(z1)
    for l in lanes:
        wp = 2 * math.pi * min(l["pole_hz"], NY * 0.999) / SR
        a1, a2 = -2 * l["pole_r"] * math.cos(wp), l["pole_r"] ** 2
        h = h * (l["gain"] / (1.0 + a1 * z1 + a2 * z2))     # all-pole: numerator = gain
    return np.abs(h)


def normalize(corners, target_db=12.0):
    """One scalar over all corners' lanes (^1/6 each) so the loudest corner peaks at target."""
    peak = max(float(np.max(_mag(lanes))) for lanes in corners.values())
    s = (10.0 ** (target_db / 20.0) / max(peak, 1e-9)) ** (1.0 / 6.0)
    for lanes in corners.values():
        for l in lanes:
            l["gain"] *= s
    return corners


def pack(corners):
    bank = {k: [lane_words(l) for l in corners[lab]] for k, lab in LABELS}
    return trench_ffi.body_bytes_from_corner_words(bank)


# ── 1. ALL-POLE KLATT VOWEL  /a/ -> /i/ ──────────────────────────────────────
def vowel():
    A_F = [150, 730, 1090, 2440, 3300, 3850]; A_BW = [90, 130, 70, 160, 250, 200]
    I_F = [150, 270, 2290, 3010, 3300, 3850]; I_BW = [90, 52, 200, 400, 250, 200]
    broad = 3.2
    def lanes(F, BW, q):  # q=0 broad, q=1 sharp
        return [P(f, r_from_bw(bw * (broad - (broad - 1.0) * q))) for f, bw in zip(F, BW)]
    return normalize({"M0_Q0": lanes(A_F, A_BW, 0), "M100_Q0": lanes(I_F, I_BW, 0),
                      "M0_Q100": lanes(A_F, A_BW, 1), "M100_Q100": lanes(I_F, I_BW, 1)})


# ── 2. ALL-POLE RESONANT LOWPASS (ladder form), cutoff 220 -> 6000 ───────────
def ladder():
    steps = [1.0, 0.74, 0.55, 0.41, 0.30, 0.22]            # poles below cutoff
    def lanes(fc, q):
        out = []
        for i, k in enumerate(steps):
            r = (0.985 if i == 0 else 0.80) if q else (0.92 if i == 0 else 0.72)
            out.append(P(fc * k, r))
        return out
    return normalize({"M0_Q0": lanes(220, 0), "M100_Q0": lanes(6000, 0),
                      "M0_Q100": lanes(220, 1), "M100_Q100": lanes(6000, 1)})


# ── 3. ALL-POLE HARMONIC TUBE, fundamental 120 -> 300 (length morph) ─────────
def tube():
    def lanes(f0, q):
        r = 0.992 if q else 0.965
        return [P(n * f0, r) for n in range(1, 7)]
    return normalize({"M0_Q0": lanes(120, 0), "M100_Q0": lanes(300, 0),
                      "M0_Q100": lanes(120, 1), "M100_Q100": lanes(300, 1)})


def main():
    out = ROOT / "dev" / "tmp" / "allpole"; out.mkdir(parents=True, exist_ok=True)
    designs = [("allpole_vowel_a_i", vowel()), ("allpole_ladder_lp", ladder()), ("allpole_tube", tube())]
    fig, axs = plt.subplots(1, 3, figsize=(13, 3.6), facecolor="#0d0e11")
    for ax, (name, corners) in zip(axs, designs):
        body = pack(corners)
        (out / f"{name}.body240").write_bytes(body)
        maxr = max(float(trench_ffi.packed_probe(body, m / 8.0, q / 8.0)["max_pole_radius"])
                   for q in range(9) for m in range(9))
        # plot the morph sweep at Q100 (true engine path)
        ax.set_facecolor("#15171b")
        for t in np.linspace(0, 1, 9):
            rows = trench_ffi.packed_interpolate(body, float(t), 1.0)
            w = 2 * np.pi * FREQS / SR; z1 = np.exp(-1j * w); z2 = z1 * z1
            h = np.ones_like(z1)
            for r in rows:
                b0, b1, b2, a1, a2 = kernel_to_biquad(r); h = h * ((b0 + b1 * z1 + b2 * z2) / (1 + a1 * z1 + a2 * z2))
            col = (0.37 + 0.54 * t, 0.68 - 0.11 * t, 0.43 - 0.20 * t)
            ax.semilogx(FREQS, 20 * np.log10(np.maximum(np.abs(h), 1e-9)), color=col,
                        lw=1.6 if t in (0, 1) else 0.7)
        ax.set_xlim(30, 18000); ax.set_ylim(-40, 30); ax.axhline(0, color="#d6564c", lw=0.6)
        ax.set_title(f"{name}   maxR {maxr:.4f}", color="#c4cad2", fontsize=9)
        ax.tick_params(colors="#878d97", labelsize=7)
        for s in ax.spines.values():
            s.set_color("#24272d")
        print(f"  {name}: maxR {maxr:.4f} {'STABLE' if maxr < 1 else 'UNSTABLE'} -> {out / (name + '.body240')}")
    fig.suptitle("ALL-POLE bodies (zeros banished) — Q=100 morph sweep", color="#e8923a", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out / "allpole_sheet.png", dpi=120, facecolor="#0d0e11")
    print(f"\nwrote {out / 'allpole_sheet.png'}")


if __name__ == "__main__":
    main()
