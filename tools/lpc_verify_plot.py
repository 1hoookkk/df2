#!/usr/bin/env python3
"""lpc_verify_plot.py — visual proof for the two synthetic LPC fixtures.

For each fixture wav + .lpc.json pair, overlays:
  - the signal's FFT magnitude (light grey, the actual data),
  - the ground-truth all-pole envelope from F = 730/1090/2440/3500/4500/5500
    Hz, r = 0.96 (black, what the recovered curve must match),
  - the recovered all-pole envelope built from the JSON's poles (red dashed),
  - down-triangle markers for truth pole frequencies,
  - up-triangle markers for recovered pole frequencies.

Two stacked panels: flat and voiced fixtures. Saves to
dev/tmp/lpc_verify_plot.png.

numpy / scipy / matplotlib only.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


GROUND_TRUTH = [
    (730.0,  0.96),
    (1090.0, 0.96),
    (2440.0, 0.96),
    (3500.0, 0.96),
    (4500.0, 0.96),
    (5500.0, 0.96),
]

FIXTURES = [
    ("flat (impulse train -> 6-pole)",
     Path("dev/tmp/lpc_test_input.wav"),
     Path("dev/tmp/lpc_test_input.lpc.json")),
    ("voiced (1/(1 - 0.97 z^-1) -> 6-pole)",
     Path("dev/tmp/lpc_test_input_voiced.wav"),
     Path("dev/tmp/lpc_test_input_voiced.lpc.json")),
]

OUT = Path("dev/tmp/lpc_verify_plot.png")


def biquad_response(freqs: np.ndarray, sr: float, f: float, r: float) -> np.ndarray:
    theta = 2.0 * np.pi * f / sr
    z_inv = np.exp(-1j * 2.0 * np.pi * freqs / sr)
    den = 1.0 - 2.0 * r * np.cos(theta) * z_inv + (r * r) * z_inv * z_inv
    return 1.0 / den


def all_pole_response(freqs: np.ndarray, sr: float,
                      poles: list[tuple[float, float]]) -> np.ndarray:
    h = np.ones(len(freqs), dtype=complex)
    for f, r in poles:
        h *= biquad_response(freqs, sr, f, r)
    return h


def signal_spectrum(x: np.ndarray, sr: float,
                    n_fft: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    if len(x) >= n_fft:
        x_use = x[:n_fft]
    else:
        x_use = np.concatenate([x, np.zeros(n_fft - len(x))])
    w = np.hanning(n_fft)
    spec = np.fft.rfft(x_use * w)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    db = 20.0 * np.log10(np.abs(spec) + 1e-12)
    return freqs, db


def plot_fixture(ax: plt.Axes, label: str, wav_path: Path, json_path: Path) -> None:
    sr, x = wavfile.read(wav_path)
    if x.dtype == np.int16:
        x = x.astype(np.float64) / 32768.0
    else:
        x = x.astype(np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)

    report = json.loads(json_path.read_text())
    recovered = [(p["freq_hz"], p["radius"]) for p in report["poles"]]
    pe = report["preemphasis"]

    freqs_plot = np.logspace(np.log10(60.0), np.log10(7800.0), 2048)

    # signal magnitude
    fft_freqs, fft_db = signal_spectrum(x, sr)
    mask = (fft_freqs >= 60.0) & (fft_freqs <= 7800.0)
    sig_db = fft_db[mask] - np.max(fft_db[mask])
    ax.plot(fft_freqs[mask], sig_db, color="lightgray",
            linewidth=0.7, label="signal |S(f)|")

    # truth envelope
    truth_h = all_pole_response(freqs_plot, sr, GROUND_TRUTH)
    truth_db = 20.0 * np.log10(np.abs(truth_h))
    truth_db -= truth_db.max()
    ax.plot(freqs_plot, truth_db, color="black", linewidth=2.0,
            label="truth all-pole envelope")

    # recovered envelope
    rec_h = all_pole_response(freqs_plot, sr, recovered)
    rec_db = 20.0 * np.log10(np.abs(rec_h))
    rec_db -= rec_db.max()
    ax.plot(freqs_plot, rec_db, color="tab:red", linewidth=1.6,
            linestyle="--", label="recovered envelope")

    # truth pole markers (down triangles at the top)
    for f, _ in GROUND_TRUTH:
        ax.axvline(f, color="black", linewidth=0.4, alpha=0.18)
        ax.plot(f, 2.5, marker="v", color="black", markersize=9,
                clip_on=False, zorder=5)

    # recovered pole markers (up triangles just below truth)
    for f, _ in recovered:
        ax.plot(f, -1.5, marker="^", color="tab:red", markersize=9,
                clip_on=False, zorder=5)

    title = (
        f"{label}    "
        f"tilt = {pe['measured_tilt_db_per_octave']:+.2f} dB/oct    "
        f"preemph = {pe['applied']}"
    )
    ax.set_title(title, fontsize=10)
    ax.set_xscale("log")
    ax.set_xlim(60.0, 7800.0)
    ax.set_ylim(-70.0, 5.0)
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("magnitude (dB, peak-normalised)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="lower left", fontsize=8)

    # per-formant Δf annotations, top-right
    lines = ["truth  →  recovered (Δf, Δr)"]
    for (tf, tr), (rf, rr) in zip(GROUND_TRUTH, sorted(recovered, key=lambda p: p[0])):
        lines.append(
            f"  {tf:>6.1f}  →  {rf:>7.2f}  "
            f"({rf - tf:+6.2f} Hz, {rr - tr:+.4f})"
        )
    ax.text(0.99, 0.97, "\n".join(lines),
            transform=ax.transAxes, ha="right", va="top",
            family="monospace", fontsize=8,
            bbox=dict(facecolor="white", edgecolor="0.7", alpha=0.95))


def main() -> int:
    fig, axes = plt.subplots(2, 1, figsize=(11, 9))
    for ax, (label, wav, jp) in zip(axes, FIXTURES):
        plot_fixture(ax, label, wav, jp)
    fig.suptitle(
        "LPC verification — recovered vs ground truth (order 12, 16 kHz, ±20 Hz gate)",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=130)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
