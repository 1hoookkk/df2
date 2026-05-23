#!/usr/bin/env python3
"""Coefficient-field bakeoff for the Talking Hedz packed oracle.

Offline analysis only. Does not modify runtime code or cartridge assets.
All run outputs are written below dev/tmp/coefficient_field_bakeoff/<timestamp>/.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from numpy.polynomial.chebyshev import chebvander2d
from scipy.interpolate import RBFInterpolator, RectBivariateSpline
from scipy.io import wavfile
from scipy.signal import sosfilt, sosfreqz

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.minifloat import COMBINE_K, decode, encode  # noqa: E402

DEFAULT_CARTRIDGE = ROOT / "ref" / "p2k_skins" / "00_talking_hedz.json"
DEFAULT_OUT_ROOT = ROOT / "dev" / "tmp" / "coefficient_field_bakeoff"
SR = 44100
EPS = 1e-30
DECODE_LUT = np.array([decode(w) for w in range(65536)], dtype=np.float32)

CORNER_LABELS = {
    "A": "M0_Q0",
    "B": "M100_Q0",
    "C": "M0_Q100",
    "D": "M100_Q100",
}


@dataclass(frozen=True)
class SurfaceFit:
    name: str
    predict: Callable[[np.ndarray], np.ndarray]


def stage_to_kernel(stage: dict) -> np.ndarray:
    """Convert P2K stage fields to kernel-form [c0..c4]."""
    a1 = float(stage["a1"])
    r = float(stage.get("r", stage.get("radius")))
    val1 = float(stage["val1"])
    val2 = float(stage["val2"])
    val3 = float(stage["val3"])
    flag = float(stage.get("flag", 1.0))

    if flag >= 0.5:
        c2 = 2.0 + a1
        c3 = 1.0 - r * r
        b0 = 1.0 + val1
        b1 = a1 + val2
        b2 = r * r - val3
        c4 = b0
        c0 = 2.0 + b1 / b0 if abs(b0) > 1e-12 else 2.0
        c1 = 1.0 - b2 / b0 if abs(b0) > 1e-12 else 1.0
        return np.array([c0, c1, c2, c3, c4], dtype=np.float64)

    a1_bq = a1 - 2.0
    a2_bq = 1.0 - r
    b0_bq = (1.0 + a1_bq + a2_bq) / 4.0
    c0 = 4.0 if abs(b0_bq) > 1e-12 else 2.0
    c1 = 0.0 if abs(b0_bq) > 1e-12 else 1.0
    return np.array([c0, c1, a1, r, b0_bq], dtype=np.float64)


def kernel_to_sos(coeffs: np.ndarray) -> np.ndarray:
    rows = []
    for c0, c1, c2, c3, c4 in coeffs:
        b0 = c4
        b1 = (c0 - 2.0) * c4
        b2 = (1.0 - c1) * c4
        a1 = c2 - 2.0
        a2 = 1.0 - c3
        rows.append([b0, b1, b2, 1.0, a1, a2])
    return np.asarray(rows, dtype=np.float64)


def kernel_to_words(coeffs: np.ndarray) -> np.ndarray:
    words = np.empty(coeffs.shape, dtype=np.uint16)
    encode_array = np.vectorize(encode, otypes=[np.uint16])
    words[..., 0] = encode_array((coeffs[..., 0] - coeffs[..., 1]) / COMBINE_K)
    words[..., 1] = encode_array(coeffs[..., 1])
    words[..., 2] = encode_array((coeffs[..., 2] - coeffs[..., 3]) / COMBINE_K)
    words[..., 3] = encode_array(coeffs[..., 3])
    words[..., 4] = encode_array(coeffs[..., 4] / COMBINE_K)  # c4 scale 4.0
    return words


def words_to_kernel(words: np.ndarray) -> np.ndarray:
    decoded = DECODE_LUT[words.astype(np.uint16)].astype(np.float64)
    out = np.empty(decoded.shape, dtype=np.float64)
    out[..., 0] = decoded[..., 0] * COMBINE_K + decoded[..., 1]
    out[..., 1] = decoded[..., 1]
    out[..., 2] = decoded[..., 2] * COMBINE_K + decoded[..., 3]
    out[..., 3] = decoded[..., 3]
    out[..., 4] = decoded[..., 4] * COMBINE_K  # c4 scale 4.0 (verified vs ROM)
    return out


def lerp_u16(a: np.ndarray, b: np.ndarray, frac: float) -> np.ndarray:
    ai = a.astype(np.int64)
    bi = b.astype(np.int64)
    trunc = np.trunc((bi - ai).astype(np.float32) * np.float32(frac)).astype(np.int64)
    delta_i16 = ((trunc + 0x8000) % 0x10000) - 0x8000
    return ((ai + delta_i16) & 0xFFFF).astype(np.uint16)


def packed_oracle(corner_words: dict[str, np.ndarray], morph: float, q: float) -> np.ndarray:
    """E-mu packed-canonical oracle: morph-first u16 lerp, then LUT decode."""
    top = lerp_u16(corner_words["A"], corner_words["B"], morph)
    bottom = lerp_u16(corner_words["C"], corner_words["D"], morph)
    words = lerp_u16(top, bottom, q)
    return words_to_kernel(words)


def decoded_float_baseline(corner_coeffs: dict[str, np.ndarray], morph: float, q: float) -> np.ndarray:
    top = corner_coeffs["A"] + (corner_coeffs["B"] - corner_coeffs["A"]) * morph
    bottom = corner_coeffs["C"] + (corner_coeffs["D"] - corner_coeffs["C"]) * morph
    return top + (bottom - top) * q


def load_corner_coeffs(path: Path) -> tuple[dict[str, np.ndarray], dict]:
    data = json.loads(path.read_text())
    keyframes = {kf["label"]: kf for kf in data["keyframes"]}
    corners = {}
    for name, label in CORNER_LABELS.items():
        stages = keyframes[label]["stages"]
        corners[name] = np.vstack([stage_to_kernel(stage) for stage in stages])
    return corners, data


def make_grid(n: int, offset: bool = False) -> np.ndarray:
    if offset:
        axis = (np.arange(n, dtype=np.float64) + 0.5) / n
    else:
        axis = np.linspace(0.0, 1.0, n, dtype=np.float64)
    return np.array([(m, q) for m in axis for q in axis], dtype=np.float64)


def sample_field(points: np.ndarray, sampler: Callable[[float, float], np.ndarray]) -> np.ndarray:
    return np.stack([sampler(float(m), float(q)) for m, q in points], axis=0)


def fit_chebyshev(points: np.ndarray, values: np.ndarray, degree: int, ridge: float) -> SurfaceFit:
    scaled = points * 2.0 - 1.0
    design = chebvander2d(scaled[:, 0], scaled[:, 1], [degree, degree])
    design = design.reshape(len(points), -1)
    y = values.reshape(len(points), -1)
    lhs = design.T @ design + ridge * np.eye(design.shape[1])
    rhs = design.T @ y
    beta = np.linalg.solve(lhs, rhs)
    out_shape = values.shape[1:]

    def predict(new_points: np.ndarray) -> np.ndarray:
        new_scaled = new_points * 2.0 - 1.0
        vand = chebvander2d(new_scaled[:, 0], new_scaled[:, 1], [degree, degree])
        pred = vand.reshape(len(new_points), -1) @ beta
        return pred.reshape((len(new_points),) + out_shape)

    return SurfaceFit(f"chebyshev_d{degree}", predict)


def fit_bicubic(points: np.ndarray, values: np.ndarray, grid_n: int) -> SurfaceFit:
    axis = np.linspace(0.0, 1.0, grid_n, dtype=np.float64)
    out_shape = values.shape[1:]
    flat = values.reshape(grid_n, grid_n, -1)
    splines = [
        RectBivariateSpline(axis, axis, flat[:, :, idx], kx=3, ky=3, s=0.0)
        for idx in range(flat.shape[-1])
    ]

    def predict(new_points: np.ndarray) -> np.ndarray:
        pred = np.empty((len(new_points), flat.shape[-1]), dtype=np.float64)
        for idx, spline in enumerate(splines):
            pred[:, idx] = spline.ev(new_points[:, 0], new_points[:, 1])
        return pred.reshape((len(new_points),) + out_shape)

    return SurfaceFit("bicubic_spline", predict)


def fit_rbf(points: np.ndarray, values: np.ndarray, smoothing: float) -> SurfaceFit:
    out_shape = values.shape[1:]
    y = values.reshape(len(points), -1)
    rbf = RBFInterpolator(points, y, kernel="thin_plate_spline", degree=1, smoothing=smoothing)

    def predict(new_points: np.ndarray) -> np.ndarray:
        return rbf(new_points).reshape((len(new_points),) + out_shape)

    return SurfaceFit("rbf_thin_plate", predict)


def response(coeffs: np.ndarray, wor_n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sos = kernel_to_sos(coeffs)
    freqs, h = sosfreqz(sos, worN=wor_n, fs=SR)
    mag_db = 20.0 * np.log10(np.maximum(np.abs(h), EPS))
    phase = np.unwrap(np.angle(h))
    omega = 2.0 * np.pi * freqs / SR
    group_delay = -np.gradient(phase, omega)
    return freqs, mag_db, group_delay


def summarize_response_errors(
    oracle_values: np.ndarray,
    prediction_values: np.ndarray,
    wor_n: int,
) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray]:
    mag_errors = []
    gd_errors = []
    freqs_ref = None
    for oracle, pred in zip(oracle_values, prediction_values):
        freqs, mag_o, gd_o = response(oracle, wor_n)
        _, mag_p, gd_p = response(pred, wor_n)
        freqs_ref = freqs
        mag_errors.append(mag_p - mag_o)
        gd_errors.append(gd_p - gd_o)
    mag_errors = np.asarray(mag_errors)
    gd_errors = np.asarray(gd_errors)
    summary = {
        "mag_rms_db": rms(mag_errors),
        "mag_max_abs_db": max_abs(mag_errors),
        "gd_rms_samples": rms(gd_errors),
        "gd_max_abs_samples": max_abs(gd_errors),
    }
    return summary, freqs_ref, mag_errors, gd_errors


def pole_zero_stats(values: np.ndarray) -> tuple[list[dict], np.ndarray, np.ndarray]:
    rows = []
    all_poles = []
    all_zeros = []
    for point_idx, coeffs in enumerate(values):
        for stage_idx, coeff in enumerate(coeffs):
            sos = kernel_to_sos(coeff.reshape(1, 5))[0]
            b = sos[:3]
            a = sos[3:]
            poles = np.roots(a)
            zeros = np.roots(b) if np.max(np.abs(b)) > EPS else np.array([], dtype=np.complex128)
            all_poles.extend(poles.tolist())
            all_zeros.extend(zeros.tolist())
            max_radius = float(np.max(np.abs(poles))) if len(poles) else 0.0
            rows.append(
                {
                    "point_index": point_idx,
                    "stage": stage_idx,
                    "max_pole_radius": max_radius,
                    "stable": max_radius < 1.0,
                }
            )
    return rows, np.asarray(all_poles), np.asarray(all_zeros)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def max_abs(x: np.ndarray) -> float:
    return float(np.max(np.abs(np.asarray(x, dtype=np.float64))))


def render(coeffs: np.ndarray, dry: np.ndarray) -> np.ndarray:
    out = sosfilt(kernel_to_sos(coeffs), dry.astype(np.float64))
    np.nan_to_num(out, copy=False, nan=0.0, posinf=1.0, neginf=-1.0)
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0.99:
        out = out * (0.99 / peak)
    return out.astype(np.float32)


def deterministic_pink(duration: float) -> np.ndarray:
    rng = np.random.default_rng(13013)
    n = int(round(duration * SR))
    white = rng.standard_normal(n)
    fft = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    freqs[0] = 1.0
    pink = np.fft.irfft(fft / np.sqrt(freqs), n)
    peak = float(np.max(np.abs(pink)))
    if peak > 0:
        pink *= 0.4 / peak
    return pink.astype(np.float32)


def null_depth(ref: np.ndarray, cand: np.ndarray) -> float:
    n = min(len(ref), len(cand))
    residual = ref[:n].astype(np.float64) - cand[:n].astype(np.float64)
    ref_rms = math.sqrt(float(np.mean(ref[:n].astype(np.float64) ** 2))) + EPS
    res_rms = math.sqrt(float(np.mean(residual ** 2))) + EPS
    return float(20.0 * math.log10(res_rms / ref_rms))


def write_wav(path: Path, samples: np.ndarray) -> None:
    wavfile.write(str(path), SR, samples.astype(np.float32))


def plot_error_heatmap(
    out: Path,
    title: str,
    heldout_points: np.ndarray,
    values: np.ndarray,
    label: str,
) -> None:
    side = int(round(math.sqrt(len(heldout_points))))
    grid = values.reshape(side, side)
    fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
    image = ax.imshow(
        grid.T,
        origin="lower",
        extent=(0.0, 1.0, 0.0, 1.0),
        aspect="auto",
        cmap="magma",
    )
    fig.colorbar(image, ax=ax, label=label)
    ax.set_title(title)
    ax.set_xlabel("Morph")
    ax.set_ylabel("Q")
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_pole_zero(out: Path, title: str, poles: np.ndarray, zeros: np.ndarray) -> None:
    fig, ax = plt.subplots(figsize=(6, 6), constrained_layout=True)
    theta = np.linspace(0.0, 2.0 * np.pi, 512)
    ax.plot(np.cos(theta), np.sin(theta), color="0.6", linewidth=1.0, label="unit circle")
    if len(zeros):
        ax.scatter(zeros.real, zeros.imag, s=6, alpha=0.25, label="zeros", color="#1f77b4")
    if len(poles):
        ax.scatter(poles.real, poles.imag, s=8, alpha=0.35, label="poles", color="#d62728")
    ax.set_title(title)
    ax.set_xlabel("Real")
    ax.set_ylabel("Imag")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.2)
    ax.legend(loc="upper right")
    fig.savefig(out, dpi=150)
    plt.close(fig)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def nearest_heldout_point(target: float, heldout_points: np.ndarray) -> tuple[float, float]:
    diagonal = np.array([target, target], dtype=np.float64)
    idx = int(np.argmin(np.sum((heldout_points - diagonal) ** 2, axis=1)))
    return float(heldout_points[idx, 0]), float(heldout_points[idx, 1])


def write_report(
    path: Path,
    manifest: dict,
    metrics: list[dict],
    render_rows: list[dict],
) -> None:
    any_fit_stable = any(
        row["method"] != "decoded_float_bilinear"
        and row["stable_points"] == row["evaluated_points"]
        for row in metrics
    )
    exact_midpoint_rows = [
        row for row in render_rows
        if row["point_name"] == "diag_50" and row["method"] != "oracle"
    ]
    offset_midpoint_rows = [
        row for row in render_rows
        if row["point_name"] == "offset_near_50" and row["method"] != "oracle"
    ]
    best_exact_mid = (
        sorted(exact_midpoint_rows, key=lambda row: row["null_vs_oracle_db"])[0]
        if exact_midpoint_rows else None
    )
    best_offset_mid = (
        sorted(offset_midpoint_rows, key=lambda row: row["null_vs_oracle_db"])[0]
        if offset_midpoint_rows else None
    )
    baseline_offset_mid = next(
        (
            row for row in offset_midpoint_rows
            if row["method"] == "decoded_float_bilinear"
        ),
        None,
    )

    lines = [
        "# Coefficient Field Bakeoff",
        "",
        "Offline analysis harness only. Runtime code and cartridge assets were not modified.",
        "",
        "## Trust Choice",
        "",
        "- Oracle: morph-first packed u16 interpolation with E-MU/MSVC-style int16 truncation at each lerp step, then decode LUT lookup.",
        "- Corner packed words are derived from decoded c0..c4 in `ref/p2k_skins/00_talking_hedz.json`; raw ROM u16 words are not present in this checkout.",
        "- Baseline: decoded-float bilinear interpolation in c-domain.",
        "- Plots are diagnostic only; render null metrics and audition WAVs are the listening gate.",
        "",
        "## Run",
        "",
        f"- Output directory: `{manifest['output_dir']}`",
        f"- Training grid: {manifest['training_grid']} points",
        f"- Held-out grid: {manifest['heldout_grid']} points",
        f"- Stages: {manifest['stage_count']}",
        f"- Coefficients per stage: {manifest['coefficients_per_stage']}",
        "",
        "## Held-out Metrics",
        "",
        "| method | coef rms | coef max | mag rms dB | mag max dB | group delay rms samples | max pole radius | stable held-out |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics:
        lines.append(
            "| {method} | {coef_rms:.6g} | {coef_max_abs:.6g} | {mag_rms_db:.4g} | "
            "{mag_max_abs_db:.4g} | {gd_rms_samples:.4g} | {max_pole_radius:.6f} | "
            "{stable_points}/{evaluated_points} |".format(**row)
        )

    lines.extend(["", "## Render Nulls", ""])
    lines.append("| point | method | morph | q | null vs oracle dB |")
    lines.append("|---|---|---:|---:|---:|")
    for row in render_rows:
        if row["method"] == "oracle":
            continue
        lines.append(
            f"| {row['point_name']} | {row['method']} | {row['morph']:.5f} | "
            f"{row['q']:.5f} | {row['null_vs_oracle_db']:.2f} |"
        )

    lines.extend(["", "## Midpoint Read", ""])
    lines.append(
        "Exact 50% lies on the 17x17 training grid, so an exact spline/RBF "
        "match there is not evidence by itself."
    )
    if best_exact_mid:
        lines.append(
            f"Best exact-midpoint metric proxy is `{best_exact_mid['method']}` "
            f"with {best_exact_mid['null_vs_oracle_db']:.2f} dB "
            "null vs packed oracle."
        )
    if best_offset_mid:
        delta = ""
        if baseline_offset_mid:
            delta_db = baseline_offset_mid["null_vs_oracle_db"] - best_offset_mid["null_vs_oracle_db"]
            delta = f" ({delta_db:.2f} dB better than decoded-float baseline)"
        lines.append(
            f"Best held-out midpoint-near proxy is `{best_offset_mid['method']}` "
            f"with {best_offset_mid['null_vs_oracle_db']:.2f} dB null vs packed oracle{delta}."
        )
    lines.extend(["", "## Success Criteria", ""])
    lines.append("- First success: PASS. The packed-canonical oracle was implemented and sampled into 17x17 training plus 16x16 held-out grids.")
    lines.append(
        "- Second success: "
        + ("PASS. At least one fitted surface stayed stable over every held-out point." if any_fit_stable else "FAIL. No fitted surface stayed stable over every held-out point.")
    )
    lines.append(
        "- Real success: NOT CLAIMED. Fitted surfaces beat decoded-float on render nulls, "
        "but the held-out midpoint-near null remains far above the -60 dB gate; audition is still required."
    )
    lines.append(
        "Audible preservation is not claimed from plots alone. The WAVs in `wav/` "
        "are exported for the owner audition; metric nulls are the objective proxy."
    )

    path.write_text("\n".join(lines) + "\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cartridge", type=Path, default=DEFAULT_CARTRIDGE)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--timestamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--cheb-degree", type=int, default=4)
    parser.add_argument("--cheb-ridge", type=float, default=1e-10)
    parser.add_argument("--rbf-smoothing", type=float, default=1e-8)
    parser.add_argument("--freq-bins", type=int, default=2048)
    parser.add_argument("--duration", type=float, default=3.0)
    args = parser.parse_args(argv)

    out_dir = args.out_root / args.timestamp
    plots_dir = out_dir / "plots"
    wav_dir = out_dir / "wav"
    data_dir = out_dir / "data"
    for directory in (plots_dir, wav_dir, data_dir):
        directory.mkdir(parents=True, exist_ok=True)

    corner_coeffs, cartridge = load_corner_coeffs(args.cartridge)
    corner_words = {name: kernel_to_words(coeffs) for name, coeffs in corner_coeffs.items()}
    stage_count, coeff_count = corner_coeffs["A"].shape

    oracle_sampler = lambda m, q: packed_oracle(corner_words, m, q)
    baseline_sampler = lambda m, q: decoded_float_baseline(corner_coeffs, m, q)

    train_points = make_grid(17)
    heldout_points = make_grid(16, offset=True)
    train_values = sample_field(train_points, oracle_sampler)
    heldout_oracle = sample_field(heldout_points, oracle_sampler)
    heldout_baseline = sample_field(heldout_points, baseline_sampler)

    fits = [
        fit_chebyshev(train_points, train_values, args.cheb_degree, args.cheb_ridge),
        fit_bicubic(train_points, train_values, 17),
        fit_rbf(train_points, train_values, args.rbf_smoothing),
    ]
    predictions = {"decoded_float_bilinear": heldout_baseline}
    predictions.update({fit.name: fit.predict(heldout_points) for fit in fits})

    np.savez_compressed(
        data_dir / "samples.npz",
        train_points=train_points,
        train_oracle=train_values,
        heldout_points=heldout_points,
        heldout_oracle=heldout_oracle,
        heldout_decoded_float=heldout_baseline,
        corner_coeffs=np.stack([corner_coeffs[k] for k in ("A", "B", "C", "D")]),
        corner_words=np.stack([corner_words[k] for k in ("A", "B", "C", "D")]),
    )

    metric_rows = []
    stability_rows = []
    pole_zero_cache = {}
    for method, pred in predictions.items():
        coeff_delta = pred - heldout_oracle
        resp_summary, _freqs, mag_errors, gd_errors = summarize_response_errors(
            heldout_oracle, pred, args.freq_bins
        )
        point_stability, poles, zeros = pole_zero_stats(pred)
        for row in point_stability:
            stability_rows.append({"method": method, **row})
        stable_points = 0
        for point_idx in range(len(heldout_points)):
            rows = [r for r in point_stability if r["point_index"] == point_idx]
            if rows and all(r["stable"] for r in rows):
                stable_points += 1
        max_pole_radius = max(float(r["max_pole_radius"]) for r in point_stability)
        metric_rows.append(
            {
                "method": method,
                "coef_rms": rms(coeff_delta),
                "coef_max_abs": max_abs(coeff_delta),
                **resp_summary,
                "max_pole_radius": max_pole_radius,
                "stable_points": stable_points,
                "evaluated_points": len(heldout_points),
            }
        )
        pole_zero_cache[method] = (poles, zeros)

        coef_rms_by_point = np.sqrt(np.mean(coeff_delta.reshape(len(heldout_points), -1) ** 2, axis=1))
        mag_rms_by_point = np.sqrt(np.mean(mag_errors ** 2, axis=1))
        gd_rms_by_point = np.sqrt(np.mean(gd_errors ** 2, axis=1))
        plot_error_heatmap(
            plots_dir / f"{method}_coefficient_error.png",
            f"{method} coefficient RMS vs oracle",
            heldout_points,
            coef_rms_by_point,
            "coefficient RMS",
        )
        plot_error_heatmap(
            plots_dir / f"{method}_magnitude_error.png",
            f"{method} magnitude RMS error",
            heldout_points,
            mag_rms_by_point,
            "dB RMS",
        )
        plot_error_heatmap(
            plots_dir / f"{method}_group_delay_error.png",
            f"{method} group-delay RMS error",
            heldout_points,
            gd_rms_by_point,
            "samples RMS",
        )
        plot_pole_zero(
            plots_dir / f"{method}_pole_zero.png",
            f"{method} held-out poles and zeros",
            poles,
            zeros,
        )

    oracle_stability, oracle_poles, oracle_zeros = pole_zero_stats(heldout_oracle)
    for row in oracle_stability:
        stability_rows.append({"method": "oracle", **row})
    plot_pole_zero(
        plots_dir / "oracle_pole_zero.png",
        "oracle held-out poles and zeros",
        oracle_poles,
        oracle_zeros,
    )

    write_csv(data_dir / "heldout_metrics.csv", metric_rows)
    write_csv(data_dir / "stability.csv", stability_rows)

    dry = deterministic_pink(args.duration)
    write_wav(wav_dir / "dry_pink.wav", dry)
    render_points = []
    for target in (0.25, 0.50, 0.75):
        render_points.append((f"diag_{int(target * 100)}", target, target))
        near_m, near_q = nearest_heldout_point(target, heldout_points)
        render_points.append((f"offset_near_{int(target * 100)}", near_m, near_q))

    all_methods: dict[str, Callable[[float, float], np.ndarray]] = {
        "oracle": oracle_sampler,
        "decoded_float_bilinear": baseline_sampler,
    }
    for fit in fits:
        all_methods[fit.name] = lambda m, q, f=fit: f.predict(np.array([[m, q]], dtype=np.float64))[0]

    render_rows = []
    for point_name, morph, q in render_points:
        point_dir = wav_dir / point_name
        point_dir.mkdir(parents=True, exist_ok=True)
        oracle_audio = None
        for method, sampler in all_methods.items():
            coeffs = sampler(morph, q)
            audio = render(coeffs, dry)
            write_wav(point_dir / f"{method}.wav", audio)
            if method == "oracle":
                oracle_audio = audio
        for method, sampler in all_methods.items():
            audio_path = point_dir / f"{method}.wav"
            _sr, audio = wavfile.read(str(audio_path))
            render_rows.append(
                {
                    "point_name": point_name,
                    "method": method,
                    "morph": morph,
                    "q": q,
                    "wav": str(audio_path),
                    "null_vs_oracle_db": 0.0 if method == "oracle" else null_depth(oracle_audio, audio),
                }
            )
    write_csv(data_dir / "render_nulls.csv", render_rows)

    manifest = {
        "timestamp": args.timestamp,
        "output_dir": str(out_dir),
        "cartridge": str(args.cartridge),
        "cartridge_name": cartridge.get("name"),
        "oracle": "morph-first packed u16 interpolation, E-MU/MSVC-style int16 truncation at each lerp, then decode LUT lookup",
        "corner_words_source": "derived from decoded c0..c4 in cartridge; raw ROM words absent",
        "training_grid": len(train_points),
        "heldout_grid": len(heldout_points),
        "stage_count": stage_count,
        "coefficients_per_stage": coeff_count,
        "methods": list(predictions.keys()),
        "render_points": [
            {"name": name, "morph": morph, "q": q} for name, morph, q in render_points
        ],
        "sample_rate": SR,
        "duration_seconds": args.duration,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    write_report(out_dir / "REPORT.md", manifest, metric_rows, render_rows)

    print(f"wrote bakeoff outputs: {out_dir}")
    print("held-out stability:")
    for row in metric_rows:
        print(
            f"  {row['method']}: {row['stable_points']}/{row['evaluated_points']} "
            f"stable, midpoint/proxy WAVs in {wav_dir}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
