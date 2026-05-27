"""One usable forge recipe: slammed dark->bright belch.

The recipe stays inside the Python runtime path:
spec -> compile_body() -> audit sweep -> export raw body JSON.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pyruntime.body import Body
from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.macro_compile import (
    Actor,
    BodySpec,
    CompileMacro,
    PressureBehavior,
    SlotSpec,
    SlotState,
    compile_body,
    freq_to_place,
)
from pyruntime.preset_audit import audit_preset
from pyruntime.preset_schema import (
    CompensationLaw,
    KnobSemantic,
    MotionLaw,
    MotionRegion,
    MotionThreshold,
    PreDriveLaw,
    PresetSchema,
    RigidityClass,
    RolePolicy,
)
from pyruntime.stage_roles import InterpolationPolicy, StageRole
from pyruntime.validator import validate
from pyruntime.zero_law import ContourKind

RECIPE_NAME = "Slammed_Dark_Bright_Belch"
SWEEP_Q = 0.82
BELCH_SCAN_POINTS = 9
LOW_BAND_MAX_HZ = 250.0
HIGH_BAND_MIN_HZ = 2500.0
_FREQS = freq_points()


@dataclass(frozen=True)
class SweepMetric:
    morph: float
    q: float
    centroid_hz: float
    low_band_db: float
    high_band_db: float
    tilt_db: float
    peak_db: float


@dataclass(frozen=True)
class AuditionPoint:
    label: str
    morph: float
    q: float
    note: str


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str


def _slot_state(
    actor: Actor,
    freq_hz: float,
    focus: float,
    weight: float,
    contour: ContourKind,
    color: float = 0.0,
    hue: float = 0.0,
) -> SlotState:
    return SlotState(
        place=freq_to_place(actor, freq_hz),
        focus=focus,
        weight=weight,
        contour=contour,
        color=color,
        hue=hue,
        contour_override=None,
    )


def build_slammed_dark_bright_belch_spec() -> BodySpec:
    """Author one dark->bright belch body through the proven slot compiler."""
    slots = [
        SlotSpec(
            Actor.FOUNDATION,
            _slot_state(Actor.FOUNDATION, 80.0, 0.54, 0.70, ContourKind.PURE),
            _slot_state(Actor.FOUNDATION, 160.0, 0.42, 0.36, ContourKind.PURE),
            PressureBehavior.COLLAPSE,
            CompileMacro.SINGLE,
            0.0,
        ),
        SlotSpec(
            Actor.MASS,
            _slot_state(Actor.MASS, 190.0, 0.52, 0.62, ContourKind.NEAR_ALLPASS, 0.10, 0.0),
            _slot_state(Actor.MASS, 450.0, 0.48, 0.40, ContourKind.INTERIOR_ZERO, 0.22, 0.18),
            PressureBehavior.YIELD,
            CompileMacro.SINGLE,
            0.0,
        ),
        SlotSpec(
            Actor.THROAT,
            _slot_state(Actor.THROAT, 340.0, 0.60, 0.52, ContourKind.UNIT_CIRCLE),
            _slot_state(Actor.THROAT, 1100.0, 0.82, 0.82, ContourKind.INTERIOR_ZERO, 0.12, 0.0),
            PressureBehavior.TIGHTEN,
            CompileMacro.SINGLE,
            0.0,
        ),
        SlotSpec(
            Actor.BITE,
            _slot_state(Actor.BITE, 950.0, 0.48, 0.24, ContourKind.INTERIOR_ZERO, 0.22, -0.15),
            _slot_state(Actor.BITE, 2800.0, 0.80, 0.74, ContourKind.UNIT_CIRCLE),
            PressureBehavior.TIGHTEN,
            CompileMacro.SINGLE,
            0.0,
        ),
        SlotSpec(
            Actor.AIR,
            _slot_state(Actor.AIR, 2600.0, 0.30, 0.14, ContourKind.PURE),
            _slot_state(Actor.AIR, 8800.0, 0.68, 0.42, ContourKind.INTERIOR_ZERO, 0.18, 0.45),
            PressureBehavior.CROSS,
            CompileMacro.SINGLE,
            0.0,
        ),
        SlotSpec(
            Actor.SCAR,
            _slot_state(Actor.SCAR, 1700.0, 0.28, 0.10, ContourKind.INTERIOR_ZERO, 0.55, -0.35),
            _slot_state(Actor.SCAR, 5600.0, 0.74, 0.40, ContourKind.INTERIOR_ZERO, 0.42, 0.28),
            PressureBehavior.COLLAPSE,
            CompileMacro.SINGLE,
            0.0,
        ),
    ]
    return BodySpec(name=RECIPE_NAME, slots=slots, boost=5.5)


def build_slammed_dark_bright_belch_preset_schema(belch_point: AuditionPoint) -> PresetSchema:
    active_stage_mask = [True, True, True, True, True, True] + [False] * 6
    def role(role: StageRole) -> RolePolicy:
        return RolePolicy.for_role(
            role=role,
            rigidity=RigidityClass.FLUID,
            interpolation=InterpolationPolicy.LOG_FREQUENCY,
        )

    def latent() -> RolePolicy:
        return RolePolicy.for_role(
            role=StageRole.LATENT,
            rigidity=RigidityClass.RIGID,
            interpolation=InterpolationPolicy.LINEAR_RMS,
        )

    stage_roles = [
        role(StageRole.SHELF),
        role(StageRole.CORRECTION_LIGAMENT),
        role(StageRole.FORMANT),
        role(StageRole.FORMANT),
        role(StageRole.PHASE_SCAR),
        role(StageRole.ANTI_FORMANT),
        latent(),
        latent(),
        latent(),
        latent(),
        latent(),
        latent(),
    ]
    return PresetSchema(
        active_stage_mask=active_stage_mask,
        stage_roles=stage_roles,
        pre_drive=PreDriveLaw(
            input_slam_db=25.0,
            output_trim_db=-18.0,
            clip_mode="hard-clip-v1",
            note="Dense pre-filter slam is part of the preset identity, not optional polish.",
        ),
        compensation=CompensationLaw(
            mode="dark-to-bright-trim-v1",
            rest_trim_db=-24.0,
            bright_trim_db=1.5,
            sweep_q=SWEEP_Q,
            note="Treat compensation as authored balance between dark floor and bright exit.",
        ),
        motion=MotionLaw(
            mode="belch-sweep-v1",
            sweep_q=SWEEP_Q,
            belch_point_morph=belch_point.morph,
            belch_point_q=belch_point.q,
            asymmetry="dark_to_bright",
            regions=[
                MotionRegion(
                    label="DARK_FLOOR",
                    morph_min=0.0,
                    morph_max=0.45,
                    q_min=0.0,
                    q_max=1.0,
                    behavior="low-dominant floor",
                    note="Weight leads. Brightness remains subordinate.",
                ),
                MotionRegion(
                    label="BELCH_RAMP",
                    morph_min=0.45,
                    morph_max=0.82,
                    q_min=0.65,
                    q_max=1.0,
                    behavior="centroid surge under stress",
                    note="This is the pressure release corridor.",
                ),
                MotionRegion(
                    label="BRIGHT_EXIT",
                    morph_min=0.82,
                    morph_max=1.0,
                    q_min=0.65,
                    q_max=1.0,
                    behavior="bright hollow recovery",
                    note="The body has turned over and shed the floor weight.",
                ),
            ],
            thresholds=[
                MotionThreshold(
                    label="BELCH_POINT",
                    morph=belch_point.morph,
                    q=belch_point.q,
                    event="centroid_jump",
                    allow_endpoint=False,
                    note="Primary internal threshold for the dark->bright break.",
                )
            ],
            knobs=[
                KnobSemantic(
                    label="MORPH",
                    axis="morph",
                    min_value=0.0,
                    max_value=1.0,
                    curve="linear",
                    behavior="body transition between dark floor and bright exit",
                ),
                KnobSemantic(
                    label="PRESSURE",
                    axis="q",
                    min_value=0.0,
                    max_value=1.0,
                    curve="linear",
                    behavior="stress control for sweep emphasis",
                ),
            ],
            note="Slow sweep reveals the interior belch; the reverse path should read as a different recovery.",
        ),
    )


def compile_slammed_dark_bright_belch() -> Body:
    spec = build_slammed_dark_bright_belch_spec()
    body = Body(name=spec.name, corners=compile_body(spec), boost=spec.boost)
    belch_point = find_belch_point(build_sweep(body))
    body.preset_schema = build_slammed_dark_bright_belch_preset_schema(belch_point)
    return body


def _response_metric(body: Body, morph: float, q: float) -> SweepMetric:
    db = cascade_response_db(body.corners.interpolate(morph, q), _FREQS)
    mag = 10.0 ** (db / 20.0)
    centroid = float((_FREQS * mag).sum() / mag.sum())
    low_band = float(db[_FREQS <= LOW_BAND_MAX_HZ].mean())
    high_band = float(db[_FREQS >= HIGH_BAND_MIN_HZ].mean())
    return SweepMetric(
        morph=morph,
        q=q,
        centroid_hz=centroid,
        low_band_db=low_band,
        high_band_db=high_band,
        tilt_db=high_band - low_band,
        peak_db=float(db.max()),
    )


def build_sweep(body: Body, q: float = SWEEP_Q, points: int = BELCH_SCAN_POINTS) -> list[SweepMetric]:
    morphs = np.linspace(0.0, 1.0, points)
    return [_response_metric(body, float(morph), q) for morph in morphs]


def find_belch_point(sweep: list[SweepMetric]) -> AuditionPoint:
    if len(sweep) < 2:
        raise ValueError("Belch scan needs at least two sweep points")

    best_idx = 1
    best_score = float("-inf")
    for idx in range(1, len(sweep) - 1):
        curr = sweep[idx]
        prev = sweep[idx - 1]
        if curr.morph < 0.5 or curr.morph >= 0.95:
            continue
        centroid_jump = curr.centroid_hz - prev.centroid_hz
        score = centroid_jump + max(0.0, curr.peak_db - 20.0) * 35.0 + curr.tilt_db * 20.0
        if score > best_score:
            best_score = score
            best_idx = idx

    point = sweep[best_idx]
    return AuditionPoint(
        label="BELCH_POINT",
        morph=point.morph,
        q=point.q,
        note=(
            "Run the sweep with +25 dB pre-filter slam, then stop here when the "
            "centroid jumps but the low body has not fully fallen away."
        ),
    )


def build_ab_audition(body: Body, belch_point: AuditionPoint) -> list[AuditionPoint]:
    return [
        AuditionPoint(
            label="A_DARK_FLOOR",
            morph=0.12,
            q=0.24,
            note="Slack opening. Hear the padded dark floor before the belch starts.",
        ),
        belch_point,
        AuditionPoint(
            label="B_BRIGHT_EXIT",
            morph=1.0,
            q=SWEEP_Q,
            note="Post-belch bright exit. Compare this against A, not against the interior hit.",
        ),
    ]


def run_three_gate_pipeline(body: Body) -> list[GateResult]:
    issues = validate(body.corners)
    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity != "error"]
    audit = audit_preset(body)
    audit_errors = [finding for finding in audit.findings if finding.severity == "error"]

    sweep = build_sweep(body)
    belch_point = find_belch_point(sweep)
    belch_metric = next(metric for metric in sweep if abs(metric.morph - belch_point.morph) < 1e-9)

    sweep_start = sweep[0]
    sweep_end = sweep[-1]
    centroid_span = sweep_end.centroid_hz - sweep_start.centroid_hz
    tilt_delta = sweep_end.tilt_db - sweep_start.tilt_db
    low_band_drop = sweep_start.low_band_db - sweep_end.low_band_db

    biggest_jump = max(
        sweep[idx].centroid_hz - sweep[idx - 1].centroid_hz
        for idx in range(1, len(sweep))
        if sweep[idx].morph >= 0.5
    )

    return [
        GateResult(
            name="gate_1_surface_integrity",
            passed=(not errors and len(warnings) <= 3 and not audit_errors),
            detail=(
                f"{len(errors)} errors, {len(warnings)} warnings, {len(audit_errors)} audit errors. "
                "Recipe stays legal only if stability, bounded crowding, and declared preset schema agree."
            ),
        ),
        GateResult(
            name="gate_2_dark_to_bright_sweep",
            passed=(centroid_span >= 1200.0 and tilt_delta >= 25.0 and low_band_drop >= 20.0),
            detail=(
                f"centroid_span={centroid_span:.1f}Hz, "
                f"tilt_delta={tilt_delta:.1f}dB, low_band_drop={low_band_drop:.1f}dB"
            ),
        ),
        GateResult(
            name="gate_3_belch_emergence",
            passed=(
                biggest_jump >= 800.0
                and belch_metric.peak_db >= 20.0
                and -25.0 <= belch_metric.tilt_db <= -5.0
            ),
            detail=(
                f"belch_morph={belch_metric.morph:.2f}, "
                f"centroid_jump={biggest_jump:.1f}Hz, "
                f"peak={belch_metric.peak_db:.1f}dB, tilt={belch_metric.tilt_db:.1f}dB"
            ),
        ),
    ]


def _report_dict(body: Body) -> dict:
    sweep = build_sweep(body)
    belch_point = find_belch_point(sweep)
    gates = run_three_gate_pipeline(body)
    audition = build_ab_audition(body, belch_point)
    audit = audit_preset(body)

    return {
        "name": body.name,
        "preset_schema": body.preset_schema.to_dict() if body.preset_schema is not None else None,
        "recommended_input_slam_db": 25.0,
        "recommended_output_trim_db": -18.0,
        "sweep_q": SWEEP_Q,
        "sweep": [metric.__dict__ for metric in sweep],
        "belch_point": belch_point.__dict__,
        "audition": [point.__dict__ for point in audition],
        "gates": [gate.__dict__ for gate in gates],
        "audit": {
            "passed": audit.passed(),
            "metrics": audit.metrics,
            "findings": [finding.__dict__ for finding in audit.findings],
        },
    }


def export_slammed_dark_bright_belch(out_dir: str | Path) -> dict:
    body = compile_slammed_dark_bright_belch()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    body_path = out_path / f"{body.name}.json"
    report_path = out_path / f"{body.name}.report.json"
    body_path.write_text(body.to_json(), encoding="utf-8")
    report = _report_dict(body)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {
        "body_path": str(body_path),
        "report_path": str(report_path),
        "report": report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile and export the slammed dark->bright belch Python forge recipe."
    )
    parser.add_argument(
        "--out-dir",
        default="artifacts/forge_recipes",
        help="Directory for the raw body JSON and the 3-gate report.",
    )
    args = parser.parse_args(argv)

    result = export_slammed_dark_bright_belch(args.out_dir)
    print(result["body_path"])
    print(result["report_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
