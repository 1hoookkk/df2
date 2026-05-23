"""Behavioral preset schema for authored TRENCH bodies."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pyruntime.constants import NUM_BODY_STAGES
from pyruntime.stage_roles import (
    DEFAULT_ROLE_BOUNDS,
    InterpolationPolicy,
    RoleBounds,
    StageRole,
    normalize_role_name,
    legacy_role_alias,
    parse_interpolation_policy,
    parse_stage_role,
    role_spec,
)


def _is_passthrough(stage, tol: float = 1e-12) -> bool:
    return (
        abs(stage.a1) <= tol
        and abs(stage.r) <= tol
        and abs(stage.val1) <= tol
        and abs(stage.val2) <= tol
        and abs(stage.val3) <= tol
    )


class RigidityClass(str, Enum):
    RIGID = "rigid"
    SEMI_RIGID = "semi_rigid"
    FLUID = "fluid"


class LegacyImportMode(str, Enum):
    ERROR = "error"
    WARN = "warn"
    ALLOW = "allow"


@dataclass(frozen=True)
class RolePolicy:
    role: StageRole
    rigidity: RigidityClass
    bounds: RoleBounds
    interpolation: InterpolationPolicy
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "rigidity": self.rigidity.value,
            "bounds": self.bounds.to_dict(),
            "interpolation": self.interpolation.value,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict, is_active: bool) -> "RolePolicy":
        role_raw = data.get("role")
        role = parse_stage_role(role_raw, allow_legacy=False)
        if role is None:
            raise ValueError(f"unknown stage role '{role_raw}' in typed role policy")
        rigidity_raw = data.get("rigidity")
        if rigidity_raw is None:
            rigidity = RigidityClass.FLUID if is_active else RigidityClass.RIGID
        else:
            try:
                rigidity = RigidityClass(normalize_role_name(str(rigidity_raw)))
            except ValueError:
                rigidity = RigidityClass.FLUID if is_active else RigidityClass.RIGID
        interpolation = parse_interpolation_policy(data.get("interpolation"))
        if interpolation is None:
            raise ValueError(f"unknown interpolation policy '{data.get('interpolation')}'")
        spec = role_spec(role)
        bounds = RoleBounds.from_dict(
            data.get("bounds"),
            spec.bounds if spec is not None else DEFAULT_ROLE_BOUNDS,
        )
        return cls(
            role=role,
            rigidity=rigidity,
            bounds=bounds,
            interpolation=interpolation,
            note=str(data.get("note", "")),
        )

    @classmethod
    def from_legacy(cls, role_name: str, is_active: bool) -> "RolePolicy":
        role = parse_stage_role(role_name, allow_legacy=True)
        if role is None:
            raise ValueError(f"unknown legacy stage role '{role_name}'")
        rigidity = RigidityClass.FLUID if is_active else RigidityClass.RIGID
        interpolation = InterpolationPolicy.LOG_FREQUENCY
        spec = role_spec(role)
        bounds = spec.bounds if spec is not None else DEFAULT_ROLE_BOUNDS
        note = ""
        return cls(
            role=role,
            rigidity=rigidity,
            bounds=bounds,
            interpolation=interpolation,
            note=note,
        )

    @classmethod
    def for_role(
        cls,
        role: StageRole,
        rigidity: RigidityClass,
        interpolation: InterpolationPolicy,
        bounds: RoleBounds | None = None,
        note: str = "",
    ) -> "RolePolicy":
        spec = role_spec(role)
        resolved_bounds = bounds or (spec.bounds if spec is not None else DEFAULT_ROLE_BOUNDS)
        return cls(
            role=role,
            rigidity=rigidity,
            bounds=resolved_bounds,
            interpolation=interpolation,
            note=note,
        )


@dataclass(frozen=True)
class PreDriveLaw:
    input_slam_db: float
    output_trim_db: float
    clip_mode: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "inputSlamDb": self.input_slam_db,
            "outputTrimDb": self.output_trim_db,
            "clipMode": self.clip_mode,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PreDriveLaw":
        return cls(
            input_slam_db=float(data["inputSlamDb"]),
            output_trim_db=float(data["outputTrimDb"]),
            clip_mode=str(data["clipMode"]),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True)
class CompensationLaw:
    mode: str
    rest_trim_db: float
    bright_trim_db: float
    sweep_q: float
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "restTrimDb": self.rest_trim_db,
            "brightTrimDb": self.bright_trim_db,
            "sweepQ": self.sweep_q,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CompensationLaw":
        return cls(
            mode=str(data["mode"]),
            rest_trim_db=float(data["restTrimDb"]),
            bright_trim_db=float(data["brightTrimDb"]),
            sweep_q=float(data["sweepQ"]),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True)
class MotionRegion:
    label: str
    morph_min: float
    morph_max: float
    q_min: float
    q_max: float
    behavior: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "morphMin": self.morph_min,
            "morphMax": self.morph_max,
            "qMin": self.q_min,
            "qMax": self.q_max,
            "behavior": self.behavior,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MotionRegion":
        return cls(
            label=str(data["label"]),
            morph_min=float(data["morphMin"]),
            morph_max=float(data["morphMax"]),
            q_min=float(data["qMin"]),
            q_max=float(data["qMax"]),
            behavior=str(data["behavior"]),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True)
class MotionThreshold:
    label: str
    morph: float
    q: float
    event: str
    allow_endpoint: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "morph": self.morph,
            "q": self.q,
            "event": self.event,
            "allowEndpoint": self.allow_endpoint,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MotionThreshold":
        return cls(
            label=str(data["label"]),
            morph=float(data["morph"]),
            q=float(data["q"]),
            event=str(data["event"]),
            allow_endpoint=bool(data.get("allowEndpoint", False)),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True)
class KnobSemantic:
    label: str
    axis: str
    min_value: float
    max_value: float
    curve: str
    behavior: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "axis": self.axis,
            "min": self.min_value,
            "max": self.max_value,
            "curve": self.curve,
            "behavior": self.behavior,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnobSemantic":
        return cls(
            label=str(data["label"]),
            axis=str(data["axis"]),
            min_value=float(data["min"]),
            max_value=float(data["max"]),
            curve=str(data["curve"]),
            behavior=str(data["behavior"]),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True)
class MotionLaw:
    mode: str
    sweep_q: float
    belch_point_morph: float
    belch_point_q: float
    asymmetry: str
    regions: list[MotionRegion]
    thresholds: list[MotionThreshold]
    knobs: list[KnobSemantic]
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "sweepQ": self.sweep_q,
            "belchPointMorph": self.belch_point_morph,
            "belchPointQ": self.belch_point_q,
            "asymmetry": self.asymmetry,
            "regions": [region.to_dict() for region in self.regions],
            "thresholds": [threshold.to_dict() for threshold in self.thresholds],
            "knobs": [knob.to_dict() for knob in self.knobs],
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MotionLaw":
        regions = [MotionRegion.from_dict(region) for region in data.get("regions", [])]
        thresholds = [
            MotionThreshold.from_dict(threshold)
            for threshold in data.get("thresholds", [])
        ]
        knobs = [KnobSemantic.from_dict(knob) for knob in data.get("knobs", [])]

        belch_point_morph = data.get("belchPointMorph")
        belch_point_q = data.get("belchPointQ")
        if belch_point_morph is None or belch_point_q is None:
            for threshold in thresholds:
                if normalize_role_name(threshold.label) == "belch_point":
                    belch_point_morph = threshold.morph
                    belch_point_q = threshold.q
                    break
        if belch_point_morph is None:
            belch_point_morph = 0.0
        if belch_point_q is None:
            belch_point_q = 0.0

        return cls(
            mode=str(data["mode"]),
            sweep_q=float(data["sweepQ"]),
            belch_point_morph=float(belch_point_morph),
            belch_point_q=float(belch_point_q),
            asymmetry=str(data["asymmetry"]),
            regions=regions,
            thresholds=thresholds,
            knobs=knobs,
            note=str(data.get("note", "")),
        )

    def primary_event(self, label: str) -> MotionThreshold | None:
        target = normalize_role_name(label)
        for threshold in self.thresholds:
            if normalize_role_name(threshold.label) == target:
                return threshold
        return None


_BOUNDS_DIMS = ("freq_hz", "radius", "gain", "zero_energy")


@dataclass(frozen=True)
class PresetSchema:
    active_stage_mask: list[bool]
    stage_roles: list[RolePolicy]
    pre_drive: PreDriveLaw
    compensation: CompensationLaw
    motion: MotionLaw
    version: int = 2

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "activeStageMask": self.active_stage_mask,
            "stageRoles": [role.to_dict() for role in self.stage_roles],
            "preDrive": self.pre_drive.to_dict(),
            "compensationLaw": self.compensation.to_dict(),
            "motionLaw": self.motion.to_dict(),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict,
        legacy_mode: LegacyImportMode = LegacyImportMode.ERROR,
        warnings: list[str] | None = None,
    ) -> "PresetSchema":
        active_mask = [bool(v) for v in data["activeStageMask"]]
        raw_roles = data.get("stageRoles", [])
        stage_roles: list[RolePolicy] = []
        if raw_roles and isinstance(raw_roles[0], dict):
            for idx, entry in enumerate(raw_roles):
                try:
                    stage_roles.append(RolePolicy.from_dict(entry, is_active=active_mask[idx]))
                except ValueError as exc:
                    raise ValueError(f"stageRoles[{idx}]: {exc}") from exc
        else:
            if legacy_mode == LegacyImportMode.ERROR:
                raise ValueError("legacy stageRoles are not allowed without an explicit migration step")
            for idx, entry in enumerate(raw_roles):
                role_name = str(entry)
                alias = legacy_role_alias(role_name)
                if alias is None:
                    raise ValueError(f"stageRoles[{idx}] uses unknown legacy role '{role_name}'")
                if warnings is not None and legacy_mode == LegacyImportMode.WARN:
                    warnings.append(
                        f"stageRoles[{idx}] legacy role '{role_name}' remapped to '{alias.value}'"
                    )
                stage_roles.append(RolePolicy.from_legacy(role_name, is_active=active_mask[idx]))
        return cls(
            version=int(data.get("version", 1)),
            active_stage_mask=active_mask,
            stage_roles=stage_roles,
            pre_drive=PreDriveLaw.from_dict(data["preDrive"]),
            compensation=CompensationLaw.from_dict(data["compensationLaw"]),
            motion=MotionLaw.from_dict(data["motionLaw"]),
        )

    def validate_for_body(self, body) -> list[str]:
        issues: list[str] = []
        if len(self.active_stage_mask) != NUM_BODY_STAGES:
            issues.append(
                f"activeStageMask must have {NUM_BODY_STAGES} entries, got {len(self.active_stage_mask)}"
            )
        if len(self.stage_roles) != NUM_BODY_STAGES:
            issues.append(
                f"stageRoles must have {NUM_BODY_STAGES} entries, got {len(self.stage_roles)}"
            )
        if issues:
            return issues

        for idx, role_policy in enumerate(self.stage_roles):
            spec = role_spec(role_policy.role)
            if spec is None:
                issues.append(f"stage {idx} uses unknown role '{role_policy.role}'")
                continue
            if role_policy.interpolation not in spec.allowed_interpolations:
                issues.append(
                    f"stage {idx} role '{role_policy.role.value}' disallows interpolation '{role_policy.interpolation.value}'"
                )
            for dim in _BOUNDS_DIMS:
                pb = getattr(role_policy.bounds, dim)
                if pb.min_value > pb.max_value:
                    issues.append(f"stage {idx} has invalid {dim} bounds")
                sb = getattr(spec.bounds, dim)
                if pb.min_value < sb.min_value:
                    issues.append(f"stage {idx} bounds dip below role '{role_policy.role.value}' {dim} band")
                if pb.max_value > sb.max_value:
                    issues.append(f"stage {idx} bounds exceed role '{role_policy.role.value}' {dim} band")

            is_active = self.active_stage_mask[idx]
            if is_active and role_policy.role == StageRole.LATENT:
                issues.append(f"stage {idx} marked active but role is latent")
            if not is_active and role_policy.role != StageRole.LATENT:
                issues.append(f"stage {idx} marked inactive but role is '{role_policy.role.value}'")

        if not self.motion.regions:
            issues.append("motionLaw must declare at least one region")
        for region in self.motion.regions:
            if region.morph_min >= region.morph_max:
                issues.append(f"motion region '{region.label}' has invalid morph bounds")
            if region.q_min > region.q_max:
                issues.append(f"motion region '{region.label}' has invalid q bounds")
        if self.motion.primary_event("BELCH_POINT") is None:
            issues.append("motionLaw must declare BELCH_POINT threshold")
        return issues
