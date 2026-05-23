"""Packed-domain interpolation — clean scalar reference implementation.

Formula source: FUN_1802c3d40 (E-mu EosAudioEngine.dll decompilation).
This supersedes the stale pyruntime/minifloat.py::interpolate_packed,
which is Q-first and clamps. This implementation is morph-first and wraps.

Derived-packed-canonical note:
  When raw ROM u16 corner words are unavailable, `coeffs_to_words` derives
  words from decoded c0..c4. Results are labelled derived-packed-canonical
  and do not claim historical E-MU bit parity.
"""
from __future__ import annotations

import ctypes
import math


COMBINE_K = 4.0


# ── minifloat codec ───────────────────────────────────────────────────────────


def decode(word: int) -> float:
    """Decode u16 minifloat word to float.

    u = word + 1
      u==65536 → 1.0
      u==1     → 0.0
      e = (u>>12)&0xF, m = u&0xFFF
      e==0: ldexp(m/4096, e-15)   (denormal)
      e>0:  ldexp((m|0x1000)/8192, e-15)  (normal)
    """
    u = (int(word) & 0xFFFF) + 1
    if u == 65536:
        return 1.0
    if u == 1:
        return 0.0
    e = (u >> 12) & 0xF
    m = u & 0xFFF
    x = m / 4096.0 if e == 0 else (m | 0x1000) / 8192.0
    return math.ldexp(x, e - 15)


def encode(value: float) -> int:
    """Encode float to nearest u16 minifloat word. Inverse of decode."""
    v = float(value)
    if v >= 1.0:
        return 0xFFFF
    if v <= 0.0:
        return 0x0000

    denorm_mant = round(v * 134_217_728.0)
    if 0 < denorm_mant <= 0xFFF:
        return (denorm_mant - 1) & 0xFFFF

    log2_val = math.log2(v)
    exp_stored = min(int(math.floor(log2_val)) + 1, 0)
    if exp_stored < -14:
        return 0x0000

    biased_exp = exp_stored + 15
    scale = 2.0 ** (exp_stored - 13)
    mant_with_hidden = round(v / scale)

    if mant_with_hidden >= 0x2000:
        if exp_stored < 0:
            biased_exp += 1
            exp_stored += 1
            scale2 = 2.0 ** (exp_stored - 13)
            mant_with_hidden = round(v / scale2)
            mant = min(mant_with_hidden & 0xFFF, 0xFFF)
            u = (biased_exp << 12) | mant
            return (u - 1) & 0xFFFF
        return 0xFFFF

    mant = min(max(mant_with_hidden - 0x1000, 0), 0xFFF)
    u = (biased_exp << 12) | mant
    return (u - 1) & 0xFFFF


def _f32(x: float) -> float:
    """Round to f32 precision (exact MSVC f32 multiplication semantics)."""
    return ctypes.c_float(x).value


# ── interpolation ─────────────────────────────────────────────────────────────


def lerp_u16(a: int, b: int, frac: float) -> int:
    """E-MU/MSVC-style packed u16 lerp with i16 truncation before adding base.

    C formula: (uint16_t)((int16_t)((float)((int)B - (int)A) * frac) + A)

    Critical: the (int16_t) cast wraps the delta BEFORE adding A.
    Does NOT clamp — wraps per MSVC x86/ARM behavior.
    Uses f32 arithmetic to match the hardware multiply exactly.
    """
    a = int(a) & 0xFFFF
    b = int(b) & 0xFFFF
    # f32 multiply (per MSVC (float) cast)
    product = _f32(_f32(b - a) * _f32(frac))
    # Truncate toward zero, then wrap to int16
    trunc = int(product)  # Python int() truncates toward zero for finite floats
    delta_i16 = ((trunc + 0x8000) % 0x10000) - 0x8000
    return (a + delta_i16) & 0xFFFF


def coeffs_to_words(c0: float, c1: float, c2: float, c3: float, c4: float) -> tuple[int, ...]:
    """Derive 5 packed u16 words from kernel-form coefficients.

    Inverse recombination:
      w0 = encode((c0 - c1) / 4)
      w1 = encode(c1)
      w2 = encode((c2 - c3) / 4)
      w3 = encode(c3)
      w4 = encode(c4 / 4)      (c4 scale = 4.0, verified vs ROM 2026-05-19)

    Returns derived-packed-canonical words; not raw ROM values.
    """
    return (
        encode((c0 - c1) / COMBINE_K),
        encode(c1),
        encode((c2 - c3) / COMBINE_K),
        encode(c3),
        encode(c4 / COMBINE_K),
    )


def words_to_coeffs(words: tuple[int, ...]) -> tuple[float, ...]:
    """Decode 5 u16 words to kernel-form c0..c4.

    Recombination:
      d0..d4 = decode(w0..w4)
      c0 = 4*d0 + d1
      c1 = d1
      c2 = 4*d2 + d3
      c3 = d3
      c4 = 4*d4      (c4 scale = 4.0, verified vs ROM 2026-05-19)
    """
    d = [decode(w) for w in words]
    return (
        COMBINE_K * d[0] + d[1],
        d[1],
        COMBINE_K * d[2] + d[3],
        d[3],
        COMBINE_K * d[4],
    )


def packed_bilinear(
    corner_words: dict[str, list[tuple[int, ...]]],
    morph: float,
    q: float,
) -> list[tuple[float, ...]]:
    """Morph-first bilinear interpolation in u16 space, then decode.

    Args:
        corner_words: dict with keys 'A' (M0_Q0), 'B' (M100_Q0),
                      'C' (M0_Q100), 'D' (M100_Q100).
                      Each value is a list of 5-tuples (one per stage).
        morph: float in [0, 1]
        q: float in [0, 1]

    Returns:
        List of (c0, c1, c2, c3, c4) tuples, one per stage.
    """
    num_stages = len(corner_words["A"])
    result = []
    for si in range(num_stages):
        a = corner_words["A"][si]
        b = corner_words["B"][si]
        c = corner_words["C"][si]
        d = corner_words["D"][si]

        out_words = tuple(
            lerp_u16(
                lerp_u16(a[wi], b[wi], morph),  # edge0: A→B along morph
                lerp_u16(c[wi], d[wi], morph),  # edge1: C→D along morph
                q,                               # edge0→edge1 along Q
            )
            for wi in range(5)
        )
        result.append(words_to_coeffs(out_words))
    return result


def build_corner_words_from_coeffs(
    corner_coeffs: dict[str, list[tuple[float, ...]]],
) -> dict[str, list[tuple[int, ...]]]:
    """Derive packed corner words from decoded coefficient arrays.

    Args:
        corner_coeffs: dict with keys 'A'..'D', each a list of
                       (c0, c1, c2, c3, c4) tuples per stage.

    Returns:
        dict with same keys, each a list of 5-word tuples.
        Labelled derived-packed-canonical.
    """
    return {
        name: [coeffs_to_words(*stage) for stage in stages]
        for name, stages in corner_coeffs.items()
    }
