"""Typed stage-role taxonomy for authored bodies."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StageRole(str, Enum):
    FORMANT = "formant"
    ANTI_FORMANT = "anti_formant"
    SHELF = "shelf"
    PHASE_SCAR = "phase_scar"
    CORRECTION_LIGAMENT = "correction_ligament"
    LATENT = "latent"


class InterpolationPolicy(str, Enum):
    LOG_FREQUENCY = "log_frequency"
    LINEAR_PHASE = "linear_phase"
    SIGMOIDAL_GAIN = "sigmoidal_gain"
    GROUP_DELAY_PROXY = "group_delay_proxy"
    LINEAR_RMS = "linear_rms"


@dataclass(frozen=True)
class Range:
    min_value: float
    max_value: float

    def to_dict(self) -> dict:
        return {"min": self.min_value, "max": self.max_value}

    @classmethod
    def from_dict(cls, data: dict | None, fallback: "Range") -> "Range":
        if data is None:
            return fallback
        return cls(
            min_value=float(data.get("min", fallback.min_value)),
            max_value=float(data.get("max", fallback.max_value)),
        )


@dataclass(frozen=True)
class RoleBounds:
    freq_hz: Range
    radius: Range
    gain: Range
    zero_energy: Range

    def to_dict(self) -> dict:
        return {
            "freqHz": self.freq_hz.to_dict(),
            "radius": self.radius.to_dict(),
            "gain": self.gain.to_dict(),
            "zeroEnergy": self.zero_energy.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict | None, fallback: "RoleBounds") -> "RoleBounds":
        if data is None:
            return fallback
        return cls(
            freq_hz=Range.from_dict(data.get("freqHz"), fallback.freq_hz),
            radius=Range.from_dict(data.get("radius"), fallback.radius),
            gain=Range.from_dict(data.get("gain"), fallback.gain),
            zero_energy=Range.from_dict(data.get("zeroEnergy"), fallback.zero_energy),
        )


@dataclass(frozen=True)
class StageRoleSpec:
    role: StageRole
    bounds: RoleBounds
    description: str
    allowed_interpolations: tuple[InterpolationPolicy, ...]
    active: bool = True



DEFAULT_ROLE_BOUNDS = RoleBounds(
    freq_hz=Range(0.0, 20000.0),
    radius=Range(0.0, 0.9999),
    gain=Range(0.1, 3.5),
    zero_energy=Range(0.0, 6.0),
)


ROLE_TAXONOMY: dict[StageRole, StageRoleSpec] = {
    StageRole.SHELF: StageRoleSpec(
        role=StageRole.SHELF,
        bounds=RoleBounds(
            freq_hz=Range(20.0, 400.0),
            radius=Range(0.05, 0.999),
            gain=Range(0.05, 3.0),
            zero_energy=Range(0.0, 1.0),
        ),
        description="low or high shelf anchor; acts as tonal floor or ceiling",
        allowed_interpolations=(
            InterpolationPolicy.LOG_FREQUENCY,
            InterpolationPolicy.LINEAR_RMS,
            InterpolationPolicy.SIGMOIDAL_GAIN,
        ),
    ),
    StageRole.CORRECTION_LIGAMENT: StageRoleSpec(
        role=StageRole.CORRECTION_LIGAMENT,
        bounds=RoleBounds(
            freq_hz=Range(80.0, 1200.0),
            radius=Range(0.05, 0.999),
            gain=Range(0.05, 3.0),
            zero_energy=Range(0.0, 2.0),
        ),
        description="supportive ligament that stabilizes spectral spread",
        allowed_interpolations=(
            InterpolationPolicy.LOG_FREQUENCY,
            InterpolationPolicy.LINEAR_RMS,
            InterpolationPolicy.GROUP_DELAY_PROXY,
        ),
    ),
    StageRole.FORMANT: StageRoleSpec(
        role=StageRole.FORMANT,
        bounds=RoleBounds(
            freq_hz=Range(200.0, 3200.0),
            radius=Range(0.1, 0.999),
            gain=Range(0.05, 3.5),
            zero_energy=Range(0.0, 3.0),
        ),
        description="vocal or resonant band-forming energy",
        allowed_interpolations=(
            InterpolationPolicy.LOG_FREQUENCY,
            InterpolationPolicy.SIGMOIDAL_GAIN,
            InterpolationPolicy.GROUP_DELAY_PROXY,
        ),
    ),
    StageRole.ANTI_FORMANT: StageRoleSpec(
        role=StageRole.ANTI_FORMANT,
        bounds=RoleBounds(
            freq_hz=Range(500.0, 8000.0),
            radius=Range(0.05, 0.999),
            gain=Range(0.05, 2.5),
            zero_energy=Range(0.05, 6.0),
        ),
        description="notch or subtraction cavity opposing a formant",
        allowed_interpolations=(
            InterpolationPolicy.LOG_FREQUENCY,
            InterpolationPolicy.LINEAR_PHASE,
            InterpolationPolicy.GROUP_DELAY_PROXY,
        ),
    ),
    StageRole.PHASE_SCAR: StageRoleSpec(
        role=StageRole.PHASE_SCAR,
        bounds=RoleBounds(
            freq_hz=Range(1200.0, 14000.0),
            radius=Range(0.05, 0.999),
            gain=Range(0.05, 3.5),
            zero_energy=Range(0.0, 6.0),
        ),
        description="abrasion or scar in upper bands; phase memory",
        allowed_interpolations=(
            InterpolationPolicy.LOG_FREQUENCY,
            InterpolationPolicy.LINEAR_PHASE,
            InterpolationPolicy.GROUP_DELAY_PROXY,
        ),
    ),
    StageRole.LATENT: StageRoleSpec(
        role=StageRole.LATENT,
        bounds=RoleBounds(
            freq_hz=Range(0.0, 0.0),
            radius=Range(0.0, 0.0),
            gain=Range(1.0, 1.0),
            zero_energy=Range(0.0, 0.0),
        ),
        description="inactive slot; passthrough only",
        allowed_interpolations=(InterpolationPolicy.LINEAR_RMS,),
        active=False,
    ),
}


LEGACY_ROLE_ALIASES: dict[str, StageRole] = {
    "foundation": StageRole.SHELF,
    "mass": StageRole.FORMANT,
    "throat": StageRole.FORMANT,
    "bite": StageRole.FORMANT,
    "air": StageRole.PHASE_SCAR,
    "scar": StageRole.ANTI_FORMANT,
    "inactive": StageRole.LATENT,
}


def normalize_role_name(name: str) -> str:
    return name.strip().lower()


def parse_stage_role(value: str | StageRole | None, allow_legacy: bool = False) -> StageRole | None:
    if value is None:
        return None
    if isinstance(value, StageRole):
        return value
    key = normalize_role_name(str(value))
    try:
        return StageRole(key)
    except ValueError:
        if allow_legacy:
            return LEGACY_ROLE_ALIASES.get(key)
        return None


def legacy_role_alias(name: str) -> StageRole | None:
    return LEGACY_ROLE_ALIASES.get(normalize_role_name(name))


def parse_interpolation_policy(value: str | InterpolationPolicy | None) -> InterpolationPolicy | None:
    if value is None:
        return None
    if isinstance(value, InterpolationPolicy):
        return value
    key = normalize_role_name(str(value))
    try:
        return InterpolationPolicy(key)
    except ValueError:
        return None


def role_spec(role: StageRole | str | None) -> StageRoleSpec | None:
    parsed = parse_stage_role(role, allow_legacy=False) if not isinstance(role, StageRole) else role
    if parsed is None:
        return None
    return ROLE_TAXONOMY.get(parsed)
