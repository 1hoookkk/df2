#!/usr/bin/env python3
"""Plot a single .body240 the way the engine plays it.

Uses the canonical runtime path: trench_ffi.packed_interpolate (the DLL's
PackedCorners::interpolate, plot==engine 0.0000 dB) -> kernel_to_biquad ->
cascade magnitude. Judgment view = the four corners + a Q=100 morph sweep
(the "magic in the middle"), per forge-web/CLAUDE.md.

    python tools/plot_body240.py path/to/body.body240 [--out out.png]
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.packed_interp import kernel_to_biquad  # noqa: E402

SR = 39062.5
FREQS = np.logspace(math.log10(30.0), math.log10(18000.0), 512)


def cascade_db(body: bytes, morph: float, q: float) -> np.ndarray:
    rows = trench_ffi.packed_interpolate(body, morph, q)
    w = 2.0 * math.pi * FREQS / SR
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    h = np.ones_like(z1)
    for row in rows:
        b0, b1, b2, a1, a2 = kernel_to_biquad(row)
        num = b0 + b1 * z1 + b2 * z2
        den = 1.0 + a1 * z1 + a2 * z2
        h = h * (num / den)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-9))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("body", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    body = args.body.read_bytes()
    if len(body) != 240:
        print(f"!! expected 240 bytes, got {len(body)}", file=sys.stderr)
        return 2

    out = args.out or args.body.with_suffix(".png")
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(10, 9), facecolor="#0d0e11")
    for ax in (ax0, ax1):
        ax.set_facecolor("#15171b")
        ax.set_xscale("log")
        ax.set_xlim(30, 18000)
        ax.set_ylim(-40, 30)
        ax.axhline(0, color="#d6564c", lw=0.8, alpha=0.7)
        ax.grid(True, which="both", color="#24272d", lw=0.5)
        ax.tick_params(colors="#878d97")
        for s in ax.spines.values():
            s.set_color("#24272d")

    # top: the four corners
    corners = [("M0_Q0", 0, 0, "#5f8fae"), ("M100_Q0", 1, 0, "#ae5f8f"),
               ("M0_Q100", 0, 1, "#5fae6e"), ("M100_Q100", 1, 1, "#e8923a")]
    for name, m, q, c in corners:
        ax0.plot(FREQS, cascade_db(body, m, q), color=c, lw=1.6, label=name)
    ax0.set_title(f"{args.body.name} — four corners", color="#c4cad2", loc="left")
    ax0.legend(facecolor="#15171b", edgecolor="#24272d", labelcolor="#c4cad2", fontsize=8)

    # bottom: Q=100 morph sweep (the interior)
    for t in np.linspace(0, 1, 9):
        shade = 0.30 + 0.65 * t
        ax1.plot(FREQS, cascade_db(body, float(t), 1.0),
                 color=(0.96 * shade, 0.57 * shade, 0.24 * shade), lw=1.3)
    ax1.set_title("Q=100 morph sweep  (M0 → M100, the magic in the middle)",
                  color="#c4cad2", loc="left")
    ax1.set_xlabel("Hz", color="#878d97")

    fig.tight_layout()
    fig.savefig(out, dpi=110, facecolor="#0d0e11")
    print(f"wrote {out}  (DLL: {trench_ffi.lib_path()})")
    # quick stability read
    probes = [trench_ffi.packed_probe(body, m / 8.0, q / 8.0)
              for q in range(9) for m in range(9)]
    maxr = max(float(p["max_pole_radius"]) for p in probes)
    print(f"9x9 grid maxR={maxr:.4f}  ({'STABLE' if maxr < 1.0 else 'UNSTABLE'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
