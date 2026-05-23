#!/usr/bin/env python3
"""Packed-domain interpolation verification report.

Verifies that pyruntime/packed_interp.py matches the coefficient_field_bakeoff
oracle at selected M/Q positions, and reports decoded-float vs packed-domain
coefficient and null differences at midpoint.

Outputs:
  dev/tmp/packed_interp_report_<timestamp>.md

Usage:
    python tools/packed_interp_report.py
    python tools/packed_interp_report.py --cartridge path/to/cartridge.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import sosfilt

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.packed_interp import (
    build_corner_words_from_coeffs,
    packed_bilinear,
    decode,
    encode,
    lerp_u16,
)
from tools.coefficient_field_bakeoff import (
    load_corner_coeffs,
    kernel_to_words,
    kernel_to_sos,
    packed_oracle,
    decoded_float_baseline,
    null_depth,
    deterministic_pink,
)

DEFAULT_CARTRIDGE = ROOT / "ref" / "p2k_skins" / "00_talking_hedz.json"
DEFAULT_OUT = ROOT / "dev" / "tmp"
SR = 44100
EPS = 1e-30


# ── helpers ───────────────────────────────────────────────────────────────────


def np_words_to_scalar(np_arr: np.ndarray) -> list[tuple[int, ...]]:
    """Convert numpy [stages × 5] u16 array to list of 5-tuples of Python ints."""
    return [tuple(int(w) for w in row) for row in np_arr]


def scalar_coeffs_to_np(stage_tuples: list[tuple[float, ...]]) -> np.ndarray:
    return np.array(stage_tuples, dtype=np.float64)


def render_audio(coeffs_np: np.ndarray, dry: np.ndarray) -> np.ndarray:
    sos = kernel_to_sos(coeffs_np)
    out = sosfilt(sos, dry.astype(np.float64))
    np.nan_to_num(out, copy=False, nan=0.0, posinf=1.0, neginf=-1.0)
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0.99:
        out = out * (0.99 / peak)
    return out.astype(np.float32)


# ── verification ──────────────────────────────────────────────────────────────


def verify_lerp_u16_scalar_vs_numpy() -> list[str]:
    """Check scalar lerp_u16 matches the numpy oracle for a sample of inputs."""
    issues = []
    test_cases = [
        (0x0000, 0x0000, 0.5),
        (0x0000, 0xFFFF, 0.0),
        (0x0000, 0xFFFF, 1.0),
        (0x1000, 0x3000, 0.5),
        (0x4000, 0xC000, 0.25),
        (0x8000, 0xFFFF, 0.75),
        (0x0100, 0xFF00, 0.333),
        (0x0000, 0xFFFF, 0.5),
    ]
    for a, b, frac in test_cases:
        scalar = lerp_u16(a, b, frac)
        # numpy oracle from bakeoff
        ai, bi = np.int64(a), np.int64(b)
        trunc = np.trunc((bi - ai).astype(np.float32) * np.float32(frac)).astype(np.int64)
        delta_i16 = int(((trunc + 0x8000) % 0x10000) - 0x8000)
        numpy_result = int((ai + delta_i16) & 0xFFFF)
        if scalar != numpy_result:
            issues.append(
                f"lerp_u16({a:#06x}, {b:#06x}, {frac}): "
                f"scalar={scalar:#06x} numpy={numpy_result:#06x}"
            )
    return issues


def compare_packed_at_point(
    corner_words_np: dict[str, np.ndarray],
    corner_coeffs_scalar: dict[str, list[tuple[float, ...]]],
    morph: float,
    q: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Run both oracle paths and return (oracle_coeffs, scalar_coeffs, max_abs_diff)."""
    oracle_np = packed_oracle(corner_words_np, morph, q)  # [stages × 5] ndarray

    scalar_words = build_corner_words_from_coeffs(corner_coeffs_scalar)
    scalar_result = packed_bilinear(scalar_words, morph, q)
    scalar_np = scalar_coeffs_to_np(scalar_result)

    max_diff = float(np.max(np.abs(oracle_np - scalar_np)))
    return oracle_np, scalar_np, max_diff


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cartridge", type=Path, default=DEFAULT_CARTRIDGE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.out / f"packed_interp_report_{timestamp}.md"
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"cartridge: {args.cartridge}")

    # ── load cartridge ──
    corner_coeffs_np, _ = load_corner_coeffs(args.cartridge)
    # corner_coeffs_np is dict A/B/C/D → numpy [stages × 5] float64

    corner_words_np = {name: kernel_to_words(coeffs) for name, coeffs in corner_coeffs_np.items()}

    # Build scalar form for packed_interp.py
    corner_coeffs_scalar = {
        name: [tuple(float(v) for v in row) for row in coeffs]
        for name, coeffs in corner_coeffs_np.items()
    }

    # ── verify lerp_u16 scalar vs numpy ──
    print("verifying lerp_u16 scalar vs numpy oracle...")
    lerp_issues = verify_lerp_u16_scalar_vs_numpy()
    lerp_ok = len(lerp_issues) == 0

    # ── verify packed_bilinear vs bakeoff oracle at test points ──
    test_points = [
        ("diag_25",      0.25,    0.25),
        ("diag_50",      0.50,    0.50),
        ("diag_75",      0.75,    0.75),
        ("offset_25",    0.21875, 0.21875),
        ("offset_50",    0.46875, 0.46875),
        ("offset_75",    0.71875, 0.71875),
    ]

    match_rows = []
    for label, morph, q in test_points:
        oracle_np, scalar_np, max_diff = compare_packed_at_point(
            corner_words_np, corner_coeffs_scalar, morph, q
        )
        passed = max_diff < 1e-9
        match_rows.append({
            "label": label,
            "morph": morph,
            "q": q,
            "max_abs_diff": max_diff,
            "passed": passed,
        })
        status = "PASS" if passed else "FAIL"
        print(f"  {label} morph={morph:.5f} q={q:.5f}: max|Δ|={max_diff:.2e}  {status}")

    # ── midpoint comparison: decoded-float vs packed ──
    morph_mid, q_mid = 0.5, 0.5
    oracle_mid = packed_oracle(corner_words_np, morph_mid, q_mid)
    baseline_mid = decoded_float_baseline(corner_coeffs_np, morph_mid, q_mid)

    coeff_diff_mid = oracle_mid - baseline_mid
    max_coeff_diff = float(np.max(np.abs(coeff_diff_mid)))

    # ── render null at midpoint ──
    dry = deterministic_pink(3.0)
    oracle_audio = render_audio(oracle_mid, dry)
    baseline_audio = render_audio(baseline_mid, dry)
    null_db = null_depth(oracle_audio, baseline_audio)

    # ── report ──
    all_passed = lerp_ok and all(r["passed"] for r in match_rows)

    lines = [
        "# Packed-Domain Interpolation Report",
        "",
        f"- Timestamp: {timestamp}",
        f"- Cartridge: `{args.cartridge.name}` (derived-packed-canonical, not raw ROM words)",
        f"- Oracle: `tools/coefficient_field_bakeoff.py::packed_oracle`",
        f"- Candidate: `pyruntime/packed_interp.py::packed_bilinear`",
        "",
        "## lerp_u16 Scalar vs NumPy Oracle",
        "",
        f"Result: {'PASS — all test cases match' if lerp_ok else 'FAIL'}",
    ]
    if lerp_issues:
        lines.append("")
        for issue in lerp_issues:
            lines.append(f"  - {issue}")

    lines += [
        "",
        "## packed_bilinear vs Oracle at Test Points",
        "",
        "| point | morph | q | max |Δ| | result |",
        "|---|---:|---:|---:|---|",
    ]
    for r in match_rows:
        status = "PASS" if r["passed"] else "FAIL"
        lines.append(
            f"| {r['label']} | {r['morph']:.5f} | {r['q']:.5f} "
            f"| {r['max_abs_diff']:.2e} | {status} |"
        )

    lines += [
        "",
        "## Midpoint Decoded-Float vs Packed-Domain (M=0.5, Q=0.5)",
        "",
        "### Per-stage coefficient differences (packed − decoded-float)",
        "",
        "| stage | Δc0 | Δc1 | Δc2 | Δc3 | Δc4 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for si in range(oracle_mid.shape[0]):
        d = coeff_diff_mid[si]
        lines.append(
            f"| {si} | {d[0]:+.6f} | {d[1]:+.6f} | {d[2]:+.6f} "
            f"| {d[3]:+.6f} | {d[4]:+.6f} |"
        )

    lines += [
        "",
        f"Max |Δ| across all coefficients: **{max_coeff_diff:.6f}**",
        "",
        "### Render null: packed oracle vs decoded-float baseline",
        "",
        f"Null depth: **{null_db:.2f} dB**",
        "",
        "(< −60 dB = inaudible difference; > −30 dB = audible divergence)",
        "",
        "## Overall",
        "",
        f"**{'PASS' if all_passed else 'FAIL'}** — "
        f"scalar matches oracle: {'yes' if lerp_ok else 'NO'}; "
        f"all point matches: {'yes' if all(r['passed'] for r in match_rows) else 'NO'}",
    ]

    report_text = "\n".join(lines) + "\n"
    out_path.write_text(report_text)
    print(f"\nwrote: {out_path}")
    print(f"midpoint null (packed vs decoded-float): {null_db:.2f} dB")
    print(f"overall: {'PASS' if all_passed else 'FAIL'}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
