#!/usr/bin/env python3
"""Study the selected packed P2K reference fixtures without authoring from them.

The outputs are study-only. They expose aggregate behavior and comparative plots
for clean-room design research. They must never be used as shippable templates.
"""
from __future__ import annotations

import csv
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi
from tools.audit_generated_presets import analyze_body, response_db, state_metrics

SOURCE = ROOT / "ref" / "p2k_variants" / "study_best_of_best"
OUT = ROOT / "dev" / "tmp" / "p2k_reference_grammar"
FREQS = np.logspace(math.log10(40.0), math.log10(16000.0), 512)

FIELD = "#090d0c"
INK = "#c6cec8"
MUTED = "#819087"
GRID = "#17211d"
SPINE = "#46564e"
GREEN = "#56ed70"
AMBER = "#e6a13b"
RED = "#ee493c"
CYAN = "#2fc8cc"
STAGE_COLORS = ["#56ed70", "#2fc8cc", "#e6a13b", "#ff873c", "#ee493c", "#aa78ff"]


def compact_name(preset: str) -> str:
    return preset.removeprefix("P2k_")


def load_records() -> list[dict]:
    records = []
    for line in (SOURCE / "exact_packed_bodies.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        record["body"] = bytes.fromhex(record.pop("bytes_hex"))
        record["role"] = "selected"
        records.append(record)
    return records


def load_calibration_records() -> list[dict]:
    records = []
    preset = "P2k_013_talking_hedz"
    for path in sorted((ROOT / "ref" / "p2k_variants" / preset).glob("variant_*_dat_*.bin")):
        match = re.fullmatch(r"variant_(\d+)_dat_(\d+)\.bin", path.name)
        if not match:
            continue
        records.append({
            "preset": preset,
            "variant": int(match.group(1)),
            "dat_index": int(match.group(2)),
            "source_file": str(path.relative_to(ROOT)),
            "body": path.read_bytes(),
            "role": "calibration",
        })
    return records


def load_flat_rows() -> list[dict]:
    with (SOURCE / "sampled_cavities.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def quantiles(values: list[float]) -> dict:
    if not values:
        return {"p10": None, "p25": None, "p50": None, "p75": None, "p90": None}
    return {
        key: round(float(np.quantile(values, q)), 6)
        for key, q in (("p10", 0.10), ("p25", 0.25), ("p50", 0.50),
                       ("p75", 0.75), ("p90", 0.90))
    }


def close_zero_fractions(body: bytes) -> dict:
    positions = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
    total = 0
    close_half = 0
    close_one = 0
    remote = 0
    offsets = []
    for morph, secondary in positions:
        for stage in state_metrics(body, morph, secondary)["stages"]:
            if not stage.get("active") or stage.get("zero_kind") == "none":
                continue
            offset = stage.get("zero_offset_octaves")
            if offset is None:
                continue
            total += 1
            offsets.append(abs(float(offset)))
            close_half += abs(offset) <= 0.5
            close_one += abs(offset) <= 1.0
            remote += abs(offset) > 1.5
    return {
        "stages": total,
        "close_half_octave_fraction": close_half / max(1, total),
        "close_one_octave_fraction": close_one / max(1, total),
        "remote_over_1_5_octaves_fraction": remote / max(1, total),
        "abs_offset_octaves": quantiles(offsets),
    }


def metrics_for(record: dict) -> dict:
    metrics = analyze_body(record["body"])
    offsets = close_zero_fractions(record["body"])
    return {
        "preset": record["preset"],
        "variant": record["variant"],
        "dat_index": record["dat_index"],
        "role": record["role"],
        **metrics,
        **offsets,
    }


def mean(rows: list[dict], key: str) -> float:
    vals = [float(row[key]) for row in rows if row.get(key) is not None]
    return float(np.mean(vals)) if vals else 0.0


def med(rows: list[dict], key: str) -> float:
    vals = [float(row[key]) for row in rows if row.get(key) is not None]
    return float(np.median(vals)) if vals else 0.0


def aggregate_variant_scale(flat_rows: list[dict]) -> dict:
    endpoints = {"M000_S000", "M100_S000", "M000_S100", "M100_S100"}
    base = {}
    for row in flat_rows:
        if row["state"] in endpoints and row["variant"] == "0" and row["pole_hz"]:
            base[(row["preset"], row["state"], row["stage"])] = float(row["pole_hz"])
    ratios = defaultdict(list)
    for row in flat_rows:
        if row["state"] not in endpoints or not row["pole_hz"]:
            continue
        denom = base.get((row["preset"], row["state"], row["stage"]))
        if denom:
            ratios[int(row["variant"])].append(float(row["pole_hz"]) / denom)
    return {
        str(variant): {
            "median_frequency_ratio_vs_variant0": round(statistics.median(values), 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
        }
        for variant, values in sorted(ratios.items())
    }


def preset_summary(all_metrics: list[dict]) -> list[dict]:
    by_preset = defaultdict(list)
    for row in all_metrics:
        by_preset[row["preset"]].append(row)
    summary = []
    for preset, rows in sorted(by_preset.items()):
        representative = next(row for row in rows if row["variant"] == 0)
        summary.append({
            "preset": preset,
            "role": rows[0]["role"],
            "variants": len(rows),
            "all_variants_stable": all(row["stable"] and row["finite"] for row in rows),
            "close_zero_fraction_half_octave": round(mean(rows, "close_half_octave_fraction"), 4),
            "close_zero_fraction_one_octave": round(mean(rows, "close_one_octave_fraction"), 4),
            "remote_zero_fraction_over_1_5_octaves": round(mean(rows, "remote_over_1_5_octaves_fraction"), 4),
            "zero_motion_error_octaves": round(mean(rows, "zero_motion_error_octaves_mean"), 4),
            "morph_contrast_rms_db": round(mean(rows, "morph_contrast_rms_db"), 3),
            "secondary_contrast_rms_db": round(mean(rows, "secondary_contrast_rms_db"), 3),
            "center_span_db": round(mean(rows, "center_span_db"), 3),
            "center_sag_db": round(mean(rows, "center_sag_db"), 3),
            "endpoint_collisions_lt_200hz": round(mean(rows, "endpoint_collisions_lt_200hz"), 3),
            "center_collisions_lt_200hz": round(mean(rows, "center_collisions_lt_200hz"), 3),
            "center_response_peaks": round(mean(rows, "center_response_peaks"), 3),
            "center_response_valleys": round(mean(rows, "center_response_valleys"), 3),
            "variant0": {
                key: representative[key]
                for key in (
                    "max_pole_radius", "endpoint_zero_fraction",
                    "endpoint_close_paired_zero_fraction", "zero_motion_error_octaves_mean",
                    "morph_contrast_rms_db", "secondary_contrast_rms_db",
                    "center_span_db", "center_sag_db",
                    "endpoint_collisions_lt_200hz", "center_collisions_lt_200hz",
                    "center_response_peaks", "center_response_valleys",
                )
            },
        })
    return summary


def style(ax) -> None:
    ax.set_facecolor(FIELD)
    ax.grid(True, color=GRID, linewidth=0.45)
    ax.tick_params(colors=INK, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(SPINE)


def one_stage_response_db(row: tuple[float, ...]) -> np.ndarray:
    b0, b1, b2, a1, a2 = row
    w = 2.0 * math.pi * FREQS / 39062.5
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    h = (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-30))


def band_median(curve: np.ndarray, lo: float, hi: float) -> float:
    return float(np.median(curve[(FREQS >= lo) & (FREQS <= hi)]))


def foundation_analysis(record: dict) -> dict:
    state = state_metrics(record["body"], 0.0, 0.0)
    rows = trench_ffi.packed_probe(record["body"], 0.0, 0.0)["biquad"]
    stages = []
    for index, (row, roots) in enumerate(zip(rows, state["stages"])):
        curve = one_stage_response_db(row)
        low = band_median(curve, 60.0, 180.0)
        mid = band_median(curve, 500.0, 1800.0)
        high = band_median(curve, 6000.0, 14000.0)
        span = float(np.max(curve) - np.min(curve))
        stages.append({
            "stage": index,
            "pole_kind": roots.get("pole_kind"),
            "zero_kind": roots.get("zero_kind"),
            "pole_hz": roots.get("pole_hz"),
            "zero_hz": roots.get("zero_hz"),
            "low_db": round(low, 3),
            "mid_db": round(mid, 3),
            "high_db": round(high, 3),
            "high_minus_low_db": round(high - low, 3),
            "span_db": round(span, 3),
        })
    strongest = max(stages, key=lambda stage: abs(stage["high_minus_low_db"]))
    broad = [
        stage for stage in stages
        if abs(stage["high_minus_low_db"]) >= 8.0 or stage["span_db"] >= 24.0
    ]
    cascade = response_db(rows)
    cascade_tilt = band_median(cascade, 6000.0, 14000.0) - band_median(cascade, 60.0, 180.0)
    if strongest["pole_kind"] == "real_pair" or strongest["zero_kind"] == "real_pair":
        method = "real-root slope / shelf foundation"
    elif abs(strongest["high_minus_low_db"]) >= 12.0:
        method = "broad complex-pair tilt foundation"
    elif len(broad) >= 2:
        method = "distributed broad-stage foundation"
    else:
        method = "clustered cavity field; no single dominant foundation stage"
    return {
        "preset": record["preset"],
        "role": record["role"],
        "method_heuristic": method,
        "cascade_high_minus_low_db": round(cascade_tilt, 3),
        "strongest_foundation_stage": strongest["stage"],
        "strongest_stage_high_minus_low_db": strongest["high_minus_low_db"],
        "broad_stage_count": len(broad),
        "stages": stages,
    }


def plot_foundations(records: list[dict], path: Path) -> list[dict]:
    representative = [record for record in records if record["variant"] == 0]
    analyses = [foundation_analysis(record) for record in representative]
    fig, axes = plt.subplots(5, 3, figsize=(15, 18.3), facecolor=FIELD)
    for ax, record, analysis in zip(axes.flat, representative, analyses):
        style(ax)
        ax.set_xscale("log")
        ax.set_xlim(FREQS[0], FREQS[-1])
        rows = trench_ffi.packed_probe(record["body"], 0.0, 0.0)["biquad"]
        curves = []
        for index, row in enumerate(rows):
            curve = one_stage_response_db(row)
            curves.append(curve)
            width = 2.1 if index == analysis["strongest_foundation_stage"] else 0.9
            alpha = 1.0 if index == analysis["strongest_foundation_stage"] else 0.72
            ax.plot(FREQS, curve, color=STAGE_COLORS[index], linewidth=width,
                    alpha=alpha, label=f"S{index + 1}")
        cascade = response_db(rows)
        ax.plot(FREQS, cascade, color="#f2f4ef", linewidth=1.4, label="CASCADE")
        ylo = max(-100.0, min(float(np.min(curve)) for curve in curves + [cascade]) - 4.0)
        yhi = min(80.0, max(float(np.max(curve)) for curve in curves + [cascade]) + 4.0)
        ax.set_ylim(ylo, yhi)
        suffix = "  [CAL]" if record["role"] == "calibration" else ""
        ax.set_title(compact_name(record["preset"]) + suffix, color=INK, fontsize=8.7,
                     family="monospace")
        ax.text(0.02, 0.035, analysis["method_heuristic"],
                color=MUTED, fontsize=6.2, family="monospace", transform=ax.transAxes)
        ax.legend(facecolor="#111610", edgecolor=SPINE, labelcolor=INK,
                  fontsize=5.5, ncol=4, loc="upper right")
    for ax in axes.flat[len(representative):]:
        ax.set_axis_off()
    fig.suptitle(
        "M0/S0 FOUNDATION DECOMPOSITION  variant 0\n"
        "white=cascade  colored=individual serialized stages  thick colored line=largest broad tilt contribution\n"
        "labels are study heuristics: inspect construction method, never treat as shippable templates",
        color=INK, fontsize=10, family="monospace", y=0.995,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(path, dpi=145, facecolor=FIELD)
    plt.close(fig)
    return analyses


def plot_response_overview(records: list[dict], path: Path) -> None:
    representative = [record for record in records if record["variant"] == 0]
    fig, axes = plt.subplots(5, 3, figsize=(15, 18.3), facecolor=FIELD)
    for ax, record in zip(axes.flat, representative):
        style(ax)
        ax.set_xscale("log")
        ax.set_xlim(FREQS[0], FREQS[-1])
        states = [
            ("M0/S0", 0.0, 0.0, GREEN),
            ("CENTER", 0.5, 0.5, AMBER),
            ("M1/S1", 1.0, 1.0, RED),
        ]
        curves = []
        for label, morph, secondary, color in states:
            curve = response_db(trench_ffi.packed_probe(record["body"], morph, secondary)["biquad"])
            curves.append(curve)
            ax.plot(FREQS, curve, color=color, linewidth=1.25, label=label)
        yhi = min(80.0, max(float(np.max(curve)) for curve in curves) + 5.0)
        ylo = max(-100.0, min(float(np.min(curve)) for curve in curves) - 5.0)
        ax.set_ylim(ylo, yhi)
        suffix = "  [CALIBRATION]" if record["role"] == "calibration" else ""
        ax.set_title(compact_name(record["preset"]) + suffix, color=INK, fontsize=9,
                     family="monospace")
        ax.legend(facecolor="#111610", edgecolor=SPINE, labelcolor=INK,
                  fontsize=6.5, ncol=3, loc="lower left")
    for ax in axes.flat[len(representative):]:
        ax.set_axis_off()
    fig.suptitle(
        "P2K SELECTED REFERENCE STUDY  variant 0  |  packed runtime curves  |  "
        "green M0/S0  amber center  red M1/S1\n"
        "study-only reference material: inspect behavior, never ship coefficients or direct derivatives",
        color=INK, fontsize=10, family="monospace", y=0.995,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(path, dpi=145, facecolor=FIELD)
    plt.close(fig)


def plot_tracks(records: list[dict], path: Path) -> None:
    representative = [record for record in records if record["variant"] == 0]
    fig, axes = plt.subplots(5, 3, figsize=(15, 18.3), facecolor=FIELD)
    for ax, record in zip(axes.flat, representative):
        style(ax)
        ax.set_yscale("log")
        ax.set_ylim(25.0, 18500.0)
        ax.set_xlim(-0.04, 1.04)
        start = state_metrics(record["body"], 0.0, 0.0)["stages"]
        end = state_metrics(record["body"], 1.0, 0.0)["stages"]
        for index, (stage_a, stage_b) in enumerate(zip(start, end)):
            color = STAGE_COLORS[index]
            if stage_a.get("pole_hz") and stage_b.get("pole_hz"):
                ax.plot([0, 1], [stage_a["pole_hz"], stage_b["pole_hz"]],
                        color=color, linewidth=1.5, marker="o", markersize=3.5)
            if stage_a.get("zero_hz") and stage_b.get("zero_hz"):
                ax.plot([0, 1], [stage_a["zero_hz"], stage_b["zero_hz"]],
                        color=color, linewidth=0.9, linestyle="--",
                        marker="x", markersize=4)
        ax.set_xticks([0, 1], ["M0", "M1"])
        suffix = "  [CALIBRATION]" if record["role"] == "calibration" else ""
        ax.set_title(compact_name(record["preset"]) + suffix, color=INK, fontsize=9,
                     family="monospace")
    for ax in axes.flat[len(representative):]:
        ax.set_axis_off()
    fig.suptitle(
        "POLE-ZERO MORPH TRACKS  variant 0 / SECONDARY=0\n"
        "solid circles=poles  dashed x=zeros  |  matching color means same serialized stage slot",
        color=INK, fontsize=10, family="monospace", y=0.995,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(path, dpi=145, facecolor=FIELD)
    plt.close(fig)


def plot_metrics(summary: list[dict], path: Path) -> None:
    columns = [
        ("close_zero_fraction_one_octave", "zero <=1 oct"),
        ("remote_zero_fraction_over_1_5_octaves", "zero >1.5 oct"),
        ("zero_motion_error_octaves", "zero-motion err"),
        ("morph_contrast_rms_db", "morph RMS dB"),
        ("secondary_contrast_rms_db", "secondary RMS dB"),
        ("center_span_db", "center span dB"),
        ("endpoint_collisions_lt_200hz", "endpoint fusions"),
        ("center_response_peaks", "center peaks"),
        ("center_response_valleys", "center valleys"),
    ]
    values = np.array([[float(row[key]) for key, _ in columns] for row in summary])
    lo = np.min(values, axis=0)
    hi = np.max(values, axis=0)
    normalized = (values - lo) / np.maximum(hi - lo, 1e-12)
    fig, ax = plt.subplots(figsize=(15, 7.3), facecolor=FIELD)
    ax.set_facecolor(FIELD)
    image = ax.imshow(normalized, aspect="auto", cmap="magma", vmin=0.0, vmax=1.0)
    ax.set_xticks(range(len(columns)), [label for _, label in columns],
                  rotation=35, ha="right", color=INK, fontsize=8)
    ax.set_yticks(
        range(len(summary)),
        [compact_name(row["preset"]) + (" [CAL]" if row["role"] == "calibration" else "")
         for row in summary],
                  color=INK, fontsize=8)
    for row_index, row in enumerate(values):
        for col_index, value in enumerate(row):
            ax.text(col_index, row_index, f"{value:.2f}", ha="center", va="center",
                    fontsize=7, color="white" if normalized[row_index, col_index] > 0.38 else INK)
    for spine in ax.spines.values():
        spine.set_color(SPINE)
    fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02).ax.tick_params(colors=INK)
    ax.set_title(
        "P2K SELECTED REFERENCE GRAMMAR  all four variants averaged\n"
        "numbers are behavioral metrics; heat is column-relative, not a quality score",
        color=INK, fontsize=10, family="monospace",
    )
    fig.tight_layout()
    fig.savefig(path, dpi=145, facecolor=FIELD)
    plt.close(fig)


def markdown_report(summary: list[dict], global_row: dict, variant_scale: dict) -> str:
    rows = []
    for row in summary:
        rows.append(
            f"| {compact_name(row['preset'])}{' [CAL]' if row['role'] == 'calibration' else ''} | "
            f"{row['close_zero_fraction_one_octave']:.2f} | "
            f"{row['remote_zero_fraction_over_1_5_octaves']:.2f} | "
            f"{row['zero_motion_error_octaves']:.2f} | "
            f"{row['morph_contrast_rms_db']:.1f} | {row['secondary_contrast_rms_db']:.1f} | "
            f"{row['center_span_db']:.1f} | {row['endpoint_collisions_lt_200hz']:.1f} |"
        )
    scale_lines = [
        f"- Variant `{variant}` median pole-frequency ratio versus variant `0`: "
        f"`{details['median_frequency_ratio_vs_variant0']}`."
        for variant, details in variant_scale.items()
    ]
    return f"""# Selected P2K Reference Grammar Study

Study-only recovered reference material. Do not ship coefficients, bytes, preset
names, templates, or direct derivatives.

## Scope

- 12 selected reference families plus Talking Hedz as a labeled calibration fixture.
- 4 packed 240-byte variants per family.
- 52 bodies in the comparison: 48 selected plus 4 Talking Hedz calibration variants.
- 7,200 flattened pole-zero rows for the selected set; Talking Hedz is compared separately.
- Decoder: release `trench_core.dll`, packed-u16 morph-first bilinear path.

## What The Data Settles

1. Zeros are not optional. Every sampled row contains numerator structure:
   `{global_row['rows_with_zero']}` of `{global_row['sampled_rows']}` rows have zeros.
2. "Every zero hugs its pole" is too simple. `{global_row['close_one_octave_fraction']:.1%}`
   of endpoint zeros sit within one octave of their pole, while
   `{global_row['remote_over_1_5_octaves_fraction']:.1%}` sit more than 1.5 octaves away.
   The references combine local peak-notch tears with long-range spectral counterweights.
3. The same serialized stage slot often changes role aggressively across the surface.
   Mean pole-versus-zero movement disagreement is `{global_row['zero_motion_error_octaves']:.2f}`
   octaves. Role registration matters, but rigid pole-zero co-motion is not the observed law.
4. Sub-200 Hz pole fusion is not automatically a bug. The selected references contain it
   at endpoints and use it as one source of broad mass. It needs plot inspection, not a
   universal rejection rule.
5. The four `.bin` variants are mostly scaled frequency variants of the same family grammar:
{chr(10).join(scale_lines)}

## Comparative Metrics

| reference | zero <=1 oct | zero >1.5 oct | zero motion err oct | morph RMS dB | secondary RMS dB | center span dB | endpoint fusions |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## Authoring Doctrine Extracted From The Study

- Start from a six-stage actor program, not six arbitrary EQ peaks.
- Give every active stage numerator structure. Pole-only generators are incomplete.
- Use at least two zero roles:
  - local zeros for a peak-plus-canyon cavity;
  - remote zeros for broad tilt, air caps, low-body excavation, and cross-spectrum tension.
- Keep stage slots intentionally registered across corners, but allow a stage's pole and zero
  to move by different amounts when the macro program requires it.
- Treat collisions as an authored macro. Some are useful broad mountains; some are mush.
  Surface them on the plot and let the author decide.
- Judge the complete four-corner packed surface, especially the center. Endpoint beauty alone
  is insufficient.
- Use physical or acoustic models as actor skeletons, then add deterministic zero-role programs.
  Pure textbook models are too polite; random poles are uncontrolled.

## Files

- `response_overview.png`: response mountains at M0/S0, center, and M1/S1.
- `pole_zero_tracks.png`: stage-slot movement from M0 to M1 at SECONDARY=0.
- `foundations.png`: M0/S0 cascade decomposed into its six individual stages.
- `metrics_heatmap.png`: comparative behavioral metrics.
- `summary.json`: sanitized metrics and extracted laws.
"""


def main() -> None:
    if not trench_ffi.available():
        raise SystemExit("trench-core DLL unavailable; build cargo build -p trench-core --release")
    OUT.mkdir(parents=True, exist_ok=True)
    records = load_records() + load_calibration_records()
    flat_rows = load_flat_rows()
    all_metrics = [metrics_for(record) for record in records]
    summary = preset_summary(all_metrics)
    variant_scale = aggregate_variant_scale(flat_rows)

    offsets = [abs(float(row["zero_offset_octaves"])) for row in flat_rows if row["zero_offset_octaves"]]
    representative_metrics = [row for row in all_metrics if row["variant"] == 0]
    global_row = {
        "sampled_rows": len(flat_rows),
        "rows_with_zero": sum(row["zero_kind"] != "none" for row in flat_rows),
        "complex_zero_rows": sum(row["zero_kind"] == "complex_pair" for row in flat_rows),
        "zero_abs_offset_octaves": quantiles(offsets),
        "close_one_octave_fraction": sum(value <= 1.0 for value in offsets) / max(1, len(offsets)),
        "remote_over_1_5_octaves_fraction": sum(value > 1.5 for value in offsets) / max(1, len(offsets)),
        "zero_motion_error_octaves": med(representative_metrics, "zero_motion_error_octaves_mean"),
        "stable_bodies": sum(row["stable"] and row["finite"] for row in all_metrics),
        "bodies": len(all_metrics),
    }
    laws = [
        "Every active stage needs numerator structure; pole-only generation is incomplete.",
        "Use both local peak-notch zeros and remote spectral counterweight zeros.",
        "Register stage slots intentionally across corners, but do not force rigid pole-zero co-motion.",
        "Treat sub-200 Hz pole fusion as an authored macro surfaced on plots, not a universal reject.",
        "Judge the packed four-corner surface and its center; endpoints alone do not prove the body.",
        "Use physical/acoustic skeletons plus deterministic zero-role programs; do not use random poles.",
    ]
    payload = {
        "format": "df2-p2k-selected-reference-grammar-study-v1",
        "status": "study-only-reference",
        "clean_room_boundary": (
            "Behavioral study only. Do not ship coefficients, bytes, preset names, "
            "templates, or direct derivatives."
        ),
        "global": global_row,
        "variant_frequency_scaling": variant_scale,
        "per_reference": summary,
        "extracted_laws": laws,
    }
    foundations = plot_foundations(records, OUT / "foundations.png")
    payload["foundation_heuristics"] = foundations
    (OUT / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(
        markdown_report(summary, global_row, variant_scale), encoding="utf-8"
    )
    plot_response_overview(records, OUT / "response_overview.png")
    plot_tracks(records, OUT / "pole_zero_tracks.png")
    plot_metrics(summary, OUT / "metrics_heatmap.png")
    print(f"wrote {OUT}")
    print(json.dumps(global_row, indent=2))


if __name__ == "__main__":
    main()
