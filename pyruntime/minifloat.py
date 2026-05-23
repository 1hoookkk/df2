"""E-mu mini-float codec and packed interpolation helpers.

Python port of trench-core/src/minifloat.rs.
"""
from __future__ import annotations

import math

from pyruntime.encode import EncodedCoeffs

COMBINE_K = 4.0


def decode(raw: int) -> float:
    """Decode u16 mini-float to f64."""
    raw = int(raw) & 0xFFFF
    if raw == 0xFFFF:
        return 1.0
    if raw == 0x0000:
        return 0.0

    u = raw + 1
    exp = ((u >> 12) & 0xF) - 15
    mant = u & 0xFFF

    if exp < -14:
        # denormal: mant * 2^-27
        return mant * (1.0 / 134_217_728.0)

    # normal: (mant|0x1000) * 2^(exp-13)
    return (mant | 0x1000) * (1.0 / 8192.0) * (2.0 ** exp)


def encode(value: float) -> int:
    """Encode f64 to u16 mini-float."""
    v = float(value)
    if v >= 1.0:
        return 0xFFFF
    if v <= 0.0:
        return 0x0000

    denorm_mant = int(round(v * 134_217_728.0))
    if 0 < denorm_mant <= 0xFFF:
        return int((denorm_mant - 1) & 0xFFFF)

    log2_val = math.log2(v)
    exp_stored = min(int(math.floor(log2_val)) + 1, 0)
    if exp_stored < -14:
        return 0x0000

    biased_exp = exp_stored + 15
    mant_with_hidden = int(round(v / (2.0 ** (exp_stored - 13))))

    if mant_with_hidden >= 0x2000:
        if exp_stored < 0:
            biased_exp += 1
            mant_with_hidden = int(round(v / (2.0 ** (exp_stored + 1 - 13))))
            mant = min(mant_with_hidden & 0xFFF, 0xFFF)
            u = (biased_exp << 12) | mant
            return int((u - 1) & 0xFFFF)
        return 0xFFFF

    mant = min(max(mant_with_hidden - 0x1000, 0), 0xFFF)
    u = (biased_exp << 12) | mant
    return int((u - 1) & 0xFFFF)


def quantize(value: float) -> float:
    return decode(encode(value))


def pack(coeffs: EncodedCoeffs) -> tuple[int, int, int, int, int]:
    """Pack kernel-form [c0..c4] into 5 u16 words."""
    return (
        encode((coeffs.c0 - coeffs.c1) / COMBINE_K),
        encode(coeffs.c1),
        encode((coeffs.c2 - coeffs.c3) / COMBINE_K),
        encode(coeffs.c3),
        encode(coeffs.c4),
    )


def _lerp_u16(a: int, b: int, frac: float) -> int:
    ai = int(a) & 0xFFFF
    bi = int(b) & 0xFFFF
    out = ai + int((bi - ai) * float(frac))
    return max(0, min(0xFFFF, out))


def interpolate_packed(
    m0_q0: tuple[int, int, int, int, int],
    m0_q100: tuple[int, int, int, int, int],
    m100_q0: tuple[int, int, int, int, int],
    m100_q100: tuple[int, int, int, int, int],
    morph: float,
    q: float,
) -> EncodedCoeffs:
    """Q-first bilinear interpolation in u16 space, then decode."""
    interp = [0, 0, 0, 0, 0]
    for i in range(5):
        q_m0 = _lerp_u16(m0_q0[i], m0_q100[i], q)
        q_m1 = _lerp_u16(m100_q0[i], m100_q100[i], q)
        interp[i] = _lerp_u16(q_m0, q_m1, morph)

    d0 = decode(interp[0])
    d1 = decode(interp[1])
    d2 = decode(interp[2])
    d3 = decode(interp[3])
    d4 = decode(interp[4])

    return EncodedCoeffs(
        c0=d0 * COMBINE_K + d1,
        c1=d1,
        c2=d2 * COMBINE_K + d3,
        c3=d3,
        c4=d4,
    )
