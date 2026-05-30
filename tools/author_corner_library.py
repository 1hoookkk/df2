#!/usr/bin/env python3
"""author_corner_library.py — the corner LIBRARY (DATA), organised low/high x open/closed.
All authoring/encoding goes through the owner (corner_author), which composes the canonical
corner_words primitives. This file holds only postures + the plot.
  bp = bright band-peak (rolls off below) · lp = dark (rolls off above) · open=sharp radius
Run:  python tools/author_corner_library.py     (bake both formats + plot)
"""
from __future__ import annotations
import math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from pyruntime.freq_response import cascade_response_db
from tools import corner_author as ca          # THE owner — primitives / compile / encode / write

OUT = ROOT / "dev/tmp/arma_source_pack/corners_audio_only/_authored"
R_CLOSED, R_OPEN = 0.94, 0.985                  # open/closed = pole sharpness (radius)

def post(freqs, fn, r):
    return [fn(f, r) for f in freqs]

LIBRARY = {
    "vox": {k: ca.vowel(k) for k in ("u", "uv", "a", "i")},     # exact Klatt vowels
    "low_closed": {   # low-MID, broad/tame (bp, low radius)
        "round_oo":   post([300, 560, 900], ca.bp, R_CLOSED),
        "back_aw":    post([440, 760, 1150], ca.bp, R_CLOSED),
        "stone_room": post([290, 430, 640, 980], ca.bp, R_CLOSED),
    },
    "low_open": {     # low-MID razor (bp, sharp)
        "razor_low":  post([300, 520, 820, 1400], ca.bp, R_OPEN),
        "acid_303":   post([280, 560, 900, 1600], ca.bp, R_OPEN),
        "bottle_mid": post([357, 619, 1072, 2000], ca.bp, R_OPEN),
    },
    "high_closed": {  # bright, broad/tame (bp, low radius)
        "airy":       post([800, 2400, 4200, 6500], ca.bp, R_CLOSED),
        "soft_bell":  post([520, 1500, 2600, 4000], ca.bp, R_CLOSED),
    },
    "high_open": {    # bright AND razor (bp, sharp)
        "tin_scream": post([1591, 2347, 3283, 4594], ca.bp, R_OPEN),
        "metal_edge": post([2300, 3500, 5200, 7500], ca.bp, R_OPEN),
        "glass":      post([1200, 2800, 4500, 7000], ca.bp, R_OPEN),
    },
    "experimental": {  # golden-ratio comb (40 Hz x 1.61, direct zeros)
        "golden_comb": ca.golden_comb(6),
        "wide_comb":   ca.golden_comb(7),
    },
    "physics": {  # real acoustic models (native in the owner)
        "pipe_30cm":    ca.tube(30.0),
        "pipe_18cm":    ca.tube(18.0),
        "bell_220":     ca.modal("bell", 220.0),
        "plate_300":    ca.modal("plate", 300.0),
    },
}

def plot_library(baked):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pyruntime.encode import EncodedCoeffs
    FP = np.logspace(math.log10(40), math.log10(16000), 600)
    groups = list(baked.items())
    fig, axes = plt.subplots(len(groups), 1, figsize=(11, 2.5 * len(groups)), dpi=120)
    fig.patch.set_facecolor("#0c0f0e")
    cols = ["#ff7a5a", "#ffd24a", "#9aef5a", "#5ad1ff", "#c79bff", "#ff9ad2"]
    for ax, (g, corners) in zip(axes, groups):
        for i, (name, coeffs) in enumerate(corners):
            db = cascade_response_db(coeffs, FP, ca.SR)
            ax.semilogx(FP, db, lw=1.7, color=cols[i % len(cols)], label=name, alpha=.95)
        ax.set_title(g, color="#9aef5a", fontsize=11, loc="left")
        ax.set_xlim(40, 16000); ax.set_ylim(-40, 24); ax.grid(alpha=.13)
        ax.axhline(0, color="#445", lw=.8)
        ax.set_facecolor("#0c0f0e"); ax.tick_params(colors="#9aa", labelsize=7)
        ax.set_ylabel("dB", color="#9aa")
        ax.legend(facecolor="#0c0f0e", edgecolor="#33433c", labelcolor="#cfe9dc", fontsize=7, ncol=6, loc="upper right")
        for sp in ax.spines.values(): sp.set_color("#33433c")
    axes[-1].set_xlabel("Hz", color="#9aa")
    fig.tight_layout(); fig.savefig(OUT / "library.png"); plt.close(fig)
    (OUT / "library.html").write_text(
        '<!doctype html><meta charset=utf-8><title>corner library</title>'
        '<body style="background:#0c0f0e;color:#e5dccb;font-family:system-ui;margin:18px">'
        '<h1 style="color:#9aef5a">Corner library — direct pole-zero (bp/lp/formant), via the owner</h1>'
        '<img src="library.png" style="width:100%;max-width:1100px"></body>', encoding="utf-8")

if __name__ == "__main__":
    baked, skipped = {}, []
    for group, corners in LIBRARY.items():
        for name, stages in corners.items():
            coeffs, words, rep = ca.write_corner(stages, name, group)
            if not rep["ok"]:
                skipped.append(f"{group}/{name} {rep}"); continue
            baked.setdefault(group, []).append((name, coeffs))
    n = sum(len(v) for v in baked.values())
    plot_library(baked)
    print(f"authored {n} postures (both formats) -> {OUT}")
    for g, v in baked.items():
        print(f"  _authored/{g}/  ({len(v)})")
    for s in skipped:
        print(f"  !! SKIP {s}")
