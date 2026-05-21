#!/usr/bin/env python3
"""make_dirac.py — emit a clean dirac WAV for IR capture.

A single sample at +1.0 at index 0, zeros after. Run this through your
mixer chain at each of the four M/Q corner states; the four bounce
results are the four wet IRs that capture_ir_to_cartridge.py consumes.

Usage:
    python tools/make_dirac.py --out captures/dirac.wav
    python tools/make_dirac.py --out captures/dirac.wav --sr 48000 --length 0.5
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from scipy.io import wavfile


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="output wav path")
    ap.add_argument("--sr", type=int, default=44100, help="sample rate (Hz)")
    ap.add_argument("--length", type=float, default=0.5,
                    help="total length in seconds (impulse + trailing zeros)")
    ap.add_argument("--pre-zeros", type=int, default=0,
                    help="leading zeros before the impulse (rarely needed; 0 by default)")
    ap.add_argument("--amplitude", type=float, default=1.0,
                    help="impulse amplitude in [-1,+1]")
    ap.add_argument("--fmt", choices=("f32", "i24", "i16"), default="f32",
                    help="output sample format (f32 strongly preferred for IR work)")
    args = ap.parse_args()

    n = int(round(args.length * args.sr))
    if n < args.pre_zeros + 1:
        print(f"!! length {args.length}s @ {args.sr}Hz = {n} samples — too short")
        return 1

    sig = np.zeros(n, dtype=np.float32)
    sig[args.pre_zeros] = float(args.amplitude)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.fmt == "f32":
        wavfile.write(str(args.out), args.sr, sig.astype(np.float32))
    elif args.fmt == "i24":
        # scipy.io.wavfile doesn't write 24-bit; round-trip via i32 with i24 range
        s = np.clip(sig, -1.0, 1.0)
        out = (s * (2**23 - 1)).astype(np.int32)
        wavfile.write(str(args.out), args.sr, out)
    else:
        out = (np.clip(sig, -1.0, 1.0) * (2**15 - 1)).astype(np.int16)
        wavfile.write(str(args.out), args.sr, out)

    print(f"wrote: {args.out}")
    print(f"  sr={args.sr} Hz  length={n} samples ({args.length:.3f}s)  "
          f"impulse@{args.pre_zeros} amp={args.amplitude}  fmt={args.fmt}")
    print()
    print("Next: bounce this through your mixer chain four times,")
    print("one per M/Q corner state. Keep the chain LTI (bypass any")
    print("dynamics that respond to level — comp/limit/saturate)")
    print("during the IR pass; the cartridge can only carry LTI behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
