#!/usr/bin/env python3
"""Export P2K calibration presets as machine-readable magnitude responses.

The JSON output is the source of truth. PNGs are only rendered views for humans.
This keeps P2K references useful as calibration/guardrail data without turning
them into recipes for new bodies.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pyruntime import packed_interp as pi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db


DEFAULT_OUT = ROOT / "dev" / "tmp" / "p2k_response_calibration"
DEFAULT_INPUTS = [
    ROOT / "ref" / "presets",
    ROOT / "ref" / "p2k_skins",
    ROOT / "ref" / "millennium.kernels.json",
]
SR_DEFAULT = 39062.5
STAGES = 6
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
CURVE_POINTS = (
    ("M0_Q0", 0.0, 0.0),
    ("M50_Q0", 0.5, 0.0),
    ("M100_Q0", 1.0, 0.0),
    ("M0_Q100", 0.0, 1.0),
    ("M50_Q50", 0.5, 0.5),
    ("M100_Q100", 1.0, 1.0),
)
BANDS = (
    ("low", 20.0, 120.0),
    ("body", 120.0, 800.0),
    ("bite", 800.0, 4000.0),
    ("air", 4000.0, 16000.0),
)


def slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_") or "preset"


def amp_to_db(x: float) -> float:
    return 20.0 * math.log10(max(abs(float(x)), 1e-30))


def raw_stage_to_kernel(stage: dict[str, Any]) -> tuple[float, float, float, float, float]:
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
        return (2.0, 1.0, 2.0 + a1, 1.0 - a2, b0)
    return (2.0 + b1 / b0, 1.0 - b2 / b0, 2.0 + a1, 1.0 - a2, b0)


def body_bytes_to_words(raw: bytes) -> dict[str, list[tuple[int, ...]]]:
    if len(raw) != 240:
        raise ValueError(f"expected 240-byte packed preset, got {len(raw)} bytes")
    words: dict[str, list[tuple[int, ...]]] = {}
    off = 0
    for label in CORNER_ORDER:
        rows = []
        for _ in range(STAGES):
            row = []
            for _ in range(5):
                row.append(int.from_bytes(raw[off:off + 2], "little"))
                off += 2
            rows.append(tuple(row))
        words[label] = rows
    return words


def load_preset(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".bin":
        words = body_bytes_to_words(path.read_bytes())
        return {
            "id": slug(path.stem),
            "name": path.stem,
            "source": str(path),
            "sample_rate_hz": SR_DEFAULT,
            "mode": "packed_u16_exact",
            "boosts": {label: 1.0 for label in CORNER_ORDER},
            "packed_words": words,
            "corners": None,
        }

    doc = json.loads(path.read_text(encoding="utf-8"))
    name = str(doc.get("name", path.stem))
    sr = float(doc.get("sampleRate", doc.get("sample_rate", SR_DEFAULT)))
    boost_default = float(doc.get("boost", 1.0))
    boosts = {label: boost_default for label in CORNER_ORDER}

    if "keyframes" in doc:
        by_label = {kf["label"]: kf for kf in doc["keyframes"]}
        corners = {}
        packed_words = {}
        packed_count = 0
        for label in CORNER_ORDER:
            kf = by_label[label]
            boosts[label] = float(kf.get("boost", boost_default))
            if kf.get("packedWords"):
                rows = [tuple(int(v) & 0xFFFF for v in row) for row in kf["packedWords"][:STAGES]]
                packed_words[label] = rows
                corners[label] = [pi.words_to_coeffs(row) for row in rows]
                packed_count += 1
            else:
                corners[label] = [stage_to_kernel(s) for s in kf["stages"][:STAGES]]
        return {
            "id": slug(path.stem),
            "name": name,
            "source": str(path),
            "sample_rate_hz": sr,
            "mode": "packed_u16_exact" if packed_count == 4 else "float_kernel_bilinear",
            "boosts": boosts,
            "packed_words": packed_words if packed_count == 4 else None,
            "corners": corners,
        }

    if "corners" in doc and isinstance(doc["corners"], dict):
        corners = {
            label: [stage_to_kernel(s) for s in doc["corners"][label]["stages"][:STAGES]]
            for label in CORNER_ORDER
        }
        return {
            "id": slug(path.stem),
            "name": name,
            "source": str(path),
            "sample_rate_hz": sr,
            "mode": "float_kernel_bilinear",
            "boosts": boosts,
            "packed_words": None,
            "corners": corners,
        }

    if "corners" in doc and isinstance(doc["corners"], list):
        if len(doc["corners"]) < 4:
            raise ValueError(f"{path}: corners array has {len(doc['corners'])}, expected 4")
        corners = {
            label: [tuple(float(v) for v in row) for row in doc["corners"][i][:STAGES]]
            for i, label in enumerate(CORNER_ORDER)
        }
        return {
            "id": slug(path.stem),
            "name": name,
            "source": str(path),
            "sample_rate_hz": sr,
            "mode": "float_kernel_bilinear",
            "boosts": boosts,
            "packed_words": None,
            "corners": corners,
        }

    raise ValueError(f"{path}: unsupported P2K calibration format")


def stage_to_kernel(stage: dict[str, Any]) -> tuple[float, float, float, float, float]:
    if all(k in stage for k in ("c0", "c1", "c2", "c3", "c4")):
        return tuple(float(stage[k]) for k in ("c0", "c1", "c2", "c3", "c4"))
    return raw_stage_to_kernel(stage)


def interpolate_boost(boosts: dict[str, float], morph: float, q: float) -> float:
    q_m0 = boosts["M0_Q0"] + (boosts["M0_Q100"] - boosts["M0_Q0"]) * q
    q_m1 = boosts["M100_Q0"] + (boosts["M100_Q100"] - boosts["M100_Q0"]) * q
    return q_m0 + (q_m1 - q_m0) * morph


def interpolate_float(corners: dict[str, list[tuple[float, ...]]], morph: float, q: float) -> list[tuple[float, ...]]:
    out = []
    for si in range(STAGES):
        row = []
        for ci in range(5):
            q_m0 = corners["M0_Q0"][si][ci] + (corners["M0_Q100"][si][ci] - corners["M0_Q0"][si][ci]) * q
            q_m1 = corners["M100_Q0"][si][ci] + (corners["M100_Q100"][si][ci] - corners["M100_Q0"][si][ci]) * q
            row.append(q_m0 + (q_m1 - q_m0) * morph)
        out.append(tuple(row))
    return out


def rows_for_curve(preset: dict[str, Any], morph: float, q: float) -> list[tuple[float, ...]]:
    if preset["mode"] == "packed_u16_exact" and preset["packed_words"]:
        words = {
            "A": preset["packed_words"]["M0_Q0"],
            "B": preset["packed_words"]["M100_Q0"],
            "C": preset["packed_words"]["M0_Q100"],
            "D": preset["packed_words"]["M100_Q100"],
        }
        return pi.packed_bilinear(words, morph, q)
    return interpolate_float(preset["corners"], morph, q)


def band_mean(freqs: np.ndarray, db: np.ndarray, lo: float, hi: float) -> float:
    mask = (freqs >= lo) & (freqs < hi)
    return float(np.mean(db[mask])) if np.any(mask) else float("nan")


def local_extrema(freqs: np.ndarray, db: np.ndarray, want: str, limit: int = 8) -> list[dict[str, float]]:
    vals = np.asarray(db)
    if len(vals) < 3:
        return []
    if want == "peaks":
        idx = np.where((vals[1:-1] > vals[:-2]) & (vals[1:-1] >= vals[2:]))[0] + 1
        idx = sorted(idx, key=lambda i: vals[i], reverse=True)
    else:
        idx = np.where((vals[1:-1] < vals[:-2]) & (vals[1:-1] <= vals[2:]))[0] + 1
        idx = sorted(idx, key=lambda i: vals[i])
    out = []
    used: list[float] = []
    for i in idx:
        f = float(freqs[i])
        if any(abs(math.log2(f / u)) < 0.12 for u in used):
            continue
        used.append(f)
        out.append({"freq_hz": round(f, 2), "db": round(float(vals[i]), 2)})
        if len(out) >= limit:
            break
    return sorted(out, key=lambda x: x["freq_hz"])


def curve_features(freqs: np.ndarray, db: np.ndarray) -> dict[str, Any]:
    bands = {name: round(band_mean(freqs, db, lo, hi), 2) for name, lo, hi in BANDS}
    return {
        "bands_db": bands,
        "low_minus_body_db": round(bands["low"] - bands["body"], 2),
        "low_minus_bite_db": round(bands["low"] - bands["bite"], 2),
        "body_minus_bite_db": round(bands["body"] - bands["bite"], 2),
        "peak_db": round(float(np.max(db)), 2),
        "floor_db": round(float(np.min(db)), 2),
        "contrast_db": round(float(np.max(db) - np.min(db)), 2),
        "peaks": local_extrema(freqs, db, "peaks"),
        "notches": local_extrema(freqs, db, "notches"),
    }


def stage_diagnostics(rows: list[tuple[float, ...]], sr: float) -> list[dict[str, float]]:
    out = []
    for i, row in enumerate(rows, 1):
        c0, c1, c2, c3, c4 = row
        b0, b1, b2, a1, a2 = pi.kernel_to_biquad(row)
        r = math.sqrt(max(a2, 0.0))
        pole_hz = 0.0
        if r > 1e-9:
            pole_hz = math.acos(max(-1.0, min(1.0, -a1 / (2.0 * r)))) * sr / (2.0 * math.pi)
        dc_gain = c4 * (c0 - c1) / (c2 - c3) if abs(c2 - c3) > 1e-30 else math.inf
        out.append({
            "stage": i,
            "pole_hz": round(pole_hz, 2),
            "radius": round(r, 6),
            "c4": round(float(c4), 8),
            "stage_dc_gain_db": round(amp_to_db(dc_gain), 2) if math.isfinite(dc_gain) else 999.0,
            "b0": round(float(b0), 8),
            "b1": round(float(b1), 8),
            "b2": round(float(b2), 8),
        })
    return out


def export_preset(preset: dict[str, Any], out_root: Path, freqs: np.ndarray) -> dict[str, Any]:
    dest = out_root / preset["id"]
    dest.mkdir(parents=True, exist_ok=True)

    curves: dict[str, Any] = {}
    summary_rows = []
    for label, morph, q in CURVE_POINTS:
        rows = rows_for_curve(preset, morph, q)
        boost = interpolate_boost(preset["boosts"], morph, q)
        db = cascade_response_db([EncodedCoeffs(*row) for row in rows], freqs, preset["sample_rate_hz"])
        db = db + amp_to_db(boost)
        features = curve_features(freqs, db)
        curves[label] = {
            "morph": morph,
            "q": q,
            "boost": boost,
            "freq_hz": [round(float(f), 4) for f in freqs],
            "db": [round(float(v), 4) for v in db],
            "features": features,
        }
        summary_rows.append({
            "preset": preset["name"],
            "curve": label,
            "mode": preset["mode"],
            **features["bands_db"],
            "peak": features["peak_db"],
            "low_minus_body": features["low_minus_body_db"],
            "low_minus_bite": features["low_minus_bite_db"],
            "contrast": features["contrast_db"],
        })

    m0_rows = rows_for_curve(preset, 0.0, 0.0)
    payload = {
        "id": preset["id"],
        "name": preset["name"],
        "source": preset["source"],
        "sample_rate_hz": preset["sample_rate_hz"],
        "grid": {
            "type": "log",
            "min_hz": float(freqs[0]),
            "max_hz": float(freqs[-1]),
            "points": int(len(freqs)),
        },
        "interpolation_mode": preset["mode"],
        "curves": curves,
        "m0_q0_stage_diagnostics": stage_diagnostics(m0_rows, preset["sample_rate_hz"]),
        "notes": [
            "Machine-readable magnitude response. PNG plot is derived from this JSON.",
            "Use as calibration/guardrail data, not as an original-body recipe.",
        ],
    }
    (dest / "response.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    plot_response(payload, dest / "magnitude_response.png")
    return {"preset": preset["name"], "dir": str(dest), "rows": summary_rows}


def plot_response(payload: dict[str, Any], out: Path) -> None:
    plt.rcParams["figure.facecolor"] = "#080c0b"
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.set_facecolor("#08100d")
    colors = {
        "M0_Q0": "#53f071",
        "M50_Q0": "#a4ff7b",
        "M100_Q0": "#2ed4e8",
        "M0_Q100": "#ffcf5a",
        "M50_Q50": "#f781ff",
        "M100_Q100": "#ff5c72",
    }
    for label in ("M0_Q0", "M50_Q0", "M100_Q0", "M0_Q100", "M50_Q50", "M100_Q100"):
        c = payload["curves"][label]
        ax.semilogx(c["freq_hz"], c["db"], lw=1.6, color=colors[label], label=label)
    ax.set_xlim(payload["grid"]["min_hz"], payload["grid"]["max_hz"])
    ax.set_ylim(-80, 30)
    ax.set_xlabel("frequency (Hz)", color="#b9c5be")
    ax.set_ylabel("magnitude (dB)", color="#b9c5be")
    ax.set_title(f"{payload['name']} — P2K calibration magnitude response", color="#50ff75")
    ax.grid(True, which="both", color="#183026", alpha=0.55)
    ax.tick_params(colors="#aeb8b1")
    for sp in ax.spines.values():
        sp.set_color("#375246")
    ax.legend(facecolor="#0b1511", edgecolor="#42604f", labelcolor="#d7ddd8", fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def collect_inputs(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.bin")))
            files.extend(sorted(path.glob("*.json")))
        elif path.exists():
            files.append(path)
    skip_suffixes = (".kernels.json",)
    out = []
    for f in files:
        if f.name.upper() == "MANIFEST.json":
            continue
        if f.name.endswith(skip_suffixes):
            out.append(f)
        elif f.suffix.lower() in (".bin", ".json"):
            out.append(f)
    return sorted(dict.fromkeys(out))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("inputs", nargs="*", type=Path, help="Preset files or directories. Defaults to ref P2K calibration refs.")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--points", type=int, default=1024)
    args = p.parse_args(argv)

    inputs = collect_inputs(args.inputs or DEFAULT_INPUTS)
    if not inputs:
        raise SystemExit("no calibration inputs found")
    args.out.mkdir(parents=True, exist_ok=True)
    freqs = np.logspace(math.log10(20.0), math.log10(16000.0), args.points)

    all_rows = []
    exports = []
    errors = []
    for path in inputs:
        try:
            preset = load_preset(path)
            result = export_preset(preset, args.out, freqs)
            exports.append({"name": result["preset"], "dir": result["dir"], "source": str(path)})
            all_rows.extend(result["rows"])
            print(f"wrote {Path(result['dir']) / 'response.json'}")
        except Exception as exc:
            errors.append({"source": str(path), "error": str(exc)})
            print(f"skip {path}: {exc}", file=sys.stderr)

    with (args.out / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["preset", "curve", "mode", "low", "body", "bite", "air", "peak",
                  "low_minus_body", "low_minus_bite", "contrast"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in all_rows:
            w.writerow(row)
    (args.out / "index.json").write_text(json.dumps({
        "exports": exports,
        "errors": errors,
        "summary_csv": str(args.out / "summary.csv"),
    }, indent=2), encoding="utf-8")
    print(f"wrote {args.out / 'summary.csv'} ({len(all_rows)} curves)")
    if errors:
        print(f"{len(errors)} input(s) skipped; see index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
