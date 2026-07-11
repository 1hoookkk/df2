"""VOICE - the realistic vocal body, built DIRECTLY from the measured tables.

Construction (Tyson 2026-07-12, "most realistic sounding one possible"):
Peterson-Barney formant anchors + Klatt bandwidths - the exact tables the
repo's physical throat model uses - composed under the anatomy law. The
raw-audio ARMA fitter was tried first and taught the constitution's lesson
live: independently fitted corners have NO lane correspondence and the
packed interpolation went Schur-unstable (rho 1.0087, measured). Formant-
index correspondence (F1->F1, F2->F2...) is the honest lift.

Frame (LAWS L23/L24/L25):
  crown @1 = F5 (top pole) | talkers 2-5 = F1..F4 | floor @6 = the glottal
  F0 pole (108 Hz, the model's own constant) + the body's ONLY unit zero.
  ONE shared gain word 0.56 (hedz's measured word).
  Q100 = PRESSED voice: Klatt bandwidths x0.45 - an authored second scene
  (tense throat), not a derived sharpener. Centers hold (BLOOM-family).
Radii from the CLAUDE.md paragraph-8 law: r = exp(-pi * bw / SR).
"""
from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pyruntime import trench_ffi
from pyruntime.designer_compile import SR as RUNTIME_SR
from tools.body240_clip import encode_clip
from tools.make_zap_body import stage_words, kernel_rho, response_peak_hz

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dev", "tmp", "zapkit")

# Peterson-Barney adult-male anchors (aa / iy) + Klatt bandwidths - the same
# tables tools/generate_synthetic_throat_captures.py declares. F0 = 108 Hz is
# that model's own glottal constant.
# (role, aa_hz, iy_hz, bw_hz, unit_zero)
STAGES = [
    ("crown",  3850.0, 3850.0, 200.0, False),   # F5 - top pole
    ("talker",  300.0,  270.0,  55.0, False),   # F1
    ("talker",  870.0, 2290.0,  90.0, False),   # F2
    ("talker", 2240.0, 3010.0, 120.0, False),   # F3
    ("talker", 3300.0, 3300.0, 250.0, False),   # F4
    ("floor",   108.0,  108.0,  55.0, True),    # F0 pole + THE unit zero (the cliff)
]

PRESSED_BW = 0.45     # Q100 pose: tense voice - bandwidths tighten, centers hold


def radius(bw_hz: float) -> float:
    return math.exp(-math.pi * bw_hz / RUNTIME_SR)


def corner_rows(morph_high: bool, bw_scale: float):
    rows = []
    for role, aa, iy, bw, uz in STAGES:
        hz = iy if morph_high else aa
        rows.append(tuple(stage_words(hz, radius(bw * bw_scale), uz)))
    return rows


def main() -> None:
    corners = {
        "A": corner_rows(False, 1.0),
        "B": corner_rows(True, 1.0),
        "C": corner_rows(False, PRESSED_BW),
        "D": corner_rows(True, PRESSED_BW),
    }
    body = trench_ffi.body_bytes_from_corner_words(corners)
    assert len(body) == 240

    for (m, q, high) in ((0.0, 0.0, False), (1.0, 0.0, True),
                         (0.0, 1.0, False), (1.0, 1.0, True)):
        anchors = [(s[2] if high else s[1]) for s in STAGES]
        rows = trench_ffi.packed_interpolate(body, m, q)
        got = response_peak_hz(list(rows))
        cents = min(abs(1200.0 * math.log2(got / hz)) for hz in anchors)
        print(f"corner M{int(m*100)}_Q{int(q*100)}: peak {got:6.1f} Hz -> "
              f"nearest table formant {cents:+.0f} cents")
        assert cents < 60.0, "corner peak not on a table formant"

    worst = 0.0
    for i in range(17):
        for j in range(17):
            worst = max(worst, kernel_rho(list(trench_ffi.packed_interpolate(body, i / 16.0, j / 16.0))))
    print(f"17x17 grid worst rho = {worst:.6f}")
    assert worst < 1.0

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "VOICE.body240")
    with open(path, "wb") as f:
        f.write(body)
    clip = encode_clip(body)
    with open(os.path.join(OUT_DIR, "VOICE.clip.txt"), "w") as f:
        f.write(clip + "\n")
    print(f"\nVOICE.body240 written ({path})")
    print(f"clip:\n{clip}")


if __name__ == "__main__":
    main()
