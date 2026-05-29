#!/usr/bin/env python3
"""Plot the response-first rack: before/after the pedestal fix + per-body shape.

No roles, no stages drawn. Full cascade, resonances (dots) and zeros (red v)
marked on the curve, and the morph manifold. Before = old role-based rack (with
the hard-coded sub pedestal); after = response-first vocal_rack2.
"""
from __future__ import annotations
import io, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.gridspec import GridSpec  # noqa: E402
from pyruntime import packed_interp as pi  # noqa: E402

OLD = os.path.join(ROOT, "dev", "tmp", "vocal_rack_tube")   # pedestal (role-based + sub)
NEW = os.path.join(ROOT, "dev", "tmp", "vocal_rack2")        # response-first
OUT = os.path.join(NEW, "plots")
SR = 39062.5
TAU = 2.0 * math.pi
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
FREQS = np.logspace(math.log10(40.0), math.log10(16000.0), 460)
FIELD, INK, GREEN, CYAN, AMBER, RED = "#0a0d0c", "#bec5be", "#5bef6f", "#31c6c9", "#e8a33d", "#e83d31"


def corner_words(cart, label):
    d = json.load(io.open(cart, encoding="utf-8"))
    kf = {k["label"]: k for k in d["keyframes"]}[label]
    return [tuple(int(x) & 0xFFFF for x in w) for w in kf["packedWords"]]


def words_dict(cart):
    d = json.load(io.open(cart, encoding="utf-8"))
    by = {k["label"]: k for k in d["keyframes"]}
    return {LABEL_TO_KEY[l]: [tuple(int(x) & 0xFFFF for x in w) for w in by[l]["packedWords"]] for l in CORNER_ORDER}


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
        out[i] = 20 * math.log10(mag + 1e-30)
    return out


def kdb(words, freqs):
    return cascade_db([pi.words_to_coeffs(w) for w in words], freqs)


def pole_freq(s):
    a1, a2 = s[2] - 2, 1 - s[3]
    r = max(a2, 0) ** 0.5
    if r <= 1e-6 or a1 * a1 - 4 * a2 >= 0:
        return None
    return math.acos(max(-1, min(1, -a1 / (2 * r)))) * SR / TAU


def zero_freq(s):
    n1, n2 = s[0] - 2, 1 - s[1]
    if abs(n1) < 0.02 and abs(n2) < 0.02:
        return None
    rz = max(n2, 0) ** 0.5
    if rz <= 1e-6 or n1 * n1 - 4 * n2 >= 0:
        return None
    return math.acos(max(-1, min(1, -n1 / (2 * rz)))) * SR / TAU


def style(ax):
    ax.set_facecolor(FIELD)
    for s in ax.spines.values():
        s.set_color("#46534b")
    ax.tick_params(colors=INK, labelsize=8)
    ax.grid(True, color="#16201b", lw=0.5)


def before_after(bodies):
    fig = plt.figure(figsize=(13, 4.2), facecolor=FIELD)
    gs = GridSpec(1, 3, wspace=0.18)
    for n, (bid, name) in enumerate(bodies):
        ax = fig.add_subplot(gs[0, n]); style(ax)
        old = kdb(corner_words(os.path.join(OLD, f"{bid}_tube.cart.json"), "M0_Q0"), FREQS)
        new = kdb(corner_words(os.path.join(NEW, f"{bid}.cart.json"), "M0_Q0"), FREQS)
        old -= old.max(); new -= new.max()  # align peaks; compare SHAPE
        ax.plot(FREQS, old, color=RED, lw=1.4, label="before (sub pedestal)")
        ax.plot(FREQS, new, color=GREEN, lw=1.6, label="after (response-first)")
        for lo, hi, nm in [(20, 120, "low"), (120, 800, "body"), (800, 4000, "bite"), (4000, 16000, "air")]:
            ax.axvspan(lo, hi, color="#5bef6f", alpha=0.03)
        ax.set_xscale("log"); ax.set_xlim(40, 16000); ax.set_ylim(-90, 4)
        ax.set_title(name, color=GREEN, fontsize=10)
        ax.set_xlabel("Hz", color=INK, fontsize=8)
        if n == 0:
            ax.set_ylabel("level (dB, peak-aligned)", color=INK, fontsize=8)
            ax.legend(facecolor="#11150f", edgecolor="#46534b", labelcolor=INK, fontsize=7, loc="lower left")
    fig.suptitle("Before / after — killing the hard-coded sub pedestal (M0_Q0 shape)", color=GREEN, fontsize=12)
    p = os.path.join(OUT, "before_after.png")
    fig.savefig(p, dpi=115, facecolor=FIELD, bbox_inches="tight"); plt.close(fig)
    return p


def plot_body(bid, name, desc):
    wd = words_dict(os.path.join(NEW, f"{bid}.cart.json"))
    fig = plt.figure(figsize=(11, 7.5), facecolor=FIELD)
    gs = GridSpec(2, 1, height_ratios=[1, 1.1], hspace=0.3)
    logf = np.log10(FREQS)
    ax = fig.add_subplot(gs[0]); style(ax)
    for m, color, tag, key in [(0.0, GREEN, "Morph 0", "A"), (1.0, CYAN, "Morph 100", "B")]:
        curve = cascade_db(pi.packed_bilinear(wd, m, 0.0), FREQS)
        ax.plot(FREQS, curve, color=color, lw=1.6, label=tag)
        ax.fill_between(FREQS, curve, curve.min() - 4, color=color, alpha=0.07)
        for s in [pi.words_to_coeffs(w) for w in wd[key]]:
            pf = pole_freq(s)
            if pf and 40 < pf < 16000:
                ax.plot(pf, np.interp(math.log10(pf), logf, curve), "o", color=color, ms=6, zorder=5)
            zf = zero_freq(s)
            if zf and 40 < zf < 16000:
                yz = np.interp(math.log10(zf), logf, curve)
                ax.plot(zf, yz, "v", color=RED, mec=color, ms=9, zorder=6)
    ax.scatter([], [], marker="o", color=INK, label="resonance")
    ax.scatter([], [], marker="v", color=RED, label="zero / notch")
    ax.set_xscale("log"); ax.set_xlim(40, 16000)
    ax.set_xlabel("frequency (Hz)", color=INK, fontsize=9); ax.set_ylabel("level (dB)", color=INK, fontsize=9)
    ax.set_title(f"{name} — full cascade (dots = resonances · ▼ = zeros · no sub, no roles)", color=GREEN, fontsize=11)
    ax.legend(facecolor="#11150f", edgecolor="#46534b", labelcolor=INK, fontsize=8, loc="upper right", ncol=2)

    ax = fig.add_subplot(gs[1]); style(ax)
    steps = 90
    Z = np.array([cascade_db(pi.packed_bilinear(wd, r / (steps - 1), 0.0), FREQS) for r in range(steps)])
    ax.pcolormesh(FREQS, np.linspace(0, 1, steps), np.clip(Z, -54, 6), cmap="magma", vmin=-54, vmax=6, shading="auto")
    ax.set_xscale("log"); ax.set_xlim(40, 16000)
    ax.set_xlabel("frequency (Hz)", color=INK, fontsize=9); ax.set_ylabel("morph (0→100)", color=INK, fontsize=9)
    ax.set_title("the morph — resonances gliding (bright = energy, dark bands = the zeros)", color=AMBER, fontsize=10)
    fig.text(0.5, 0.005, desc, color="#69836f", fontsize=9, ha="center")
    p = os.path.join(OUT, f"{bid}.png")
    fig.savefig(p, dpi=110, facecolor=FIELD, bbox_inches="tight"); plt.close(fig)
    return p


def main():
    os.makedirs(OUT, exist_ok=True)
    rep = json.load(io.open(os.path.join(NEW, "report.json"), encoding="utf-8"))
    items = [(bid, b["name"], b["desc"]) for bid, b in rep["bodies"].items()]
    ba = before_after([(i, n) for i, n, _ in items[:3]])
    print(f"before/after -> {os.path.relpath(ba, ROOT)}")
    for bid, name, desc in items:
        print(f"  {name} -> {os.path.relpath(plot_body(bid, name, desc), ROOT)}")


if __name__ == "__main__":
    main()
