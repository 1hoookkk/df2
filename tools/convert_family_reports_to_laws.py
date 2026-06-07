#!/usr/bin/env python3
"""Convert clean-room family reports into Law Author section laws.

Input is the aggregate family contract folder written by
`dev/tmp/x3_p2k_family_browser`. Output is original section-law-v1 JSON under
`recipes/laws/`. These laws use aggregate frequency bands and movement metrics;
they do not copy packed bytes, coefficient tables, endpoint curves, names, or
preset rows.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def geom_pair(values: list[float | None], fallback: float) -> float:
    vals = [float(v) for v in values if v is not None and float(v) > 0.0]
    if len(vals) < 2:
        return fallback
    return math.sqrt(vals[0] * vals[1])


def width_oct(values: list[float | None], fallback: float = 1.0) -> float:
    vals = [float(v) for v in values if v is not None and float(v) > 0.0]
    if len(vals) < 2 or vals[1] <= vals[0]:
        return fallback
    return clamp(math.log2(vals[1] / vals[0]), 0.28, 2.4)


def actor(contract: dict[str, Any], role: str) -> dict[str, Any] | None:
    for item in contract.get("actor_bands", []):
        if item.get("role") == role:
            return item
    return None


def fc(contract: dict[str, Any], role: str, fallback: float) -> float:
    item = actor(contract, role)
    if not item:
        return fallback
    return geom_pair(item.get("peak_hz_p10_p90") or [], fallback)


def canyon_fc(contract: dict[str, Any], role: str, fallback: float) -> float:
    item = actor(contract, role)
    if not item:
        return fallback
    return geom_pair(item.get("canyon_hz_p10_p90") or [], fallback)


def bw(contract: dict[str, Any], role: str, fallback: float = 1.0) -> float:
    item = actor(contract, role)
    if not item:
        return fallback
    return width_oct(item.get("peak_hz_p10_p90") or [], fallback)


def zero_offset(fc_hz: float, zero_hz: float) -> float:
    if fc_hz <= 0.0 or zero_hz <= 0.0:
        return 0.0
    return clamp(math.log2(zero_hz / fc_hz), -5.5, 5.5)


def metrics(contract: dict[str, Any]) -> dict[str, float]:
    data = contract.get("aggregate_metrics", {})
    morph = float(data.get("p2k_median_morph_motion_rms_db") or data.get("x3_median_morph_motion_rms_db") or 10.0)
    q = float(data.get("p2k_median_q_pressure_rms_db") or data.get("x3_median_q_pressure_rms_db") or 8.0)
    tilt = float(data.get("median_low_minus_high_tilt_db") or 24.0)
    return {
        "morph": morph,
        "q": q,
        "tilt": tilt,
        "morph_spread": clamp(morph / 28.0, 0.25, 1.0),
        "q_crank": clamp(q / 18.0, 0.35, 1.0),
        "tilt_db": clamp(tilt * 0.55, 8.0, 22.0),
        "canyon_depth": clamp(14.0 + q * 0.85, 14.0, 30.0),
    }


def family_sections(contract: dict[str, Any]) -> list[dict[str, Any]]:
    family = contract["family"]
    low = fc(contract, "low", 190.0)
    low_mid = fc(contract, "low_mid", 650.0)
    mouth = fc(contract, "mouth", 1550.0)
    bite = fc(contract, "bite", 3600.0)
    air = fc(contract, "air", 8500.0)
    low_mid_z = canyon_fc(contract, "low_mid", low_mid * 0.82)
    mouth_z = canyon_fc(contract, "mouth", mouth * 0.92)
    bite_z = canyon_fc(contract, "bite", bite * 0.9)
    air_z = canyon_fc(contract, "air", air * 1.2)

    if family == "vocal_formant":
        return [
            section("anchor", low, 6.8, 0.9, low * 0.62, 0.10, 0.00, 1.0),
            section("f1", low_mid, 4.5, bw(contract, "low_mid"), low_mid_z, 0.55, 0.00, 1.0),
            section("f2_mouth", mouth, 5.5, bw(contract, "mouth"), mouth_z, 0.70, 0.00, 1.0),
            section("f3_bite", bite, 1.5, bw(contract, "bite"), bite_z, 0.55, 0.00, 0.9),
            section("air_restraint", air, -4.0, bw(contract, "air", 0.8), air_z, 0.20, 0.00, 0.55),
            section("remote_canyon", air_z, -7.0, 0.75, low_mid, 0.10, 0.65, 0.75),
        ]
    if family == "phaser_comb":
        return [
            section("anchor", low, 5.8, 0.95, low * 0.70, 0.10, 0.00, 1.0),
            section("comb_cut_low", low_mid, -5.0, 0.55, low_mid_z, 0.90, 0.35, 0.75),
            section("comb_peak_mouth", mouth, 3.0, 0.62, mouth_z, 0.85, 0.25, 0.85),
            section("comb_cut_bite", bite, -6.0, 0.52, bite_z, 0.85, -0.25, 0.8),
            section("comb_peak_air", air, 1.0, 0.55, air_z, 0.65, -0.30, 0.65),
            section("air_kill", air_z, -8.0, 0.5, 16500.0, 0.25, 0.40, 0.65),
        ]
    if family == "slope_ladder":
        return [
            section("anchor", low, 6.5, 1.05, low * 0.7, 0.10, 0.00, 1.0),
            section("low_mid_keep", low_mid, 2.0, bw(contract, "low_mid"), low_mid_z, 0.45, 0.10, 0.8),
            section("descending_frame", mouth, -2.0, 1.2, mouth_z, 0.25, -0.15, 0.65),
            section("bite_cliff", bite, -5.0, 0.8, bite_z, 0.35, -0.20, 0.8),
            section("air_kill", air, -8.0, 0.65, air_z, 0.20, 0.35, 0.75),
            section("top_cap", 16500.0, -7.0, 0.8, 8250.0, 0.05, 0.25, 0.45),
        ]
    if family == "bandpass_swept_eq":
        return [
            section("anchor", low, 5.8, 0.95, low * 0.65, 0.12, 0.00, 1.0),
            section("low_mid_window", low_mid, 2.0, bw(contract, "low_mid"), low_mid_z, 0.75, -0.10, 0.8),
            section("mouth_sweep", mouth, 4.0, bw(contract, "mouth"), mouth_z, 1.0, -0.15, 1.0),
            section("bite_sweep", bite, 2.0, bw(contract, "bite"), bite_z, 0.90, 0.20, 0.9),
            section("air_restraint", air, -3.5, bw(contract, "air", 0.85), air_z, 0.45, 0.30, 0.65),
            section("remote_kill", 4130.0, -7.0, 0.6, 9650.0, 0.20, 0.45, 0.75),
        ]
    return [
        section("anchor", low, 6.5, 0.9, low * 0.65, 0.10, 0.00, 1.0),
        section("low_mid", low_mid, 2.5, bw(contract, "low_mid"), low_mid_z, 0.55, 0.00, 0.8),
        section("mouth", mouth, 4.0, bw(contract, "mouth"), mouth_z, 0.85, -0.10, 1.0),
        section("bite", bite, 1.5, bw(contract, "bite"), bite_z, 0.75, 0.15, 0.9),
        section("air_cut", air, -4.5, bw(contract, "air", 0.8), air_z, 0.35, 0.30, 0.65),
        section("remote_canyon", 4130.0, -7.0, 0.7, 16500.0, 0.20, 0.35, 0.75),
    ]


def section(
    role: str,
    fc_hz: float,
    gain_db: float,
    bw_oct: float,
    zero_hz: float,
    morph_oct: float,
    zero_morph_oct: float,
    q_weight: float,
) -> dict[str, Any]:
    return {
        "role": role,
        "fc_hz": round(clamp(fc_hz, 24.0, 18000.0), 4),
        "gain_db": round(float(gain_db), 4),
        "bw_oct": round(clamp(bw_oct, 0.28, 2.4), 4),
        "zero_offset_oct": round(zero_offset(fc_hz, zero_hz), 5),
        "morph_oct": round(float(morph_oct), 5),
        "zero_morph_oct": round(float(zero_morph_oct), 5),
        "zero_secondary_oct": 0.0,
        "q_weight": round(clamp(q_weight, 0.0, 1.0), 4),
    }


def convert_contract(path: Path, out_dir: Path) -> Path:
    contract = json.loads(path.read_text(encoding="utf-8"))
    m = metrics(contract)
    family = contract["family"]
    name = f"family_{family}"
    low = fc(contract, "low", 190.0)
    payload = {
        "format": "section-law-v1",
        "name": name,
        "family": family,
        "source_contract": str(path.as_posix()),
        "clean_room_note": "Generated from aggregate family contract bounds only; no reference bytes, coefficient rows, endpoint curves, names, or preset tables are copied.",
        "anchor_hz": round(low, 4),
        "anchor_gain_db": 6.5,
        "tilt_db": round(m["tilt_db"], 4),
        "canyon_depth": round(m["canyon_depth"], 4),
        "q_crank": round(m["q_crank"], 4),
        "morph_spread": round(m["morph_spread"], 4),
        "density": 0.82,
        "sections": family_sections(contract),
        "aggregate_metrics": contract.get("aggregate_metrics", {}),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--contracts",
        type=Path,
        default=ROOT / "dev" / "tmp" / "x3_p2k_family_browser" / "contracts",
        help="folder containing family-reference-contract-v1 JSON files",
    )
    ap.add_argument("--out", type=Path, default=ROOT / "recipes" / "laws")
    args = ap.parse_args(argv)

    paths = sorted(args.contracts.glob("*.json"))
    if not paths:
        print(f"no contract JSONs in {args.contracts}", file=sys.stderr)
        return 1
    for path in paths:
        out = convert_contract(path, args.out)
        print(f"{path} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
