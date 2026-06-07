"""Measurement confidence, actor continuity, and packed-surface audit helpers.

This module serves the controlled dry/wet capture compiler. It keeps the
provenance boundary explicit: captures provide measured complex transfer
function evidence; six serialized lanes are persistent locally reconstructed
actors; authored additions are opt-in.
"""
from __future__ import annotations

import hashlib
import itertools
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from pyruntime import trench_ffi
from pyruntime.forge_fit import cascade_response
from pyruntime.packed_interp import (
    coeffs_to_words,
    kernel_to_biquad,
    packed_bilinear,
)

LETTERS = ("A", "B", "C", "D")
PASS_KERNEL = np.array([2.0, 1.0, 2.0, 1.0, 1.0], dtype=np.float64)
ZERO_TREATMENTS = (
    "TYPE1_LOCAL_TEAR",
    "TYPE2_ZERO_ABOVE",
    "TYPE3_ZERO_BELOW",
    "NEUTRAL",
)
WHOLE_BODY_GESTURES = (
    "Contrary Vocal",
    "Shutter Cliff",
    "Opposed Hollow",
    "Counterweighted Tear",
    "Sweep Field",
)


def summary(values: np.ndarray) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {"min": 0.0, "p05": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0, "mean": 0.0}
    return {
        "min": float(np.min(finite)),
        "p05": float(np.percentile(finite, 5.0)),
        "median": float(np.median(finite)),
        "p95": float(np.percentile(finite, 95.0)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
    }


def confidence_map(
    perceptual: np.ndarray,
    dry_psd: np.ndarray,
    wet_psd: np.ndarray,
    cross_psd: np.ndarray,
    coherence: np.ndarray,
    repeated_h: np.ndarray | None = None,
) -> dict[str, Any]:
    """Build a bounded confidence map for one corner.

    Effective weight:
        clip_p95(
            perceptual_importance
          * sqrt(coherence)
          * sqrt(clamp(dry_psd / dry_p95))
          * sqrt(snr_proxy / (1 + snr_proxy))
          * 1 / sqrt(1 + repeat_variance_ratio)
        )

    Each term is bounded before multiplication. The final p95 normalization and
    [0, 1] clip prevent isolated numerically perfect bins from dominating.
    """
    perceptual = np.asarray(perceptual, dtype=np.float64)
    dry_psd = np.maximum(np.asarray(dry_psd, dtype=np.float64), 0.0)
    wet_psd = np.maximum(np.asarray(wet_psd, dtype=np.float64), 0.0)
    cross_psd = np.asarray(cross_psd, dtype=np.complex128)
    coherence = np.clip(np.asarray(coherence, dtype=np.float64), 0.0, 1.0)

    dry_ref = max(float(np.percentile(dry_psd, 95.0)), 1.0e-30)
    excitation = np.sqrt(np.clip(dry_psd / dry_ref, 0.0, 1.0))
    coherence_term = np.sqrt(coherence)

    coherent_wet = np.abs(cross_psd) ** 2 / np.maximum(dry_psd, 1.0e-30)
    incoherent_wet = np.maximum(wet_psd - coherent_wet, wet_psd * 1.0e-6)
    snr_ratio = np.clip(coherent_wet / np.maximum(incoherent_wet, 1.0e-30), 0.0, 1.0e6)
    snr_term = np.sqrt(snr_ratio / (1.0 + snr_ratio))

    repeatability = np.ones_like(perceptual)
    repeatability_available = repeated_h is not None and len(repeated_h) > 1
    repeat_variance_ratio = np.zeros_like(perceptual)
    if repeatability_available:
        h = np.asarray(repeated_h, dtype=np.complex128)
        center = np.mean(h, axis=0)
        variance = np.mean(np.abs(h - center) ** 2, axis=0)
        floor = max(float(np.median(np.abs(center) ** 2)) * 1.0e-6, 1.0e-20)
        repeat_variance_ratio = np.clip(variance / (np.abs(center) ** 2 + floor), 0.0, 1.0e6)
        repeatability = 1.0 / np.sqrt(1.0 + repeat_variance_ratio)

    raw = (
        np.maximum(perceptual, 0.0)
        * coherence_term
        * excitation
        * snr_term
        * repeatability
    )
    normalizer = max(float(np.percentile(raw, 95.0)), 1.0e-30)
    effective = np.clip(raw / normalizer, 0.0, 1.0)
    return {
        "effective": effective,
        "components": {
            "perceptual_importance": perceptual,
            "coherence_term": coherence_term,
            "excitation_term": excitation,
            "snr_term": snr_term,
            "repeatability_term": repeatability,
        },
        "summary": {
            "formula": (
                "clip_0_1(p95_normalize(perceptual_importance * sqrt(coherence) * "
                "sqrt(clamp(dry_psd / dry_psd_p95, 0, 1)) * "
                "sqrt(snr_proxy / (1 + snr_proxy)) * "
                "1 / sqrt(1 + repeat_variance_ratio)))"
            ),
            "effective": summary(effective),
            "coherence": summary(coherence),
            "excitation": summary(excitation),
            "snr_proxy_linear": summary(snr_ratio),
            "snr_term": summary(snr_term),
            "repeatability_available": bool(repeatability_available),
            "repeatability_term": summary(repeatability),
            "repeat_variance_ratio": summary(repeat_variance_ratio),
        },
    }


@dataclass(frozen=True)
class RootPair:
    freq_hz: float
    radius: float
    kind: str


@dataclass(frozen=True)
class ActorGeometry:
    pole: RootPair
    zero: RootPair | None
    gain: float
    treatment: str


def _root_pair(coeffs: tuple[float, float, float], sr: float) -> RootPair | None:
    if abs(coeffs[0]) < 1.0e-15:
        return None
    roots = np.roots(coeffs)
    if roots.size == 0:
        return None
    root = max(roots, key=lambda value: (abs(float(np.imag(value))), abs(value)))
    return RootPair(
        freq_hz=abs(float(np.angle(root))) * sr / (2.0 * math.pi),
        radius=float(abs(root)),
        kind="complex_pair" if abs(float(np.imag(root))) > 1.0e-7 else "real_pair",
    )


def classify_zero_treatment(pole: RootPair, zero: RootPair | None) -> str:
    if zero is None or pole.radius < 1.0e-6 or zero.radius < 1.0e-6:
        return "NEUTRAL"
    ratio = zero.freq_hz / max(pole.freq_hz, 20.0)
    if 2.0 ** -0.35 <= ratio <= 2.0 ** 0.35:
        return "TYPE1_LOCAL_TEAR"
    if ratio > 1.0:
        return "TYPE2_ZERO_ABOVE"
    return "TYPE3_ZERO_BELOW"


def describe_stage(row: np.ndarray, sr: float) -> ActorGeometry:
    b0, b1, b2, a1, a2 = kernel_to_biquad(tuple(float(v) for v in row))
    pole = _root_pair((1.0, a1, a2), sr) or RootPair(0.0, 0.0, "none")
    zero = _root_pair((b0, b1, b2), sr)
    return ActorGeometry(pole, zero, float(b0), classify_zero_treatment(pole, zero))


def actor_kernel(
    pole_hz: float,
    pole_radius: float,
    zero_hz: float,
    zero_radius: float,
    sr: float,
) -> np.ndarray:
    """Build one DC-normalized pole-zero actor in packable kernel form."""
    wp = 2.0 * math.pi * pole_hz / sr
    wz = 2.0 * math.pi * zero_hz / sr
    a1, a2 = -2.0 * pole_radius * math.cos(wp), pole_radius * pole_radius
    z1, z2 = -2.0 * zero_radius * math.cos(wz), zero_radius * zero_radius
    gain = (1.0 + a1 + a2) / max(1.0 + z1 + z2, 1.0e-9)
    return np.array([2.0 + z1, 1.0 - z2, 2.0 + a1, 1.0 - a2, gain], dtype=np.float64)


def _octave_distance(a: float, b: float) -> float:
    return abs(math.log2(max(float(a), 20.0) / max(float(b), 20.0)))


def actor_distance(a: ActorGeometry, b: ActorGeometry) -> float:
    cost = _octave_distance(a.pole.freq_hz, b.pole.freq_hz)
    cost += 0.25 * abs(a.pole.radius - b.pole.radius)
    if a.zero is not None and b.zero is not None:
        cost += 0.45 * _octave_distance(a.zero.freq_hz, b.zero.freq_hz)
        cost += 0.10 * abs(a.zero.radius - b.zero.radius)
    elif (a.zero is None) != (b.zero is None):
        cost += 0.75
    return float(cost)


def infer_lane_mapping(anchor: np.ndarray, candidate: np.ndarray, sr: float) -> tuple[list[int], float]:
    """Return candidate row indices ordered by anchor row using pole-zero geometry."""
    a = [describe_stage(row, sr) for row in np.asarray(anchor)]
    b = [describe_stage(row, sr) for row in np.asarray(candidate)]
    if len(a) != 6 or len(b) != 6:
        raise ValueError("lane matching requires exactly six serialized rows")
    best_mapping = list(range(6))
    best_cost = math.inf
    for mapping in itertools.permutations(range(6)):
        cost = sum(actor_distance(a[index], b[mapping[index]]) for index in range(6))
        if cost < best_cost:
            best_mapping = list(mapping)
            best_cost = cost
    return best_mapping, float(best_cost)


def align_actor_lanes(
    kernels: dict[str, np.ndarray],
    sr: float,
    overrides: dict[str, list[int]] | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, Any]]]:
    """Reorder B/C/D around A without changing any corner response."""
    anchor = np.asarray(kernels["A"], dtype=np.float64)
    aligned = {"A": anchor.copy()}
    report = {
        "A": {
            "source": "anchor",
            "anchor_lane_to_source_lane_1_based": list(range(1, 7)),
            "minimum_cost": 0.0,
        }
    }
    for letter in LETTERS[1:]:
        inferred, cost = infer_lane_mapping(anchor, kernels[letter], sr)
        mapping = list(overrides[letter]) if overrides and letter in overrides else inferred
        if sorted(mapping) != list(range(6)):
            raise ValueError(f"{letter} mapping must be a zero-based permutation of 0..5")
        aligned[letter] = np.asarray(kernels[letter], dtype=np.float64)[mapping].copy()
        report[letter] = {
            "source": "explicit-user" if overrides and letter in overrides else "inferred-minimum-cost",
            "anchor_lane_to_source_lane_1_based": [index + 1 for index in mapping],
            "minimum_cost": cost,
        }
    return aligned, report


def _stage_response(row: np.ndarray, z_inv: np.ndarray) -> np.ndarray:
    b0, b1, b2, a1, a2 = kernel_to_biquad(tuple(float(v) for v in row))
    z2 = z_inv * z_inv
    return (b0 + b1 * z_inv + b2 * z2) / (1.0 + a1 * z_inv + a2 * z2)


def lane_support(
    kernels: dict[str, np.ndarray],
    z_inv: np.ndarray,
    measurement_weight: np.ndarray,
    sr: float,
    latent_threshold: float = 0.012,
    weak_threshold: float = 0.060,
) -> list[dict[str, Any]]:
    """Classify each persistent lane as measured-strong, measured-weak, or latent."""
    weight = np.asarray(measurement_weight, dtype=np.float64)
    weight_norm = weight / max(float(np.mean(weight)), 1.0e-30)
    measurement_confidence = float(np.mean(np.clip(weight, 0.0, 1.0)))
    out = []
    for lane in range(6):
        effects = []
        corners = {}
        for letter in LETTERS:
            row = np.asarray(kernels[letter][lane], dtype=np.float64)
            h = _stage_response(row, z_inv)
            effect = float(np.sqrt(np.mean(weight_norm * np.abs(h - 1.0) ** 2)))
            effects.append(effect)
            corners[letter] = asdict(describe_stage(row, sr))
        effect = float(np.mean(effects))
        confidence = float(np.clip((effect / max(weak_threshold, 1.0e-9)) * measurement_confidence, 0.0, 1.0))
        if effect < latent_threshold:
            evidence = "LATENT"
        elif effect < weak_threshold or confidence < 0.35:
            evidence = "MEASURED_WEAK"
        else:
            evidence = "MEASURED_STRONG"
        out.append({
            "lane_index": lane,
            "effect_rms": effect,
            "confidence": confidence,
            "evidence": evidence,
            "corners": corners,
        })
    return out


def neutralize_latent_lanes(
    kernels: dict[str, np.ndarray],
    lane_reports: list[dict[str, Any]],
) -> dict[str, np.ndarray]:
    out = {letter: np.asarray(rows, dtype=np.float64).copy() for letter, rows in kernels.items()}
    for report in lane_reports:
        if report["evidence"] == "LATENT":
            lane = int(report["lane_index"])
            for letter in LETTERS:
                out[letter][lane] = PASS_KERNEL
    return out


def classify_body_gestures(lanes: list[dict[str, Any]]) -> list[str]:
    """Suggest semantic whole-body gestures from persistent actor geometry."""
    treatments = [
        corner["treatment"]
        for lane in lanes
        for corner in lane["corners"].values()
        if lane["evidence"] != "LATENT"
    ]
    gestures = []
    if treatments.count("TYPE1_LOCAL_TEAR") >= 4:
        gestures.append("Contrary Vocal")
    if treatments.count("TYPE2_ZERO_ABOVE") >= 4:
        gestures.append("Shutter Cliff")
    if treatments.count("TYPE3_ZERO_BELOW") >= 4:
        gestures.append("Opposed Hollow")
    if "TYPE1_LOCAL_TEAR" in treatments and (
        "TYPE2_ZERO_ABOVE" in treatments or "TYPE3_ZERO_BELOW" in treatments
    ):
        gestures.append("Counterweighted Tear")
    for lane in lanes:
        freqs = [float(corner["pole"]["freq_hz"]) for corner in lane["corners"].values()]
        if min(freqs) > 20.0 and max(freqs) / min(freqs) >= 2.0 ** 0.5:
            gestures.append("Sweep Field")
            break
    return [gesture for gesture in WHOLE_BODY_GESTURES if gesture in gestures]


def pack_kernels(kernels: dict[str, np.ndarray]) -> tuple[dict[str, list[tuple[int, ...]]], bytes]:
    words = {
        letter: [coeffs_to_words(*(float(value) for value in row)) for row in kernels[letter]]
        for letter in LETTERS
    }
    body = trench_ffi.body_bytes_from_corner_words(words)
    return words, body


def weighted_complex_null_db(
    candidate: np.ndarray,
    target: np.ndarray,
    weight: np.ndarray,
) -> float:
    weight = np.asarray(weight, dtype=np.float64)
    target = np.asarray(target, dtype=np.complex128)
    residual = weight * (np.asarray(candidate, dtype=np.complex128) - target)
    reference = weight * target
    num = float(np.sqrt(np.mean(np.abs(residual) ** 2)))
    den = float(np.sqrt(np.mean(np.abs(reference) ** 2))) + 1.0e-30
    return float(20.0 * np.log10(num / den + 1.0e-30))


def _float_bilinear(kernels: dict[str, np.ndarray], morph: float, q: float) -> np.ndarray:
    top = kernels["A"] + (kernels["B"] - kernels["A"]) * morph
    bottom = kernels["C"] + (kernels["D"] - kernels["C"]) * morph
    return top + (bottom - top) * q


def _probe_point(body: bytes, morph: float, q: float) -> dict[str, Any]:
    probe = trench_ffi.packed_probe(body, morph, q)
    return {
        "morph": float(morph),
        "q": float(q),
        "max_pole_radius": float(probe["max_pole_radius"]),
        "unstable_mask": int(probe["unstable_mask"]),
        "nonfinite_mask": int(probe["nonfinite_mask"]),
    }


def packed_surface_audit(
    kernels: dict[str, np.ndarray],
    words: dict[str, list[tuple[int, ...]]],
    body: bytes,
    targets: dict[str, np.ndarray],
    weights: dict[str, np.ndarray],
    z_inv: np.ndarray,
) -> dict[str, Any]:
    """Audit the real packed u16 reachable surface through trench-core."""
    if not trench_ffi.available():
        raise RuntimeError("packed surface audit requires a built trench-core shared library")

    special = {
        "M0_Q0": (0.0, 0.0),
        "M100_Q0": (1.0, 0.0),
        "M0_Q100": (0.0, 1.0),
        "M100_Q100": (1.0, 1.0),
        "M50_Q0": (0.5, 0.0),
        "M50_Q100": (0.5, 1.0),
        "M0_Q50": (0.0, 0.5),
        "M100_Q50": (1.0, 0.5),
        "M50_Q50": (0.5, 0.5),
    }
    special_rows = {name: _probe_point(body, *point) for name, point in special.items()}

    grid = [_probe_point(body, morph / 16.0, q / 16.0) for q in range(17) for morph in range(17)]
    max_radius = max(row["max_pole_radius"] for row in grid)
    unstable_points = sum(bool(row["unstable_mask"]) for row in grid)
    unstable_rows = sum(int(row["unstable_mask"]).bit_count() for row in grid)
    nonfinite_points = sum(bool(row["nonfinite_mask"]) for row in grid)
    nonfinite_rows = sum(int(row["nonfinite_mask"]).bit_count() for row in grid)

    packed_corner_nulls = {}
    unpacked_corner_nulls = {}
    postpack_degradation = {}
    for letter, point in zip(LETTERS, ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))):
        unpacked_h = cascade_response(kernels[letter], z_inv)
        packed_h = cascade_response(np.asarray(packed_bilinear(words, *point)), z_inv)
        unpacked_corner_nulls[letter] = weighted_complex_null_db(unpacked_h, targets[letter], weights[letter])
        packed_corner_nulls[letter] = weighted_complex_null_db(packed_h, targets[letter], weights[letter])
        postpack_degradation[letter] = packed_corner_nulls[letter] - unpacked_corner_nulls[letter]

    midpoint_rows = {}
    for name, point in special.items():
        packed_h = cascade_response(np.asarray(packed_bilinear(words, *point)), z_inv)
        float_h = cascade_response(_float_bilinear(kernels, *point), z_inv)
        midpoint_rows[name] = {
            "packed_vs_decoded_float_db": weighted_complex_null_db(
                packed_h, float_h, np.ones_like(z_inv, dtype=np.float64)
            ),
        }

    sweeps = {
        "morph_q0": [(float(value), 0.0) for value in np.linspace(0.0, 1.0, 33)],
        "morph_q1": [(float(value), 1.0) for value in np.linspace(0.0, 1.0, 33)],
        "secondary_m0": [(0.0, float(value)) for value in np.linspace(0.0, 1.0, 33)],
        "secondary_m1": [(1.0, float(value)) for value in np.linspace(0.0, 1.0, 33)],
        "diagonal": [(float(value), float(value)) for value in np.linspace(0.0, 1.0, 33)],
    }
    sweep_report = {}
    warnings = []
    for name, points in sweeps.items():
        responses = [
            cascade_response(np.asarray(packed_bilinear(words, morph, q)), z_inv)
            for morph, q in points
        ]
        jumps = [
            weighted_complex_null_db(
                responses[index + 1], responses[index], np.ones_like(z_inv, dtype=np.float64)
            )
            for index in range(len(responses) - 1)
        ]
        worst = max(jumps) if jumps else -600.0
        sweep_report[name] = {
            "points": len(points),
            "worst_adjacent_response_delta_db": float(worst),
            "median_adjacent_response_delta_db": float(np.median(jumps)) if jumps else -600.0,
        }
        if worst > -8.0:
            warnings.append(f"{name}: adjacent packed response delta reaches {worst:+.2f} dB")

    if unstable_rows:
        warnings.append(f"17x17 grid contains {unstable_rows} unstable serialized rows")
    if nonfinite_rows:
        warnings.append(f"17x17 grid contains {nonfinite_rows} non-finite serialized rows")
    return {
        "packed_backend": "trench-core",
        "packed_body_sha256": hashlib.sha256(body).hexdigest(),
        "body_bytes": len(body),
        "special_points": special_rows,
        "stability_grid": {
            "shape": "17x17",
            "points": len(grid),
            "maximum_pole_radius": float(max_radius),
            "unstable_points": int(unstable_points),
            "unstable_rows": int(unstable_rows),
            "nonfinite_points": int(nonfinite_points),
            "nonfinite_rows": int(nonfinite_rows),
        },
        "corner_weighted_complex_residual_db": packed_corner_nulls,
        "prepack_corner_weighted_complex_residual_db": unpacked_corner_nulls,
        "postpack_corner_degradation_db": postpack_degradation,
        "midpoint_degradation": midpoint_rows,
        "sweeps": sweep_report,
        "warnings": warnings,
    }
