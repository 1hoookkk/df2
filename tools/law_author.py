#!/usr/bin/env python3
"""Compile a compact law into a legal six-lane .body240 body.

This is Forge/manual-authoring support, not production training. The input law
can be either the original small scalar object:

  anchor_hz, anchor_gain_db, tilt_db, canyon_depth, q_crank, morph_spread, density

or a section-law-v1 object with six measured sections:

  fc_hz, gain_db, bw_oct, zero_offset_oct, morph_oct, zero_morph_oct, q_weight

The output is four corners of six lane dicts, packed through tools.author_lanes
and tools.author_body, then audited with the shipped trench_core packed probe.
"""
from __future__ import annotations

import argparse
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

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from tools import author_body  # noqa: E402
from tools.author_lanes import AUTHORING_SR, body_to_packed_v1  # noqa: E402

CORNER_ORDER = ("M0_S0", "M1_S0", "M0_S1", "M1_S1")
PACKED_CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
STAGES = 6
FREQS = np.geomspace(30.0, AUTHORING_SR * 0.49, 420)
W = 2.0 * np.pi * FREQS / AUTHORING_SR
Z1 = np.exp(-1j * W)
Z2 = np.exp(-2j * W)
RIM_RADIUS = 0.9999


@dataclass(frozen=True)
class Law:
    name: str
    anchor_hz: float
    anchor_gain_db: float
    tilt_db: float
    canyon_depth: float
    q_crank: float
    morph_spread: float
    density: float
    format: str = "scalar-law-v1"
    family: str = "hedz_like"
    sections: tuple[dict[str, Any], ...] = ()
    source_contract: str | None = None


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def lmul(freq_hz: float, semitones: float) -> float:
    return clamp(freq_hz * (2.0 ** (semitones / 12.0)), 24.0, AUTHORING_SR * 0.48)


def gain_db(db: float) -> float:
    return 10.0 ** (float(db) / 20.0)


def q_radius(freq_hz: float, q: float) -> float:
    q = max(0.35, float(q))
    bw = max(8.0, float(freq_hz) / q)
    return clamp(math.exp(-math.pi * bw / AUTHORING_SR), 0.18, RIM_RADIUS)


def bw_oct_radius(freq_hz: float, bw_oct: float) -> float:
    half = clamp(float(bw_oct), 0.12, 5.0) * 0.5
    lo = float(freq_hz) / (2.0 ** half)
    hi = float(freq_hz) * (2.0 ** half)
    bw_hz = max(8.0, hi - lo)
    return clamp(math.exp(-math.pi * bw_hz / AUTHORING_SR), 0.18, 0.9988)


def zero_radius(canyon_depth: float, scale: float) -> float:
    depth = clamp(canyon_depth, 0.0, 36.0) / 36.0
    return clamp(0.42 + depth * scale, 0.25, 0.9985)


def unity_dc_gain(pole_hz: float, pole_r: float, zero_hz: float, zero_r: float) -> float:
    """b0 that makes one pole/zero section unity at z=1."""
    wp = 2.0 * math.pi * clamp(pole_hz, 24.0, AUTHORING_SR * 0.48) / AUTHORING_SR
    wz = 2.0 * math.pi * clamp(zero_hz, 24.0, AUTHORING_SR * 0.48) / AUTHORING_SR
    a1 = -2.0 * pole_r * math.cos(wp)
    a2 = pole_r * pole_r
    n1 = -2.0 * zero_r * math.cos(wz)
    n2 = zero_r * zero_r
    den_dc = 1.0 + a1 + a2
    num_dc = 1.0 + n1 + n2
    if abs(num_dc) < 1e-9:
        return 1.0
    return clamp(den_dc / num_dc, 0.025, 3.75)


def lane(
    pole_hz: float,
    pole_q: float | None,
    zero_hz: float,
    zero_r: float,
    gain: float,
    role: str,
    pole_r: float | None = None,
) -> dict[str, Any]:
    realized_pole_r = q_radius(pole_hz, pole_q) if pole_r is None else clamp(pole_r, 0.18, RIM_RADIUS)
    return {
        "pole_hz": round(clamp(pole_hz, 24.0, AUTHORING_SR * 0.48), 4),
        "pole_r": round(realized_pole_r, 7),
        "zero_hz": round(clamp(zero_hz, 24.0, AUTHORING_SR * 0.48), 4),
        "zero_r": round(clamp(zero_r, 0.05, 0.9985), 7),
        "gain": round(clamp(gain, 0.025, 3.75), 7),
        "role": role,
    }


def load_law(path: Path) -> Law:
    data = json.loads(path.read_text(encoding="utf-8"))
    name = str(data.get("name") or path.stem)
    sections = tuple(data.get("sections") or ())
    return Law(
        name=name,
        anchor_hz=float(data.get("anchor_hz", 190.0)),
        anchor_gain_db=float(data.get("anchor_gain_db", 6.5)),
        tilt_db=float(data.get("tilt_db", 16.0)),
        canyon_depth=float(data.get("canyon_depth", 18.0)),
        q_crank=clamp(float(data.get("q_crank", 0.8)), 0.0, 1.0),
        morph_spread=clamp(float(data.get("morph_spread", 0.7)), 0.0, 1.0),
        density=clamp(float(data.get("density", 0.75)), 0.0, 1.0),
        format=str(data.get("format", "scalar-law-v1")),
        family=str(data.get("family", "hedz_like")),
        sections=sections,
        source_contract=data.get("source_contract"),
    )


def compile_law(law: Law) -> dict[str, list[dict[str, Any]]]:
    if law.format == "section-law-v1" or law.sections:
        return compile_section_law(law)
    return compile_scalar_law(law)


def compile_section_law(law: Law) -> dict[str, list[dict[str, Any]]]:
    """Compile measured Fc/gain/BW sections into root-domain lanes.

    Sections are unity-DC by construction: each lane gets a b0 that makes H(1)=1.
    Positive gain sections become pole-dominant ridges; negative sections become
    zero-dominant canyons/cuts. Secondary/Q locks frequency and cranks radius.
    """
    sections = list(law.sections)
    if len(sections) != STAGES:
        raise ValueError(f"section-law-v1 requires exactly {STAGES} sections, got {len(sections)}")
    corners: dict[str, list[dict[str, Any]]] = {}
    depth = clamp(law.canyon_depth, 0.0, 36.0) / 36.0
    for label in CORNER_ORDER:
        morph = 1.0 if label.startswith("M1") else 0.0
        secondary = 1.0 if label.endswith("S1") else 0.0
        rows = []
        for i, section in enumerate(sections):
            role = str(section.get("role", f"section_{i + 1}"))
            fc = clamp(float(section["fc_hz"]), 24.0, AUTHORING_SR * 0.48)
            gain = float(section.get("gain_db", 0.0))
            bw_oct = float(section.get("bw_oct", 1.0))
            q_weight = clamp(float(section.get("q_weight", 1.0)), 0.0, 1.0)
            morph_oct = float(section.get("morph_oct", 0.0)) * law.morph_spread
            zero_offset_oct = float(section.get("zero_offset_oct", 0.0))
            zero_morph_oct = float(section.get("zero_morph_oct", 0.0)) * law.morph_spread
            zero_secondary_oct = float(section.get("zero_secondary_oct", 0.0))

            pole_hz = clamp(fc * (2.0 ** (morph_oct * morph)), 24.0, AUTHORING_SR * 0.48)
            zero_hz = clamp(
                fc * (2.0 ** (zero_offset_oct + zero_morph_oct * morph + zero_secondary_oct * secondary)),
                24.0,
                AUTHORING_SR * 0.48,
            )

            base_r = bw_oct_radius(fc, bw_oct)
            q_pressure = law.q_crank * q_weight * secondary
            if gain >= 0.0:
                pole_r = base_r + (RIM_RADIUS - base_r) * q_pressure
                zero_r = clamp(0.38 + depth * 0.22 + 0.06 * q_pressure, 0.18, 0.94)
            else:
                pole_r = clamp(0.44 + 0.25 * (1.0 - depth) + 0.10 * q_pressure, 0.18, 0.94)
                zero_r = clamp(0.74 + depth * 0.24 + 0.02 * q_pressure, 0.35, 0.9985)
            if role == "anchor" and secondary > 0.0:
                pole_r = RIM_RADIUS

            rows.append(
                lane(
                    pole_hz=pole_hz,
                    pole_q=None,
                    zero_hz=zero_hz,
                    zero_r=zero_r,
                    gain=unity_dc_gain(pole_hz, pole_r, zero_hz, zero_r),
                    role=role,
                    pole_r=pole_r,
                )
            )
        corners[label] = rows
    return corners


def compile_scalar_law(law: Law) -> dict[str, list[dict[str, Any]]]:
    """Return four corners of six persistent lane contracts."""
    a = clamp(law.anchor_hz, 45.0, 3600.0)
    q = law.q_crank
    spread = law.morph_spread
    density = law.density
    depth = law.canyon_depth
    base_gain = gain_db(law.anchor_gain_db) * 0.36
    tilt = clamp(law.tilt_db, -24.0, 24.0)

    corners: dict[str, list[dict[str, Any]]] = {}
    for label in CORNER_ORDER:
        morph = 1.0 if label.startswith("M1") else 0.0
        secondary = 1.0 if label.endswith("S1") else 0.0
        contrast = (morph - 0.5) * 2.0
        pressure = secondary
        brighten = 2.0 ** (contrast * spread * 0.62)
        tighten = 1.0 + q * (1.35 + 0.8 * pressure)
        density_lift = 0.65 + 0.75 * density
        tilt_gain = gain_db((tilt / 18.0) * contrast)
        pressure_gain = gain_db(1.5 * pressure)

        rows = [
            lane(
                pole_hz=lmul(a, -0.8 + 1.6 * morph),
                pole_q=None,
                zero_hz=lmul(a, -8.0 - 1.8 * pressure),
                zero_r=zero_radius(depth, 0.28),
                gain=base_gain * pressure_gain,
                role="anchor",
                pole_r=RIM_RADIUS if pressure > 0.0 else 0.9988,
            ),
            lane(
                pole_hz=lmul(a, -18.0 + 4.0 * morph - 2.0 * pressure),
                pole_q=None,
                zero_hz=lmul(a, -29.0 + 1.5 * morph),
                zero_r=zero_radius(depth, 0.18),
                gain=0.42 * density_lift * gain_db(-0.35 * tilt),
                role="low_mass",
                pole_r=0.42 + 0.10 * density + 0.03 * pressure,
            ),
            lane(
                pole_hz=lmul(a * brighten, 7.0 + 4.0 * pressure),
                pole_q=4.0 * tighten,
                zero_hz=lmul(a * brighten, -2.5 - 3.5 * pressure),
                zero_r=zero_radius(depth, 0.42),
                gain=0.33 * density_lift * tilt_gain,
                role="mouth_ladder",
            ),
            lane(
                pole_hz=lmul(a * brighten, 14.0 + 5.0 * morph + 2.0 * pressure),
                pole_q=5.5 * tighten,
                zero_hz=lmul(a * brighten, 10.0 - 2.0 * morph + 3.0 * pressure),
                zero_r=zero_radius(depth, 0.55),
                gain=0.26 * density_lift * gain_db(0.45 * tilt),
                role="bite_canyon",
            ),
            lane(
                pole_hz=lmul(a, 24.0 - 10.0 * morph + 6.0 * pressure),
                pole_q=3.2 + 9.0 * q,
                zero_hz=lmul(a, 20.0 + 11.0 * morph - 3.0 * pressure),
                zero_r=zero_radius(depth, 0.62),
                gain=0.19 * density_lift * gain_db(0.30 * tilt) * (1.0 + 0.18 * pressure),
                role="tear_crosser",
            ),
            lane(
                pole_hz=lmul(a, 34.0 + 7.0 * morph + 4.0 * pressure),
                pole_q=2.8 + 4.5 * q,
                zero_hz=lmul(a, 43.0 + 5.0 * morph),
                zero_r=zero_radius(depth, 0.50),
                gain=0.13 * density_lift * gain_db(0.55 * tilt),
                role="air_cap",
            ),
        ]
        corners[label] = rows
    return corners


def body_bytes_from_cart(cart: dict[str, Any]) -> bytes:
    by_label = {kf["label"]: kf for kf in cart["keyframes"]}
    raw = bytearray()
    for label in PACKED_CORNER_ORDER:
        for row in by_label[label]["packedWords"]:
            for word in row:
                raw += (int(word) & 0xFFFF).to_bytes(2, "little")
    return bytes(raw)


def cascade_db(biquads: list[tuple[float, ...]]) -> np.ndarray:
    total = np.zeros_like(FREQS)
    for b0, b1, b2, a1, a2 in biquads:
        num = b0 + b1 * Z1 + b2 * Z2
        den = 1.0 + a1 * Z1 + a2 * Z2
        total += 20.0 * np.log10(np.maximum(np.abs(num) / np.maximum(np.abs(den), 1e-12), 1e-12))
    return total


def stage_db(biquad: tuple[float, ...]) -> np.ndarray:
    return cascade_db([biquad])


def response_metric(body: bytes, morph: float, q: float) -> tuple[np.ndarray, dict[str, Any]]:
    probe = trench_ffi.packed_probe(body, morph, q)
    return cascade_db(probe["biquad"]), probe


def audit_body(law: Law, corners: dict[str, list[dict[str, Any]]], body: bytes, grid_n: int) -> dict[str, Any]:
    points = np.linspace(0.0, 1.0, grid_n)
    warnings: list[str] = []
    cells: list[dict[str, Any]] = []
    max_radius = 0.0
    unstable = False
    nonfinite = False
    heat = np.zeros((grid_n, grid_n))

    for qi, q in enumerate(points):
        for mi, morph in enumerate(points):
            db, probe = response_metric(body, float(morph), float(q))
            heat[qi, mi] = float(np.nanmax(db) - np.nanmin(db))
            max_radius = max(max_radius, float(probe["max_pole_radius"]))
            cell_unstable = int(probe["unstable_mask"]) != 0
            cell_nonfinite = int(probe["nonfinite_mask"]) != 0 or not bool(np.all(np.isfinite(db)))
            unstable = unstable or cell_unstable
            nonfinite = nonfinite or cell_nonfinite
            cells.append(
                {
                    "morph": round(float(morph), 4),
                    "secondary": round(float(q), 4),
                    "max_pole_radius": float(probe["max_pole_radius"]),
                    "unstable_mask": int(probe["unstable_mask"]),
                    "nonfinite_mask": int(probe["nonfinite_mask"]),
                    "response_span_db": float(heat[qi, mi]),
                }
            )

    anchor_ok = all(
        any(row["role"] == "anchor" and abs(math.log2(row["pole_hz"] / law.anchor_hz)) < 0.42 for row in rows)
        for rows in corners.values()
    )
    if not anchor_ok:
        warnings.append("anchor missing or moved too far from anchor_hz")

    corner_tilts = []
    for morph, q in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
        db, _ = response_metric(body, morph, q)
        lo = float(db[int(np.argmin(np.abs(FREQS - 220.0)))])
        hi = float(db[int(np.argmin(np.abs(FREQS - 7200.0)))])
        corner_tilts.append(hi - lo)
    tilt_span = max(corner_tilts) - min(corner_tilts)
    # Strong descending terrain is legal and common in the family reports. The
    # failure is the opposite: high band dominating the low/body band, or an
    # absurd packed readout. Keep the gate directional instead of timid.
    tilt_ok = (
        np.all(np.isfinite(corner_tilts))
        and tilt_span <= 120.0
        and min(corner_tilts) >= -140.0
        and max(corner_tilts) <= 32.0
    )
    if not tilt_ok:
        warnings.append("tilt out of sane range")

    canyon_lanes = [
        row for rows in corners.values() for row in rows
        if "canyon" in row["role"] or row["zero_r"] >= 0.72
    ]
    canyon_ok = bool(canyon_lanes) and max(row["zero_r"] for row in canyon_lanes) >= zero_radius(law.canyon_depth, 0.42)
    if not canyon_ok:
        warnings.append("canyon depth not present in lane zeros")

    if unstable:
        warnings.append("packed probe found unstable stage(s)")
    if nonfinite:
        warnings.append("packed probe found nonfinite response/stage(s)")
    if max_radius >= 1.0:
        warnings.append(f"max pole radius reached instability: {max_radius:.6f}")

    return {
        "law": asdict(law),
        "grid_n": grid_n,
        "checks": {
            "stable": not unstable,
            "finite_response": not nonfinite,
            "max_pole_radius": max_radius,
            "anchor_present": anchor_ok,
            "tilt_sane": bool(tilt_ok),
            "tilt_span_db": float(tilt_span),
            "corner_tilt_db": [float(v) for v in corner_tilts],
            "canyon_depth_present": canyon_ok,
        },
        "warnings": warnings,
        "grid": cells,
        "heatmap_response_span_db": heat.tolist(),
        "verdict": "PASS" if not warnings else "WARN",
    }


def plot_sheet(
    law: Law,
    corners: dict[str, list[dict[str, Any]]],
    body: bytes,
    audit: dict[str, Any],
    out: Path,
) -> None:
    fig = plt.figure(figsize=(16.0, 11.0), facecolor="#f3efe6")
    gs = fig.add_gridspec(4, 6, height_ratios=[1.15, 1.0, 1.0, 1.15], hspace=0.55, wspace=0.36)

    ax0 = fig.add_subplot(gs[0, :3])
    colors = {
        "M0_S0": "#1263a6",
        "M1_S0": "#c06d11",
        "M0_S1": "#3b7d3b",
        "M1_S1": "#8a3fa0",
    }
    for label, (morph, q) in {
        "M0_S0": (0.0, 0.0),
        "M1_S0": (1.0, 0.0),
        "M0_S1": (0.0, 1.0),
        "M1_S1": (1.0, 1.0),
    }.items():
        db, _ = response_metric(body, morph, q)
        ax0.semilogx(FREQS, np.clip(db, -72.0, 72.0), lw=1.6, color=colors[label], label=label)
    ax0.set_title("four-corner packed response")
    ax0.set_xlim(30.0, AUTHORING_SR * 0.49)
    ax0.set_ylim(-72.0, 72.0)
    ax0.grid(True, which="both", alpha=0.22)
    ax0.legend(fontsize=8)

    ax1 = fig.add_subplot(gs[0, 3:])
    heat = np.array(audit["heatmap_response_span_db"], dtype=float)
    im = ax1.imshow(heat, origin="lower", cmap="inferno", extent=[0, 100, 0, 100], aspect="auto")
    ax1.set_title("Morph/Q packed-probe response span")
    ax1.set_xlabel("Morph")
    ax1.set_ylabel("Secondary")
    fig.colorbar(im, ax=ax1, fraction=0.046, pad=0.04, label="dB span")

    midpoint_probe = trench_ffi.packed_probe(body, 0.5, 0.5)
    for i in range(STAGES):
        ax = fig.add_subplot(gs[1 + i // 3, (i % 3) * 2:(i % 3) * 2 + 2])
        row = corners["M0_S0"][i]
        ax.semilogx(FREQS, np.clip(stage_db(midpoint_probe["biquad"][i]), -54.0, 48.0), color="#222222", lw=1.2)
        ax.axvline(row["pole_hz"], color="#1263a6", lw=0.8, alpha=0.8)
        ax.axvline(row["zero_hz"], color="#b22d2d", lw=0.8, alpha=0.8)
        ax.set_title(f"{i + 1}. {row['role']}", fontsize=9)
        ax.set_xlim(30.0, AUTHORING_SR * 0.49)
        ax.set_ylim(-54.0, 48.0)
        ax.grid(True, which="both", alpha=0.16)
        ax.tick_params(labelsize=7)

    ax_notes = fig.add_subplot(gs[3, :])
    ax_notes.axis("off")
    checks = audit["checks"]
    warnings = audit["warnings"] or ["none"]
    table_lines = [
        f"law: {law.name} | anchor {law.anchor_hz:.1f} Hz | tilt {law.tilt_db:.1f} dB | canyon {law.canyon_depth:.1f} | q {law.q_crank:.2f} | morph spread {law.morph_spread:.2f} | density {law.density:.2f}",
        f"audit: {audit['verdict']} | stable={checks['stable']} finite={checks['finite_response']} max pole r={checks['max_pole_radius']:.6f} anchor={checks['anchor_present']} tilt sane={checks['tilt_sane']} canyon={checks['canyon_depth_present']}",
        "warnings: " + "; ".join(warnings),
        "stage table is emitted as stages.json and repeated below for M0_S0.",
    ]
    y = 0.95
    for line in table_lines:
        ax_notes.text(0.01, y, line, fontsize=10, family="monospace", va="top", color="#17140f")
        y -= 0.14
    for i, row in enumerate(corners["M0_S0"]):
        ax_notes.text(
            0.01,
            y,
            f"{i + 1:02d} {row['role']:<14} pole {row['pole_hz']:>8.1f} zero {row['zero_hz']:>8.1f} pole_r {row['pole_r']:.6f} zero_r {row['zero_r']:.6f} gain {row['gain']:.4f}",
            fontsize=9,
            family="monospace",
            va="top",
            color="#17140f",
        )
        y -= 0.095

    fig.suptitle(f"Law Author - {law.name}", fontsize=15, color="#17140f", x=0.015, ha="left")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)


def write_outputs(law_path: Path, out_dir: Path, grid_n: int) -> dict[str, Any]:
    law = load_law(law_path)
    corners = compile_law(law)
    body_doc = body_to_packed_v1(law.name, corners, boost=1.0, sr=AUTHORING_SR)

    run_dir = out_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    packed_source = run_dir / "packed-body-v1.json"
    cart_path = run_dir / f"{law.name}.cartridge.json"
    body_path = run_dir / f"{law.name}.body240"
    law_source_path = run_dir / "law_source.json"
    stage_path = run_dir / "stages.json"
    audit_path = run_dir / "audit.json"
    plot_path = run_dir / "plot_sheet.png"

    packed_source.write_text(json.dumps(body_doc, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(law_path, law_source_path)
    stage_path.write_text(json.dumps(corners, indent=2) + "\n", encoding="utf-8")

    name, boost, words = author_body.load_packed_words(packed_source)
    cart = author_body.compiled_payload(name, boost, words)
    cart["provenance"] = "law-author-v1"
    cart["lawSource"] = "law_source.json"
    cart["authoringModel"] = "response-surface-v1"
    cart_path.write_text(json.dumps(cart, indent=2) + "\n", encoding="utf-8")
    body = author_body.raw_from_words(words)
    body_path.write_bytes(body)

    audit = audit_body(law, corners, body, grid_n)
    cart["lawAudit"] = {
        "verdict": audit["verdict"],
        "checks": audit["checks"],
        "warnings": audit["warnings"],
    }
    cart_path.write_text(json.dumps(cart, indent=2) + "\n", encoding="utf-8")
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    plot_sheet(law, corners, body, audit, plot_path)

    return {
        "law": law,
        "corners": corners,
        "audit": audit,
        "paths": {
            "run_dir": run_dir,
            "body240": body_path,
            "compiled_v1": cart_path,
            "law_source": law_source_path,
            "stages": stage_path,
            "packed_body_v1": packed_source,
            "audit": audit_path,
            "plot_sheet": plot_path,
        },
    }


def default_law_path(name: str) -> Path:
    return ROOT / "recipes" / "laws" / f"{name}.json"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--law", type=Path, help="law JSON path")
    src.add_argument("--preset", default="hedz_like_anchor_canyons", help="law preset under recipes/laws")
    out = ap.add_mutually_exclusive_group()
    out.add_argument("--out", type=Path, help="exact output directory for this compile")
    out.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="parent output directory; compile is written under <out-dir>/<law-name>",
    )
    ap.add_argument("--grid", type=int, default=17, help="Morph/Q audit grid size")
    args = ap.parse_args(argv)

    law_path = args.law or default_law_path(str(args.preset))
    if not law_path.exists():
        print(f"law_author error: missing law JSON: {law_path}", file=sys.stderr)
        return 1
    if not trench_ffi.available():
        print(
            "law_author error: trench_core packed probe is unavailable; build with "
            "cargo build --release -p trench-core",
            file=sys.stderr,
        )
        return 1

    try:
        law_name = load_law(law_path).name
        if args.out is not None:
            out_dir = args.out
        else:
            parent = args.out_dir or (ROOT / "dev" / "tmp" / "law_author")
            out_dir = parent / law_name
        result = write_outputs(law_path, out_dir, max(3, int(args.grid)))
    except Exception as exc:
        print(f"law_author error: {exc}", file=sys.stderr)
        return 1

    paths = result["paths"]
    audit = result["audit"]
    print(f"law      -> {law_path}")
    print(f"body240  -> {paths['body240']} ({paths['body240'].stat().st_size} bytes)")
    print(f"compiled -> {paths['compiled_v1']}")
    print(f"source   -> {paths['law_source']}")
    print(f"stages   -> {paths['stages']}")
    print(f"audit    -> {paths['audit']} ({audit['verdict']})")
    print(f"plot     -> {paths['plot_sheet']}")
    if audit["warnings"]:
        for warning in audit["warnings"]:
            print(f"WARNING {warning}")
    else:
        print("VERDICT PASS")
    return 0 if audit["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
