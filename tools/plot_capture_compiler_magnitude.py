#!/usr/bin/env python3
"""Render packed-domain magnitude plots for a compiled TRENCH cartridge."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime.forge_fit import cascade_response  # noqa: E402
from pyruntime.packed_interp import kernel_to_biquad, packed_bilinear  # noqa: E402

CORNER_KEYS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_LETTER = dict(zip(CORNER_KEYS, ("A", "B", "C", "D")))
FIELD = "#0a0d0c"
INK = "#d8e1dc"
DIM = "#83938b"
GRID = "#213028"
COLORS = ("#5bef6f", "#31c6c9", "#e8a33d", "#ff6b6b", "#bc8cff")


def load_words(path: Path) -> tuple[str, float, dict[str, list[tuple[int, ...]]]]:
    cart = json.loads(path.read_text(encoding="utf-8"))
    by_label = {frame["label"]: frame for frame in cart["keyframes"]}
    words = {
        LETTER: [tuple(int(word) & 0xFFFF for word in row) for row in by_label[label]["packedWords"]]
        for label, LETTER in LABEL_TO_LETTER.items()
    }
    return str(cart["name"]), float(cart["sampleRate"]), words


def response_db(rows: list[tuple[float, ...]], freqs: np.ndarray, sr: float) -> np.ndarray:
    z_inv = np.exp(-1j * 2.0 * np.pi * freqs / sr)
    return 20.0 * np.log10(np.maximum(np.abs(cascade_response(np.asarray(rows), z_inv)), 1.0e-15))


def stage_response_db(row: tuple[float, ...], freqs: np.ndarray, sr: float) -> np.ndarray:
    b0, b1, b2, a1, a2 = kernel_to_biquad(row)
    z1 = np.exp(-1j * 2.0 * np.pi * freqs / sr)
    z2 = z1 * z1
    h = (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1.0e-15))


def at(words: dict[str, list[tuple[int, ...]]], morph: float, q: float) -> list[tuple[float, ...]]:
    return packed_bilinear(words, float(morph), float(q))


def style(ax: plt.Axes) -> None:
    ax.set_facecolor(FIELD)
    ax.grid(True, which="both", color=GRID, linewidth=0.45)
    ax.tick_params(colors=INK, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#405149")


def finish(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170, facecolor=FIELD, bbox_inches="tight")
    plt.close(fig)


def plot_keypoints(
    out: Path,
    name: str,
    words: dict[str, list[tuple[int, ...]]],
    freqs: np.ndarray,
    sr: float,
) -> None:
    groups = (
        (
            "Packed corners + center",
            (
                ("M0 Q0", 0.0, 0.0),
                ("M100 Q0", 1.0, 0.0),
                ("M0 Q100", 0.0, 1.0),
                ("M100 Q100", 1.0, 1.0),
                ("M50 Q50", 0.5, 0.5),
            ),
        ),
        (
            "Packed edge midpoints + center",
            (
                ("M50 Q0", 0.5, 0.0),
                ("M50 Q100", 0.5, 1.0),
                ("M0 Q50", 0.0, 0.5),
                ("M100 Q50", 1.0, 0.5),
                ("M50 Q50", 0.5, 0.5),
            ),
        ),
    )
    fig, axes = plt.subplots(2, 1, figsize=(12.5, 9.0), sharex=True, constrained_layout=True)
    fig.patch.set_facecolor(FIELD)
    for ax, (title, points) in zip(axes, groups):
        style(ax)
        for color, (label, morph, q) in zip(COLORS, points):
            ax.semilogx(freqs, response_db(at(words, morph, q), freqs, sr), color=color, linewidth=1.75, label=label)
        ax.set_title(title, color=INK, fontsize=11, loc="left")
        ax.set_ylabel("magnitude (dB)", color=INK)
        ax.legend(facecolor="#111711", edgecolor="#405149", labelcolor=INK, fontsize=8, ncol=3)
    axes[-1].set_xlabel("frequency (Hz)", color=INK)
    fig.suptitle(f"{name}: packed-domain magnitude keypoints", color=INK, fontsize=14, fontweight="bold")
    finish(fig, out)


def plot_surface(
    out: Path,
    name: str,
    words: dict[str, list[tuple[int, ...]]],
    freqs: np.ndarray,
    sr: float,
) -> None:
    axis = np.linspace(0.0, 1.0, 5)
    curves = [response_db(at(words, morph, q), freqs, sr) for q in axis for morph in axis]
    lo = float(np.percentile(np.concatenate(curves), 2.0))
    hi = float(np.percentile(np.concatenate(curves), 99.0))
    fig, axes = plt.subplots(5, 5, figsize=(14.5, 11.5), sharex=True, sharey=True, constrained_layout=True)
    fig.patch.set_facecolor(FIELD)
    for row, q in enumerate(axis[::-1]):
        for col, morph in enumerate(axis):
            ax = axes[row, col]
            style(ax)
            ax.semilogx(freqs, response_db(at(words, morph, q), freqs, sr), color="#5bef6f", linewidth=1.0)
            ax.set_ylim(lo, hi)
            if row == 4:
                ax.set_xlabel(f"M {morph:.2f}", color=INK, fontsize=8)
            if col == 0:
                ax.set_ylabel(f"Q {q:.2f}\ndB", color=INK, fontsize=8)
    fig.suptitle(f"{name}: packed magnitude surface, 5 x 5 reachable points", color=INK, fontsize=14, fontweight="bold")
    finish(fig, out)


def plot_sweeps(
    out: Path,
    name: str,
    words: dict[str, list[tuple[int, ...]]],
    freqs: np.ndarray,
    sr: float,
) -> None:
    axis = np.linspace(0.0, 1.0, 81)
    sweeps = (
        ("Morph sweep at Q=0", [(value, 0.0) for value in axis]),
        ("Morph sweep at Q=1", [(value, 1.0) for value in axis]),
        ("Secondary sweep at M=0", [(0.0, value) for value in axis]),
        ("Secondary sweep at M=1", [(1.0, value) for value in axis]),
        ("Diagonal sweep M=Q", [(value, value) for value in axis]),
    )
    values = [np.stack([response_db(at(words, morph, q), freqs, sr) for morph, q in points]) for _, points in sweeps]
    lo = float(np.percentile(np.concatenate([value.ravel() for value in values]), 2.0))
    hi = float(np.percentile(np.concatenate([value.ravel() for value in values]), 99.0))
    fig, axes = plt.subplots(3, 2, figsize=(13.5, 11.0), constrained_layout=True)
    fig.patch.set_facecolor(FIELD)
    for ax, (title, _points), value in zip(axes.ravel(), sweeps, values):
        style(ax)
        mesh = ax.pcolormesh(freqs, axis, np.clip(value, lo, hi), cmap="magma", vmin=lo, vmax=hi, shading="auto")
        ax.set_xscale("log")
        ax.set_xlabel("frequency (Hz)", color=INK)
        ax.set_ylabel("sweep position", color=INK)
        ax.set_title(title, color=INK, fontsize=10, loc="left")
        cb = fig.colorbar(mesh, ax=ax, fraction=0.046, pad=0.02)
        cb.set_label("magnitude (dB)", color=INK)
        cb.ax.tick_params(colors=INK, labelsize=7)
    axes.ravel()[-1].axis("off")
    fig.suptitle(f"{name}: packed-domain magnitude sweeps", color=INK, fontsize=14, fontweight="bold")
    finish(fig, out)


def plot_lanes(
    out: Path,
    name: str,
    words: dict[str, list[tuple[int, ...]]],
    freqs: np.ndarray,
    sr: float,
) -> None:
    corners = (
        ("M0 Q0", 0.0, 0.0),
        ("M100 Q0", 1.0, 0.0),
        ("M0 Q100", 0.0, 1.0),
        ("M100 Q100", 1.0, 1.0),
    )
    fig, axes = plt.subplots(3, 2, figsize=(13.0, 10.0), sharex=True, constrained_layout=True)
    fig.patch.set_facecolor(FIELD)
    for lane, ax in enumerate(axes.ravel()):
        style(ax)
        for color, (label, morph, q) in zip(COLORS, corners):
            rows = at(words, morph, q)
            ax.semilogx(freqs, stage_response_db(rows[lane], freqs, sr), color=color, linewidth=1.35, label=label)
        ax.axhline(0.0, color=DIM, linewidth=0.7)
        ax.set_title(f"persistent lane {lane}", color=INK, fontsize=10, loc="left")
        ax.set_ylabel("dB", color=INK)
    for ax in axes[-1]:
        ax.set_xlabel("frequency (Hz)", color=INK)
    axes[0, 0].legend(facecolor="#111711", edgecolor="#405149", labelcolor=INK, fontsize=8, ncol=2)
    fig.suptitle(f"{name}: packed persistent-actor magnitudes", color=INK, fontsize=14, fontweight="bold")
    finish(fig, out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cartridge", type=Path)
    ap.add_argument("--out-dir", type=Path)
    args = ap.parse_args()

    name, sr, words = load_words(args.cartridge)
    out = args.out_dir or args.cartridge.with_name(args.cartridge.name.replace(".cart.json", ".artifacts"))
    max_hz = min(20_000.0, sr * 0.49)
    freqs = np.logspace(math.log10(20.0), math.log10(max_hz), 960)
    outputs = {
        "keypoints": out / "packed_magnitude_keypoints.png",
        "surface": out / "packed_magnitude_surface_5x5.png",
        "sweeps": out / "packed_magnitude_sweeps.png",
        "lanes": out / "packed_lane_magnitudes.png",
    }
    plot_keypoints(outputs["keypoints"], name, words, freqs, sr)
    plot_surface(outputs["surface"], name, words, freqs, sr)
    plot_sweeps(outputs["sweeps"], name, words, freqs, sr)
    plot_lanes(outputs["lanes"], name, words, freqs, sr)
    for label, path in outputs.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
