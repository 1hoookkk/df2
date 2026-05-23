"""Stage parameter construction from frequency/radius/zero specifications.

Authoring invariant for carve stages:
  val3 = r^2 - 1 - val1
  val2 = 2 * (r - 1 - val1) * cos(theta)

Those equations are the unit-circle, same-angle special case of the general
zero-placement law below, and they lock topology so val2/val3 are derived
instead of independently mutated.
"""
import math

from pyruntime.constants import SR, TWO_PI
from pyruntime.stage_params import StageParams


def _pole_angle(freq_hz: float) -> float:
    clamped = max(20.0, min(SR * 0.48, float(freq_hz)))
    return TWO_PI * clamped / SR


def resonator(freq_hz: float, radius: float, val1: float) -> StageParams:
    """All-pole resonator. val2=0, val3=0."""
    theta = _pole_angle(freq_hz)
    return StageParams(
        a1=-2.0 * radius * math.cos(theta),
        r=radius,
        val1=val1,
        val2=0.0,
        val3=0.0,
    )


def resonator_with_zero(
    freq_hz: float,
    radius: float,
    val1: float,
    zero_freq_hz: float,
    zero_radius: float,
) -> StageParams:
    """Resonator with explicit zero placement.

    The solver mutates (pole, zero, val1). val2/val3 are derived from those.
    Numerator targets are scaled by b0=(1+val1), so zero depth is controlled
    by val1 and cannot drift independently.
    """
    theta = _pole_angle(freq_hz)
    phi = _pole_angle(zero_freq_hz)

    a1 = -2.0 * radius * math.cos(theta)
    b0 = 1.0 + val1
    b1_target = -2.0 * zero_radius * math.cos(phi) * b0
    b2_target = (zero_radius * zero_radius) * b0

    val2 = b1_target - a1
    val3 = radius * radius - b2_target
    return StageParams(a1=a1, r=radius, val1=val1, val2=val2, val3=val3)


def zero_forced(freq_hz: float, radius: float, val1: float) -> StageParams:
    """Unit-circle zero at pole frequency using locked topology law."""
    return resonator_with_zero(freq_hz, radius, val1, freq_hz, 1.0)


def zero_forced_offset(
    freq_hz: float, radius: float, val1: float, offset_semitones: float
) -> StageParams:
    """Unit-circle zero offset from pole by semitones."""
    zero_freq = freq_hz * 2.0 ** (offset_semitones / 12.0)
    zero_freq = max(20.0, min(SR * 0.48, zero_freq))
    return resonator_with_zero(freq_hz, radius, val1, zero_freq, 1.0)
