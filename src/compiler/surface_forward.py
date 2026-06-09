"""Continuous KERNEL-interpolation surrogate of the runtime.

The runtime lerps packed WORDS, which decode to the kernel (c0..c4) — NOT the
biquad. Interpolating biquads diverges (~19 dB, OBSERVED) because kernel->biquad
is nonlinear. So interpolate in the kernel domain, then convert kernel->biquad."""
from __future__ import annotations
import numpy as np
from pyruntime.packed_interp import words_to_coeffs
from src.compiler.rootspace import params_to_biquad, biquad_to_params
from src.compiler.surface_target import FREQS, GRID, mag_db  # noqa: F401
from src.utils.body240 import CORNER_ORDER


def _bq_to_kernel(bq) -> np.ndarray:
    b0, b1, b2, a1, a2 = bq
    return np.array([b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0])


def corner_kernels(P6) -> np.ndarray:            # (6,5) params -> (6,5) kernels (c0..c4)
    return np.array([_bq_to_kernel(params_to_biquad(P6[i])) for i in range(6)])


def _kern_to_bq(K) -> np.ndarray:                # (6,5) kernel -> (6,5) biquad
    c0, c1, c2, c3, c4 = K[:, 0], K[:, 1], K[:, 2], K[:, 3], K[:, 4]
    return np.stack([c4, (c0 - 2) * c4, (1 - c1) * c4, c2 - 2, 1 - c3], axis=1)


def _interp(K4, m, q):                           # bilinear over the 4 corners' kernels
    A, B, C, D = K4
    return (1 - q) * ((1 - m) * A + m * B) + q * ((1 - m) * C + m * D)


def surface_db(P, freqs, grid) -> np.ndarray:
    K4 = [corner_kernels(P[c]) for c in range(4)]
    out = np.empty((len(grid), len(freqs)))
    for gi, (m, q) in enumerate(grid):
        bq = _kern_to_bq(_interp(K4, m, q))
        out[gi] = [mag_db(bq, f) for f in freqs]
    return out


def stab_term(P, grid) -> np.ndarray:            # interior poles pushed inside the circle
    K4 = [corner_kernels(P[c]) for c in range(4)]
    pen = []
    for (m, q) in grid:
        a2 = 1.0 - _interp(K4, m, q)[:, 3]       # biquad a2 = 1 - c3 = pole r^2
        pen.append(np.maximum(0.0, a2 - 0.9997))
    return np.concatenate(pen)


def params_from_body(body: bytes) -> np.ndarray:
    P = np.empty((4, 6, 5))
    off = 0
    words = {}
    for label in CORNER_ORDER:
        rows = []
        for _ in range(6):
            rows.append([body[off + 2 * w] | (body[off + 2 * w + 1] << 8) for w in range(5)]); off += 10
        words[label] = rows
    for ci, label in enumerate(CORNER_ORDER):
        for s in range(6):
            c = words_to_coeffs(tuple(words[label][s]))         # kernel c0..c4
            bq = (c[4], (c[0] - 2) * c[4], (1 - c[1]) * c[4], c[2] - 2, 1 - c[3])
            P[ci, s] = biquad_to_params(bq)
    return P
