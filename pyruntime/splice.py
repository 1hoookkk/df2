"""P2K corner splice with compatibility gates.

Corner layout: A=M0_Q0, B=M0_Q100, C=M100_Q0, D=M100_Q100.
Morph axis (A/B -> C/D) traverses between two filter voices.
Q axis (A/C -> B/D) applies pressure.
"""
from __future__ import annotations

import math
from enum import Enum

from pyruntime.constants import NUM_BODY_STAGES
from pyruntime.corner import CornerArray, CornerName, CornerState
from pyruntime.encode import EncodedCoeffs
from pyruntime.stage_params import StageParams

PASSTHROUGH_ENC = EncodedCoeffs(c0=2.0, c1=1.0, c2=2.0, c3=1.0, c4=1.0)


class SpliceMode(Enum):
    REST_TO_REST = "RestToRest"
    REST_TO_MORPHED = "RestToMorphed"
    MORPHED_TO_MORPHED = "MorphedToMorphed"
    CROSS = "Cross"


class SpliceError(ValueError):
    """Base splice failure."""


class TypeMismatch(SpliceError):
    """Type gate failed."""


class Type3CompressionFailure(SpliceError):
    """Type-3 high-frequency compression rule failed."""


class WahFailure(SpliceError):
    """Morph sweep violates wah guard."""


def _clone_corner(corner: CornerState) -> CornerState:
    pre = None
    if corner._pre_encoded is not None:
        pre = list(corner._pre_encoded)
    return CornerState(stages=list(corner.stages), boost=corner.boost, _pre_encoded=pre)


def _enforce_inactive_passthrough(corner: CornerState, active_stage_count: int) -> CornerState:
    out = _clone_corner(corner)
    n = max(NUM_BODY_STAGES, len(out.stages))
    stages = list(out.stages)
    while len(stages) < n:
        stages.append(StageParams.passthrough())
    for i in range(active_stage_count, n):
        stages[i] = StageParams.passthrough()
    out.stages = stages[:n]

    if out._pre_encoded is not None:
        encoded = list(out._pre_encoded)
        while len(encoded) < n:
            encoded.append(PASSTHROUGH_ENC)
        for i in range(active_stage_count, n):
            encoded[i] = PASSTHROUGH_ENC
        out._pre_encoded = encoded[:n]
    return out


def _run_type_gate(filter_type_a: int | None, filter_type_b: int | None) -> int | None:
    if filter_type_a is None or filter_type_b is None:
        return None
    if int(filter_type_a) != int(filter_type_b):
        raise TypeMismatch(
            f"Type split gate failed: A/C types differ ({filter_type_a} vs {filter_type_b})."
        )
    return int(filter_type_a)


def _run_type3_compression_gate(corners: CornerArray, active_stage_count: int) -> None:
    # Type 3 guard: freq_value > 0xDB must compress toward 220 under negative shift.
    # In this authoring layer we only have pre-encoded c2 when provenance carries it.
    # c2 * 128 approximates firmware freq_value for the relevant path.
    for cn in (CornerName.A, CornerName.C):
        pre = corners.corner(cn)._pre_encoded
        if pre is None:
            continue
        for i, enc in enumerate(pre[:active_stage_count]):
            freq_value = int(round(enc.c2 * 128.0))
            if freq_value > 0xDB:
                raise Type3CompressionFailure(
                    f"Type 3 compression gate failed at {cn.name} stage {i}: "
                    f"freq_value={freq_value} (>0xDB)."
                )


def _run_wah_gate(
    corners: CornerArray,
    active_stage_count: int,
    wah_c1_limit: float,
    morph_samples: int,
) -> None:
    q_samples = (0.0, 0.5, 1.0)
    steps = max(3, int(morph_samples))
    for i in range(steps):
        morph = i / (steps - 1)
        for q in q_samples:
            encoded = corners.interpolate(morph, q)
            for si, stage in enumerate(encoded[:active_stage_count]):
                c1 = float(stage.c1)
                if not math.isfinite(c1):
                    raise WahFailure(
                        f"Wah gate failed: non-finite c1 at stage {si}, morph={morph:.3f}, q={q:.3f}."
                    )
                if c1 >= wah_c1_limit:
                    raise WahFailure(
                        f"Wah gate failed: c1={c1:.6f} >= {wah_c1_limit:.6f} "
                        f"at stage {si}, morph={morph:.3f}, q={q:.3f}."
                    )


def splice_corners(
    body_a: CornerArray,
    body_b: CornerArray,
    mode: SpliceMode,
    *,
    filter_type_a: int | None = None,
    filter_type_b: int | None = None,
    active_stage_count: int = 6,
    wah_c1_limit: float = 2.0,
    morph_samples: int = 65,
) -> CornerArray:
    """Splice two bodies into a novel morph trajectory with hard gates."""
    if mode == SpliceMode.REST_TO_REST:
        a = _clone_corner(body_a.corner(CornerName.A))
        b = _clone_corner(body_a.corner(CornerName.B))
        c = _clone_corner(body_b.corner(CornerName.A))
        d = _clone_corner(body_b.corner(CornerName.B))
    elif mode == SpliceMode.REST_TO_MORPHED:
        a = _clone_corner(body_a.corner(CornerName.A))
        b = _clone_corner(body_a.corner(CornerName.B))
        c = _clone_corner(body_b.corner(CornerName.C))
        d = _clone_corner(body_b.corner(CornerName.D))
    elif mode == SpliceMode.MORPHED_TO_MORPHED:
        a = _clone_corner(body_a.corner(CornerName.C))
        b = _clone_corner(body_a.corner(CornerName.D))
        c = _clone_corner(body_b.corner(CornerName.C))
        d = _clone_corner(body_b.corner(CornerName.D))
    elif mode == SpliceMode.CROSS:
        a = _clone_corner(body_a.corner(CornerName.A))
        b = _clone_corner(body_b.corner(CornerName.B))
        c = _clone_corner(body_b.corner(CornerName.C))
        d = _clone_corner(body_a.corner(CornerName.D))
    else:
        raise ValueError(f"Unknown splice mode: {mode}")

    kind = _run_type_gate(filter_type_a, filter_type_b)

    a = _enforce_inactive_passthrough(a, active_stage_count)
    b = _enforce_inactive_passthrough(b, active_stage_count)
    c = _enforce_inactive_passthrough(c, active_stage_count)
    d = _enforce_inactive_passthrough(d, active_stage_count)
    out = CornerArray(a=a, b=b, c=c, d=d)

    if kind == 3:
        _run_type3_compression_gate(out, active_stage_count)
    _run_wah_gate(out, active_stage_count, wah_c1_limit, morph_samples)
    return out
