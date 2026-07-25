#!/usr/bin/env python3
"""Author and audition four isolated, explicitly authored DF2 body recuts.

The body definitions below are deliberately literal four-corner design records.
Q100 is authored independently. The generated 240-byte bodies are then handed
to the retained author_body packed-word path, trench_core packed_probe, and the
shipped FilterEngine FFI. This file does not alter any source-area body.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
PACK = Path(__file__).resolve().parent
HELPER_PATH = ROOT / "dev" / "tmp" / "audition" / "last_presets_2026-07-13" / "build_last_presets_audition.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from src.utils.body240 import raw_from_words  # noqa: E402
from tools.corner_words import corner_words, notch  # noqa: E402


HELPER_SPEC = importlib.util.spec_from_file_location("audition_helpers", HELPER_PATH)
if HELPER_SPEC is None or HELPER_SPEC.loader is None:
    raise RuntimeError(f"cannot load audition helper: {HELPER_PATH}")
HELPERS = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(HELPERS)
HELPERS.PACK_DIR = PACK


CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
AUTHORING_SR = 39062.5
GRID = 17
NATIVE_SR = float(HELPERS.NATIVE_SR)


def stage(pole_hz: float, zero_hz: float, radius: float, zero_radius: float, depth: float) -> tuple[float, float, float, float, float]:
    """One explicit pole/zero/SCALE record: pole, zero, r, rz, val1."""
    return (float(pole_hz), float(zero_hz), float(radius), float(zero_radius), float(depth))


# The last field is val1, so SCALE/b0 is exactly 1 + depth. These are not
# fitted or derived-Q records: every corner below is a separate authored pose.
# Zero centers are intentionally not co-located with pole centers; this is the
# repair for the old VOWL chord's near cancellation.
CANDIDATE_SPECS: list[dict[str, Any]] = [
    {
        "name": "VOWL_CHORD_2actor_recut",
        "slug": "vowl_chord_2actor_recut",
        "concept": "Two vocal actors with independent inter-formant valleys; a vowel chord instead of six near-cancelled resonators.",
        "reference": ROOT / "bodies" / "proofs" / "VOWL_CHORD_2actor.body240",
        "reference_role": "Observed original VOWL chord geometry only; no source bytes or coefficient rows copied.",
        "source_provenance": "UNKNOWN: no external approved source session is attached; geometry is an authored recut in this run.",
        "corners": {
            "M0_Q0": [
                stage(270, 680, .978, .72, -.70), stage(870, 1500, .975, .70, -.65), stage(2240, 3900, .972, .76, -.60),
                stage(330, 950, .978, .66, -.70), stage(2050, 3150, .975, .74, -.65), stage(3150, 5000, .972, .80, -.60),
            ],
            "M100_Q0": [
                stage(530, 1000, .978, .70, -.70), stage(1840, 2700, .975, .75, -.65), stage(2480, 4300, .972, .80, -.60),
                stage(660, 1250, .978, .67, -.70), stage(1720, 2950, .975, .74, -.65), stage(2410, 4800, .972, .82, -.60),
            ],
            "M0_Q100": [
                stage(730, 1250, .977, .70, -.69), stage(1090, 1750, .976, .72, -.64), stage(2440, 4000, .973, .78, -.59),
                stage(430, 820, .977, .67, -.69), stage(1900, 2900, .975, .75, -.64), stage(2700, 4600, .973, .81, -.59),
            ],
            "M100_Q100": [
                stage(400, 760, .978, .68, -.70), stage(1300, 2050, .975, .73, -.65), stage(2950, 5000, .972, .80, -.60),
                stage(800, 1400, .977, .68, -.70), stage(2100, 3450, .974, .77, -.65), stage(2800, 5200, .972, .83, -.60),
            ],
        },
    },
    {
        "name": "VOWL_CHORD_2actor_duet_recut",
        "slug": "vowl_chord_2actor_duet_recut",
        "concept": "A more unstable-feeling duet: crossed mouths plus an upper glass zero that makes the last actor tear into air.",
        "reference": ROOT / "bodies" / "proofs" / "VOWL_CHORD_2actor_duet.body240",
        "reference_role": "Observed original duet geometry only; no source bytes or coefficient rows copied.",
        "source_provenance": "UNKNOWN: no external approved source session is attached; geometry is an authored recut in this run.",
        "corners": {
            "M0_Q0": [
                stage(300, 760, .978, .65, -.70), stage(900, 1550, .975, .68, -.65), stage(2350, 4100, .972, .76, -.60),
                stage(210, 520, .979, .62, -.70), stage(1980, 3600, .975, .74, -.65), stage(3320, 7200, .972, .80, -.56),
            ],
            "M100_Q0": [
                stage(620, 1250, .977, .66, -.70), stage(1700, 2900, .975, .73, -.65), stage(2650, 4700, .972, .79, -.60),
                stage(480, 900, .978, .63, -.70), stage(2300, 3900, .974, .76, -.65), stage(3600, 9800, .970, .82, -.55),
            ],
            "M0_Q100": [
                stage(250, 560, .978, .60, -.70), stage(1150, 2050, .975, .70, -.65), stage(2850, 5200, .971, .78, -.60),
                stage(730, 1800, .977, .67, -.69), stage(2100, 4400, .974, .77, -.64), stage(4800, 14500, .969, .86, -.52),
            ],
            "M100_Q100": [
                stage(520, 1050, .977, .64, -.70), stage(1450, 2500, .975, .71, -.65), stage(3050, 5600, .971, .80, -.60),
                stage(920, 1600, .977, .66, -.69), stage(2600, 4600, .973, .78, -.64), stage(5200, 16000, .968, .88, -.52),
            ],
        },
    },
    {
        "name": "SWEEP_TO_VOWEL",
        "slug": "sweep_to_vowel",
        "concept": "A sparse mechanical sweep at Morph 0 that resolves into a voiced multi-formant mouth at Morph 100.",
        "reference": ROOT / "juce-shell" / "assets" / "bodies" / "sweep.body240",
        "reference_role": "Observed sweep movement only; no source bytes or coefficient rows copied.",
        "source_provenance": "UNKNOWN: no external approved source session is attached; geometry is an authored recut in this run.",
        "corners": {
            "M0_Q0": [
                stage(80, 18000, .900, .72, -.82), stage(545, 1420, .925, .74, -.78), stage(1420, 2840, .940, .78, -.74),
                stage(365, 780, .915, .68, -.80), stage(450, 5450, .910, .74, -.78), stage(16450, 16500, .950, .84, -.62),
            ],
            "M100_Q0": [
                stage(300, 700, .978, .70, -.70), stage(870, 1500, .975, .72, -.65), stage(2240, 3900, .972, .78, -.60),
                stage(270, 650, .978, .66, -.70), stage(2290, 3600, .974, .78, -.65), stage(3010, 5200, .972, .82, -.58),
            ],
            "M0_Q100": [
                stage(120, 16000, .910, .68, -.82), stage(900, 2500, .930, .73, -.78), stage(1800, 6000, .940, .80, -.74),
                stage(420, 900, .920, .68, -.80), stage(700, 8000, .910, .80, -.77), stage(15000, 12000, .945, .86, -.60),
            ],
            "M100_Q100": [
                stage(530, 1050, .978, .70, -.70), stage(1840, 2750, .975, .76, -.65), stage(2480, 4300, .972, .82, -.59),
                stage(660, 1300, .977, .68, -.70), stage(1720, 3150, .974, .78, -.65), stage(2410, 4700, .972, .83, -.58),
            ],
        },
    },
    {
        "name": "TEAR_TO_GLASS",
        "slug": "tear_to_glass",
        "concept": "A crossed 808-like tear at Morph 0 that opens into metallic glass and high-air shards at Morph 100.",
        "reference": ROOT / "juce-shell" / "assets" / "bodies" / "ship_808_tear.body240",
        "reference_role": "Observed tear movement only; no source bytes or coefficient rows copied.",
        "source_provenance": "UNKNOWN: no external approved source session is attached; geometry is an authored recut in this run.",
        "corners": {
            "M0_Q0": [
                stage(271, 139, .965, .64, -.45), stage(513, 434, .968, .66, -.45), stage(972, 1711, .970, .76, -.42),
                stage(4524, 2192, .974, .70, -.38), stage(12497, 6386, .978, .72, -.34), stage(3600, 2901, .972, .68, -.40),
            ],
            "M100_Q0": [
                stage(420, 7000, .974, .64, -.43), stage(1200, 2200, .976, .76, -.40), stage(3200, 4800, .974, .84, -.36),
                stage(7500, 11000, .978, .72, -.34), stage(13200, 15500, .980, .78, -.32), stage(16200, 12000, .982, .70, -.30),
            ],
            "M0_Q100": [
                stage(190, 1000, .966, .62, -.45), stage(680, 250, .968, .62, -.45), stage(1450, 3100, .970, .74, -.42),
                stage(5200, 1450, .975, .69, -.38), stage(10500, 4200, .979, .70, -.34), stage(4100, 9000, .973, .80, -.36),
            ],
            "M100_Q100": [
                stage(360, 6800, .976, .62, -.43), stage(1500, 2900, .978, .78, -.40), stage(3800, 6200, .976, .86, -.36),
                stage(8200, 13200, .980, .74, -.32), stage(14500, 17400, .982, .82, -.30), stage(17500, 12500, .984, .72, -.28),
            ],
        },
    },
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    return value


def geometry_json(records: dict[str, list[tuple[float, float, float, float, float]]]) -> dict[str, list[dict[str, float]]]:
    return {
        corner: [
            {
                "pole_hz": pole,
                "zero_hz": zero,
                "pole_radius": radius,
                "zero_radius": zero_radius,
                "val1": depth,
                "scale_b0": 1.0 + depth,
            }
            for pole, zero, radius, zero_radius, depth in stages
        ]
        for corner, stages in records.items()
    }


def compile_candidates() -> tuple[list[dict[str, Any]], dict[str, str]]:
    candidates: list[dict[str, Any]] = []
    reference_hashes: dict[str, str] = {}
    body_dir = PACK / "candidates"
    body_dir.mkdir(parents=True, exist_ok=True)

    for spec in CANDIDATE_SPECS:
        corners = spec["corners"]
        if tuple(corners) != CORNER_ORDER:
            raise RuntimeError(f"{spec['name']}: corner order is not the authored contract")
        if any(len(corners[label]) != 6 for label in CORNER_ORDER):
            raise RuntimeError(f"{spec['name']}: every authored corner must contain six lanes")

        words = {label: corner_words([notch(pole, radius, depth, zero, zero_radius) for pole, zero, radius, zero_radius, depth in corners[label]]) for label in CORNER_ORDER}
        body = raw_from_words(words)
        if len(body) != 240:
            raise RuntimeError(f"{spec['name']}: generated body is {len(body)} bytes")

        body_path = body_dir / f"{spec['slug']}.body240"
        design_path = body_dir / f"{spec['slug']}.design.json"
        body_path.write_bytes(body)

        reference = Path(spec["reference"])
        if reference.exists():
            reference_hashes[str(reference)] = sha256_file(reference)
        else:
            reference_hashes[str(reference)] = "UNKNOWN"

        design = {
            "format": "packed-body-v1",
            "name": spec["name"],
            "boost": 1.0,
            "authoring_sample_rate_hz": AUTHORING_SR,
            "cornerOrder": list(CORNER_ORDER),
            "corner": {label: {"words": [list(row) for row in words[label]]} for label in CORNER_ORDER},
            "packedWords": {label: [list(row) for row in words[label]] for label in CORNER_ORDER},
            "authored_geometry": geometry_json(corners),
            "authoring_law": {
                "all_four_corners_authored": True,
                "q100_is_authored_second_pose": True,
                "q_is_not_derived": True,
                "stage_correspondence_is_sacred": True,
                "hidden_repair_or_normalization": False,
            },
            "concept": spec["concept"],
            "source_provenance": spec["source_provenance"],
            "reference_body": {
                "path": str(reference),
                "sha256": reference_hashes[str(reference)],
                "role": spec["reference_role"],
            },
            "body_sha256": sha256_bytes(body),
            "byte_length": len(body),
        }
        design_path.write_text(json.dumps(json_ready(design), indent=2) + "\n", encoding="utf-8")

        item = {
            "name": spec["name"],
            "slug": spec["slug"],
            "concept": spec["concept"],
            "path": str(body_path.resolve()),
            "mtime": iso_mtime(body_path),
            "mtime_epoch": body_path.stat().st_mtime,
            "sha256": sha256_bytes(body),
            "byte_length": len(body),
            "sidecar_exists": True,
            "sidecars": [{"path": str(design_path.resolve()), "kind": "design/provenance"}],
            "design_path": str(design_path.resolve()),
            "provenance_status": "OBSERVED: generated design/provenance sidecar present; external source provenance UNKNOWN",
            "source_provenance": spec["source_provenance"],
            "reference_body": str(reference),
            "reference_sha256": reference_hashes[str(reference)],
            "reference_role": spec["reference_role"],
            "notes": spec["concept"],
        }
        candidates.append(item)

    return candidates, reference_hashes


def roundtrip_packed_words(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proof_dir = PACK / "proof"
    proof_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    author_body = ROOT / "tools" / "author_body.py"
    for candidate in candidates:
        design = Path(candidate["design_path"])
        roundtrip = proof_dir / f"{candidate['slug']}.roundtrip.body240"
        compiled = proof_dir / f"{candidate['slug']}.roundtrip.cart.json"
        command = [sys.executable, str(author_body), str(design), "--raw-out", str(roundtrip), "--out", str(compiled)]
        completed = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
        original = Path(candidate["path"]).read_bytes()
        returned = roundtrip.read_bytes()
        result = {
            "candidate": candidate["name"],
            "command": " ".join(f'"{part}"' if " " in part else part for part in command),
            "roundtrip_body": str(roundtrip.resolve()),
            "compiled_cart": str(compiled.resolve()),
            "stdout": completed.stdout.strip(),
            "byte_identical": original == returned,
            "roundtrip_sha256": sha256_bytes(returned),
        }
        if not result["byte_identical"]:
            raise RuntimeError(f"{candidate['name']}: packedWords -> raw body did not converge")
        results.append(result)
    return results


def candidate_table(candidates: list[dict[str, Any]]) -> None:
    fields = [
        "decision_KEEP_or_KILL", "name", "concept", "absolute_path", "sha256", "byte_length",
        "design_sidecar", "reference_body", "reference_sha256", "grid_resolution", "unstable_rows",
        "nonfinite_rows", "max_pole_radius", "max_radius_at", "max_abs_pole_center_delta_hz_observed",
        "max_abs_zero_center_delta_hz_observed", "runtime_plot", "raw_snapshots_wav", "listen_snapshots_wav", "notes",
    ]
    with (PACK / "candidate_table.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in candidates:
            audio = candidate.get("audio", {})
            writer.writerow({
                "decision_KEEP_or_KILL": "",
                "name": candidate["name"],
                "concept": candidate["concept"],
                "absolute_path": candidate["path"],
                "sha256": candidate["sha256"],
                "byte_length": candidate["byte_length"],
                "design_sidecar": candidate["design_path"],
                "reference_body": candidate["reference_body"],
                "reference_sha256": candidate["reference_sha256"],
                "grid_resolution": candidate["grid_resolution"],
                "unstable_rows": candidate["unstable_rows"],
                "nonfinite_rows": candidate["nonfinite_rows"],
                "max_pole_radius": f"{candidate['max_pole_radius']:.9f}",
                "max_radius_at": json.dumps(candidate["max_pole_radius_at"], separators=(",", ":")),
                "max_abs_pole_center_delta_hz_observed": f"{candidate['max_abs_pole_center_delta_hz_observed']:.6f}",
                "max_abs_zero_center_delta_hz_observed": f"{candidate['max_abs_zero_center_delta_hz_observed']:.6f}",
                "runtime_plot": candidate["plot_path"],
                "raw_snapshots_wav": audio.get("raw_files", {}).get("snapshots", ""),
                "listen_snapshots_wav": audio.get("listen_files", {}).get("snapshots", ""),
                "notes": "Blank decision is intentional; mark KEEP or KILL after listening.",
            })


def read_float_wav(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RuntimeError(f"not a canonical WAV: {path}")
    return np.frombuffer(data[44:], dtype="<f4").copy()


def verify_audio(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for candidate in candidates:
        audio = candidate["audio"]
        raw_files = audio["raw_files"]
        listen_files = audio["listen_files"]
        raw_peaks: dict[str, float] = {}
        listen_peaks: dict[str, float] = {}
        for behavior, raw_name in raw_files.items():
            raw = read_float_wav(Path(raw_name))
            listen = read_float_wav(Path(listen_files[behavior]))
            if raw.size != listen.size or not np.all(np.isfinite(raw)) or not np.all(np.isfinite(listen)):
                raise RuntimeError(f"{candidate['name']} {behavior}: nonfinite or mismatched WAV")
            raw_peaks[behavior] = float(np.max(np.abs(raw)))
            listen_peaks[behavior] = float(np.max(np.abs(listen)))
        checks.append({
            "candidate": candidate["name"],
            "all_float32_mono_finite": True,
            "raw_peak_observed": max(raw_peaks.values()),
            "listen_peak_observed": max(listen_peaks.values()),
            "listen_gain_linear": audio["listen_gain_linear"],
            "raw_untouched": True,
            "raw_peaks": raw_peaks,
            "listen_peaks": listen_peaks,
        })
    return checks


def build_readme(manifest: dict[str, Any]) -> str:
    runtime = manifest["runtime"]
    lines = [
        "# Interesting preset recuts — 2026-07-13",
        "",
        "This is an isolated audition pack for the latest VOWL/sweep/tear recuts. Original source bodies remain in place and were not overwritten, moved, or normalized.",
        "",
        "## What changed",
        "",
        "The old VOWL chord was nearly flat because each stage's pole and zero centers were co-located, with only a small radius separation. The two VOWL recuts keep six lane identities but author independent zero centers in the valleys between formants. The sweep recut begins with sparse moving mechanical centers and resolves into authored vowel centers. The tear recut begins with crossed tear/notch centers and resolves into upper metallic/glass centers.",
        "",
        "These are explicit designs, not a fitter. Each body has six stages in each of four independently authored corners: M0_Q0, M100_Q0, M0_Q100, M100_Q100. Q100 is not derived.",
        "",
        "## Candidates",
        "",
    ]
    for candidate in manifest["candidates"]:
        lines.append(f"- `{candidate['name']}` — `{candidate['sha256']}` — {candidate['concept']}")
        lines.append(f"  body: `{candidate['path']}`")
        lines.append(f"  design/provenance sidecar: `{candidate['design_path']}`")
        lines.append(f"  observed reference only: `{candidate['reference_body']}` — `{candidate['reference_sha256']}`")
    lines += [
        "",
        "## Runtime and sampled certification",
        "",
        f"Backend: `{runtime['backend']}`",
        f"Runtime library: `{runtime['library']}`",
        "Plots and probe data come from `pyruntime.trench_ffi.packed_probe` rows returned by the shipped `trench_core` decoder. Audio comes from the shipped FilterEngine FFI; there is no silent fallback renderer.",
        f"Probe grid: `{manifest['probe']['grid_resolution']}` ({manifest['probe']['points']} points per candidate). This is sampled certification, not continuum proof.",
        "",
        "| Candidate | unstable rows | nonfinite rows | maximum pole radius | observed pole movement Hz | observed zero movement Hz |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for candidate in manifest["candidates"]:
        lines.append(
            f"| `{candidate['name']}` | {candidate['unstable_rows']} | {candidate['nonfinite_rows']} | {candidate['max_pole_radius']:.9f} | {candidate['max_abs_pole_center_delta_hz_observed']:.3f} | {candidate['max_abs_zero_center_delta_hz_observed']:.3f} |"
        )
    lines += [
        "",
        "The four authored corner reports and observed Q0→Q100 pole/zero center movements are in `manifest.json` under each candidate. No Q values were derived, repaired, normalized, reordered, or rejected because of an old derived-Q rule.",
        "",
        "## Audio",
        "",
        f"Native engine sample rate: `{manifest['audio']['sample_rate_hz']:.0f} Hz`.",
        "Every candidate has seven files in `wav_raw/` and matching files in `wav_listen/`: frozen snapshots, Morph sweeps at Q0/Q50/Q100, and Q sweeps at Morph 0/50/100. The source set is deterministic pink noise, saw, and 808/short drum. An approved real material loop was not found; status is `UNKNOWN` and it was omitted.",
        "",
        "`wav_raw/` is faithful engine output at unity I/O. It is not clipped, normalized, or replaced. `wav_listen/` applies one clearly documented scalar per candidate uniformly to all seven files for easy comparison; the scalar and raw peak are in `manifest.json`.",
        "",
        "## Proof artifacts",
        "",
        "- `plots/<name>_runtime.png`: four runtime corner curves, Morph sweeps, Q sweeps, six-lane pole/zero schematic, and secondary stability/nonfinite map on shared axes.",
        "- `plots/contact_sheet.png` and `plots/comparison_sheet.png`: identical runtime-derived dB scale (`-100…60 dB`).",
        "- `proof/*.roundtrip.body240` and `proof/*.roundtrip.cart.json`: packedWords/body-cart parity checks through `tools/author_body.py`; each raw roundtrip is byte-identical to the generated body.",
        "- `candidate_table.csv`: short listening table. The decision field is blank for you to mark `KEEP` or `KILL`; this pack contains no keep/kill verdict.",
        "",
        "## Exact commands",
        "",
        f"```powershell\nSet-Location -LiteralPath '{ROOT}'\npython '{Path(__file__).resolve()}'\n```",
        "",
        "Runtime authority: `trench_core` only. Source provenance for these new authored geometries is `UNKNOWN` beyond the explicit design records in their sidecars. P2K material was not copied or used in this pack.",
        "",
        "No plugin UI, workstation UI, runtime math, source-area body, or candidate byte outside this isolated output folder was modified.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    PACK.mkdir(parents=True, exist_ok=True)
    before_reference_hashes = {
        str(Path(spec["reference"])): sha256_file(Path(spec["reference"])) if Path(spec["reference"]).exists() else "UNKNOWN"
        for spec in CANDIDATE_SPECS
    }

    candidates, reference_hashes = compile_candidates()
    roundtrip = roundtrip_packed_words(candidates)

    print(f"auditing {len(candidates)} generated bodies through trench_core packed_probe", flush=True)
    runtime_candidates: list[dict[str, Any]] = []
    for item in candidates:
        candidate = HELPERS.candidate_runtime_record(item, GRID)
        runtime_candidates.append(candidate)
        candidate["plot_path"] = str((PACK / "plots" / f"{candidate['slug']}_runtime.png").resolve())
        candidate["_plot_path"] = candidate["plot_path"]
        HELPERS.plot_candidate(candidate, Path(candidate["plot_path"]))

    HELPERS.plot_comparison_sheet(runtime_candidates, PACK / "plots" / "comparison_sheet.png")
    HELPERS.plot_contact_sheet(runtime_candidates, PACK / "plots" / "contact_sheet.png")

    sources, source_metadata = HELPERS.build_sources()
    print(f"rendering {len(runtime_candidates)} bodies through shipped engine at {NATIVE_SR:.0f} Hz", flush=True)
    for candidate in runtime_candidates:
        candidate["audio"] = HELPERS.render_audio_for_candidate(candidate, sources, source_metadata)
    audio_checks = verify_audio(runtime_candidates)

    after_reference_hashes = {
        path: sha256_file(Path(path)) if Path(path).exists() else "UNKNOWN"
        for path in before_reference_hashes
    }
    if before_reference_hashes != after_reference_hashes:
        raise RuntimeError("source reference hash changed while building isolated pack")

    candidate_table(runtime_candidates)
    public_candidates = [HELPERS.manifest_candidate(candidate) for candidate in runtime_candidates]
    manifest = {
        "format": "df2-interesting-preset-audition-v1",
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "workspace": str(ROOT),
        "output_directory": str(PACK.resolve()),
        "runtime": {
            "backend": "pyruntime.trench_ffi -> shipped trench_core packed_probe and FilterEngine FFI",
            "library": str(trench_ffi.lib_path()) if trench_ffi.lib_path() else "UNKNOWN",
            "body_bytes": 240,
            "corner_order": list(CORNER_ORDER),
            "interpolation_authority": "packed-u16 Morph-first, then Q; six serial DF2T sections",
            "audio_mode": "BODY SOLO; unity I/O; AGC, DC block, saturation disabled",
        },
        "authoring": {
            "method": "explicit four-corner pole/zero/SCALE records via tools.corner_words -> trench_core-compatible packed words",
            "all_four_corners_authored": True,
            "q100_is_authored": True,
            "q_is_not_derived": True,
            "hidden_repair_or_normalization": False,
            "external_source_provenance": "UNKNOWN",
        },
        "probe": {
            "grid_resolution": f"{GRID}x{GRID}",
            "points": GRID * GRID,
            "certification_label": "sampled certification; not continuum proof",
        },
        "audio": {
            "sample_rate_hz": NATIVE_SR,
            "format": "IEEE float32 mono WAV",
            "source_metadata": source_metadata,
            "approved_real_material_loop": "UNKNOWN; no approved source metadata found, omitted",
            "raw_audio": "faithful engine output; untouched",
            "listen_audio": "one scalar per candidate applied uniformly to the seven files; not a replacement for raw",
        },
        "candidates": public_candidates,
        "packed_words_roundtrip": roundtrip,
        "audio_verification": audio_checks,
        "reference_hashes_before": before_reference_hashes,
        "reference_hashes_after": after_reference_hashes,
        "reference_hashes_used_by_design": reference_hashes,
        "commands": [
            f"Set-Location -LiteralPath '{ROOT}'",
            f"python '{Path(__file__).resolve()}'",
            "For each generated design sidecar: python tools/author_body.py <design.json> --raw-out <roundtrip.body240> --out <roundtrip.cart.json>",
        ],
        "verdict": "No keep/kill verdicts supplied; candidate_table.csv is intentionally blank.",
    }
    (PACK / "manifest.json").write_text(json.dumps(json_ready(manifest), indent=2) + "\n", encoding="utf-8")
    (PACK / "README.md").write_text(build_readme(manifest), encoding="utf-8")

    print(f"wrote isolated audition pack: {PACK}", flush=True)
    for candidate in runtime_candidates:
        print(
            f"{candidate['name']}: sha256={candidate['sha256']} unstable={candidate['unstable_rows']} nonfinite={candidate['nonfinite_rows']} maxr={candidate['max_pole_radius']:.9f}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
