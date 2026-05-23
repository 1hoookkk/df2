#!/usr/bin/env python3
"""lpc_extract.py — extract resonant poles from an audio file via LPC analysis.

First machine in the audio-to-cartridge factory. Loads a wav, finds the
steady-state region, runs 12th-order LPC on a pre-emphasised + Hamming-
windowed analysis frame at 16 kHz, and reports the top 6 resonant poles
(by radius) inside the formant band.

Behavioural pole extraction only. Not a fitter, not an authoring step;
the output is a JSON of (freq_hz, radius, bandwidth_hz) for a downstream
fitter to consume. No cartridge/runtime code is touched.

Usage:
    python tools/lpc_extract.py path/to/sound.wav

Writes: <basename>.lpc.json next to the input wav.
Prints: poles table to stdout.

scipy / numpy only.
"""
from __future__ import annotations

import argparse
import json
import sys
from math import gcd
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.linalg import solve_toeplitz
from scipy.signal import lfilter, resample_poly

# ── constants (spec-fixed) ──────────────────────────────────────────────────
ANALYSIS_SR = 16000
LPC_ORDER = 12
PRE_EMPH = 0.97
FRAME_MS = 25.0          # RMS-frame length for steady-state detection
HOP_MS = 10.0            # RMS-frame hop
PEAK_RMS_TOL_DB = 3.0    # within this many dB of peak counts as steady-state
FORMANT_FREQ_MIN_HZ = 90.0
FORMANT_FREQ_MAX_HZ = 7000.0
N_KEEP = 6
DUMMY_FREQ_HZ = 7000.0
DUMMY_RADIUS = 0.5
# Pre-emphasis is applied only when the steady-state spectrum tilts down
# steeper than this. Flat-source synthetic inputs (impulse trains, white
# noise) measure near 0 dB/oct and skip pre-emphasis; voiced speech and
# typical low-tilted natural sources measure ≲ −5 dB/oct and trigger it.
PREEMPH_TILT_BAND_HZ = (200.0, 4000.0)
PREEMPH_TILT_THRESHOLD_DB_PER_OCT = -3.0


# ── load + resample ─────────────────────────────────────────────────────────
def load_mono_16k(path: Path) -> tuple[np.ndarray, int]:
    """Read wav, fold to mono float64 in [-1,1], resample to 16 kHz."""
    sr, x = wavfile.read(path)
    if x.dtype == np.int16:
        x = x.astype(np.float64) / 32768.0
    elif x.dtype == np.int32:
        x = x.astype(np.float64) / 2147483648.0
    elif x.dtype == np.uint8:
        x = (x.astype(np.float64) - 128.0) / 128.0
    else:
        x = x.astype(np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)
    sr = int(sr)
    if sr != ANALYSIS_SR:
        g = gcd(sr, ANALYSIS_SR)
        up = ANALYSIS_SR // g
        down = sr // g
        x = resample_poly(x, up, down)
    return x.astype(np.float64), ANALYSIS_SR


# ── steady-state region ─────────────────────────────────────────────────────
def steady_state_region(x: np.ndarray, sr: int) -> tuple[int, int]:
    """Longest contiguous frame-run whose RMS is within PEAK_RMS_TOL_DB of peak.

    Returns sample indices (start, end) of the chosen region.
    """
    frame_n = int(round(FRAME_MS * 1e-3 * sr))
    hop_n = int(round(HOP_MS * 1e-3 * sr))
    if len(x) < frame_n:
        return 0, len(x)

    n_frames = 1 + (len(x) - frame_n) // hop_n
    starts = np.arange(n_frames) * hop_n
    # framewise RMS via strided view-free indexing
    frames = np.stack([x[s:s + frame_n] for s in starts])
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-30)
    peak = max(rms.max(), 1e-30)
    db = 20.0 * np.log10(rms / peak + 1e-30)
    above = db >= -PEAK_RMS_TOL_DB

    best_start_frame, best_len = 0, 0
    cur = None
    for i, v in enumerate(above):
        if v:
            if cur is None:
                cur = i
        elif cur is not None:
            run = i - cur
            if run > best_len:
                best_start_frame, best_len = cur, run
            cur = None
    if cur is not None:
        run = len(above) - cur
        if run > best_len:
            best_start_frame, best_len = cur, run

    if best_len == 0:
        return 0, len(x)
    s = int(starts[best_start_frame])
    e = int(starts[best_start_frame + best_len - 1] + frame_n)
    return s, min(e, len(x))


# ── spectral-tilt detection (gates pre-emphasis) ────────────────────────────
def measure_tilt_db_per_octave(seg: np.ndarray, sr: int) -> float:
    """Linear regression of 20·log10|S(f)| vs log2(f) over the tilt band.

    Operates on a Hamming-windowed copy of the steady-state region — the
    window suppresses edge-leakage so the slope estimate reflects the
    underlying source × envelope spectrum, not boundary discontinuities.

    Positive slope = upward (rising-towards-Nyquist) tilt; negative slope =
    downward (rolling-off) tilt, the canonical voiced-speech case.
    """
    windowed = seg * np.hamming(len(seg))
    mag = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(windowed), d=1.0 / sr)
    log_mag = 20.0 * np.log10(mag + 1e-12)
    lo, hi = PREEMPH_TILT_BAND_HZ
    mask = (freqs >= lo) & (freqs <= hi)
    if mask.sum() < 4:
        return 0.0                              # too narrow to fit; skip preemph
    log_f = np.log2(freqs[mask])
    slope, _intercept = np.polyfit(log_f, log_mag[mask], 1)
    return float(slope)


# ── LPC via autocorrelation + Levinson (solve_toeplitz) ─────────────────────
def lpc_autocorr(x: np.ndarray, order: int) -> np.ndarray:
    """Return LPC polynomial coeffs [1, a_1, ..., a_order] (A(z) form).

    Solves the Yule-Walker normal equations T(r[0..p-1]) a = -r[1..p] via
    scipy.linalg.solve_toeplitz (O(p^2)).
    """
    n = len(x)
    if n <= order:
        raise ValueError(f"signal length {n} <= LPC order {order}; nothing to fit")
    full = np.correlate(x, x, mode="full")
    r = full[n - 1: n + order]  # r[0..order], length order+1
    if r[0] <= 0.0:
        raise ValueError("zero-energy signal; cannot run LPC")
    a_rest = solve_toeplitz(r[:order], -r[1:order + 1])
    return np.concatenate(([1.0], a_rest))


# ── root selection ──────────────────────────────────────────────────────────
def extract_poles(lpc_coeffs: np.ndarray, sr: int) -> list[dict]:
    """Roots of A(z) -> filter -> sort by radius -> keep N_KEEP -> sort by freq."""
    roots = np.roots(lpc_coeffs)
    cand: list[tuple[float, float]] = []
    for z in roots:
        if z.imag <= 0:
            continue                                # one root per conjugate pair
        r = float(abs(z))
        if r >= 1.0:
            continue                                # outside / on unit circle
        f = float(np.angle(z) * sr / (2.0 * np.pi))
        if f < FORMANT_FREQ_MIN_HZ or f > FORMANT_FREQ_MAX_HZ:
            continue
        cand.append((f, r))

    cand.sort(key=lambda fr: fr[1], reverse=True)   # highest radius first
    if len(cand) < N_KEEP:
        print(
            f"WARNING: only {len(cand)} valid pole(s) found inside "
            f"[{FORMANT_FREQ_MIN_HZ}, {FORMANT_FREQ_MAX_HZ}] Hz; "
            f"padding to {N_KEEP} with dummy "
            f"({DUMMY_FREQ_HZ} Hz, r={DUMMY_RADIUS}).",
            file=sys.stderr,
        )
        while len(cand) < N_KEEP:
            cand.append((DUMMY_FREQ_HZ, DUMMY_RADIUS))

    cand = cand[:N_KEEP]
    cand.sort(key=lambda fr: fr[0])                 # final: ascending in freq

    poles = []
    for f, r in cand:
        bw = float(-sr / np.pi * np.log(r)) if r > 0.0 else float("inf")
        poles.append({"freq_hz": f, "radius": r, "bandwidth_hz": bw})
    return poles


# ── driver ──────────────────────────────────────────────────────────────────
def analyse_wav(path: Path) -> dict:
    x, sr = load_mono_16k(path)
    s, e = steady_state_region(x, sr)
    seg = x[s:e].copy()

    # Tilt detection runs on a Hamming-windowed copy of the unprocessed
    # steady-state region. Pre-emphasis is only applied if the source rolls
    # off steeper than the threshold — synthetic flat-spectrum signals
    # (impulse trains, noise) skip it and stay fittable at order 12.
    tilt = measure_tilt_db_per_octave(seg, sr)
    preemph_applied = tilt < PREEMPH_TILT_THRESHOLD_DB_PER_OCT
    if preemph_applied:
        seg = lfilter([1.0, -PRE_EMPH], [1.0], seg)

    # Hamming window the (possibly pre-emphasised) analysis region
    seg = seg * np.hamming(len(seg))
    lpc = lpc_autocorr(seg, LPC_ORDER)
    poles = extract_poles(lpc, sr)
    return {
        "source_file": str(path),
        "sample_rate_analysis": sr,
        "steady_state_ms": [
            round(s * 1000.0 / sr, 3),
            round(e * 1000.0 / sr, 3),
        ],
        "lpc_order": LPC_ORDER,
        "preemphasis": {
            "applied": bool(preemph_applied),
            "measured_tilt_db_per_octave": round(float(tilt), 4),
            "threshold_db_per_octave": PREEMPH_TILT_THRESHOLD_DB_PER_OCT,
            "coefficient": PRE_EMPH if preemph_applied else None,
        },
        "poles": poles,
    }


def print_table(report: dict) -> None:
    s0, s1 = report["steady_state_ms"]
    pe = report["preemphasis"]
    print(f"# {report['source_file']}")
    print(
        f"  sr={report['sample_rate_analysis']} Hz   "
        f"steady-state {s0:.1f}–{s1:.1f} ms   "
        f"order={report['lpc_order']}"
    )
    print(
        f"  preemph: applied={pe['applied']}  "
        f"tilt={pe['measured_tilt_db_per_octave']:+.2f} dB/oct  "
        f"threshold={pe['threshold_db_per_octave']:+.1f} dB/oct"
        + (f"  coef={pe['coefficient']}" if pe['applied'] else "")
    )
    print(f"  {'#':>2}  {'freq_hz':>10}  {'radius':>8}  {'bw_hz':>10}")
    for i, p in enumerate(report["poles"]):
        print(
            f"  {i+1:>2}  {p['freq_hz']:>10.2f}  "
            f"{p['radius']:>8.4f}  {p['bandwidth_hz']:>10.2f}"
        )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("wav", type=Path, help="Input .wav file")
    args = ap.parse_args(argv)

    if not args.wav.exists():
        print(f"!! {args.wav} not found", file=sys.stderr)
        return 1

    report = analyse_wav(args.wav)
    print_table(report)

    out_path = args.wav.with_suffix(".lpc.json")
    out_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nwrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
