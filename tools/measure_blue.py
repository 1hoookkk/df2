"""Measure the REAL filter response (the blue) from wet/dry render.

Ground truth for the X3 filter is the render, never our decode (circular).
wet = dry passed through the morphing filter, so |Wet(f,t)|/|Dry(f,t)| = |H(f,t)|.

The wet is a morph+res sweep 0->100 over its whole length; dry is a shorter loop
tiled to match. Reads |H| at the start (corner A = morph0/res0) and end
(corner D = morph100/res100) and overlays our decoded A/D so divergence is visible.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import soundfile as sf
from scipy.signal import stft, freqz
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.cascade_scope import load_corners, STAGE_SR, CORNER_LABELS

WET = r"C:\Users\hooki\Downloads\phaser morph 0-100 res0to 100.wav"
DRY = r"C:\Users\hooki\OneDrive\Documents\Image-Line\FL Studio\Audio\Rendered\Pattern 3 (consolidated).wav"
BODY = os.path.join(os.path.expanduser("~"), "Documents", "TRENCH", "bodies",
                    "FUNDAMENTALS", "06_PHA", "phaser_1.body240")


def mono(path):
    x, sr = sf.read(path, always_2d=True)
    return x.mean(axis=1), sr


def align_lag(wet, dry):
    """Coarse lag (samples) of dry within wet start, via envelope xcorr."""
    n = min(len(dry), len(wet))
    a = np.abs(wet[:n]); b = np.abs(dry[:n])
    a -= a.mean(); b -= b.mean()
    c = np.correlate(a, b, mode="full")
    return np.argmax(c) - (n - 1)


def decoded_mag(stages, freqs_hz):
    w = 2 * np.pi * freqs_hz / STAGE_SR
    h = np.ones_like(w, dtype=complex)
    for (b0, b1, b2, a1, a2) in stages:
        _, hi = freqz([b0, b1, b2], [1.0, a1, a2], worN=w)
        h = h * hi
    return 20 * np.log10(np.maximum(np.abs(h), 1e-9))


def main():
    wet, sr = mono(WET)
    dry, srd = mono(DRY)
    assert sr == srd, (sr, srd)

    lag = align_lag(wet, dry)
    dry_roll = np.roll(np.resize(dry, len(wet)) if len(dry) < len(wet) else dry[:len(wet)],
                       max(lag, 0))
    dry_t = np.resize(np.roll(dry, max(lag, 0)), len(wet))  # tile aligned dry to wet length

    nper = 8192
    f, tw, W = stft(wet, sr, nperseg=nper, noverlap=nper * 3 // 4)
    _, td, D = stft(dry_t, sr, nperseg=nper, noverlap=nper * 3 // 4)
    Wm, Dm = np.abs(W), np.abs(D)

    # trust only bins where dry has real energy; |H| elsewhere is meaningless
    floor = Dm.max() * 1e-3
    H = np.where(Dm > floor, Wm / np.maximum(Dm, 1e-12), np.nan)

    dur = len(wet) / sr
    def band_db(t0, t1):
        m = (tw >= t0) & (tw <= t1)
        col = np.nanmedian(H[:, m], axis=1)
        return 20 * np.log10(np.maximum(col, 1e-6))

    A_meas = band_db(0.2, 1.4)          # morph ~1-9%  -> corner A
    D_meas = band_db(dur - 1.4, dur - 0.2)  # morph ~90-98% -> corner D

    corners = load_corners(BODY)
    grid = np.geomspace(20.0, STAGE_SR * 0.499, 1024)
    A_dec = decoded_mag(corners[0], grid)
    D_dec = decoded_mag(corners[3], grid)

    fig, (axA, axD) = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    for ax, meas, dec, lbl in [(axA, A_meas, A_dec, CORNER_LABELS[0]),
                               (axD, D_meas, D_dec, CORNER_LABELS[3])]:
        ax.semilogx(f, meas - np.nanmedian(meas), color="royalblue", lw=2.2, label="measured (real X3 render)")
        ax.semilogx(grid, dec - np.median(dec), color="black", lw=1.4, ls="--", label="our decode")
        ax.set_title(lbl); ax.grid(True, which="both", alpha=0.25)
        ax.set_xlim(80, sr / 2); ax.set_xlabel("Hz"); ax.legend(fontsize=9)
    axA.set_ylabel("dB (median-normalised)")
    fig.suptitle(f"Real filter (blue) vs our decode — lag={lag} smp — phaser_1", fontsize=12)
    fig.tight_layout()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scratchpad", "measure_blue.png")
    fig.savefig(out, dpi=110)
    print("wrote", os.path.abspath(out), "| lag", lag)

    # also dump the |H(f,t)| morph movie so we can SEE morph+res sweep
    fig2, ax2 = plt.subplots(figsize=(13, 6))
    Hdb = 20 * np.log10(np.clip(np.nan_to_num(H, nan=1e-6), 1e-6, None))
    im = ax2.pcolormesh(tw, f, Hdb, shading="auto", vmin=-24, vmax=24, cmap="magma")
    ax2.set_yscale("log"); ax2.set_ylim(80, sr / 2)
    ax2.set_xlabel("time s  (morph+res 0->100)"); ax2.set_ylabel("Hz")
    fig2.colorbar(im, label="|H| dB"); ax2.set_title("Real |H(f,t)| — the morph movie")
    out2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scratchpad", "morph_movie.png")
    fig2.tight_layout(); fig2.savefig(out2, dpi=110)
    print("wrote", os.path.abspath(out2))


if __name__ == "__main__":
    main()
