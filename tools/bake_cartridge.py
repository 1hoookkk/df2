#!/usr/bin/env python3
"""Compile a P2K cartridge JSON to kernel-form c0..c4 stage format.

Output stages use {c0, c1, c2, c3, c4} fields readable by Cartridge::from_json
via StageCoeffsJson — bypasses emu_resonator, stays in the Python stage_to_kernel
coefficient convention (all-positive, minifloat-encodable).

Usage:
    python tools/bake_cartridge.py
    python tools/bake_cartridge.py --in ref/p2k_skins/00_talking_hedz.json \
                                   --out dev/bake/00_talking_hedz_compiled.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.coefficient_field_bakeoff import stage_to_kernel

DEFAULT_IN = ROOT / "ref" / "p2k_skins" / "00_talking_hedz.json"
DEFAULT_OUT = ROOT / "dev" / "bake" / "00_talking_hedz_compiled.json"

REQUIRED_LABELS = {"M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"}


def bake(src: Path, dst: Path) -> None:
    data = json.loads(src.read_text())

    found_labels = {kf["label"] for kf in data.get("keyframes", [])}
    missing = REQUIRED_LABELS - found_labels
    if missing:
        raise ValueError(f"Missing keyframes: {missing}")

    compiled_keyframes = []
    for kf in data["keyframes"]:
        if kf["label"] not in REQUIRED_LABELS:
            continue
        raw_stages = kf.get("stages", [])
        compiled_stages = []
        for stage in raw_stages:
            k = stage_to_kernel(stage)
            compiled_stages.append({
                "c0": round(float(k[0]), 9),
                "c1": round(float(k[1]), 9),
                "c2": round(float(k[2]), 9),
                "c3": round(float(k[3]), 9),
                "c4": round(float(k[4]), 9),
            })
        compiled_keyframes.append({
            "label": kf["label"],
            "boost": kf.get("boost", 1.0),
            "stages": compiled_stages,
        })

    out = {
        "name": data["name"],
        "sampleRate": data.get("sampleRate", 39062.5),
        "keyframes": compiled_keyframes,
    }

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=2))
    print(f"baked: {src.name} → {dst}")
    for kf in compiled_keyframes:
        label = kf["label"]
        s0 = kf["stages"][0] if kf["stages"] else {}
        print(f"  {label}: stage0 c0={s0.get('c0', '?'):.6f}  c3={s0.get('c3', '?'):.6f}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", type=Path, default=DEFAULT_IN)
    parser.add_argument("--out", dest="dst", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    bake(args.src, args.dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
