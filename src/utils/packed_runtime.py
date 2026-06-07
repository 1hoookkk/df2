"""Post-pack terrain scoring through the shipped trench-core runtime."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from pyruntime import trench_ffi
from src.utils.terrain_metrics import analyze_body, state_metrics

ENDPOINTS = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
EDGES = (((0.0, 0.0), (1.0, 0.0)), ((0.0, 1.0), (1.0, 1.0)),
         ((0.0, 0.0), (0.0, 1.0)), ((1.0, 0.0), (1.0, 1.0)))


def _median(values: list[float]) -> float:
    return float(np.median(values)) if values else 0.0


def evaluate_body(body: bytes, grid_steps: int) -> dict[str, Any]:
    """Measure one real packed body. No floating-point surrogate is authoritative."""
    if len(body) != trench_ffi.BODY_BYTES:
        raise ValueError(f"expected {trench_ffi.BODY_BYTES} bytes, got {len(body)}")
    detailed = analyze_body(body)
    points = np.linspace(0.0, 1.0, int(grid_steps))
    probes = [trench_ffi.packed_probe(body, float(morph), float(secondary))
              for secondary in points for morph in points]
    # The shipped player sweeps the continuous interior, not just the grid nodes.
    # Probe the cell midpoints between nodes so instability that peaks off-grid is caught.
    interior_axis = (points[:-1] + points[1:]) / 2.0
    interior = [trench_ffi.packed_probe(body, float(morph), float(secondary))
                for secondary in interior_axis for morph in interior_axis]
    states = {point: state_metrics(body, *point) for edge in EDGES for point in edge}
    zero_motion, pole_motion, disagreement = [], [], []
    for start, end in EDGES:
        for before, after in zip(states[start]["stages"], states[end]["stages"]):
            if not before.get("active") or not after.get("active"):
                continue
            if before.get("pole_hz") and after.get("pole_hz"):
                pole = math.log2(after["pole_hz"] / before["pole_hz"])
                pole_motion.append(abs(pole))
                if before.get("zero_hz") and after.get("zero_hz"):
                    zero = math.log2(after["zero_hz"] / before["zero_hz"])
                    zero_motion.append(abs(zero))
                    disagreement.append(abs(zero - pole))
    endpoints = [state_metrics(body, *point) for point in ENDPOINTS]
    interior_max_radius = max((float(probe["max_pole_radius"]) for probe in interior), default=0.0)
    max_radius = max(max(float(probe["max_pole_radius"]) for probe in probes), interior_max_radius)
    metrics = {
        **detailed,
        "grid_steps": int(grid_steps),
        "grid_points": len(probes),
        "grid_unstable_rows": sum(int(probe["unstable_mask"]).bit_count() for probe in probes),
        "grid_nonfinite_rows": sum(int(probe["nonfinite_mask"]).bit_count() for probe in probes),
        "interior_grid_points": len(interior),
        "interior_unstable_rows": sum(int(probe["unstable_mask"]).bit_count() for probe in interior),
        "interior_nonfinite_rows": sum(int(probe["nonfinite_mask"]).bit_count() for probe in interior),
        "interior_max_pole_radius": interior_max_radius,
        "max_pole_radius": max_radius,
        "ceiling_occupancy_fraction": sum(float(probe["max_pole_radius"]) >= 0.998 for probe in probes) / len(probes),
        "median_zero_motion_octaves": _median(zero_motion),
        "median_pole_motion_octaves": _median(pole_motion),
        "median_pole_zero_disagreement_octaves": _median(disagreement),
        "highest_endpoint_peak_db": max(float(state["peak_db"]) for state in endpoints),
        "deepest_endpoint_floor_db": min(float(state["floor_db"]) for state in endpoints),
        "endpoint_span_db_mean": float(np.mean([state["span_db"] for state in endpoints])),
    }
    metrics["objective"] = (
        0.32 * metrics["endpoint_span_db_mean"]
        + 0.28 * metrics["center_span_db"]
        + 1.10 * metrics["morph_contrast_rms_db"]
        + 0.85 * metrics["secondary_contrast_rms_db"]
        + 3.5 * (metrics["center_response_peaks"] + metrics["center_response_valleys"])
        + 14.0 * metrics["ceiling_occupancy_fraction"]
        + 7.0 * metrics["median_zero_motion_octaves"]
    )
    return metrics


def gate_failures(metrics: dict[str, Any], gates: Any, reference: dict[str, Any]) -> list[str]:
    failures = []
    required_endpoint = max(float(gates.minimum_endpoint_span_db),
                            reference["median_endpoint_span_db"] * float(gates.reference_endpoint_span_ratio))
    required_morph = max(float(gates.minimum_morph_contrast_db),
                         reference["median_morph_contrast_db"] * float(gates.reference_morph_contrast_ratio))
    required_secondary = max(float(gates.minimum_secondary_contrast_db),
                             reference["median_secondary_contrast_db"] * float(gates.reference_secondary_contrast_ratio))
    checks = (
        (metrics["stable"] and metrics["finite"] and not metrics["grid_unstable_rows"]
         and not metrics["grid_nonfinite_rows"] and not metrics["interior_unstable_rows"]
         and not metrics["interior_nonfinite_rows"], "packed surface is unstable or non-finite"),
        (metrics["max_pole_radius"] <= float(gates.maximum_pole_radius), "pole ceiling exceeded"),
        (metrics["max_pole_radius"] >= float(gates.minimum_ceiling_radius), "never reaches hot pole corridor"),
        (metrics["center_span_db"] >= float(gates.minimum_center_span_db), "center terrain is too tame"),
        (metrics["endpoint_span_db_mean"] >= required_endpoint, "endpoint terrain is below ROM-calibrated floor"),
        (metrics["endpoint_span_db_mean"] <= float(gates.maximum_span_db), "endpoint terrain is pathological"),
        (metrics["morph_contrast_rms_db"] >= required_morph, "Morph contrast is too weak"),
        (metrics["secondary_contrast_rms_db"] >= required_secondary, "Secondary contrast is too weak"),
        (metrics["center_response_peaks"] >= int(gates.minimum_center_peaks), "not enough center mountains"),
        (metrics["center_response_valleys"] >= int(gates.minimum_center_valleys), "not enough center canyons"),
        (metrics["median_zero_motion_octaves"] >= float(gates.minimum_zero_motion_octaves), "zeros do not travel enough"),
    )
    for passed, reason in checks:
        if not passed:
            failures.append(reason)
    return failures


def archive_cell(metrics: dict[str, Any], archive_cfg: Any) -> tuple[int, ...]:
    return (
        int(np.digitize(metrics["endpoint_span_db_mean"], list(archive_cfg.span_bins))),
        int(np.digitize(metrics["morph_contrast_rms_db"], list(archive_cfg.motion_bins))),
        int(np.digitize(metrics["center_response_peaks"] + metrics["center_response_valleys"],
                        list(archive_cfg.complexity_bins))),
        int(np.digitize(metrics["median_zero_motion_octaves"], list(archive_cfg.zero_motion_bins))),
    )
