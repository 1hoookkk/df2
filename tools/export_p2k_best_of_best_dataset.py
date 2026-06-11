#!/usr/bin/env python3
"""Export selected recovered P2K fixtures as a study-only machine-readable corpus.

The exact packed words are the oracle. Any pole/zero, stability, or response
fields are explicitly runtime-derived analysis produced through trench-core's
packed FFI. They are useful for study and comparison, not shippable authoring
templates.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.constants import SR  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db  # noqa: E402
from pyruntime import trench_ffi  # noqa: E402


OUT = ROOT / "ref" / "p2k_variants" / "study_best_of_best"
P2K = ROOT / "ref" / "p2k_variants"
CORNER_LABELS = ("M0_S0", "M1_S0", "M0_S1", "M1_S1")
CORNER_COORDS = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
GRID = tuple(round(i * 0.25, 2) for i in range(5))
FREQS = np.logspace(np.log10(30.0), np.log10(18000.0), 192)
EPS = 1e-12
COMPACT_STATES = frozenset(
    {
        "M000_S000",
        "M100_S000",
        "M000_S100",
        "M100_S100",
        "M050_S050",
    }
)

PRESETS = (
    "P2k_005_klub_klassik",
    "P2k_009_tb_or_not_tb",
    "P2k_015_dj_alkaline",
    "P2k_018_razor_blades",
    "P2k_022_deep_bouche",
    "P2k_025_angelz_hairz",
    "P2k_029_lucifer_s_q",
    "P2k_031_ear_bender",
    "P2k_000_ace_of_bass",
    "P2k_001_megasweepz",
    "P2k_003_millennium",
    "P2k_004_meaty_gizmo",
)

FAVOURITE_PRESETS = (
    "P2k_005_klub_klassik",
    "P2k_009_tb_or_not_tb",
    "P2k_015_dj_alkaline",
    "P2k_018_razor_blades",
    "P2k_022_deep_bouche",
    "P2k_025_angelz_hairz",
    "P2k_029_lucifer_s_q",
    "P2k_031_ear_bender",
    "P2k_001_megasweepz",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def rounded_or_none(value: float, digits: int = 9) -> float | None:
    return round(float(value), digits) if math.isfinite(value) else None


def read_words(body: bytes) -> list[list[list[int]]]:
    if len(body) != trench_ffi.BODY_BYTES:
        raise ValueError(f"body must be {trench_ffi.BODY_BYTES} bytes, got {len(body)}")
    words = np.frombuffer(body, dtype="<u2").reshape(4, 6, 5)
    return words.astype(np.uint16).tolist()


def state_label(morph: float, secondary: float) -> str:
    return f"M{int(round(morph * 100)):03d}_S{int(round(secondary * 100)):03d}"


def angle_hz(root: complex) -> float:
    angle = abs(math.atan2(root.imag, root.real))
    return angle * SR / (2.0 * math.pi)


def roots_of(coeffs: Iterable[float]) -> list[complex]:
    values = np.asarray(tuple(coeffs), dtype=np.float64)
    while len(values) > 1 and abs(values[0]) < EPS:
        values = values[1:]
    if len(values) <= 1:
        return []
    return [complex(root) for root in np.roots(values)]


def classify_roots(roots: list[complex]) -> str:
    if not roots:
        return "none"
    if len(roots) == 1:
        return "first_order"
    if all(abs(root.imag) < 1e-8 for root in roots):
        return "real_pair"
    if abs(roots[0].imag + roots[1].imag) < 1e-6:
        return "complex_pair"
    return "mixed"


def representative_root(roots: list[complex]) -> complex | None:
    if not roots:
        return None
    positive_imag = [root for root in roots if root.imag >= 0.0]
    return max(positive_imag or roots, key=lambda root: abs(root))


def root_record(roots: list[complex], kind: str) -> dict[str, Any]:
    representative = representative_root(roots)
    if representative is None:
        return {
            "kind": kind,
            "frequency_hz": None,
            "radius": None,
            "roots": [],
        }
    return {
        "kind": kind,
        "frequency_hz": rounded_or_none(angle_hz(representative), 6),
        "radius": rounded_or_none(abs(representative), 9),
        "roots": [
            {
                "real": rounded_or_none(root.real, 12),
                "imag": rounded_or_none(root.imag, 12),
                "radius": rounded_or_none(abs(root), 12),
                "frequency_hz": rounded_or_none(angle_hz(root), 6),
            }
            for root in roots
        ],
    }


def stage_analysis(stage_index: int, biquad: tuple[float, ...]) -> dict[str, Any]:
    b0, b1, b2, a1, a2 = (float(value) for value in biquad)
    poles = roots_of((1.0, a1, a2))
    zeros = roots_of((b0, b1, b2))
    pole = root_record(poles, classify_roots(poles))
    zero = root_record(zeros, classify_roots(zeros))
    pole_radius = pole["radius"]
    pole_hz = pole["frequency_hz"]
    zero_hz = zero["frequency_hz"]
    pole_bw_hz = None
    zero_offset_octaves = None
    if pole_radius is not None and 0.0 < pole_radius < 1.0:
        pole_bw_hz = rounded_or_none(-SR / math.pi * math.log(pole_radius), 6)
    if pole_hz is not None and zero_hz is not None and pole_hz > 0.0 and zero_hz > 0.0:
        zero_offset_octaves = rounded_or_none(math.log2(zero_hz / pole_hz), 9)
    return {
        "stage": stage_index,
        "biquad": [rounded_or_none(value, 12) for value in (b0, b1, b2, a1, a2)],
        "pole": pole,
        "zero": zero,
        "pole_bandwidth_hz": pole_bw_hz,
        "zero_offset_octaves": zero_offset_octaves,
        "gain_b0": rounded_or_none(b0, 12),
    }


def state_analysis(body: bytes, morph: float, secondary: float) -> dict[str, Any]:
    kernels = trench_ffi.packed_interpolate(body, morph, secondary)
    probe = trench_ffi.packed_probe(body, morph, secondary)
    stages = [
        stage_analysis(stage_index, tuple(biquad))
        for stage_index, biquad in enumerate(probe["biquad"])
    ]
    response = cascade_response_db([EncodedCoeffs(*row) for row in kernels], FREQS, SR)
    return {
        "state": state_label(morph, secondary),
        "morph": morph,
        "secondary": secondary,
        "kernel": [[rounded_or_none(value, 12) for value in row] for row in kernels],
        "stages": stages,
        "max_pole_radius": rounded_or_none(probe["max_pole_radius"], 12),
        "unstable_mask": int(probe["unstable_mask"]),
        "nonfinite_mask": int(probe["nonfinite_mask"]),
        "response_db": [round(float(value), 6) for value in response],
    }


def variant_key(path: Path) -> tuple[int, int]:
    match = re.fullmatch(r"variant_(\d+)_dat_(\d+)\.bin", path.name)
    if not match:
        raise ValueError(f"unexpected variant filename: {path.name}")
    return int(match.group(1)), int(match.group(2))


def flatten_state_csv(
    writer: csv.DictWriter,
    preset: str,
    variant: int,
    dat_index: int,
    analysis: dict[str, Any],
) -> None:
    for stage in analysis["stages"]:
        pole = stage["pole"]
        zero = stage["zero"]
        writer.writerow(
            {
                "preset": preset,
                "variant": variant,
                "dat_index": dat_index,
                "state": analysis["state"],
                "morph": analysis["morph"],
                "secondary": analysis["secondary"],
                "stage": stage["stage"],
                "pole_kind": pole["kind"],
                "pole_hz": pole["frequency_hz"],
                "pole_radius": pole["radius"],
                "pole_bandwidth_hz": stage["pole_bandwidth_hz"],
                "zero_kind": zero["kind"],
                "zero_hz": zero["frequency_hz"],
                "zero_radius": zero["radius"],
                "zero_offset_octaves": stage["zero_offset_octaves"],
                "gain_b0": stage["gain_b0"],
                "max_state_pole_radius": analysis["max_pole_radius"],
                "unstable_mask": analysis["unstable_mask"],
                "nonfinite_mask": analysis["nonfinite_mask"],
            }
        )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    body_records: list[dict[str, Any]] = []
    curve_records: list[dict[str, Any]] = []
    body_index: list[dict[str, Any]] = []
    compact_records: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}

    stage_csv_path = OUT / "sampled_cavities.csv"
    with stage_csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        fields = [
            "preset",
            "variant",
            "dat_index",
            "state",
            "morph",
            "secondary",
            "stage",
            "pole_kind",
            "pole_hz",
            "pole_radius",
            "pole_bandwidth_hz",
            "zero_kind",
            "zero_hz",
            "zero_radius",
            "zero_offset_octaves",
            "gain_b0",
            "max_state_pole_radius",
            "unstable_mask",
            "nonfinite_mask",
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()

        for preset in PRESETS:
            preset_dir = P2K / preset
            if not preset_dir.is_dir():
                raise FileNotFoundError(f"missing preset directory: {preset_dir}")

            variant_files = sorted(preset_dir.glob("variant_*_dat_*.bin"), key=variant_key)
            if len(variant_files) != 4:
                raise ValueError(f"{preset}: expected 4 variants, got {len(variant_files)}")

            for variant_path in variant_files:
                variant, dat_index = variant_key(variant_path)
                body = variant_path.read_bytes()
                if len(body) != trench_ffi.BODY_BYTES:
                    raise ValueError(f"{variant_path}: expected 240 bytes, got {len(body)}")

                digest = sha256(body)
                duplicate_of = seen_hashes.get(digest)
                seen_hashes.setdefault(digest, str(variant_path.relative_to(ROOT)))
                states = []

                for morph in GRID:
                    for secondary in GRID:
                        analysis = state_analysis(body, morph, secondary)
                        flatten_state_csv(writer, preset, variant, dat_index, analysis)
                        curve_records.append(
                            {
                                "preset": preset,
                                "variant": variant,
                                "dat_index": dat_index,
                                "state": analysis["state"],
                                "morph": morph,
                                "secondary": secondary,
                                "response_db": analysis["response_db"],
                            }
                        )
                        states.append(
                            {
                                key: value
                                for key, value in analysis.items()
                                if key != "response_db"
                            }
                        )

                body_record = {
                    "preset": preset,
                    "variant": variant,
                    "dat_index": dat_index,
                    "source_file": str(variant_path.relative_to(ROOT)),
                    "bytes": len(body),
                    "sha256": digest,
                    "duplicate_of": duplicate_of,
                    "bytes_hex": body.hex(),
                    "packed_words": {
                        label: rows
                        for label, rows in zip(CORNER_LABELS, read_words(body))
                    },
                    "sampled_states": states,
                }
                body_records.append(body_record)
                compact_records.append(
                    {
                        "preset": preset,
                        "variant": variant,
                        "dat_index": dat_index,
                        "source_file": str(variant_path.relative_to(ROOT)),
                        "sha256": digest,
                        "states": [
                            {
                                "state": state["state"],
                                "morph": state["morph"],
                                "secondary": state["secondary"],
                                "max_pole_radius": state["max_pole_radius"],
                                "unstable_mask": state["unstable_mask"],
                                "nonfinite_mask": state["nonfinite_mask"],
                                "cavities": [
                                    {
                                        "stage": stage["stage"],
                                        "pole_hz": stage["pole"]["frequency_hz"],
                                        "pole_radius": stage["pole"]["radius"],
                                        "pole_bandwidth_hz": stage["pole_bandwidth_hz"],
                                        "pole_kind": stage["pole"]["kind"],
                                        "zero_hz": stage["zero"]["frequency_hz"],
                                        "zero_radius": stage["zero"]["radius"],
                                        "zero_kind": stage["zero"]["kind"],
                                        "zero_offset_octaves": stage["zero_offset_octaves"],
                                        "gain_b0": stage["gain_b0"],
                                    }
                                    for stage in state["stages"]
                                ],
                            }
                            for state in states
                            if state["state"] in COMPACT_STATES
                        ],
                    }
                )
                body_index.append(
                    {
                        "preset": preset,
                        "variant": variant,
                        "dat_index": dat_index,
                        "source_file": str(variant_path.relative_to(ROOT)),
                        "bytes": len(body),
                        "sha256": digest,
                        "duplicate_of": duplicate_of,
                    }
                )

    with (OUT / "exact_packed_bodies.jsonl").open("w", encoding="utf-8") as handle:
        for record in body_records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    with (OUT / "response_curves.jsonl").open("w", encoding="utf-8") as handle:
        for record in curve_records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    compact_evidence = {
        "format": "df2-p2k-study-compact-algorithm-evidence-v1",
        "status": "study-only-reference",
        "warning": (
            "Compact runtime-derived view for algorithm research. Exact fixture bytes "
            "remain the oracle. Do not ship or treat as an original template."
        ),
        "representative_states": sorted(COMPACT_STATES),
        "bodies": compact_records,
    }
    (OUT / "compact_algorithm_evidence.json").write_text(
        json.dumps(compact_evidence, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    all_sampled_cavities = [
        cavity
        for body in compact_records
        for state in body["states"]
        for cavity in state["cavities"]
    ]

    def quantiles(field: str) -> dict[str, float | None]:
        values = [
            float(cavity[field])
            for cavity in all_sampled_cavities
            if cavity[field] is not None and math.isfinite(float(cavity[field]))
        ]
        if not values:
            return {"p10": None, "p50": None, "p90": None}
        return {
            label: round(float(np.quantile(values, q)), 6)
            for label, q in (("p10", 0.10), ("p50", 0.50), ("p90", 0.90))
        }

    algorithm_digest = {
        "format": "df2-p2k-study-algorithm-digest-v1",
        "status": "study-only-reference",
        "warning": (
            "Runtime-derived behavioral digest for algorithm research. Exact fixture "
            "bytes remain the oracle. Do not ship or reconstruct these bodies."
        ),
        "scope": {
            "selected_presets": len(PRESETS),
            "variants_analyzed_for_global_counts": len(compact_records),
            "representative_rows": "variant 0 only; four endpoints plus center",
        },
        "global_summary": {
            "sampled_cavity_rows": len(all_sampled_cavities),
            "rows_with_zero": sum(cavity["zero_kind"] != "none" for cavity in all_sampled_cavities),
            "rows_with_complex_zero_pair": sum(
                cavity["zero_kind"] == "complex_pair" for cavity in all_sampled_cavities
            ),
            "pole_radius": quantiles("pole_radius"),
            "pole_bandwidth_hz": quantiles("pole_bandwidth_hz"),
            "zero_radius": quantiles("zero_radius"),
            "zero_offset_octaves": quantiles("zero_offset_octaves"),
        },
        "representative_bodies": [
            {
                "preset": body["preset"],
                "variant": body["variant"],
                "dat_index": body["dat_index"],
                "sha256": body["sha256"],
                "states": body["states"],
            }
            for body in compact_records
            if body["variant"] == 0
        ],
    }
    (OUT / "algorithm_evidence_digest.json").write_text(
        json.dumps(algorithm_digest, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    prompt_detail_presets = {
        "P2k_000_ace_of_bass",
        "P2k_001_megasweepz",
        "P2k_018_razor_blades",
        "P2k_022_deep_bouche",
    }

    def prompt_state_summary(state: dict) -> list:
        return [
            state["state"],
            state["morph"],
            state["secondary"],
            state["max_pole_radius"],
            state["unstable_mask"],
            state["nonfinite_mask"],
        ]

    def prompt_state_detail(state: dict) -> list:
        return prompt_state_summary(state) + [
            [
                [
                    cavity["stage"],
                    cavity["pole_hz"],
                    cavity["pole_radius"],
                    cavity["pole_bandwidth_hz"],
                    cavity["pole_kind"],
                    cavity["zero_hz"],
                    cavity["zero_radius"],
                    cavity["zero_kind"],
                    cavity["zero_offset_octaves"],
                    cavity["gain_b0"],
                ]
                for cavity in state["cavities"]
            ]
        ]

    prompt_variant0_bodies = [body for body in compact_records if body["variant"] == 0]
    algorithm_prompt_digest = {
        "format": "df2-p2k-study-algorithm-prompt-digest-v2",
        "status": "study-only-reference",
        "warning": "Behavior study only. Exact bytes remain oracle. Never ship or reconstruct.",
        "legend": {
            "summaryState": "[state,morph,secondary,maxPoleRadius,unstableMask,nonfiniteMask]",
            "detailState": "[state,morph,secondary,maxPoleRadius,unstableMask,nonfiniteMask,cavities]",
            "cavity": (
                "[stage,poleHz,poleRadius,poleBandwidthHz,poleKind,"
                "zeroHz,zeroRadius,zeroKind,zeroOffsetOctaves,gainB0]"
            ),
        },
        "global_summary": algorithm_digest["global_summary"],
        "variant0_body_summaries": [
            [
                body["preset"],
                body["dat_index"],
                body["sha256"],
                [prompt_state_summary(state) for state in body["states"]],
            ]
            for body in prompt_variant0_bodies
        ],
        "detailed_variant0_bodies": [
            [
                body["preset"],
                body["dat_index"],
                body["sha256"],
                [prompt_state_detail(state) for state in body["states"]],
            ]
            for body in prompt_variant0_bodies
            if body["preset"] in prompt_detail_presets
        ],
    }
    (OUT / "algorithm_prompt_digest.json").write_text(
        json.dumps(algorithm_prompt_digest, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    llm_clarity_pack = {
        "format": "df2-p2k-llm-clarity-pack-v1",
        "status": "study-only-reference",
        "warning": (
            "Behavior study only. Exact bytes remain the oracle. Use this derived "
            "analysis to identify relationships, not to ship or reconstruct presets."
        ),
        "runtime_truth": [
            "Each P2K preset is one verbatim 240-byte packed body.",
            "Layout: 4 corners x 6 persistent serialized stage lanes x 5 u16 words.",
            "Corner order: M0_S0, M1_S0, M0_S1, M1_S1.",
            "Runtime behavior is live morph-first packed-u16 bilinear interpolation.",
            "The sound lives in the continuous trajectory between stored corners.",
            "Lane N only interpolates against lane N. Never silently re-sort by frequency.",
            "Each lane contains its own poles, zeros, and gain. A zero is not a separate lane.",
        ],
        "creative_goal": (
            "Identify a small human-usable vocabulary of relationship gestures for "
            "authoring original four-corner bodies by hand. A gesture may populate "
            "ordinary editable corners, then disappear. Do not propose a new runtime type."
        ),
        "seed_hypothesis": (
            "Contrary Vocal: two persistent formant lanes move in opposing directions "
            "while their zeros preserve or deepen a hollow center. Treat this as a "
            "creative hypothesis to test against the evidence, not as a proven recipe."
        ),
        "analysis_request": [
            "Explain the recurring pole, zero, gain, and lane-trajectory relationships in plain language.",
            "Separate measured evidence from creative hypotheses.",
            "Identify what distinguishes coherent musical motion from midpoint mush.",
            "Identify what creates controlled destruction without instability or excessive heat.",
            "Propose 3 to 5 named authoring gestures at the same level as Contrary Vocal.",
            "For each gesture, describe six lane roles, Morph motion, Secondary intensification, and midpoint listening tests.",
            "Prefer relative relationships. Do not invent unsupported fixed-frequency recipes.",
            "Do not propose constructors, Bezier trajectories, physical modeling, or architecture refactors.",
        ],
        "legend": algorithm_prompt_digest["legend"],
        "global_summary": algorithm_digest["global_summary"],
        "favourite_variant0_bodies": [
            [
                body["preset"],
                body["dat_index"],
                body["sha256"],
                [prompt_state_detail(state) for state in body["states"]],
            ]
            for body in prompt_variant0_bodies
            if body["preset"] in FAVOURITE_PRESETS
        ],
    }
    (OUT / "llm_clarity_pack.json").write_text(
        json.dumps(llm_clarity_pack, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with (OUT / "body_index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=body_index[0].keys())
        writer.writeheader()
        writer.writerows(body_index)

    frequency_grid = {
        "sample_rate_hz": SR,
        "frequency_grid_hz": [round(float(value), 6) for value in FREQS],
    }
    (OUT / "frequency_grid.json").write_text(
        json.dumps(frequency_grid, indent=2) + "\n",
        encoding="utf-8",
    )

    duplicate_count = sum(1 for record in body_index if record["duplicate_of"])
    manifest = {
        "format": "df2-p2k-study-best-of-best-v1",
        "status": "study-only-reference",
        "clean_room_boundary": (
            "Recovered third-party fixture bytes and runtime-derived analysis. "
            "Inspect for behavioral study only. Do not ship coefficients, packed words, "
            "bytes, preset names, extracted templates, or direct derivatives."
        ),
        "oracle": (
            "exact .bin bytes -> trench_core PackedCorners packed-u16 morph-first "
            "bilinear interpolation -> decode -> DF2T biquad cascade"
        ),
        "derived_analysis_warning": (
            "Pole/zero roots, frequencies, radii, response curves, and sampled state "
            "records are runtime-derived analysis. Exact packed words remain the oracle."
        ),
        "layout": {
            "body_bytes": trench_ffi.BODY_BYTES,
            "corners": 4,
            "corner_order": list(CORNER_LABELS),
            "stages_per_corner": trench_ffi.NUM_STAGES,
            "packed_words_per_stage": trench_ffi.NUM_COEFFS,
            "sample_rate_hz": SR,
        },
        "selection": list(PRESETS),
        "counts": {
            "presets": len(PRESETS),
            "variants_per_preset": 4,
            "bodies": len(body_records),
            "sampled_states_per_body": len(GRID) * len(GRID),
            "sampled_stage_rows": len(body_records) * len(GRID) * len(GRID) * trench_ffi.NUM_STAGES,
            "curve_records": len(curve_records),
            "duplicate_bodies": duplicate_count,
        },
        "files": {
            "exact_packed_bodies_jsonl": "exact_packed_bodies.jsonl",
            "body_index_csv": "body_index.csv",
            "sampled_cavities_csv": "sampled_cavities.csv",
            "frequency_grid_json": "frequency_grid.json",
            "response_curves_jsonl": "response_curves.jsonl",
            "compact_algorithm_evidence_json": "compact_algorithm_evidence.json",
            "algorithm_evidence_digest_json": "algorithm_evidence_digest.json",
            "algorithm_prompt_digest_json": "algorithm_prompt_digest.json",
            "llm_clarity_pack_json": "llm_clarity_pack.json",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    readme = """# P2K Best-Of-Best Study Corpus

Study-only recovered reference data. Do not ship it.

The exact `.bin` bytes and their packed words are the oracle. Analysis fields
are derived by loading those exact bytes through `trench_core`'s packed runtime
FFI at a `5 x 5` `MORPH x SECONDARY` grid. This preserves numerator and
denominator behavior: every sampled stage reports both poles and zeros.

Files:

- `exact_packed_bodies.jsonl`: lossless records, packed words, hashes, and
  sampled runtime-derived cavity analysis.
- `body_index.csv`: compact inventory.
- `sampled_cavities.csv`: flat analysis table for clustering and comparison.
- `frequency_grid.json`: frequency axis shared by every response curve.
- `response_curves.jsonl`: packed-runtime response arrays for plot tooling.
- `compact_algorithm_evidence.json`: endpoint-plus-center cavity view sized for
  a focused analysis prompt.
- `algorithm_evidence_digest.json`: smaller analytical digest for token-limited
  model runs.
- `algorithm_prompt_digest.json`: tuple-compressed digest for the focused Pro
  prompt.
- `llm_clarity_pack.json`: single-upload prompt context for relationship-level
  design analysis across the nine favorite bodies.
- `manifest.json`: layout, counts, provenance boundary, and file map.

The raw fixture bytes remain under `ref/p2k_variants/P2k_*`. This export is a
machine-readable study view, not an original-authoring library.
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    print(f"wrote {OUT}")
    print(json.dumps(manifest["counts"], indent=2))


if __name__ == "__main__":
    main()
