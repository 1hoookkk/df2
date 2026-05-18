#!/usr/bin/env python3
"""null_test.py — the validation gate for df2 body authoring.

Renders two WAVs are required:
  reference:  E-mu wet render at a known M/Q position
  candidate:  df2 wet render through the authored body at the same position

The tool sample-aligns the two, inverts one, sums them, and reports the
null depth in dB. Pass threshold per FRAME_BANK.md: ≤ -60 dB.

Usage:
    python tools/null_test.py reference.wav candidate.wav
    python tools/null_test.py reference.wav candidate.wav --max-lag 2048

Stdlib + numpy + scipy only. No other deps.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate


def load_wav_mono(path: Path) -> tuple[int, np.ndarray]:
    """Load a WAV as float64 mono. Mixes stereo to mono if needed."""
    sr, data = wavfile.read(path)
    if data.dtype.kind in ("i", "u"):
        # int PCM → float32 range
        info = np.iinfo(data.dtype)
        max_abs = max(abs(info.min), abs(info.max))
        data = data.astype(np.float64) / max_abs
    else:
        data = data.astype(np.float64)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return sr, data


def align(ref: np.ndarray, cand: np.ndarray, max_lag: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Cross-correlate to find integer-sample lag of cand vs ref.
    Returns aligned (ref, cand) and the applied lag.
    """
    n = min(len(ref), len(cand))
    a = ref[:n] - ref[:n].mean()
    b = cand[:n] - cand[:n].mean()
    # Limit correlation window for speed
    window = min(n, max(max_lag * 8, 16384))
    xcorr = correlate(a[:window], b[:window], mode="full")
    center = window - 1
    search_min = max(0, center - max_lag)
    search_max = min(len(xcorr), center + max_lag + 1)
    lag = int(np.argmax(xcorr[search_min:search_max])) + search_min - center
    if lag > 0:
        cand_aligned = np.concatenate([np.zeros(lag), cand])[:len(ref)]
        ref_aligned = ref[:len(cand_aligned)]
    elif lag < 0:
        ref_aligned = np.concatenate([np.zeros(-lag), ref])[:len(cand)]
        cand_aligned = cand[:len(ref_aligned)]
    else:
        m = min(len(ref), len(cand))
        ref_aligned, cand_aligned = ref[:m], cand[:m]
    return ref_aligned, cand_aligned, lag


def null_depth_db(ref: np.ndarray, cand: np.ndarray) -> tuple[float, float, float]:
    """Returns (null_dB, ref_rms_dB, residual_rms_dB)."""
    m = min(len(ref), len(cand))
    ref, cand = ref[:m], cand[:m]
    residual = ref - cand
    ref_rms = np.sqrt(np.mean(ref**2)) + 1e-30
    res_rms = np.sqrt(np.mean(residual**2)) + 1e-30
    null_db = 20 * np.log10(res_rms / ref_rms)
    return null_db, 20 * np.log10(ref_rms), 20 * np.log10(res_rms)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Null test reference vs candidate WAV.")
    p.add_argument("reference", type=Path)
    p.add_argument("candidate", type=Path)
    p.add_argument("--max-lag", type=int, default=2048,
                   help="Max sample lag to search for alignment (default 2048).")
    p.add_argument("--threshold-db", type=float, default=-60.0,
                   help="Pass threshold in dB (default -60).")
    args = p.parse_args(argv)

    sr_ref, ref = load_wav_mono(args.reference)
    sr_cand, cand = load_wav_mono(args.candidate)

    if sr_ref != sr_cand:
        print(f"FAIL: sample rate mismatch ({sr_ref} vs {sr_cand} Hz)", file=sys.stderr)
        return 2

    ref_aligned, cand_aligned, lag = align(ref, cand, args.max_lag)
    null_db, ref_db, res_db = null_depth_db(ref_aligned, cand_aligned)

    passed = null_db <= args.threshold_db
    status = "PASS" if passed else "FAIL"

    print(f"reference:    {args.reference}")
    print(f"candidate:    {args.candidate}")
    print(f"sample rate:  {sr_ref} Hz")
    print(f"applied lag:  {lag} samples")
    print(f"reference RMS: {ref_db:+7.2f} dBFS")
    print(f"residual RMS:  {res_db:+7.2f} dBFS")
    print(f"null depth:    {null_db:+7.2f} dB  (threshold {args.threshold_db:+.1f} dB)")
    print(f"{status}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
