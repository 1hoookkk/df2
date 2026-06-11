#!/usr/bin/env python3
"""Independently verify Forge exact skeleton tables.

This script deliberately does not import tools/make_exact_skeletons.py.
It treats tables/exact_skeletons.json as an external artifact, then checks:

  table JSON -> legacy root params -> trench_core compile_body -> packed_probe

against a freshly rebuilt SciPy reference. The Forge app reads the verification
sidecar and only exposes skeletons whose packed body passed this check.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import scipy.signal as sig

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402

SR = 39_062.5
ORDER = 12
STAGES = 6
AUDIT_N = 17
FREQS = np.geomspace(60.0, 16_000.0, 600)


def db_to_lin(db: float) -> float:
    return 10.0 ** (float(db) / 20.0)


def design_sos(key: str, cutoff_hz: float) -> np.ndarray:
    if key == "butterworth":
        return sig.butter(ORDER, cutoff_hz, btype="low", output="sos", fs=SR)
    if key == "cheby2":
        return sig.cheby2(ORDER, 60.0, cutoff_hz, btype="low", output="sos", fs=SR)
    if key == "elliptic":
        return sig.ellip(ORDER, 1.0, 60.0, cutoff_hz, btype="low", output="sos", fs=SR)
    raise ValueError(f"unknown exact skeleton key: {key}")


def response_db(rows: np.ndarray) -> np.ndarray:
    w = 2.0 * np.pi * FREQS / SR
    z1 = np.exp(-1j * w)
    z2 = np.exp(-2j * w)
    h = np.ones_like(z1)
    for b0, b1, b2, a1, a2 in rows:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def scipy_response_db(key: str, cutoff_hz: float) -> np.ndarray:
    sos = design_sos(key, cutoff_hz)
    _, h = sig.sosfreqz(sos, worN=FREQS, fs=SR)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def params_for_skeleton(skeleton: dict[str, Any]) -> list[float]:
    params: list[float] = []
    # Same corner order as trench_core/compiler.rs and the Rust app.
    # Q100 rows follow the app's Q LINK rule: pole radius moves toward the rim.
    for hi, q_hi in ((False, False), (True, False), (False, True), (True, True)):
        for row in skeleton["sections"]:
            suffix = "hi" if hi else "lo"
            pole_hz = float(row[f"pole_hz_{suffix}"])
            pole_r = float(row[f"pole_r_{suffix}"])
            zero_hz = float(row[f"zero_hz_{suffix}"])
            zero_r = float(row[f"zero_r_{suffix}"])
            gain_db = float(row[f"gain_db_{suffix}"])
            if q_hi:
                pole_r = 1.0 - (1.0 - pole_r) * 0.35
            params.extend(
                [
                    1.0,
                    pole_hz,
                    pole_r,
                    db_to_lin(gain_db),
                    1.0 if zero_r > 0.0001 else 0.0,
                    zero_hz,
                    zero_r,
                ]
            )
    return params


def frame_metrics(body: bytes, key: str, morph: float, cutoff_hz: float) -> dict[str, Any]:
    probe = trench_ffi.packed_probe(body, morph, 0.0)
    packed = response_db(np.asarray(probe["biquad"], dtype=np.float64).reshape(STAGES, 5))
    ref = scipy_response_db(key, cutoff_hz)
    passband = FREQS <= cutoff_hz * 0.85
    active = ref > -70.0
    passband_max = float(np.max(np.abs(packed[passband] - ref[passband])))
    body_max = float(
        np.max(np.abs(np.clip(packed[active], -70.0, None) - np.clip(ref[active], -70.0, None)))
    )
    return {
        "cutoff_hz": float(cutoff_hz),
        "passband_max_db": passband_max,
        "body_max_db": body_max,
        "max_pole_radius": float(probe["max_pole_radius"]),
        "unstable_mask": int(probe["unstable_mask"]),
        "nonfinite_mask": int(probe["nonfinite_mask"]),
    }


def audit_grid(body: bytes) -> dict[str, Any]:
    max_r = 0.0
    unstable = 0
    nonfinite = 0
    for qi in range(AUDIT_N):
        q = qi / (AUDIT_N - 1)
        for mi in range(AUDIT_N):
            m = mi / (AUDIT_N - 1)
            probe = trench_ffi.packed_probe(body, m, q)
            max_r = max(max_r, float(probe["max_pole_radius"]))
            if int(probe["unstable_mask"]):
                unstable += 1
            if int(probe["nonfinite_mask"]):
                nonfinite += 1
    return {"grid": AUDIT_N, "max_pole_radius": max_r, "unstable_cells": unstable, "nonfinite_cells": nonfinite}


def verify(path: Path, passband_limit: float, body_limit: float) -> dict[str, Any]:
    if not trench_ffi.available():
        raise RuntimeError("trench_core is unavailable; run cargo build --release -p trench-core")
    doc = json.loads(path.read_text(encoding="utf-8"))
    results = []
    for skeleton in doc.get("skeletons", []):
        body = trench_ffi.compile_body(params_for_skeleton(skeleton))
        lo = frame_metrics(body, skeleton["key"], 0.0, float(skeleton["f_lo"]))
        hi = frame_metrics(body, skeleton["key"], 1.0, float(skeleton["f_hi"]))
        grid = audit_grid(body)
        passband_max = max(lo["passband_max_db"], hi["passband_max_db"])
        body_max = max(lo["body_max_db"], hi["body_max_db"])
        ok = (
            passband_max <= passband_limit
            and body_max <= body_limit
            and grid["unstable_cells"] == 0
            and grid["nonfinite_cells"] == 0
        )
        results.append(
            {
                "key": skeleton["key"],
                "label": skeleton.get("label", skeleton["key"]),
                "verdict": "PASS" if ok else "FAIL",
                "passband_max_db": passband_max,
                "body_max_db": body_max,
                "grid": grid,
                "frames": {"lo": lo, "hi": hi},
            }
        )
    return {
        "format": "exact-skeleton-independent-verification-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(path.relative_to(ROOT)),
        "runtime": str(trench_ffi.lib_path()) if trench_ffi.lib_path() else None,
        "method": "fresh scipy reference; table JSON compiled through trench_core.compile_body and checked through packed_probe",
        "thresholds": {"passband_max_db": passband_limit, "body_max_db": body_limit, "grid": AUDIT_N},
        "skeletons": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", type=Path, default=ROOT / "tables" / "exact_skeletons.json")
    ap.add_argument("--out", type=Path, default=ROOT / "tables" / "exact_skeletons.verification.json")
    ap.add_argument("--report", type=Path, default=ROOT / "dev" / "tmp" / "exact_skeleton_verification" / "report.json")
    ap.add_argument("--passband-limit-db", type=float, default=0.25)
    ap.add_argument("--body-limit-db", type=float, default=3.0)
    args = ap.parse_args()

    result = verify(args.table, args.passband_limit_db, args.body_limit_db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2)
    args.out.write_text(text + "\n", encoding="utf-8")
    args.report.write_text(text + "\n", encoding="utf-8")

    failures = 0
    for row in result["skeletons"]:
        if row["verdict"] != "PASS":
            failures += 1
        print(
            f"{row['verdict']:4s} {row['key']:<12s} "
            f"passband {row['passband_max_db']:.3f} dB  "
            f"body {row['body_max_db']:.3f} dB  "
            f"max|p| {row['grid']['max_pole_radius']:.6f}"
        )
    print(f"wrote {args.out}")
    print(f"wrote {args.report}")
    if failures:
        print(f"{failures} table(s) failed independent packed verification")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
