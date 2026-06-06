#!/usr/bin/env python3
"""Compile controlled dry/wet captures into one audited 240-byte TRENCH body.

The direct workflow remains:

    python tools/capture_to_cartridge.py `
        --name "My Captured Body" `
        --dry captures/dry_pink.wav `
        --wet-m0-q0 captures/wet_m0_q0.wav `
        --wet-m100-q0 captures/wet_m100_q0.wav `
        --wet-m0-q100 captures/wet_m0_q100.wav `
        --wet-m100-q100 captures/wet_m100_q100.wav `
        --out bodies/my_captured_body.cart.json

For repeated captures, use --manifest. A manifest may also provide explicit
``actor_kernel_seeds`` from an authored or quarry workflow such as
``dev/tmp/arma_source_pack``. Controlled dry/wet captures measure complex
transfer-function evidence. The six packed actors compiled from that evidence
are locally reconstructed actors, not uniquely identified anatomy.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile
from scipy.signal import csd, sosfilt, welch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.capture_compiler import (  # noqa: E402
    LETTERS,
    PASS_KERNEL,
    WHOLE_BODY_GESTURES,
    ZERO_TREATMENTS,
    actor_kernel,
    align_actor_lanes,
    confidence_map,
    classify_body_gestures,
    describe_stage,
    lane_support,
    neutralize_latent_lanes,
    pack_kernels,
    packed_surface_audit,
)
from pyruntime.forge_fit import fit_grid, perceptual_weight  # noqa: E402
from pyruntime.forge_joint import StageBand, joint_fit_corners  # noqa: E402
from pyruntime.packed_interp import kernel_to_biquad, packed_bilinear  # noqa: E402
from tools.author_body import compiled_payload  # noqa: E402
from tools.rom_corner_audit import clean_null  # noqa: E402

CORNER_KEYS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
KEY_TO_LETTER = dict(zip(CORNER_KEYS, LETTERS))
LETTER_TO_KEY = dict(zip(LETTERS, CORNER_KEYS))
NUM_STAGES = 6


def slugify(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower() or "untitled"


def load_mono(path: Path) -> tuple[float, np.ndarray]:
    sr, data = wavfile.read(str(path))
    arr = np.asarray(data)
    if arr.dtype.kind == "i":
        arr = arr.astype(np.float64) / max(float(np.iinfo(arr.dtype).max), 1.0)
    elif arr.dtype.kind == "u":
        info = np.iinfo(arr.dtype)
        midpoint = (float(info.max) + 1.0) * 0.5
        arr = (arr.astype(np.float64) - midpoint) / midpoint
    else:
        arr = arr.astype(np.float64)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    if arr.ndim != 1 or arr.size < 256:
        raise ValueError(f"{path}: expected at least 256 mono samples")
    return float(sr), arr


def empirical_tf(
    dry: np.ndarray,
    wet: np.ndarray,
    sr: float,
    nperseg: int = 8192,
) -> dict[str, np.ndarray]:
    """Measure H(f)=Sxy/Sxx and the spectra needed by the confidence map."""
    nperseg = max(256, min(nperseg, len(dry), len(wet)))
    f, sxx = welch(dry, fs=sr, nperseg=nperseg, detrend="constant", scaling="density")
    _, syy = welch(wet, fs=sr, nperseg=nperseg, detrend="constant", scaling="density")
    _, sxy = csd(dry, wet, fs=sr, nperseg=nperseg, detrend="constant", scaling="density")
    h = sxy / np.maximum(sxx, 1.0e-30)
    coherence = np.abs(sxy) ** 2 / np.maximum(sxx * syy, 1.0e-30)
    return {"freqs": f, "h": h, "coherence": coherence, "sxx": sxx, "syy": syy, "sxy": sxy}


def _sample_real(f_lin: np.ndarray, values: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    return np.interp(np.clip(freqs, f_lin[0], f_lin[-1]), f_lin, np.asarray(values, dtype=np.float64))


def _sample_complex(f_lin: np.ndarray, values: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    fq = np.clip(freqs, f_lin[0], f_lin[-1])
    mag = np.interp(fq, f_lin, np.abs(values))
    phase = np.interp(fq, f_lin, np.unwrap(np.angle(values)))
    return mag * np.exp(1j * phase)


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def _manifest_corner_paths(base: Path, entry: Any, label: str) -> list[Path]:
    if isinstance(entry, str):
        values = [entry]
    elif isinstance(entry, list):
        values = entry
    elif isinstance(entry, dict):
        values = entry.get("wets", entry.get("wet"))
        values = [values] if isinstance(values, str) else values
    else:
        values = None
    if not values or not all(isinstance(value, str) for value in values):
        raise ValueError(f"manifest corner {label} requires wet or wets")
    return [_resolve(base, value) for value in values]


def parse_mapping(value: str) -> tuple[str, list[int]]:
    if "=" not in value:
        raise ValueError("--lane-mapping must look like B=1,3,2,4,5,6")
    key, raw = value.split("=", 1)
    letter = KEY_TO_LETTER.get(key.strip().upper(), key.strip().upper())
    if letter not in LETTERS[1:]:
        raise ValueError("--lane-mapping corner must be B, C, D, or a non-anchor corner label")
    try:
        mapping = [int(item.strip()) - 1 for item in raw.split(",")]
    except ValueError as exc:
        raise ValueError("--lane-mapping rows must be six comma-separated 1-based integers") from exc
    if sorted(mapping) != list(range(NUM_STAGES)):
        raise ValueError("--lane-mapping rows must be a permutation of 1,2,3,4,5,6")
    return letter, mapping


def capture_inputs(args: argparse.Namespace) -> tuple[str, Path, dict[str, list[Path]], dict[str, Any]]:
    manifest: dict[str, Any] = {}
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        base = args.manifest.parent
        name = args.name or str(manifest.get("name") or "")
        dry_value = args.dry or manifest.get("dry")
        corners = manifest.get("corners")
        if not isinstance(corners, dict):
            raise ValueError("--manifest requires a corners object")
        paths = {label: _manifest_corner_paths(base, corners[label], label) for label in CORNER_KEYS}
        if dry_value is None:
            raise ValueError("--manifest requires dry or the CLI must supply --dry")
        dry = _resolve(base, dry_value)
    else:
        name = args.name or ""
        if args.dry is None:
            raise ValueError("--dry is required without --manifest")
        dry = args.dry
        paths = {}
        for label, primary, repeats in (
            ("M0_Q0", args.wet_m0_q0, args.wet_m0_q0_repeat),
            ("M100_Q0", args.wet_m100_q0, args.wet_m100_q0_repeat),
            ("M0_Q100", args.wet_m0_q100, args.wet_m0_q100_repeat),
            ("M100_Q100", args.wet_m100_q100, args.wet_m100_q100_repeat),
        ):
            if primary is None:
                raise ValueError(f"--wet-{label.lower().replace('_', '-')} is required without --manifest")
            paths[label] = [primary, *repeats]
    if not name:
        raise ValueError("--name is required unless supplied by --manifest")
    return name, dry, paths, manifest


def _manifest_seeds(manifest: dict[str, Any]) -> dict[str, np.ndarray] | None:
    raw = manifest.get("lane_seeds_hz")
    if not isinstance(raw, dict):
        return None
    seeds = {}
    for key, values in raw.items():
        letter = KEY_TO_LETTER.get(str(key).upper(), str(key).upper())
        if letter in LETTERS:
            arr = np.asarray(values, dtype=np.float64)
            if arr.shape != (NUM_STAGES,):
                raise ValueError(f"lane_seeds_hz.{key} must contain six pole frequencies")
            seeds[letter] = arr
    return seeds or None


def _manifest_kernel_seeds(manifest: dict[str, Any]) -> dict[str, np.ndarray] | None:
    raw = manifest.get("actor_kernel_seeds")
    if not isinstance(raw, dict):
        return None
    seeds = {}
    for key, values in raw.items():
        letter = KEY_TO_LETTER.get(str(key).upper(), str(key).upper())
        if letter in LETTERS:
            arr = np.asarray(values, dtype=np.float64)
            if arr.shape != (NUM_STAGES, 5):
                raise ValueError(f"actor_kernel_seeds.{key} must contain six kernel rows")
            seeds[letter] = arr
    return seeds or None


def _bands_from_seeds(seeds: dict[str, np.ndarray] | None, sr: float) -> list[StageBand] | None:
    if not seeds or any(letter not in seeds for letter in LETTERS):
        return None
    stacked = np.stack([seeds[letter] for letter in LETTERS])
    return [
        StageBand(
            freq_lo_hz=max(20.0, float(np.min(stacked[:, lane])) / 1.35),
            freq_hi_hz=min(sr * 0.49, float(np.max(stacked[:, lane])) * 1.35),
        )
        for lane in range(NUM_STAGES)
    ]


def _manifest_mappings(manifest: dict[str, Any], cli_values: list[str]) -> dict[str, list[int]]:
    mappings: dict[str, list[int]] = {}
    raw = manifest.get("lane_mappings")
    if isinstance(raw, dict):
        for key, values in raw.items():
            letter = KEY_TO_LETTER.get(str(key).upper(), str(key).upper())
            if letter == "A":
                continue
            if letter not in LETTERS:
                raise ValueError(f"unknown lane_mappings corner {key}")
            mapping = [int(value) - 1 for value in values]
            if sorted(mapping) != list(range(NUM_STAGES)):
                raise ValueError(f"lane_mappings.{key} must be a 1-based permutation of 1..6")
            mappings[letter] = mapping
    for value in cli_values:
        letter, mapping = parse_mapping(value)
        mappings[letter] = mapping
    return mappings


def _authored_lane(decision: str, previous: np.ndarray, sr: float) -> np.ndarray:
    defaults = {
        "add authored local tear": (1800.0, 0.965, 1550.0, 0.91),
        "add authored remote air cap": (6200.0, 0.90, 9800.0, 0.82),
        "add authored hollow": (950.0, 0.94, 420.0, 0.86),
        "reinforce foundation": (180.0, 0.92, 680.0, 0.75),
    }
    default = defaults[decision]
    rows = np.empty_like(previous)
    for index, row in enumerate(previous):
        pole = describe_stage(row, sr).pole
        pole_hz = pole.freq_hz if pole.radius > 0.1 else default[0]
        rows[index] = actor_kernel(pole_hz, default[1], default[2], default[3], sr)
    return rows


def apply_lane_decisions(
    kernels: dict[str, np.ndarray],
    reports: list[dict[str, Any]],
    sr: float,
    interactive: bool,
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    out = neutralize_latent_lanes(kernels, reports)
    decisions = []
    options = {
        "p": "preserve weak measured actor",
        "l": "leave latent",
        "t": "add authored local tear",
        "a": "add authored remote air cap",
        "h": "add authored hollow",
        "f": "reinforce foundation",
    }
    for report in reports:
        if report["evidence"] == "MEASURED_STRONG":
            continue
        lane = int(report["lane_index"])
        default = "l" if report["evidence"] == "LATENT" else "p"
        answer = default
        if interactive:
            print()
            print(f"lane {lane}: {report['evidence']} confidence={report['confidence']:.3f}")
            for key, label in options.items():
                print(f"  [{key}] {label}")
            answer = input(f"decision [{default}]: ").strip().lower() or default
        if answer not in options:
            raise ValueError(f"unknown lane decision {answer!r}")
        decision = options[answer]
        evidence = report["evidence"]
        if answer == "p":
            out = {letter: np.asarray(rows).copy() for letter, rows in out.items()}
            for letter in LETTERS:
                out[letter][lane] = kernels[letter][lane]
        elif answer == "l":
            for letter in LETTERS:
                out[letter][lane] = PASS_KERNEL
            evidence = "LATENT"
        else:
            authored = _authored_lane(decision, np.stack([kernels[letter][lane] for letter in LETTERS]), sr)
            for letter, row in zip(LETTERS, authored):
                out[letter][lane] = row
            evidence = "AUTHORED"
        decisions.append({"lane_index": lane, "decision": decision, "result_evidence": evidence})
    return out, decisions


def _kernel_to_sos(kernel: np.ndarray) -> np.ndarray:
    return np.asarray([
        [b0, b1, b2, 1.0, a1, a2]
        for b0, b1, b2, a1, a2 in (kernel_to_biquad(tuple(row)) for row in kernel)
    ], dtype=np.float64)


def render_kernel(dry: np.ndarray, kernel: np.ndarray, boost: float = 1.0) -> np.ndarray:
    return np.nan_to_num(sosfilt(_kernel_to_sos(kernel), np.asarray(dry, dtype=np.float64)) * boost)


def _sibling(out: Path, suffix: str) -> Path:
    stem = out.name[:-10] if out.name.endswith(".cart.json") else out.stem
    return out.with_name(stem + suffix)


def write_artifacts(
    artifact_dir: Path,
    dry: np.ndarray,
    words: dict[str, list[tuple[int, ...]]],
    body: bytes,
    sr: int,
    boost: float,
) -> list[str]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    center = np.asarray(packed_bilinear(words, 0.5, 0.5), dtype=np.float64)
    center_wav = artifact_dir / "audition_m50_q50.wav"
    wavfile.write(str(center_wav), sr, render_kernel(dry, center, boost).astype(np.float32))
    outputs.append(str(center_wav))

    chunks = []
    chunk_len = min(len(dry), max(256, int(round(sr * 0.30))))
    for value in np.linspace(0.0, 1.0, 17):
        kernel = np.asarray(packed_bilinear(words, float(value), float(value)), dtype=np.float64)
        chunks.append(render_kernel(dry[:chunk_len], kernel, boost))
    diagonal = np.concatenate(chunks)
    diagonal_wav = artifact_dir / "audition_diagonal_17.wav"
    wavfile.write(str(diagonal_wav), sr, diagonal.astype(np.float32))
    outputs.append(str(diagonal_wav))

    radii = np.empty((17, 17), dtype=np.float64)
    for qi in range(17):
        for mi in range(17):
            radii[qi, mi] = trench_ffi.packed_probe(body, mi / 16.0, qi / 16.0)["max_pole_radius"]
    fig, ax = plt.subplots(figsize=(6.2, 5.2), constrained_layout=True)
    image = ax.imshow(radii, origin="lower", extent=(0.0, 1.0, 0.0, 1.0), aspect="auto", cmap="magma")
    fig.colorbar(image, ax=ax, label="maximum pole radius")
    ax.set_xlabel("Morph")
    ax.set_ylabel("Secondary / Q")
    ax.set_title("Packed 17 x 17 stability surface")
    png = artifact_dir / "packed_stability_17x17.png"
    fig.savefig(png, dpi=145)
    plt.close(fig)
    outputs.append(str(png))
    return outputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", help="body name; optional when manifest supplies name")
    ap.add_argument("--dry", type=Path, help="exact dry broadband source .wav")
    ap.add_argument("--wet-m0-q0", type=Path)
    ap.add_argument("--wet-m100-q0", type=Path)
    ap.add_argument("--wet-m0-q100", type=Path)
    ap.add_argument("--wet-m100-q100", type=Path)
    ap.add_argument("--wet-m0-q0-repeat", type=Path, action="append", default=[])
    ap.add_argument("--wet-m100-q0-repeat", type=Path, action="append", default=[])
    ap.add_argument("--wet-m0-q100-repeat", type=Path, action="append", default=[])
    ap.add_argument("--wet-m100-q100-repeat", type=Path, action="append", default=[])
    ap.add_argument("--manifest", type=Path, help="capture-to-cartridge-manifest-v1 JSON")
    ap.add_argument("--lane-mapping", action="append", default=[],
                    help="override inferred actor correspondence, e.g. B=1,3,2,4,5,6")
    ap.add_argument("--interactive-lanes", action="store_true",
                    help="ask how to spend weak or latent lanes; unattended mode invents nothing")
    ap.add_argument("--out", type=Path, help="output cart.json path")
    ap.add_argument("--artifacts-dir", type=Path, help="plots and audition WAV directory")
    ap.add_argument("--boost", type=float, default=1.0)
    ap.add_argument("--restarts", type=int, default=8)
    ap.add_argument("--max-nfev", type=int, default=1500)
    ap.add_argument("--grid", type=int, default=1024)
    ap.add_argument("--profile", default="vocal")
    ap.add_argument("--robust-delta", type=float, default=3.0)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    try:
        name, dry_path, wet_paths, manifest = capture_inputs(args)
        sr_dry, dry = load_mono(dry_path)
        sr = float(sr_dry)
        freqs, z_inv = fit_grid(sr, n=args.grid)
        base_weight = perceptual_weight(freqs, args.profile)

        print(f"loaded dry: {dry_path} ({len(dry) / sr:.2f}s @ {sr:g} Hz)")
        targets: dict[str, np.ndarray] = {}
        weights: dict[str, np.ndarray] = {}
        measurement_report: dict[str, Any] = {}
        loaded_wets: dict[str, list[np.ndarray]] = {}
        for label in CORNER_KEYS:
            repeat_rows = []
            loaded_wets[label] = []
            for path in wet_paths[label]:
                sr_wet, wet = load_mono(path)
                if sr_wet != sr:
                    raise ValueError(f"{path}: sample rate {sr_wet:g} does not match dry {sr:g}")
                n = min(len(dry), len(wet))
                repeat_rows.append(empirical_tf(dry[:n], wet[:n], sr))
                loaded_wets[label].append(wet)
            sampled_h = np.stack([_sample_complex(row["freqs"], row["h"], freqs) for row in repeat_rows])
            sampled_coh = np.mean([_sample_real(row["freqs"], row["coherence"], freqs) for row in repeat_rows], axis=0)
            sampled_sxx = np.mean([_sample_real(row["freqs"], row["sxx"], freqs) for row in repeat_rows], axis=0)
            sampled_syy = np.mean([_sample_real(row["freqs"], row["syy"], freqs) for row in repeat_rows], axis=0)
            sampled_sxy = np.mean([_sample_complex(row["freqs"], row["sxy"], freqs) for row in repeat_rows], axis=0)
            target = np.mean(sampled_h, axis=0)
            confidence = confidence_map(base_weight, sampled_sxx, sampled_syy, sampled_sxy, sampled_coh, sampled_h)
            letter = KEY_TO_LETTER[label]
            targets[letter] = target
            weights[letter] = confidence["effective"]
            measurement_report[label] = {
                "wet_files": [str(path) for path in wet_paths[label]],
                "repeat_count": len(wet_paths[label]),
                **confidence["summary"],
            }
            print(
                f"measured {label:9} repeats={len(wet_paths[label])} "
                f"coherence_mean={confidence['summary']['coherence']['mean']:.4f} "
                f"confidence_mean={confidence['summary']['effective']['mean']:.4f}"
            )

        combined_weight = np.minimum.reduce([weights[letter] for letter in LETTERS])
        seeds = _manifest_seeds(manifest)
        kernel_seeds = _manifest_kernel_seeds(manifest)
        bands = _bands_from_seeds(seeds, sr)
        print(
            f"joint fit: 4 corners x 6 persistent actors, restarts={args.restarts}, "
            f"grid={args.grid}, robust_delta={args.robust_delta:g}"
        )
        fit = joint_fit_corners(
            targets=targets,
            freqs=freqs,
            z_inv=z_inv,
            sr=sr,
            bands=bands,
            seeds=seeds,
            initial_kernels=kernel_seeds,
            profile=args.profile,
            weight=combined_weight,
            n_restarts=args.restarts,
            seed=1234,
            max_nfev=args.max_nfev,
            robust_delta=args.robust_delta,
            verbose=args.verbose,
        )
        overrides = _manifest_mappings(manifest, args.lane_mapping)
        aligned, mappings = align_actor_lanes(fit.kernel, sr, overrides)
        initial_lanes = lane_support(aligned, z_inv, combined_weight, sr)
        final_kernels, lane_decisions = apply_lane_decisions(aligned, initial_lanes, sr, args.interactive_lanes)
        final_lanes = lane_support(final_kernels, z_inv, combined_weight, sr)
        for lane, decision in zip(final_lanes, ({row["lane_index"]: row for row in lane_decisions}.get(i) for i in range(6))):
            lane["measurement_support"] = lane.pop("evidence")
            lane["evidence_label"] = "LATENT" if lane["measurement_support"] == "LATENT" else "INFERRED"
            if decision and decision["result_evidence"] == "AUTHORED":
                lane["evidence_label"] = "AUTHORED"
        gestures = classify_body_gestures([
            {**lane, "evidence": lane["evidence_label"]}
            for lane in final_lanes
        ])

        words, body = pack_kernels(final_kernels)
        audit = packed_surface_audit(final_kernels, words, body, targets, weights, z_inv)
        packed_nulls = audit["corner_weighted_complex_residual_db"]
        print("packed corner weighted complex residuals:")
        for letter in LETTERS:
            print(f"  {LETTER_TO_KEY[letter]:9} {packed_nulls[letter]:+8.2f} dB")
        grid = audit["stability_grid"]
        print(
            f"packed 17x17: maxR={grid['maximum_pole_radius']:.9f} "
            f"unstable_rows={grid['unstable_rows']} nonfinite_rows={grid['nonfinite_rows']}"
        )

        captured_wet_nulls = {}
        for label in CORNER_KEYS:
            letter = KEY_TO_LETTER[label]
            rendered = render_kernel(dry, np.asarray(packed_bilinear(words, *{
                "A": (0.0, 0.0), "B": (1.0, 0.0), "C": (0.0, 1.0), "D": (1.0, 1.0),
            }[letter]), dtype=np.float64), args.boost)
            wet = loaded_wets[label][0]
            n = min(len(rendered), len(wet))
            lag, null_db = clean_null(rendered[:n], wet[:n])
            captured_wet_nulls[label] = {"null_db": float(null_db), "lag_samples": int(lag)}

        out = args.out or ROOT / "bodies" / f"{slugify(name)}.cart.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        body_path = _sibling(out, ".body240")
        report_path = _sibling(out, ".report.json")
        artifact_dir = args.artifacts_dir or _sibling(out, ".artifacts")
        body_path.write_bytes(body)
        artifacts = write_artifacts(artifact_dir, dry, words, body, int(round(sr)), args.boost)

        keyed_words = {LETTER_TO_KEY[letter]: words[letter] for letter in LETTERS}
        payload = compiled_payload(name, args.boost, keyed_words)
        payload["sampleRate"] = sr
        payload["authoring_sample_rate_hz"] = sr
        payload["provenance"] = "controlled-dry-wet-capture-compiled-packed-240"
        payload["captureReport"] = str(report_path)
        payload["body240Sha256"] = audit["packed_body_sha256"]
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        counts = {
            label: sum(row["measurement_support"] == label for row in final_lanes)
            for label in ("MEASURED_STRONG", "MEASURED_WEAK", "LATENT")
        }
        counts["AUTHORED"] = sum(row["evidence_label"] == "AUTHORED" for row in final_lanes)
        report = {
            "format": "capture-to-cartridge-report-v2",
            "name": name,
            "provenance_boundary": {
                "controlled_capture": "MEASURED_STRONG or MEASURED_WEAK complex transfer-function evidence",
                "serialized_actors": "INFERRED local six-lane reconstruction unless individually labeled AUTHORED or LATENT",
                "standalone_wav_claim_rejected": "audio-only WAV does not uniquely recover physical vocal-tract zeros",
            },
            "capture_mode": "repeated" if any(len(paths) > 1 for paths in wet_paths.values()) else "single",
            "input_dry_file": str(dry_path),
            "wet_files": {label: [str(path) for path in wet_paths[label]] for label in CORNER_KEYS},
            "input_sample_rates_hz": {
                "dry": sr,
                "wets": {label: [sr for _path in wet_paths[label]] for label in CORNER_KEYS},
            },
            "sample_rate_hz": sr,
            "authoring_sample_rate_hz": sr,
            "measurement_confidence": measurement_report,
            "fit_configuration": {
                "profile": args.profile,
                "grid_points": args.grid,
                "restarts": args.restarts,
                "best_restart_1_based": fit.best_restart + 1,
                "max_nfev": args.max_nfev,
                "robust_complex_loss": "target-relative bounded influence",
                "robust_delta": args.robust_delta,
                "manifest_lane_seeds_available": bool(seeds),
                "manifest_actor_kernel_seeds_available": bool(kernel_seeds),
                "actor_prior_source": manifest.get("actor_prior_source"),
                "seeded_stage_bands_available": bool(bands),
            },
            "vocabulary": {
                "primitive_zero_treatments": list(ZERO_TREATMENTS),
                "whole_body_gestures": list(WHOLE_BODY_GESTURES),
                "inferred_whole_body_gestures": gestures,
            },
            "lane_mappings": mappings,
            "lane_support_summary": counts,
            "lane_decisions": lane_decisions,
            "lanes": final_lanes,
            "captured_wet_time_domain_nulls": captured_wet_nulls,
            "packed_surface_audit": audit,
            "outputs": {
                "cartridge": str(out),
                "body240": str(body_path),
                "report": str(report_path),
                "artifacts": artifacts,
            },
            "warnings": list(fit.notes) + list(audit["warnings"]),
            "limitations": [
                (
                    f"Packed coefficients were fitted and audited at {sr:g} Hz. "
                    "Preparing the cascade at another host rate shifts the realized "
                    "pole and zero frequencies unless the runtime adds rate adaptation."
                ),
                (
                    "Standalone WAVs, including dev/tmp/arma_source_pack quarry material, "
                    "supply INFERRED spectral-envelope actor priors only. They do not "
                    "uniquely recover physical source-filter zeros."
                ),
            ],
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            "lane support: "
            f"{counts['MEASURED_STRONG']} strong, {counts['MEASURED_WEAK']} weak, "
            f"{counts['LATENT']} latent, {counts['AUTHORED']} authored"
        )
        print(f"wrote cartridge: {out}")
        print(f"wrote body240:   {body_path} ({len(body)} bytes)")
        print(f"wrote report:    {report_path}")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"capture_to_cartridge error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
