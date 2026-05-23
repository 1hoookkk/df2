#!/usr/bin/env python3
"""plot_hedz_gap.py — side-by-side wet vs candidate spectra per M/Q corner.

Aligns (cross-correlation), gain-matches (least squares), then plots the
averaged magnitude spectrum of the E-mu wet render against the df2 candidate
for all four corners. Shows where the reconstruction diverges.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.io import wavfile
from scipy.signal import correlate, welch

DL = Path(r"C:\Users\hooki\Downloads")
PAIRS = [
    ("m0q0", "M0_Q0"),
    ("m0q1", "M0_Q100"),
    ("m1q0", "M100_Q0"),
    ("m1q1", "M100_Q100"),
]


def load(path: Path) -> np.ndarray:
    sr, data = wavfile.read(str(path))
    if data.dtype.kind in ("i", "u"):
        info = np.iinfo(data.dtype)
        data = data.astype(np.float64) / max(abs(info.min), abs(info.max))
    else:
        data = data.astype(np.float64)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return sr, data


def align(ref, cand, max_lag=200000):
    n = min(len(ref), len(cand))
    a = ref[:n] - ref[:n].mean()
    b = cand[:n] - cand[:n].mean()
    xcorr = correlate(a, b, mode="full")
    center = n - 1
    lo, hi = max(0, center - max_lag), min(len(xcorr), center + max_lag + 1)
    lag = int(np.argmax(xcorr[lo:hi])) + lo - center
    if lag > 0:
        cand = np.concatenate([np.zeros(lag), cand])
    elif lag < 0:
        ref = np.concatenate([np.zeros(-lag), ref])
    m = min(len(ref), len(cand))
    return ref[:m], cand[:m], lag


def main() -> int:
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for ax, (wet_tag, cand_tag) in zip(axes.flat, PAIRS):
        sr, ref = load(DL / f"hedz regions - {wet_tag}.wav")
        _, cand = load(DL / f"cand_{cand_tag}.wav")
        ref, cand, lag = align(ref, cand)
        g = float(np.dot(ref, cand) / (np.dot(cand, cand) + 1e-30))
        cand_g = cand * g

        f, pr = welch(ref, sr, nperseg=8192)
        _, pc = welch(cand_g, sr, nperseg=8192)
        _, pres = welch(ref - cand_g, sr, nperseg=8192)
        db = lambda x: 10 * np.log10(x + 1e-30)

        null = 20 * np.log10(np.sqrt(np.mean((ref - cand_g) ** 2)) /
                             (np.sqrt(np.mean(ref ** 2)) + 1e-30))
        ax.semilogx(f, db(pr), label="E-mu wet", lw=1.4)
        ax.semilogx(f, db(pc), label="df2 cand (gain-matched)", lw=1.0)
        ax.semilogx(f, db(pres), label="residual", lw=0.8, color="0.5")
        ax.set_title(f"{wet_tag}  (lag {lag}, gain {20*np.log10(abs(g)+1e-30):+.1f} dB, "
                     f"null {null:+.1f} dB)")
        ax.set_xlim(20, sr / 2)
        ax.set_xlabel("Hz")
        ax.set_ylabel("dB")
        ax.grid(True, which="both", alpha=0.25)
        ax.legend(fontsize=8)
    fig.tight_layout()
    out = DL / "hedz_gap.png"
    fig.savefig(out, dpi=110)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
