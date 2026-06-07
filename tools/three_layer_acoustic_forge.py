#!/usr/bin/env python3
"""Three-layer acoustic Forge prototype: Anatomy + Articulation + Survival.

This is clean-room Forge/manual-authoring research, not production training.

Layer 1 Anatomy:
  A locked six-lane pole mountain. Poles move minimally on Morph and tighten
  under Secondary.

Layer 2 Articulation:
  Clean-room zero trajectories. These are original mathematical archetypes,
  not vendor zero tables or preset data.

Layer 3 Survival:
  Per-lane gain budgeting. The compiler measures how much each articulated lane
  would lose relative to its anatomy-only pole stage and bakes makeup into the
  four legal body corners.

The final artifact is still the repo contract: 4 corners x 6 lanes x 5 packed
u16 words = one legal .body240 body.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
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

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words, kernel_to_biquad  # noqa: E402
from src.utils.body240 import (  # noqa: E402
    AUTHORING_SR,
    CORNER_ORDER,
    PACKED_KEYS,
    compiled_payload,
    raw_from_words,
)


TAU = 2.0 * math.pi
OUT_ROOT = ROOT / "dev" / "tmp" / "three_layer_acoustic_forge"
CORNER_POINTS = {
    "M0_Q0": (0.0, 0.0),
    "M100_Q0": (1.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q100": (1.0, 1.0),
}


@dataclass(frozen=True)
class AnatomyLane:
    lane: int
    role: str
    pole_hz: float
    pole_radius_q0: float
    pole_radius_q100: float
    morph_octaves: float
    note: str


@dataclass(frozen=True)
class ArticulationLane:
    lane: int
    mode: str
    zero_home_ratio: float
    zero_away_ratio: float
    zero_radius_q0: float
    zero_radius_q100: float
    depth: float
    note: str


@dataclass(frozen=True)
class CornerLane:
    lane: int
    role: str
    pole_hz: float
    pole_radius: float
    zero_hz: float
    zero_radius: float
    base_gain: float
    survival_db: float
    gain: float
    kernel: tuple[float, float, float, float, float]


@dataclass(frozen=True)
class SurvivalConfig:
    gain_compensation_strategy: str = "normalize_stages"
    factor: float = 0.45
    cap_db: float = 12.0
    loss_percentile: float = 60.0
    band_ratio: float = 2.3
    depth_weight_min: float = 0.35
    pressure_weight_base: float = 0.70
    pressure_weight_q: float = 0.55
    base_gain: float = 0.54
    low_lane_gain_bias: float = 1.18
    high_lane_pressure_trim: float = 0.90
    high_lane_pressure_start: int = 4


@dataclass(frozen=True)
class Recipe:
    name: str
    sample_rate_hz: float
    anatomy: tuple[AnatomyLane, ...]
    articulation: tuple[ArticulationLane, ...]
    survival: SurvivalConfig
    source: str


ANATOMY: tuple[AnatomyLane, ...] = (
    AnatomyLane(0, "chest floor", 92.0, 0.946, 0.985, 0.08, "low mass; defines the body floor"),
    AnatomyLane(1, "throat wall", 330.0, 0.962, 0.991, 0.10, "low-mid room boundary"),
    AnatomyLane(2, "mouth dome", 920.0, 0.974, 0.996, 0.12, "main vowel pressure peak"),
    AnatomyLane(3, "bite ridge", 1850.0, 0.970, 0.997, -0.10, "counter ridge for speaking motion"),
    AnatomyLane(4, "tear rail", 3950.0, 0.966, 0.9982, 0.14, "upper high-Q rail"),
    AnatomyLane(5, "air rail", 7900.0, 0.952, 0.9985, -0.06, "top rail / phaser-like pressure"),
)


ARTICULATION: tuple[ArticulationLane, ...] = (
    ArticulationLane(0, "shelf-knee", 2.15, 2.75, 0.66, 0.82, 0.45, "zero above F0, avoids killing the floor"),
    ArticulationLane(1, "opposing-canyon", 1.70, 0.78, 0.88, 0.97, 0.80, "low-mid canyon crosses down toward the wall"),
    ArticulationLane(2, "mouth-word", 1.18, 0.64, 0.91, 0.985, 0.92, "primary moving mouth cut"),
    ArticulationLane(3, "bite-word", 0.72, 1.58, 0.90, 0.988, 0.95, "counter-motion cut for vowel contrast"),
    ArticulationLane(4, "phaser-canyon", 1.42, 0.92, 0.94, 0.995, 1.00, "near-pole canyon, pressure sensitive"),
    ArticulationLane(5, "air-canyon", 0.86, 1.26, 0.91, 0.996, 0.86, "upper rail shimmer and collapse control"),
)


DEFAULT_SURVIVAL = SurvivalConfig()


def default_recipe_doc() -> dict[str, Any]:
    return {
        "format": "three-layer-acoustic-recipe-v1",
        "name": "cleanroom_three_layer_acoustic_recipe",
        "sample_rate_hz": AUTHORING_SR,
        "clean_room_note": "Original mathematical recipe. No vendor bytes, coefficient tables, filter names, or presets.",
        "anatomy": {
            "poles": [asdict(item) for item in ANATOMY],
        },
        "articulation": {
            "zero_table_archetype": "custom",
            "zeros": [asdict(item) for item in ARTICULATION],
        },
        "survival": asdict(DEFAULT_SURVIVAL),
    }


def _require_keys(item: dict[str, Any], keys: tuple[str, ...], context: str) -> None:
    missing = [key for key in keys if key not in item]
    if missing:
        raise ValueError(f"{context}: missing {', '.join(missing)}")


def _load_anatomy(doc: dict[str, Any]) -> tuple[AnatomyLane, ...]:
    poles = doc.get("anatomy", {}).get("poles")
    if not isinstance(poles, list) or len(poles) != 6:
        raise ValueError("recipe anatomy.poles must contain exactly six lanes")
    lanes = []
    for index, item in enumerate(poles):
        if not isinstance(item, dict):
            raise ValueError(f"anatomy.poles[{index}] must be an object")
        _require_keys(
            item,
            ("lane", "role", "pole_hz", "pole_radius_q0", "pole_radius_q100", "morph_octaves"),
            f"anatomy.poles[{index}]",
        )
        lanes.append(AnatomyLane(
            lane=int(item["lane"]),
            role=str(item["role"]),
            pole_hz=float(item["pole_hz"]),
            pole_radius_q0=float(item["pole_radius_q0"]),
            pole_radius_q100=float(item["pole_radius_q100"]),
            morph_octaves=float(item["morph_octaves"]),
            note=str(item.get("note", "")),
        ))
    return tuple(lanes)


def _load_articulation(doc: dict[str, Any]) -> tuple[ArticulationLane, ...]:
    articulation = doc.get("articulation", {})
    zeros = articulation.get("zeros")
    if not isinstance(zeros, list) or len(zeros) != 6:
        archetype = articulation.get("zero_table_archetype")
        raise ValueError(
            "recipe articulation.zeros must contain exactly six lanes; "
            f"zero_table_archetype={archetype!r} is a label, not hidden data"
        )
    lanes = []
    for index, item in enumerate(zeros):
        if not isinstance(item, dict):
            raise ValueError(f"articulation.zeros[{index}] must be an object")
        _require_keys(
            item,
            ("lane", "mode", "zero_home_ratio", "zero_away_ratio", "zero_radius_q0", "zero_radius_q100", "depth"),
            f"articulation.zeros[{index}]",
        )
        lanes.append(ArticulationLane(
            lane=int(item["lane"]),
            mode=str(item["mode"]),
            zero_home_ratio=float(item["zero_home_ratio"]),
            zero_away_ratio=float(item["zero_away_ratio"]),
            zero_radius_q0=float(item["zero_radius_q0"]),
            zero_radius_q100=float(item["zero_radius_q100"]),
            depth=float(item["depth"]),
            note=str(item.get("note", "")),
        ))
    return tuple(lanes)


def _load_survival(doc: dict[str, Any]) -> SurvivalConfig:
    values = {**asdict(DEFAULT_SURVIVAL), **doc.get("survival", {})}
    strategy = str(values["gain_compensation_strategy"])
    if strategy not in {"normalize_stages", "off"}:
        raise ValueError(f"unsupported survival.gain_compensation_strategy: {strategy!r}")
    if strategy == "off":
        values["factor"] = 0.0
    return SurvivalConfig(
        gain_compensation_strategy=strategy,
        factor=float(values["factor"]),
        cap_db=float(values["cap_db"]),
        loss_percentile=float(values["loss_percentile"]),
        band_ratio=float(values["band_ratio"]),
        depth_weight_min=float(values["depth_weight_min"]),
        pressure_weight_base=float(values["pressure_weight_base"]),
        pressure_weight_q=float(values["pressure_weight_q"]),
        base_gain=float(values["base_gain"]),
        low_lane_gain_bias=float(values["low_lane_gain_bias"]),
        high_lane_pressure_trim=float(values["high_lane_pressure_trim"]),
        high_lane_pressure_start=int(values["high_lane_pressure_start"]),
    )


def load_recipe(path: Path) -> Recipe:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != "three-layer-acoustic-recipe-v1":
        raise ValueError("recipe format must be three-layer-acoustic-recipe-v1")
    anatomy = _load_anatomy(doc)
    articulation = _load_articulation(doc)
    if sorted(item.lane for item in anatomy) != list(range(6)):
        raise ValueError("anatomy lane ids must be 0..5")
    if sorted(item.lane for item in articulation) != list(range(6)):
        raise ValueError("articulation lane ids must be 0..5")
    anatomy_by_lane = tuple(sorted(anatomy, key=lambda item: item.lane))
    articulation_by_lane = tuple(sorted(articulation, key=lambda item: item.lane))
    return Recipe(
        name=str(doc.get("name", path.stem)),
        sample_rate_hz=float(doc.get("sample_rate_hz", AUTHORING_SR)),
        anatomy=anatomy_by_lane,
        articulation=articulation_by_lane,
        survival=_load_survival(doc),
        source=str(path),
    )


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def geom(a: float, b: float, t: float) -> float:
    a = max(float(a), 1e-9)
    b = max(float(b), 1e-9)
    return a * (b / a) ** float(t)


def hz_radius_to_kernel(
    pole_hz: float,
    pole_radius: float,
    zero_hz: float,
    zero_radius: float,
    gain: float,
    sr: float,
) -> tuple[float, float, float, float, float]:
    pole_hz = clamp(pole_hz, 25.0, 0.47 * sr)
    zero_hz = clamp(zero_hz, 25.0, 0.47 * sr)
    pole_radius = clamp(pole_radius, 0.05, 0.99965)
    zero_radius = clamp(zero_radius, 0.0, 0.9997)
    gain = clamp(gain, 1e-5, 3.95)
    wp = TAU * pole_hz / sr
    wz = TAU * zero_hz / sr
    return (
        2.0 - 2.0 * zero_radius * math.cos(wz),
        1.0 - zero_radius * zero_radius,
        2.0 - 2.0 * pole_radius * math.cos(wp),
        1.0 - pole_radius * pole_radius,
        gain,
    )


def biquad_mag_db(kernel: tuple[float, float, float, float, float], freqs: np.ndarray, sr: float) -> np.ndarray:
    b0, b1, b2, a1, a2 = kernel_to_biquad(kernel)
    z = np.exp(-1j * (TAU * freqs / sr))
    h = (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def anatomy_state(lane: AnatomyLane, morph: float, secondary: float, sr: float) -> tuple[float, float]:
    pole = lane.pole_hz * (2.0 ** (lane.morph_octaves * (morph - 0.5)))
    pole = clamp(pole, 30.0, 0.45 * sr)
    radius = lane.pole_radius_q0 + (lane.pole_radius_q100 - lane.pole_radius_q0) * secondary
    return pole, clamp(radius, 0.10, 0.99965)


def zero_state(
    anatomy: AnatomyLane,
    articulation: ArticulationLane,
    morph: float,
    secondary: float,
    sr: float,
) -> tuple[float, float]:
    pole_hz, _ = anatomy_state(anatomy, morph, secondary, sr)
    ratio = geom(articulation.zero_home_ratio, articulation.zero_away_ratio, morph)
    zero_hz = clamp(pole_hz * ratio, 30.0, 0.47 * sr)
    zr = articulation.zero_radius_q0 + (articulation.zero_radius_q100 - articulation.zero_radius_q0) * secondary
    return zero_hz, clamp(zr, 0.05, 0.9997)


def stage_anchor_gain(lane: AnatomyLane, secondary: float, survival: SurvivalConfig) -> float:
    # Broad, conservative starting budget. Survival pass does the real work.
    low_bias = survival.low_lane_gain_bias if lane.lane == 0 else 1.0
    pressure_trim = (
        survival.high_lane_pressure_trim
        if secondary >= 0.5 and lane.lane >= survival.high_lane_pressure_start
        else 1.0
    )
    return survival.base_gain * low_bias * pressure_trim


def survival_makeup_db(
    lane: AnatomyLane,
    articulation: ArticulationLane,
    morph: float,
    secondary: float,
    sr: float,
    freqs: np.ndarray,
    survival: SurvivalConfig,
) -> float:
    pole_hz, pole_radius = anatomy_state(lane, morph, secondary, sr)
    zero_hz, zero_radius = zero_state(lane, articulation, morph, secondary, sr)
    base_gain = stage_anchor_gain(lane, secondary, survival)

    anatomy_kernel = hz_radius_to_kernel(
        pole_hz, pole_radius, zero_hz=pole_hz, zero_radius=0.0, gain=base_gain, sr=sr
    )
    articulated_kernel = hz_radius_to_kernel(
        pole_hz, pole_radius, zero_hz=zero_hz, zero_radius=zero_radius, gain=base_gain, sr=sr
    )
    anatomy_db = biquad_mag_db(anatomy_kernel, freqs, sr)
    articulated_db = biquad_mag_db(articulated_kernel, freqs, sr)

    # Measure loss in the actor's local band, not the whole spectrum. This is
    # stage makeup, not a global loudness normalizer.
    lo = max(35.0, pole_hz / survival.band_ratio)
    hi = min(0.47 * sr, pole_hz * survival.band_ratio)
    band = (freqs >= lo) & (freqs <= hi)
    if not np.any(band):
        return 0.0
    loss = float(np.percentile(anatomy_db[band] - articulated_db[band], survival.loss_percentile))
    depth_weight = survival.depth_weight_min + (1.0 - survival.depth_weight_min) * articulation.depth
    pressure_weight = survival.pressure_weight_base + survival.pressure_weight_q * secondary
    makeup = max(0.0, loss) * depth_weight * pressure_weight * survival.factor
    return clamp(makeup, 0.0, survival.cap_db)


def corner_lane(
    lane: AnatomyLane,
    articulation: ArticulationLane,
    morph: float,
    secondary: float,
    sr: float,
    freqs: np.ndarray,
    survival: SurvivalConfig,
) -> CornerLane:
    pole_hz, pole_radius = anatomy_state(lane, morph, secondary, sr)
    zero_hz, zero_radius = zero_state(lane, articulation, morph, secondary, sr)
    base_gain = stage_anchor_gain(lane, secondary, survival)
    makeup = survival_makeup_db(lane, articulation, morph, secondary, sr, freqs, survival)
    gain = base_gain * (10.0 ** (makeup / 20.0))
    kernel = hz_radius_to_kernel(pole_hz, pole_radius, zero_hz, zero_radius, gain, sr)
    return CornerLane(
        lane=lane.lane,
        role=lane.role,
        pole_hz=round(pole_hz, 6),
        pole_radius=round(pole_radius, 9),
        zero_hz=round(zero_hz, 6),
        zero_radius=round(zero_radius, 9),
        base_gain=round(base_gain, 9),
        survival_db=round(makeup, 6),
        gain=round(gain, 9),
        kernel=tuple(float(v) for v in kernel),
    )


def build_body(
    sr: float,
    survival_factor: float | None = None,
    *,
    anatomy: tuple[AnatomyLane, ...] = ANATOMY,
    articulation: tuple[ArticulationLane, ...] = ARTICULATION,
    survival: SurvivalConfig | None = None,
) -> tuple[bytes, dict[str, list[tuple[int, ...]]], dict[str, Any]]:
    freqs = freq_points()
    if survival is None:
        survival = DEFAULT_SURVIVAL
    if survival_factor is not None:
        survival = SurvivalConfig(**{**asdict(survival), "factor": float(survival_factor)})
    kernels: dict[str, list[tuple[float, ...]]] = {}
    corners: dict[str, list[CornerLane]] = {}
    for label in CORNER_ORDER:
        morph, secondary = CORNER_POINTS[label]
        lanes = [
            corner_lane(a, z, morph, secondary, sr, freqs, survival)
            for a, z in zip(anatomy, articulation)
        ]
        corners[label] = lanes
        kernels[label] = [lane.kernel for lane in lanes]
    words = {
        label: [tuple(int(v) for v in coeffs_to_words(*row)) for row in rows]
        for label, rows in kernels.items()
    }
    return raw_from_words(words), words, {
        "anatomy": [asdict(item) for item in anatomy],
        "articulation": [asdict(item) for item in articulation],
        "survival": asdict(survival),
        "corners": {
            label: [
                {
                    **asdict(lane),
                    "kernel": [round(float(v), 12) for v in lane.kernel],
                }
                for lane in lanes
            ]
            for label, lanes in corners.items()
        },
    }


def body_for_ffi(words: dict[str, list[tuple[int, ...]]]) -> bytes:
    return trench_ffi.body_bytes_from_corner_words({
        PACKED_KEYS[label]: words[label] for label in CORNER_ORDER
    })


def response_at(body: bytes, morph: float, secondary: float, sr: float) -> np.ndarray:
    rows = trench_ffi.packed_interpolate(body, morph, secondary)
    return cascade_response_db([EncodedCoeffs(*row) for row in rows], freq_points(), sr)


def audit(body: bytes, grid: int = 17) -> dict[str, Any]:
    max_radius = 0.0
    unstable = 0
    nonfinite = 0
    rows = []
    for morph in np.linspace(0.0, 1.0, grid):
        for secondary in np.linspace(0.0, 1.0, grid):
            probe = trench_ffi.packed_probe(body, float(morph), float(secondary))
            max_radius = max(max_radius, float(probe["max_pole_radius"]))
            unstable |= int(probe["unstable_mask"])
            nonfinite |= int(probe["nonfinite_mask"])
            if int(probe["unstable_mask"]) or int(probe["nonfinite_mask"]):
                rows.append({
                    "morph": round(float(morph), 6),
                    "secondary": round(float(secondary), 6),
                    "unstable_mask": int(probe["unstable_mask"]),
                    "nonfinite_mask": int(probe["nonfinite_mask"]),
                })
    return {
        "grid": grid,
        "grid_points": grid * grid,
        "max_pole_radius": round(max_radius, 9),
        "unstable_mask": unstable,
        "nonfinite_mask": nonfinite,
        "failures": rows,
    }


def plot_response(name: str, body: bytes, meta: dict[str, Any], out: Path, sr: float) -> None:
    freqs = freq_points()
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.4), facecolor="#070a09")
    for ax in axes.ravel():
        ax.set_facecolor("#090d0c")
        ax.grid(True, which="both", color="#26342f", alpha=0.42, linewidth=0.55)
        ax.tick_params(colors="#a7b4ad", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#25352e")

    for ax, secondary, title in ((axes[0, 0], 0.0, "Q0 morph surface"), (axes[0, 1], 1.0, "Q100 pressurized surface")):
        image = np.array([response_at(body, morph, secondary, sr) for morph in np.linspace(0.0, 1.0, 260)]).T
        lo = float(np.nanpercentile(image, 4))
        hi = float(np.nanpercentile(image, 99.3))
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
        ax.set_title(title, color="#e9efe9", fontsize=10)
        ax.set_xlabel("Morph", color="#a7b4ad", fontsize=8)

    colors = {"M0_Q0": "#e8dfb6", "M100_Q0": "#5bd0ff", "M0_Q100": "#ff9470", "M100_Q100": "#ac95ff"}
    for label in CORNER_ORDER:
        morph, secondary = CORNER_POINTS[label]
        curve = response_at(body, morph, secondary, sr)
        axes[1, 0].semilogx(freqs, np.clip(curve - float(np.max(curve)), -75, 8), color=colors[label], lw=1.6, label=label)
    axes[1, 0].set_title("four baked corners, normalized", color="#e9efe9", fontsize=10)
    axes[1, 0].set_xlim(20, 18000)
    axes[1, 0].set_ylim(-75, 8)
    axes[1, 0].legend(facecolor="#101713", edgecolor="#27372f", labelcolor="#e9efe9", fontsize=8)

    lane_ids = [lane["lane"] for lane in meta["corners"]["M100_Q100"]]
    gains = [lane["survival_db"] for lane in meta["corners"]["M100_Q100"]]
    axes[1, 1].bar(lane_ids, gains, color="#76d5aa", width=0.62)
    axes[1, 1].set_title("survival makeup at tight-away", color="#e9efe9", fontsize=10)
    axes[1, 1].set_xlabel("lane", color="#a7b4ad", fontsize=8)
    axes[1, 1].set_ylabel("dB", color="#a7b4ad", fontsize=8)
    axes[1, 1].set_ylim(0, max(4.0, max(gains) * 1.2))

    fig.suptitle(name, color="#e9efe9", fontsize=13)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=135)
    plt.close(fig)


def plot_stages(name: str, words: dict[str, list[tuple[int, ...]]], meta: dict[str, Any], out: Path, sr: float) -> None:
    freqs = freq_points()
    colors = {"M0_Q0": "#e8dfb6", "M100_Q0": "#5bd0ff", "M0_Q100": "#ff9470", "M100_Q100": "#ac95ff"}
    fig, axes = plt.subplots(2, 3, figsize=(15.6, 8.6), facecolor="#070a09")
    for lane_index, ax in enumerate(axes.ravel()):
        ax.set_facecolor("#090d0c")
        lane_meta = meta["corners"]["M100_Q100"][lane_index]
        for label in CORNER_ORDER:
            kernel = tuple(float(v) for v in meta["corners"][label][lane_index]["kernel"])
            curve = biquad_mag_db(kernel, freqs, sr)
            ax.semilogx(freqs, np.clip(curve - float(np.max(curve)), -64, 16),
                        color=colors[label], lw=1.35, label=label)
            pole = float(meta["corners"][label][lane_index]["pole_hz"])
            zero = float(meta["corners"][label][lane_index]["zero_hz"])
            ax.axvline(pole, color=colors[label], alpha=0.22, linewidth=0.8)
            ax.scatter([zero], [-58], color=colors[label], marker="v", s=20, alpha=0.85)
        ax.set_title(
            f"lane {lane_index}: {lane_meta['role']}  +{lane_meta['survival_db']:.1f} dB",
            color="#e9efe9",
            fontsize=9,
        )
        ax.set_xlim(20, 18000)
        ax.set_ylim(-64, 16)
        ax.grid(True, which="both", color="#26342f", alpha=0.42, linewidth=0.55)
        ax.tick_params(colors="#a7b4ad", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#25352e")
    axes.ravel()[0].legend(facecolor="#101713", edgecolor="#27372f", labelcolor="#e9efe9", fontsize=7)
    fig.suptitle(f"{name}: individual stage/lane responses (triangles = zeros/canyons)", color="#e9efe9", fontsize=13)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=135)
    plt.close(fig)


def write_index(report: dict[str, Any], out_dir: Path) -> None:
    rows = []
    for lane in report["layer_report"]["corners"]["M100_Q100"]:
        rows.append(
            "<tr>"
            f"<td>{lane['lane']}</td><td>{html.escape(lane['role'])}</td>"
            f"<td>{lane['pole_hz']:.1f}</td><td>{lane['zero_hz']:.1f}</td>"
            f"<td>{lane['pole_radius']:.5f}</td><td>{lane['zero_radius']:.5f}</td>"
            f"<td>{lane['survival_db']:.2f}</td><td>{lane['gain']:.3f}</td>"
            "</tr>"
        )
    page = f"""<!doctype html><meta charset=utf-8>
<title>{html.escape(report['name'])}</title>
<style>
body{{background:#070a09;color:#d7ded9;font:14px/1.45 system-ui,sans-serif;margin:24px}}
img{{max-width:100%;border:1px solid #26342f}}
table{{border-collapse:collapse;margin-top:16px}}
td,th{{border:1px solid #26342f;padding:6px 9px}}
th{{color:#9fe7c6;background:#101713}}
code{{color:#a7f0c1}}
</style>
<h1>{html.escape(report['name'])}</h1>
<p>Clean-room three-layer body: Anatomy poles, Articulation zeros, Survival gain. Runtime authority is the packed .body240.</p>
<h2>Full Cascade</h2>
<img src="{html.escape(report['outputs']['plot'])}">
<h2>Stages / Lanes</h2>
<img src="{html.escape(report['outputs']['stages_plot'])}">
<h2>Tight-Away Survival Budget</h2>
<table><tr><th>lane</th><th>role</th><th>pole Hz</th><th>zero Hz</th><th>pole r</th><th>zero r</th><th>makeup dB</th><th>gain</th></tr>
{''.join(rows)}
</table>
<p><code>{html.escape(report['outputs']['body240'])}</code></p>
"""
    (out_dir / "index.html").write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean-room Anatomy + Articulation + Survival body compiler")
    parser.add_argument("--recipe", type=Path, help="three-layer-acoustic-recipe-v1 JSON input")
    parser.add_argument("--write-default-recipe", type=Path, help="write an editable recipe JSON and exit")
    parser.add_argument("--name", default=None, help="override recipe/output name")
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    parser.add_argument("--survival-factor", type=float, default=None, help="override recipe survival.factor")
    parser.add_argument("--boost", type=float, default=1.0)
    parser.add_argument("--sr", type=float, default=None, help="override recipe sample_rate_hz")
    args = parser.parse_args()

    if args.write_default_recipe:
        args.write_default_recipe.parent.mkdir(parents=True, exist_ok=True)
        args.write_default_recipe.write_text(json.dumps(default_recipe_doc(), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.write_default_recipe}")
        return

    if not trench_ffi.available():
        raise SystemExit("trench-core unavailable; build with cargo build --release -p trench-core")

    if args.recipe:
        recipe = load_recipe(args.recipe)
    else:
        recipe = Recipe(
            name="cleanroom_three_layer_acoustic_system",
            sample_rate_hz=AUTHORING_SR,
            anatomy=ANATOMY,
            articulation=ARTICULATION,
            survival=DEFAULT_SURVIVAL,
            source="built-in-default",
        )

    name = args.name or recipe.name
    sr = float(args.sr if args.sr is not None else recipe.sample_rate_hz)
    survival = recipe.survival
    if args.survival_factor is not None:
        survival = SurvivalConfig(**{**asdict(survival), "factor": float(args.survival_factor)})

    out_dir = args.out / name
    out_dir.mkdir(parents=True, exist_ok=True)

    body, words, layer_report = build_body(
        sr,
        anatomy=recipe.anatomy,
        articulation=recipe.articulation,
        survival=survival,
    )
    if body != body_for_ffi(words):
        raise RuntimeError("body serializer mismatch between body240 and trench_ffi")
    audit_report = audit(body, grid=17)
    body_path = out_dir / f"{name}.body240"
    cart_path = out_dir / f"{name}.cart.json"
    plot_path = out_dir / "response.png"
    stages_plot_path = out_dir / "stages.png"
    report_path = out_dir / "report.json"
    body_path.write_bytes(body)
    cart_path.write_text(json.dumps(compiled_payload(name, args.boost, words), indent=2) + "\n", encoding="utf-8")
    plot_response(name, body, layer_report, plot_path, sr)
    plot_stages(name, words, layer_report, stages_plot_path, sr)

    report = {
        "format": "three-layer-acoustic-forge-v1",
        "name": name,
        "recipe_source": recipe.source,
        "clean_room_note": "Original mathematical anatomy/zero archetypes only. No vendor bodies, bytes, coefficient tables, names, or presets are used.",
        "runtime_authority": ".body240 packed words plus trench-core packed_probe",
        "body240_sha256": hashlib.sha256(body).hexdigest(),
        "survival_factor": float(survival.factor),
        "audit": audit_report,
        "layer_report": layer_report,
        "outputs": {
            "body240": body_path.name,
            "cart": cart_path.name,
            "plot": plot_path.name,
            "stages_plot": stages_plot_path.name,
            "index": "index.html",
        },
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_index(report, out_dir)
    print(f"wrote {body_path}")
    print(f"wrote {cart_path}")
    print(f"wrote {plot_path}")
    print(f"wrote {report_path}")
    print(f"max pole radius {audit_report['max_pole_radius']}")
    print(f"unstable_mask {audit_report['unstable_mask']} nonfinite_mask {audit_report['nonfinite_mask']}")
    print(f"body240 sha256 {report['body240_sha256']}")


if __name__ == "__main__":
    main()
