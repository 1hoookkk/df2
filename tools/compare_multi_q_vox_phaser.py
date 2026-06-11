#!/usr/bin/env python3
"""Compare P2K Multi Q Vox against X3 Phaser 1/2 response foundations.

Clean-room study tool: this compares decoded shapes and roots only. It does not
copy vendor bytes into generated products.
"""
from __future__ import annotations

import itertools
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import packed_interp, trench_ffi  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402


P2K_BODY = ROOT / "ref" / "presets" / "P2k_012_multi_q_vox.bin"
BLOCKS = ROOT / "ref" / "x3_menu" / "runtime_blocks"
OUT = ROOT / "dev" / "tmp" / "multi_q_vox_phaser_foundation"
P2K_SR = 39062.5
X3_SR = 48000.0
CORNER_LABELS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")


def biquad_response_db(bq: tuple[float, float, float, float, float], freqs: np.ndarray, sr: float) -> np.ndarray:
    b0, b1, b2, a1, a2 = bq
    z = np.exp(-1j * (2.0 * np.pi * freqs / sr))
    h = (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def cascade_direct_response_db(rows: list[tuple[float, float, float, float, float]], freqs: np.ndarray, sr: float) -> np.ndarray:
    out = np.zeros_like(freqs, dtype=float)
    for row in rows:
        out += biquad_response_db(row, freqs, sr)
    return out


def read_x3_block(name: str, stages: int = 2) -> list[list[tuple[float, float, float, float, float]]]:
    raw = (BLOCKS / f"{name}_48000.raw").read_bytes()
    words = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    per_corner = stages * 5
    corners: list[list[tuple[float, float, float, float, float]]] = []
    for ci in range(4):
        seg = words[ci * per_corner:(ci + 1) * per_corner]
        rows = []
        for si in range(stages):
            w = seg[si * 5:si * 5 + 5]
            # Probe-verified X3 fixed-class decode:
            # canonical DF2T slots [b0,b1,b2,a1,a2] = raw slots [2,3,4,0,1] / 16384.
            rows.append(tuple(float(w[i]) / 16384.0 for i in (2, 3, 4, 0, 1)))  # type: ignore[arg-type]
        corners.append(rows)
    return corners


def p2k_corner_rows(body: bytes) -> list[list[tuple[float, float, float, float, float]]]:
    corners = []
    for morph, q in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
        kernels = trench_ffi.packed_interpolate(body, morph, q)
        corners.append([packed_interp.kernel_to_biquad(tuple(row)) for row in kernels])
    return corners


def normed_rms(a: np.ndarray, b: np.ndarray) -> float:
    aa = a - float(np.mean(a))
    bb = b - float(np.mean(b))
    return float(np.sqrt(np.mean((aa - bb) ** 2)))


def raw_rms(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def root_summary(bq: tuple[float, float, float, float, float], sr: float) -> dict[str, list[dict[str, float]]]:
    b0, b1, b2, a1, a2 = bq

    def roots(poly: tuple[float, float, float]) -> list[dict[str, float]]:
        found = np.roots(poly)
        out = []
        for z in found:
            freq = abs(float(np.angle(z))) * sr / (2.0 * math.pi)
            out.append({"hz": round(freq, 3), "radius": round(abs(complex(z)), 6)})
        return sorted(out, key=lambda item: (item["hz"], item["radius"]))

    return {
        "zeros": roots((b0, b1, b2)),
        "poles": roots((1.0, a1, a2)),
    }


def stage_pair_scores(
    p2k_rows: list[list[tuple[float, float, float, float, float]]],
    x3_rows: list[list[tuple[float, float, float, float, float]]],
    freqs: np.ndarray,
) -> list[dict[str, Any]]:
    scores = []
    for pair in itertools.combinations(range(6), 2):
        normed = []
        raw = []
        for ci in range(4):
            p2k_curve = cascade_direct_response_db([p2k_rows[ci][pair[0]], p2k_rows[ci][pair[1]]], freqs, P2K_SR)
            x3_curve = cascade_direct_response_db(x3_rows[ci], freqs, X3_SR)
            normed.append(normed_rms(p2k_curve, x3_curve))
            raw.append(raw_rms(p2k_curve, x3_curve))
        scores.append({
            "p2k_stage_pair": pair,
            "mean_offset_normalized_rms_db": round(float(np.mean(normed)), 4),
            "max_offset_normalized_rms_db": round(float(np.max(normed)), 4),
            "mean_raw_rms_db": round(float(np.mean(raw)), 4),
        })
    return sorted(scores, key=lambda row: row["mean_offset_normalized_rms_db"])


def whole_scores(
    p2k_rows: list[list[tuple[float, float, float, float, float]]],
    x3_rows: list[list[tuple[float, float, float, float, float]]],
    freqs: np.ndarray,
) -> dict[str, float]:
    normed = []
    raw = []
    for ci in range(4):
        p2k_curve = cascade_direct_response_db(p2k_rows[ci], freqs, P2K_SR)
        x3_curve = cascade_direct_response_db(x3_rows[ci], freqs, X3_SR)
        normed.append(normed_rms(p2k_curve, x3_curve))
        raw.append(raw_rms(p2k_curve, x3_curve))
    return {
        "mean_offset_normalized_rms_db": round(float(np.mean(normed)), 4),
        "mean_raw_rms_db": round(float(np.mean(raw)), 4),
    }


def plot_overlay(
    p2k_rows: list[list[tuple[float, float, float, float, float]]],
    ph1: list[list[tuple[float, float, float, float, float]]],
    ph2: list[list[tuple[float, float, float, float, float]]],
    ph1_pair: tuple[int, int],
    ph2_pair: tuple[int, int],
    freqs: np.ndarray,
    out: Path,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 8.0), facecolor="#070a09")
    colors = {
        "p2k_all": "#f3efc4",
        "p2k_pair": "#62d5ff",
        "phaser1": "#ff8f70",
        "phaser2": "#b49cff",
    }
    for ci, ax in enumerate(axes.ravel()):
        curves = {
            "Multi Q Vox all 6": cascade_direct_response_db(p2k_rows[ci], freqs, P2K_SR),
            f"Multi Q Vox pair {ph1_pair}": cascade_direct_response_db([p2k_rows[ci][i] for i in ph1_pair], freqs, P2K_SR),
            "X3 Phaser 1": cascade_direct_response_db(ph1[ci], freqs, X3_SR),
            "X3 Phaser 2": cascade_direct_response_db(ph2[ci], freqs, X3_SR),
            f"Multi Q Vox pair {ph2_pair}": cascade_direct_response_db([p2k_rows[ci][i] for i in ph2_pair], freqs, P2K_SR),
        }
        ref = max(float(np.percentile(curves["Multi Q Vox all 6"], 95)), 1e-9)
        ax.set_facecolor("#090d0c")
        ax.semilogx(freqs, np.clip(curves["Multi Q Vox all 6"] - ref, -80, 24), color=colors["p2k_all"], lw=1.9, label="Multi Q Vox all 6")
        ax.semilogx(freqs, np.clip(curves[f"Multi Q Vox pair {ph1_pair}"] - np.mean(curves[f"Multi Q Vox pair {ph1_pair}"]), -80, 24), color=colors["p2k_pair"], lw=1.2, label=f"best P2K pair vs Phaser 1 {ph1_pair}")
        ax.semilogx(freqs, np.clip(curves["X3 Phaser 1"] - np.mean(curves["X3 Phaser 1"]), -80, 24), color=colors["phaser1"], lw=1.2, label="Phaser 1")
        ax.semilogx(freqs, np.clip(curves[f"Multi Q Vox pair {ph2_pair}"] - np.mean(curves[f"Multi Q Vox pair {ph2_pair}"]), -80, 24), color=colors["p2k_pair"], lw=1.0, alpha=0.55, label=f"best P2K pair vs Phaser 2 {ph2_pair}")
        ax.semilogx(freqs, np.clip(curves["X3 Phaser 2"] - np.mean(curves["X3 Phaser 2"]), -80, 24), color=colors["phaser2"], lw=1.2, label="Phaser 2")
        ax.set_title(CORNER_LABELS[ci], color="#e9efe9", fontsize=10)
        ax.set_xlim(20, 18000)
        ax.set_ylim(-80, 24)
        ax.grid(True, which="both", color="#25362f", alpha=0.42, linewidth=0.55)
        ax.tick_params(colors="#a7b4ad", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#25362f")
    axes.ravel()[0].legend(facecolor="#101713", edgecolor="#26342f", labelcolor="#e9efe9", fontsize=7)
    fig.suptitle("Multi Q Vox vs X3 Phaser 1/2 decoded response foundations", color="#e9efe9")
    fig.tight_layout()
    fig.savefig(out, dpi=135)
    plt.close(fig)


def main() -> None:
    if not trench_ffi.available():
        raise SystemExit("trench-core unavailable; build with cargo build --release -p trench-core")
    OUT.mkdir(parents=True, exist_ok=True)
    body = P2K_BODY.read_bytes()
    p2k = p2k_corner_rows(body)
    phaser1 = read_x3_block("phaser_1")
    phaser2 = read_x3_block("phaser_2")
    freqs = freq_points()
    freqs = freqs[(freqs >= 20.0) & (freqs <= 18000.0)]

    ph1_pairs = stage_pair_scores(p2k, phaser1, freqs)
    ph2_pairs = stage_pair_scores(p2k, phaser2, freqs)
    best_ph1 = tuple(ph1_pairs[0]["p2k_stage_pair"])
    best_ph2 = tuple(ph2_pairs[0]["p2k_stage_pair"])
    plot_overlay(p2k, phaser1, phaser2, best_ph1, best_ph2, freqs, OUT / "overlay.png")

    report: dict[str, Any] = {
        "format": "multi-q-vox-vs-x3-phaser-foundation-v1",
        "clean_room_note": "Study-only decoded shape comparison. P2K packed and X3 fixed-point bytes are not copied into product artifacts.",
        "x3_decode": {
            "observed_by_probe": "2-pole lowpass oracle leaves one candidate",
            "representation": "direct_df2t",
            "scale": "i16 / 16384",
            "word_order_to_b0_b1_b2_a1_a2": [2, 3, 4, 0, 1],
        },
        "whole_cascade_vs_phaser1": whole_scores(p2k, phaser1, freqs),
        "whole_cascade_vs_phaser2": whole_scores(p2k, phaser2, freqs),
        "best_p2k_stage_pairs_vs_phaser1": ph1_pairs[:8],
        "best_p2k_stage_pairs_vs_phaser2": ph2_pairs[:8],
        "p2k_roots": {
            CORNER_LABELS[ci]: [root_summary(row, P2K_SR) for row in p2k[ci]]
            for ci in range(4)
        },
        "phaser1_roots": {
            CORNER_LABELS[ci]: [root_summary(row, X3_SR) for row in phaser1[ci]]
            for ci in range(4)
        },
        "phaser2_roots": {
            CORNER_LABELS[ci]: [root_summary(row, X3_SR) for row in phaser2[ci]]
            for ci in range(4)
        },
        "plot": "overlay.png",
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'report.json'}")
    print(f"open {OUT / 'overlay.png'}")
    print("best P2K pair vs Phaser 1:", ph1_pairs[0])
    print("best P2K pair vs Phaser 2:", ph2_pairs[0])
    print("whole vs Phaser 1:", report["whole_cascade_vs_phaser1"])
    print("whole vs Phaser 2:", report["whole_cascade_vs_phaser2"])


if __name__ == "__main__":
    main()
