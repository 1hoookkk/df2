"""Cascade scope — read a body's stage anatomy off the SERIAL CASCADE.

The point (Tyson, 2026-07-21): a per-stage plot doesn't show what each biquad
does to the SHAPE. A filter is a serial cascade of 6 biquad organs, so the
legible view is the RUNNING PRODUCT: stage 1 alone, then 1x2, then 1x2x3 ...
through all 6. Each curve is the shape *after* that organ is added, so you see
air (stage 1) -> +body -> +voice stacking into the final response.

Decodes the 4 stored corners (M0Q0, M100Q0, M0Q100, M100Q100) directly from the
240-byte body via the shipping packed_interp decode chain (no interpolation, no
DLL needed — the corners ARE morph/Q in {0,1}^2). Overlay the measured blue
(wet/dry) separately; this tool draws the authored cascade.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import freqz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad

STAGE_SR = 39_062.5
NUM_CORNERS, NUM_STAGES, NUM_COEFFS = 4, 6, 5
CORNER_LABELS = ["M0 Q0 (A)", "M100 Q0 (B)", "M0 Q100 (C)", "M100 Q100 (D)"]


def load_corners(path: str) -> list[list[tuple[float, ...]]]:
    """240 bytes -> [corner][stage] = (b0,b1,b2,a1,a2). Corner-major, 5 u16 LE."""
    raw = open(path, "rb").read()
    assert len(raw) == 240, f"expected 240 bytes, got {len(raw)}"
    words = np.frombuffer(raw, dtype="<u2").reshape(NUM_CORNERS, NUM_STAGES, NUM_COEFFS)
    corners = []
    for c in range(NUM_CORNERS):
        corners.append([kernel_to_biquad(words_to_coeffs(tuple(int(x) for x in words[c, s])))
                        for s in range(NUM_STAGES)])
    return corners


def cascade_mag(stages, freqs_hz):
    """Cumulative cascade magnitude in dB: returns [6][F], row k = product of
    stages 0..k. freqz is evaluated at the physical Hz mapped to STAGE_SR."""
    w = 2 * np.pi * freqs_hz / STAGE_SR
    running = np.ones_like(w, dtype=complex)
    out = []
    for (b0, b1, b2, a1, a2) in stages:
        _, h = freqz([b0, b1, b2], [1.0, a1, a2], worN=w)
        running = running * h
        out.append(20 * np.log10(np.maximum(np.abs(running), 1e-9)))
    return np.array(out)


def _extrema(freqs, curve, kind, prom=3.0):
    """Crude peak/notch finder on the final cascade curve (dB)."""
    from scipy.signal import find_peaks
    sig = curve if kind == "peak" else -curve
    idx, _ = find_peaks(sig, prominence=prom)
    return [(freqs[i], curve[i]) for i in idx]


def main():
    body = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.expanduser("~"),
        "Documents", "TRENCH", "bodies", "FUNDAMENTALS", "06_PHA", "phaser_1.body240",
    )
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "scratchpad", "cascade_scope.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    corners = load_corners(body)
    freqs = np.geomspace(20.0, STAGE_SR * 0.499, 1024)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True, sharey=True)
    for ci, ax in enumerate(axes.flat):
        curves = cascade_mag(corners[ci], freqs)
        for k in range(NUM_STAGES):
            ax.semilogx(freqs, curves[k], lw=1.0 + 1.2 * (k == NUM_STAGES - 1),
                        alpha=0.35 + 0.55 * (k / (NUM_STAGES - 1)),
                        color="steelblue" if k < NUM_STAGES - 1 else "black",
                        label=f"+stage {k+1}" if ci == 0 else None)
        final = curves[-1]
        for f, db in _extrema(freqs, final, "notch"):
            ax.axvline(f, color="crimson", ls=":", lw=0.8)
            ax.annotate(f"{f:.0f}", (f, db), color="crimson", fontsize=7, ha="center", va="top")
        for f, db in _extrema(freqs, final, "peak"):
            ax.plot(f, db, "^", color="darkorange", ms=6)
            ax.annotate(f"{f:.0f}", (f, db), color="darkorange", fontsize=7, ha="center", va="bottom")
        ax.set_title(CORNER_LABELS[ci], fontsize=10)
        ax.grid(True, which="both", alpha=0.25)
        ax.set_xlim(20, STAGE_SR * 0.5)
    axes[0, 0].legend(fontsize=7, loc="lower left")
    for ax in axes[:, 0]:
        ax.set_ylabel("dB")
    for ax in axes[1, :]:
        ax.set_xlabel("Hz")
    fig.suptitle(f"Serial cascade (running product of biquad organs) — {os.path.basename(body)}",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    print("wrote", os.path.abspath(out))

    # self-check: print detected notches/peaks on the final cascade per corner
    for ci in range(NUM_CORNERS):
        final = cascade_mag(corners[ci], freqs)[-1]
        notches = ", ".join(f"{f:.0f}" for f, _ in _extrema(freqs, final, "notch")) or "-"
        peaks = ", ".join(f"{f:.0f}" for f, _ in _extrema(freqs, final, "peak")) or "-"
        print(f"{CORNER_LABELS[ci]:14s} notches Hz: {notches:32s}  peaks Hz: {peaks}")


if __name__ == "__main__":
    main()
