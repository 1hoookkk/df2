"""Pack (theta,r,g) params -> the 240-byte body the runtime ships.

THE ONE ENCODER: trench_ffi.compile_body (the shipped trench-core forward compiler,
byte-identical to the forge-web WASM GUI — proven 240/240, 0.0000 dB). The old
coeffs_to_words path was a rogue reimplementation that skipped the engine's gain
normalization and diverged up to 59 dB. Every body MUST come from compile_body so the
plot, the corridor gate, and the GUI all null to 0 against what the engine actually plays.
"""
from __future__ import annotations
import math
from pyruntime import trench_ffi
from src.architectures.trajectory_program import AUTHORING_SR as SR
from pyruntime.packed_interp import coeffs_to_words  # legacy decode-side use only
from src.compiler.rootspace import params_to_biquad
from src.utils.body240 import CORNER_ORDER, raw_from_words

_TAU = 2.0 * math.pi


def _params168(P):
    """(4,6,5) [theta_p, r_p, theta_z, r_z, g] -> 168 flat params
    [on, pole_hz, pole_r, gain, zero_on, zero_hz, zero_depth] x 6 x 4 corners."""
    out = []
    for ci in range(4):
        for si in range(6):
            tp, rp, tz, rz, g = (float(x) for x in P[ci][si])
            out += [1.0, tp * SR / _TAU, rp, g, (1.0 if rz > 1e-3 else 0.0), tz * SR / _TAU, rz]
    return out


def body_from_params(P) -> bytes:
    """Compile through the shipped engine — the single owner of the forward path."""
    return trench_ffi.compile_body(_params168(P))


def _kernel_to_section(k):
    """kernel (c0..c4) -> [on, pole_hz, pole_r, gain, zero_on, zero_hz, zero_depth] for compile_body."""
    c0, c1, c2, c3, c4 = (float(x) for x in k)
    b0, b1, b2, a1, a2 = c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3
    pr = math.sqrt(max(a2, 0.0))
    pth = math.acos(max(-1.0, min(1.0, -a1 / (2 * pr)))) if pr > 1e-9 else 0.0
    g = b0 if abs(b0) > 1e-12 else 1e-12
    zr = math.sqrt(max(b2 / g, 0.0))
    zth = math.acos(max(-1.0, min(1.0, (b1 / g) / (-2 * zr)))) if zr > 1e-9 else 0.0
    return [1.0, pth * SR / _TAU, pr, g, (1.0 if zr > 1e-3 else 0.0), zth * SR / _TAU, zr]


def body_from_kernels(corner_kernels) -> bytes:
    """Fit kernels (4 corners in CORNER_ORDER x 6 sections) -> body via the shipped compiler.
    Used to route the magnitude-fit paths (sweep_roster) through the one encoder."""
    params = []
    for corner in corner_kernels:
        for k in corner:
            params += _kernel_to_section(k)
    return trench_ffi.compile_body(params)


def words_from_body(body):
    """Decode a 240-byte body back to {CORNER_ORDER[i]: [(w0..w4) x6]} (canonical cart words)."""
    out, off = {}, 0
    for label in CORNER_ORDER:
        rows = []
        for _ in range(6):
            rows.append(tuple(body[off + 2 * w] | (body[off + 2 * w + 1] << 8) for w in range(5)))
            off += 10
        out[label] = rows
    return out


def _kernel(bq):
    b0, b1, b2, a1, a2 = bq
    return (b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


def words_from_params(P):  # LEGACY (rogue, non-normalized) — kept for inspection, NOT for bodies
    return {CORNER_ORDER[ci]: [tuple(int(v) for v in coeffs_to_words(*_kernel(params_to_biquad(P[ci][s]))))
                               for s in range(6)] for ci in range(4)}


def null_vs_engine(P) -> int:
    """Gate: bytes that DIFFER between a candidate path and the shipped encoder. 0 == clean null."""
    a = body_from_params(P)
    b = raw_from_words(words_from_params(P))
    return sum(x != y for x, y in zip(a, b))
