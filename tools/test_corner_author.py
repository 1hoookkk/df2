"""Locks the invariants of the owned corner primitive (corner_author), now thin over the
canonical corner_words primitives. run: python -m pytest tools/test_corner_author.py -q
"""
import math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from tools import corner_author as ca
from tools import author_corner_library as lib
from tools.corner_words import bp
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
import pyruntime.trench_ffi as ff

def _pole_freq(e):
    a1, a2 = e.c2 - 2, 1 - e.c3
    r = math.sqrt(max(a2, 1e-9))
    return math.acos(max(-1, min(1, -a1 / (2 * r)))) * ca.SR / (2 * math.pi)

def test_every_posture_ok_and_no_sub_boost():
    for group, corners in lib.LIBRARY.items():
        for name, stages in corners.items():
            _, _, rep = ca.compile(stages)
            assert rep["ok"], f"{group}/{name} rejected: {rep}"
            assert rep["sub_db"] < 2.0, f"{group}/{name} boosts sub: {rep['sub_db']} dB"

def test_body240_is_240_bytes_and_renders_finite():
    _, words, _ = ca.compile(ca.vowel("i"))
    raw = ca.body240([words] * 4)
    assert len(raw) == 240
    resp = cascade_response_db([EncodedCoeffs(*r) for r in ff.packed_interpolate(raw, 0.5, 0.5)],
                               np.array([60.0, 1000.0, 8000.0]), ca.SR)
    assert np.all(np.isfinite(resp))

def test_authoring_uses_canonical_primitives_not_reinvented_dsp():
    """corner_author composes corner_words primitives — no private RBJ/kernel realizer."""
    assert not hasattr(ca, "_peaking") and not hasattr(ca, "_lowpass")
    assert ca.bp is bp  # re-exported, same object

def test_vowel_uses_exact_klatt_freq():
    coeffs, _, _ = ca.compile(ca.vowel("i"))
    assert abs(_pole_freq(coeffs[0]) - 310) < 5.0   # Klatt /i/ F1 = 310 (not P-B 270)

def test_fixed_slots_not_sorted():
    coeffs, _, _ = ca.compile([bp(3000, 0.98), bp(300, 0.98)])
    assert _pole_freq(coeffs[0]) > 1500           # slot 0 stays the 3 kHz section

def test_coupling_floor_200hz():
    coeffs, _, _ = ca.compile(ca.vowel("i"))
    fs = sorted(_pole_freq(e) for e in coeffs if abs(e.c4 - 1.0) > 1e-6 or _pole_freq(e) > 50)[:5]
    for a, b in zip(fs, fs[1:]):
        if b < 4000:
            assert b - a >= 200 - 5.0
