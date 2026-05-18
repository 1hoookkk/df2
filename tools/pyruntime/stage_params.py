"""StageParams — raw stage coefficients in the authoring domain.

Mirrors runtime/src/corner.rs StageParams struct.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from pyruntime.constants import SR, TWO_PI


@dataclass(frozen=True, slots=True)
class StageParams:
    a1: float
    r: float
    val1: float
    val2: float
    val3: float

    def freq_hz(self) -> float:
        """Pole frequency in Hz at the authoring sample rate."""
        if self.r < 1e-6:
            return 0.0
        arg = (-self.a1 / (2.0 * self.r))
        arg = max(-1.0, min(1.0, arg))
        return math.acos(arg) * SR / TWO_PI

    def zero_energy(self) -> float:
        """Euclidean norm of val2, val3 — measures zero activity."""
        return math.sqrt(self.val2 * self.val2 + self.val3 * self.val3)

    def radius(self) -> float:
        return self.r

    def gain(self) -> float:
        """b0 = 1 + val1."""
        return 1.0 + self.val1

    def encode(self) -> "EncodedCoeffs":
        """Encode to kernel-form coefficients via f32 cast path."""
        from pyruntime.encode import raw_to_encoded
        return raw_to_encoded(self)

    @staticmethod
    def passthrough() -> StageParams:
        return StageParams(a1=0.0, r=0.0, val1=0.0, val2=0.0, val3=0.0)
