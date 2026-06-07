#!/usr/bin/env python3
"""author_lanes — root-domain (pole / zero / gain) -> packed-body-v1 front-end.

The missing authoring layer. The old forge/ that turned hand-placed roots into a
240-byte body was torn down in the v2 pivot; author_body.py only eats pre-packed
u16 words. This rebuilds the root-domain front-end *without* forking the packed
math:

    lane (pole pair + zero pair + gain)
      -> general DF2T biquad [b0, b1, b2, a1, a2]
      -> kernel [c0..c4]                       (the documented bijection)
      -> packed u16 words                      via packed_interp.coeffs_to_words
      -> packed-body-v1 JSON                   compiled by tools/author_body.py

A body is exactly 4 corners x 6 persistent lanes x 5 u16 words = 240 bytes.
Corner order matches the runtime: M0_S0, M1_S0, M0_S1, M1_S1.
Lane identity is preserved by construction: lane i in every corner is the same
serialized actor; only its roots and gain move. We never re-sort lanes by
frequency (lane N only ever interpolates against lane N at runtime).

Sound==plot discipline (the kernel/biquad landmine): we author ONE rep — a plain
biquad — encode it to the words the shipped engine actually runs, and any plot is
read back from those SAME words. `--verify` proves the encode->decode round-trip
matches the intended magnitude, so the curve you see is the filter you hear.

CLI:
    python -m tools.author_lanes --verify          # round-trip proof, no files
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.packed_interp import (  # noqa: E402
    coeffs_to_words,
    kernel_to_biquad,
    words_to_coeffs,
)

# df2 bodies are authored in the chip-native domain. author_body.py enforces this
# exact rate; the shipped player resamples to host SR on playback.
AUTHORING_SR = 39062.5

# Runtime corner order. Tyson's M0/S0, M1/S0, M0/S1, M1/S1 map onto author_body's
# M0_Q0, M100_Q0, M0_Q100, M100_Q100 (Secondary == Q).
CORNER_LABELS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
STAGES = 6
WORDS_PER_STAGE = 5


# ───────────────────────────── root domain → biquad ─────────────────────────


def _conj_pair(freq_hz: float, radius: float, sr: float) -> tuple[float, float]:
    """Second-order pair coefficients [x1, x2] for a complex-conjugate root at
    `freq_hz` with magnitude `radius`:  z^2 + x1 z + x2  ->  (x1, x2)."""
    theta = 2.0 * math.pi * (freq_hz / sr)
    return (-2.0 * radius * math.cos(theta), radius * radius)


def lane_biquad(
    *,
    pole_hz: float,
    pole_r: float,
    zero_hz: Optional[float] = None,
    zero_r: float = 0.0,
    gain: float = 1.0,
    sr: float = AUTHORING_SR,
) -> tuple[float, float, float, float, float]:
    """One persistent lane as a general biquad (b0, b1, b2, a1, a2).

    Pole pair sets the denominator (resonance). Zero pair sets the numerator
    (the carve / counterweight). `gain` scales the whole numerator (b0). A lane
    with `zero_hz=None` has a flat numerator [gain, 0, 0] (pure resonator).
    """
    a1, a2 = _conj_pair(pole_hz, pole_r, sr)
    if zero_hz is None:
        n1, n2 = 0.0, 0.0
    else:
        n1, n2 = _conj_pair(zero_hz, zero_r, sr)
    b0 = float(gain)
    return (b0, b0 * n1, b0 * n2, a1, a2)


def biquad_to_kernel(
    b0: float, b1: float, b2: float, a1: float, a2: float
) -> tuple[float, float, float, float, float]:
    """Inverse of packed_interp.kernel_to_biquad. c4=b0; c0=b1/b0+2; c1=1-b2/b0;
    c2=a1+2; c3=1-a2."""
    if abs(b0) < 1e-12:
        raise ValueError("lane gain b0 ~ 0; numerator would vanish")
    return (b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


def lane_words(lane: dict[str, Any], sr: float = AUTHORING_SR) -> tuple[int, ...]:
    """Root-domain lane dict -> 5 packed u16 words (canonical FFI encoder)."""
    bq = lane_biquad(
        pole_hz=lane["pole_hz"],
        pole_r=lane["pole_r"],
        zero_hz=lane.get("zero_hz"),
        zero_r=lane.get("zero_r", 0.0),
        gain=lane.get("gain", 1.0),
        sr=sr,
    )
    return coeffs_to_words(*biquad_to_kernel(*bq))


def body_to_packed_v1(
    name: str,
    corners: dict[str, list[dict[str, Any]]],
    *,
    boost: float = 1.0,
    sr: float = AUTHORING_SR,
) -> dict[str, Any]:
    """Assemble a packed-body-v1 doc that tools/author_body.py compiles.

    `corners` maps each of M0_S0 / M1_S0 / M0_S1 / M1_S1 to a list of exactly 6
    lane dicts (the persistent lanes, in fixed order)."""
    alias = {"M0_S0": "M0_Q0", "M1_S0": "M100_Q0", "M0_S1": "M0_Q100", "M1_S1": "M100_Q100"}
    out_corner: dict[str, Any] = {}
    for key, lanes in corners.items():
        label = alias.get(key, key)
        if label not in CORNER_LABELS:
            raise ValueError(f"unknown corner {key!r}")
        if len(lanes) != STAGES:
            raise ValueError(f"corner {key}: expected {STAGES} lanes, got {len(lanes)}")
        out_corner[label] = {
            "words": [[int(w) for w in lane_words(lane, sr)] for lane in lanes]
        }
    missing = [c for c in CORNER_LABELS if c not in out_corner]
    if missing:
        raise ValueError(f"missing corner(s): {missing}")
    return {
        "format": "packed-body-v1",
        "name": name,
        "boost": boost,
        "authoring_sample_rate_hz": sr,
        "corner": out_corner,
    }


# ───────────────────────────── magnitude + round-trip ───────────────────────


def biquad_mag_db(bq: tuple[float, ...], freqs: np.ndarray, sr: float) -> np.ndarray:
    """|H(e^jw)| in dB for one biquad over `freqs`."""
    b0, b1, b2, a1, a2 = bq
    w = 2.0 * np.pi * (freqs / sr)
    z1 = np.exp(-1j * w)
    z2 = np.exp(-2j * w)
    num = b0 + b1 * z1 + b2 * z2
    den = 1.0 + a1 * z1 + a2 * z2
    h = np.abs(num) / np.maximum(np.abs(den), 1e-12)
    return 20.0 * np.log10(np.maximum(h, 1e-9))


def pole_radius(a1: float, a2: float) -> float:
    disc = a1 * a1 - 4.0 * a2
    if disc >= 0.0:  # real roots
        r = (-a1 + math.sqrt(disc)) / 2.0
        return max(abs(r), abs((-a1 - math.sqrt(disc)) / 2.0))
    return math.sqrt(max(a2, 0.0))  # complex pair magnitude = sqrt(a2)


def realized_biquad(bq: tuple[float, ...]) -> tuple[float, ...]:
    """Push a biquad through encode -> decode and return what the engine runs."""
    words = coeffs_to_words(*biquad_to_kernel(*bq))
    return kernel_to_biquad(words_to_coeffs(words))


def verify(sr: float = AUTHORING_SR) -> int:
    """Round-trip proof: intended magnitude vs realized-after-quantization, over
    a bank of lanes spanning the ranges seen in real bodies. The gate is that the
    curve we author is the curve the shipped engine produces."""
    freqs = np.geomspace(40.0, sr / 2.0 * 0.98, 600)
    band = (freqs >= 50.0) & (freqs <= 16000.0)
    bank = [
        # label, pole_hz, pole_r, zero_hz, zero_r, gain
        ("low resonator",        120.0, 0.985, None,    0.0,  0.55),
        ("mid resonator hi-Q",  1000.0, 0.997, None,    0.0,  0.55),
        ("local carve below",   2500.0, 0.990, 1700.0,  0.96, 0.55),
        ("local carve above",   2500.0, 0.990, 3600.0,  0.96, 0.55),
        ("remote counterweight", 800.0, 0.965, 9000.0,  0.75, 0.55),
        ("near-edge cap zero",  8000.0, 0.949, 17900.0, 0.9999, 0.55),
        ("hot center gain",     3000.0, 0.992, 2800.0,  0.97, 1.20),
        ("broad low-Q tilt",     400.0, 0.860, 6000.0,  0.55, 0.55),
        ("upper bite",          5500.0, 0.985, 4800.0,  0.94, 0.55),
        ("deep narrow notch",   1500.0, 0.980, 1500.0,  0.999, 0.55),
    ]
    print(f"round-trip proof @ {sr:.1f} Hz  (intended biquad vs shipped-engine realized)")
    print(f"{'lane':24s} {'maxErr dB':>10s} {'peakErr dB':>11s} {'poleR':>8s} {'realR':>8s}")
    worst = 0.0
    for label, p_hz, p_r, z_hz, z_r, g in bank:
        bq = lane_biquad(pole_hz=p_hz, pole_r=p_r, zero_hz=z_hz, zero_r=z_r, gain=g, sr=sr)
        rbq = realized_biquad(bq)
        m0 = biquad_mag_db(bq, freqs, sr)
        m1 = biquad_mag_db(rbq, freqs, sr)
        err = np.abs(m1 - m0)[band]
        # error at the resonant peak (where it matters most)
        peak_i = int(np.argmax(m0[band]))
        max_err = float(np.max(err))
        peak_err = float(err[peak_i])
        worst = max(worst, max_err)
        print(f"{label:24s} {max_err:10.3f} {peak_err:11.3f} "
              f"{pole_radius(bq[3], bq[4]):8.4f} {pole_radius(rbq[3], rbq[4]):8.4f}")
    print(f"\nworst-case max error across band: {worst:.3f} dB")
    ok = worst < 1.0
    print("VERDICT:", "PASS — sound==plot holds, safe to author" if ok
          else "FAIL — quantization breaks the shape; do not author yet")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true",
                    help="run the encode/decode round-trip proof and exit")
    ap.add_argument("--sr", type=float, default=AUTHORING_SR, help="authoring sample rate")
    args = ap.parse_args(argv)
    if args.verify:
        return verify(args.sr)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
