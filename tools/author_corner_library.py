#!/usr/bin/env python3
"""author_corner_library.py — the corner LIBRARY (DATA), organised by axis. Every bit of
authoring/compiling/encoding is delegated to the ONE owner, tools/corner_author.py — this
file holds only the postures and the plot. (The duplicated compiler that used to live here
is gone; the doctrine is enforced in corner_author as invariants.)

Each posture is written in BOTH formats by the owner:
  <group>/<name>.corner.json  — Forge well (the Forge recursively scans this tree)
  <group>/<name>.body240      — the verbatim 240-byte body (posture replicated x4)

Axes: LOW<->HIGH = where the constellation sits; CLOSED<->OPEN = damped/wide vs razor.
Run:  python tools/author_corner_library.py     (bake both formats + plot)
"""
from __future__ import annotations
import math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from tools import corner_author as ca          # THE owner — author / compile / encode / write

SR = ca.SR
OUT = ROOT / "dev/tmp/arma_source_pack/corners_audio_only/_authored"

def stk(freqs, bw, gain, tilt=0.0):
    """design postures (cavity/tube/modal): uniform Bw/gain + slight up-tilt (balance rule).
    NOT for vowels — vowels use ca.vowel() (exact F+B, gain derived from Bw, coupling)."""
    f0 = freqs[0]
    return [ca.PK(f, bw, round(gain + tilt * math.log2(f / f0), 1)) for f in freqs]

C_BW, C_G = 0.9, 7.0    # CLOSED = wide / modest
O_BW, O_G = 0.30, 12.0  # OPEN   = narrow / hot

# ── THE LIBRARY ──────────────────────────────────────────────────────────────────────
LIBRARY = {
    "vox": {  # EXACT Klatt corner vowels (recipe #1, via the owner) — the vowel-space vertices
        k: ca.vowel(k) for k in ("u", "uv", "a", "i")
    },
    "low_closed": {   # dark, low-MID, damped. NO sub bump — sub passes at unity.
        "round_oo":   stk([300, 560, 900, 2100, 3300], C_BW, 8, tilt=0.6),
        "back_aw":    stk([440, 760, 1150, 2400, 3300], C_BW, 8, tilt=0.5),
        "warm_o":     stk([500, 800, 1200, 2830], C_BW, 8, tilt=0.5),
        "stone_room": stk([290, 430, 640, 980, 1700], 1.0, 7, tilt=0.6),
        "oo50_pipe":  stk([343, 686, 1029, 1372, 1715], C_BW, 7, tilt=0.7),
    },
    "low_open": {     # low-MID razor; sub flat at unity
        "razor_low":  stk([300, 520, 820, 1400, 2400], O_BW, 11, tilt=0.4),
        "acid_303":   stk([280, 560, 900, 1600, 2700], 0.25, 12, tilt=0.3),
        "retroflex":  stk([490, 1090, 1690, 2600], 0.28, 12, tilt=0.0),
        "bottle_mid": stk([357, 619, 1072, 2000, 3200], 0.32, 11, tilt=0.3),
        "beer_glass": stk([536, 928, 1608, 2600], 0.30, 12, tilt=0.2),
    },
    "high_closed": {  # bright but damped/soft (non-vowel bright postures)
        "airy":       stk([800, 2400, 4200, 6500], 1.0, 6, tilt=0.5),
        "soft_bell":  stk([520, 1500, 2600, 4000], C_BW, 7, tilt=0.6),
        "mason_soft": stk([715, 2144, 2768, 3573], 1.0, 7, tilt=0.4),
    },
    "high_open": {    # bright AND razor
        "tin_scream": stk([1591, 2347, 3283, 4594, 6000], 0.28, 11, tilt=0.0),
        "metal_edge": stk([2300, 3500, 5200, 7500], 0.26, 12, tilt=0.0),
        "glass":      stk([1200, 2800, 4500, 7000], O_BW, 12, tilt=0.0),
        "ee_scream":  stk([2290, 3010, 3850, 5500], 0.26, 12, tilt=0.0),
        "oo10_pipe":  stk([1715, 3430, 5145, 6860], 0.28, 11, tilt=0.0),
    },
    "experimental": {  # special TYPES — recipe #3 golden-ratio comb (40 Hz x 1.61)
        "golden_comb": ca.golden_comb(6, -16, 0.20),
        "wide_comb":   ca.golden_comb(6, -12, 0.30),
    },
}

def plot_library(baked):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    FP = np.logspace(math.log10(40), math.log10(16000), 600)
    groups = list(baked.items())
    fig, axes = plt.subplots(len(groups), 1, figsize=(11, 2.5 * len(groups)), dpi=120)
    fig.patch.set_facecolor("#0c0f0e")
    cols = ["#ff7a5a", "#ffd24a", "#9aef5a", "#5ad1ff", "#c79bff", "#ff9ad2"]
    for ax, (g, corners) in zip(axes, groups):
        for i, (name, secs) in enumerate(corners):
            db = cascade_response_db([EncodedCoeffs(*s) for s in secs], FP, SR)
            ax.semilogx(FP, db, lw=1.7, color=cols[i % len(cols)], label=name, alpha=.95)
        ax.set_title(g, color="#9aef5a", fontsize=11, loc="left")
        ax.set_xlim(40, 16000); ax.set_ylim(-26, 20); ax.grid(alpha=.13)
        ax.axhline(0, color="#445", lw=.8)
        ax.set_facecolor("#0c0f0e"); ax.tick_params(colors="#9aa", labelsize=7)
        ax.set_ylabel("dB", color="#9aa")
        ax.legend(facecolor="#0c0f0e", edgecolor="#33433c", labelcolor="#cfe9dc", fontsize=7, ncol=6, loc="upper right")
        for sp in ax.spines.values(): sp.set_color("#33433c")
    axes[-1].set_xlabel("Hz", color="#9aa")
    fig.tight_layout(); fig.savefig(OUT / "library.png"); plt.close(fig)
    html = ['<!doctype html><meta charset=utf-8><title>authored corner library</title>',
            '<style>body{background:#0c0f0e;color:#e5dccb;font-family:system-ui;margin:18px}'
            'h1{color:#9aef5a}img{width:100%;max-width:1100px}.k{color:#9aa;font-size:13px}</style>',
            '<h1>Authored corner library — simple magnitude curves (dB vs log Hz)</h1>',
            '<p class=k>Each curve = one corner POSTURE, authored + compiled + encoded by the single owner '
            '(tools/corner_author.py). Both formats written: .corner.json (Forge) + .body240 (verbatim). '
            'Sub passes at unity (0 dB line) on every one.</p>',
            '<img src="library.png">']
    (OUT / "library.html").write_text("\n".join(html), encoding="utf-8")

if __name__ == "__main__":
    baked, skipped = {}, []
    for group, corners in LIBRARY.items():
        for name, sections in corners.items():
            secs, rep = ca.write_corner(sections, name, group)        # -> .corner.json (Forge)
            if not rep["ok"]:
                skipped.append(f"{group}/{name} {rep}"); continue
            ca.write_body240([secs] * 4, OUT / group / f"{name}.body240")  # -> verbatim 240-byte
            baked.setdefault(group, []).append((name, secs))
    n = sum(len(v) for v in baked.values())
    plot_library(baked)
    print(f"authored {n} postures (both formats) -> {OUT}")
    for g, v in baked.items():
        print(f"  _authored/{g}/  ({len(v)})  .corner.json + .body240")
    for s in skipped:
        print(f"  !! SKIP {s}")
    print(f"plots -> {OUT / 'library.html'}")
