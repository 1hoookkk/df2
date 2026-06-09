"""Co-optimize 4 corners in (theta,r,g) against the TRUE packed runtime surface."""
from __future__ import annotations
import math
import numpy as np
from scipy.optimize import least_squares
from scipy.signal import find_peaks
from pyruntime import trench_ffi
from src.compiler.surface_target import FREQS, GRID
from src.compiler.encode import body_from_params
from src.architectures.trajectory_program import AUTHORING_SR as SR

LO = np.array([2 * math.pi * 40 / SR, 0.10, 2 * math.pi * 40 / SR, 0.10, 0.001])  # gain floor 0.02->0.001: 0.02 clamped low-output bodies (FuzziFace b0~0.0025) +18 dB/section
HI = np.array([math.pi, 0.99985, math.pi, 0.99985, 40.0])
REG_W = 0.5    # pole-radius commit penalty: pushes poles out of the mushy 0.65 band -> cleaner,
               # more morph-predictable structure at equal-or-better accuracy (Exp C: RMS 1.83->1.74)
_W = 2 * np.pi * FREQS / SR
_c, _sn, _c2, _s2 = np.cos(_W), np.sin(_W), np.cos(2 * _W), np.sin(2 * _W)


def surface(body) -> np.ndarray:                 # vectorised true-runtime surface
    out = np.empty((len(GRID), len(FREQS)))
    for gi, (m, q) in enumerate(GRID):
        acc = np.zeros(len(FREQS))
        for (b0, b1, b2, a1, a2) in trench_ffi.packed_probe(body, float(m), float(q))["biquad"]:
            nr, ni = b0 + b1 * _c + b2 * _c2, -(b1 * _sn + b2 * _s2)
            dr, di = 1 + a1 * _c + a2 * _c2, -(a1 * _sn + a2 * _s2)
            acc += 20 * np.log10(np.maximum(1e-12, np.hypot(nr, ni) / np.maximum(1e-12, np.hypot(dr, di))))
        out[gi] = acc
    return out


def _seed(target, rng):
    P = np.empty((4, 6, 5))
    for ci, gi in enumerate((0, 4, 20, 24)):
        y = target[gi] - target[gi].max(); idx, _ = find_peaks(y, prominence=2.0)
        pk = list(FREQS[idx[np.argsort(y[idx])[::-1]]][:6]) if len(idx) else list(FREQS[::40][:6])
        pk += [FREQS[-1]] * (6 - len(pk))
        for s in range(6):
            fp = float(pk[s]) * (2.0 ** rng.normal(0, 0.05))
            th = 2 * math.pi * float(np.clip(fp, 40, SR * 0.49)) / SR
            P[ci, s] = [th, 0.95, th, 0.85, 1.0]
    return P


def _apply_frozen(base, frozen_zeros):
    fz = np.asarray(frozen_zeros, float)
    if fz.ndim == 3:                                     # (4,6,2): zeros move per corner (a leader canyon)
        base[:, :, 2] = fz[:, :, 0]; base[:, :, 3] = fz[:, :, 1]
    else:                                                # (6,2): one zero per section, held across corners
        base[:, :, 2] = fz[:, 0]; base[:, :, 3] = fz[:, 1]


def fit_surface(target, seed=0, frozen_zeros=None, seed_P=None, free=None, rp_max=None,
                n_restarts=2, max_nfev=2500):
    rng = np.random.default_rng(seed)
    mask = np.ones((4, 6, 5), bool) if free is None else np.asarray(free, bool).copy()
    if frozen_zeros is not None:
        mask[:, :, 2:4] = False
    himat = np.broadcast_to(HI, (4, 6, 5)).copy()
    if rp_max is not None:                               # cap pole radius at the real corpus ceiling
        himat[:, :, 1] = float(rp_max)
    lob = np.broadcast_to(LO, (4, 6, 5))[mask]
    hib = himat[mask]
    best, bestc = None, np.inf
    # A structured seed (from_law) fixes the anchor+mover lane layout; refine it once.
    restarts = 1 if seed_P is not None else n_restarts
    for _ in range(restarts):
        base = seed_P.copy() if seed_P is not None else _seed(target, rng)
        if frozen_zeros is not None:
            _apply_frozen(base, frozen_zeros)

        def resid(x, base=base):
            P = base.copy(); P[mask] = x
            surf = (surface(body_from_params(P)) - target).ravel()
            rp = P[:, :, 1].ravel()                              # 24 pole radii
            reg = REG_W * np.exp(-((rp - 0.65) / 0.22) ** 2)     # commit penalty (out of the mush band)
            return np.concatenate([surf, reg])

        x0 = np.clip(base[mask], lob + 1e-6, hib - 1e-6)
        sol = least_squares(resid, x0, bounds=(lob, hib), method="trf", x_scale="jac",
                            diff_step=1e-3, max_nfev=max_nfev)
        if sol.cost < bestc:
            P = base.copy(); P[mask] = sol.x; best, bestc = P, sol.cost
    return best
