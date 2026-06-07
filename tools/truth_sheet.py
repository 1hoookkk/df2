#!/usr/bin/env python3
"""ONE plot-only truth sheet for ONE original packed body, SHIPPING PACKED PATH only.

Loads a compiled-v1 `packedWords` body, interpolates via
`pyruntime.packed_interp.packed_bilinear` -> trench-core
`trench_packed_interpolate` (PackedCorners::interpolate_biquad, the path the
player runs). No packed:None, no RBJ, no recovered generators, no third-party
coefficients. Adapts the packed plotting in tools/body_plots.py.
"""
import hashlib
import io
import json
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyruntime import packed_interp as pi  # noqa: E402

SRC = os.path.join(ROOT, "bodies", "neon_vane.cart.json")
B240 = os.path.join(ROOT, "bodies", "neon_vane.body240")
OUT = os.path.join(ROOT, "dev", "tmp", "neon_vane_truth_sheet.png")

SR = 39062.5
TAU = 2.0 * math.pi
FREQS = np.logspace(math.log10(60.0), math.log10(16000.0), 420)
L2K = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")

FIELD = "#0a0d0c"; INK = "#bec5be"; GREEN = "#5bef6f"; CYAN = "#31c6c9"
AMBER = "#e8a33d"; RED = "#e83d31"; VIOLET = "#a873ff"


def cascade_db(kernels, freqs):
    out = np.empty(len(freqs))
    for i, f in enumerate(freqs):
        w = TAU * f / SR
        mag = 1.0
        for c in kernels:  # decoded kernel c0..c4 -> biquad b/a (same map as body_plots)
            b0, b1, b2, a1, a2 = c[4], (c[0] - 2) * c[4], (1 - c[1]) * c[4], c[2] - 2, 1 - c[3]
            cw, c2w, sw, s2w = math.cos(w), math.cos(2 * w), math.sin(w), math.sin(2 * w)
            nr, ni = b0 + b1 * cw + b2 * c2w, -b1 * sw - b2 * s2w
            dr, di = 1 + a1 * cw + a2 * c2w, -a1 * sw - a2 * s2w
            mag *= ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)) ** 0.5
        out[i] = 20.0 * math.log10(mag + 1e-30)
    return out


def load_words(path):
    d = json.load(io.open(path, encoding="utf-8"))
    by = {kf["label"]: [tuple(int(x) & 0xFFFF for x in w) for w in kf["packedWords"]] for kf in d["keyframes"]}
    words = {L2K[lbl]: by[lbl] for lbl in ORDER}
    return words, d


CRANK = 0.70  # close this fraction of every pole's gap to the unit circle (clamp 0.999)


def crank_kernel(c, amt):
    """Push a decoded stage's POLE radius toward the unit circle (sharper/taller),
    keeping its angle (centre frequency). Pure radius crank — no reconstruction."""
    a1, a2 = c[2] - 2.0, 1.0 - c[3]
    r = max(a2, 0.0) ** 0.5
    if r <= 1e-4 or r >= 1.0:
        return c
    cos = max(-1.0, min(1.0, -a1 / (2.0 * r)))
    r2 = min(0.9990, 1.0 - (1.0 - r) * (1.0 - amt))
    a1n, a2n = -2.0 * r2 * cos, r2 * r2
    return (c[0], c[1], a1n + 2.0, 1.0 - a2n, c[4])


def response_at(words, morph, q, crank=0.0):
    # SHIPPING packed path: u16 bilinear in packed space -> decode -> (crank) -> cascade.
    kernels = pi.packed_bilinear(words, morph, q)
    if crank > 0.0:
        kernels = [crank_kernel(c, crank) for c in kernels]
    return cascade_db(kernels, FREQS)


def pole_info(words, key):
    """List (freq_hz, radius) of each resonant pole in a corner — to say what it IS."""
    out = []
    for s in words[key]:
        c = pi.words_to_coeffs(tuple(s))
        a1, a2 = c[2] - 2.0, 1.0 - c[3]
        r = max(a2, 0.0) ** 0.5
        if r <= 1e-4 or a1 * a1 - 4.0 * a2 >= 0.0:
            continue
        f = math.acos(max(-1.0, min(1.0, -a1 / (2.0 * r)))) * SR / TAU
        if 30 < f < 18000:
            out.append((round(f), round(r, 4)))
    return sorted(out)


def style(ax):
    ax.set_facecolor(FIELD)
    for s in ax.spines.values():
        s.set_color("#46534b")
    ax.set_xscale("log"); ax.set_xlim(60, 16000)
    ax.tick_params(colors=INK, labelsize=7)
    ax.grid(True, color="#16201b", lw=0.4)


def main():
    words, d = load_words(SRC)
    sha = hashlib.sha256(io.open(SRC, "rb").read()).hexdigest()
    sha240 = hashlib.sha256(io.open(B240, "rb").read()).hexdigest()

    # what ARE the corners — resonant pole inventory (freq Hz, radius)
    corners = [("M0 / S0", "A", 0.0, 0.0), ("M1 / S0", "B", 1.0, 0.0),
               ("M0 / S1", "C", 0.0, 1.0), ("M1 / S1", "D", 1.0, 1.0)]
    print("\nNeon Vane — resonant poles per corner (freq Hz @ radius):")
    for lab, key, _, _ in corners:
        print(f"  {lab:8s} {key}: {pole_info(words, key)}")

    mvals = [0.0, 0.25, 0.5, 0.75, 1.0]
    all_curves = [response_at(words, m, q, CRANK) for _, _, m, q in corners]
    all_curves += [response_at(words, m, 0.0, CRANK) for m in mvals]
    all_curves += [response_at(words, m, 1.0, CRANK) for m in mvals]
    ymax = max(c.max() for c in all_curves) + 3
    ymin = max(min(c.min() for c in all_curves), ymax - 60)

    fig = plt.figure(figsize=(11, 10), facecolor=FIELD)
    gs = GridSpec(4, 2, height_ratios=[1, 1, 1.2, 1.2], hspace=0.42, wspace=0.16)

    # 1. four corner miniplots  M0/S0  M1/S0  /  M0/S1  M1/S1
    cell = {0: (0, 0), 1: (0, 1), 2: (1, 0), 3: (1, 1)}
    ccol = [AMBER, GREEN, CYAN, RED]
    for i, (lab, key, m, q) in enumerate(corners):
        r, c = cell[i]
        ax = fig.add_subplot(gs[r, c]); style(ax)
        orig = response_at(words, m, q, 0.0)
        cranked = response_at(words, m, q, CRANK)
        ax.plot(FREQS, orig, color="#5a6b60", lw=1.0, label="original")
        ax.plot(FREQS, cranked, color=ccol[i], lw=1.7, label=f"radius cranked {CRANK:g}")
        ax.fill_between(FREQS, cranked, ymin, color=ccol[i], alpha=0.10)
        ax.set_ylim(ymin, ymax)
        ax.set_title(f"{lab}   (corner {key})", color=INK, fontsize=9, family="monospace")
        if i == 0:
            ax.legend(facecolor="#11150f", edgecolor="#46534b", labelcolor=INK, fontsize=6.5, loc="lower left")

    # 2. MORPH overlays at SECONDARY=0 and SECONDARY=1
    grad = [GREEN, CYAN, AMBER, "#ff8a3d", RED]
    for row, qv, tag in [(2, 0.0, "SECONDARY = 0"), (3, 1.0, "SECONDARY = 1")]:
        ax = fig.add_subplot(gs[row, :]); style(ax)
        for j, m in enumerate(mvals):
            curve = response_at(words, m, qv, CRANK)
            ax.plot(FREQS, curve, color=grad[j], lw=1.5, label=f"M={m:g}")
        ax.set_ylim(ymin, ymax)
        ax.set_ylabel("dB", color=INK, fontsize=8)
        ax.set_title(f"MORPH sweep  ·  {tag}", color=ccol[0] if row == 2 else CYAN, fontsize=10, family="monospace")
        ax.legend(facecolor="#11150f", edgecolor="#46534b", labelcolor=INK, fontsize=7, ncol=5, loc="upper right")
    ax.set_xlabel("frequency (Hz)", color=INK, fontsize=9)

    prov = d.get("provenance", "?")
    head = (f"TRUTH SHEET · {d.get('name','?')} · {d.get('format','?')} · ORIGINAL (clean-room) · provenance={prov}  ·  RADIUS CRANKED {CRANK:g} (poles → wall, clamp 0.999)\n"
            f"shipping packed path: pyruntime.packed_interp.packed_bilinear → trench_packed_interpolate (PackedCorners::interpolate_biquad)\n"
            f"source: bodies/neon_vane.cart.json   sha256={sha[:32]}…\n"
            f".body240: bodies/neon_vane.body240   sha256={sha240[:32]}…   |  authoring SR={SR:g} Hz")
    fig.suptitle(head, color=INK, fontsize=8.5, family="monospace", ha="left", x=0.06, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, dpi=130, facecolor=FIELD)
    print("wrote", OUT)
    print("source sha256:", sha)
    print("body240 sha256:", sha240)


if __name__ == "__main__":
    main()
