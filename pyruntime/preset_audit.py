"""Validation and audit framework for behavioral preset truth."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.preset_schema import RigidityClass
from pyruntime.stage_roles import StageRole, role_spec

LOW_BAND_MAX_HZ = 250.0
HIGH_BAND_MIN_HZ = 2500.0
_FREQS = freq_points()

RIGID_FREQ_TOL_HZ = 5.0
RIGID_RADIUS_TOL = 1e-3
RIGID_GAIN_TOL = 1e-3
RIGID_ZERO_ENERGY_TOL = 1e-3

EDGE_TOL = 1e-6


@dataclass(frozen=True)
class AuditFinding:
    kind: str
    severity: str
    message: str


@dataclass(frozen=True)
class SweepAuditMetric:
    morph: float
    q: float
    centroid_hz: float
    low_band_db: float
    high_band_db: float
    tilt_db: float
    peak_db: float


@dataclass(frozen=True)
class PresetAuditReport:
    findings: list[AuditFinding]
    sweep: list[SweepAuditMetric]
    metrics: dict

    def errors(self) -> list[AuditFinding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    def warnings(self) -> list[AuditFinding]:
        return [finding for finding in self.findings if finding.severity == "warning"]

    def passed(self) -> bool:
        return not self.errors()


@dataclass(frozen=True)
class StageStats:
    freq_min: float
    freq_max: float
    radius_min: float
    radius_max: float
    gain_min: float
    gain_max: float
    zero_energy_min: float
    zero_energy_max: float
    any_non_passthrough: bool

    @property
    def freq_span(self) -> float:
        return self.freq_max - self.freq_min

    @property
    def radius_span(self) -> float:
        return self.radius_max - self.radius_min

    @property
    def gain_span(self) -> float:
        return self.gain_max - self.gain_min

    @property
    def zero_energy_span(self) -> float:
        return self.zero_energy_max - self.zero_energy_min


def _measure_point(body, morph: float, q: float) -> SweepAuditMetric:
    db = cascade_response_db(body.corners.interpolate(morph, q), _FREQS)
    mag = 10.0 ** (db / 20.0)
    centroid = float((_FREQS * mag).sum() / mag.sum())
    low_band = float(db[_FREQS <= LOW_BAND_MAX_HZ].mean())
    high_band = float(db[_FREQS >= HIGH_BAND_MIN_HZ].mean())
    return SweepAuditMetric(
        morph=morph,
        q=q,
        centroid_hz=centroid,
        low_band_db=low_band,
        high_band_db=high_band,
        tilt_db=high_band - low_band,
        peak_db=float(db.max()),
    )


def _strongest_jump(sweep: list[SweepAuditMetric]) -> tuple[float, SweepAuditMetric]:
    """Find the sweep point with the largest centroid step."""
    best = float("-inf")
    best_metric = sweep[1]
    for idx in range(1, len(sweep) - 1):
        jump = sweep[idx].centroid_hz - sweep[idx - 1].centroid_hz
        if jump > best:
            best = jump
            best_metric = sweep[idx]
    return best, best_metric


def _measure_sweep(body, q: float, points: int = 17) -> list[SweepAuditMetric]:
    morphs = np.linspace(0.0, 1.0, points)
    return [_measure_point(body, float(morph), q) for morph in morphs]


def _stage_stats(body) -> list[StageStats]:
    stats: list[StageStats] = []
    corner_names = list(body.corners.names())
    for idx in range(len(body.corners.corner(corner_names[0]).stages)):
        stages = [body.corners.corner(name).stages[idx] for name in corner_names]
        non_passthrough = [stage for stage in stages if stage.r > 1e-12]
        any_non_passthrough = bool(non_passthrough)

        if non_passthrough:
            freqs = [stage.freq_hz() for stage in non_passthrough]
            radii = [stage.radius() for stage in non_passthrough]
            gains = [stage.gain() for stage in non_passthrough]
            zero_energy = [stage.zero_energy() for stage in non_passthrough]
        else:
            freqs = [0.0]
            radii = [0.0]
            gains = [1.0]
            zero_energy = [0.0]

        stats.append(
            StageStats(
                freq_min=min(freqs),
                freq_max=max(freqs),
                radius_min=min(radii),
                radius_max=max(radii),
                gain_min=min(gains),
                gain_max=max(gains),
                zero_energy_min=min(zero_energy),
                zero_energy_max=max(zero_energy),
                any_non_passthrough=any_non_passthrough,
            )
        )
    return stats


def _schema_audit(body) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    schema = body.preset_schema
    if schema is None:
        findings.append(AuditFinding("schema", "error", "presetSchema missing"))
        return findings
    for issue in schema.validate_for_body(body):
        findings.append(AuditFinding("schema", "error", issue))
    return findings


def _check_bounds(idx: int, label: str, stat: StageStats, bounds, dims: list[tuple[str, str, str]]) -> list[AuditFinding]:
    """Check stage stats against bounds for named dimensions."""
    findings = []
    for dim_name, stat_min_attr, stat_max_attr in dims:
        bound = getattr(bounds, dim_name)
        stat_min = getattr(stat, stat_min_attr)
        stat_max = getattr(stat, stat_max_attr)
        if stat_min < bound.min_value or stat_max > bound.max_value:
            findings.append(AuditFinding("taxonomy", "error", f"stage {idx} {label} {dim_name} out of bounds"))
    return findings


_BOUNDS_DIMS = [
    ("freq_hz", "freq_min", "freq_max"),
    ("radius", "radius_min", "radius_max"),
    ("gain", "gain_min", "gain_max"),
    ("zero_energy", "zero_energy_min", "zero_energy_max"),
]


def _taxonomy_audit(body) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    schema = body.preset_schema
    if schema is None:
        return findings

    stats = _stage_stats(body)
    for idx, (role_policy, stage_stat, is_active) in enumerate(
        zip(schema.stage_roles, stats, schema.active_stage_mask)
    ):
        if is_active and not stage_stat.any_non_passthrough:
            findings.append(
                AuditFinding(
                    "taxonomy",
                    "error",
                    f"stage {idx} marked active but is passthrough in every corner",
                )
            )
        if not is_active and stage_stat.any_non_passthrough:
            findings.append(
                AuditFinding(
                    "taxonomy",
                    "error",
                    f"stage {idx} marked inactive but carries authored data",
                )
            )
        if role_policy.role == StageRole.LATENT and stage_stat.any_non_passthrough:
            findings.append(
                AuditFinding(
                    "taxonomy",
                    "error",
                    f"stage {idx} role latent but carries authored data",
                )
            )
        if role_policy.role != StageRole.LATENT and not stage_stat.any_non_passthrough:
            findings.append(
                AuditFinding(
                    "taxonomy",
                    "error",
                    f"stage {idx} role '{role_policy.role.value}' has no authored data",
                )
            )

        spec = role_spec(role_policy.role)
        if spec is None:
            continue

        if stage_stat.any_non_passthrough:
            findings.extend(_check_bounds(idx, f"role '{role_policy.role.value}'", stage_stat, spec.bounds, _BOUNDS_DIMS))

        if role_policy.rigidity == RigidityClass.RIGID and stage_stat.any_non_passthrough:
            if (
                stage_stat.freq_span > RIGID_FREQ_TOL_HZ
                or stage_stat.radius_span > RIGID_RADIUS_TOL
                or stage_stat.gain_span > RIGID_GAIN_TOL
                or stage_stat.zero_energy_span > RIGID_ZERO_ENERGY_TOL
            ):
                findings.append(
                    AuditFinding(
                        "taxonomy",
                        "error",
                        f"stage {idx} marked rigid but moves across corners",
                    )
                )

        if role_policy.rigidity == RigidityClass.SEMI_RIGID and stage_stat.any_non_passthrough:
            findings.extend(_check_bounds(idx, "semi-rigid", stage_stat, role_policy.bounds, _BOUNDS_DIMS))

    return findings


def _motion_audit(body, sweep: list[SweepAuditMetric], strongest_jump_metric: SweepAuditMetric | None = None) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    schema = body.preset_schema
    if schema is None:
        return findings

    regions = schema.motion.regions
    if not regions:
        findings.append(AuditFinding("motion", "error", "motionLaw must declare at least one region"))
        return findings

    ordered = sorted(regions, key=lambda r: r.morph_min)
    if ordered != regions:
        findings.append(AuditFinding("motion", "error", "motion regions are not ordered by morph_min"))
    if ordered[0].morph_min > EDGE_TOL:
        findings.append(AuditFinding("motion", "error", "motion regions do not cover morph=0.0"))
    if ordered[-1].morph_max < 1.0 - EDGE_TOL:
        findings.append(AuditFinding("motion", "error", "motion regions do not cover morph=1.0"))
    for prev, curr in zip(ordered, ordered[1:]):
        if curr.morph_min > prev.morph_max + EDGE_TOL:
            findings.append(
                AuditFinding(
                    "motion",
                    "error",
                    f"motion regions gap between '{prev.label}' and '{curr.label}'",
                )
            )

    for threshold in schema.motion.thresholds:
        if not threshold.allow_endpoint:
            if threshold.morph <= EDGE_TOL or threshold.morph >= 1.0 - EDGE_TOL:
                findings.append(
                    AuditFinding(
                        "motion",
                        "error",
                        f"threshold '{threshold.label}' must be interior unless marked allowEndpoint",
                    )
                )
            if threshold.q <= EDGE_TOL or threshold.q >= 1.0 - EDGE_TOL:
                findings.append(
                    AuditFinding(
                        "motion",
                        "error",
                        f"threshold '{threshold.label}' must be interior unless marked allowEndpoint",
                    )
                )

    declared_belch = schema.motion.primary_event("BELCH_POINT")
    if declared_belch is None:
        findings.append(AuditFinding("motion", "error", "motionLaw must declare BELCH_POINT threshold"))
    else:
        if len(sweep) < 3 or strongest_jump_metric is None:
            findings.append(AuditFinding("motion", "error", "motion sweep too small to locate belch"))
        else:
            morph_delta = abs(strongest_jump_metric.morph - declared_belch.morph)
            if morph_delta > 0.16:
                findings.append(
                    AuditFinding(
                        "motion",
                        "error",
                        (
                            f"declared BELCH_POINT morph {declared_belch.morph:.2f} "
                            f"does not match measured strongest jump at {strongest_jump_metric.morph:.2f}"
                        ),
                    )
                )

    return findings


def _truthful_semantics_audit(body, metrics: dict) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    schema = body.preset_schema
    if schema is None:
        return findings

    if schema.motion.asymmetry.strip().lower() == "dark_to_bright":
        if metrics["centroid_span_hz"] < 600.0:
            findings.append(
                AuditFinding(
                    "semantics",
                    "error",
                    "motion claims dark_to_bright but centroid span is too small",
                )
            )
        if metrics["tilt_delta_db"] < 15.0:
            findings.append(
                AuditFinding(
                    "semantics",
                    "error",
                    "motion claims dark_to_bright but tilt shift is too small",
                )
            )
        if metrics["low_band_drop_db"] < 10.0:
            findings.append(
                AuditFinding(
                    "semantics",
                    "error",
                    "motion claims dark_to_bright but low-band drop is too small",
                )
            )
        if schema.compensation.rest_trim_db >= schema.compensation.bright_trim_db:
            findings.append(
                AuditFinding(
                    "semantics",
                    "error",
                    "compensationLaw claims dark-to-bright trim but rest trim is not lower than bright trim",
                )
            )
        if metrics["low_band_drop_db"] < 10.0:
            findings.append(
                AuditFinding(
                    "semantics",
                    "error",
                    "compensationLaw claims dark floor to bright exit but low-band drop is too small",
                )
            )

    return findings


def audit_preset(body, points: int = 17) -> PresetAuditReport:
    findings: list[AuditFinding] = []
    schema_findings = _schema_audit(body)
    findings.extend(schema_findings)

    schema = body.preset_schema
    if schema is None:
        return PresetAuditReport(findings=findings, sweep=[], metrics={})

    sweep = _measure_sweep(body, schema.motion.sweep_q, points=points)
    if not sweep:
        findings.append(AuditFinding("motion", "error", "motion sweep could not be measured"))
        return PresetAuditReport(findings=findings, sweep=sweep, metrics={})

    start = sweep[0]
    end = sweep[-1]
    strongest_jump, strongest_jump_metric = _strongest_jump(sweep)

    metrics = {
        "sweep_q": schema.motion.sweep_q,
        "centroid_span_hz": end.centroid_hz - start.centroid_hz,
        "tilt_delta_db": end.tilt_db - start.tilt_db,
        "low_band_drop_db": start.low_band_db - end.low_band_db,
        "strongest_jump_hz": strongest_jump,
        "measured_belch_morph": strongest_jump_metric.morph,
        "measured_belch_q": strongest_jump_metric.q,
    }

    findings.extend(_taxonomy_audit(body))
    findings.extend(_motion_audit(body, sweep, strongest_jump_metric))
    findings.extend(_truthful_semantics_audit(body, metrics))

    return PresetAuditReport(findings=findings, sweep=sweep, metrics=metrics)

