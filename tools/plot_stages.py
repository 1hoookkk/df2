"""Stage plots from packed words — the approved first-principles verdict sheets.

Pipeline (the ONLY legal one): 240-byte packed body -> corners A/B/C/D ->
pyruntime.packed_interp.packed_bilinear (real trench-core lerp_u16 via FFI)
-> kernel_to_biquad -> H_i(z) at SR 39062.5. No reductions, no surrogates.

Usage:
  python tools/plot_stages.py P2k_013_talking_hedz            # both sheets
  python tools/plot_stages.py P2k_004_meaty_gizmo --mode per_stage
Outputs: dev/tmp/stage_plots/<body>_{per_stage,overlay}.png
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pyruntime import packed_interp as pi

SR = 39062.5
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "dev", "tmp", "stage_plots")

POSITIONS = [
    ("M0 Q0", 0.0, 0.0, "#1f77b4"),
    ("M100 Q0", 1.0, 0.0, "#d62728"),
    ("M0 Q100", 0.0, 1.0, "#2ca02c"),
    ("M100 Q100", 1.0, 1.0, "#9467bd"),
    ("M50 Q50", 0.5, 0.5, "black"),
]
LANE_COLORS = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd", "#8c564b"]


def load_body(body: str) -> dict:
    pat = os.path.join(ROOT, "ref", "p2k_variants", body, "variant_0_*.bin")
    hits = glob.glob(pat)
    if not hits:
        # also accept a direct path to any 240-byte body
        if os.path.isfile(body) and os.path.getsize(body) == 240:
            hits = [body]
        else:
            raise SystemExit(f"no body found: {pat}")
    raw = open(hits[0], "rb").read()
    assert len(raw) == 240, f"{hits[0]}: {len(raw)} bytes != 240"
    w = np.frombuffer(raw, dtype="<u2").reshape(4, 6, 5)
    return {k: [tuple(int(x) for x in w[c, s]) for s in range(6)] for c, k in enumerate("ABCD")}


def freq_grid():
    f = np.geomspace(20, 19000, 800)
    z1 = np.exp(-1j * 2 * np.pi * f / SR)
    return f, z1, z1 * z1


def stage_response(row, z1, z2):
    b0, b1, b2, a1, a2 = pi.kernel_to_biquad(row)
    return (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)


def db(x):
    return 20 * np.log10(np.maximum(np.abs(x), 1e-9))


def sheet_per_stage(body: str, cw: dict, path: str) -> None:
    f, z1, z2 = freq_grid()
    rows_at = {lb: pi.packed_bilinear(cw, m, q) for lb, m, q, _ in POSITIONS}
    fig, axes = plt.subplots(6, 1, figsize=(11, 22), sharex=True)
    for s in range(6):
        ax = axes[s]
        for lb, m, q, c in POSITIONS:
            H = stage_response(rows_at[lb][s], z1, z2)
            ax.semilogx(f, db(H), lw=1.8 if lb == "M50 Q50" else 1.2, color=c, label=lb)
        ax.axhline(0, color="#999999", lw=0.7)
        ax.set_ylim(-40, 40)
        ax.set_ylabel("dB")
        ax.set_title(f"STAGE {s + 1}", loc="left")
        ax.grid(True, which="both", lw=0.3, color="#dddddd")
    axes[0].legend(ncol=5, fontsize=9, loc="upper left")
    axes[-1].set_xlabel("Hz")
    fig.suptitle(f"{body} — per stage, corners + center", y=0.9995)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def sheet_overlay(body: str, cw: dict, path: str) -> None:
    f, z1, z2 = freq_grid()
    fig, axes = plt.subplots(5, 1, figsize=(11, 20), sharex=True)
    for ax, (lb, m, q, _) in zip(axes, POSITIONS):
        rows = pi.packed_bilinear(cw, m, q)
        prod = np.ones_like(z1)
        for s, row in enumerate(rows):
            H = stage_response(row, z1, z2)
            prod = prod * H
            ax.semilogx(f, db(H), lw=1.0, color=LANE_COLORS[s], label=f"stage {s + 1}")
        ax.semilogx(f, db(prod), lw=2.5, color="black", label="cascade")
        ax.axhline(0, color="#999999", lw=0.7)
        ax.set_ylim(-45, 40)
        ax.set_ylabel("dB")
        ax.set_title(f"{body} — {lb}", loc="left")
        ax.grid(True, which="both", lw=0.3, color="#dddddd")
    axes[0].legend(ncol=7, fontsize=8, loc="upper left")
    axes[-1].set_xlabel("Hz")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("body", nargs="?", default="P2k_013_talking_hedz")
    ap.add_argument("--mode", choices=["per_stage", "overlay", "both"], default="both")
    args = ap.parse_args()

    plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white",
                         "font.size": 11, "axes.titlesize": 12})
    os.makedirs(OUT_DIR, exist_ok=True)
    cw = load_body(args.body)
    name = os.path.basename(args.body).replace(".bin", "")
    if args.mode in ("per_stage", "both"):
        p = os.path.join(OUT_DIR, f"{name}_per_stage.png")
        sheet_per_stage(name, cw, p)
        print(p)
    if args.mode in ("overlay", "both"):
        p = os.path.join(OUT_DIR, f"{name}_overlay.png")
        sheet_overlay(name, cw, p)
        print(p)


if __name__ == "__main__":
    main()
