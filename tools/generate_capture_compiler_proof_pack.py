#!/usr/bin/env python3
"""Generate and evaluate a deterministic repeated-capture compiler proof pack.

The synthetic source body contains five active persistent pole-zero actors and
one latent passthrough lane. It deliberately includes local-tear, zero-above,
and zero-below treatments. The generated manifest is feedstock for
``tools/capture_to_cartridge.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import sosfilt

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime.capture_compiler import PASS_KERNEL, actor_kernel  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words, kernel_to_biquad, words_to_coeffs  # noqa: E402

SR = 48_000
SECONDS = 6.0
CORNERS = (
    ("M0_Q0", 0.0, 0.0),
    ("M100_Q0", 1.0, 0.0),
    ("M0_Q100", 0.0, 1.0),
    ("M100_Q100", 1.0, 1.0),
)
LANES = (
    ("FOUNDATION", "TYPE2_ZERO_ABOVE", (190.0, 245.0), (720.0, 860.0), (0.91, 0.94), (0.76, 0.80)),
    ("LOCAL_TEAR", "TYPE1_LOCAL_TEAR", (620.0, 860.0), (565.0, 785.0), (0.95, 0.97), (0.89, 0.92)),
    ("HOLLOW", "TYPE3_ZERO_BELOW", (1650.0, 2520.0), (980.0, 1320.0), (0.94, 0.965), (0.82, 0.88)),
    ("AIR_CAP", "TYPE2_ZERO_ABOVE", (3150.0, 3880.0), (5750.0, 7240.0), (0.91, 0.94), (0.80, 0.84)),
    ("TOOTH", "TYPE1_LOCAL_TEAR", (5100.0, 5980.0), (4680.0, 5480.0), (0.925, 0.95), (0.86, 0.89)),
    ("LATENT", "NEUTRAL", (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
)


def lerp(pair: tuple[float, float], t: float) -> float:
    return pair[0] + (pair[1] - pair[0]) * t


def rows_at(morph: float, q: float) -> np.ndarray:
    rows = []
    for _name, treatment, pole, zero, pole_radius, zero_radius in LANES:
        if treatment == "NEUTRAL":
            rows.append(PASS_KERNEL.copy())
            continue
        rows.append(actor_kernel(
            lerp(pole, morph),
            min(0.985, lerp(pole_radius, q)),
            lerp(zero, morph),
            min(0.96, lerp(zero_radius, q)),
            SR,
        ))
    # Use the representable packed corner as source truth.
    return np.asarray([
        words_to_coeffs(coeffs_to_words(*(float(value) for value in row)))
        for row in rows
    ], dtype=np.float64)


def kernel_to_sos(rows: np.ndarray) -> np.ndarray:
    return np.asarray([
        [b0, b1, b2, 1.0, a1, a2]
        for b0, b1, b2, a1, a2 in (kernel_to_biquad(tuple(row)) for row in rows)
    ], dtype=np.float64)


def dry_excitation() -> np.ndarray:
    rng = np.random.default_rng(0x43415054555245)
    x = rng.standard_normal(int(round(SR * SECONDS)))
    edge = int(round(SR * 0.025))
    ramp = np.linspace(0.0, 1.0, edge)
    x[:edge] *= ramp
    x[-edge:] *= ramp[::-1]
    return (x * (0.18 / max(float(np.max(np.abs(x))), 1.0e-30))).astype(np.float32)


def write_wav(path: Path, data: np.ndarray) -> None:
    wavfile.write(str(path), SR, np.asarray(data, dtype=np.float32))


def generate(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    dry = dry_excitation()
    write_wav(out / "dry_broadband.wav", dry)
    manifest_corners = {}
    truth_corners = {}
    seeds = {}
    kernel_seeds = {}
    for label, morph, q in CORNERS:
        rows = rows_at(morph, q)
        clean = sosfilt(kernel_to_sos(rows), dry.astype(np.float64))
        wet_names = []
        for repeat in range(3):
            rng = np.random.default_rng(0x50524F4F + repeat + int(morph * 10) + int(q * 100))
            noisy = clean + rng.standard_normal(len(clean)) * (3.0e-6 * (repeat + 1))
            wet_name = f"wet_{label.lower()}_repeat{repeat + 1}.wav"
            write_wav(out / wet_name, noisy)
            wet_names.append(wet_name)
        manifest_corners[label] = {"wets": wet_names}
        seeds[label] = [
            float(lerp(lane[2], morph)) if lane[1] != "NEUTRAL" else 12_000.0
            for lane in LANES
        ]
        kernel_seeds[label] = rows.tolist()
        truth_corners[label] = {"morph": morph, "q": q, "kernel": rows.tolist()}
    manifest = {
        "format": "capture-to-cartridge-manifest-v1",
        "name": "Synthetic Capture Compiler Proof",
        "dry": "dry_broadband.wav",
        "corners": manifest_corners,
        "lane_seeds_hz": seeds,
        "actor_kernel_seeds": kernel_seeds,
        "actor_prior_source": "deterministic synthetic ground truth; explicit prior for recovery proof",
    }
    manifest_path = out / "capture_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    truth = {
        "format": "capture-compiler-proof-truth-v1",
        "sample_rate_hz": SR,
        "lane_order": [lane[0] for lane in LANES],
        "expected_treatments": [lane[1] for lane in LANES],
        "expected_latent_lane": 5,
        "corners": truth_corners,
        "compile_command": (
            "python tools/capture_to_cartridge.py "
            f"--manifest {manifest_path} --out {out / 'synthetic_capture_compiler_proof.cart.json'} "
            "--restarts 1 --max-nfev 250 --grid 256 --verbose"
        ),
    }
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    print(f"wrote proof pack: {out}")
    print(truth["compile_command"])
    return manifest_path


def evaluate(report_path: Path) -> Path:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    truth_path = report_path.parent / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    expected = truth["expected_treatments"]
    actual = [lane["corners"]["A"]["treatment"] for lane in report["lanes"]]
    matches = [want == got for want, got in zip(expected, actual)]
    audit = report["packed_surface_audit"]
    evaluation = {
        "format": "capture-compiler-proof-evaluation-v1",
        "report": str(report_path),
        "classification_accuracy": sum(matches) / len(matches),
        "expected_treatments": expected,
        "actual_treatments": actual,
        "classification_matches": matches,
        "authoring_sample_rate_hz": report["authoring_sample_rate_hz"],
        "lane_mappings": report["lane_mappings"],
        "lane_support_summary": report["lane_support_summary"],
        "expected_latent_lane": truth["expected_latent_lane"],
        "actual_latent_lanes": [
            lane["lane_index"] for lane in report["lanes"] if lane["evidence_label"] == "LATENT"
        ],
        "corner_weighted_complex_residual_db": audit["corner_weighted_complex_residual_db"],
        "postpack_corner_degradation_db": audit["postpack_corner_degradation_db"],
        "captured_wet_time_domain_nulls": report["captured_wet_time_domain_nulls"],
        "inferred_whole_body_gestures": report["vocabulary"]["inferred_whole_body_gestures"],
        "stability_grid": audit["stability_grid"],
        "packed_body_sha256": audit["packed_body_sha256"],
        "warnings": report["warnings"],
        "limitations": report["limitations"],
    }
    out = report_path.parent / "proof_evaluation.json"
    out.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evaluation, indent=2))
    print(f"wrote evaluation: {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "capture_compiler_proof_pack")
    ap.add_argument("--evaluate", type=Path, help="evaluate a compiler report generated from this pack")
    args = ap.parse_args()
    if args.evaluate:
        evaluate(args.evaluate)
    else:
        generate(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
