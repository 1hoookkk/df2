#!/usr/bin/env python3
"""Build the compact browser data module for Forge phone authoring."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.law_author import Law, compile_law, load_law

CONTRACTS = ROOT / "dev" / "tmp" / "x3_p2k_family_browser" / "contracts"
VOCAB = ROOT / "dev" / "tmp" / "p2k_full_vocabulary"
LAWS = ROOT / "recipes" / "laws"
OUT = ROOT / "forge-web" / "data" / "family-laws.js"

CORNER_MAP = {
    "M0_S0": "M0_Q0",
    "M1_S0": "M100_Q0",
    "M0_S1": "M0_Q100",
    "M1_S1": "M100_Q100",
}

MOVE_BY_FAMILY = {
    "bandpass_swept_eq": "high bank collapse",
    "morph_special": "remote-cut violence",
    "phaser_comb": "comb/phaser field",
    "slope_ladder": "shelf/cliff frame",
    "vocal_formant": "talking vowel glide",
}

FUNDAMENTAL_SEEDS: list[dict[str, Any]] = [
    {
        "format": "section-law-v1",
        "name": "root_contrary_bp_shelf",
        "family": "root_crossing",
        "title": "CONTRARY BP SHELF",
        "move": "contrary crossing / band-pass shelf",
        "intent": "A band-pass window whose shelf frame and zeros travel against the pole rows.",
        "bias": "Use when the center should feel like a moving window, not a polite EQ bump.",
        "anchor_hz": 194.0,
        "anchor_gain_db": 4.5,
        "tilt_db": 8.0,
        "canyon_depth": 27.0,
        "q_crank": 0.78,
        "morph_spread": 0.86,
        "density": 0.78,
        "sections": [
            {"role": "anchor", "fc_hz": 194.0, "gain_db": 3.5, "bw_oct": 2.6, "zero_offset_oct": -1.25, "morph_oct": 0.22, "zero_morph_oct": 1.35, "zero_secondary_oct": -0.35, "q_weight": 0.65},
            {"role": "bp_lower_wall", "fc_hz": 545.0, "gain_db": -6.5, "bw_oct": 0.85, "zero_offset_oct": -1.15, "morph_oct": 1.05, "zero_morph_oct": -1.05, "zero_secondary_oct": 0.25, "q_weight": 0.9},
            {"role": "bp_mouth_peak", "fc_hz": 780.0, "gain_db": 5.2, "bw_oct": 0.72, "zero_offset_oct": 0.62, "morph_oct": 1.25, "zero_morph_oct": -1.10, "zero_secondary_oct": 0.15, "q_weight": 1.0},
            {"role": "shelf_hinge", "fc_hz": 2220.0, "gain_db": 2.8, "bw_oct": 1.25, "zero_offset_oct": -0.78, "morph_oct": -0.65, "zero_morph_oct": 1.18, "zero_secondary_oct": -0.22, "q_weight": 0.82},
            {"role": "remote_canyon", "fc_hz": 4440.0, "gain_db": -9.0, "bw_oct": 0.58, "zero_offset_oct": -1.85, "morph_oct": -0.55, "zero_morph_oct": 1.75, "zero_secondary_oct": 0.42, "q_weight": 0.95},
            {"role": "air_kill", "fc_hz": 9650.0, "gain_db": -5.8, "bw_oct": 1.10, "zero_offset_oct": 0.72, "morph_oct": -1.0, "zero_morph_oct": -1.05, "zero_secondary_oct": 0.35, "q_weight": 0.55},
        ],
    },
    {
        "format": "section-law-v1",
        "name": "root_peak_shelf_morph",
        "family": "root_shelf",
        "title": "PEAK/SHELF MORPH",
        "move": "low-pass / mid-shelf / high-pass continuum",
        "intent": "Operator-style Peak/Shelf Morph behavior: frequency means different things as the shelf frame turns.",
        "bias": "Use as the calibration seed for shelf fundamentals before adding character rows.",
        "anchor_hz": 200.0,
        "anchor_gain_db": 3.8,
        "tilt_db": 14.0,
        "canyon_depth": 20.0,
        "q_crank": 0.62,
        "morph_spread": 0.78,
        "density": 0.62,
        "sections": [
            {"role": "anchor", "fc_hz": 200.0, "gain_db": 2.6, "bw_oct": 3.2, "zero_offset_oct": -1.60, "morph_oct": 0.25, "zero_morph_oct": 0.35, "zero_secondary_oct": -0.10, "q_weight": 0.55},
            {"role": "dark_shelf", "fc_hz": 390.0, "gain_db": -7.0, "bw_oct": 2.0, "zero_offset_oct": -1.0, "morph_oct": 1.4, "zero_morph_oct": 0.95, "zero_secondary_oct": 0.0, "q_weight": 0.65},
            {"role": "mid_shelf", "fc_hz": 780.0, "gain_db": 3.0, "bw_oct": 1.8, "zero_offset_oct": 0.25, "morph_oct": 0.85, "zero_morph_oct": -0.35, "zero_secondary_oct": 0.12, "q_weight": 0.85},
            {"role": "peak_hinge", "fc_hz": 2220.0, "gain_db": 4.5, "bw_oct": 0.85, "zero_offset_oct": -0.18, "morph_oct": 0.35, "zero_morph_oct": 0.10, "zero_secondary_oct": -0.18, "q_weight": 1.0},
            {"role": "bright_shelf", "fc_hz": 4130.0, "gain_db": 2.2, "bw_oct": 1.7, "zero_offset_oct": 0.92, "morph_oct": -0.55, "zero_morph_oct": -1.10, "zero_secondary_oct": 0.15, "q_weight": 0.72},
            {"role": "air_cap", "fc_hz": 8250.0, "gain_db": -4.0, "bw_oct": 1.35, "zero_offset_oct": 0.80, "morph_oct": -0.9, "zero_morph_oct": -0.85, "zero_secondary_oct": 0.18, "q_weight": 0.42},
        ],
    },
    {
        "format": "section-law-v1",
        "name": "root_dark_cliff_frame",
        "family": "root_shelf",
        "title": "DARK CLIFF FRAME",
        "move": "hard descending cliff with character rows inside",
        "intent": "The broad keep/kill frame first; character rows sit inside a descending wall.",
        "bias": "Use when the top must fall into the mouth/bite area instead of opening upward.",
        "anchor_hz": 134.0,
        "anchor_gain_db": 4.0,
        "tilt_db": -18.0,
        "canyon_depth": 30.0,
        "q_crank": 0.70,
        "morph_spread": 0.82,
        "density": 0.72,
        "sections": [
            {"role": "anchor", "fc_hz": 134.0, "gain_db": 3.0, "bw_oct": 3.4, "zero_offset_oct": -1.15, "morph_oct": 0.15, "zero_morph_oct": 0.30, "zero_secondary_oct": 0.0, "q_weight": 0.45},
            {"role": "cliff", "fc_hz": 390.0, "gain_db": -10.0, "bw_oct": 1.4, "zero_offset_oct": -0.65, "morph_oct": 1.0, "zero_morph_oct": 0.80, "zero_secondary_oct": 0.25, "q_weight": 0.80},
            {"role": "remote_cut", "fc_hz": 780.0, "gain_db": -8.2, "bw_oct": 0.74, "zero_offset_oct": -1.55, "morph_oct": 0.95, "zero_morph_oct": 1.25, "zero_secondary_oct": 0.35, "q_weight": 0.92},
            {"role": "mouth_bite", "fc_hz": 2180.0, "gain_db": 3.2, "bw_oct": 0.86, "zero_offset_oct": 0.30, "morph_oct": -0.35, "zero_morph_oct": -0.45, "zero_secondary_oct": 0.0, "q_weight": 0.88},
            {"role": "tear_cut", "fc_hz": 4130.0, "gain_db": -8.6, "bw_oct": 0.70, "zero_offset_oct": -0.92, "morph_oct": -0.85, "zero_morph_oct": 0.95, "zero_secondary_oct": 0.22, "q_weight": 0.76},
            {"role": "air_kill", "fc_hz": 7200.0, "gain_db": -13.4, "bw_oct": 0.9, "zero_offset_oct": -0.18, "morph_oct": -1.3, "zero_morph_oct": -0.65, "zero_secondary_oct": 0.12, "q_weight": 0.50},
        ],
    },
    {
        "format": "section-law-v1",
        "name": "root_bright_shelf_frame",
        "family": "root_shelf",
        "title": "BRIGHT SHELF FRAME",
        "move": "rising shelf with restrained air cap",
        "intent": "A broad rising frame, with air restraint so it reads as shelf rather than fizz.",
        "bias": "Use for bright shelf fundamentals before adding remote violence.",
        "anchor_hz": 320.0,
        "anchor_gain_db": 3.2,
        "tilt_db": 18.0,
        "canyon_depth": 18.0,
        "q_crank": 0.54,
        "morph_spread": 0.72,
        "density": 0.58,
        "sections": [
            {"role": "anchor", "fc_hz": 320.0, "gain_db": 2.2, "bw_oct": 2.8, "zero_offset_oct": -1.30, "morph_oct": 0.30, "zero_morph_oct": 0.25, "zero_secondary_oct": -0.10, "q_weight": 0.45},
            {"role": "low_keep", "fc_hz": 545.0, "gain_db": -3.0, "bw_oct": 2.2, "zero_offset_oct": -0.75, "morph_oct": 0.35, "zero_morph_oct": 0.20, "zero_secondary_oct": 0.0, "q_weight": 0.45},
            {"role": "shelf_rise", "fc_hz": 1200.0, "gain_db": 2.8, "bw_oct": 1.9, "zero_offset_oct": 0.45, "morph_oct": 0.65, "zero_morph_oct": -0.20, "zero_secondary_oct": 0.05, "q_weight": 0.72},
            {"role": "bite_peak", "fc_hz": 2220.0, "gain_db": 4.0, "bw_oct": 0.95, "zero_offset_oct": 0.18, "morph_oct": 0.45, "zero_morph_oct": -0.12, "zero_secondary_oct": -0.15, "q_weight": 0.95},
            {"role": "tear_shelf", "fc_hz": 4440.0, "gain_db": 2.5, "bw_oct": 1.35, "zero_offset_oct": 0.65, "morph_oct": -0.25, "zero_morph_oct": -0.60, "zero_secondary_oct": 0.12, "q_weight": 0.65},
            {"role": "air_restraint", "fc_hz": 9650.0, "gain_db": -4.8, "bw_oct": 0.95, "zero_offset_oct": 0.55, "morph_oct": -0.55, "zero_morph_oct": -0.70, "zero_secondary_oct": 0.35, "q_weight": 0.52},
        ],
    },
    {
        "format": "section-law-v1",
        "name": "root_remote_cut_bp",
        "family": "root_bp",
        "title": "REMOTE-CUT BP",
        "move": "band-pass body with cuts walking away",
        "intent": "The zeros are the actors; peaks hold a window while remote cuts move separately.",
        "bias": "Use when polite band-pass laws feel too static or too all-pole.",
        "anchor_hz": 365.0,
        "anchor_gain_db": 4.0,
        "tilt_db": 4.0,
        "canyon_depth": 32.0,
        "q_crank": 0.82,
        "morph_spread": 0.92,
        "density": 0.82,
        "sections": [
            {"role": "anchor", "fc_hz": 365.0, "gain_db": 2.8, "bw_oct": 2.4, "zero_offset_oct": -1.10, "morph_oct": 0.25, "zero_morph_oct": 0.20, "zero_secondary_oct": -0.20, "q_weight": 0.55},
            {"role": "lower_bp_wall", "fc_hz": 780.0, "gain_db": -7.2, "bw_oct": 0.72, "zero_offset_oct": -1.80, "morph_oct": 0.95, "zero_morph_oct": 1.70, "zero_secondary_oct": 0.40, "q_weight": 1.0},
            {"role": "mouth_peak", "fc_hz": 1200.0, "gain_db": 4.8, "bw_oct": 0.78, "zero_offset_oct": 0.22, "morph_oct": 0.55, "zero_morph_oct": -0.40, "zero_secondary_oct": -0.12, "q_weight": 0.95},
            {"role": "bite_peak", "fc_hz": 2220.0, "gain_db": 3.8, "bw_oct": 0.82, "zero_offset_oct": -0.15, "morph_oct": 0.35, "zero_morph_oct": -0.75, "zero_secondary_oct": 0.0, "q_weight": 0.88},
            {"role": "remote_canyon", "fc_hz": 4440.0, "gain_db": -10.5, "bw_oct": 0.55, "zero_offset_oct": -2.30, "morph_oct": -0.65, "zero_morph_oct": 2.15, "zero_secondary_oct": 0.55, "q_weight": 1.0},
            {"role": "air_kill", "fc_hz": 8250.0, "gain_db": -7.5, "bw_oct": 0.90, "zero_offset_oct": 0.85, "morph_oct": -0.85, "zero_morph_oct": -1.30, "zero_secondary_oct": 0.30, "q_weight": 0.70},
        ],
    },
    {
        "format": "section-law-v1",
        "name": "root_mouth_window",
        "family": "root_mouth",
        "title": "MOUTH WINDOW",
        "move": "vowel window / bite glide",
        "intent": "Keep the body legible while one or two mouth rows sweep hard.",
        "bias": "Use for OOH/AAH/EEE-style motion without copying any reference row.",
        "anchor_hz": 390.0,
        "anchor_gain_db": 4.0,
        "tilt_db": 8.0,
        "canyon_depth": 24.0,
        "q_crank": 0.74,
        "morph_spread": 0.70,
        "density": 0.78,
        "sections": [
            {"role": "anchor", "fc_hz": 390.0, "gain_db": 2.6, "bw_oct": 2.2, "zero_offset_oct": -0.90, "morph_oct": -0.20, "zero_morph_oct": 0.25, "zero_secondary_oct": -0.12, "q_weight": 0.55},
            {"role": "mouth_f1", "fc_hz": 780.0, "gain_db": 5.8, "bw_oct": 0.95, "zero_offset_oct": 0.06, "morph_oct": -0.55, "zero_morph_oct": 0.20, "zero_secondary_oct": 0.0, "q_weight": 1.0},
            {"role": "mouth_f2", "fc_hz": 1200.0, "gain_db": 4.8, "bw_oct": 0.88, "zero_offset_oct": 0.18, "morph_oct": 0.85, "zero_morph_oct": -0.20, "zero_secondary_oct": 0.0, "q_weight": 1.0},
            {"role": "bite", "fc_hz": 2220.0, "gain_db": 3.4, "bw_oct": 0.82, "zero_offset_oct": -0.10, "morph_oct": 0.62, "zero_morph_oct": -0.45, "zero_secondary_oct": 0.12, "q_weight": 0.92},
            {"role": "tear_canyon", "fc_hz": 3790.0, "gain_db": -6.2, "bw_oct": 0.70, "zero_offset_oct": -0.75, "morph_oct": -0.35, "zero_morph_oct": 0.80, "zero_secondary_oct": 0.22, "q_weight": 0.72},
            {"role": "air_kill", "fc_hz": 8875.0, "gain_db": -5.2, "bw_oct": 1.05, "zero_offset_oct": 0.65, "morph_oct": -0.70, "zero_morph_oct": -0.70, "zero_secondary_oct": 0.20, "q_weight": 0.55},
        ],
    },
    {
        "format": "section-law-v1",
        "name": "root_comb_phaser_field",
        "family": "root_comb",
        "title": "COMB/PHASER FIELD",
        "move": "staged cut field / allpass-like rows",
        "intent": "Rows act as a field of cuts, not a stack of peaks.",
        "bias": "Use when the plot needs staged canyons and coherent center motion.",
        "anchor_hz": 450.0,
        "anchor_gain_db": 2.8,
        "tilt_db": 2.0,
        "canyon_depth": 28.0,
        "q_crank": 0.66,
        "morph_spread": 0.74,
        "density": 0.86,
        "sections": [
            {"role": "anchor", "fc_hz": 450.0, "gain_db": 1.8, "bw_oct": 1.8, "zero_offset_oct": -0.10, "morph_oct": 0.18, "zero_morph_oct": -0.18, "zero_secondary_oct": 0.0, "q_weight": 0.50},
            {"role": "notch_1", "fc_hz": 780.0, "gain_db": -7.0, "bw_oct": 0.52, "zero_offset_oct": 0.18, "morph_oct": 0.35, "zero_morph_oct": -0.32, "zero_secondary_oct": 0.12, "q_weight": 0.88},
            {"role": "notch_2", "fc_hz": 1200.0, "gain_db": -6.5, "bw_oct": 0.50, "zero_offset_oct": -0.20, "morph_oct": -0.28, "zero_morph_oct": 0.34, "zero_secondary_oct": -0.10, "q_weight": 0.84},
            {"role": "notch_3", "fc_hz": 2180.0, "gain_db": -7.8, "bw_oct": 0.46, "zero_offset_oct": 0.16, "morph_oct": 0.46, "zero_morph_oct": -0.55, "zero_secondary_oct": 0.18, "q_weight": 0.92},
            {"role": "blade", "fc_hz": 4440.0, "gain_db": -8.4, "bw_oct": 0.44, "zero_offset_oct": -0.22, "morph_oct": -0.42, "zero_morph_oct": 0.68, "zero_secondary_oct": -0.16, "q_weight": 0.86},
            {"role": "air_notch", "fc_hz": 8250.0, "gain_db": -5.5, "bw_oct": 0.62, "zero_offset_oct": 0.28, "morph_oct": -0.58, "zero_morph_oct": -0.35, "zero_secondary_oct": 0.20, "q_weight": 0.62},
        ],
    },
    {
        "format": "section-law-v1",
        "name": "root_high_bank_collapse",
        "family": "root_collapse",
        "title": "HIGH BANK COLLAPSE",
        "move": "falling air bank into mouth/bite",
        "intent": "High rows collapse down into mouth/bite while high zeros cut the top.",
        "bias": "This is the opposite of merely opening the high band upward.",
        "anchor_hz": 390.0,
        "anchor_gain_db": 4.2,
        "tilt_db": -8.0,
        "canyon_depth": 15.0,
        "q_crank": 0.48,
        "morph_spread": 0.88,
        "density": 0.80,
        "sections": [
            {"role": "anchor", "fc_hz": 390.0, "gain_db": 2.8, "bw_oct": 2.5, "zero_offset_oct": -1.0, "morph_oct": 0.08, "zero_morph_oct": 0.25, "zero_secondary_oct": 0.0, "q_weight": 0.50},
            {"role": "low_keep", "fc_hz": 545.0, "gain_db": 1.4, "bw_oct": 1.8, "zero_offset_oct": -0.35, "morph_oct": 0.28, "zero_morph_oct": 0.15, "zero_secondary_oct": -0.10, "q_weight": 0.48},
            {"role": "mouth_landing", "fc_hz": 780.0, "gain_db": 3.8, "bw_oct": 0.92, "zero_offset_oct": 0.22, "morph_oct": 0.55, "zero_morph_oct": -0.20, "zero_secondary_oct": 0.0, "q_weight": 0.82},
            {"role": "bite_landing", "fc_hz": 2220.0, "gain_db": 3.0, "bw_oct": 0.76, "zero_offset_oct": -0.18, "morph_oct": -0.35, "zero_morph_oct": 0.32, "zero_secondary_oct": 0.12, "q_weight": 0.90},
            {"role": "falling_tear", "fc_hz": 9650.0, "gain_db": -5.4, "bw_oct": 0.92, "zero_offset_oct": 0.18, "morph_oct": -0.80, "zero_morph_oct": -0.05, "zero_secondary_oct": 0.10, "q_weight": 0.56},
            {"role": "air_kill", "fc_hz": 18000.0, "gain_db": -6.4, "bw_oct": 1.20, "zero_offset_oct": 0.05, "morph_oct": -0.25, "zero_morph_oct": 0.00, "zero_secondary_oct": 0.05, "q_weight": 0.35},
        ],
    },
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def law_from_data(data: dict[str, Any], fallback_name: str) -> Law:
    return Law(
        name=str(data.get("name") or fallback_name),
        anchor_hz=float(data.get("anchor_hz", 190.0)),
        anchor_gain_db=float(data.get("anchor_gain_db", 6.5)),
        tilt_db=float(data.get("tilt_db", 16.0)),
        canyon_depth=float(data.get("canyon_depth", 18.0)),
        q_crank=max(0.0, min(1.0, float(data.get("q_crank", 0.8)))),
        morph_spread=max(0.0, min(1.0, float(data.get("morph_spread", 0.7)))),
        density=max(0.0, min(1.0, float(data.get("density", 0.75)))),
        format=str(data.get("format", "scalar-law-v1")),
        family=str(data.get("family", "root_crossing")),
        sections=tuple(data.get("sections") or ()),
        source_contract=data.get("source_contract"),
    )


def top_rails(limit: int = 10) -> list[dict[str, Any]]:
    path = VOCAB / "frequency_rails.csv"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("band") in {"mouth", "low-mid", "tear", "air", "bite", "low"}:
                rows.append(
                    {
                        "kind": row.get("kind", ""),
                        "hz": float(row.get("rail_hz") or 0.0),
                        "band": row.get("band", ""),
                        "hits": int(row.get("total_hits") or 0),
                        "states": row.get("top_states", ""),
                    }
                )
    rows.sort(key=lambda r: (r["hits"], r["hz"]), reverse=True)
    return rows[:limit]


def lane_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": row["role"],
        "poleHz": row["pole_hz"],
        "poleR": row["pole_r"],
        "zeroHz": row["zero_hz"],
        "zeroR": row["zero_r"],
        "gain": row["gain"],
    }


def law_payload(path: Path) -> dict[str, Any]:
    law_data = load_json(path)
    return law_data_payload(law_data, source=str(path.relative_to(ROOT)))


def law_data_payload(law_data: dict[str, Any], source: str) -> dict[str, Any]:
    family = law_data["family"]
    contract_path = CONTRACTS / f"{family}.json"
    contract = load_json(contract_path) if contract_path.exists() else {}
    compiled = compile_law(law_from_data(law_data, law_data.get("name", "law")))
    corners = {
        CORNER_MAP[label]: [lane_payload(row) for row in rows]
        for label, rows in compiled.items()
        if label in CORNER_MAP
    }
    metrics = contract.get("aggregate_metrics") or law_data.get("aggregate_metrics") or {}
    sections = law_data.get("sections") or []
    source_law = {
        "format": law_data.get("format", "section-law-v1"),
        "name": law_data["name"],
        "family": family,
        "title": law_data.get("title"),
        "intent": law_data.get("intent"),
        "bias": law_data.get("bias"),
        "move": law_data.get("move"),
        "anchor_hz": law_data.get("anchor_hz"),
        "anchor_gain_db": law_data.get("anchor_gain_db"),
        "tilt_db": law_data.get("tilt_db"),
        "canyon_depth": law_data.get("canyon_depth"),
        "q_crank": law_data.get("q_crank"),
        "morph_spread": law_data.get("morph_spread"),
        "density": law_data.get("density"),
        "source_contract": law_data.get("source_contract"),
        "sections": sections,
    }
    return {
        "id": law_data["name"],
        "family": family,
        "title": law_data.get("title") or contract.get("title") or law_data["name"].replace("_", " "),
        "intent": law_data.get("intent") or contract.get("intent") or "",
        "bias": law_data.get("bias") or contract.get("contract_bias") or "",
        "move": law_data.get("move") or MOVE_BY_FAMILY.get(family, family.replace("_", " ")),
        "source": source,
        "cleanRoom": "derived from aggregate foundation measurements and row-motion rails; no reference bytes, packed words, endpoint curves, names, or preset tables are copied",
        "controls": {
            "anchorHz": law_data.get("anchor_hz"),
            "tiltDb": law_data.get("tilt_db"),
            "canyonDepth": law_data.get("canyon_depth"),
            "qCrank": law_data.get("q_crank"),
            "morphSpread": law_data.get("morph_spread"),
            "density": law_data.get("density"),
        },
        "metrics": {
            "morphDb": metrics.get("p2k_median_morph_motion_rms_db"),
            "qDb": metrics.get("p2k_median_q_pressure_rms_db"),
            "tiltDb": metrics.get("median_low_minus_high_tilt_db"),
        },
        "law": source_law,
        "roles": [str(s.get("role", f"section_{i + 1}")) for i, s in enumerate(sections)],
        "corners": corners,
    }


def main() -> int:
    laws = [law_data_payload(data, source="dev/tmp/measured_foundations + aggregate row-motion rails") for data in FUNDAMENTAL_SEEDS]
    payload = {
        "format": "forge-web-family-laws-v2",
        "source": {
            "laws": "tools/build_forge_family_data.py:FUNDAMENTAL_SEEDS",
            "fundamentals": "dev/tmp/measured_foundations/summary.json",
            "vocabulary": "dev/tmp/measured_foundations/{foundation_families.csv,authoring_rails.csv,report.md}",
            "boundary": "clean-room constructors only; no protected bytes, packed words, endpoint curves, names, or preset tables are copied",
        },
        "rails": top_rails(),
        "families": laws,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "export const FAMILY_AUTHORING = "
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + ";\nexport const FAMILY_LAWS = FAMILY_AUTHORING.families;\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({len(laws)} families)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
