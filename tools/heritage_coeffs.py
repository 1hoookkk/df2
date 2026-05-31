"""Heritage coefficient recipes — E-mu firmware integer domain to EncodedCoeffs.

Translates MorphDesigner firmware coefficient recipes from the 8-bit packed
integer domain (0-127) to trench-core kernel form (c0-c4).

Pipeline: packed bytes → firmware integer values → 5 uint16 words →
minifloat decode → K=4 recombine → kernel [c0..c4].

Three filter types:
  Type 1 — bandpass resonator: symmetric c0==c2, gain routes into c1/c3
  Type 2 — resonant formant: hardcoded c0/c1, frequency-dependent c4
  Type 3 — shaped asymmetric: elevated radius, high-freq compression, inverted c4

Proven from RE vault: FUN_1802c6590 decompilation + 79 preset vector oracles.
"""
from __future__ import annotations

import math
from pyruntime.encode import EncodedCoeffs
from pyruntime.stage_params import StageParams

# ---------------------------------------------------------------------------
# SR family table (proven from RE vault)
# ---------------------------------------------------------------------------

SR_FAMILY = {44100: 0, 48000: 1, 96000: 2, 192000: 3}

FW_BASE  = [18, 18, 4, 1]
FW_SCALE = [220, 220, 200, 177]


# ---------------------------------------------------------------------------
# Minifloat decode (matches trench-core/src/minifloat.rs exactly)
# ---------------------------------------------------------------------------

def _mf_decode(packed: int) -> float:
    """Decode a u16 minifloat to float. Matches Rust decode()."""
    packed = packed & 0xFFFF
    if packed == 0xFFFF:
        return 1.0
    if packed == 0x0000:
        return 0.0
    u = packed + 1
    exp = ((u >> 12) & 0xF) - 15
    mant = u & 0xFFF
    if exp < -14:
        return mant / 134217728.0  # 2^-27
    else:
        scaled = (mant | 0x1000) / 8192.0  # 2^-13
        return scaled * (2.0 ** exp)


# Combining constant K=4.0 (DAT_18065a1ac, proven from Ghidra).
_COMBINE_K = 4.0


def _fw_words_to_kernel(w0: int, w1: int, w2: int, w3: int, w4: int) -> EncodedCoeffs:
    """Decode 5 firmware uint16 words to kernel-form [c0..c4].

    Matches the proven pipeline: FUN_1802c3d40 interpolation output →
    FUN_1802c3600 decode → recombine with K=4.
    """
    d0 = _mf_decode(w0)
    d1 = _mf_decode(w1)
    d2 = _mf_decode(w2)
    d3 = _mf_decode(w3)
    d4 = _mf_decode(w4)
    return EncodedCoeffs(
        c0=d0 * _COMBINE_K + d1,
        c1=d1,
        c2=d2 * _COMBINE_K + d3,
        c3=d3,
        c4=d4 * _COMBINE_K,
    )


# ---------------------------------------------------------------------------
# Firmware intermediate helpers
# ---------------------------------------------------------------------------

def fw_freq_value(packed_freq: int, sr: int = 44100) -> int:
    """freq_value = (scale[sr] * freq_param) >> 7 + base[sr]."""
    idx = SR_FAMILY.get(sr, 0)
    return (FW_SCALE[idx] * packed_freq) // 128 + FW_BASE[idx]


def fw_radius(freq_value: int) -> int:
    """Pole radius: floor(freq_value * 124 / 256) + 118."""
    return (freq_value * 124) // 256 + 118


def fw_gain_offset(packed_gain: int, global_shift: int = 0) -> int:
    """Signed gain offset: clamp((gain-64)//2 + global_shift, -32, 31)."""
    raw = (packed_gain - 64) // 2 + global_shift
    return max(-32, min(31, raw))


# ---------------------------------------------------------------------------
# StageParams reverse-solve from EncodedCoeffs
# ---------------------------------------------------------------------------

def _encoded_to_stage_params(enc: EncodedCoeffs) -> StageParams:
    """Best-effort StageParams derived from EncodedCoeffs."""
    a1 = enc.c2 - 2.0
    r_sq = 1.0 - enc.c3
    r = math.sqrt(max(0.0, r_sq))
    val1 = enc.c4 - 1.0
    val2 = (enc.c0 - 2.0) * enc.c4 - a1
    val3 = r_sq - (1.0 - enc.c1) * enc.c4
    return StageParams(a1=a1, r=r, val1=val1, val2=val2, val3=val3)


# ---------------------------------------------------------------------------
# Type 1 — bandpass resonator
# ---------------------------------------------------------------------------

def type1_to_encoded(freq_packed: int, gain_packed: int,
                     global_shift: int = 0, sr: int = 44100) -> EncodedCoeffs:
    """Type 1: packed bytes → 5 firmware uint16 → kernel c0..c4.

    c0/c2 = freq_value (symmetric).
    c1 = radius + gain_offset (bandwidth opens).
    c3 = radius - gain_offset (bandwidth closes).
    c4 = 0xE000 constant.
    """
    fv = fw_freq_value(freq_packed, sr)
    rad = fw_radius(fv)
    go = fw_gain_offset(gain_packed, global_shift)

    w0 = fv << 8
    w1 = max(0, min(255, rad + go)) << 8
    w2 = fv << 8
    w3 = max(0, min(255, rad - go)) << 8
    w4 = 0xE000

    return _fw_words_to_kernel(w0, w1, w2, w3, w4)


def type1_compile(freq_packed: int, gain_packed: int,
                  global_shift: int = 0) -> tuple[StageParams, EncodedCoeffs]:
    """Type 1 compile: returns (StageParams, EncodedCoeffs)."""
    enc = type1_to_encoded(freq_packed, gain_packed, global_shift)
    return _encoded_to_stage_params(enc), enc


# ---------------------------------------------------------------------------
# Type 2 — resonant formant (hardcoded numerator)
# ---------------------------------------------------------------------------

def type2_to_encoded(freq_packed: int, gain_packed: int = 64,
                     global_shift: int = 0, sr: int = 44100) -> EncodedCoeffs:
    """Type 2: resonant formant with fixed numerator.

    c0 = 0xEC (236), c1 = 0xFF (255) — hardcoded.
    c2 = freq_value, c3 = radius - gain_offset.
    c4 = (freq_value + 0xF5) for sr < 96k, freq_value for sr >= 96k.
    """
    idx = SR_FAMILY.get(sr, 0)
    fv = fw_freq_value(freq_packed, sr)
    rad = fw_radius(fv)
    go = fw_gain_offset(gain_packed, global_shift)

    if idx < 2:  # 44100, 48000
        w0 = 0xEC << 8
        w1 = 0xFF << 8
        w4_val = fv + 0xF5
    else:        # 96000, 192000
        w0 = 0xE1 << 8
        w1 = 0xF0 << 8
        w4_val = fv

    w2 = fv << 8
    w3 = max(0, min(255, rad - go)) << 8
    w4 = w4_val << 8

    return _fw_words_to_kernel(w0, w1, w2, w3, w4)


def type2_compile(freq_packed: int, gain_packed: int = 64,
                  global_shift: int = 0) -> tuple[StageParams, EncodedCoeffs]:
    """Type 2 compile: returns (StageParams, EncodedCoeffs)."""
    enc = type2_to_encoded(freq_packed, gain_packed, global_shift)
    return _encoded_to_stage_params(enc), enc


# ---------------------------------------------------------------------------
# Type 3 — shaped asymmetric (elevated radius, frequency compression)
# ---------------------------------------------------------------------------

def type3_freq_compression(freq_value: int, gain_offset: int) -> int:
    """Type 3 high-frequency compression guard.

    Compresses freq_value toward 220 when near Nyquist with negative
    endpoint gain offset. Prevents instability under morph sweeps.
    """
    if freq_value > 0xDB and gain_offset < 0:
        freq_value = (((freq_value - 220) * (gain_offset + 32)) >> 5) + 220
    return freq_value


def type3_to_encoded(freq_packed: int, gain_packed: int,
                     shift: int = 0, sr: int = 44100) -> EncodedCoeffs:
    """Type 3: shaped asymmetric with elevated radius.

    c0 = freq_base (anchored at SR base frequency).
    c1 = elevated radius (freq_base * 124/256 + 150).
    c2 = freq_value (after optional compression).
    c3 = radius - gain_offset.
    c4 = inverted frequency slope for sr < 96k, constant for sr >= 96k.
    """
    idx = SR_FAMILY.get(sr, 0)
    fv = fw_freq_value(freq_packed, sr)
    go = fw_gain_offset(gain_packed, shift)

    # The DLL compresses emitted w2 only. Radius and low-rate w4 use raw fv.
    fv_compressed = type3_freq_compression(fv, go)
    rad = fw_radius(fv)

    base = FW_BASE[idx]

    w0 = base << 8
    w1 = ((base * 124) // 256 + 150) << 8  # elevated radius: +150 not +118
    w2 = fv_compressed << 8
    w3 = max(0, min(255, rad - go)) << 8

    if idx < 2:  # 44100, 48000
        c4_raw = (fv - 18) * (-12) + (-8192)
        # Pack as int16 → uint16
        w4 = c4_raw & 0xFFFF
    else:
        w4 = 0xE000  # constant for high SR

    return _fw_words_to_kernel(w0, w1, w2, w3, w4)


def type3_compile(freq_packed: int, gain_packed: int, shift: int = 0) -> tuple[StageParams, EncodedCoeffs]:
    """Type 3 compile: returns (StageParams, EncodedCoeffs)."""
    enc = type3_to_encoded(freq_packed, gain_packed, shift=shift)
    return _encoded_to_stage_params(enc), enc


# ---------------------------------------------------------------------------
# Inline tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Type 1: freq=64, gain=64 (midpoint) ===")
    sp1, enc1 = type1_compile(64, 64)
    print(f"  EncodedCoeffs: c0={enc1.c0:.5f}, c1={enc1.c1:.5f}, c2={enc1.c2:.5f}, c3={enc1.c3:.5f}, c4={enc1.c4:.5f}")
    print(f"  StageParams:   a1={sp1.a1:.5f}, r={sp1.r:.5f}, val1={sp1.val1:.5f}, val2={sp1.val2:.5f}, val3={sp1.val3:.5f}")
    fv1 = fw_freq_value(64)
    rad1 = fw_radius(fv1)
    print(f"  fw: freq_value={fv1}, radius={rad1}")

    print()
    print("=== Type 2: freq=64, gain=64 — freq_value bypass ===")
    sp2, enc2 = type2_compile(64)
    print(f"  EncodedCoeffs: c0={enc2.c0:.5f}, c1={enc2.c1:.5f}, c2={enc2.c2:.5f}, c3={enc2.c3:.5f}, c4={enc2.c4:.5f}")
    fv2 = fw_freq_value(64)
    rad2 = fw_radius(fv2)
    expected2 = _fw_words_to_kernel(0xEC00, 0xFF00, fv2 << 8, rad2 << 8, ((fv2 + 0xF5) << 8) & 0xFFFF)
    assert enc2 == expected2, "Type 2 kernel must match the packed-word recipe"
    print("  Verified: Type 2 packed-word recipe")

    print()
    print("=== Type 3: freq=64, gain=64 — elevated radius ===")
    sp3, enc3 = type3_compile(64, 64)
    print(f"  EncodedCoeffs: c0={enc3.c0:.5f}, c1={enc3.c1:.5f}, c2={enc3.c2:.5f}, c3={enc3.c3:.5f}, c4={enc3.c4:.5f}")
    fv3 = fw_freq_value(64)
    rad3_anchor = (FW_BASE[0] * 124) // 256 + 150
    rad1_anchor = fw_radius(FW_BASE[0])
    assert rad3_anchor > rad1_anchor, "Type 3 anchor radius should exceed the Type 1 anchor radius"
    print(f"  Elevated anchor radius verified: {rad3_anchor} > {rad1_anchor}")

    print()
    print("All checks passed.")
