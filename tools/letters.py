"""The TRENCH letter alphabet in PyTorch — a differentiable MIRROR of the canonical
compiler, `trench_core::compiler::section_biquad`.

Why a mirror and not a call: the fitter needs gradients through the letter, and
section_biquad is opaque C. So the formulas are transcribed here EXACTLY and then
held to the real thing by `verify()`, which is run on import. If the Rust ever
changes, the assert fires — the mirror cannot drift silently. Same discipline as
lerp_u16 in fit_body.py.

Do NOT hand-roll a "peak" here. The canonical letters are FLAT-ENDED (unity away
from fc), which is what lets six of them compose in a serial cascade without
fighting. A naive pole/zero pair is not: measured, a hand-rolled PEAK read +15.8 dB
at 20 Hz instead of 0.0, and six of those multiplied to a +142 dB cascade.
"""

import ctypes
import math
from pathlib import Path

import numpy as np
import torch

AUTHORING_SR = 39_062.5
TAU = 2.0 * math.pi

# compiler.rs
FREQ_MIN, FREQ_MAX = 20.0, AUTHORING_SR * 0.49
Q_MIN, Q_MAX = 0.3, 128.0
ZNORM_FLOOR = 1e-9
SHELF_RADIUS_MAX = 0.9992
NOTCH_RADIUS_MAX = 0.999
NOTCH_ZERO_RADIUS_MAX = 0.99999

TYPE_PEAK, TYPE_LOW_SHELF, TYPE_NOTCH = 0, 1, 2
TYPE_LOWPASS, TYPE_HIGHPASS, TYPE_BANDPASS, TYPE_HIGH_SHELF = 3, 4, 5, 6
NAMES = {0: "PEAK", 1: "LOSHELF", 2: "NOTCH", 3: "LP", 4: "HP", 5: "BP", 6: "HISHELF"}
IDS = {v: k for k, v in NAMES.items()}


def _norm(b0, b1, b2, a0, a1, a2):
    a0 = torch.where(a0.abs() < ZNORM_FLOOR, torch.full_like(a0, ZNORM_FLOOR), a0)
    return torch.stack([b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0])


def section_biquad(type_id, fc, q, gain_db):
    """Differentiable [b0,b1,b2,a1,a2]. Mirrors compiler::section_biquad exactly."""
    fc = torch.clamp(fc, FREQ_MIN, FREQ_MAX)
    q = torch.clamp(q, Q_MIN, Q_MAX)
    w0 = TAU * fc / AUTHORING_SR
    sw, cw = torch.sin(w0), torch.cos(w0)
    alpha = sw / (2.0 * q)

    if type_id == TYPE_PEAK:
        a = torch.pow(10.0, gain_db / 40.0)
        return _norm(1.0 + alpha * a, -2.0 * cw, 1.0 - alpha * a,
                     1.0 + alpha / a, -2.0 * cw, 1.0 - alpha / a)

    if type_id == TYPE_HIGH_SHELF:
        a = torch.pow(10.0, gain_db / 40.0)
        t = 2.0 * torch.sqrt(a) * alpha
        return _norm(a * ((a + 1.0) + (a - 1.0) * cw + t),
                     -2.0 * a * ((a - 1.0) + (a + 1.0) * cw),
                     a * ((a + 1.0) + (a - 1.0) * cw - t),
                     (a + 1.0) - (a - 1.0) * cw + t,
                     2.0 * ((a - 1.0) - (a + 1.0) * cw),
                     (a + 1.0) - (a - 1.0) * cw - t)

    if type_id == TYPE_LOW_SHELF:
        a = torch.pow(10.0, gain_db / 20.0)
        rp = torch.clamp(torch.exp(-math.pi * (fc / torch.clamp(q, min=Q_MIN)) / AUTHORING_SR),
                         max=SHELF_RADIUS_MAX)
        a1 = -2.0 * rp * cw
        a2 = rp * rp
        rz = rp
        den_dc = 1.0 + a1 + a2
        den_ny = 1.0 - a1 + a2
        k = a * den_dc / torch.clamp(den_ny, min=ZNORM_FLOOR)
        s = 1.0 + rz * rz
        t = s * (k - 1.0) / torch.clamp(k + 1.0, min=ZNORM_FLOOR)
        cwz = torch.clamp(-t / (2.0 * rz), -1.0, 1.0)
        b1n = -2.0 * rz * cwz
        b2n = rz * rz
        b0 = den_ny / torch.clamp(1.0 - b1n + b2n, min=ZNORM_FLOOR)
        return torch.stack([b0, b0 * b1n, b0 * b2n, a1, a2])

    if type_id == TYPE_NOTCH:
        rp = torch.clamp(torch.exp(-math.pi * (fc / torch.clamp(q, min=0.5)) / AUTHORING_SR),
                         max=NOTCH_RADIUS_MAX)
        depth = torch.clamp(gain_db, max=0.0)
        rz = torch.clamp(1.0 - (1.0 - rp) * torch.pow(10.0, depth / 20.0),
                         0.0, NOTCH_ZERO_RADIUS_MAX)
        a1 = -2.0 * rp * cw
        a2 = rp * rp
        b1n = -2.0 * rz * cw
        b2n = rz * rz
        b0 = (1.0 + a1 + a2) / torch.clamp(1.0 + b1n + b2n, min=ZNORM_FLOOR)
        return torch.stack([b0, b0 * b1n, b0 * b2n, a1, a2])

    g = torch.pow(10.0, gain_db / 20.0)
    if type_id == TYPE_LOWPASS:
        return _norm(g * (1.0 - cw) * 0.5, g * (1.0 - cw), g * (1.0 - cw) * 0.5,
                     1.0 + alpha, -2.0 * cw, 1.0 - alpha)
    if type_id == TYPE_HIGHPASS:
        return _norm(g * (1.0 + cw) * 0.5, -g * (1.0 + cw), g * (1.0 + cw) * 0.5,
                     1.0 + alpha, -2.0 * cw, 1.0 - alpha)
    if type_id == TYPE_BANDPASS:
        z = torch.zeros_like(cw)
        return _norm(g * alpha, z, -g * alpha, 1.0 + alpha, -2.0 * cw, 1.0 - alpha)

    raise ValueError(f"unknown type_id {type_id}")


def verify(tol=1e-9):
    """Hold the mirror to the canonical compiler. Runs on import; asserts on drift."""
    dll = Path(__file__).resolve().parents[1] / "target" / "release" / "trench_core.dll"
    lib = ctypes.CDLL(str(dll))
    lib.trench_section_biquad.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_double,
                                          ctypes.c_double, ctypes.POINTER(ctypes.c_double)]
    worst, worst_at = 0.0, None
    for t in range(7):
        for fc in (25.0, 120.0, 700.0, 3000.0, 12000.0, 19000.0):
            for q in (0.4, 1.0, 4.0, 20.0, 100.0):
                for g in (-24.0, -6.0, 0.0, 6.0, 18.0):
                    out = (ctypes.c_double * 5)()
                    lib.trench_section_biquad(t, fc, q, g, out)
                    ref = np.array(out)
                    mine = section_biquad(
                        t,
                        torch.tensor(fc, dtype=torch.float64),
                        torch.tensor(q, dtype=torch.float64),
                        torch.tensor(g, dtype=torch.float64),
                    ).detach().numpy()
                    err = np.abs(mine - ref).max()
                    if err > worst:
                        worst, worst_at = err, (NAMES[t], fc, q, g)
    assert worst < tol, f"letter mirror DRIFTED from trench-core: {worst:.3e} at {worst_at}"
    return worst, worst_at


_WORST, _WORST_AT = verify()


if __name__ == "__main__":
    print(f"letter mirror matches trench_core::compiler::section_biquad")
    print(f"  worst coefficient error over 7 letters x 6 fc x 5 Q x 5 gains ({7*6*5*5} cases):")
    print(f"    {_WORST:.3e}   (at {_WORST_AT})")


# --------------------------------------------------- biquad -> the five packed words
def biquad_to_words01(bq):
    """[b0,b1,b2,a1,a2] -> the five PRE-ENCODE packed quantities, differentiable.

    The exact inverse of the runtime decode (stage_law::geometry_from_words):
        qz = 1 - v1 ;  pz = 4*v0 + v1 - 2 ;  qp = 1 - v3 ;  pp = 4*v2 + v3 - 2 ;  k = 4*v4
        biquad = [k, k*pz, k*qz, pp, qp]
    """
    b0, b1, b2, a1, a2 = bq[0], bq[1], bq[2], bq[3], bq[4]
    b0s = torch.where(b0.abs() < 1e-12, torch.full_like(b0, 1e-12), b0)
    pz, qz = b1 / b0s, b2 / b0s
    v1 = 1.0 - qz
    v0 = (pz + 2.0 - v1) / 4.0
    v3 = 1.0 - a2
    v2 = (a1 + 2.0 - v3) / 4.0
    v4 = b0 / 4.0
    return torch.stack([v0, v1, v2, v3, v4])


def _verify_round_trip(tol=1e-12):
    """letter -> words01 -> back to the biquad must return the SAME biquad."""
    worst = 0.0
    for t in range(7):
        for fc in (60.0, 700.0, 5000.0, 15000.0):
            for q in (0.5, 3.0, 30.0):
                for g in (-18.0, 0.0, 12.0):
                    bq = section_biquad(t, torch.tensor(fc, dtype=torch.float64),
                                        torch.tensor(q, dtype=torch.float64),
                                        torch.tensor(g, dtype=torch.float64))
                    v = biquad_to_words01(bq)
                    k = 4.0 * v[4]
                    back = torch.stack([k, k * (4.0 * v[0] + v[1] - 2.0), k * (1.0 - v[1]),
                                        4.0 * v[2] + v[3] - 2.0, 1.0 - v[3]])
                    worst = max(worst, float((back - bq).abs().max()))
    assert worst < tol, f"biquad<->words01 round trip broken: {worst:.3e}"
    return worst


_RT = _verify_round_trip()
