#!/usr/bin/env python3
"""Extract Talking Hedz M0_Q0 as a floor recipe and compare body loudness.

This is analysis-only. It uses the in-repo P2K Talking Hedz cartridge as the
reference because that file carries the raw pole/radius and numerator terms.
Candidate bodies are read from compiled-v1 cartridge JSON files under bodies/.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from pyruntime import packed_interp as pi


HEDZ_DEFAULT = ROOT / "ref" / "p2k_skins" / "00_talking_hedz.json"
BODIES_DEFAULT = ROOT / "bodies"
OUT_DEFAULT = ROOT / "dev" / "tmp" / "hedz_floor_profile"
AUTHORING_SR_DEFAULT = 39062.5
STAGES = 6

CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
BANDS = (
    ("low", 20.0, 120.0),
    ("body", 120.0, 800.0),
    ("bite", 800.0, 4000.0),
    ("air", 4000.0, 16000.0),
)


def db(value: float) -> float:
    return 20.0 * math.log10(max(abs(float(value)), 1e-30))


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def pole_freq_hz(a1: float, radius: float, sr: float) -> float:
    if radius <= 0.0:
        return 0.0
    theta = math.acos(clamp(-a1 / (2.0 * radius), -1.0, 1.0))
    return theta * sr / (2.0 * math.pi)


def raw_stage_to_kernel(stage: dict[str, Any]) -> EncodedCoeffs:
    a1 = float(stage["a1"])
    r = float(stage["r"])
    a2 = r * r
    val1 = float(stage["val1"])
    val2 = float(stage["val2"])
    val3 = float(stage["val3"])

    b0 = 1.0 + val1
    b1 = a1 + val2
    b2 = a2 - val3

    if abs(b0) <= 1e-12:
        return EncodedCoeffs(c0=2.0, c1=1.0, c2=2.0 + a1, c3=1.0 - a2, c4=b0)
    return EncodedCoeffs(
        c0=2.0 + b1 / b0,
        c1=1.0 - b2 / b0,
        c2=2.0 + a1,
        c3=1.0 - a2,
        c4=b0,
    )


def raw_stage_recipe(stage: dict[str, Any], index: int, sr: float) -> dict[str, Any]:
    a1 = float(stage["a1"])
    r = float(stage["r"])
    a2 = r * r
    val1 = float(stage["val1"])
    val2 = float(stage["val2"])
    val3 = float(stage["val3"])
    b0 = 1.0 + val1
    b1 = a1 + val2
    b2 = a2 - val3
    enc = raw_stage_to_kernel(stage)
    return {
        "stage": index,
        "pole_freq_hz": pole_freq_hz(a1, r, sr),
        "radius": r,
        "a1": a1,
        "a2": a2,
        "b0": b0,
        "b1": b1,
        "b2": b2,
        "numerator_shape_b0_norm": [
            1.0,
            b1 / b0 if abs(b0) > 1e-12 else 0.0,
            b2 / b0 if abs(b0) > 1e-12 else 0.0,
        ],
        "kernel_c0": enc.c0,
        "kernel_c1": enc.c1,
        "kernel_c2": enc.c2,
        "kernel_c3": enc.c3,
        "kernel_c4": enc.c4,
        "c4_gain_db": db(enc.c4),
    }


def band_levels(stages: list[EncodedCoeffs], freqs: np.ndarray, sr: float, boost: float) -> dict[str, float]:
    curve = cascade_response_db(stages, freqs, sr) + db(boost)
    out: dict[str, float] = {}
    for name, lo, hi in BANDS:
        mask = (freqs >= lo) & (freqs < hi)
        out[name] = float(np.mean(curve[mask])) if np.any(mask) else float("nan")
    out["broadband"] = float(np.mean(curve[(freqs >= BANDS[0][1]) & (freqs < BANDS[-1][2])]))
    out["peak"] = float(np.max(curve))
    return out


def load_hedz(path: Path, target_boost: float | None) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sr = float(doc.get("sampleRate", doc.get("sample_rate", AUTHORING_SR_DEFAULT)))
    by_label = {kf["label"]: kf for kf in doc["keyframes"]}
    kf = by_label["M0_Q0"]
    source_boost = float(kf.get("boost", doc.get("boost", 1.0)))
    boost = source_boost if target_boost is None else float(target_boost)
    raw_stages = kf["stages"][:STAGES]
    stages = [raw_stage_to_kernel(s) for s in raw_stages]
    c4_product = math.prod(s.c4 for s in stages)
    recipe = {
        "source": str(path),
        "name": doc.get("name", path.stem),
        "corner": "M0_Q0",
        "sample_rate_hz": sr,
        "source_boost": source_boost,
        "comparison_boost": boost,
        "stage_count": len(stages),
        "c4_product": c4_product,
        "c4_product_db": db(c4_product),
        "effective_c4_product_with_boost": c4_product * boost,
        "effective_c4_product_with_boost_db": db(c4_product * boost),
        "stages": [raw_stage_recipe(s, i + 1, sr) for i, s in enumerate(raw_stages)],
    }
    return {"doc": doc, "recipe": recipe, "stages": stages, "sr": sr, "boost": boost}


def keyframe_to_stages(kf: dict[str, Any], path: Path) -> list[EncodedCoeffs]:
    if kf.get("packedWords"):
        return [
            EncodedCoeffs(*pi.words_to_coeffs(tuple(int(v) for v in row)))
            for row in kf["packedWords"][:STAGES]
        ]
    stages = kf.get("stages", [])[:STAGES]
    out = []
    for st in stages:
        if all(k in st for k in ("c0", "c1", "c2", "c3", "c4")):
            out.append(EncodedCoeffs(float(st["c0"]), float(st["c1"]), float(st["c2"]),
                                     float(st["c3"]), float(st["c4"])))
        elif all(k in st for k in ("a1", "r", "val1", "val2", "val3")):
            out.append(raw_stage_to_kernel(st))
        else:
            raise ValueError(f"{path}: unsupported stage shape in {kf.get('label')}")
    if len(out) != STAGES:
        raise ValueError(f"{path}: expected at least {STAGES} stages in {kf.get('label')}, got {len(out)}")
    return out


def compare_candidate(path: Path, target: dict[str, float], freqs: np.ndarray) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    by_label = {kf.get("label"): kf for kf in doc.get("keyframes", [])}
    if "M0_Q0" not in by_label:
        raise ValueError(f"{path}: missing M0_Q0")
    kf = by_label["M0_Q0"]
    sr = float(doc.get("sampleRate", doc.get("sample_rate", AUTHORING_SR_DEFAULT)))
    boost = float(kf.get("boost", doc.get("boost", 1.0)))
    stages = keyframe_to_stages(kf, path)
    levels = band_levels(stages, freqs, sr, boost)
    deltas = {name: levels[name] - target[name] for name, _, _ in BANDS}
    band_names = [name for name, _, _ in BANDS]
    vals = np.array([deltas[name] for name in band_names], dtype=float)
    shape = vals - float(np.mean(vals))
    return {
        "file": str(path),
        "name": doc.get("name", path.stem),
        "boost": boost,
        "source": doc.get("provenance", ""),
        "levels": levels,
        "deltas": deltas,
        "rms_delta_db": float(np.sqrt(np.mean(vals * vals))),
        "mean_delta_db": float(np.mean(vals)),
        "shape_rms_delta_db": float(np.sqrt(np.mean(shape * shape))),
        "peak_db": levels["peak"],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "rank",
        "name",
        "file",
        "boost",
        "rms_delta_db",
        "shape_rms_delta_db",
        "mean_delta_db",
        "low_db",
        "body_db",
        "bite_db",
        "air_db",
        "low_delta_db",
        "body_delta_db",
        "bite_delta_db",
        "air_delta_db",
        "peak_db",
        "source",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, r in enumerate(rows, 1):
            flat = {
                "rank": i,
                "name": r["name"],
                "file": r["file"],
                "boost": r["boost"],
                "rms_delta_db": r["rms_delta_db"],
                "shape_rms_delta_db": r["shape_rms_delta_db"],
                "mean_delta_db": r["mean_delta_db"],
                "peak_db": r["peak_db"],
                "source": r["source"],
            }
            for name, _, _ in BANDS:
                flat[f"{name}_db"] = r["levels"][name]
                flat[f"{name}_delta_db"] = r["deltas"][name]
            w.writerow(flat)


def fmt(v: float) -> str:
    return f"{v:+.2f}"


def write_report(path: Path, recipe: dict[str, Any], target: dict[str, float], rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("# Talking Hedz M0_Q0 Floor Profile")
    lines.append("")
    lines.append(f"Source: `{recipe['source']}`")
    lines.append(f"Corner: `{recipe['corner']}`")
    lines.append(f"Sample rate: `{recipe['sample_rate_hz']}` Hz")
    lines.append(f"File boost: `{recipe['source_boost']}`")
    lines.append(f"Comparison boost: `{recipe['comparison_boost']}`")
    lines.append(f"C4 product: `{recipe['c4_product']:.9f}` ({recipe['c4_product_db']:+.2f} dB)")
    lines.append(
        f"C4 product with comparison boost: `{recipe['effective_c4_product_with_boost']:.9f}` "
        f"({recipe['effective_c4_product_with_boost_db']:+.2f} dB)"
    )
    lines.append("")
    lines.append("## M0_Q0 Recipe")
    lines.append("")
    lines.append("| stage | pole Hz | radius | b0 | b1 | b2 | b/b0 shape | c4 dB |")
    lines.append("|---:|---:|---:|---:|---:|---:|---|---:|")
    for st in recipe["stages"]:
        shape = ", ".join(f"{x:+.4f}" for x in st["numerator_shape_b0_norm"])
        lines.append(
            f"| {st['stage']} | {st['pole_freq_hz']:.1f} | {st['radius']:.6f} | "
            f"{st['b0']:+.6f} | {st['b1']:+.6f} | {st['b2']:+.6f} | "
            f"`[{shape}]` | {st['c4_gain_db']:+.2f} |"
        )
    lines.append("")
    lines.append("## Target Band Levels")
    lines.append("")
    lines.append("| band | Hz | level |")
    lines.append("|---|---:|---:|")
    for name, lo, hi in BANDS:
        lines.append(f"| {name} | {lo:.0f}-{hi:.0f} | {target[name]:+.2f} dB |")
    lines.append(f"| broadband | {BANDS[0][1]:.0f}-{BANDS[-1][2]:.0f} | {target['broadband']:+.2f} dB |")
    lines.append(f"| peak |  | {target['peak']:+.2f} dB |")
    lines.append("")
    lines.append("## Closest Candidate Bodies")
    lines.append("")
    lines.append("Ranked by RMS absolute delta across low/body/bite/air. Shape RMS is the same comparison after removing overall gain offset.")
    lines.append("")
    lines.append("| rank | body | rms | shape rms | mean offset | low | body | bite | air |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for i, r in enumerate(rows[:20], 1):
        lines.append(
            f"| {i} | {r['name']} | {r['rms_delta_db']:.2f} | {r['shape_rms_delta_db']:.2f} | "
            f"{fmt(r['mean_delta_db'])} | {fmt(r['deltas']['low'])} | "
            f"{fmt(r['deltas']['body'])} | {fmt(r['deltas']['bite'])} | {fmt(r['deltas']['air'])} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hedz", type=Path, default=HEDZ_DEFAULT)
    p.add_argument("--bodies", type=Path, default=BODIES_DEFAULT)
    p.add_argument("--out", type=Path, default=OUT_DEFAULT)
    p.add_argument(
        "--target-boost",
        type=float,
        default=None,
        help="Override the Hedz M0_Q0 boost used for band-level comparison. "
             "Default uses the source file's boost.",
    )
    args = p.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    freqs = np.logspace(math.log10(20.0), math.log10(16000.0), 2048)

    hedz = load_hedz(args.hedz, args.target_boost)
    target = band_levels(hedz["stages"], freqs, hedz["sr"], hedz["boost"])
    hedz["recipe"]["band_levels_db"] = target

    rows = []
    errors = []
    for path in sorted(args.bodies.glob("*.cart.json")):
        try:
            rows.append(compare_candidate(path, target, freqs))
        except Exception as exc:  # keep rack-wide comparisons robust
            errors.append({"file": str(path), "error": str(exc)})
    rows.sort(key=lambda r: (r["rms_delta_db"], r["shape_rms_delta_db"]))

    payload = {
        "recipe": hedz["recipe"],
        "target_band_levels_db": target,
        "candidate_count": len(rows),
        "errors": errors,
        "candidates": rows,
        "notes": [
            "Candidate comparison uses each body's M0_Q0 keyframe and its own boost.",
            "If packedWords are present, they are treated as coefficient authority.",
            "Bands are log-frequency means over low/body/bite/air.",
        ],
    }
    (args.out / "recipe.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_csv(args.out / "candidate_loudness.csv", rows)
    write_report(args.out / "REPORT.md", hedz["recipe"], target, rows)

    print(f"wrote {args.out / 'REPORT.md'}")
    print(f"wrote {args.out / 'candidate_loudness.csv'} ({len(rows)} candidates)")
    if errors:
        print(f"skipped {len(errors)} candidate(s); see recipe.json errors")
    if rows:
        best = rows[0]
        print(
            f"closest: {best['name']} rms={best['rms_delta_db']:.2f} dB "
            f"shape={best['shape_rms_delta_db']:.2f} dB"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
