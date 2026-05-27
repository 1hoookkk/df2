"""Named corners, CornerArray, and bilinear interpolation.

Transcribed from runtime/src/corner.rs.
"""
from __future__ import annotations
from enum import IntEnum
from dataclasses import dataclass
from pyruntime.stage_params import StageParams
from pyruntime.encode import EncodedCoeffs, raw_to_encoded
from pyruntime.constants import NUM_BODY_STAGES
from pyruntime import packed_interp as _packed


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
        """Bilinear interpolation at (morph, q), via the one packed-math owner.

        Delegates to pyruntime.packed_interp (which calls the shipped trench-core
        when the library is loaded), so this judges the EXACT morph the player
        produces: morph-first lerp in u16 space with i16-truncate-and-wrap, gain
        at the runtime c4/4 scale. Returns a list of EncodedCoeffs for all stages.

        Corner-label remap: this module names corners A=M0_Q0, B=M0_Q100,
        C=M100_Q0, D=M100_Q100, whereas the owner's word bank is keyed
        A=M0_Q0, B=M100_Q0, C=M0_Q100, D=M100_Q100 — so B and C swap on handoff.
        """
        encs = [c.encode() for c in self._corners]

        def words_of(idx: int) -> list:
            return [_packed.coeffs_to_words(e.c0, e.c1, e.c2, e.c3, e.c4)
                    for e in encs[idx]]

        bank = {
            "A": words_of(0),   # M0_Q0
            "B": words_of(2),   # M100_Q0   (this module's corner C)
            "C": words_of(1),   # M0_Q100   (this module's corner B)
            "D": words_of(3),   # M100_Q100
        }
        rows = _packed.packed_bilinear(bank, float(morph), float(q))
        return [EncodedCoeffs(c0=r[0], c1=r[1], c2=r[2], c3=r[3], c4=r[4])
                for r in rows]
