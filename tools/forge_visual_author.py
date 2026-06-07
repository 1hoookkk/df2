#!/usr/bin/env python3
"""Minimal Python authoring workbench for DF2 Forge.

One command writes a session directory:

    dev/tmp/forge_visual_author/<session>/
      target.json
      fitted_lanes.json
      law_source.json
      body.body240
      cartridge.json
      audit.json
      response.png
      workbench.html

The workbench is intentionally small:

1. Read a target magnitude curve, or use a clean default target.
2. Fit each corner with the shipped trench_core magnitude fitter.
3. Convert fitted biquads back into authorable pole/zero/gain lanes.
4. Repack those lanes through tools.author_lanes.
5. Audit and plot from the packed body through trench_core.

It is not a P2K copier. Study data can be converted into a target JSON later,
but this script only consumes target curves and emits clean-room authoring
artifacts.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.packed_interp import kernel_to_biquad  # noqa: E402
from tools import author_body  # noqa: E402
from tools.author_lanes import AUTHORING_SR, body_to_packed_v1, lane_biquad  # noqa: E402

CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
CORNER_TO_MQ = {
    "M0_Q0": (0.0, 0.0),
    "M100_Q0": (1.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q100": (1.0, 1.0),
}
STAGES = 6
FREQS = np.geomspace(30.0, AUTHORING_SR * 0.49, 620)
FIT_FREQS = np.geomspace(40.0, 16000.0, 192)
POLE_R_MAX = 0.9999
ZERO_R_MAX = 0.9985
GAIN_LO = 0.025
GAIN_HI = 3.75
FIT_HZ_LO = 24.0
FIT_HZ_HI = AUTHORING_SR * 0.48
ROLE_BY_INDEX = (
    "low_foundation",
    "low_mid_body",
    "mid_formant",
    "upper_bite",
    "high_restraint",
    "remote_counterweight",
)


@dataclass(frozen=True)
class FitProduct:
    target: dict[str, Any]
    corners: dict[str, list[dict[str, Any]]]
    body: bytes
    cartridge: dict[str, Any]
    audit: dict[str, Any]
    heatmap: list[list[float]]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def hz_fmt(hz: float) -> str:
    return f"{hz / 1000.0:.2f}k" if hz >= 1000.0 else f"{hz:.0f}"


def default_target() -> dict[str, Any]:
    """A clean-room starter target with four corners.

    The curves are deliberately simple. This is a workbench smoke test, not a
    claim about any reference preset.
    """
    points = [
        [40, -20],
        [200, -8],
        [700, 2],
        [3000, -6],
        [16000, -20],
    ]
    return {
        "format": "forge-visual-target-v1",
        "name": "basic_foundation",
        "source": "clean-hand-target",
        "authoring_sample_rate_hz": AUTHORING_SR,
        "notes": "Small stable smoke target for proving target -> lanes -> body240 -> audit.",
        "corners": {
            "M0_Q0": {"points": points},
            "M100_Q0": {"points": points},
            "M0_Q100": {"points": points},
            "M100_Q100": {"points": points},
        },
    }


def load_target(path: Path | None) -> dict[str, Any]:
    if path is None:
        return normalize_target(default_target())
    return normalize_target(json.loads(path.read_text(encoding="utf-8")))


def normalize_point(point: Any) -> list[float]:
    if isinstance(point, dict):
        hz = point.get("hz", point.get("freq", point.get("frequency_hz")))
        db = point.get("db", point.get("gain_db", point.get("magnitude_db")))
    elif isinstance(point, (list, tuple)) and len(point) >= 2:
        hz, db = point[0], point[1]
    else:
        raise ValueError(f"bad target point: {point!r}")
    return [round(clamp(float(hz), 24.0, AUTHORING_SR * 0.49), 6), round(float(db), 6)]


def normalize_points(points: Any) -> list[list[float]]:
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("target points must contain at least two [hz, db] entries")
    out = [normalize_point(p) for p in points]
    out.sort(key=lambda p: p[0])
    dedup: list[list[float]] = []
    for hz, db in out:
        if dedup and abs(dedup[-1][0] - hz) < 1e-9:
            dedup[-1][1] = db
        else:
            dedup.append([hz, db])
    return dedup


def normalize_target(data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "forge_visual_author")
    base_points = data.get("points")
    corners_in = data.get("corners")
    corners: dict[str, dict[str, Any]] = {}
    if isinstance(corners_in, dict):
        for label in CORNER_ORDER:
            entry = corners_in.get(label)
            if entry is None:
                if base_points is None:
                    raise ValueError(f"target missing corners.{label}")
                points = base_points
            elif isinstance(entry, dict):
                points = entry.get("points", entry.get("anchors"))
            else:
                points = entry
            corners[label] = {"points": normalize_points(points)}
    else:
        if base_points is None:
            raise ValueError("target requires either points or corners")
        points = normalize_points(base_points)
        corners = {label: {"points": points} for label in CORNER_ORDER}

    return {
        "format": "forge-visual-target-v1",
        "name": name,
        "source": str(data.get("source") or "target-json"),
        "authoring_sample_rate_hz": AUTHORING_SR,
        "notes": str(data.get("notes") or ""),
        "corners": corners,
    }


def target_curve(points: list[list[float]], freqs: np.ndarray) -> np.ndarray:
    hz = np.array([p[0] for p in points], dtype=float)
    db = np.array([p[1] for p in points], dtype=float)
    return np.interp(np.log(freqs), np.log(hz), db, left=db[0], right=db[-1])


def pair_from_roots(a: float, b: float, *, radius_max: float) -> tuple[float, float, str]:
    roots = np.roots([1.0, float(a), float(b)])
    root = sorted(roots, key=lambda z: (abs(np.imag(z)) < 1e-8, -abs(z)))[0]
    angle = abs(float(np.angle(root)))
    if angle > math.pi:
        angle = (2.0 * math.pi) - angle
    hz = angle * AUTHORING_SR / (2.0 * math.pi)
    hz = clamp(hz, 24.0, AUTHORING_SR * 0.48)
    radius = clamp(abs(root), 0.05, radius_max)
    kind = "complex_pair" if abs(np.imag(root)) >= 1e-8 else "real_pair_collapsed"
    return hz, radius, kind


def lane_from_kernel(row: tuple[float, ...], index: int) -> dict[str, Any]:
    b0, b1, b2, a1, a2 = kernel_to_biquad(row)
    pole_hz, pole_r, pole_kind = pair_from_roots(a1, a2, radius_max=POLE_R_MAX)
    if abs(b0) < 1e-9:
        zero_hz, zero_r, zero_kind = pole_hz, 0.25, "fallback_zero"
        gain = 0.025
    else:
        zero_hz, zero_r, zero_kind = pair_from_roots(b1 / b0, b2 / b0, radius_max=ZERO_R_MAX)
        gain = clamp(abs(b0), GAIN_LO, GAIN_HI)
    return {
        "role": ROLE_BY_INDEX[min(index, len(ROLE_BY_INDEX) - 1)],
        "pole_hz": round(pole_hz, 4),
        "pole_r": round(clamp(pole_r, 0.18, POLE_R_MAX), 7),
        "zero_hz": round(zero_hz, 4),
        "zero_r": round(clamp(zero_r, 0.05, ZERO_R_MAX), 7),
        "gain": round(gain, 7),
        "fit_readback": {
            "pole_kind": pole_kind,
            "zero_kind": zero_kind,
            "source_kernel": [float(v) for v in row],
        },
    }


def root_response_db(lanes: list[dict[str, Any]], freqs: np.ndarray) -> np.ndarray:
    w = 2.0 * np.pi * freqs / AUTHORING_SR
    z1 = np.exp(-1j * w)
    z2 = np.exp(-2j * w)
    total = np.zeros_like(freqs)
    for lane in lanes:
        b0, b1, b2, a1, a2 = lane_biquad(
            pole_hz=lane["pole_hz"],
            pole_r=lane["pole_r"],
            zero_hz=lane["zero_hz"],
            zero_r=lane["zero_r"],
            gain=lane["gain"],
            sr=AUTHORING_SR,
        )
        num = b0 + b1 * z1 + b2 * z2
        den = 1.0 + a1 * z1 + a2 * z2
        total += 20.0 * np.log10(np.maximum(np.abs(num) / np.maximum(np.abs(den), 1e-12), 1e-12))
    return np.nan_to_num(total, nan=0.0, posinf=120.0, neginf=-120.0)


def vector_from_lanes(lanes: list[dict[str, Any]]) -> np.ndarray:
    values: list[float] = []
    for lane in lanes:
        values.extend(
            [
                math.log(clamp(lane["pole_hz"], FIT_HZ_LO, FIT_HZ_HI)),
                clamp(lane["pole_r"], 0.18, POLE_R_MAX),
                math.log(clamp(lane["zero_hz"], FIT_HZ_LO, FIT_HZ_HI)),
                clamp(lane["zero_r"], 0.05, ZERO_R_MAX),
                math.log(clamp(lane["gain"], GAIN_LO, GAIN_HI)),
            ]
        )
    return np.array(values, dtype=float)


def lanes_from_vector(vec: np.ndarray) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for i in range(STAGES):
        off = i * 5
        lanes.append(
            {
                "lane": i + 1,
                "role": ROLE_BY_INDEX[min(i, len(ROLE_BY_INDEX) - 1)],
                "pole_hz": round(clamp(math.exp(float(vec[off])), FIT_HZ_LO, FIT_HZ_HI), 4),
                "pole_r": round(clamp(float(vec[off + 1]), 0.18, POLE_R_MAX), 7),
                "zero_hz": round(clamp(math.exp(float(vec[off + 2])), FIT_HZ_LO, FIT_HZ_HI), 4),
                "zero_r": round(clamp(float(vec[off + 3]), 0.05, ZERO_R_MAX), 7),
                "gain": round(clamp(math.exp(float(vec[off + 4])), GAIN_LO, GAIN_HI), 7),
            }
        )
    return lanes


def optimizer_bounds() -> tuple[np.ndarray, np.ndarray]:
    lo: list[float] = []
    hi: list[float] = []
    for _ in range(STAGES):
        lo.extend([math.log(FIT_HZ_LO), 0.18, math.log(FIT_HZ_LO), 0.05, math.log(GAIN_LO)])
        hi.extend([math.log(FIT_HZ_HI), POLE_R_MAX, math.log(FIT_HZ_HI), ZERO_R_MAX, math.log(GAIN_HI)])
    return np.array(lo, dtype=float), np.array(hi, dtype=float)


def heuristic_lanes(points: list[list[float]]) -> list[dict[str, Any]]:
    lo_hz = max(50.0, min(p[0] for p in points))
    hi_hz = min(12000.0, max(p[0] for p in points))
    if hi_hz <= lo_hz:
        hi_hz = min(FIT_HZ_HI, lo_hz * 32.0)
    centers = np.geomspace(lo_hz, hi_hz, STAGES)
    curve = target_curve(points, centers)
    mid = float(np.median(curve))
    lanes = []
    for i, (fc, db) in enumerate(zip(centers, curve)):
        pressure = clamp(abs(float(db) - mid) / 30.0, 0.0, 1.0)
        positive = float(db) >= mid
        lanes.append(
            {
                "lane": i + 1,
                "role": ROLE_BY_INDEX[min(i, len(ROLE_BY_INDEX) - 1)],
                "pole_hz": round(float(fc), 4),
                "pole_r": round(0.70 + 0.22 * pressure, 7),
                "zero_hz": round(clamp(float(fc) * (0.68 if positive else 1.0), FIT_HZ_LO, FIT_HZ_HI), 4),
                "zero_r": round(0.42 + (0.48 * pressure if not positive else 0.18 * pressure), 7),
                "gain": round(clamp(0.28 * (10.0 ** (float(db) / 80.0)), GAIN_LO, GAIN_HI), 7),
            }
        )
    return lanes


def optimize_root_lanes(seed_lanes: list[dict[str, Any]], target_db: np.ndarray) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lo, hi = optimizer_bounds()
    x0 = np.minimum(np.maximum(vector_from_lanes(seed_lanes), lo), hi)

    def residual(vec: np.ndarray) -> np.ndarray:
        lanes = lanes_from_vector(vec)
        model = root_response_db(lanes, FIT_FREQS)
        main = (model - target_db) / 6.0
        # Small, explicit pressure against pathological all-rim/all-gain fits.
        regs: list[float] = []
        for i in range(STAGES):
            off = i * 5
            pole_r = float(vec[off + 1])
            regs.append((pole_r - 0.93) * 0.08)
            regs.append((float(vec[off + 3]) - 0.82) * 0.035)
            regs.append(math.exp(float(vec[off + 4])) * 0.015)
        return np.concatenate([main, np.array(regs, dtype=float)])

    result = least_squares(
        residual,
        x0,
        bounds=(lo, hi),
        loss="soft_l1",
        f_scale=1.0,
        max_nfev=900,
        xtol=1e-5,
        ftol=1e-5,
        gtol=1e-5,
    )
    lanes = lanes_from_vector(result.x)
    lanes.sort(key=lambda row: row["pole_hz"])
    for i, lane in enumerate(lanes):
        lane["lane"] = i + 1
        lane["role"] = ROLE_BY_INDEX[min(i, len(ROLE_BY_INDEX) - 1)]
    model = root_response_db(lanes, FIT_FREQS)
    stats = residual_stats(target_db, model)
    return lanes, {
        "success": bool(result.success),
        "status": int(result.status),
        "cost": float(result.cost),
        "nfev": int(result.nfev),
        "root_domain_fit": stats,
    }


def fit_corner(points: list[list[float]]) -> list[dict[str, Any]]:
    curve = target_curve(points, FIT_FREQS)
    rows = trench_ffi.fit_corner_from_magnitude(list(zip(FIT_FREQS.tolist(), curve.tolist())), AUTHORING_SR)
    ffi_seed = [lane_from_kernel(tuple(float(v) for v in row), i) for i, row in enumerate(rows)]
    heuristic_seed = heuristic_lanes(points)

    candidates = []
    for seed_name, seed in (("ffi-root-readback", ffi_seed), ("heuristic-log-rails", heuristic_seed)):
        lanes, opt = optimize_root_lanes(seed, curve)
        candidates.append((opt["root_domain_fit"]["p95_abs_error_db"], seed_name, lanes, opt))
    _score, _seed_name, lanes, _opt = min(candidates, key=lambda item: item[0])
    return lanes


def response_db(body: bytes, morph: float, q: float, freqs: np.ndarray = FREQS) -> np.ndarray:
    probe = trench_ffi.packed_probe(body, float(morph), float(q))
    w = 2.0 * np.pi * freqs / AUTHORING_SR
    z1 = np.exp(-1j * w)
    z2 = np.exp(-2j * w)
    total = np.zeros_like(freqs)
    for b0, b1, b2, a1, a2 in probe["biquad"]:
        num = b0 + b1 * z1 + b2 * z2
        den = 1.0 + a1 * z1 + a2 * z2
        total += 20.0 * np.log10(np.maximum(np.abs(num) / np.maximum(np.abs(den), 1e-12), 1e-12))
    return total


def residual_stats(target_db: np.ndarray, packed_db: np.ndarray) -> dict[str, float]:
    err = np.asarray(packed_db - target_db, dtype=float)
    abs_err = np.abs(err)
    return {
        "mean_error_db": round(float(np.mean(err)), 3),
        "median_abs_error_db": round(float(np.median(abs_err)), 3),
        "p95_abs_error_db": round(float(np.percentile(abs_err, 95.0)), 3),
        "max_abs_error_db": round(float(np.max(abs_err)), 3),
    }


def make_packed(name: str, corners: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, list[tuple[int, ...]]], bytes, dict[str, Any]]:
    doc = body_to_packed_v1(name, corners, boost=1.0, sr=AUTHORING_SR)
    words = {
        label: [tuple(int(v) for v in row) for row in doc["corner"][label]["words"]]
        for label in CORNER_ORDER
    }
    body = author_body.raw_from_words(words)
    cartridge = author_body.compiled_payload(name, 1.0, words)
    cartridge["provenance"] = "forge-visual-author-v1"
    cartridge["lawSource"] = "law_source.json"
    cartridge["runtime_authority"] = "body.body240"
    return doc, words, body, cartridge


def audit_body(target: dict[str, Any], body: bytes, grid_n: int) -> tuple[dict[str, Any], list[list[float]]]:
    points = np.linspace(0.0, 1.0, max(3, int(grid_n)))
    max_radius = 0.0
    unstable = False
    nonfinite = False
    heat = np.zeros((len(points), len(points)))
    for qi, q in enumerate(points):
        for mi, morph in enumerate(points):
            probe = trench_ffi.packed_probe(body, float(morph), float(q))
            db = response_db(body, float(morph), float(q))
            span = float(np.nanmax(db) - np.nanmin(db))
            heat[qi, mi] = span
            max_radius = max(max_radius, float(probe["max_pole_radius"]))
            cell_unstable = int(probe["unstable_mask"]) != 0
            cell_nonfinite = int(probe["nonfinite_mask"]) != 0 or not bool(np.all(np.isfinite(db)))
            unstable = unstable or cell_unstable
            nonfinite = nonfinite or cell_nonfinite

    fit_by_corner = {}
    worst_p95 = 0.0
    for label, (morph, q) in CORNER_TO_MQ.items():
        tgt = target_curve(target["corners"][label]["points"], FREQS)
        got = response_db(body, morph, q)
        stats = residual_stats(tgt, got)
        fit_by_corner[label] = stats
        worst_p95 = max(worst_p95, stats["p95_abs_error_db"])

    warnings = []
    if len(body) != 240:
        warnings.append(f"body length is {len(body)} bytes, expected 240")
    if unstable:
        warnings.append("packed probe found unstable stage(s)")
    if nonfinite:
        warnings.append("packed probe found nonfinite response/stage(s)")
    if max_radius >= 1.0:
        warnings.append(f"max pole radius reached instability: {max_radius:.6f}")
    if worst_p95 > 24.0:
        warnings.append(f"fit is rough: worst p95 residual {worst_p95:.2f} dB")

    audit = {
        "format": "forge-visual-author-audit-v1",
        "target": target["name"],
        "body240_bytes": len(body),
        "grid_n": len(points),
        "checks": {
            "stable": not unstable,
            "finite_response": not nonfinite,
            "max_pole_radius": round(max_radius, 6),
            "fit_p95_abs_error_db_worst_corner": round(worst_p95, 3),
        },
        "fit_by_corner": fit_by_corner,
        "response_span_db": {
            "min": round(float(np.min(heat)), 3),
            "mean": round(float(np.mean(heat)), 3),
            "max": round(float(np.max(heat)), 3),
        },
        "warnings": warnings,
        "verdict": "PASS" if not warnings else "WARN",
    }
    return audit, heat.tolist()


def build_product(target: dict[str, Any], grid_n: int) -> FitProduct:
    if not trench_ffi.available():
        raise RuntimeError("trench_core FFI is unavailable; build trench-core first")

    corners: dict[str, list[dict[str, Any]]] = {}
    for label in CORNER_ORDER:
        corners[label] = fit_corner(target["corners"][label]["points"])

    _doc, _words, body, cartridge = make_packed(target["name"], corners)
    audit, heatmap = audit_body(target, body, grid_n)
    cartridge["visualAuthorAudit"] = {
        "verdict": audit["verdict"],
        "checks": audit["checks"],
        "warnings": audit["warnings"],
    }
    return FitProduct(target=target, corners=corners, body=body, cartridge=cartridge, audit=audit, heatmap=heatmap)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def plot_response(product: FitProduct, out: Path) -> None:
    colors = {
        "M0_Q0": "#1f77b4",
        "M100_Q0": "#d18f00",
        "M0_Q100": "#2e8b57",
        "M100_Q100": "#8a4bb8",
    }
    fig = plt.figure(figsize=(15.5, 10.0), facecolor="#f4efe7")
    gs = fig.add_gridspec(3, 2, height_ratios=[1.0, 1.0, 0.82], hspace=0.42, wspace=0.26)

    for i, label in enumerate(CORNER_ORDER):
        ax = fig.add_subplot(gs[i // 2, i % 2])
        morph, q = CORNER_TO_MQ[label]
        tgt = target_curve(product.target["corners"][label]["points"], FREQS)
        got = response_db(product.body, morph, q)
        stats = product.audit["fit_by_corner"][label]
        ax.semilogx(FREQS, tgt, color="#202020", lw=1.5, ls="--", label="target")
        ax.semilogx(FREQS, got, color=colors[label], lw=1.7, label="packed body")
        ax.fill_between(FREQS, tgt, got, color=colors[label], alpha=0.14, lw=0)
        ax.set_xlim(30.0, AUTHORING_SR * 0.49)
        lo = float(min(np.percentile(tgt, 1), np.percentile(got, 1)) - 8.0)
        hi = float(max(np.percentile(tgt, 99), np.percentile(got, 99)) + 8.0)
        ax.set_ylim(max(-96.0, lo), min(96.0, hi))
        ax.grid(True, which="both", alpha=0.22)
        ax.set_title(f"{label}  p95 residual {stats['p95_abs_error_db']:.2f} dB", fontsize=10)
        ax.legend(fontsize=8)

    axh = fig.add_subplot(gs[2, 0])
    heat = np.array(product.heatmap, dtype=float)
    im = axh.imshow(heat, origin="lower", cmap="magma", extent=[0, 100, 0, 100], aspect="auto")
    axh.set_title("packed Morph/Q response span")
    axh.set_xlabel("Morph")
    axh.set_ylabel("Q")
    fig.colorbar(im, ax=axh, fraction=0.046, pad=0.04, label="dB span")

    axt = fig.add_subplot(gs[2, 1])
    axt.axis("off")
    checks = product.audit["checks"]
    lines = [
        f"target: {product.target['name']} ({product.target['source']})",
        f"body: {len(product.body)} bytes | verdict {product.audit['verdict']}",
        f"stable={checks['stable']} finite={checks['finite_response']} max_r={checks['max_pole_radius']:.6f}",
        f"worst p95 residual={checks['fit_p95_abs_error_db_worst_corner']:.2f} dB",
        "warnings: " + ("; ".join(product.audit["warnings"]) if product.audit["warnings"] else "none"),
        "runtime truth: response curves are from packed body.body240 via trench_core probe",
    ]
    y = 0.95
    for line in lines:
        axt.text(0.02, y, line, family="monospace", fontsize=10, color="#16130f", va="top")
        y -= 0.13

    fig.suptitle("Forge Visual Author - target vs packed-runtime response", x=0.015, ha="left", fontsize=14)
    fig.savefig(out, dpi=130, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def write_workbench(product: FitProduct, out: Path) -> None:
    rows = []
    for label in CORNER_ORDER:
        for lane in product.corners[label]:
            rows.append(
                "<tr>"
                f"<td>{html.escape(label)}</td>"
                f"<td>{lane['lane']}</td>"
                f"<td>{html.escape(lane['role'])}</td>"
                f"<td>{hz_fmt(lane['pole_hz'])}</td>"
                f"<td>{lane['pole_r']:.5f}</td>"
                f"<td>{hz_fmt(lane['zero_hz'])}</td>"
                f"<td>{lane['zero_r']:.5f}</td>"
                f"<td>{lane['gain']:.4f}</td>"
                "</tr>"
            )
    audit = product.audit
    checks = audit["checks"]
    warnings = "; ".join(audit["warnings"]) if audit["warnings"] else "none"
    html_text = f"""<!doctype html>
<meta charset="utf-8">
<title>Forge Visual Author - {html.escape(product.target['name'])}</title>
<style>
body{{margin:24px;background:#f4efe7;color:#16130f;font:13px/1.45 system-ui,Segoe UI,Arial,sans-serif}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:14px;margin:22px 0 8px}}
.meta{{font-family:Consolas,monospace;background:#fffaf1;border:1px solid #d8cbb8;padding:10px;max-width:980px}}
img{{display:block;max-width:100%;border:1px solid #d8cbb8;background:white}}
table{{border-collapse:collapse;width:100%;max-width:1180px;background:#fffaf1}}
th,td{{border:1px solid #d8cbb8;padding:6px 8px;text-align:left;font-family:Consolas,monospace;font-size:12px}}
th{{background:#e7dccb}}
a{{color:#8a4b00}}
</style>
<h1>Forge Visual Author</h1>
<div class="meta">
target: {html.escape(product.target['name'])}<br>
verdict: {html.escape(audit['verdict'])}<br>
body: {len(product.body)} bytes<br>
stable: {checks['stable']} / finite: {checks['finite_response']} / max pole r: {checks['max_pole_radius']:.6f}<br>
worst p95 residual: {checks['fit_p95_abs_error_db_worst_corner']:.2f} dB<br>
warnings: {html.escape(warnings)}<br>
runtime truth: plots and audit are from packed <a href="body.body240">body.body240</a>
</div>
<h2>Response</h2>
<img src="response.png" alt="target versus packed runtime response">
<h2>Artifacts</h2>
<div class="meta">
<a href="target.json">target.json</a><br>
<a href="fitted_lanes.json">fitted_lanes.json</a><br>
<a href="law_source.json">law_source.json</a><br>
<a href="body.body240">body.body240</a><br>
<a href="cartridge.json">cartridge.json</a><br>
<a href="audit.json">audit.json</a>
</div>
<h2>Fitted Lanes</h2>
<table>
<thead><tr><th>corner</th><th>lane</th><th>role</th><th>pole Hz</th><th>pole r</th><th>zero Hz</th><th>zero r</th><th>gain</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
"""
    out.write_text(html_text, encoding="utf-8")


def write_session(product: FitProduct, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "target.json", product.target)
    write_json(
        out_dir / "fitted_lanes.json",
        {
            "format": "forge-visual-author-fit-v1",
            "name": product.target["name"],
            "method": "target magnitude -> six pole/zero lanes -> packed body",
            "corner_order": list(CORNER_ORDER),
            "corners": product.corners,
        },
    )
    write_json(
        out_dir / "law_source.json",
        {
            "format": "forge-root-lanes-v1",
            "name": product.target["name"],
            "corner_order": list(CORNER_ORDER),
            "corners": product.corners,
        },
    )
    (out_dir / "body.body240").write_bytes(product.body)
    write_json(out_dir / "cartridge.json", product.cartridge)
    write_json(out_dir / "audit.json", product.audit)
    plot_response(product, out_dir / "response.png")
    write_workbench(product, out_dir / "workbench.html")


def default_session_name(target_name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in target_name).strip("_")
    return f"{stamp}_{safe or 'session'}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=Path, help="target JSON. If omitted, uses a clean default target.")
    ap.add_argument("--session", help="session folder name under dev/tmp/forge_visual_author")
    ap.add_argument("--out-root", type=Path, default=ROOT / "dev" / "tmp" / "forge_visual_author")
    ap.add_argument("--grid", type=int, default=17, help="Morph/Q audit grid size")
    args = ap.parse_args(argv)

    try:
        target = load_target(args.target)
        session = args.session or default_session_name(target["name"])
        out_dir = args.out_root / session
        product = build_product(target, args.grid)
        write_session(product, out_dir)
    except Exception as exc:
        print(f"forge_visual_author error: {exc}", file=sys.stderr)
        return 1

    print(f"session  -> {out_dir}")
    print(f"target   -> {out_dir / 'target.json'}")
    print(f"lanes    -> {out_dir / 'fitted_lanes.json'}")
    print(f"source   -> {out_dir / 'law_source.json'}")
    print(f"body240  -> {out_dir / 'body.body240'} ({len(product.body)} bytes)")
    print(f"cart     -> {out_dir / 'cartridge.json'}")
    print(f"audit    -> {out_dir / 'audit.json'} ({product.audit['verdict']})")
    print(f"plot     -> {out_dir / 'response.png'}")
    print(f"html     -> {out_dir / 'workbench.html'}")
    if product.audit["warnings"]:
        for warning in product.audit["warnings"]:
            print(f"WARNING {warning}")
    else:
        print("VERDICT PASS")
    return 0 if product.audit["checks"]["stable"] and product.audit["checks"]["finite_response"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
