"""Kernel-form encode: StageParams → EncodedCoeffs.

Transcribed from trench-core/src/encode.rs.
Critical: casts to float32 before computing (matches Rust as f32).
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from pyruntime.stage_params import StageParams

GUARD = 1e-12


@dataclass(frozen=True, slots=True)
class EncodedCoeffs:
    c0: float
    c1: float
    c2: float
    c3: float
    c4: float


def raw_to_encoded(stage: StageParams, flag: float = 1.0) -> EncodedCoeffs:
    """Convert StageParams to kernel-form [c0..c4].

    Casts to float32 first to match Rust's to_raw_stage() → raw_to_encoded().
    """
    # Cast to f32 to match Rust pipeline
    a1 = float(np.float32(stage.a1))
    r = float(np.float32(stage.r))
    val1 = float(np.float32(stage.val1))
    val2 = float(np.float32(stage.val2))
    val3 = float(np.float32(stage.val3))

    if flag >= 0.5:
        # Resonator path
        c2 = 2.0 + a1
        c3 = 1.0 - r * r

        b0 = 1.0 + val1
        b1 = a1 + val2
        b2 = r * r - val3

        c4 = b0
        c0 = (2.0 + b1 / b0) if abs(b0) > GUARD else 2.0
        c1 = (1.0 - b2 / b0) if abs(b0) > GUARD else 1.0

        return EncodedCoeffs(c0=c0, c1=c1, c2=c2, c3=c3, c4=c4)
    else:
        # Lowpass path
        a1_bq = a1 - 2.0
        a2_bq = 1.0 - r
        b0_bq = (1.0 + a1_bq + a2_bq) / 4.0

        c0 = 4.0 if abs(b0_bq) > GUARD else 2.0
        c1 = 0.0 if abs(b0_bq) > GUARD else 1.0
        c2 = a1
        c3 = r
        c4 = b0_bq

        return EncodedCoeffs(c0=c0, c1=c1, c2=c2, c3=c3, c4=c4)
