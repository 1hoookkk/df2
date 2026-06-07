#!/usr/bin/env python3
"""Emit a deterministic broadband WAV for transfer-function capture.

Use the same generated file as the dry source for every chain-state bounce.
Pink noise is the default because it gives the capture fitter useful energy
across the audible band without making the high frequencies dominate.

Usage:
    python tools/make_broadband.py --out captures/dry_pink.wav
    python tools/make_broadband.py --out captures/dry_pink.wav --sr 48000 --length 20
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from scipy.io import wavfile


def broadband(kind: str, sr: int, length: float, amplitude: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(round(length * sr))
    if n < 256:
        raise ValueError("length must contain at least 256 samples")
    signal = rng.standard_normal(n)
    if kind == "pink":
        spectrum = np.fft.rfft(signal)
        freqs = np.fft.rfftfreq(n, 1.0 / sr)
        freqs[0] = 1.0
        signal = np.fft.irfft(spectrum / np.sqrt(freqs), n)
    peak = float(np.max(np.abs(signal)))
    if peak > 0.0:
        signal *= amplitude / peak
    return signal.astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="output WAV path")
    ap.add_argument("--kind", choices=("pink", "white"), default="pink")
    ap.add_argument("--sr", type=int, default=48000, help="sample rate in Hz")
    ap.add_argument("--length", type=float, default=20.0, help="duration in seconds")
    ap.add_argument("--amplitude", type=float, default=0.25,
                    help="peak amplitude in [0, 1]")
    ap.add_argument("--seed", type=int, default=13013)
    args = ap.parse_args()

    if args.sr <= 0:
        raise ValueError("--sr must be positive")
    if not 0.0 < args.amplitude <= 1.0:
        raise ValueError("--amplitude must be in (0, 1]")

    signal = broadband(args.kind, args.sr, args.length, args.amplitude, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(args.out), args.sr, signal)
    print(f"wrote: {args.out}")
    print(f"  {args.kind} noise  sr={args.sr} Hz  samples={len(signal)}  "
          f"seconds={len(signal) / args.sr:.3f}  peak={float(np.max(np.abs(signal))):.3f}")
    print()
    print("Bounce this exact file through each chain state. Do not normalize,")
    print("trim, fade, dither, or change gain between the four wet captures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
