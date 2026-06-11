#!/usr/bin/env python3
"""Render readable normalized magnitude plots for the ARMA source-pack probe."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROBE = ROOT / "dev" / "tmp" / "arma_source_pack" / "probe" / "arma_source_probe.json"
SHAPE_BAND = (120.0, 7_500.0)
COLORS = {
    "good": "#75e6a4",
    "usable": "#f6c453",
    "rough": "#ff7b72",
}
BG = "#080b0d"
PANEL = "#0d1215"
GRID = "#26323a"
TEXT = "#d8e1e8"
MUTED = "#9aa7b2"
TARGET = "#d8e1e8"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("probe_json", nargs="?", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--out-dir", type=Path)
    return parser.parse_args()


def style_axis(ax: plt.Axes) -> None:
    ax.set_facecolor(PANEL)
    ax.grid(True, which="major", color=GRID, lw=0.55, alpha=0.72)
    ax.grid(True, which="minor", color=GRID, lw=0.30, alpha=0.42)
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#40505a")


def normalized_curves(row: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    freqs = np.asarray(row["freqs_hz"], dtype=np.float64)
    target = np.asarray(row["target_db"], dtype=np.float64)
    packed = np.asarray(row["packed_fit_db"], dtype=np.float64)
    mask = (freqs >= SHAPE_BAND[0]) & (freqs <= SHAPE_BAND[1])
    target = target - float(np.max(target[mask]))
    packed = packed + float(np.mean(target[mask] - packed[mask]))
    return freqs, target, packed, packed - target


def write_source_overview(rows: list[dict], out_dir: Path) -> Path:
    fig, axes = plt.subplots(4, 3, figsize=(18.0, 16.0), facecolor=BG, constrained_layout=True)
    for ax, row in zip(np.asarray(axes).ravel(), rows):
        freqs, target, _packed, _residual = normalized_curves(row)
        color = COLORS[row["status"]]
        style_axis(ax)
        ax.semilogx(freqs, target, color=color, lw=2.0)
        ax.axvspan(*SHAPE_BAND, color="#8b949e", alpha=0.055)
        ax.axhline(0.0, color="#6e7b84", lw=0.7)
        ax.set_xlim(40.0, 7_800.0)
        ax.set_ylim(-54.0, 4.0)
        ax.set_title(row["name"], color=TEXT, fontsize=12, fontweight="bold", loc="left")
        ax.text(
            0.99,
            0.95,
            row["status"].upper(),
            transform=ax.transAxes,
            ha="right",
            va="top",
            color=color,
            fontsize=9,
            fontweight="bold",
        )
    for ax in np.asarray(axes).ravel()[len(rows):]:
        ax.axis("off")
    fig.suptitle(
        "ARMA source pack: normalized source magnitude envelopes",
        color="#f0f6fc",
        fontsize=20,
        fontweight="bold",
    )
    fig.supxlabel("frequency (Hz)", color=TEXT, fontsize=13)
    fig.supylabel("normalized magnitude (dB)", color=TEXT, fontsize=13)
    path = out_dir / "magnitude_source_overview.png"
    fig.savefig(path, dpi=180, facecolor=BG)
    plt.close(fig)
    return path


def write_fit_overview(rows: list[dict], out_dir: Path) -> Path:
    fig, axes = plt.subplots(4, 3, figsize=(18.0, 16.0), facecolor=BG, constrained_layout=True)
    for index, (ax, row) in enumerate(zip(np.asarray(axes).ravel(), rows)):
        freqs, target, packed, _residual = normalized_curves(row)
        color = COLORS[row["status"]]
        style_axis(ax)
        ax.semilogx(freqs, target, color=TARGET, lw=1.7, label="source envelope")
        ax.semilogx(freqs, packed, color=color, lw=2.0, label="packed ARMA fit")
        ax.axvspan(*SHAPE_BAND, color="#8b949e", alpha=0.055)
        ax.axhline(0.0, color="#6e7b84", lw=0.7)
        ax.set_xlim(40.0, 7_800.0)
        ax.set_ylim(-54.0, 4.0)
        ax.set_title(row["name"], color=TEXT, fontsize=12, fontweight="bold", loc="left")
        ax.text(
            0.99,
            0.95,
            f"{row['status'].upper()}  RMS {row['in_band_shape_rms_db']:.2f} dB",
            transform=ax.transAxes,
            ha="right",
            va="top",
            color=color,
            fontsize=8,
            fontweight="bold",
        )
        if index == 0:
            legend = ax.legend(loc="lower left", fontsize=8, facecolor="#12191d", edgecolor="#40505a")
            for text in legend.get_texts():
                text.set_color(TEXT)
    for ax in np.asarray(axes).ravel()[len(rows):]:
        ax.axis("off")
    fig.suptitle(
        "ARMA source pack: normalized source envelope versus packed fit",
        color="#f0f6fc",
        fontsize=20,
        fontweight="bold",
    )
    fig.supxlabel("frequency (Hz)", color=TEXT, fontsize=13)
    fig.supylabel("normalized magnitude (dB)", color=TEXT, fontsize=13)
    path = out_dir / "magnitude_fit_overview.png"
    fig.savefig(path, dpi=180, facecolor=BG)
    plt.close(fig)
    return path


def write_individual(row: dict, out_dir: Path) -> Path:
    freqs, target, packed, residual = normalized_curves(row)
    color = COLORS[row["status"]]
    fig, (response_ax, residual_ax) = plt.subplots(
        2,
        1,
        figsize=(14.0, 8.0),
        height_ratios=(3.2, 1.0),
        sharex=True,
        facecolor=BG,
        constrained_layout=True,
    )
    style_axis(response_ax)
    style_axis(residual_ax)
    response_ax.semilogx(freqs, target, color=TARGET, lw=2.2, label="normalized source envelope")
    response_ax.semilogx(freqs, packed, color=color, lw=2.4, label="gain-aligned packed ARMA fit")
    response_ax.axvspan(*SHAPE_BAND, color="#8b949e", alpha=0.055)
    response_ax.axhline(0.0, color="#6e7b84", lw=0.7)
    response_ax.set_xlim(40.0, 7_800.0)
    response_ax.set_ylim(-62.0, 5.0)
    response_ax.set_ylabel("normalized magnitude (dB)", color=TEXT, fontsize=11)
    legend = response_ax.legend(loc="lower left", fontsize=9, facecolor="#12191d", edgecolor="#40505a")
    for text in legend.get_texts():
        text.set_color(TEXT)

    residual_ax.semilogx(freqs, residual, color=color, lw=1.7)
    residual_ax.axvspan(*SHAPE_BAND, color="#8b949e", alpha=0.055)
    residual_ax.axhline(0.0, color="#d8e1e8", lw=0.8)
    residual_ax.set_ylabel("fit error (dB)", color=TEXT, fontsize=11)
    residual_ax.set_xlabel("frequency (Hz)", color=TEXT, fontsize=11)
    mask = (freqs >= SHAPE_BAND[0]) & (freqs <= SHAPE_BAND[1])
    residual_limit = max(6.0, min(30.0, float(np.percentile(np.abs(residual[mask]), 98.0)) * 1.2))
    residual_ax.set_ylim(-residual_limit, residual_limit)

    fig.suptitle(
        f"{row['name']}: normalized magnitude envelope and packed ARMA fit",
        color="#f0f6fc",
        fontsize=18,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.945,
        (
            f"{row['status'].upper()}   shape RMS {row['in_band_shape_rms_db']:.2f} dB   "
            f"packed drift {row['packed_drift_rms_db']:.2f} dB   "
            f"effective rows {row['effective_shape_rows']}/{row['emitted_rows']}   "
            f"max pole radius {row['max_pole_radius']:.5f}"
        ),
        color=color,
        fontsize=10,
        fontweight="bold",
        ha="center",
    )
    path = out_dir / f"{row['name']}.png"
    fig.savefig(path, dpi=180, facecolor=BG)
    plt.close(fig)
    return path


def main() -> int:
    args = parse_args()
    probe_json = args.probe_json.resolve()
    out_dir = (args.out_dir or probe_json.parent / "magnitude_plots").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = json.loads(probe_json.read_text(encoding="utf-8"))["rows"]
    outputs = [
        write_source_overview(rows, out_dir),
        write_fit_overview(rows, out_dir),
    ]
    outputs.extend(write_individual(row, out_dir) for row in rows)
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
