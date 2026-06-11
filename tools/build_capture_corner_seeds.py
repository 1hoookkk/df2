#!/usr/bin/env python3
"""Build static Forge web corner seeds from synthetic capture fixtures.

The generated module is intentionally a projection into the shipped
`compile_body` parameter space, not a claim that arbitrary SOS rows null back to
their source coefficients. The editor still packs through trench-core/WASM.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "forge-web" / "data" / "corner-captures.js"
FIXTURES = [
    (
        "synthetic_throat_u_to_a",
        "Synthetic throat /u/ -> /a/",
        ROOT / "dev" / "tmp" / "synthetic_throat_captures" / "ground_truth.json",
    ),
    (
        "synthetic_mountains_throat",
        "Synthetic mountains throat /u/ -> /i/",
        ROOT / "dev" / "tmp" / "synthetic_mountains_throat_captures" / "ground_truth.json",
    ),
]

CORNER_KEYS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
F_MIN = 30.0
F_MAX = 16000.0
RP_MIN = 0.5
RP_MAX = 0.9992
RZ_MIN = 0.0
RZ_MAX = 0.9995
G_DB_MIN = -26.0
G_DB_MAX = 12.0


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def root_pair(coeffs: list[float], sr: float) -> tuple[float, float]:
    roots = np.roots(coeffs)
    root = max(roots, key=lambda z: (abs(z), abs(np.angle(z))))
    radius = float(abs(root))
    angle = float(abs(np.angle(root)))
    hz = angle * sr / (2.0 * math.pi)
    return clamp(hz, F_MIN, F_MAX), radius


def db(value: float) -> float:
    return 20.0 * math.log10(max(1.0e-12, float(value)))


def section_from_sos(row: list[float], sr: float, role: str) -> dict:
    b0, b1, b2, a0, a1, a2 = (float(v) for v in row)
    if abs(a0) < 1.0e-12:
        a0 = 1.0
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
    pole_hz, pole_r = root_pair([1.0, a1, a2], sr)

    if abs(b0) < 1.0e-12 or (abs(b1) < 1.0e-12 and abs(b2) < 1.0e-12):
        zero_hz, zero_r = F_MAX, 0.0
        # This follows trench-core's all-pole branch. It is often lossy because
        # the compiler clamps gain to +12 dB.
        gain = b0 / max(1.0e-9, 1.0 - pole_r * pole_r)
        mode = "all-pole projected"
    else:
        nb1, nb2 = b1 / b0, b2 / b0
        zero_hz, zero_r = root_pair([1.0, nb1, nb2], sr)
        den_dc = 1.0 + a1 + a2
        num_dc = 1.0 + nb1 + nb2
        gain = b0 * num_dc / max(1.0e-9, den_dc)
        mode = "pole-zero projected"

    gain_db = clamp(db(gain), G_DB_MIN, G_DB_MAX)
    clamped = (
        pole_r < RP_MIN or pole_r > RP_MAX or zero_r < RZ_MIN or zero_r > RZ_MAX
        or db(gain) < G_DB_MIN or db(gain) > G_DB_MAX
    )
    return {
        "role": role,
        "pf": round(clamp(pole_hz, F_MIN, F_MAX), 6),
        "pr": round(clamp(pole_r, RP_MIN, RP_MAX), 9),
        "zf": round(clamp(zero_hz, F_MIN, F_MAX), 6),
        "zr": round(clamp(zero_r, RZ_MIN, RZ_MAX), 9),
        "gainDb": round(gain_db, 6),
        "on": True,
        "mode": mode,
        "clamped": bool(clamped),
    }


def roles_for_corner(corner: dict, count: int) -> list[str]:
    if "actors" in corner:
        roles = [str(actor.get("name") or f"S{i + 1}") for i, actor in enumerate(corner["actors"])]
    elif "formants" in corner:
        roles = [str(formant.get("name") or f"F{i + 1}") for i, formant in enumerate(corner["formants"])]
    else:
        roles = [f"S{i + 1}" for i in range(count)]
    return roles[:count]


def fixture_to_seed(seed_id: str, name: str, path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sr = float(doc.get("sample_rate_hz", 44100.0))
    corners = doc["corners"]
    first = corners[CORNER_KEYS[0]]
    count = min(6, len(first.get("sos", [])))
    roles = roles_for_corner(first, count)
    sections = []
    for si in range(count):
        section = {"role": roles[si], "on": True, "corners": {}}
        for key in CORNER_KEYS:
            role = roles_for_corner(corners[key], count)[si]
            corner = section_from_sos(corners[key]["sos"][si], sr, role)
            section["corners"][key] = {k: corner[k] for k in ("pf", "pr", "zf", "zr", "gainDb")}
        sections.append(section)
    while len(sections) < 6:
        sections.append({
            "role": "BYPASS",
            "on": False,
            "corners": {
                key: {"pf": 9000.0, "pr": 0.5, "zf": 16000.0, "zr": 0.0, "gainDb": 0.0}
                for key in CORNER_KEYS
            },
        })
    clamped = any(
        section_from_sos(corners[key]["sos"][si], sr, roles_for_corner(corners[key], count)[si])["clamped"]
        for key in CORNER_KEYS
        for si in range(count)
    )
    return {
        "id": seed_id,
        "name": name,
        "source": str(path.relative_to(ROOT)).replace("\\", "/"),
        "claim": doc.get("claim", ""),
        "axes": doc.get("axes", {}),
        "projection": "source SOS roots projected into trench-core compile_body corner params",
        "lossy": bool(clamped),
        "cornerLabels": {
            key: str(corners[key].get("label", key))
            for key in CORNER_KEYS
        },
        "sections": sections,
    }


def main() -> None:
    seeds = [fixture_to_seed(*item) for item in FIXTURES]
    text = (
        "// Generated by tools/build_capture_corner_seeds.py. Do not edit by hand.\n"
        "// Source fixtures are clean-room synthetic captures; values are projected\n"
        "// into the compile_body 4-corner root-domain parameter space.\n"
        "export const CAPTURE_CORNER_SETS = "
        + json.dumps(seeds, indent=2)
        + ";\n"
    )
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
