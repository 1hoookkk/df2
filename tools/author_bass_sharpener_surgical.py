#!/usr/bin/env python3
"""Bake the Bass Sharpener surgical morph body.

Clean-room authoring pass: the reference XML is treated as a gesture only.
The emitted runtime body is six active pole/zero biquads, packed and plotted
through trench_core.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words, words_to_coeffs  # noqa: E402
from src.utils.body240 import AUTHORING_SR, CORNER_ORDER, compiled_payload, raw_from_words  # noqa: E402
from src.utils.packed_runtime import evaluate_body  # noqa: E402
from tools.three_layer_acoustic_forge import CORNER_POINTS, audit, response_at  # noqa: E402


TAU = 2.0 * math.pi
OUT = ROOT / "dev" / "tmp" / "law_author" / "bass_sharpener_surgical"
SHIP_BODY = ROOT / "presets" / "v1_bass_sharpener.body240"
SHIP_CART = ROOT / "juce-shell" / "assets" / "cartridges" / "v1_bass_sharpener.json"


@dataclass(frozen=True)
class Lane:
    lane: int
    role: str
    pole_m0: float
    pole_m100: float
    pole_r0: float
    pole_r1: float
    zero_m0: float
    zero_m100: float
    zero_r0: float
    zero_r1: float
    dc_db_m0: float
    dc_db_m100: float
    note: str


LANES = (
    Lane(
        0,
        "sub pin",
        72.0,
        76.0,
        0.900,
        0.944,
        148.0,
        132.0,
        0.620,
        0.735,
        2.6,
        3.0,
        "held low foundation; keeps the bass present while the higher lanes cut",
    ),
    Lane(
        1,
        "low plane",
        145.0,
        236.0,
        0.900,
        0.962,
        310.0,
        405.0,
        0.760,
        0.885,
        1.9,
        2.3,
        "first LP-style knee; moves logarithmically into the old designer low-mid number",
    ),
    Lane(
        2,
        "tickle ridge",
        236.0,
        520.0,
        0.918,
        0.982,
        520.0,
        910.0,
        0.835,
        0.952,
        1.2,
        1.6,
        "moving bass ridge; this is the audible tickle as Morph comes up",
    ),
    Lane(
        3,
        "flat cut",
        620.0,
        1080.0,
        0.790,
        0.925,
        1120.0,
        1540.0,
        0.900,
        0.987,
        -0.3,
        -0.6,
        "first surgical zero; carves the angled plateau instead of adding another bump",
    ),
    Lane(
        4,
        "angle lock",
        1420.0,
        2470.0,
        0.690,
        0.850,
        2300.0,
        3400.0,
        0.925,
        0.992,
        -1.4,
        -2.2,
        "locks the descending plane above the bass formant",
    ),
    Lane(
        5,
        "zero shear",
        3250.0,
        4200.0,
        0.570,
        0.710,
        5050.0,
        5850.0,
        0.940,
        0.996,
        -2.8,
        -4.3,
        "high zero shear; gives the high Morph corner its hard LP cliff",
    ),
)

MORPH_FOCUS_POLE = (0.025, 0.045, 0.057, 0.135, 0.160, 0.145)
MORPH_FOCUS_ZERO = (0.085, 0.060, 0.095, 0.080, 0.067, 0.056)
FILTER_Q_EFFECT = 0.0


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def log_lerp(a: float, b: float, t: float) -> float:
    return float(a) * (float(b) / float(a)) ** float(t)


def dc_pin_gain(
    pole_hz: float,
    pole_radius: float,
    zero_hz: float,
    zero_radius: float,
    dc_db: float,
    sr: float,
) -> float:
    wp = TAU * pole_hz / sr
    wz = TAU * zero_hz / sr
    den0 = 1.0 - 2.0 * pole_radius * math.cos(wp) + pole_radius * pole_radius
    num0 = 1.0 - 2.0 * zero_radius * math.cos(wz) + zero_radius * zero_radius
    target = 10.0 ** (float(dc_db) / 20.0)
    return clamp(target * den0 / max(num0, 1.0e-9), 1.0e-5, 3.95)


def stage_kernel(
    pole_hz: float,
    pole_radius: float,
    zero_hz: float,
    zero_radius: float,
    gain: float,
    sr: float,
) -> tuple[float, float, float, float, float]:
    pole_hz = clamp(pole_hz, 25.0, 0.47 * sr)
    zero_hz = clamp(zero_hz, 25.0, 0.47 * sr)
    pole_radius = clamp(pole_radius, 0.05, 0.99945)
    zero_radius = clamp(zero_radius, 0.0, 0.9996)
    wp = TAU * pole_hz / sr
    wz = TAU * zero_hz / sr
    return (
        2.0 - 2.0 * zero_radius * math.cos(wz),
        1.0 - zero_radius * zero_radius,
        2.0 - 2.0 * pole_radius * math.cos(wp),
        1.0 - pole_radius * pole_radius,
        clamp(gain, 1.0e-5, 3.95),
    )


def corner_lane(lane: Lane, morph: float, q: float) -> dict[str, Any]:
    pole_hz = log_lerp(lane.pole_m0, lane.pole_m100, morph)
    zero_hz = log_lerp(lane.zero_m0, lane.zero_m100, morph)
    filter_q = q * FILTER_Q_EFFECT
    pole_r = lane.pole_r0 + (lane.pole_r1 - lane.pole_r0) * filter_q
    zero_r = lane.zero_r0 + (lane.zero_r1 - lane.zero_r0) * filter_q

    # The high Morph corner is meant to feel surgical even when the plugin uses
    # the Slam axis instead of filter-Q. Bake a small amount of endpoint focus
    # into Morph while preserving frequency lock across the secondary axis.
    if morph >= 0.5:
        focus = (morph - 0.5) * 2.0
        pole_r = clamp(pole_r + focus * MORPH_FOCUS_POLE[lane.lane], 0.05, 0.99945)
        zero_r = clamp(zero_r + focus * MORPH_FOCUS_ZERO[lane.lane], 0.0, 0.9996)

    dc_db = lane.dc_db_m0 + (lane.dc_db_m100 - lane.dc_db_m0) * morph
    gain = dc_pin_gain(pole_hz, pole_r, zero_hz, zero_r, dc_db, AUTHORING_SR)
    kernel = stage_kernel(pole_hz, pole_r, zero_hz, zero_r, gain, AUTHORING_SR)
    return {
        "lane": lane.lane,
        "role": lane.role,
        "pole_hz": round(pole_hz, 6),
        "pole_radius": round(pole_r, 9),
        "zero_hz": round(zero_hz, 6),
        "zero_radius": round(zero_r, 9),
        "dc_db": round(dc_db, 6),
        "gain": round(gain, 9),
        "kernel": [round(float(v), 12) for v in kernel],
        "note": lane.note,
    }


def build_body() -> tuple[bytes, dict[str, list[tuple[int, ...]]], dict[str, Any]]:
    words: dict[str, list[tuple[int, ...]]] = {}
    corners: dict[str, list[dict[str, Any]]] = {}
    for label in CORNER_ORDER:
        morph, q = CORNER_POINTS[label]
        lanes = [corner_lane(lane, morph, q) for lane in LANES]
        corners[label] = lanes
        words[label] = [tuple(int(v) for v in coeffs_to_words(*lane["kernel"])) for lane in lanes]
    return raw_from_words(words), words, {
        "format": "bass-sharpener-surgical-authoring-v1",
        "sample_rate_hz": AUTHORING_SR,
        "clean_room_note": "Six original pole/zero lanes. Reference XML used only as a morph gesture, not as copied coefficients or tables.",
        "lanes": [asdict(lane) for lane in LANES],
        "corners": corners,
    }


def curve_stats(body: bytes) -> dict[str, Any]:
    freqs = freq_points()
    result: dict[str, Any] = {}
    for label, (morph, q) in CORNER_POINTS.items():
        curve = response_at(body, morph, q, AUTHORING_SR)
        result[label] = {
            "peak_db": round(float(np.max(curve)), 4),
            "floor_db": round(float(np.min(curve)), 4),
            "span_db": round(float(np.max(curve) - np.min(curve)), 4),
            "db_60": round(float(np.interp(60.0, freqs, curve)), 4),
            "db_236": round(float(np.interp(236.0, freqs, curve)), 4),
            "db_520": round(float(np.interp(520.0, freqs, curve)), 4),
            "db_1080": round(float(np.interp(1080.0, freqs, curve)), 4),
            "db_4200": round(float(np.interp(4200.0, freqs, curve)), 4),
            "db_9000": round(float(np.interp(9000.0, freqs, curve)), 4),
        }
    return result


def plot_body(body: bytes, meta: dict[str, Any], out: Path) -> None:
    freqs = freq_points()
    colors = {
        "M0_Q0": "#e8dfb6",
        "M100_Q0": "#5bd0ff",
        "M0_Q100": "#ff9470",
        "M100_Q100": "#ac95ff",
    }
    fig = plt.figure(figsize=(16.2, 12.0), facecolor="#070a09")
    gs = fig.add_gridspec(4, 3, height_ratios=[1.05, 1.05, 0.82, 0.82])
    ax_main = fig.add_subplot(gs[:2, :2])
    ax_main.set_facecolor("#090d0c")
    for label, (morph, q) in CORNER_POINTS.items():
        curve = response_at(body, morph, q, AUTHORING_SR)
        ax_main.semilogx(freqs, np.clip(curve, -80, 30), color=colors[label], lw=1.8, label=label)
    for hz in (76, 236, 520, 1080, 2470, 4200, 5850):
        ax_main.axvline(hz, color="#49564f", alpha=0.28, linewidth=0.8)
    ax_main.set_title("Bass Sharpener surgical body - packed trench_core response", color="#ecf3ef", fontsize=12)
    ax_main.set_xlim(20, 18000)
    ax_main.set_ylim(-42, 24)
    ax_main.grid(True, which="both", color="#26342f", alpha=0.42, linewidth=0.55)
    ax_main.tick_params(colors="#a7b4ad", labelsize=8)
    ax_main.legend(facecolor="#101713", edgecolor="#27372f", labelcolor="#e9efe9", fontsize=8)

    for row, q in enumerate((0.0, 1.0)):
        ax = fig.add_subplot(gs[row, 2])
        ax.set_facecolor("#090d0c")
        image = np.array([response_at(body, float(m), q, AUTHORING_SR) for m in np.linspace(0.0, 1.0, 260)]).T
        lo = float(np.nanpercentile(image, 4.0))
        hi = float(np.nanpercentile(image, 99.2))
        ax.imshow(
            np.clip(image, lo, max(hi, lo + 1.0)),
            aspect="auto",
            origin="lower",
            cmap="magma",
            extent=[0, 1, 0, len(freqs)],
            vmin=lo,
            vmax=max(hi, lo + 1.0),
        )
        ymarks = [60, 150, 400, 1000, 2500, 6000, 12000]
        yidx = [int(np.argmin(np.abs(freqs - freq))) for freq in ymarks]
        ax.set_yticks(yidx)
        ax.set_yticklabels([str(freq) for freq in ymarks], color="#a7b4ad")
        ax.set_title(f"Morph surface at {'Q0 / plugin path' if q == 0.0 else 'Slam axis locked'}", color="#ecf3ef", fontsize=9)
        ax.set_xlabel("Morph", color="#a7b4ad", fontsize=8)
        ax.tick_params(colors="#a7b4ad", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#25352e")

    for lane_index in range(6):
        ax = fig.add_subplot(gs[2 + lane_index // 3, lane_index % 3])
        ax.set_facecolor("#090d0c")
        for label in ("M0_Q0", "M100_Q0"):
            row = tuple(float(v) for v in words_to_coeffs(tuple(meta["packedWords"][label][lane_index])))
            curve = cascade_response_db([EncodedCoeffs(*row)], freqs, AUTHORING_SR)
            curve -= float(np.max(curve))
            ax.semilogx(freqs, np.clip(curve, -54, 10), color=colors[label], lw=1.2)
            zero = meta["corners"][label][lane_index]["zero_hz"]
            ax.scatter([zero], [-50 + lane_index * 1.0], marker="v", color=colors[label], s=18, alpha=0.85)
        lane = meta["corners"]["M100_Q0"][lane_index]
        ax.set_title(f"{lane_index}: {lane['role']}", color="#ecf3ef", fontsize=8)
        ax.set_xlim(20, 18000)
        ax.set_ylim(-54, 8)
        ax.grid(True, which="both", color="#26342f", alpha=0.33, linewidth=0.45)
        ax.tick_params(colors="#a7b4ad", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#25352e")

    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140)
    plt.close(fig)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def bake(install: bool) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    body, words, meta = build_body()
    meta["packedWords"] = {label: [[int(v) for v in row] for row in rows] for label, rows in words.items()}
    cart = compiled_payload("bass_sharpener", 1.0, words)
    cart.update(
        {
            "provenance": "clean-room six-lane Bass Sharpener surgical morph; zeros authored for flat angled LP carve",
            "authoring": {
                "body": "six active pole-zero biquads",
                "morph": "log-feel fixed-axis move in plugin; high corner is surgical endpoint",
                "secondary": "plugin labels this axis Slam; packed secondary corners mirror Q0 so no filter-Q is hidden in the body",
                "reference_usage": "gesture study only; no copied coefficients, preset bytes, or protected tables",
            },
        }
    )

    body_path = OUT / "bass_sharpener.body240"
    cart_path = OUT / "bass_sharpener.cartridge.json"
    meta_path = OUT / "stages.json"
    audit_path = OUT / "audit.json"
    metrics_path = OUT / "metrics.json"
    plot_path = OUT / "plot_surgical.png"

    body_path.write_bytes(body)
    write_json(cart_path, cart)
    write_json(meta_path, meta)
    audit_report = audit(body, grid=21)
    metrics = evaluate_body(body, 17)
    report = {
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "cart_sha256": hashlib.sha256(cart_path.read_bytes()).hexdigest(),
        "body_bytes": len(body),
        "audit": audit_report,
        "curve_stats": curve_stats(body),
        "metrics": metrics,
    }
    write_json(audit_path, audit_report)
    write_json(metrics_path, report)
    plot_body(body, meta, plot_path)

    if install:
        shutil.copyfile(body_path, SHIP_BODY)
        shutil.copyfile(cart_path, SHIP_CART)

    return {
        **report,
        "paths": {
            "body": str(body_path),
            "cartridge": str(cart_path),
            "stages": str(meta_path),
            "audit": str(audit_path),
            "metrics": str(metrics_path),
            "plot": str(plot_path),
            "installed_body": str(SHIP_BODY) if install else None,
            "installed_cartridge": str(SHIP_CART) if install else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="copy the baked body/cartridge into the plugin assets")
    args = parser.parse_args()
    report = bake(args.install)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
