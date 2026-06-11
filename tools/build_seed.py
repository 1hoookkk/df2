#!/usr/bin/env python3
"""build_seed — author GPT's 'violent mouth / reece bender' 4-corner seed VERBATIM,
pack it, and MEASURE it against its own targets (morph-motion >=17 dB, Q-pressure
>=10 dB, 6 active zeros, stable). Verify the recipe through the engine — don't trust it.

    python tools/build_seed.py
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
FREQS = np.logspace(math.log10(60.0), math.log10(16000.0), 400)
W = 2 * np.pi * FREQS / SR; Z1 = np.exp(-1j * W); Z2 = Z1 * Z1


def L(ph, pr, zh, zr, gdb):
    return {"pole_hz": ph, "pole_r": pr, "zero_hz": zh, "zero_r": zr, "gain": 10.0 ** (gdb / 20.0)}


# GPT's verbatim tables. Corner map: HOME=M0_Q0, AWAY=M100_Q0, TIGHT HOME=M0_Q100, TIGHT AWAY=M100_Q100
HOME = [L(72, .984, 38, .998, -2), L(360, .990, 900, .996, 1), L(1050, .989, 620, .995, 0),
        L(2300, .986, 1650, .996, -1), L(4100, .982, 3300, .995, -2), L(8700, .975, 12500, .995, -4)]
AWAY = [L(125, .986, 54, .998, -1), L(760, .992, 480, .997, 2), L(2100, .991, 1350, .997, 2),
        L(3650, .990, 2800, .997, 1), L(6100, .989, 4700, .997, 0), L(11800, .982, 9200, .996, -3)]
THOME = [L(72, .990, 50, .999, -5), L(360, .996, 900, .999, -2), L(1050, .996, 620, .998, -2),
         L(2300, .994, 1650, .999, -3), L(4100, .992, 3300, .998, -4), L(8700, .986, 12500, .997, -6)]
TAWAY = [L(125, .991, 65, .999, -5), L(760, .997, 480, .999, -1), L(2100, .997, 1350, .999, -1),
         L(3650, .9965, 2800, .999, -2), L(6100, .996, 4700, .9985, -3), L(11800, .990, 9200, .998, -5)]


def mag(body, m, q):
    h = np.ones_like(Z1)
    for r in trench_ffi.packed_interpolate(body, m, q):
        b0, b1, b2, a1, a2 = kernel_to_biquad(r)
        h = h * ((b0 + b1 * Z1 + b2 * Z2) / (1 + a1 * Z1 + a2 * Z2))
    return 20 * np.log10(np.maximum(np.abs(h), 1e-9))


def rms(a):
    return float(np.sqrt(np.mean(a ** 2)))


def main():
    bank = {"A": [lane_words(l) for l in HOME], "B": [lane_words(l) for l in AWAY],
            "C": [lane_words(l) for l in THOME], "D": [lane_words(l) for l in TAWAY]}
    body = trench_ffi.body_bytes_from_corner_words(bank)
    out = ROOT / "dev" / "tmp" / "seed"; out.mkdir(parents=True, exist_ok=True)
    (out / "violent_mouth_reece.body240").write_bytes(body)

    m00, m10, m01, m11 = mag(body, 0, 0), mag(body, 1, 0), mag(body, 0, 1), mag(body, 1, 1)
    morph = 0.5 * (rms(m01 - m11) + rms(m00 - m10))
    qp = 0.5 * (rms(m00 - m01) + rms(m10 - m11))
    rows = trench_ffi.packed_interpolate(body, 0.0, 1.0)
    nz = sum(1 for r in rows if abs(kernel_to_biquad(r)[1]) + abs(kernel_to_biquad(r)[2]) > 1e-6)
    maxr = max(float(trench_ffi.packed_probe(body, m / 8.0, q / 8.0)["max_pole_radius"])
               for q in range(9) for m in range(9))
    pk = float(max(c.max() for c in (m00, m10, m01, m11)))

    print("=== violent_mouth_reece — measured vs GPT's targets ===")
    print(f"  morph-motion : {morph:5.1f} dB   (target >=17, good 18-30)   {'PASS' if morph>=17 else 'LOW'}")
    print(f"  Q-pressure   : {qp:5.1f} dB   (target >=10, good 10-22)   {'PASS' if qp>=10 else 'LOW'}")
    print(f"  active zeros : {nz}        (target 6)                  {'PASS' if nz==6 else 'CHECK'}")
    print(f"  max pole r   : {maxr:.4f}  (target <1.0, <0.999 normal) {'STABLE' if maxr<1 else 'UNSTABLE'}")
    print(f"  peak mag     : {pk:5.1f} dB   (no >+48 pileup)            {'OK' if pk<48 else 'HOT'}")

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8), facecolor="#0d0e11")
    for ax in (a1, a2):
        ax.set_facecolor("#15171b"); ax.set_xlim(60, 16000); ax.set_ylim(-42, 30)
        ax.axhline(0, color="#d6564c", lw=0.6); ax.tick_params(colors="#878d97", labelsize=7)
        for s in ax.spines.values():
            s.set_color("#24272d")
    for c, col, lab in [(m00, "#5fae6e", "HOME"), (m10, "#e8923a", "AWAY"),
                        (m01, "#3a8a5a", "TIGHT HOME"), (m11, "#b06a28", "TIGHT AWAY")]:
        a1.semilogx(FREQS, c, color=col, lw=1.4, label=lab)
    a1.legend(facecolor="#15171b", edgecolor="#24272d", labelcolor="#c4cad2", fontsize=7)
    a1.set_title("four corners", color="#c4cad2", fontsize=9)
    for t in np.linspace(0, 1, 11):
        col = (0.37 + 0.54 * t, 0.68 - 0.11 * t, 0.43 - 0.20 * t)
        a2.semilogx(FREQS, mag(body, float(t), 1.0), color=col, lw=1.5 if t in (0, 1) else 0.7)
    a2.set_title(f"Q=100 morph sweep   morph-motion {morph:.1f} dB · Q-pressure {qp:.1f} dB · maxR {maxr:.4f}", color="#c4cad2", fontsize=9)
    fig.tight_layout(); fig.savefig(out / "violent_mouth_reece.png", dpi=120, facecolor="#0d0e11")
    print(f"\nwrote {out / 'violent_mouth_reece.png'}  +  .body240")


if __name__ == "__main__":
    main()
