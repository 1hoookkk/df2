"""Packed-runtime terrain measurements used by production calibration and scoring."""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import find_peaks

from pyruntime import trench_ffi

SR = 39_062.5
TAU = 2.0 * math.pi
FREQS = np.logspace(math.log10(40.0), math.log10(16_000.0), 512)
GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
ENDPOINTS = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
PASS = (1.0, 0.0, 0.0, 0.0, 0.0)


def response_db(rows: list[tuple[float, ...]]) -> np.ndarray:
    z1 = np.exp(-1j * (TAU * FREQS / SR))
    z2 = z1 * z1
    response = np.ones_like(z1, dtype=np.complex128)
    for b0, b1, b2, a1, a2 in rows:
        response *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(response), 1e-30))


def _root_pair(c0: float, c1: float, c2: float) -> tuple[str, float | None, float | None]:
    if abs(c0) < 1e-15:
        return "none", None, None
    roots = np.roots((c0, c1, c2))
    if not len(roots):
        return "none", None, None
    root = max(roots, key=lambda value: abs(value.imag))
    return ("complex_pair" if abs(root.imag) > 1e-7 else "real_pair",
            abs(float(np.angle(root))) * SR / TAU, float(abs(root)))


def _stage_metrics(row: tuple[float, ...]) -> dict:
    b0, b1, b2, a1, a2 = row
    if max(abs(row[index] - PASS[index]) for index in range(5)) < 1e-8:
        return {"active": False}
    pole_kind, pole_hz, pole_radius = _root_pair(1.0, a1, a2)
    zero_kind, zero_hz, zero_radius = ("none", None, None) if abs(b1) < 1e-10 and abs(b2) < 1e-10 else _root_pair(b0, b1, b2)
    offset = math.log2(zero_hz / pole_hz) if pole_hz and zero_hz and pole_hz > 1e-6 and zero_hz > 1e-6 else None
    return {"active": True, "pole_kind": pole_kind, "pole_hz": pole_hz, "pole_radius": pole_radius,
            "zero_kind": zero_kind, "zero_hz": zero_hz, "zero_radius": zero_radius,
            "zero_offset_octaves": offset, "paired_close": offset is not None and abs(offset) <= 1.0}


def state_metrics(body: bytes, morph: float, secondary: float) -> dict:
    probe = trench_ffi.packed_probe(body, morph, secondary)
    stages = [_stage_metrics(row) for row in probe["biquad"]]
    active = [stage for stage in stages if stage["active"]]
    db = response_db(probe["biquad"])
    peaks, _ = find_peaks(db, prominence=3.0)
    valleys, _ = find_peaks(-db, prominence=3.0)
    pole_hz = sorted(stage["pole_hz"] for stage in active if stage.get("pole_hz") is not None)
    zeros = [stage for stage in active if stage.get("zero_kind") != "none"]
    return {"morph": morph, "secondary": secondary, "max_pole_radius": probe["max_pole_radius"],
            "unstable_mask": probe["unstable_mask"], "nonfinite_mask": probe["nonfinite_mask"],
            "active_stages": len(active), "zero_bearing_stages": len(zeros),
            "close_paired_zero_stages": sum(bool(stage.get("paired_close")) for stage in zeros),
            "pole_collisions_lt_200hz": sum(pole_hz[index + 1] - pole_hz[index] < 200.0 for index in range(len(pole_hz) - 1)),
            "peak_db": float(np.max(db)), "floor_db": float(np.min(db)),
            "span_db": float(np.max(db) - np.min(db)), "response_peaks": int(len(peaks)),
            "response_valleys": int(len(valleys)), "db": db, "stages": stages}


def _rms_delta(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def _zero_motion_error(a: dict, b: dict) -> list[float]:
    errors = []
    for before, after in zip(a["stages"], b["stages"]):
        if before.get("active") and after.get("active") and before.get("pole_hz") and after.get("pole_hz") and before.get("zero_hz") and after.get("zero_hz"):
            pole_move = math.log2(after["pole_hz"] / before["pole_hz"])
            zero_move = math.log2(after["zero_hz"] / before["zero_hz"])
            errors.append(abs(zero_move - pole_move))
    return errors


def analyze_body(body: bytes) -> dict:
    states = {(morph, secondary): state_metrics(body, morph, secondary) for secondary in GRID for morph in GRID}
    endpoints = [states[point] for point in ENDPOINTS]
    center = states[(0.5, 0.5)]
    zero_motion = []
    for start, end in (((0.0, 0.0), (1.0, 0.0)), ((0.0, 1.0), (1.0, 1.0)),
                       ((0.0, 0.0), (0.0, 1.0)), ((1.0, 0.0), (1.0, 1.0))):
        zero_motion += _zero_motion_error(states[start], states[end])
    endpoint_active = sum(state["active_stages"] for state in endpoints)
    return {"stable": all(state["unstable_mask"] == 0 for state in states.values()),
            "finite": all(state["nonfinite_mask"] == 0 for state in states.values()),
            "max_pole_radius": max(state["max_pole_radius"] for state in states.values()),
            "endpoint_active_stages": endpoint_active,
            "endpoint_zero_fraction": sum(state["zero_bearing_stages"] for state in endpoints) / max(1, endpoint_active),
            "endpoint_close_paired_zero_fraction": sum(state["close_paired_zero_stages"] for state in endpoints) / max(1, endpoint_active),
            "zero_motion_error_octaves_mean": float(np.mean(zero_motion)) if zero_motion else None,
            "endpoint_collisions_lt_200hz": sum(state["pole_collisions_lt_200hz"] for state in endpoints),
            "center_collisions_lt_200hz": center["pole_collisions_lt_200hz"],
            "morph_contrast_rms_db": 0.5 * (_rms_delta(states[(0.0, 0.0)]["db"], states[(1.0, 0.0)]["db"]) + _rms_delta(states[(0.0, 1.0)]["db"], states[(1.0, 1.0)]["db"])),
            "secondary_contrast_rms_db": 0.5 * (_rms_delta(states[(0.0, 0.0)]["db"], states[(0.0, 1.0)]["db"]) + _rms_delta(states[(1.0, 0.0)]["db"], states[(1.0, 1.0)]["db"])),
            "center_sag_db": center["peak_db"] - float(np.mean([state["peak_db"] for state in endpoints])),
            "center_span_db": center["span_db"], "center_response_peaks": center["response_peaks"],
            "center_response_valleys": center["response_valleys"],
            "endpoint_span_db_mean": float(np.mean([state["span_db"] for state in endpoints])),
            "endpoint_response_peaks_mean": float(np.mean([state["response_peaks"] for state in endpoints])),
            "endpoint_response_valleys_mean": float(np.mean([state["response_valleys"] for state in endpoints]))}
