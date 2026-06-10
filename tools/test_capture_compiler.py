from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi
from pyruntime.capture_compiler import (
    LETTERS,
    PASS_KERNEL,
    actor_kernel,
    align_actor_lanes,
    classify_body_gestures,
    classify_zero_treatment,
    confidence_map,
    describe_stage,
    lane_support,
    pack_kernels,
    packed_surface_audit,
)
from pyruntime.forge_fit import cascade_response, fit_grid
from pyruntime.forge_joint import bounded_complex_residual
from tools.capture_to_cartridge import _manifest_kernel_seeds, capture_inputs


def confidence(repeated_h=None):
    perceptual = np.ones(8)
    dry = np.ones(8)
    wet = np.ones(8)
    cross = np.ones(8, dtype=np.complex128) * 0.95
    coherence = np.ones(8) * 0.95
    return confidence_map(perceptual, dry, wet, cross, coherence, repeated_h)


def test_confidence_downweights_low_coherence_and_weak_excitation():
    perceptual = np.ones(8)
    dry = np.ones(8)
    dry[2] = 1.0e-8
    wet = np.ones(8)
    cross = np.ones(8, dtype=np.complex128) * 0.95
    coherence = np.ones(8) * 0.95
    coherence[4] = 1.0e-6

    result = confidence_map(perceptual, dry, wet, cross, coherence)

    assert result["effective"][2] < result["effective"][0] * 0.01
    assert result["effective"][4] < result["effective"][0] * 0.01


def test_repeatability_variance_downweights_disagreeing_bin():
    repeated = np.ones((3, 8), dtype=np.complex128)
    repeated[:, 3] = [1.0 + 0j, -1.0 + 0j, 0.0 + 1.0j]

    result = confidence(repeated)

    term = result["components"]["repeatability_term"]
    assert result["summary"]["repeatability_available"]
    assert term[3] < term[0] * 0.5


def test_bounded_complex_residual_limits_outlier_influence():
    raw = np.array([0.01 + 0j, 100.0 + 0j])
    target = np.ones(2, dtype=np.complex128)

    robust = bounded_complex_residual(raw, target, delta=3.0)

    assert abs(robust[0] - raw[0]) < 1.0e-5
    assert abs(robust[1]) < abs(raw[1]) * 0.25


def test_zero_treatment_classifier_covers_three_primitives_and_neutral():
    sr = 48_000.0
    local = describe_stage(actor_kernel(1000.0, 0.95, 900.0, 0.88, sr), sr)
    local_strong = describe_stage(actor_kernel(1000.0, 0.95, 900.0, 0.92, sr), sr)
    above = describe_stage(actor_kernel(1000.0, 0.95, 2500.0, 0.88, sr), sr)
    below = describe_stage(actor_kernel(1000.0, 0.95, 350.0, 0.88, sr), sr)
    neutral = describe_stage(PASS_KERNEL, sr)

    assert local.treatment == "TYPE1_LOCAL_TEAR"
    assert local.zero_placement == "local"
    assert local_strong.topology == "local_tear"
    assert above.treatment == "TYPE2_ZERO_ABOVE"
    assert above.zero_placement == "remote_above"
    assert above.topology == "remote_counterweight"
    assert below.treatment == "TYPE3_ZERO_BELOW"
    assert below.zero_placement == "remote_below"
    assert below.topology == "remote_counterweight"
    assert classify_zero_treatment(neutral.pole, neutral.zero) == "NEUTRAL"
    assert neutral.topology == "neutral"


def test_lane_matching_uses_zero_aware_geometry_not_input_rank():
    sr = 48_000.0
    anchor = np.vstack([
        actor_kernel(300, 0.94, 750, 0.80, sr),
        actor_kernel(700, 0.95, 620, 0.88, sr),
        actor_kernel(1400, 0.96, 800, 0.84, sr),
        actor_kernel(2800, 0.93, 5000, 0.78, sr),
        actor_kernel(5200, 0.91, 4800, 0.82, sr),
        PASS_KERNEL,
    ])
    candidate = anchor[[1, 0, 2, 4, 3, 5]]

    aligned, report = align_actor_lanes({"A": anchor, "B": candidate, "C": anchor, "D": anchor}, sr)

    assert report["B"]["anchor_lane_to_source_lane_1_based"] == [2, 1, 3, 5, 4, 6]
    assert np.allclose(aligned["B"], anchor)


def test_latent_lane_detection_marks_passthrough():
    sr = 48_000.0
    freqs, z_inv = fit_grid(sr, 64)
    active = actor_kernel(1200.0, 0.96, 900.0, 0.88, sr)
    rows = np.vstack([active, active, active, active, active, PASS_KERNEL])

    reports = lane_support({letter: rows for letter in LETTERS}, z_inv, np.ones_like(freqs), sr)

    assert reports[5]["evidence"] == "LATENT"
    assert reports[0]["evidence"] != "LATENT"


def test_whole_body_gesture_classifier_reports_counterweighted_sweep():
    sr = 48_000.0
    corners = {
        "A": describe_stage(actor_kernel(500.0, 0.95, 470.0, 0.88, sr), sr),
        "B": describe_stage(actor_kernel(900.0, 0.95, 820.0, 0.88, sr), sr),
        "C": describe_stage(actor_kernel(500.0, 0.95, 1700.0, 0.82, sr), sr),
        "D": describe_stage(actor_kernel(900.0, 0.95, 2400.0, 0.82, sr), sr),
    }
    lane = {"evidence": "INFERRED", "corners": {key: asdict(value) for key, value in corners.items()}}
    lanes = [lane, lane, lane, lane]

    gestures = classify_body_gestures(lanes)

    assert "Counterweighted Tear" in gestures
    assert "Sweep Field" in gestures


def test_packed_17x17_stability_audit_uses_shipped_core():
    assert trench_ffi.available()
    sr = 48_000.0
    freqs, z_inv = fit_grid(sr, 64)
    rows = np.vstack([
        actor_kernel(300, 0.92, 700, 0.75, sr),
        actor_kernel(800, 0.94, 720, 0.86, sr),
        actor_kernel(1800, 0.95, 1050, 0.82, sr),
        actor_kernel(3300, 0.92, 5900, 0.80, sr),
        actor_kernel(5200, 0.91, 4900, 0.84, sr),
        PASS_KERNEL,
    ])
    kernels = {letter: rows for letter in LETTERS}
    words, body = pack_kernels(kernels)
    target = cascade_response(rows, z_inv)
    targets = {letter: target for letter in LETTERS}
    weights = {letter: np.ones_like(freqs) for letter in LETTERS}

    audit = packed_surface_audit(kernels, words, body, targets, weights, z_inv)

    assert len(body) == 240
    assert audit["stability_grid"]["points"] == 289
    assert audit["stability_grid"]["unstable_rows"] == 0
    assert audit["stability_grid"]["nonfinite_rows"] == 0


def test_manifest_parsing_accepts_repeated_corner_captures(tmp_path):
    manifest = {
        "format": "capture-to-cartridge-manifest-v1",
        "name": "Repeated Proof",
        "dry": "dry.wav",
        "corners": {
            "M0_Q0": {"wets": ["a.wav", "b.wav"]},
            "M100_Q0": "c.wav",
            "M0_Q100": ["d.wav"],
            "M100_Q100": {"wet": "e.wav"},
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    args = argparse.Namespace(
        manifest=path, name=None, dry=None,
        wet_m0_q0=None, wet_m100_q0=None, wet_m0_q100=None, wet_m100_q100=None,
        wet_m0_q0_repeat=[], wet_m100_q0_repeat=[], wet_m0_q100_repeat=[], wet_m100_q100_repeat=[],
    )

    name, dry, corners, _ = capture_inputs(args)

    assert name == "Repeated Proof"
    assert dry == tmp_path / "dry.wav"
    assert corners["M0_Q0"] == [tmp_path / "a.wav", tmp_path / "b.wav"]


def test_direct_cli_capture_inputs_preserve_original_four_wet_interface(tmp_path):
    args = argparse.Namespace(
        manifest=None, name="Direct Capture", dry=tmp_path / "dry.wav",
        wet_m0_q0=tmp_path / "a.wav", wet_m100_q0=tmp_path / "b.wav",
        wet_m0_q100=tmp_path / "c.wav", wet_m100_q100=tmp_path / "d.wav",
        wet_m0_q0_repeat=[], wet_m100_q0_repeat=[], wet_m0_q100_repeat=[], wet_m100_q100_repeat=[],
    )

    name, dry, corners, manifest = capture_inputs(args)

    assert name == "Direct Capture"
    assert dry == tmp_path / "dry.wav"
    assert corners["M100_Q100"] == [tmp_path / "d.wav"]
    assert manifest == {}


def test_manifest_actor_kernel_priors_are_explicit_six_row_inputs():
    manifest = {"actor_kernel_seeds": {letter: np.tile(PASS_KERNEL, (6, 1)).tolist() for letter in LETTERS}}

    seeds = _manifest_kernel_seeds(manifest)

    assert seeds is not None
    assert set(seeds) == set(LETTERS)
    assert seeds["A"].shape == (6, 5)
