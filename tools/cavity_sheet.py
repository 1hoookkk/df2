#!/usr/bin/env python3
"""Coupled-CAVITY authoring — the real E-mu character, not a graphic EQ.

Every stage is a POLE + a coupled ZERO sitting close to it at HIGH radius — a
sharp peak with a deep notch right beside it (the cavity / the "tear"). Because
the pole and zero are close, the section is ~unity at DC and Nyquist, so six in
series stay balanced (no cliff) while each carries jagged peak+notch character —
exactly how your favourites (Deep Bouche etc.) are built. Plotted through the
shipping packed-domain lerp.
"""
import math, os, sys
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyruntime import packed_interp as pi

SR = 39062.5; TAU = 2 * math.pi
FREQS = np.logspace(math.log10(60), math.log10(16000), 460)
OUT = os.path.join(ROOT, "dev", "tmp", "cavity_sheet.png")
FIELD = "#0a0d0c"; INK = "#bec5be"; AMBER = "#e8a33d"; GREEN = "#5bef6f"; CYAN = "#31c6c9"; RED = "#e83d31"

# 6 cavities: a low body, F1-F4, and an air resonance. (Peterson F1-F4.)
POLES = {
    "ah_m": [185, 730, 1090, 2440, 3400, 5500],
    "ee_m": [185, 270, 2290, 3010, 3700, 5500],
    "ah_f": [200, 850, 1220, 2810, 3500, 5800],
    "ee_f": [200, 310, 2790, 3310, 3950, 5800],
}
ZSEMIS = [-3, 5, 5, 6, 6, 5]      # coupled zero offset (semitones) — +above = peak then canyon
QF = [3.0, 13.0, 15.0, 16.0, 13.0, 9.0]   # cranked resonance (10..18)
RZ = 0.90                          # zero radius — HIGH = a real notch (the tear), not a soft null
CRANK = 0.65                       # push each pole this far toward the unit circle (clamp 0.9985)


def biquad_to_kernel(b0, b1, b2, a1, a2):
    return (b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


def cavity_kernel(fp, rp, fz, rz):
    """Coupled pole+zero, normalised to UNITY at DC (no pedestal, no slope)."""
    wp, wz = TAU * fp / SR, TAU * fz / SR
    a1, a2 = -2 * rp * math.cos(wp), rp * rp
    nb1, nb2 = -2 * rz * math.cos(wz), rz * rz          # monic numerator
    g = (1 + a1 + a2) / (1 + nb1 + nb2)                 # H(DC)=1
    return biquad_to_kernel(g, g * nb1, g * nb2, a1, a2)


def corner_words(vk):
    stages = []
    for i, fp in enumerate(POLES[vk]):
        rp = math.exp(-math.pi * (fp / QF[i]) / SR)
        rp = min(0.99, max(0.98, rp))   # crank radius into the 0.98-0.99 band
        fz = fp * 2.0 ** (ZSEMIS[i] / 12.0)
        stages.append(cavity_kernel(fp, rp, fz, RZ))
    return [pi.coeffs_to_words(*s) for s in stages]


def cascade_db(kernels, freqs):
    out = np.empty(len(freqs))
    for i, f in enumerate(freqs):
        w = TAU * f / SR; mag = 1.0
        for c in kernels:
            b0, b1, b2, a1, a2 = c[4], (c[0] - 2) * c[4], (1 - c[1]) * c[4], c[2] - 2, 1 - c[3]
            cw, c2, sw, s2 = math.cos(w), math.cos(2 * w), math.sin(w), math.sin(2 * w)
            nr, ni = b0 + b1 * cw + b2 * c2, -b1 * sw - b2 * s2
            dr, di = 1 + a1 * cw + a2 * c2, -a1 * sw - a2 * s2
            mag *= ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)) ** 0.5
        out[i] = 20 * math.log10(mag + 1e-30)
    return out


def response_at(words, morph, q):
    kern = []
    for s in range(len(words["A"])):
        A, B, C, D = words["A"][s], words["B"][s], words["C"][s], words["D"][s]
        stg = [pi.lerp_u16(pi.lerp_u16(A[w], B[w], morph), pi.lerp_u16(C[w], D[w], morph), q) for w in range(5)]
        kern.append(pi.words_to_coeffs(tuple(stg)))
    return cascade_db(kern, FREQS)


def style(ax):
    ax.set_facecolor(FIELD)
    for s in ax.spines.values():
        s.set_color("#46534b")
    ax.set_xscale("log"); ax.set_xlim(60, 16000); ax.tick_params(colors=INK, labelsize=7)
    ax.grid(True, color="#16201b", lw=0.4)


def hz_to_bark(f):
    return 26.81 * f / (1960 + f) - 0.53


def main():
    words = {"A": corner_words("ah_m"), "B": corner_words("ee_m"), "C": corner_words("ah_f"), "D": corner_words("ee_f")}
    corners = [("M0/S0 Ah male", "A", 0, 0, "ah_m"), ("M1/S0 Ee male", "B", 1, 0, "ee_m"),
               ("M0/S1 Ah female", "C", 0, 1, "ah_f"), ("M1/S1 Ee female", "D", 1, 1, "ee_f")]
    mvals = [0, 0.25, 0.5, 0.75, 1]
    allc = [response_at(words, m, q) for _, _, m, q, _ in corners] + [response_at(words, m, qv) for qv in (0, 1) for m in mvals]
    ymax = max(c.max() for c in allc) + 4; ymin = max(min(c.min() for c in allc), ymax - 60)
    ccol = [AMBER, GREEN, CYAN, RED]

    fig = plt.figure(figsize=(11, 10), facecolor=FIELD)
    gs = GridSpec(4, 2, height_ratios=[1, 1, 1.2, 1.2], hspace=0.46, wspace=0.16)
    cell = {0: (0, 0), 1: (0, 1), 2: (1, 0), 3: (1, 1)}
    for i, (lab, key, m, q, vk) in enumerate(corners):
        r, c = cell[i]; ax = fig.add_subplot(gs[r, c]); style(ax)
        cur = response_at(words, m, q)
        ax.plot(FREQS, cur, color=ccol[i], lw=1.5); ax.fill_between(FREQS, cur, ymin, color=ccol[i], alpha=0.10)
        ax.set_ylim(ymin, ymax)
        # readouts: peak prominence above local baseline + min Bark-spacing/combined-bw
        fr = sorted(POLES[vk]); bws = [fr[j] / QF[POLES[vk].index(fr[j])] for j in range(len(fr))]
        ratios = []
        for j in range(len(fr) - 1):
            db = hz_to_bark(fr[j + 1]) - hz_to_bark(fr[j])
            bb = (hz_to_bark(fr[j] + bws[j] / 2) - hz_to_bark(fr[j] - bws[j] / 2)) + (hz_to_bark(fr[j + 1] + bws[j + 1] / 2) - hz_to_bark(fr[j + 1] - bws[j + 1] / 2))
            ratios.append(db / max(bb, 1e-6))
        proms = []
        for fp in POLES[vk]:
            idx = int(np.argmin(np.abs(FREQS - fp))); lo, hi = max(0, idx - 22), min(len(FREQS), idx + 22)
            proms.append(cur[lo:hi].max() - cur[lo:hi].min())  # peak-to-notch depth = the tear
        ax.set_title(lab, color=INK, fontsize=8.5, family="monospace")
        ax.text(0.03, 0.05, "tear " + "/".join(f"{p:.0f}" for p in proms) + "dB  minΔBk/bw " + f"{min(ratios):.2f}",
                transform=ax.transAxes, color="#9fb0a6", fontsize=6.4, family="monospace")

    grad = [GREEN, CYAN, AMBER, "#ff8a3d", RED]
    for row, qv, tag in [(2, 0, "SECONDARY=0 male"), (3, 1, "SECONDARY=1 female")]:
        ax = fig.add_subplot(gs[row, :]); style(ax)
        for j, m in enumerate(mvals):
            ax.plot(FREQS, response_at(words, m, qv), color=grad[j], lw=1.4, label=f"M={m:g}")
        ax.set_ylim(ymin, ymax); ax.set_ylabel("dB", color=INK, fontsize=8)
        ax.set_title(f"MORPH Ah->Ee · {tag}", color=ccol[0] if row == 2 else CYAN, fontsize=10, family="monospace")
        ax.legend(facecolor="#11150f", edgecolor="#46534b", labelcolor=INK, fontsize=7, ncol=5, loc="upper right")
    ax.set_xlabel("frequency (Hz)", color=INK, fontsize=9)

    head = ("COUPLED-CAVITY · Ah->Ee × male->female · pole + close high-radius zero per stage = peak + notch (the tear)\n"
            "unity-DC coupled cavities (no pedestal, no cliff) · cranked Q 10-18 · packed-domain lerp_u16 · 6 sections (ships)\n"
            "READOUT 1 peak-to-notch depth per cavity (dB, the tear)  ·  READOUT 2 min Bark-spacing/combined-bw")
    fig.suptitle(head, color=INK, fontsize=8.3, family="monospace", ha="left", x=0.06, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, dpi=130, facecolor=FIELD); print("wrote", OUT)


if __name__ == "__main__":
    main()
