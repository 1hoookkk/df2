#!/usr/bin/env python3
"""See the body — full cascade response, where the resonances land, across the morph.

No per-stage curves. No z-plane / pole math. Just:
  - THE SHAPE: the full cascade magnitude vs frequency at the two vowel endpoints,
    with each resonance peak marked where it lands on the curve.
  - THE MORPH (manifold): the full cascade response swept across Morph 0->1 as a
    heatmap; the bright ridges are the resonances gliding. Shown all-pole vs
    coupled-cavity side by side so the "EQ bumps vs connected tube" difference is
    visible.

  python tools/body_plots.py
"""
from __future__ import annotations

import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.gridspec import GridSpec  # noqa: E402

from pyruntime import packed_interp as pi  # noqa: E402

RACK = os.path.join(ROOT, "dev", "tmp", "vocal_rack")
TUBE = os.path.join(ROOT, "dev", "tmp", "vocal_rack_tube")
OUT = os.path.join(RACK, "plots")
SR = 39062.5
TAU = 2.0 * math.pi
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
FREQS = np.logspace(math.log10(60.0), math.log10(16000.0), 420)

FIELD = "#0a0d0c"
INK = "#bec5be"
DIMINK = "#69836f"
GREEN = "#5bef6f"
CYAN = "#31c6c9"
AMBER = "#e8a33d"
RED = "#e83d31"


def pole_freq(s):
    """Resonance (pole) frequency of one decoded stage, or None if not resonant."""
    a1, a2 = s[2] - 2.0, 1.0 - s[3]
    r = max(a2, 0.0) ** 0.5
    if r <= 1e-6 or a1 * a1 - 4.0 * a2 >= 0.0:
        return None
    return math.acos(max(-1.0, min(1.0, -a1 / (2.0 * r)))) * SR / TAU


def zero_freq(s):
    """Anti-resonance (zero / notch) frequency of one stage, or None if no real zero."""
    n1, n2 = s[0] - 2.0, 1.0 - s[1]  # b1/b0, b2/b0
    if abs(n1) < 0.02 and abs(n2) < 0.02:
        return None
    rz = max(n2, 0.0) ** 0.5
    if rz <= 1e-6 or n1 * n1 - 4.0 * n2 >= 0.0:
        return None
    return math.acos(max(-1.0, min(1.0, -n1 / (2.0 * rz)))) * SR / TAU


def load_words(path):
    d = json.load(io.open(path, encoding="utf-8"))
    by = {kf["label"]: [tuple(int(x) & 0xFFFF for x in w) for w in kf["packedWords"]] for kf in d["keyframes"]}
    return {LABEL_TO_KEY[lbl]: by[lbl] for lbl in CORNER_ORDER}


def cascade_db(kernels, freqs):
    out = np.empty(len(freqs))
    for i, f in enumerate(freqs):
        w = TAU * f / SR
        mag = 1.0
        for c in kernels:
            b0, b1, b2, a1, a2 = c[4], (c[0] - 2) * c[4], (1 - c[1]) * c[4], c[2] - 2, 1 - c[3]
            cw, c2w, sw, s2w = math.cos(w), math.cos(2 * w), math.sin(w), math.sin(2 * w)
            nr, ni = b0 + b1 * cw + b2 * c2w, -b1 * sw - b2 * s2w
            dr, di = 1 + a1 * cw + a2 * c2w, -a1 * sw - a2 * s2w
            mag *= ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)) ** 0.5
        out[i] = 20.0 * math.log10(mag + 1e-30)
    return out


def response_at(words, morph, q):
    return cascade_db(pi.packed_bilinear(words, morph, q), FREQS)


def find_peaks(curve, min_prom=6.0):
    pk = []
    for i in range(2, len(curve) - 2):
        if curve[i] > curve[i - 1] and curve[i] >= curve[i + 1]:
            lo = min(curve[max(0, i - 25):i]) if i > 0 else curve[i]
            if curve[i] - lo >= min_prom:
                pk.append(i)
    return pk


def waterfall(words, q, steps=90):
    Z = np.empty((steps, len(FREQS)))
    for r in range(steps):
        Z[r] = response_at(words, r / (steps - 1), q)
    return Z


def style_ax(ax):
    ax.set_facecolor(FIELD)
    for s in ax.spines.values():
        s.set_color("#46534b")
    ax.tick_params(colors=INK, labelsize=8)


def plot_body(bid, name, desc):
    ap = load_words(os.path.join(RACK, f"{bid}.cart.json"))
    tb = load_words(os.path.join(TUBE, f"{bid}_tube.cart.json"))

    fig = plt.figure(figsize=(11, 8), facecolor=FIELD)
    gs = GridSpec(2, 2, height_ratios=[1.0, 1.15], hspace=0.32, wspace=0.16)

    # ── THE SHAPE: cascade at the two vowel endpoints, peaks marked ──
    ax = fig.add_subplot(gs[0, :])
    style_ax(ax)
    logf = np.log10(FREQS)
    for morph, color, tag, words in [(0.0, GREEN, "Morph 0 (vowel A)", tb["A"]),
                                     (1.0, CYAN, "Morph 100 (vowel B)", tb["B"])]:
        curve = response_at(tb, morph, 0.0)  # decode the packed corner, then cascade
        ax.plot(FREQS, curve, color=color, lw=1.6, label=tag)
        ax.fill_between(FREQS, curve, curve.min() - 4, color=color, alpha=0.07)
        stages = [pi.words_to_coeffs(tuple(w)) for w in words]
        for s in stages:
            pf = pole_freq(s)
            if pf and 60 < pf < 16000:  # resonance = peak (pole)
                ax.plot(pf, np.interp(math.log10(pf), logf, curve), "o", color=color, ms=6, zorder=5)
            zf = zero_freq(s)
            if zf and 60 < zf < 16000:  # anti-resonance = notch (zero)
                yz = np.interp(math.log10(zf), logf, curve)
                ax.plot(zf, yz, "v", color=RED, mec=color, ms=9, zorder=6)
                ax.text(zf, yz - 7, f"{zf:.0f}", color=RED, fontsize=7, ha="center")
    ax.scatter([], [], marker="o", color=INK, label="resonance (pole)")
    ax.scatter([], [], marker="v", color=RED, label="notch (zero)")
    ax.set_xscale("log")
    ax.set_xlim(60, 16000)
    ax.set_xlabel("frequency (Hz)", color=INK, fontsize=9)
    ax.set_ylabel("level (dB)", color=INK, fontsize=9)
    ax.set_title(f"{name} — the shape (peaks = resonances ·  ▼ = the zeros / notches)", color=GREEN, fontsize=11)
    ax.grid(True, color="#16201b", lw=0.5)
    ax.legend(facecolor="#11150f", edgecolor="#46534b", labelcolor=INK, fontsize=8, loc="upper right", ncol=2)

    # ── THE MORPH: full cascade swept across Morph 0->1 (Q relaxed), all-pole vs coupled ──
    vmin, vmax = -42, 12
    for col, (words, title) in enumerate([(ap, "all-pole  (resonant EQ bumps)"),
                                          (tb, "coupled cavities  (connected tube)")]):
        ax = fig.add_subplot(gs[1, col])
        style_ax(ax)
        Z = waterfall(words, q=0.0)
        morphs = np.linspace(0, 1, Z.shape[0])
        mesh = ax.pcolormesh(FREQS, morphs, np.clip(Z, vmin, vmax), cmap="magma",
                             vmin=vmin, vmax=vmax, shading="auto")
        ax.set_xscale("log")
        ax.set_xlim(60, 16000)
        ax.set_xlabel("frequency (Hz)", color=INK, fontsize=9)
        if col == 0:
            ax.set_ylabel("morph  (0 → 100)", color=INK, fontsize=9)
        ax.set_title(title, color=AMBER, fontsize=10)
        cb = fig.colorbar(mesh, ax=ax, fraction=0.046, pad=0.02)
        cb.ax.tick_params(colors=DIMINK, labelsize=7)

    fig.text(0.5, 0.005, desc, color=DIMINK, fontsize=9, ha="center")
    path = os.path.join(OUT, f"{bid}.png")
    fig.savefig(path, dpi=110, facecolor=FIELD, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_overview(bodies):
    """All six bodies' morph manifolds (coupled) at a glance."""
    fig = plt.figure(figsize=(13, 7.5), facecolor=FIELD)
    gs = GridSpec(2, 3, hspace=0.34, wspace=0.2)
    for n, (bid, name, _desc) in enumerate(bodies):
        tb = load_words(os.path.join(TUBE, f"{bid}_tube.cart.json"))
        ax = fig.add_subplot(gs[n // 3, n % 3])
        style_ax(ax)
        Z = waterfall(tb, q=0.0)
        morphs = np.linspace(0, 1, Z.shape[0])
        ax.pcolormesh(FREQS, morphs, np.clip(Z, -42, 12), cmap="magma", vmin=-42, vmax=12, shading="auto")
        ax.set_xscale("log")
        ax.set_xlim(60, 16000)
        ax.set_title(name, color=GREEN, fontsize=10)
        if n % 3 == 0:
            ax.set_ylabel("morph", color=INK, fontsize=8)
        if n // 3 == 1:
            ax.set_xlabel("Hz", color=INK, fontsize=8)
    fig.suptitle("The rack — every body's manifold (bright ridges = resonances gliding across the morph)",
                 color=GREEN, fontsize=13)
    path = os.path.join(OUT, "overview.png")
    fig.savefig(path, dpi=110, facecolor=FIELD, bbox_inches="tight")
    plt.close(fig)
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    report = json.load(io.open(os.path.join(RACK, "report.json"), encoding="utf-8"))
    bodies = [(bid, b["name"], b["desc"]) for bid, b in report["bodies"].items()]
    print(f"core backend: {pi.core_backend()}")
    paths = []
    for bid, name, desc in bodies:
        p = plot_body(bid, name, desc)
        paths.append(p)
        print(f"  plotted {name} -> {os.path.relpath(p, ROOT)}")
    ov = plot_overview(bodies)
    print(f"  overview -> {os.path.relpath(ov, ROOT)}")

    # plots-first html
    imgs = "".join(
        f"<section><img src='{os.path.basename(p)}' style='width:100%;max-width:1000px'></section>"
        for p in [ov] + paths
    )
    html = (
        "<!doctype html><meta charset=utf-8><title>Vocal rack — plots</title>"
        "<style>body{background:#0a0d0c;color:#bec5be;font:14px/1.6 monospace;margin:20px}"
        "h1{color:#5bef6f}img{display:block;margin:10px 0;border:1px solid #1c2722}.note{color:#69836f}</style>"
        "<h1>The rack — see it</h1>"
        "<p class=note>Top of each body: the full cascade shape at both vowel ends, dots where the "
        "resonances land. Bottom: the same body swept across the morph — left all-pole (spiky EQ "
        "bumps with dead canyons), right coupled cavities (connected, tube-like).</p>"
        + imgs
    )
    open(os.path.join(OUT, "plots.html"), "w", encoding="utf-8").write(html)
    print(f"\nplots -> {os.path.relpath(os.path.join(OUT, 'plots.html'), ROOT)}")


if __name__ == "__main__":
    main()
