"""Locks the doctrine invariants of the single owned corner primitive (corner_author).
If any of these break, a corner could ship that violates the doctrine — which is exactly
the regression class this consolidation exists to prevent.
    run:  python -m pytest tools/test_corner_author.py -q
"""
import math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from tools import corner_author as ca
from tools import author_corner_library as lib
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
import pyruntime.trench_ffi as ff

def _pole_freq(sec):
    c0, c1, c2, c3, c4 = sec
    a1, a2 = c2 - 2, 1 - c3
    r = math.sqrt(max(a2, 1e-9))
    return math.acos(max(-1, min(1, -a1 / (2 * r)))) * ca.SR / (2 * math.pi)

def test_every_library_posture_is_unity_dc_and_sane():
    """[LAW] every authored corner: DC forced to unity (sub passes at unity, no boost)."""
    for group, corners in lib.LIBRARY.items():
        for name, spec in corners.items():
            secs, rep = ca.compile(spec)
            assert rep["ok"], f"{group}/{name} rejected: {rep}"
            assert abs(rep["dc_db"]) < 0.1, f"{group}/{name} DC off unity: {rep['dc_db']} dB"
            assert rep["peak_db"] < 40.0, f"{group}/{name} overloads: {rep['peak_db']} dB"

def test_body240_is_240_bytes_and_renders_finite():
    """The one source-critical step: verbatim 240-byte encode reads back through the player."""
    secs, _ = ca.compile(ca.vowel("i"))
    raw = ca.body240([secs] * 4)
    assert len(raw) == 240
    resp = cascade_response_db([EncodedCoeffs(*r) for r in ff.packed_interpolate(raw, 0.5, 0.5)],
                               np.array([60.0, 1000.0, 8000.0]), ca.SR)
    assert np.all(np.isfinite(resp))

def test_bandwidth_gain_law_6db_per_halving():
    """[LAW Klatt] peak amplitude proportional to 1/Bw: halving Bw = +6 dB exactly."""
    assert abs((ca.gain_from_bw(50) - ca.gain_from_bw(100)) - 6.0) < 1e-9
    assert abs((ca.gain_from_bw(100) - ca.gain_from_bw(200)) - 6.0) < 1e-9

def test_golden_comb_ratio_and_start():
    """[LAW Morpheus Flange3.4] notches at 40 Hz x 1.61^k."""
    fs = [s[1] for s in ca.golden_comb(5)]
    assert abs(fs[0] - ca.COMB_START) < 0.5
    for a, b in zip(fs, fs[1:]):
        assert abs(b / a - ca.GOLDEN) < 0.02

def test_fixed_slots_not_sorted():
    """Slot registration: a high-then-low spec keeps the HIGH section in slot 0 (no sort) —
    this is what lets poles CROSS under the packed morph instead of sliding."""
    secs, _ = ca.compile([ca.PK(3000, 0.3, 10), ca.PK(300, 0.3, 10)])
    assert _pole_freq(secs[0]) > 1500

def test_vowel_uses_exact_klatt_freqs():
    """[LAW Klatt Table II] /i/ F1 = 310 Hz exactly (not Peterson-Barney 270)."""
    assert abs(ca.vowel("i")[0][1] - 310) < 1.0

def test_coupling_floor_200hz():
    """[LAW Klatt] adjacent formants within a corner cannot be closer than 200 Hz."""
    fs = [s[1] for s in ca.vowel("i")]
    for a, b in zip(fs, fs[1:]):
        assert b - a >= 200 - 1.0
