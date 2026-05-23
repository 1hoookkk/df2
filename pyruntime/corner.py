"""Named corners, CornerArray, and bilinear interpolation.

Transcribed from runtime/src/corner.rs.
"""
from __future__ import annotations
from enum import IntEnum
from dataclasses import dataclass
from pyruntime.stage_params import StageParams
from pyruntime.encode import EncodedCoeffs, raw_to_encoded
from pyruntime.constants import NUM_BODY_STAGES
from pyruntime.minifloat import interpolate_packed, pack


class CornerName(IntEnum):
    A = 0  # M0_Q0
    B = 1  # M0_Q100
    C = 2  # M100_Q0
    D = 3  # M100_Q100

    def json_key(self) -> str:
        return ["M0_Q0", "M0_Q100", "M100_Q0", "M100_Q100"][self.value]

    def morph(self) -> float:
        return 0.0 if self in (CornerName.A, CornerName.B) else 1.0

    def q(self) -> float:
        return 0.0 if self in (CornerName.A, CornerName.C) else 1.0


@dataclass
class CornerState:
    stages: list  # list[StageParams], length NUM_BODY_STAGES
    boost: float = 4.0
    _pre_encoded: list | None = None  # Heritage bypass — authoritative EncodedCoeffs

    def encode(self) -> list:
        """Encode all stages to kernel-form."""
        if self._pre_encoded is not None:
            return self._pre_encoded
        return [raw_to_encoded(s) for s in self.stages]


class CornerArray:
    """The complete 4-corner surface for a body."""

    def __init__(self, a: CornerState, b: CornerState, c: CornerState, d: CornerState):
        self._corners = [a, b, c, d]

    def corner(self, name: CornerName) -> CornerState:
        return self._corners[name.value]

    def names(self) -> list[CornerName]:
        return [CornerName.A, CornerName.B, CornerName.C, CornerName.D]

    def interpolate(self, morph: float, q: float) -> list:
        """Bilinear interpolation at (morph, q). Q first, then morph.

        Returns list of EncodedCoeffs for all stages.
        Interpolation is done in packed minifloat u16 space (firmware-authentic),
        not float-domain c-coeff space.
        """
        a_enc = self._corners[0].encode()
        b_enc = self._corners[1].encode()
        c_enc = self._corners[2].encode()
        d_enc = self._corners[3].encode()

        out = []
        for i in range(NUM_BODY_STAGES):
            out.append(
                interpolate_packed(
                    pack(a_enc[i]),
                    pack(b_enc[i]),
                    pack(c_enc[i]),
                    pack(d_enc[i]),
                    morph=float(morph),
                    q=float(q),
                )
            )
        return out
