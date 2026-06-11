#!/usr/bin/env python3
"""Decode X3 fixed-class response shapes and rebuild clean-room body240 archetypes.

This is Forge/manual-authoring study glue, not production training. It reads the
fixed-class runtime blocks as response targets, emits response-derived archetype
recipes, compiles legal six-row `.body240` bodies, and compares response shape
only. It never copies X3 fixed-point words into the output body.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db  # noqa: E402
from src.utils.body240 import (  # noqa: E402
    AUTHORING_SR,
    CORNER_ORDER,
    compiled_payload,
    raw_from_words,
    render_png,
    words_from_kernels,
)

X3_ROOT = ROOT / "ref" / "x3_menu"
MANIFEST = X3_ROOT / "X3_MENU_MANIFEST.json"
OUT_ROOT = ROOT / "dev" / "tmp" / "x3_fixed_cleanroom"

DECODE_SCALE = 16_384.0
DECODE_ORDER = (2, 3, 4, 0, 1)
FIT_FREQS = np.geomspace(45.0, min(16_000.0, AUTHORING_SR * 0.45), 256)
COMPARE_MASK = (FIT_FREQS >= 80.0) & (FIT_FREQS <= 12_000.0)
CORNER_POINTS = {
    "M0_Q0": (0.0, 0.0),
    "M100_Q0": (1.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q100": (1.0, 1.0),
}


@dataclass(frozen=True)
class TargetCorner:
    label: str
    stages: tuple[tuple[float, float, float, float, float], ...]
    response_db: np.ndarray


def slug(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(ch if ch.isalnum() else "_")
    return "_".join(part for part in "".join(out).split("_") if part)


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def fixed_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in manifest["menu"] if entry.get("kind") == "rom_table_class"]


def runtime_snapshot(entry: dict[str, Any], sample_rate: int) -> dict[str, Any]:
    for snapshot in entry["runtime_snapshots"]:
        if int(snapshot["sample_rate"]) == int(sample_rate):
            return snapshot
    raise ValueError(f"{entry['name']}: no runtime snapshot at {sample_rate} Hz")


def decode_words5(words5: tuple[int, int, int, int, int]) -> tuple[float, float, float, float, float]:
    values = [float(w) / DECODE_SCALE for w in words5]
    ordered = [values[index] for index in DECODE_ORDER]
    b0, b1, b2, a1, a2 = ordered
    return b0, b1, b2, a1, a2


def poles_stable(a1: float, a2: float) -> bool:
    return abs(a2) < 0.999 and abs(a1) < 1.0 + a2


def read_target_corners(entry: dict[str, Any], sample_rate: int, freqs: np.ndarray = FIT_FREQS) -> list[TargetCorner]:
    snapshot = runtime_snapshot(entry, sample_rate)
    raw = (ROOT / snapshot["file"]).read_bytes()
    words = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    stages_per_corner = int(entry["output_stages"])
    expected = len(CORNER_ORDER) * stages_per_corner * 5
    if len(words) != expected:
        raise ValueError(f"{entry['name']}: expected {expected} i16 words, got {len(words)}")

    corners = []
    per_corner = stages_per_corner * 5
    for ci, label in enumerate(CORNER_ORDER):
        segment = words[ci * per_corner:(ci + 1) * per_corner]
        stages = []
        for si in range(stages_per_corner):
            words5 = tuple(int(w) for w in segment[si * 5:si * 5 + 5])
            stage = decode_words5(words5)
            stages.append(stage)
        response = target_response_db(stages, freqs, sample_rate)
        corners.append(TargetCorner(label=label, stages=tuple(stages), response_db=response))
    return corners


def target_response_db(
    stages: list[tuple[float, float, float, float, float]] | tuple[tuple[float, float, float, float, float], ...],
    freqs: np.ndarray,
    sample_rate: float,
) -> np.ndarray:
    z = np.exp(-1j * (2.0 * np.pi * freqs / float(sample_rate)))
    response = np.ones(len(freqs), dtype=np.complex128)
    for b0, b1, b2, a1, a2 in stages:
        response *= (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
    return 20.0 * np.log10(np.maximum(np.abs(response), 1e-12))


def normalized_shape(curve: np.ndarray) -> np.ndarray:
    arr = np.asarray(curve, dtype=np.float64)
    band = arr[COMPARE_MASK]
    return arr - float(np.mean(band))


def shape_rms_db(a: np.ndarray, b: np.ndarray) -> float:
    delta = normalized_shape(a)[COMPARE_MASK] - normalized_shape(b)[COMPARE_MASK]
    return float(np.sqrt(np.mean(delta * delta)))


def shape_max_db(a: np.ndarray, b: np.ndarray) -> float:
    delta = np.abs(normalized_shape(a)[COMPARE_MASK] - normalized_shape(b)[COMPARE_MASK])
    return float(np.max(delta))


def prominent_landmarks(curve: np.ndarray, limit: int = 4) -> dict[str, list[dict[str, float]]]:
    norm = normalized_shape(curve)
    peaks: list[tuple[float, int]] = []
    valleys: list[tuple[float, int]] = []
    for i in range(2, len(norm) - 2):
        local = norm[max(0, i - 16):min(len(norm), i + 17)]
        if norm[i] >= norm[i - 1] and norm[i] > norm[i + 1]:
            prominence = float(norm[i] - np.percentile(local, 20))
            if prominence >= 2.5:
                peaks.append((prominence, i))
        if norm[i] <= norm[i - 1] and norm[i] < norm[i + 1]:
            prominence = float(np.percentile(local, 80) - norm[i])
            if prominence >= 2.5:
                valleys.append((prominence, i))

    def pack(items: list[tuple[float, int]]) -> list[dict[str, float]]:
        out = []
        for prominence, index in sorted(items, reverse=True)[:limit]:
            out.append({
                "freq_hz": round(float(FIT_FREQS[index]), 3),
                "level_db": round(float(norm[index]), 3),
                "prominence_db": round(float(prominence), 3),
            })
        return sorted(out, key=lambda item: item["freq_hz"])

    return {"peaks": pack(peaks), "valleys": pack(valleys)}


def classify_archetype(entry: dict[str, Any], corners: list[TargetCorner]) -> dict[str, str]:
    name = entry["name"].lower()
    rom_table = str(entry.get("rom_table", ""))
    avg = np.mean([corner.response_db for corner in corners], axis=0)
    low = float(np.mean(avg[(FIT_FREQS >= 80.0) & (FIT_FREQS <= 180.0)]))
    high = float(np.mean(avg[(FIT_FREQS >= 8_000.0) & (FIT_FREQS <= 12_000.0)]))
    landmarks = prominent_landmarks(avg)
    peak_count = len(landmarks["peaks"])
    valley_count = len(landmarks["valleys"])

    if "lowpass" in name:
        topology = "ladder cap"
        zero_relation = "cuts the ladder"
        frequency_role = "low to air cap"
    elif "highpass" in name:
        topology = "floor cutter"
        zero_relation = "opposes pole"
        frequency_role = "sub to bite"
    elif "bandpass" in name:
        topology = "canyoned cluster" if "contrary" in name else "focused anchor"
        zero_relation = "opposes pole"
        frequency_role = "low-mid to bite"
    elif "phaser" in name or "flanger" in name:
        topology = "comb crosser pair"
        zero_relation = "suspends against another actor"
        frequency_role = "mouth to air"
    elif "vocal" in name:
        topology = "formant ladder"
        zero_relation = "follows pole"
        frequency_role = "low-mid mouth bite"
    elif "swept" in name:
        topology = "mover"
        zero_relation = "resolves away"
        frequency_role = "low-mid to air"
    else:
        topology = "cluster" if peak_count >= 2 else "anchor"
        zero_relation = "neutral" if valley_count == 0 else "opposes pole"
        frequency_role = "full range"

    q_posture = "focused" if peak_count <= 1 else "hard"
    if "phaser" in name or "flanger" in name:
        q_posture = "razor"
    gain_posture = "compensated" if abs(high - low) > 8.0 or rom_table in {"lp", "hp"} else "body"
    motion = "good HOME seed" if peak_count + valley_count <= 2 else "dangerous midpoint"
    if "vocal" in name or "swept" in name:
        motion = "good AWAY contrast"

    return {
        "frequency_role": frequency_role,
        "topology": topology,
        "zero_relation": zero_relation,
        "q_posture": q_posture,
        "gain_posture": gain_posture,
        "motion_compatibility": motion,
    }


def make_recipe(entry: dict[str, Any], sample_rate: int, corners: list[TargetCorner]) -> dict[str, Any]:
    corner_docs = {}
    for corner in corners:
        stable = all(poles_stable(stage[3], stage[4]) for stage in corner.stages)
        corner_docs[corner.label] = {
            "morph": CORNER_POINTS[corner.label][0],
            "secondary": CORNER_POINTS[corner.label][1],
            "stable_under_decode": stable,
            "tilt_low_minus_high_db": round(float(
                np.mean(corner.response_db[(FIT_FREQS >= 80.0) & (FIT_FREQS <= 180.0)])
                - np.mean(corner.response_db[(FIT_FREQS >= 8_000.0) & (FIT_FREQS <= 12_000.0)])
            ), 3),
            "landmarks": prominent_landmarks(corner.response_db),
        }
    return {
        "format": "x3-fixed-cleanroom-recipe-v1",
        "name": f"x3_shape_{slug(entry['name'])}",
        "clean_room_note": (
            "Response-shape archetype only. X3 fixed-point words are decoded for study, "
            "but no source words, coefficients, names-as-products, or packed data are copied "
            "into the emitted body."
        ),
        "source_policy": {
            "reference_dir": "ref/x3_menu/runtime_blocks",
            "decoded_response_only": True,
            "sample_rate_hz": int(sample_rate),
            "decode": {
                "representation": "df2t",
                "scale": DECODE_SCALE,
                "order": list(DECODE_ORDER),
                "oracle": "2 Pole Lowpass must be stable and lowpass-shaped",
            },
        },
        "menu_class": {
            "name": entry["name"],
            "class": entry.get("class"),
            "rom_table_family": entry.get("rom_table"),
            "output_stages": int(entry["output_stages"]),
        },
        "archetype": classify_archetype(entry, corners),
        "corners": corner_docs,
        "compile_policy": {
            "body_contract": "4 corners x 6 rows x 5 packed words = .body240",
            "method": "fit each decoded response silhouette into original six-row kernel corners",
            "comparison": "offset-normalized magnitude shape RMS; bytes are not compared",
        },
    }


def fit_cleanroom_words(corners: list[TargetCorner]) -> tuple[bytes, dict[str, list[tuple[int, ...]]]]:
    kernels = {}
    for corner in corners:
        target = normalized_shape(corner.response_db)
        curve = list(zip(FIT_FREQS.tolist(), target.tolist()))
        kernels[corner.label] = trench_ffi.fit_corner_from_magnitude(curve, AUTHORING_SR)
    words = words_from_kernels(kernels)
    return raw_from_words(words), words


def compiled_response(body: bytes, label: str) -> np.ndarray:
    morph, secondary = CORNER_POINTS[label]
    rows = trench_ffi.packed_interpolate(body, morph, secondary)
    return cascade_response_db([EncodedCoeffs(*row) for row in rows], FIT_FREQS, AUTHORING_SR)


def audit_body(body: bytes, grid: int) -> dict[str, Any]:
    max_radius = 0.0
    unstable = 0
    nonfinite = 0
    for morph in np.linspace(0.0, 1.0, grid):
        for secondary in np.linspace(0.0, 1.0, grid):
            probe = trench_ffi.packed_probe(body, float(morph), float(secondary))
            max_radius = max(max_radius, float(probe["max_pole_radius"]))
            unstable |= int(probe["unstable_mask"])
            nonfinite |= int(probe["nonfinite_mask"])
    return {
        "grid": int(grid),
        "grid_points": int(grid * grid),
        "max_pole_radius": round(max_radius, 9),
        "unstable_mask": int(unstable),
        "nonfinite_mask": int(nonfinite),
    }


def compare_shape(body: bytes, corners: list[TargetCorner]) -> dict[str, Any]:
    rows = []
    for corner in corners:
        actual = compiled_response(body, corner.label)
        rows.append({
            "corner": corner.label,
            "offset_normalized_rms_db": round(shape_rms_db(corner.response_db, actual), 4),
            "offset_normalized_max_db": round(shape_max_db(corner.response_db, actual), 4),
            "target_peak_db": round(float(np.max(normalized_shape(corner.response_db))), 3),
            "body_peak_db": round(float(np.max(normalized_shape(actual))), 3),
        })
    return {
        "policy": "shape_only_no_byte_comparison",
        "band_hz": [80.0, 12_000.0],
        "mean_offset_normalized_rms_db": round(float(np.mean([row["offset_normalized_rms_db"] for row in rows])), 4),
        "max_offset_normalized_rms_db": round(float(np.max([row["offset_normalized_rms_db"] for row in rows])), 4),
        "corners": rows,
    }


def plot_overlay(name: str, body: bytes, corners: list[TargetCorner], out: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), facecolor="#070a09")
    colors = {"target": "#f4d35e", "body": "#70d6ff"}
    for ax, corner in zip(axes.ravel(), corners):
        actual = compiled_response(body, corner.label)
        ax.set_facecolor("#090d0c")
        ax.semilogx(FIT_FREQS, np.clip(normalized_shape(corner.response_db), -72, 24),
                    color=colors["target"], lw=1.5, label="decoded target shape")
        ax.semilogx(FIT_FREQS, np.clip(normalized_shape(actual), -72, 24),
                    color=colors["body"], lw=1.4, label="clean body240 shape")
        ax.set_title(corner.label, color="#e8eee9", fontsize=10)
        ax.set_xlim(45, 16_000)
        ax.set_ylim(-72, 24)
        ax.grid(True, which="both", color="#26342f", alpha=0.4, linewidth=0.55)
        ax.tick_params(colors="#a7b4ad", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#25352e")
    axes.ravel()[0].legend(facecolor="#101713", edgecolor="#27372f", labelcolor="#e9efe9", fontsize=8)
    fig.suptitle(f"{name}: decoded X3 shape vs clean-room body240", color="#e9efe9", fontsize=13)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130)
    plt.close(fig)


def process_entry(entry: dict[str, Any], sample_rate: int, out_root: Path, *, plots: bool, audit_grid: int) -> dict[str, Any]:
    name = f"x3_shape_{slug(entry['name'])}"
    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)
    corners = read_target_corners(entry, sample_rate)
    recipe = make_recipe(entry, sample_rate, corners)
    body, words = fit_cleanroom_words(corners)
    comparison = compare_shape(body, corners)
    audit = audit_body(body, audit_grid)

    body_path = out_dir / f"{name}.body240"
    cart_path = out_dir / f"{name}.cart.json"
    recipe_path = out_dir / f"{name}.recipe.json"
    compare_path = out_dir / f"{name}.shape_compare.json"
    report_path = out_dir / "report.json"
    body_path.write_bytes(body)
    cart_path.write_text(json.dumps(compiled_payload(name, 1.0, words), indent=2) + "\n", encoding="utf-8")
    recipe_path.write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    compare_path.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")

    outputs = {
        "body240": body_path.name,
        "compiled_cart": cart_path.name,
        "recipe": recipe_path.name,
        "shape_compare": compare_path.name,
    }
    if plots:
        overlay_path = out_dir / "shape_overlay.png"
        packed_plot_path = out_dir / "packed_surface.png"
        plot_overlay(name, body, corners, overlay_path)
        render_png(name, words, packed_plot_path)
        outputs["shape_overlay"] = overlay_path.name
        outputs["packed_surface"] = packed_plot_path.name

    report = {
        "format": "x3-fixed-cleanroom-build-report-v1",
        "name": name,
        "clean_room_note": recipe["clean_room_note"],
        "runtime_authority": ".body240 plus compiled-v1 cartridge JSON",
        "body240_sha256": hashlib.sha256(body).hexdigest(),
        "body240_bytes": len(body),
        "audit": audit,
        "shape_comparison": comparison,
        "outputs": outputs,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        display_dir = str(out_dir.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        display_dir = str(out_dir).replace("\\", "/")

    return {
        "name": name,
        "menu_name": entry["name"],
        "body240_sha256": report["body240_sha256"],
        "shape_rms_db": comparison["mean_offset_normalized_rms_db"],
        "max_corner_shape_rms_db": comparison["max_offset_normalized_rms_db"],
        "max_pole_radius": audit["max_pole_radius"],
        "unstable_mask": audit["unstable_mask"],
        "nonfinite_mask": audit["nonfinite_mask"],
        "dir": display_dir,
    }


def write_index(rows: list[dict[str, Any]], out_root: Path) -> None:
    body_rows = []
    for row in rows:
        rel = html.escape(row["dir"])
        body_rows.append(
            "<tr>"
            f"<td><a href=\"{rel}/report.json\">{html.escape(row['menu_name'])}</a></td>"
            f"<td>{row['shape_rms_db']:.2f}</td>"
            f"<td>{row['max_corner_shape_rms_db']:.2f}</td>"
            f"<td>{row['max_pole_radius']:.5f}</td>"
            f"<td>{row['unstable_mask']}</td><td>{row['nonfinite_mask']}</td>"
            "</tr>"
        )
    page = """<!doctype html><meta charset=utf-8>
<title>X3 fixed clean-room archetypes</title>
<style>
body{background:#070a09;color:#d7ded9;font:14px/1.45 system-ui,sans-serif;margin:24px}
a{color:#8ddcff} table{border-collapse:collapse} td,th{border:1px solid #26342f;padding:6px 9px}
th{color:#9fe7c6;background:#101713}
</style>
<h1>X3 fixed clean-room archetypes</h1>
<p>Decoded fixed-class responses converted to clean-room recipes and legal .body240 bodies. Comparison is shape-only.</p>
<table><tr><th>target</th><th>mean shape RMS</th><th>max corner RMS</th><th>max pole radius</th><th>unstable</th><th>nonfinite</th></tr>
""" + "\n".join(body_rows) + "\n</table>\n"
    (out_root / "index.html").write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="X3 fixed-class response -> clean-room body240 archetypes")
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--target", action="append", help="menu-name substring or slug; may be repeated")
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    parser.add_argument("--audit-grid", type=int, default=7)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()

    if not trench_ffi.available():
        raise SystemExit("trench-core unavailable; build with cargo build --release -p trench-core")

    manifest = load_manifest()
    entries = fixed_entries(manifest)
    if args.target:
        wanted = [slug(item) for item in args.target]
        entries = [
            entry for entry in entries
            if any(token in slug(entry["name"]) or token in str(entry["name"]).lower() for token in wanted)
        ]
        if not entries:
            raise SystemExit(f"no fixed X3 entries matched {args.target}")

    args.out.mkdir(parents=True, exist_ok=True)
    rows = [process_entry(entry, args.sample_rate, args.out, plots=not args.no_plots, audit_grid=args.audit_grid)
            for entry in entries]
    summary = {
        "format": "x3-fixed-cleanroom-summary-v1",
        "sample_rate_hz": int(args.sample_rate),
        "decode": {"representation": "df2t", "scale": DECODE_SCALE, "order": list(DECODE_ORDER)},
        "count": len(rows),
        "policy": "shape_only_no_byte_comparison",
        "rows": rows,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_index(rows, args.out)
    print(f"wrote {len(rows)} clean-room X3 fixed-class bodies -> {args.out}")
    for row in rows:
        print(f"{row['menu_name']}: shape RMS {row['shape_rms_db']:.2f} dB, maxR {row['max_pole_radius']:.5f}")


if __name__ == "__main__":
    main()
