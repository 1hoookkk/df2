"""ZAP - the swipe-percussion body (audition/demo body, not a bank promotion).

Concept (Tyson 2026-07-12): the fast MORPH swipe IS the drum hit. High-ring
resonators tuned to a 12-TET A-family overtone set; a flick through the
surface manufactures a pitched percussive transient from any input.

Frame structure: the HEDZ frame, measured from true ROM bytes (LAWS L23/L24/L25):
  - crown @1 = the TOP pole; talkers 2-5; floor @6 owns the body's ONLY
    unit-radius zero (the hard cliff - a fixture of the format)
  - ONE shared gain word per corner: 0.56 (hedz's measured word; six shared
    words = ~-30 dB distributed headroom so crowns can spike under Q)
  - Q verb: BLOOM (radii -> ~0.9985, centers hold - the hedz/alkaline pose)
Frequencies from the 12-TET table (A440) - a measured table, never invented
Hz (landing-peaks precedent). Radii are designed ring times.

Audit: exact 240 bytes, corner peak readback vs authored Hz, 17x17 packed
grid Schur + finite through the shipped trench_core.dll words.
"""
from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from pyruntime.designer_compile import SR  # the engine's authoring rate
from pyruntime import trench_ffi
from tools.body240_clip import encode_clip

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dev", "tmp", "zapkit")

# 12-TET A440 table (Hz). LOW scene = A-family low register (kick/tom zone),
# HIGH scene = same family three octaves up (zap/laser zone). HEDZ frame
# order: crown @1 = the TOP pole, talkers 2-5, floor @6 (+ the unit zero).
# (stage role, low_hz, high_hz)
STAGES = [
    ("crown",  440.00, 3520.00),   # A4 -> A7 (top pole)
    ("talker", 110.00,  880.00),   # A2 -> A5
    ("talker", 164.81, 1318.51),   # E3 -> E6
    ("talker", 220.00, 1760.00),   # A3 -> A6
    ("talker", 329.63, 2637.02),   # E4 -> E7
    ("floor",   55.00,  440.00),   # A1 -> A4 (unit-radius zero: the cliff)
]

GAIN_WORD = 0.56  # hedz's measured shared gain word (L24) - all stages, all corners
R_Q0 = 0.9850     # tight ring (~12 ms at the authoring rate)
R_Q100 = 0.9985   # BLOOM (~120 ms ring) - Q verb: BLOOM, centers hold


def stage_words(hz: float, r: float, unit_zero: bool) -> list[int]:
    """One stage -> 5 packed u16 words via the shipped encoder (f32 law)."""
    a1 = -2.0 * r * math.cos(2.0 * math.pi * hz / SR)
    a1, r = float(np.float32(a1)), float(np.float32(r))
    # zero law: floor carries the body's only unit-circle zero (L23);
    # everyone else runs matched pure zeros (flat off-resonance, serial-safe)
    if unit_zero:
        val2 = a1 * (1.0 / r - 1.0)
        val3 = r * r - 1.0
    else:
        val2, val3 = 0.0, 0.0
    # kernel form (resonator path - encode.py law), shared gain word = c4
    b0 = GAIN_WORD
    b1 = a1 + val2
    b2 = r * r - val3
    c0 = 2.0 + b1 / b0
    c1 = 1.0 - b2 / b0
    c2 = 2.0 + a1
    c3 = 1.0 - r * r
    c4 = b0
    # words: c0=4*d0+d1, c1=d1, c2=4*d2+d3, c3=d3, c4=4*d4
    d = [(c0 - c1) / 4.0, c1, (c2 - c3) / 4.0, c3, c4 / 4.0]
    return [trench_ffi.encode(v) for v in d]


def corner_rows(morph_high: bool, r: float) -> list[tuple[int, ...]]:
    return [tuple(stage_words(hi if morph_high else lo, r, role == "floor"))
            for role, lo, hi in STAGES]


def kernel_rho(rows: list[tuple[float, ...]]) -> float:
    """Max pole magnitude across the 6 decoded kernel rows (c0..c4)."""
    worst = 0.0
    for (c0, c1, c2, c3, c4) in rows:
        if not all(math.isfinite(v) for v in (c0, c1, c2, c3, c4)):
            return math.inf
        roots = np.roots([1.0, c2 - 2.0, 1.0 - c3])
        worst = max(worst, float(np.max(np.abs(roots))))
    return worst


def response_peak_hz(rows: list[tuple[float, ...]]) -> float:
    """Strongest response peak of the decoded cascade (for corner readback)."""
    freqs = np.geomspace(30.0, SR * 0.45, 1200)
    w = 2.0 * np.pi * freqs / SR
    z1 = np.exp(-1j * w)
    h = np.ones_like(z1)
    for (c0, c1, c2, c3, c4) in rows:
        b0, b1, b2 = c4, (c0 - 2.0) * c4, (1.0 - c1) * c4
        a1, a2 = c2 - 2.0, 1.0 - c3
        h *= (b0 + b1 * z1 + b2 * z1 * z1) / (1.0 + a1 * z1 + a2 * z1 * z1)
    return float(freqs[int(np.argmax(np.abs(h)))])


def main() -> None:
    # canonical corner order: A=M0_Q0, B=M100_Q0, C=M0_Q100, D=M100_Q100
    corners = {
        "A": corner_rows(False, R_Q0),
        "B": corner_rows(True, R_Q0),
        "C": corner_rows(False, R_Q100),
        "D": corner_rows(True, R_Q100),
    }
    body = trench_ffi.body_bytes_from_corner_words(corners)
    assert len(body) == 240, len(body)

    # --- audit 1: corner peak readback lands ON an authored 12-TET centre ---
    for (m, q) in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
        rows = trench_ffi.packed_interpolate(body, m, q)
        got = response_peak_hz(list(rows))
        authored = [s[1] if m < 0.5 else s[2] for s in STAGES]
        cents = min(abs(1200.0 * math.log2(got / hz)) for hz in authored)
        print(f"corner M{int(m*100)}_Q{int(q*100)}: peak {got:7.1f} Hz -> nearest authored centre {cents:+.0f} cents")
        assert cents < 60.0, "corner peak not on an authored centre"

    # --- audit 2: 17x17 packed grid, Schur + finite -------------------------
    worst = 0.0
    for i in range(17):
        for j in range(17):
            rho = kernel_rho(list(trench_ffi.packed_interpolate(body, i / 16.0, j / 16.0)))
            worst = max(worst, rho)
    print(f"17x17 grid worst rho = {worst:.6f}  (must be < 1)")
    assert worst < 1.0, "unstable grid point"

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "ZAP.body240")
    with open(path, "wb") as f:
        f.write(body)
    clip = encode_clip(body)
    with open(os.path.join(OUT_DIR, "ZAP.clip.txt"), "w") as f:
        f.write(clip + "\n")
    print(f"\nZAP.body240 written ({path})")
    print(f"clip ({len(clip)} chars):\n{clip}")


if __name__ == "__main__":
    main()
