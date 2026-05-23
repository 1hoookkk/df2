"""Zero-placement family system — ContourFamily and classification.

Transcribed from runtime/src/zero_law_adapter.rs.
"""
from __future__ import annotations
import math
from enum import Enum

from pyruntime.stage_params import StageParams
from pyruntime.constants import SR, TWO_PI


class ContourKind(Enum):
    PURE = "Pure"
    UNIT_CIRCLE = "UnitCircle"
    NEAR_ALLPASS = "NearAllpass"
    INTERIOR_ZERO = "InteriorZero"


class ContourFamily:
    """Proved zero-placement families from P2K corpus analysis."""

    def __init__(self, name: str, zero_r: float = 0.0, zero_angle: float = 0.0):
        self.name = name
        self.zero_r = zero_r
        self.zero_angle = zero_angle

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ContourFamily):
            return NotImplemented
        if self.name != other.name:
            return False
        if self.name == "InteriorZero":
            return (
                abs(self.zero_r - other.zero_r) < 1e-6
                and abs(self.zero_angle - other.zero_angle) < 1e-6
            )
        return True

    def __repr__(self) -> str:
        if self.name == "InteriorZero":
            return f"ContourFamily(InteriorZero, r={self.zero_r:.4f}, angle={self.zero_angle:.4f})"
        return f"ContourFamily({self.name})"

    def val2_val3(self, a1: float, pole_radius: float) -> tuple[float, float]:
        """Compute (val2, val3) for this family given pole a1 and radius."""
        if self.name == "Pure":
            return (0.0, 0.0)
        elif self.name == "UnitCircle":
            val2 = a1 * (1.0 / pole_radius - 1.0) if pole_radius > 1e-6 else 0.0
            val3 = pole_radius * pole_radius - 1.0
            return (val2, val3)
        elif self.name == "NearAllpass":
            return (0.0, 0.0)
        elif self.name == "InteriorZero":
            val2 = -2.0 * self.zero_r * math.cos(self.zero_angle) - a1
            val3 = pole_radius * pole_radius - self.zero_r * self.zero_r
            return (val2, val3)
        return (0.0, 0.0)

    @staticmethod
    def interior_zero(zero_r: float, zero_angle: float) -> "ContourFamily":
        return ContourFamily("InteriorZero", zero_r=zero_r, zero_angle=zero_angle)


# Singletons for non-parameterized families
ContourFamily.PURE = ContourFamily("Pure")
ContourFamily.UNIT_CIRCLE = ContourFamily("UnitCircle")
ContourFamily.NEAR_ALLPASS = ContourFamily("NearAllpass")


def classify_stage(stage: StageParams) -> ContourFamily:
    """Classify a StageParams into its zero-placement family."""
    ze = stage.zero_energy()
    if ze < 0.05:
        return ContourFamily.PURE

    r_sq = stage.r * stage.r
    unit_circle_val3 = r_sq - 1.0

    # UnitCircle: BOTH conditions required
    if abs(stage.val3 - unit_circle_val3) < 0.01 and abs(stage.val2) < 0.1:
        return ContourFamily.UNIT_CIRCLE

    # InteriorZero: val3 > 0
    if stage.val3 > 0.0:
        zero_r_sq = r_sq - stage.val3
        if zero_r_sq > 0.0:
            zero_r = math.sqrt(zero_r_sq)
            b1 = stage.a1 + stage.val2
            cos_phi = (-b1 / (2.0 * zero_r)) if zero_r > 1e-6 else 1.0
            cos_phi = max(-1.0, min(1.0, cos_phi))
            zero_angle = math.acos(cos_phi)
            return ContourFamily.interior_zero(zero_r, zero_angle)

    return ContourFamily.NEAR_ALLPASS


def resolve_contour(
    kind: ContourKind,
    color: float,
    hue: float,
    a1: float,
    pole_radius: float,
) -> ContourFamily:
    """Resolve authored controls into a ContourFamily."""
    c = max(0.0, min(1.0, color))

    pole_angle = (
        math.acos(max(-1.0, min(1.0, -a1 / (2.0 * pole_radius))))
        if pole_radius > 1e-6
        else math.pi / 2.0
    )

    # Zero angle: offset from pole by hue octaves
    if abs(hue) < 1e-6:
        zero_angle = pole_angle
    else:
        pole_freq = pole_angle * SR / TWO_PI
        zero_freq = max(20.0, min(SR * 0.48, pole_freq * 2.0 ** hue))
        zero_angle = TWO_PI * zero_freq / SR

    if kind == ContourKind.PURE:
        return ContourFamily.PURE
    elif kind == ContourKind.UNIT_CIRCLE:
        if abs(hue) < 1e-6 and c < 1e-6:
            return ContourFamily.UNIT_CIRCLE
        return ContourFamily.interior_zero(1.0, zero_angle)
    elif kind == ContourKind.NEAR_ALLPASS:
        if c < 1e-6 and abs(hue) < 1e-6:
            return ContourFamily.NEAR_ALLPASS
        zero_r = pole_radius * (1.0 - c * 0.1)
        return ContourFamily.interior_zero(zero_r, zero_angle)
    elif kind == ContourKind.INTERIOR_ZERO:
        zero_r = pole_radius * (1.0 - c)
        return ContourFamily.interior_zero(zero_r, zero_angle)
    return ContourFamily.PURE


def contour_to_kind_color_hue(
    family: ContourFamily,
    a1: float,
    pole_radius: float,
) -> tuple[ContourKind, float, float]:
    """Inverse of resolve_contour: extract (kind, color, hue) from a ContourFamily."""
    if family.name == "Pure":
        return (ContourKind.PURE, 0.0, 0.0)
    elif family.name == "UnitCircle":
        return (ContourKind.UNIT_CIRCLE, 0.0, 0.0)
    elif family.name == "NearAllpass":
        return (ContourKind.NEAR_ALLPASS, 0.0, 0.0)
    elif family.name == "InteriorZero":
        # Recover color from zero_r relative to pole_radius
        color = (1.0 - family.zero_r / pole_radius) if pole_radius > 1e-6 else 0.0
        color = max(0.0, min(1.0, color))

        # Recover hue: octaves from pole_angle to zero_angle
        pole_angle = (
            math.acos(max(-1.0, min(1.0, -a1 / (2.0 * pole_radius))))
            if pole_radius > 1e-6
            else math.pi / 2.0
        )
        pole_freq = pole_angle * SR / TWO_PI
        zero_freq = family.zero_angle * SR / TWO_PI
        hue = math.log2(zero_freq / pole_freq) if pole_freq > 1e-6 and zero_freq > 1e-6 else 0.0

        return (ContourKind.INTERIOR_ZERO, color, hue)
    return (ContourKind.PURE, 0.0, 0.0)
