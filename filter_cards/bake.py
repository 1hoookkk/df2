#!/usr/bin/env python3
"""Bake clean-room Peak/Shelf filter cards into DF2 .body240 bodies.

This is the stripped authoring path:

    filter card params
      -> six root-domain pole/zero lanes
      -> packed .body240 via tools.author_lanes/tools.author_body
      -> trench_core packed probe audit
      -> response.png / workbench.html

It does not copy legacy bytes, coefficient tables, preset tables, or protected
names. The default card is a clean-room contrary Peak/Shelf sweep derived from
the public parameter grammar: FREQ -> pole angle, SHELF -> zero angle, PEAK ->
pole radius plus a small gain coupling.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from tools import author_body  # noqa: E402
from tools.author_lanes import AUTHORING_SR, body_to_packed_v1  # noqa: E402

CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
STAGES = 6
FREQS = np.geomspace(30.0, 18000.0, 720)
MEASURED_FOUNDATIONS = ROOT / "dev" / "tmp" / "measured_foundations" / "summary.json"
LOW_ZERO_RAIL_HZ = 35.0
HIGH_ZERO_RAIL_HZ = 18000.0
NYQUIST_AUTHOR_HZ = AUTHORING_SR * 0.5
MAX_AUTHOR_HZ = AUTHORING_SR * 0.49
CANONICAL_LOW_ANCHOR_HZ = (530.0, 390.0, 355.0, 270.0, 780.0, 194.0, 98.0)
FALLBACK_LOW_ANCHORS = [
    {"hz": 530.0, "band": "low-mid", "skin_count": 41, "total_hits": 135},
    {"hz": 390.0, "band": "low-mid", "skin_count": 40, "total_hits": 370},
    {"hz": 355.0, "band": "low-mid", "skin_count": 39, "total_hits": 120},
    {"hz": 270.0, "band": "low", "skin_count": 36, "total_hits": 110},
    {"hz": 780.0, "band": "mouth", "skin_count": 31, "total_hits": 203},
    {"hz": 194.0, "band": "low", "skin_count": 26, "total_hits": 292},
    {"hz": 98.0, "band": "sub", "skin_count": 21, "total_hits": 239},
]


@dataclass(frozen=True)
class BakeProduct:
    card: dict[str, Any]
    corners: dict[str, list[dict[str, Any]]]
    body: bytes
    cartridge: dict[str, Any]
    audit: dict[str, Any]
    heatmap: list[list[float]]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def safe_name(value: object, fallback: str = "filter_card") -> str:
    out = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or fallback)).strip("._-")
    return (out or fallback)[:80]


def hz_fmt(value: float) -> str:
    return f"{value / 1000.0:.2f}k" if value >= 1000.0 else f"{value:.0f}"


def log_lerp_hz(a: float, b: float, t: float) -> float:
    a = clamp(a, 20.0, MAX_AUTHOR_HZ)
    b = clamp(b, 20.0, MAX_AUTHOR_HZ)
    return math.exp(math.log(a) + clamp(t, 0.0, 1.0) * (math.log(b) - math.log(a)))


def measured_low_anchor_options() -> list[dict[str, Any]]:
    """Measured low anchors from aggregate study data.

    The source is intentionally aggregate-only: no packed words, no coefficient
    rows, no endpoint curves, and no preset tables.
    """
    if not MEASURED_FOUNDATIONS.exists():
        return [dict(row) for row in FALLBACK_LOW_ANCHORS]
    try:
        data = json.loads(MEASURED_FOUNDATIONS.read_text(encoding="utf-8"))
    except Exception:
        return [dict(row) for row in FALLBACK_LOW_ANCHORS]
    rails = []
    for row in data.get("authoring_rails", []):
        if row.get("kind") != "pole":
            continue
        band = str(row.get("band", ""))
        try:
            hz = float(row.get("hz"))
            skins = int(row.get("skin_count"))
            hits = int(row.get("total_hits"))
        except (TypeError, ValueError):
            continue
        if band not in {"sub", "low", "low-mid", "mouth"}:
            continue
        if hz > 900.0:
            continue
        rails.append({"hz": hz, "band": band, "skin_count": skins, "total_hits": hits})
    by_target = []
    for target in CANONICAL_LOW_ANCHOR_HZ:
        match = min(rails, key=lambda r: abs(float(r["hz"]) - target), default=None)
        if match is None or abs(float(match["hz"]) - target) > 6.0:
            fallback = next((row for row in FALLBACK_LOW_ANCHORS if abs(row["hz"] - target) < 1e-6), None)
            if fallback:
                by_target.append(dict(fallback))
            continue
        row = dict(match)
        row["hz"] = target
        by_target.append(row)
    return by_target or [dict(row) for row in FALLBACK_LOW_ANCHORS]


def shelf_to_zero_hz(pole_hz: float, shelf: float) -> float:
    """SHELF -> zero angle.

    Negative shelf moves the zero up toward the high rail (lowpass behavior).
    Positive shelf moves it down toward the low rail (highpass behavior).

    The exponents intentionally calibrate the clean-room tutorial anchors:
    FREQ=246/SHELF=-50 -> roughly 14 kHz, and
    FREQ=4488/SHELF=+30 -> roughly 800 Hz.
    """
    pole_hz = clamp(pole_hz, 20.0, MAX_AUTHOR_HZ)
    shelf = clamp(shelf, -64.0, 63.0)
    if shelf < 0.0:
        t = (abs(shelf) / 64.0) ** 0.25
        return clamp(log_lerp_hz(pole_hz, HIGH_ZERO_RAIL_HZ, t), 20.0, MAX_AUTHOR_HZ)
    if shelf > 0.0:
        t = (shelf / 63.0) ** 1.40
        return clamp(log_lerp_hz(pole_hz, LOW_ZERO_RAIL_HZ, t), 20.0, MAX_AUTHOR_HZ)
    return pole_hz


def shelf_to_zero_radius(shelf: float, pole_r: float) -> float:
    amount = abs(clamp(shelf, -64.0, 63.0)) / (64.0 if shelf < 0 else 63.0)
    if amount < 1e-4:
        return clamp(pole_r - 0.24, 0.08, 0.92)
    return clamp(0.42 + 0.52 * (amount ** 0.70), 0.12, 0.985)


def peak_to_radius(peak_db: float) -> float:
    """PEAK -> pole radius.

    Calibrated anchors:
      -24 dB -> heavily damped/wide
      +1.5 dB -> tight resonant bite
    Values above +1.5 continue toward the safety rim for the Q100 corner.
    """
    peak_db = float(peak_db)
    if peak_db <= -24.0:
        return clamp(0.46 + 0.12 * math.exp((peak_db + 24.0) / 12.0), 0.40, 0.58)
    if peak_db <= 1.5:
        t = (peak_db + 24.0) / 25.5
        t = t * t * (3.0 - 2.0 * t)
        return 0.58 + t * (0.985 - 0.58)
    return clamp(0.985 + (0.9975 - 0.985) * (1.0 - math.exp(-(peak_db - 1.5) / 10.0)), 0.985, 0.9975)


def peak_to_gain(peak_db: float, gain_db: float = 0.0) -> float:
    # PEAK affects volume in the source grammar, but only lightly here. The main
    # "peak" behavior belongs to pole radius; hard gain changes are left explicit.
    coupled_db = float(gain_db) + 0.18 * float(peak_db)
    return clamp(10.0 ** (coupled_db / 20.0), 0.12, 2.5)


def default_card() -> dict[str, Any]:
    return {
        "format": "filter-card-v1",
        "name": "contrary_peak_shelf_sweep",
        "description": "Clean-room contrary Peak/Shelf sweep: dark low keep -> high-mid tear.",
        "authoring_sample_rate_hz": AUTHORING_SR,
        "foundation": {
            "enabled": True,
            "lane": 2,
            "anchor_hz": 530.0,
            "source": "dev/tmp/measured_foundations/summary.json",
        },
        "q_peak_db": 3.0,
        "q_gain_db": 0.8,
        "sections": [
            {
                "lane": 1,
                "kind": "peak_shelf",
                "label": "contrary tear actor",
                "home": {"freq_hz": 246.0, "shelf": -50.0, "peak_db": -24.0, "gain_db": 0.0},
                "away": {"freq_hz": 4488.0, "shelf": 30.0, "peak_db": 1.5, "gain_db": 0.0},
            },
            {"lane": 2, "kind": "identity", "label": "neutral"},
            {"lane": 3, "kind": "identity", "label": "neutral"},
            {"lane": 4, "kind": "identity", "label": "neutral"},
            {"lane": 5, "kind": "identity", "label": "neutral"},
            {"lane": 6, "kind": "identity", "label": "neutral"},
        ],
    }


def normalize_endpoint(raw: dict[str, Any]) -> dict[str, float]:
    return {
        "freq_hz": clamp(float(raw.get("freq_hz", raw.get("freq", 1000.0))), 20.0, MAX_AUTHOR_HZ),
        "shelf": clamp(float(raw.get("shelf", 0.0)), -64.0, 63.0),
        "peak_db": clamp(float(raw.get("peak_db", raw.get("peak", 0.0))), -48.0, 18.0),
        "gain_db": clamp(float(raw.get("gain_db", 0.0)), -36.0, 18.0),
    }


def normalize_card(data: dict[str, Any]) -> dict[str, Any]:
    card = default_card()
    merged = {**card, **(data or {})}
    foundation_in = merged.get("foundation") if isinstance(merged.get("foundation"), dict) else {}
    foundation = {
        "enabled": bool(foundation_in.get("enabled", card["foundation"]["enabled"])),
        "lane": int(clamp(float(foundation_in.get("lane", card["foundation"]["lane"])), 1.0, float(STAGES))),
        "anchor_hz": clamp(float(foundation_in.get("anchor_hz", card["foundation"]["anchor_hz"])), 30.0, 900.0),
        "source": "dev/tmp/measured_foundations/summary.json",
    }
    raw_sections = merged.get("sections")
    if not isinstance(raw_sections, list):
        raw_sections = card["sections"]
    sections: list[dict[str, Any]] = []
    for i in range(STAGES):
        src = raw_sections[i] if i < len(raw_sections) and isinstance(raw_sections[i], dict) else {"kind": "identity"}
        kind = str(src.get("kind", "identity"))
        if kind != "peak_shelf":
            sections.append({"lane": i + 1, "kind": "identity", "label": str(src.get("label", "neutral"))})
            continue
        sections.append(
            {
                "lane": i + 1,
                "kind": "peak_shelf",
                "label": str(src.get("label", f"section {i + 1}")),
                "home": normalize_endpoint(src.get("home", {})),
                "away": normalize_endpoint(src.get("away", {})),
                "q_peak_db": clamp(float(src.get("q_peak_db", merged.get("q_peak_db", 0.0))), -12.0, 18.0),
                "q_gain_db": clamp(float(src.get("q_gain_db", merged.get("q_gain_db", 0.0))), -12.0, 12.0),
            }
        )
    return {
        "format": "filter-card-v1",
        "name": safe_name(merged.get("name"), "filter_card"),
        "description": str(merged.get("description", "")),
        "authoring_sample_rate_hz": AUTHORING_SR,
        "zero_rails_hz": {"low": LOW_ZERO_RAIL_HZ, "high": HIGH_ZERO_RAIL_HZ},
        "foundation": foundation,
        "measured_low_anchor_options": measured_low_anchor_options(),
        "calibration": {
            "shelf_to_zero": "negative shelf -> high zero rail; positive shelf -> low zero rail",
            "peak_to_radius": "-24 dB -> damped, +1.5 dB -> resonant",
        },
        "sections": sections,
    }


def identity_lane(lane_index: int) -> dict[str, Any]:
    # Pole and zero are identical, so this stage is effectively flat while still
    # satisfying the first-class zero contract.
    hz = 16000.0 - lane_index * 350.0
    r = 0.42
    return {
        "lane": lane_index + 1,
        "role": "identity",
        "pole_hz": hz,
        "pole_r": r,
        "zero_hz": hz,
        "zero_r": r,
        "gain": 1.0,
    }


def foundation_lane(lane_index: int, anchor_hz: float, q: float) -> dict[str, Any]:
    """Measured low-anchor foundation lane.

    The pole is pinned to an aggregate recurring low anchor. The zero is an air
    counterweight, so the lane behaves like a broad structural body rather than
    another local peak actor.
    """
    anchor_hz = clamp(anchor_hz, 30.0, 900.0)
    return {
        "lane": lane_index + 1,
        "role": "measured foundation",
        "pole_hz": round(anchor_hz, 6),
        "pole_r": round(0.68 + 0.10 * clamp(q, 0.0, 1.0), 7),
        "zero_hz": 17950.0,
        "zero_r": round(0.58 + 0.12 * clamp(q, 0.0, 1.0), 7),
        "gain": 0.34,
        "source": {
            "kind": "measured_foundation",
            "aggregate_source": "dev/tmp/measured_foundations/summary.json",
            "anchor_hz": round(anchor_hz, 6),
        },
    }


def endpoint_to_lane(section: dict[str, Any], endpoint_name: str, q: float) -> dict[str, Any]:
    endpoint = normalize_endpoint(section[endpoint_name])
    peak_db = endpoint["peak_db"] + q * float(section.get("q_peak_db", 0.0))
    gain_db = endpoint["gain_db"] + q * float(section.get("q_gain_db", 0.0))
    pole_hz = endpoint["freq_hz"]
    pole_r = peak_to_radius(peak_db)
    zero_hz = shelf_to_zero_hz(pole_hz, endpoint["shelf"])
    zero_r = shelf_to_zero_radius(endpoint["shelf"], pole_r)
    return {
        "lane": int(section["lane"]),
        "role": str(section.get("label") or "peak_shelf"),
        "pole_hz": round(pole_hz, 6),
        "pole_r": round(clamp(pole_r, 0.18, 0.9992), 7),
        "zero_hz": round(zero_hz, 6),
        "zero_r": round(clamp(zero_r, 0.05, 0.999), 7),
        "gain": round(peak_to_gain(peak_db, gain_db), 7),
        "source": {
            "kind": "peak_shelf",
            "endpoint": endpoint_name,
            "freq_hz": endpoint["freq_hz"],
            "shelf": endpoint["shelf"],
            "peak_db": round(peak_db, 6),
            "gain_db": round(gain_db, 6),
        },
    }


def card_to_corners(card: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    corners = {label: [] for label in CORNER_ORDER}
    foundation = card.get("foundation", {})
    foundation_i = int(foundation.get("lane", 2)) - 1
    for i, section in enumerate(card["sections"]):
        if foundation.get("enabled") and i == foundation_i:
            anchor = float(foundation.get("anchor_hz", 530.0))
            corners["M0_Q0"].append(foundation_lane(i, anchor, 0.0))
            corners["M100_Q0"].append(foundation_lane(i, anchor, 0.0))
            corners["M0_Q100"].append(foundation_lane(i, anchor, 1.0))
            corners["M100_Q100"].append(foundation_lane(i, anchor, 1.0))
            continue
        if section.get("kind") != "peak_shelf":
            lane = identity_lane(i)
            for label in CORNER_ORDER:
                corners[label].append(dict(lane))
            continue
        corners["M0_Q0"].append(endpoint_to_lane(section, "home", 0.0))
        corners["M100_Q0"].append(endpoint_to_lane(section, "away", 0.0))
        corners["M0_Q100"].append(endpoint_to_lane(section, "home", 1.0))
        corners["M100_Q100"].append(endpoint_to_lane(section, "away", 1.0))
    return corners


def make_body(card: dict[str, Any], corners: dict[str, list[dict[str, Any]]]) -> tuple[bytes, dict[str, Any]]:
    packed_doc = body_to_packed_v1(card["name"], corners, boost=1.0, sr=AUTHORING_SR)
    words = {
        label: [tuple(int(v) for v in row) for row in packed_doc["corner"][label]["words"]]
        for label in CORNER_ORDER
    }
    body = author_body.raw_from_words(words)
    cartridge = author_body.compiled_payload(card["name"], 1.0, words)
    cartridge["provenance"] = "clean-room-filter-card-bake-v1"
    cartridge["filterCard"] = "card.json"
    cartridge["runtime_authority"] = "body.body240"
    return body, cartridge


def response_db(body: bytes, morph: float, q: float) -> np.ndarray:
    probe = trench_ffi.packed_probe(body, float(morph), float(q))
    w = 2.0 * np.pi * FREQS / AUTHORING_SR
    z1 = np.exp(-1j * w)
    z2 = np.exp(-2j * w)
    total = np.zeros_like(FREQS)
    for b0, b1, b2, a1, a2 in probe["biquad"]:
        num = b0 + b1 * z1 + b2 * z2
        den = 1.0 + a1 * z1 + a2 * z2
        total += 20.0 * np.log10(np.maximum(np.abs(num) / np.maximum(np.abs(den), 1e-12), 1e-12))
    return np.nan_to_num(total, nan=0.0, posinf=120.0, neginf=-120.0)


def audit_body(card: dict[str, Any], body: bytes, grid: int) -> tuple[dict[str, Any], list[list[float]]]:
    points = np.linspace(0.0, 1.0, max(3, int(grid)))
    max_radius = 0.0
    unstable_mask = 0
    nonfinite_mask = 0
    heat = np.zeros((len(points), len(points)))
    samples: list[dict[str, Any]] = []
    for qi, q in enumerate(points):
        for mi, morph in enumerate(points):
            probe = trench_ffi.packed_probe(body, float(morph), float(q))
            db = response_db(body, float(morph), float(q))
            span = float(np.nanmax(db) - np.nanmin(db))
            heat[qi, mi] = span
            max_radius = max(max_radius, float(probe.get("max_pole_radius", 0.0)))
            unstable_mask |= int(probe.get("unstable_mask", 0))
            nonfinite_mask |= int(probe.get("nonfinite_mask", 0))
            if mi in (0, len(points) - 1) and qi in (0, len(points) - 1):
                samples.append(
                    {
                        "morph": round(float(morph), 6),
                        "q": round(float(q), 6),
                        "max_pole_radius": probe.get("max_pole_radius"),
                        "unstable_mask": probe.get("unstable_mask"),
                        "nonfinite_mask": probe.get("nonfinite_mask"),
                        "response_min_db": round(float(np.nanmin(db)), 3),
                        "response_max_db": round(float(np.nanmax(db)), 3),
                    }
                )

    warnings: list[str] = []
    if len(body) != 240:
        warnings.append(f"body length is {len(body)} bytes, expected 240")
    if unstable_mask:
        warnings.append(f"unstable_mask={unstable_mask}")
    if nonfinite_mask:
        warnings.append(f"nonfinite_mask={nonfinite_mask}")
    if max_radius >= 1.0:
        warnings.append(f"max pole radius reached {max_radius:.6f}")

    # Authoring-specific sanity for the default contrary actor.
    peak_sections = [s for s in card["sections"] if s.get("kind") == "peak_shelf"]
    for section in peak_sections:
        home = endpoint_to_lane(section, "home", 0.0)
        away = endpoint_to_lane(section, "away", 0.0)
        if not (home["zero_hz"] > home["pole_hz"] and away["zero_hz"] < away["pole_hz"]):
            warnings.append(f"lane {section['lane']} does not move zero contrary to pole")

    audit = {
        "format": "filter-card-audit-v1",
        "card": card["name"],
        "body240_bytes": len(body),
        "grid_n": len(points),
        "checks": {
            "stable": unstable_mask == 0 and max_radius < 1.0,
            "finite_response": nonfinite_mask == 0,
            "max_pole_radius": round(float(max_radius), 7),
            "unstable_mask": unstable_mask,
            "nonfinite_mask": nonfinite_mask,
        },
        "response_span_db": {
            "min": round(float(np.min(heat)), 3),
            "mean": round(float(np.mean(heat)), 3),
            "max": round(float(np.max(heat)), 3),
        },
        "corner_samples": samples,
        "warnings": warnings,
        "verdict": "PASS" if not warnings else "WARN",
    }
    return audit, heat.tolist()


def build_product(raw_card: dict[str, Any] | None = None, grid: int = 17) -> BakeProduct:
    if not trench_ffi.available():
        raise RuntimeError("trench_core packed probe unavailable; build with cargo build --release -p trench-core")
    card = normalize_card(raw_card or default_card())
    corners = card_to_corners(card)
    body, cartridge = make_body(card, corners)
    audit, heatmap = audit_body(card, body, grid)
    cartridge["filterCardAudit"] = {
        "verdict": audit["verdict"],
        "checks": audit["checks"],
        "warnings": audit["warnings"],
    }
    return BakeProduct(card=card, corners=corners, body=body, cartridge=cartridge, audit=audit, heatmap=heatmap)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def plot_response(product: BakeProduct, out: Path) -> None:
    fig = plt.figure(figsize=(12.5, 8.2), facecolor="#f2f0ea")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 0.82], hspace=0.34, wspace=0.24)
    ax0 = fig.add_subplot(gs[0, :])
    ax1 = fig.add_subplot(gs[1, 0])
    ax2 = fig.add_subplot(gs[1, 1])
    for ax in (ax0, ax1):
        ax.set_xscale("log")
        ax.set_xlim(30.0, 18000.0)
        ax.set_ylim(-60.0, 36.0)
        ax.grid(True, which="both", alpha=0.22)
        ax.axhline(0.0, color="#a83b33", lw=0.8, alpha=0.6)

    colors = {
        "M0_Q0": "#355c9a",
        "M100_Q0": "#b26b1f",
        "M0_Q100": "#2f8b58",
        "M100_Q100": "#913f72",
    }
    for label, m, q in (("M0_Q0", 0, 0), ("M100_Q0", 1, 0), ("M0_Q100", 0, 1), ("M100_Q100", 1, 1)):
        ax0.plot(FREQS, response_db(product.body, m, q), lw=1.8, color=colors[label], label=label)
    ax0.set_title("packed-runtime corner response", loc="left", fontsize=11)
    ax0.legend(fontsize=8)

    for morph in np.linspace(0.0, 1.0, 13):
        ax1.plot(FREQS, response_db(product.body, float(morph), 1.0), lw=1.1, alpha=0.82)
    ax1.set_title("Q100 morph sweep", loc="left", fontsize=10)
    ax1.set_xlabel("Hz")

    heat = np.array(product.heatmap, dtype=float)
    im = ax2.imshow(heat, origin="lower", extent=[0, 100, 0, 100], aspect="auto", cmap="magma")
    ax2.set_title("Morph/Q response span", loc="left", fontsize=10)
    ax2.set_xlabel("Morph")
    ax2.set_ylabel("Q")
    fig.colorbar(im, ax=ax2, fraction=0.046, pad=0.04, label="dB")

    checks = product.audit["checks"]
    fig.suptitle(
        f"{product.card['name']} | {len(product.body)} bytes | {product.audit['verdict']} | "
        f"stable={checks['stable']} finite={checks['finite_response']} maxR={checks['max_pole_radius']:.6f}",
        x=0.02,
        ha="left",
        fontsize=12,
    )
    fig.savefig(out, dpi=130, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def write_workbench(product: BakeProduct, out: Path) -> None:
    rows: list[str] = []
    for label in CORNER_ORDER:
        for lane in product.corners[label]:
            rows.append(
                "<tr>"
                f"<td>{html.escape(label)}</td>"
                f"<td>{lane['lane']}</td>"
                f"<td>{html.escape(str(lane['role']))}</td>"
                f"<td>{hz_fmt(float(lane['pole_hz']))}</td>"
                f"<td>{float(lane['pole_r']):.5f}</td>"
                f"<td>{hz_fmt(float(lane['zero_hz']))}</td>"
                f"<td>{float(lane['zero_r']):.5f}</td>"
                f"<td>{float(lane['gain']):.4f}</td>"
                "</tr>"
            )
    warnings = "; ".join(product.audit["warnings"]) if product.audit["warnings"] else "none"
    checks = product.audit["checks"]
    text = f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(product.card['name'])} filter-card bake</title>
<style>
body{{margin:24px;background:#f2f0ea;color:#161616;font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif}}
h1{{font-size:22px;margin:0 0 8px}} h2{{font-size:15px;margin:22px 0 8px}}
.meta{{max-width:980px;background:#fffaf5;border:1px solid #d6cbbb;padding:12px;font-family:Consolas,monospace}}
img{{max-width:100%;display:block;border:1px solid #d6cbbb;background:white}}
table{{border-collapse:collapse;width:100%;max-width:1180px;background:#fffaf5}}
th,td{{border:1px solid #d6cbbb;padding:6px 8px;text-align:left;font:12px Consolas,monospace}}
th{{background:#e5dccd}} a{{color:#8b4a00}}
</style>
<h1>Filter Card Bake</h1>
<div class="meta">
card: {html.escape(product.card['name'])}<br>
body: {len(product.body)} bytes<br>
verdict: {html.escape(product.audit['verdict'])}<br>
stable: {checks['stable']} / finite: {checks['finite_response']} / max pole r: {checks['max_pole_radius']:.7f}<br>
warnings: {html.escape(warnings)}<br>
runtime truth: response and audit are from packed <a href="body.body240">body.body240</a> via trench_core.
</div>
<h2>Response</h2>
<img src="response.png" alt="packed-runtime response">
<h2>Artifacts</h2>
<div class="meta">
<a href="card.json">card.json</a><br>
<a href="root_lanes.json">root_lanes.json</a><br>
<a href="law_source.json">law_source.json</a><br>
<a href="body.body240">body.body240</a><br>
<a href="cartridge.json">cartridge.json</a><br>
<a href="audit.json">audit.json</a>
</div>
<h2>Root Lanes</h2>
<table>
<thead><tr><th>corner</th><th>lane</th><th>role</th><th>pole Hz</th><th>pole r</th><th>zero Hz</th><th>zero r</th><th>gain</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""
    out.write_text(text, encoding="utf-8")


def write_session(product: BakeProduct, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "card.json", product.card)
    root_lanes = {
        "format": "root-domain-lanes-v1",
        "name": product.card["name"],
        "corner_order": list(CORNER_ORDER),
        "corners": product.corners,
    }
    write_json(out_dir / "root_lanes.json", root_lanes)
    write_json(out_dir / "law_source.json", root_lanes)
    (out_dir / "body.body240").write_bytes(product.body)
    write_json(out_dir / "cartridge.json", product.cartridge)
    write_json(out_dir / "audit.json", product.audit)
    plot_response(product, out_dir / "response.png")
    write_workbench(product, out_dir / "workbench.html")


def load_card(path: Path | None) -> dict[str, Any]:
    if path is None:
        return default_card()
    return json.loads(path.read_text(encoding="utf-8"))


def default_session_name(card_name: str) -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{safe_name(card_name)}"


def bake_to_dir(raw_card: dict[str, Any] | None, out_dir: Path, grid: int = 17) -> BakeProduct:
    product = build_product(raw_card, grid=grid)
    write_session(product, out_dir)
    return product


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--card", type=Path, help="filter-card-v1 JSON. Defaults to the clean contrary Peak/Shelf card.")
    ap.add_argument("--session", help="session folder name under dev/tmp/filter_cards")
    ap.add_argument("--out", type=Path, help="explicit output directory")
    ap.add_argument("--grid", type=int, default=17, help="Morph/Q audit grid")
    args = ap.parse_args(argv)

    try:
        raw_card = load_card(args.card)
        card = normalize_card(raw_card)
        out_dir = args.out or (ROOT / "dev" / "tmp" / "filter_cards" / (args.session or default_session_name(card["name"])))
        product = bake_to_dir(card, out_dir, grid=args.grid)
    except Exception as exc:
        print(f"filter_cards.bake error: {exc}", file=sys.stderr)
        return 1

    print(f"session  -> {out_dir}")
    print(f"card     -> {out_dir / 'card.json'}")
    print(f"lanes    -> {out_dir / 'root_lanes.json'}")
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
    ok = product.audit["checks"]["stable"] and product.audit["checks"]["finite_response"]
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
