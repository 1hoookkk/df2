#!/usr/bin/env python3
"""Build static packed-body data for forge-web.

The browser Forge has no filesystem access, so this script embeds exact
240-byte bodies plus packed words into an ES module. The embedded hex is the
authority; decoded stage tables are readouts only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from tools.author_body import CORNER_ORDER, compiled_payload, words_from_raw  # noqa: E402
from tools.law_author import cascade_db  # noqa: E402

STAGES = 6
WORDS_PER_STAGE = 5
BODY_BYTES = 240


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_jsonable_words(words: dict[str, list[tuple[int, ...]]]) -> dict[str, list[list[int]]]:
    return {k: [[int(v) for v in row] for row in rows] for k, rows in words.items()}


def _root_readout(biquad: tuple[float, ...]) -> dict[str, float | str]:
    b0, b1, b2, a1, a2 = [float(v) for v in biquad]
    poles = np.roots([1.0, a1, a2])
    zeros = np.roots([b0, b1, b2]) if abs(b0) > 1e-15 else np.roots([b1, b2])

    def pick_root(roots: np.ndarray) -> tuple[float, float]:
        if roots.size == 0:
            return 0.0, 0.0
        root = max(roots, key=lambda z: (abs(z), abs(np.angle(z))))
        radius = float(abs(root))
        angle = float(abs(np.angle(root)))
        hz = angle * 39062.5 / (2.0 * math.pi)
        return hz, radius

    pole_hz, pole_r = pick_root(poles)
    zero_hz, zero_r = pick_root(zeros)
    if pole_hz < 250 and pole_r > 0.35:
        role = "low/body anchor"
    elif zero_r > 0.92:
        role = "canyon"
    elif pole_hz > 6000 or zero_hz > 6000:
        role = "air cap"
    elif abs(math.log2(max(pole_hz, 1.0) / max(zero_hz, 1.0))) > 1.5:
        role = "remote-zero counterweight"
    else:
        role = "local peak/canyon"
    return {
        "pole_hz": float(pole_hz),
        "pole_r": float(pole_r),
        "zero_hz": float(zero_hz),
        "zero_r": float(zero_r),
        "gain": float(b0),
        "role": role,
    }


def _readout_from_body(raw: bytes) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for label, morph, q in (
        ("M0_Q0", 0.0, 0.0),
        ("M100_Q0", 1.0, 0.0),
        ("M0_Q100", 0.0, 1.0),
        ("M100_Q100", 1.0, 1.0),
    ):
        probe = trench_ffi.packed_probe(raw, morph, q)
        out[label] = [_root_readout(tuple(row)) for row in probe["biquad"]]
    return out


def _audit(raw: bytes, grid_n: int = 17) -> dict[str, Any]:
    points = np.linspace(0.0, 1.0, grid_n)
    cells: list[dict[str, Any]] = []
    heat = np.zeros((grid_n, grid_n))
    max_radius = 0.0
    unstable = False
    nonfinite = False
    for qi, q in enumerate(points):
        for mi, morph in enumerate(points):
            probe = trench_ffi.packed_probe(raw, float(morph), float(q))
            db = cascade_db(probe["biquad"])
            heat[qi, mi] = float(np.nanmax(db) - np.nanmin(db))
            max_radius = max(max_radius, float(probe["max_pole_radius"]))
            cell_unstable = int(probe["unstable_mask"]) != 0
            cell_nonfinite = int(probe["nonfinite_mask"]) != 0 or not bool(np.all(np.isfinite(db)))
            unstable = unstable or cell_unstable
            nonfinite = nonfinite or cell_nonfinite
            cells.append({
                "morph": round(float(morph), 4),
                "secondary": round(float(q), 4),
                "max_pole_radius": float(probe["max_pole_radius"]),
                "unstable_mask": int(probe["unstable_mask"]),
                "nonfinite_mask": int(probe["nonfinite_mask"]),
                "response_span_db": float(heat[qi, mi]),
            })
    warnings: list[str] = []
    if unstable:
        warnings.append("packed probe found unstable stage(s)")
    if nonfinite:
        warnings.append("packed probe found nonfinite response/stage(s)")
    if max_radius >= 1.0:
        warnings.append(f"max pole radius reached instability: {max_radius:.6f}")
    return {
        "grid_n": grid_n,
        "checks": {
            "stable": not unstable,
            "finite_response": not nonfinite,
            "max_pole_radius": max_radius,
        },
        "warnings": warnings,
        "grid": cells,
        "heatmap_response_span_db": heat.tolist(),
        "verdict": "PASS" if not warnings else "WARN",
    }


def _body_entry(
    *,
    key: str,
    name: str,
    source: Path,
    kind: str,
    law_path: Path | None = None,
    stages_path: Path | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    raw = source.read_bytes()
    if len(raw) != BODY_BYTES:
        raise ValueError(f"{source} is {len(raw)} bytes; expected {BODY_BYTES}")
    words = words_from_raw(raw)
    stages = _read_json(stages_path) if stages_path and stages_path.exists() else _readout_from_body(raw)
    audit = _read_json(audit_path) if audit_path and audit_path.exists() else _audit(raw)
    return {
        "key": key,
        "name": name,
        "kind": kind,
        "sourcePath": str(source.as_posix()),
        "body240Bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "body240Hex": raw.hex(),
        "cornerOrder": list(CORNER_ORDER),
        "cornerLabels": ["C0", "C1", "C2", "C3"],
        "words": _as_jsonable_words(words),
        "compiled": compiled_payload(name, 1.0, words),
        "law": _read_json(law_path) if law_path and law_path.exists() else None,
        "stages": stages,
        "audit": audit,
    }


def build(out: Path) -> None:
    law_dir = ROOT / "dev" / "tmp" / "law_author" / "golden_hedz_like"
    data = {
        "lawAuthorGolden": _body_entry(
            key="lawAuthorGolden",
            name="hedz_like_anchor_canyons",
            source=law_dir / "hedz_like_anchor_canyons.body240",
            kind="law-author",
            law_path=law_dir / "law_source.json",
            stages_path=law_dir / "stages.json",
            audit_path=law_dir / "audit.json",
        ),
        "talkingHedzOriginal": _body_entry(
            key="talkingHedzOriginal",
            name="P2k_013_talking_hedz_original",
            source=ROOT / "ref" / "presets" / "P2k_013_talking_hedz.bin",
            kind="original-reference",
        ),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "export const PACKED_BODIES = "
    text += json.dumps(data, indent=2, sort_keys=True)
    text += ";\n"
    out.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "forge-web" / "data" / "packed-bodies.js")
    args = ap.parse_args()
    build(args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
