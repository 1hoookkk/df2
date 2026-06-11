#!/usr/bin/env python3
"""plot_p2k_refs — STUDY plot of all 50 reference P2K presets (ref/presets/*.bin),
full Q=100 morph sweep per cell, through the shipped engine. Reference/study only
(clean-room) — looking for structural patterns, not shipping bytes.

    python tools/plot_p2k_refs.py
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pyruntime import trench_ffi                      # noqa: E402
from pyruntime.packed_interp import kernel_to_biquad  # noqa: E402

SR = 39062.5
FREQS = np.logspace(math.log10(30.0), math.log10(18000.0), 340)
W = 2 * np.pi * FREQS / SR
Z1 = np.exp(-1j * W); Z2 = Z1 * Z1


def sweep_db(body, m, q):
    h = np.ones_like(Z1)
    for r in trench_ffi.packed_interpolate(body, m, q):
        b0, b1, b2, a1, a2 = kernel_to_biquad(r)
        h = h * ((b0 + b1 * Z1 + b2 * Z2) / (1 + a1 * Z1 + a2 * Z2))
    return 20 * np.log10(np.maximum(np.abs(h), 1e-9))


def main():
    files = sorted(Path(ROOT / "ref" / "presets").glob("P2k_*.bin"))
    n = len(files); cols = 5; rows = math.ceil(n / cols)
    fig, axs = plt.subplots(rows, cols, figsize=(cols * 3.0, rows * 1.85), facecolor="#0d0e11")
    for ax in np.atleast_1d(axs).flat:
        ax.axis("off")
    for ax, f in zip(np.atleast_1d(axs).flat, files):
        ax.axis("on"); ax.set_facecolor("#15171b")
        body = f.read_bytes()
        m = re.match(r"P2k_(\d+)_(.+)", f.stem)
        num = int(m.group(1)); short = m.group(2)
        functional = num >= 33
        for j in range(9):
            t = j / 8.0
            col = (0.37 + 0.54 * t, 0.68 - 0.11 * t, 0.43 - 0.20 * t)
            ax.semilogx(FREQS, sweep_db(body, t, 1.0), color=col, lw=1.4 if j in (0, 8) else 0.6,
                        alpha=1.0 if j in (0, 8) else 0.6)
        ax.axhline(0, color="#d6564c", lw=0.5, alpha=0.6)
        ax.set_xlim(30, 18000); ax.set_ylim(-48, 30)
        ax.set_xticks([100, 1000, 10000]); ax.set_xticklabels([])
        ax.tick_params(colors="#878d97", labelsize=5)
        for s in ax.spines.values():
            s.set_color("#3a5a3a" if functional else "#5a3a3a")
        ax.set_title(f"{num:02d} {short}", color="#5fae6e" if functional else "#e8923a", fontsize=7, pad=1)
    fig.suptitle("All 50 reference P2K presets — Q=100 morph sweep  (green title = functional 33–49 · orange = designer 0–32)",
                 color="#c4cad2", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    out = ROOT / "dev" / "tmp" / "p2k_all50.png"
    fig.savefig(out, dpi=115, facecolor="#0d0e11")
    print(f"wrote {out}  ({n} presets)")


if __name__ == "__main__":
    main()
