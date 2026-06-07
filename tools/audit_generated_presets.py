#!/usr/bin/env python3
"""Audit original generated DF2 bodies through the shipped packed runtime.

This is diagnosis-only. It does not rewrite, rank, or promote bodies.
Reference fixtures are reduced to aggregate calibration statistics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402

SR = 39062.5
TAU = 2.0 * math.pi
FREQS = np.logspace(math.log10(40.0), math.log10(16000.0), 512)
GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
LABELS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
ENDPOINTS = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
PASS = (1.0, 0.0, 0.0, 0.0, 0.0)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def cart_bytes(path: Path) -> tuple[bytes, dict] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if doc.get("format") != "compiled-v1":
        return None
    keyframes = doc.get("keyframes")
    if not isinstance(keyframes, list) or len(keyframes) < 4:
        return None
    by_label = {str(kf.get("label", "")): kf for kf in keyframes if isinstance(kf, dict)}
    ordered = [by_label[label] for label in LABELS] if all(label in by_label for label in LABELS) else keyframes[:4]
    words: list[int] = []
    for keyframe in ordered:
        rows = keyframe.get("packedWords")
        if not isinstance(rows, list) or len(rows) != 6:
            return None
        for row in rows:
            if not isinstance(row, list) or len(row) != 5:
                return None
            words.extend(int(value) & 0xFFFF for value in row)
    if len(words) != 120:
        return None
    return struct.pack("<120H", *words), doc


def candidate_paths(include_dev_tmp: bool) -> list[Path]:
    paths = list((ROOT / "bodies").rglob("*.cart.json"))
    paths += list((ROOT / "juce-shell" / "assets" / "cartridges").glob("*.json"))
    if include_dev_tmp:
        paths += list((ROOT / "dev" / "tmp").rglob("*.cart.json"))
    out = []
    for path in paths:
        r = rel(path)
        if r.startswith("bodies/rom/"):
            continue
        if "/P2k_" in f"/{r}" or path.name.startswith("P2k_"):
            continue
        if path.name == "bypass.json":
            continue
        out.append(path)
    return sorted(set(out))


def group_for(path: Path, doc: dict) -> str:
    r = rel(path)
    provenance = str(doc.get("provenance", ""))
    if r.startswith("bodies/vocal_low_to_high/"):
        return "vocal_low_to_high"
    if r.startswith("bodies/non_formant/"):
        return "non_formant"
    if r.startswith("bodies/hybrids/"):
        return "hybrids"
    if r.startswith("bodies/crazy/"):
        return "crazy"
    if r.startswith("dev/tmp/"):
        parts = r.split("/")
        return "dev_tmp:" + (parts[2] if len(parts) > 2 else "unknown")
    if provenance == "direct-packed-240":
        return "early_direct_packed"
    if provenance:
        return "juce_custom:" + provenance.split(" - ", 1)[0].split(" — ", 1)[0]
    return "legacy_unclassified"


def response_db(rows: list[tuple[float, ...]]) -> np.ndarray:
    w = TAU * FREQS / SR
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    h = np.ones_like(z1, dtype=np.complex128)
    for b0, b1, b2, a1, a2 in rows:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-30))


def one_root_pair(c0: float, c1: float, c2: float) -> tuple[str, float | None, float | None]:
    if abs(c0) < 1e-15:
        return "none", None, None
    roots = np.roots((c0, c1, c2))
    if not len(roots):
        return "none", None, None
    root = max(roots, key=lambda value: abs(value.imag))
    radius = float(abs(root))
    angle = abs(float(np.angle(root)))
    kind = "complex_pair" if abs(root.imag) > 1e-7 else "real_pair"
    return kind, angle * SR / TAU, radius


def stage_metrics(row: tuple[float, ...]) -> dict:
    b0, b1, b2, a1, a2 = row
    if max(abs(row[i] - PASS[i]) for i in range(5)) < 1e-8:
        return {"active": False}
    pole_kind, pole_hz, pole_r = one_root_pair(1.0, a1, a2)
    if abs(b1) < 1e-10 and abs(b2) < 1e-10:
        zero_kind, zero_hz, zero_r = "none", None, None
    else:
        zero_kind, zero_hz, zero_r = one_root_pair(b0, b1, b2)
    offset = None
    if pole_hz and zero_hz and pole_hz > 1e-6 and zero_hz > 1e-6:
        offset = math.log2(zero_hz / pole_hz)
    return {
        "active": True,
        "pole_kind": pole_kind,
        "pole_hz": pole_hz,
        "pole_radius": pole_r,
        "zero_kind": zero_kind,
        "zero_hz": zero_hz,
        "zero_radius": zero_r,
        "zero_offset_octaves": offset,
        "paired_close": offset is not None and abs(offset) <= 1.0,
    }


def rms_delta(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def state_metrics(body: bytes, morph: float, secondary: float) -> dict:
    probe = trench_ffi.packed_probe(body, morph, secondary)
    rows = probe["biquad"]
    stages = [stage_metrics(row) for row in rows]
    active = [stage for stage in stages if stage["active"]]
    db = response_db(rows)
    peaks, _ = find_peaks(db, prominence=3.0)
    valleys, _ = find_peaks(-db, prominence=3.0)
    pole_hz = sorted(stage["pole_hz"] for stage in active if stage.get("pole_hz") is not None)
    collisions = sum((pole_hz[i + 1] - pole_hz[i]) < 200.0 for i in range(len(pole_hz) - 1))
    zeros = [stage for stage in active if stage.get("zero_kind") != "none"]
    close = [stage for stage in zeros if stage.get("paired_close")]
    return {
        "morph": morph,
        "secondary": secondary,
        "max_pole_radius": probe["max_pole_radius"],
        "unstable_mask": probe["unstable_mask"],
        "nonfinite_mask": probe["nonfinite_mask"],
        "active_stages": len(active),
        "zero_bearing_stages": len(zeros),
        "close_paired_zero_stages": len(close),
        "pole_collisions_lt_200hz": collisions,
        "peak_db": float(np.max(db)),
        "floor_db": float(np.min(db)),
        "span_db": float(np.max(db) - np.min(db)),
        "response_peaks": int(len(peaks)),
        "response_valleys": int(len(valleys)),
        "db": db,
        "stages": stages,
    }


def zero_motion_error(a: dict, b: dict) -> list[float]:
    errors = []
    for sa, sb in zip(a["stages"], b["stages"]):
        if not sa.get("active") or not sb.get("active"):
            continue
        if sa.get("pole_hz") and sb.get("pole_hz") and sa.get("zero_hz") and sb.get("zero_hz"):
            pole_move = math.log2(sb["pole_hz"] / sa["pole_hz"])
            zero_move = math.log2(sb["zero_hz"] / sa["zero_hz"])
            errors.append(abs(zero_move - pole_move))
    return errors


def analyze_body(body: bytes) -> dict:
    states = {(m, s): state_metrics(body, m, s) for s in GRID for m in GRID}
    endpoints = [states[pos] for pos in ENDPOINTS]
    center = states[(0.5, 0.5)]
    zero_motion = zero_motion_error(states[(0.0, 0.0)], states[(1.0, 0.0)])
    zero_motion += zero_motion_error(states[(0.0, 1.0)], states[(1.0, 1.0)])
    zero_motion += zero_motion_error(states[(0.0, 0.0)], states[(0.0, 1.0)])
    zero_motion += zero_motion_error(states[(1.0, 0.0)], states[(1.0, 1.0)])
    endpoint_active = sum(state["active_stages"] for state in endpoints)
    endpoint_zeros = sum(state["zero_bearing_stages"] for state in endpoints)
    endpoint_close = sum(state["close_paired_zero_stages"] for state in endpoints)
    return {
        "stable": all(state["unstable_mask"] == 0 for state in states.values()),
        "finite": all(state["nonfinite_mask"] == 0 for state in states.values()),
        "max_pole_radius": max(state["max_pole_radius"] for state in states.values()),
        "endpoint_active_stages": endpoint_active,
        "endpoint_zero_fraction": endpoint_zeros / max(1, endpoint_active),
        "endpoint_close_paired_zero_fraction": endpoint_close / max(1, endpoint_active),
        "zero_motion_error_octaves_mean": float(np.mean(zero_motion)) if zero_motion else None,
        "endpoint_collisions_lt_200hz": sum(state["pole_collisions_lt_200hz"] for state in endpoints),
        "center_collisions_lt_200hz": center["pole_collisions_lt_200hz"],
        "morph_contrast_rms_db": 0.5 * (
            rms_delta(states[(0.0, 0.0)]["db"], states[(1.0, 0.0)]["db"])
            + rms_delta(states[(0.0, 1.0)]["db"], states[(1.0, 1.0)]["db"])
        ),
        "secondary_contrast_rms_db": 0.5 * (
            rms_delta(states[(0.0, 0.0)]["db"], states[(0.0, 1.0)]["db"])
            + rms_delta(states[(1.0, 0.0)]["db"], states[(1.0, 1.0)]["db"])
        ),
        "center_sag_db": center["peak_db"] - float(np.mean([state["peak_db"] for state in endpoints])),
        "center_span_db": center["span_db"],
        "center_response_peaks": center["response_peaks"],
        "center_response_valleys": center["response_valleys"],
        "endpoint_span_db_mean": float(np.mean([state["span_db"] for state in endpoints])),
        "endpoint_response_peaks_mean": float(np.mean([state["response_peaks"] for state in endpoints])),
        "endpoint_response_valleys_mean": float(np.mean([state["response_valleys"] for state in endpoints])),
    }


def reference_bodies() -> list[bytes]:
    path = ROOT / "ref" / "p2k_variants" / "study_best_of_best" / "exact_packed_bodies.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        out.append(bytes.fromhex(row["bytes_hex"]))
    return out


def median(rows: list[dict], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None and math.isfinite(float(row[key]))]
    return float(np.median(values)) if values else None


def summarize(rows: list[dict]) -> dict:
    return {
        "bodies": len(rows),
        "stable": sum(bool(row["stable"]) for row in rows),
        "finite": sum(bool(row["finite"]) for row in rows),
        "median_endpoint_zero_fraction": median(rows, "endpoint_zero_fraction"),
        "median_close_paired_zero_fraction": median(rows, "endpoint_close_paired_zero_fraction"),
        "median_zero_motion_error_octaves": median(rows, "zero_motion_error_octaves_mean"),
        "median_morph_contrast_rms_db": median(rows, "morph_contrast_rms_db"),
        "median_secondary_contrast_rms_db": median(rows, "secondary_contrast_rms_db"),
        "median_center_sag_db": median(rows, "center_sag_db"),
        "median_center_span_db": median(rows, "center_span_db"),
        "median_center_response_peaks": median(rows, "center_response_peaks"),
        "median_center_response_valleys": median(rows, "center_response_valleys"),
        "median_endpoint_span_db": median(rows, "endpoint_span_db_mean"),
        "median_endpoint_collisions_lt_200hz": median(rows, "endpoint_collisions_lt_200hz"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-dev-tmp", action="store_true")
    parser.add_argument("--out", default="dev/tmp/generated_preset_audit")
    args = parser.parse_args()
    if not trench_ffi.available():
        raise SystemExit("trench-core FFI unavailable; run cargo build --release -p trench-core")

    output = ROOT / args.out
    output.mkdir(parents=True, exist_ok=True)
    bodies: dict[str, dict] = {}
    skipped = []
    for path in candidate_paths(args.include_dev_tmp):
        loaded = cart_bytes(path)
        if loaded is None:
            skipped.append(rel(path))
            continue
        raw, doc = loaded
        digest = hashlib.sha256(raw).hexdigest()
        entry = bodies.setdefault(
            digest,
            {
                "sha256": digest,
                "name": str(doc.get("name", path.stem)),
                "group": group_for(path, doc),
                "provenance": str(doc.get("provenance", "")),
                "paths": [],
                "raw": raw,
            },
        )
        entry["paths"].append(rel(path))

    rows = []
    for entry in bodies.values():
        metrics = analyze_body(entry.pop("raw"))
        rows.append({**entry, **metrics})
    rows.sort(key=lambda row: (row["group"], row["name"], row["sha256"]))

    by_group: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_group[row["group"]].append(row)
    reference_rows = [analyze_body(raw) for raw in reference_bodies()]

    report = {
        "scope": "original generated cartridges only; study fixtures excluded from authored rows",
        "include_dev_tmp": args.include_dev_tmp,
        "generated_unique_bodies": len(rows),
        "skipped_nonpacked_cartridges": skipped,
        "reference_aggregate": summarize(reference_rows),
        "generated_groups": {group: summarize(group_rows) for group, group_rows in sorted(by_group.items())},
        "bodies": rows,
    }
    (output / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    csv_keys = [
        "group", "name", "sha256", "stable", "finite", "max_pole_radius",
        "endpoint_zero_fraction", "endpoint_close_paired_zero_fraction",
        "zero_motion_error_octaves_mean", "endpoint_collisions_lt_200hz",
        "center_collisions_lt_200hz", "morph_contrast_rms_db",
        "secondary_contrast_rms_db", "center_sag_db", "center_span_db",
        "center_response_peaks", "center_response_valleys", "endpoint_span_db_mean",
        "endpoint_response_peaks_mean", "endpoint_response_valleys_mean", "provenance", "paths",
    ]
    with (output / "bodies.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in csv_keys})

    print(f"wrote {output}")
    print(f"generated unique bodies: {len(rows)}")
    print(f"reference calibration bodies: {len(reference_rows)}")
    for group, group_rows in sorted(by_group.items()):
        summary = summarize(group_rows)
        print(
            f"{group:<42} n={summary['bodies']:>4} "
            f"stable={summary['stable']:>4} "
            f"zeros={summary['median_endpoint_zero_fraction']:.2f} "
            f"paired={summary['median_close_paired_zero_fraction']:.2f} "
            f"morph={summary['median_morph_contrast_rms_db']:.1f}dB "
            f"sec={summary['median_secondary_contrast_rms_db']:.1f}dB "
            f"center-span={summary['median_center_span_db']:.1f}dB"
        )


if __name__ == "__main__":
    main()
