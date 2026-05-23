#!/usr/bin/env python3
"""lpc_test_input_gen.py — synthetic verification inputs for lpc_extract.py.

Writes two fixtures next to each other:

  dev/tmp/lpc_test_input.wav         — 500 ms 110 Hz impulse train ->
                                       6-pole all-pole (F = 730, 1090, 2440,
                                       3500, 4500, 5500 Hz, r = 0.96).
                                       Flat source -> near-zero tilt ->
                                       lpc_extract should SKIP pre-emphasis.

  dev/tmp/lpc_test_input_voiced.wav  — same impulse train pushed through
                                       a voiced-source-like tilt filter
                                       1 / (1 - 0.97·z^-1) BEFORE the all-
                                       pole stage, then the same 6-pole.
                                       Voiced tilt (~-6 dB/oct) -> tilt
                                       detector should TRIGGER pre-emphasis,
                                       which exactly inverts the source
                                       tilt and restores fittability.

Ground-truth formants are the same in both. The LPC extractor must
recover them within ±20 Hz from either fixture (spec gate).

scipy / numpy only.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import lfilter

SR = 16000
DUR_S = 0.5
F0 = 110.0
GROUND_TRUTH = [
    (730.0,  0.96),
    (1090.0, 0.96),
    (2440.0, 0.96),
    (3500.0, 0.96),
    (4500.0, 0.96),
    (5500.0, 0.96),
]
TILT_COEF = 0.97              # voiced-source-like tilt: 1 / (1 - 0.97 z^-1)

OUT_FLAT = Path("dev/tmp/lpc_test_input.wav")
OUT_VOICED = Path("dev/tmp/lpc_test_input_voiced.wav")


def impulse_train(n: int, sr: int, f0: float) -> np.ndarray:
    x = np.zeros(n, dtype=np.float64)
    period = sr / f0
    k = 0
    while True:
        idx = int(round(k * period))
        if idx >= n:
            break
        x[idx] = 1.0
        k += 1
    return x


def all_pole_denominator(formants: list[tuple[float, float]], sr: int) -> np.ndarray:
    a = np.array([1.0])
    for f, r in formants:
        theta = 2.0 * np.pi * f / sr
        a = np.convolve(a, [1.0, -2.0 * r * np.cos(theta), r * r])
    return a


def write_wav_int16(path: Path, x: np.ndarray, sr: int) -> None:
    y = x / (np.max(np.abs(x)) + 1e-12) * 0.9
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, sr, (y * 32767.0).astype(np.int16))


def main() -> int:
    n = int(round(SR * DUR_S))
    train = impulse_train(n, SR, F0)
    a6 = all_pole_denominator(GROUND_TRUTH, SR)
    assert len(a6) == 13, f"expected 12th-order denom (13 coefs), got {len(a6)}"

    # Fixture 1: flat source.
    y_flat = lfilter([1.0], a6, train)
    write_wav_int16(OUT_FLAT, y_flat, SR)

    # Fixture 2: voiced source. Tilt and all-pole denom convolve into one
    # 13th-order filter; one lfilter pass yields the same result as two.
    a_tilt = np.array([1.0, -TILT_COEF])
    a_voiced = np.convolve(a_tilt, a6)
    y_voiced = lfilter([1.0], a_voiced, train)
    write_wav_int16(OUT_VOICED, y_voiced, SR)

    print(f"wrote {OUT_FLAT}   ({n} samples @ {SR} Hz, flat source)")
    print(f"wrote {OUT_VOICED} ({n} samples @ {SR} Hz, voiced tilt "
          f"1/(1 - {TILT_COEF}·z^-1) before 6-pole)")
    print(f"F0 = {F0} Hz, {len(GROUND_TRUTH)} formants @ r = 0.96:")
    for i, (f, r) in enumerate(GROUND_TRUTH, 1):
        print(f"  F{i} = {f:.1f} Hz   r = {r:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
