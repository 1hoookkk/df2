"""The physical coordinate: each section is (theta_p, r_p, theta_z, r_z, g).
Angle = frequency, radius = sharpness; the conjugate twin is implicit (real coeffs)."""
from __future__ import annotations
import math
import numpy as np
from src.architectures.trajectory_program import AUTHORING_SR as SR


def params_to_biquad(p) -> np.ndarray:
    tp, rp, tz, rz, g = (float(x) for x in p)
    return np.array([g, g * (-2 * rz * math.cos(tz)), g * (rz * rz), -2 * rp * math.cos(tp), rp * rp])


def biquad_to_params(bq) -> np.ndarray:
    b0, b1, b2, a1, a2 = (float(x) for x in bq)
    rp = math.sqrt(max(a2, 0.0))
    tp = math.acos(max(-1.0, min(1.0, -a1 / (2 * rp)))) if rp > 1e-9 else 0.0
    g = b0 if abs(b0) > 1e-12 else 1e-12
    rz = math.sqrt(max(b2 / g, 0.0))
    tz = math.acos(max(-1.0, min(1.0, (b1 / g) / (-2 * rz)))) if rz > 1e-9 else 0.0
    return np.array([tp, rp, tz, rz, g])


def corner_biquads(P6) -> np.ndarray:                # (6,5) params -> (6,5) biquads
    return np.array([params_to_biquad(P6[i]) for i in range(6)])
