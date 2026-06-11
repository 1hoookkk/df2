#!/usr/bin/env python3
"""Author ONE grounded body where every pole sits on an ACOUSTIC frequency
(Peterson vowel formants), placed on a perceptual axis (log + Bark), each pole
carrying its coupled zero (the cavity), then plot the truth sheet through the
SHIPPING packed path (coeffs_to_words -> packed_bilinear -> PackedCorners::interpolate_biquad).

No arbitrary Hz. No RBJ. Frequencies come from tables/acoustic data; perceptual
spacing checked in Bark. Body = Ah->Ee (MORPH) x male->female tract size (SECONDARY).
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

SR = 39062.5
TAU = 2.0 * math.pi
FREQS = np.logspace(math.log10(60.0), math.log10(16000.0), 420)
OUT = os.path.join(ROOT, "dev", "tmp", "grounded_truth_sheet.png")
S7 = 2.0 ** (-7.0 / 12.0)  # coupled zero 7 semitones below its pole (no-pedestal bp)

FIELD = "#0a0d0c"; INK = "#bec5be"; GREEN = "#5bef6f"; CYAN = "#31c6c9"
AMBER = "#e8a33d"; RED = "#e83d31"


def hz_to_bark(f):
    """Traunmüller 1990 — perceptual critical-band index."""
    return 26.81 * f / (1960.0 + f) - 0.53


# ── ACOUSTIC anchors: Peterson 1952 F1-F4 (Hz) + a low body pole + HF. ─────────
# (tables/vowel_formants.json / vocal_formant_corners.csv). bandwidths canonical.
# STRUCTURE (Tyson): 1 low shelf (foundation/chest) + 6 peaking EQs (the resonances).
# TalkingHedz at-rest anatomy (Tyson) — 6 sections, FITS the 240-byte body:
#   biquad 1  : glottal lowpass 180 Hz, -12 dB/oct (the dropping foundation)
#   biquads 2-5: 4 vocal formants (peaking EQ, Q 8-15, up to +12 dB)
#   biquad 6  : "breath" HIGH shelf 5000 Hz (flatten the top, don't roll off)
GLOTTAL_HZ, GLOTTAL_Q = 180.0, 0.707
BREATH_HZ, BREATH_DB = 5000.0, 12.0
QF = [12.0, 14.0, 16.0, 14.0]    # cranked resonance (manual: 10..18) — sharp spikes
TARGET = [0.0, -1.0, -2.0, -3.0] # peak level each formant must REACH (fights the slope)
MIN_SPACING_HZ = 200.0           # closer than this → fuse into a hump; widen instead
VOW = {  # 4 vocal formants per corner (Peterson 1952)
    "ah_m": [730, 1090, 2440, 3400],
    "ee_m": [270, 2290, 3010, 3700],
    "ah_f": [850, 1220, 2810, 3500],
    "ee_f": [310, 2790, 3310, 3950],
}


def stage_kernel(f_hz, bw_hz, gain_db):
    """One PEAKING-EQ section (RBJ) at an acoustic frequency — UNITY gain off-centre,
    +gain_db boost at f. This is what cascades ADDITIVELY into a mountain range
    (vs a resonator, which multiplies its off-peak rolloff into a cliff and swallows
    the other poles). Q from real bandwidth. Returns kernel c0..c4 (coeffs_to_words)."""
    A = 10.0 ** (gain_db / 40.0)
    w = TAU * f_hz / SR
    q = f_hz / bw_hz
    al = math.sin(w) / (2.0 * q)
    cw = math.cos(w)
    a0 = 1.0 + al / A
    b0, b1, b2 = (1.0 + al * A) / a0, (-2.0 * cw) / a0, (1.0 - al * A) / a0
    a1, a2 = (-2.0 * cw) / a0, (1.0 - al / A) / a0
    # biquad [b0,b1,b2,a1,a2] -> kernel c0..c4 (b0=c4, b1=(c0-2)c4, b2=(1-c1)c4, a1=c2-2, a2=1-c3)
    return (b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


def biquad_to_kernel(b0, b1, b2, a1, a2):
    """a0-normalised biquad -> kernel c0..c4 (coeffs_to_words form)."""
    return (b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


def lowpass_kernel(f_hz, q):
    """RBJ 2-pole lowpass — the glottal -12 dB/oct foundation slope."""
    w = TAU * f_hz / SR
    al = math.sin(w) / (2.0 * q)
    cw = math.cos(w)
    a0 = 1.0 + al
    return biquad_to_kernel((1 - cw) / 2 / a0, (1 - cw) / a0, (1 - cw) / 2 / a0, (-2 * cw) / a0, (1 - al) / a0)


def high_shelf_kernel(f_hz, gain_db, q=0.707):
    """RBJ high shelf — the "breath" stage: flattens/lifts everything above f
    instead of letting the glottal slope roll the top off."""
    A = 10.0 ** (gain_db / 40.0)
    w = TAU * f_hz / SR
    al = math.sin(w) / (2.0 * q)
    cw = math.cos(w)
    tsa = 2.0 * math.sqrt(A) * al
    a0 = (A + 1.0) - (A - 1.0) * cw + tsa
    b0 = A * ((A + 1.0) + (A - 1.0) * cw + tsa) / a0
    b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cw) / a0
    b2 = A * ((A + 1.0) + (A - 1.0) * cw - tsa) / a0
    a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cw) / a0
    a2 = ((A + 1.0) - (A - 1.0) * cw - tsa) / a0
    return biquad_to_kernel(b0, b1, b2, a1, a2)


def low_shelf_kernel(f_hz, gain_db, q=0.707):
    """RBJ low shelf — gentle foundation that lifts the lows (variant B)."""
    A = 10.0 ** (gain_db / 40.0)
    w = TAU * f_hz / SR
    al = math.sin(w) / (2.0 * q)
    cw = math.cos(w)
    tsa = 2.0 * math.sqrt(A) * al
    a0 = (A + 1.0) + (A - 1.0) * cw + tsa
    return biquad_to_kernel(
        A * ((A + 1.0) - (A - 1.0) * cw + tsa) / a0,
        2.0 * A * ((A - 1.0) - (A + 1.0) * cw) / a0,
        A * ((A + 1.0) - (A - 1.0) * cw - tsa) / a0,
        -2.0 * ((A - 1.0) + (A + 1.0) * cw) / a0,
        ((A + 1.0) + (A - 1.0) * cw - tsa) / a0,
    )

GF_FIXED = [14.0, 12.0, 11.0, 10.0]  # cranked fixed gains (variants A/B/D)

VARIANTS = {
    "A": "current glottal slope (180Hz LP -12dB/oct)",
    "B": "gentler: low shelf foundation",
    "C": "glottal slope + freq-dependent peak compensation",
    "D": "no slope: flat baseline",
}


def baseline_stages(mode):
    if mode in ("A", "C"):
        return [lowpass_kernel(GLOTTAL_HZ, GLOTTAL_Q), high_shelf_kernel(BREATH_HZ, BREATH_DB)]
    if mode == "B":
        return [low_shelf_kernel(320.0, 8.0), high_shelf_kernel(BREATH_HZ, BREATH_DB)]
    return []  # D: flat


def formant_specs(vowel_key, mode):
    """Return [(f, bw, gain)] for the 4 formants under this mode + the baseline stages."""
    freqs = list(VOW[vowel_key])
    base = baseline_stages(mode)
    specs = []
    for i, f in enumerate(freqs):
        bw = f / QF[i]
        nb = min((abs(f - g) for j, g in enumerate(freqs) if j != i), default=1e9)
        if nb < MIN_SPACING_HZ:                      # Rule 1: widen so they don't fuse
            bw = max(bw, MIN_SPACING_HZ * 1.5)
        if mode == "C":                              # Rule 3: lift to target above the slope
            baseline = cascade_db(base, [f])[0] if base else 0.0
            gain = max(8.0, min(30.0, TARGET[i] - baseline))
        else:
            gain = GF_FIXED[i]
        specs.append((f, bw, gain))
    return specs, base


def corner_words(vowel_key, mode="C"):
    specs, base = formant_specs(vowel_key, mode)
    stages = (base[:1] if base else []) + [stage_kernel(f, bw, g) for f, bw, g in specs] + (base[1:] if base else [])
    return [pi.coeffs_to_words(*s) for s in stages]


def readouts(vowel_key, mode, m, q):
    """Two readouts: (1) each formant's peak prominence above the local baseline (dB);
    (2) the minimum Bark-spacing / combined-bandwidth across adjacent formants."""
    specs, base = formant_specs(vowel_key, mode)
    words = {"A": corner_words("ah_m", mode), "B": corner_words("ee_m", mode),
             "C": corner_words("ah_f", mode), "D": corner_words("ee_f", mode)}
    full = response_at(words, m, q)
    proms = []
    for f, bw, g in specs:
        idx = int(np.argmin(np.abs(FREQS - f)))
        lo, hi = max(0, idx - 18), min(len(FREQS), idx + 18)
        peak = full[lo:hi].max()
        bl = cascade_db(base, [f])[0] if base else 0.0
        proms.append(peak - bl)
    # Bark spacing / combined bandwidth across adjacent formants
    fb = sorted(specs)
    ratios = []
    for j in range(len(fb) - 1):
        (f1, bw1, _), (f2, bw2, _) = fb[j], fb[j + 1]
        dbark = hz_to_bark(f2) - hz_to_bark(f1)
        bwbark = (hz_to_bark(f1 + bw1 / 2) - hz_to_bark(f1 - bw1 / 2)) + (hz_to_bark(f2 + bw2 / 2) - hz_to_bark(f2 - bw2 / 2))
        ratios.append(dbark / max(bwbark, 1e-6))
    return proms, (min(ratios) if ratios else float("nan"))


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
    # Shipping packed-domain interpolation (E-mu u16 bilinear, morph-first) applied
    # per stage — same lerp_u16 math as packed_bilinear, without the 240-byte storage
    # cap, so it handles 7 sections (1 shelf + 6 peaking EQs).
    kern = []
    for s in range(len(words["A"])):
        A, B, C, D = words["A"][s], words["B"][s], words["C"][s], words["D"][s]
        stage = []
        for w in range(5):
            ab = pi.lerp_u16(A[w], B[w], morph)
            cd = pi.lerp_u16(C[w], D[w], morph)
            stage.append(pi.lerp_u16(ab, cd, q))
        kern.append(pi.words_to_coeffs(tuple(stage)))
    return cascade_db(kern, FREQS)


def style(ax):
    ax.set_facecolor(FIELD)
    for s in ax.spines.values():
        s.set_color("#46534b")
    ax.set_xscale("log"); ax.set_xlim(60, 16000)
    ax.tick_params(colors=INK, labelsize=7)
    ax.grid(True, color="#16201b", lw=0.4)


CORNERS = [("M0/S0 Ah male", "A", 0.0, 0.0, "ah_m"), ("M1/S0 Ee male", "B", 1.0, 0.0, "ee_m"),
           ("M0/S1 Ah female", "C", 0.0, 1.0, "ah_f"), ("M1/S1 Ee female", "D", 1.0, 1.0, "ee_f")]
MVALS = [0.0, 0.25, 0.5, 0.75, 1.0]
CCOL = [AMBER, GREEN, CYAN, RED]


def plot_variant(mode):
    words = {"A": corner_words("ah_m", mode), "B": corner_words("ee_m", mode),
             "C": corner_words("ah_f", mode), "D": corner_words("ee_f", mode)}
    allc = [response_at(words, m, q) for _, _, m, q, _ in CORNERS]
    allc += [response_at(words, m, qv) for qv in (0.0, 1.0) for m in MVALS]
    ymax = max(c.max() for c in allc) + 4
    ymin = max(min(c.min() for c in allc), ymax - 70)

    fig = plt.figure(figsize=(11, 10), facecolor=FIELD)
    gs = GridSpec(4, 2, height_ratios=[1, 1, 1.2, 1.2], hspace=0.5, wspace=0.16)
    cell = {0: (0, 0), 1: (0, 1), 2: (1, 0), 3: (1, 1)}
    proms_all = []
    for i, (lab, key, m, q, vk) in enumerate(CORNERS):
        r, c = cell[i]
        ax = fig.add_subplot(gs[r, c]); style(ax)
        ax.plot(FREQS, response_at(words, m, q), color=CCOL[i], lw=1.6)
        ax.fill_between(FREQS, response_at(words, m, q), ymin, color=CCOL[i], alpha=0.10)
        ax.set_ylim(ymin, ymax)
        proms, ratio = readouts(vk, mode, m, q)
        proms_all.append(proms)
        ax.set_title(lab, color=INK, fontsize=8.5, family="monospace")
        ax.text(0.03, 0.04, "prom " + "/".join(f"{p:.0f}" for p in proms) + " dB   ΔBk/bw " + f"{ratio:.2f}",
                transform=ax.transAxes, color="#9fb0a6", fontsize=6.6, family="monospace")

    grad = [GREEN, CYAN, AMBER, "#ff8a3d", RED]
    for row, qv, tag in [(2, 0.0, "SECONDARY=0 (male)"), (3, 1.0, "SECONDARY=1 (female)")]:
        ax = fig.add_subplot(gs[row, :]); style(ax)
        for j, m in enumerate(MVALS):
            ax.plot(FREQS, response_at(words, m, qv), color=grad[j], lw=1.5, label=f"M={m:g}")
        ax.set_ylim(ymin, ymax); ax.set_ylabel("dB", color=INK, fontsize=8)
        ax.set_title(f"MORPH Ah->Ee · {tag}", color=CCOL[0] if row == 2 else CYAN, fontsize=10, family="monospace")
        ax.legend(facecolor="#11150f", edgecolor="#46534b", labelcolor=INK, fontsize=7, ncol=5, loc="upper right")
    ax.set_xlabel("frequency (Hz)", color=INK, fontsize=9)

    mean_prom = np.mean([p for ps in proms_all for p in ps])
    head = (f"VARIANT {mode} — {VARIANTS[mode]}    ·    Ah->Ee × male->female · packed-path (lerp_u16) · Peterson F1-F4\n"
            f"READOUT 1 peak prominence above local baseline (per-corner, dB; mean {mean_prom:.0f})   ·   "
            f"READOUT 2 min Bark-spacing / combined-bandwidth (ΔBk/bw; >1 = resolved, <1 = fusing)")
    fig.suptitle(head, color=INK, fontsize=8.3, family="monospace", ha="left", x=0.06, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out = os.path.join(ROOT, "dev", "tmp", f"variant_{mode}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=130, facecolor=FIELD)
    plt.close(fig)
    print(f"VARIANT {mode}: {VARIANTS[mode]:55s} mean prom {mean_prom:5.1f}dB -> {out}")


def main():
    for mode in ("A", "B", "C", "D"):
        plot_variant(mode)


if __name__ == "__main__":
    main()
