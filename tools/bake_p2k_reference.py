#!/usr/bin/env python3
"""Bake a heritage P2K skin (datasets `corners` format) into a Forge reference
kernel file: 4 corners x 6 stages of c0..c4, in PackedCorners index order
[M0_Q0, M100_Q0, M0_Q100, M100_Q100].

Reference / dev only — never shipped. The Forge loads this as the green
"truth" silhouette in its midpoint scope so an authored body can be read
against a real skin (the "match or beat P2K" gate).

This uses ONLY `stage_to_kernel` (the algebraic {a1,r,val1,val2,val3} ->
kernel recombination already validated on Talking Hedz). The skin JSON is
already coefficient data, so the untested XML Type-2/3 firmware compiler is
NOT involved.

Usage:
    python tools/bake_p2k_reference.py \
        --in ../trenchwork_clean/datasets/p2k_skins/P2k_003.json \
        --out ref/p2k_skins/P2k_003.kernels.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.coefficient_field_bakeoff import stage_to_kernel

SR = 39062.5
ORDER = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
PASSTHROUGH = [2.0, 1.0, 2.0, 1.0, 1.0]


def pole_freq(a1: float, r: float) -> float:
    x = max(-1.0, min(1.0, -a1 / (2.0 * r))) if r > 0 else 1.0
    return math.acos(x) * SR / (2.0 * math.pi)


def bake(src: Path, dst: Path) -> None:
    data = json.loads(src.read_text())
    corners_in = data["corners"]
    missing = [c for c in ORDER if c not in corners_in]
    if missing:
        raise ValueError(f"{src.name}: missing corners {missing}")

    out_corners = []
    print(f"{data.get('name', src.stem)}  filterType={data.get('filterType')}  "
          f"stages={data.get('stageCount')}  boost={data.get('boost')}")
    for label in ORDER:
        raw = corners_in[label]["stages"]
        kernels = []
        freqs = []
        for st in raw[:6]:
            k = stage_to_kernel(st)
            kernels.append([round(float(v), 9) for v in k])
            freqs.append(pole_freq(float(st["a1"]), float(st["r"])))
        while len(kernels) < 6:
            kernels.append(list(PASSTHROUGH))
        out_corners.append(kernels)
        print(f"  {label:>10}: poles " + " ".join(f"{f:6.0f}" for f in freqs))

    out = {
        "name": data.get("name", src.stem),
        "sampleRate": data.get("sampleRate", SR),
        "note": "reference only — heritage skin baked via stage_to_kernel; never shipped",
        "corners": out_corners,
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=2))
    print(f"baked -> {dst}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in", dest="src", type=Path, required=True)
    p.add_argument("--out", dest="dst", type=Path, required=True)
    a = p.parse_args(argv)
    bake(a.src, a.dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
