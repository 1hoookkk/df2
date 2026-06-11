#!/usr/bin/env python3
"""Generate a family-aware X3/P2K reference browser.

Study-only clean-room report. X3 fixed classes are treated as grammar labels and
decoded response silhouettes. P2K bodies are treated as behavior evidence inside
each family. The output is HTML + aggregate bounds/contracts; it never emits
source words, coefficient tables, or shippable reference bodies.
"""
from __future__ import annotations

import html
import json
import math
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

from pyruntime import trench_ffi  # noqa: E402
from tools import reference_x3_menu_to_p2k as refmap  # noqa: E402
from tools import x3_fixed_class_cleanroom as x3  # noqa: E402


OUT = ROOT / "dev" / "tmp" / "x3_p2k_family_browser"
FREQS = refmap.COMMON_FREQS
COMPARE_MASK = refmap.COMPARE_MASK
ROOT_FREQ_MIN = 20.0
ROOT_FREQ_MAX = 22_000.0

FAMILIES: dict[str, dict[str, Any]] = {
    "slope_ladder": {
        "title": "Slope / Ladder",
        "x3": ["2 Pole Lowpass", "4 Pole Lowpass", "6 Pole Lowpass", "2 Pole Highpass", "4 Pole Highpass"],
        "p2k_contains": ["bass", "303", "tracer", "boland", "ace", "klub", "razor", "hertz"],
        "intent": "floor, cap, cliff, and tilt primitives",
        "contract_bias": "poles define slope body; zeros prevent dead shelves; Q mainly steepens radius/pressure",
    },
    "bandpass_swept_eq": {
        "title": "Bandpass / Swept EQ",
        "x3": [
            "2 Pole Bandpass", "4 Pole Bandpass", "Contrary Bandpass",
            "Swept EQ 1 Octave", "Swept EQ 2/1 Octave", "Swept EQ 3/1 Octave",
        ],
        "p2k_contains": ["dead", "vox", "peaks", "ear", "alkaline", "razor", "megasweepz", "millennium", "ravage"],
        "intent": "moving peak/canyon actors and contrary band windows",
        "contract_bias": "morph owns actor motion; Q tightens and exposes notches",
    },
    "phaser_comb": {
        "title": "Phaser / Comb",
        "x3": ["Phaser 1", "Phaser 2", "Bat Phaser", "Flanger Lite"],
        "p2k_contains": ["shifta", "vox", "dead", "gizmo", "ear", "comb", "kling", "fuzzi", "ringer"],
        "intent": "comb/canyon field over a body foundation",
        "contract_bias": "zeros and canyons are first-class; poles keep pressure and spacing coherent",
    },
    "vocal_formant": {
        "title": "Vocal / Formant",
        "x3": ["Vocal Ah-Ay-Ee", "Vocal Oo-Ah"],
        "p2k_contains": ["ooh", "eeh", "ubu", "talking", "vox", "bouche", "orator"],
        "intent": "formant ladder, mouth motion, and anti-formant canyons",
        "contract_bias": "fundamental is floor/tilt; F1/F2/F3 are actors; zeros articulate vowels",
    },
    "morph_special": {
        "title": "Morph Specials",
        "x3": ["Dual EQ Morph", "Dual EQ + LP Morph", "Dual EQ Morph/Expression", "Peak/Shelf Morph", "Morph Designer"],
        "p2k_contains": ["megasweepz", "rizer", "millennium", "ravage", "zoom", "alkaline"],
        "intent": "generated/morph writer classes needing separate decode or live capture",
        "contract_bias": "do not infer from fixed-class blocks; use support tables only as leads",
        "generated_only": True,
    },
}

FREQ_BINS = (
    ("sub", 60.0, 150.0),
    ("low", 150.0, 400.0),
    ("low_mid", 400.0, 1000.0),
    ("mouth", 1000.0, 2500.0),
    ("bite", 2500.0, 6000.0),
    ("air", 6000.0, 15000.0),
)


def p2k_slug(path: Path) -> str:
    return path.stem.lower()


def family_p2k_paths(needles: list[str]) -> list[Path]:
    paths = []
    for path in sorted(refmap.P2K_DIR.glob("P2k_*.json")):
        slug = p2k_slug(path)
        if any(needle in slug for needle in needles):
            paths.append(path)
    return paths


def mean_curve(curves: list[np.ndarray]) -> np.ndarray:
    return np.mean(np.vstack([refmap.normalize(curve) for curve in curves]), axis=0)


def safe_name(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(ch if ch.isalnum() else "_")
    return "_".join(part for part in "".join(out).split("_") if part)


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return round(float(np.quantile(values, q)), 3)


def fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{value:.2f}{suffix}"


def root_points_from_biquad(
    bq: tuple[float, float, float, float, float],
    sample_rate: float,
) -> list[dict[str, Any]]:
    b0, b1, b2, a1, a2 = bq
    out: list[dict[str, Any]] = []

    def add(kind: str, roots: np.ndarray) -> None:
        for z in roots:
            hz = abs(float(np.angle(z))) * sample_rate / (2.0 * math.pi)
            radius = float(abs(z))
            if hz < ROOT_FREQ_MIN or hz > ROOT_FREQ_MAX:
                continue
            out.append({
                "kind": kind,
                "freq_hz": hz,
                "radius": radius,
                "complex": bool(abs(complex(z).imag) > 1e-7),
                "outside_unit_circle": bool(radius > 1.0),
            })

    add("zero", np.roots((b0, b1, b2)))
    add("pole", np.roots((1.0, a1, a2)))
    return out


def x3_roots_for_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    corners = x3.read_target_corners(entry, int(refmap.X3_SR), FREQS)
    for corner in corners:
        for stage_index, bq in enumerate(corner.stages):
            for point in root_points_from_biquad(bq, refmap.X3_SR):
                out.append({
                    **point,
                    "reference": entry["name"],
                    "corner": corner.label,
                    "stage": stage_index,
                    "source": "x3",
                })
    return out


def p2k_roots_for_path(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    body = refmap.load_p2k_body(path)
    for morph, q, label in ((0.0, 0.0, "M0_Q0"), (1.0, 0.0, "M100_Q0"), (0.0, 1.0, "M0_Q100"), (1.0, 1.0, "M100_Q100")):
        rows = trench_ffi.packed_probe(body, morph, q)["biquad"]
        for stage_index, bq in enumerate(rows):
            for point in root_points_from_biquad(tuple(float(v) for v in bq), refmap.P2K_SR):
                out.append({
                    **point,
                    "reference": path.stem,
                    "corner": label,
                    "stage": stage_index,
                    "source": "p2k",
                })
    return out


def root_frequency_bounds(points: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    bins = []
    selected = [p for p in points if p["kind"] == kind]
    for name, lo, hi in FREQ_BINS:
        vals = [float(p["freq_hz"]) for p in selected if lo <= float(p["freq_hz"]) < hi]
        if vals:
            bins.append({
                "role": name,
                "range_hz": [lo, hi],
                "freq_hz_p10_p90": [quantile(vals, 0.10), quantile(vals, 0.90)],
                "observations": len(vals),
            })
    return {"kind": kind, "bands": bins}


def collect_landmark_freqs(curve_sets: dict[str, list[np.ndarray]]) -> dict[str, dict[str, list[float]]]:
    bins = {name: {"peaks": [], "valleys": []} for name, _, _ in FREQ_BINS}
    for curves in curve_sets.values():
        summary = refmap.landmarks(mean_curve(curves), limit=10)
        for kind in ("peaks", "valleys"):
            for item in summary[kind]:
                hz = float(item["freq_hz"])
                for name, lo, hi in FREQ_BINS:
                    if lo <= hz < hi:
                        bins[name][kind].append(hz)
                        break
    return bins


def contract_from_family(
    key: str,
    family: dict[str, Any],
    x3_curve_sets: dict[str, list[np.ndarray]],
    p2k_curve_sets: dict[str, list[np.ndarray]],
    root_points: list[dict[str, Any]],
) -> dict[str, Any]:
    all_sets = {**{f"x3:{k}": v for k, v in x3_curve_sets.items()}, **{f"p2k:{k}": v for k, v in p2k_curve_sets.items()}}
    x3_summaries = [refmap.summarize_curve_set(curves) for curves in x3_curve_sets.values()]
    p2k_summaries = [refmap.summarize_curve_set(curves) for curves in p2k_curve_sets.values()]
    all_summaries = x3_summaries + p2k_summaries
    landmarks = collect_landmark_freqs(all_sets)

    actor_bands = []
    for name, lo, hi in FREQ_BINS:
        peaks = landmarks[name]["peaks"]
        valleys = landmarks[name]["valleys"]
        if not peaks and not valleys:
            continue
        actor_bands.append({
            "role": name,
            "range_hz": [lo, hi],
            "peak_hz_p10_p90": [quantile(peaks, 0.10), quantile(peaks, 0.90)],
            "canyon_hz_p10_p90": [quantile(valleys, 0.10), quantile(valleys, 0.90)],
            "peak_observations": len(peaks),
            "canyon_observations": len(valleys),
        })

    return {
        "format": "family-reference-contract-v1",
        "family": key,
        "title": family["title"],
        "clean_room_policy": "Study-only aggregate bounds. Do not copy reference curves, words, coefficients, names, or presets into products.",
        "intent": family["intent"],
        "contract_bias": family["contract_bias"],
        "x3_nouns": list(x3_curve_sets.keys()),
        "p2k_verbs": list(p2k_curve_sets.keys()),
        "aggregate_metrics": {
            "x3_median_morph_motion_rms_db": quantile([s["morph_motion_rms_db"] for s in x3_summaries], 0.5),
            "p2k_median_morph_motion_rms_db": quantile([s["morph_motion_rms_db"] for s in p2k_summaries], 0.5),
            "x3_median_q_pressure_rms_db": quantile([s["q_pressure_rms_db"] for s in x3_summaries], 0.5),
            "p2k_median_q_pressure_rms_db": quantile([s["q_pressure_rms_db"] for s in p2k_summaries], 0.5),
            "median_low_minus_high_tilt_db": quantile([s["tilt_low_minus_high_db"] for s in all_summaries], 0.5),
        },
        "actor_bands": actor_bands,
        "root_bounds": {
            "zeros": root_frequency_bounds(root_points, "zero"),
            "poles": root_frequency_bounds(root_points, "pole"),
            "outside_unit_circle_zero_count": sum(1 for p in root_points if p["kind"] == "zero" and p["outside_unit_circle"]),
            "zero_count": sum(1 for p in root_points if p["kind"] == "zero"),
            "pole_count": sum(1 for p in root_points if p["kind"] == "pole"),
        },
    }


def plot_family(
    key: str,
    family: dict[str, Any],
    x3_curve_sets: dict[str, list[np.ndarray]],
    p2k_curve_sets: dict[str, list[np.ndarray]],
    out: Path,
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8), facecolor="#070a09")
    for ax in axes:
        ax.set_facecolor("#090d0c")
        ax.grid(True, which="both", color="#26342f", alpha=0.45, linewidth=0.55)
        ax.tick_params(colors="#a7b4ad", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#25352e")

    axes[0].set_title(f"{family['title']}: X3 nouns", color="#e9efe9", fontsize=11)
    for name, curves in x3_curve_sets.items():
        axes[0].semilogx(FREQS, np.clip(mean_curve(curves), -55, 28), lw=1.2, alpha=0.92, label=name)
    if not x3_curve_sets:
        axes[0].text(
            0.5, 0.5,
            "not scored yet\nwriter decode or live capture needed",
            transform=axes[0].transAxes,
            color="#aebbb4",
            ha="center",
            va="center",
            fontsize=11,
        )
    axes[0].set_xlim(float(FREQS[0]), float(FREQS[-1]))
    axes[0].set_ylim(-55, 28)
    axes[0].set_ylabel("normalized dB", color="#a7b4ad")
    if x3_curve_sets:
        axes[0].legend(facecolor="#101713", edgecolor="#26342f", labelcolor="#e9efe9", fontsize=7)

    axes[1].set_title(f"{family['title']}: P2K verbs", color="#e9efe9", fontsize=11)
    for name, curves in p2k_curve_sets.items():
        axes[1].semilogx(FREQS, np.clip(mean_curve(curves), -55, 28), lw=1.0, alpha=0.75, label=refmap.clean_label(name))
    axes[1].set_xlim(float(FREQS[0]), float(FREQS[-1]))
    axes[1].set_ylim(-55, 28)
    if len(p2k_curve_sets) <= 9:
        axes[1].legend(facecolor="#101713", edgecolor="#26342f", labelcolor="#e9efe9", fontsize=7)

    fig.suptitle(f"{family['title']} Grammar Browser", color="#e9efe9", fontsize=14)
    fig.tight_layout()
    fig.savefig(out, dpi=145)
    plt.close(fig)


def plot_roots(
    family: dict[str, Any],
    root_points: list[dict[str, Any]],
    out: Path,
) -> None:
    refs = []
    for point in root_points:
        ref = str(point["reference"])
        if ref not in refs:
            refs.append(ref)
    y_for = {name: i for i, name in enumerate(refs)}
    corner_color = {
        "M0_Q0": "#e8dfb6",
        "M100_Q0": "#5bd0ff",
        "M0_Q100": "#ff9470",
        "M100_Q100": "#ac95ff",
    }

    fig, ax = plt.subplots(figsize=(13.5, max(4.2, 0.34 * len(refs) + 1.8)), facecolor="#070a09")
    ax.set_facecolor("#090d0c")
    ax.grid(True, which="both", color="#26342f", alpha=0.45, linewidth=0.55)
    ax.tick_params(colors="#a7b4ad", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#25352e")

    for point in root_points:
        y = y_for[str(point["reference"])]
        x = float(point["freq_hz"])
        color = corner_color.get(str(point["corner"]), "#dce6df")
        marker = "o" if point["kind"] == "zero" else "^"
        size = 56 if point["kind"] == "zero" else 44
        fill = "none" if point["outside_unit_circle"] and point["kind"] == "zero" else color
        ax.scatter(
            [x], [y],
            s=size,
            marker=marker,
            edgecolors=color,
            facecolors=fill,
            linewidths=1.1,
            alpha=0.86 if point["source"] == "x3" else 0.55,
        )

    ax.set_xscale("log")
    ax.set_xlim(ROOT_FREQ_MIN, ROOT_FREQ_MAX)
    ax.set_ylim(-0.8, len(refs) - 0.2)
    ax.set_yticks(range(len(refs)))
    ax.set_yticklabels([refmap.clean_label(name) if name.startswith("P2k_") else name for name in refs], color="#dce6df")
    ax.set_xlabel("root frequency (Hz)", color="#a7b4ad")
    ax.set_title(f"{family['title']} zero/pole root rails", color="#e9efe9", fontsize=13)
    ax.text(
        0.99,
        0.02,
        "circle = zero, triangle = pole, hollow circle = zero outside unit circle",
        transform=ax.transAxes,
        color="#aebbb4",
        ha="right",
        va="bottom",
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=145)
    plt.close(fig)


def summary_table(curve_sets: dict[str, list[np.ndarray]], *, study_label: bool) -> str:
    rows = [
        "<table><thead><tr><th>reference</th><th>tilt low-high</th><th>morph motion</th><th>Q pressure</th><th>peaks</th><th>canyons</th></tr></thead><tbody>"
    ]
    for name, curves in curve_sets.items():
        s = refmap.summarize_curve_set(curves)
        label = refmap.clean_label(name) if study_label else name
        rows.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{fmt(s['tilt_low_minus_high_db'], ' dB')}</td>"
            f"<td>{fmt(s['morph_motion_rms_db'], ' dB')}</td>"
            f"<td>{fmt(s['q_pressure_rms_db'], ' dB')}</td>"
            f"<td>{len(s['landmarks']['peaks'])}</td>"
            f"<td>{len(s['landmarks']['valleys'])}</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def contract_table(contract: dict[str, Any]) -> str:
    rows = [
        "<table><thead><tr><th>actor band</th><th>range</th><th>peak p10-p90</th><th>canyon p10-p90</th><th>observations</th></tr></thead><tbody>"
    ]
    for band in contract["actor_bands"]:
        peak = band["peak_hz_p10_p90"]
        canyon = band["canyon_hz_p10_p90"]
        rows.append(
            "<tr>"
            f"<td>{band['role']}</td>"
            f"<td>{band['range_hz'][0]:.0f}-{band['range_hz'][1]:.0f} Hz</td>"
            f"<td>{fmt(peak[0], ' Hz')} - {fmt(peak[1], ' Hz')}</td>"
            f"<td>{fmt(canyon[0], ' Hz')} - {fmt(canyon[1], ' Hz')}</td>"
            f"<td>{band['peak_observations']} peaks / {band['canyon_observations']} canyons</td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def root_table(contract: dict[str, Any]) -> str:
    rows = [
        "<table><thead><tr><th>root kind</th><th>actor band</th><th>frequency p10-p90</th><th>observations</th></tr></thead><tbody>"
    ]
    for kind in ("zeros", "poles"):
        for band in contract["root_bounds"][kind]["bands"]:
            vals = band["freq_hz_p10_p90"]
            rows.append(
                "<tr>"
                f"<td>{kind}</td>"
                f"<td>{band['role']}</td>"
                f"<td>{fmt(vals[0], ' Hz')} - {fmt(vals[1], ' Hz')}</td>"
                f"<td>{band['observations']}</td>"
                "</tr>"
            )
    rows.append("</tbody></table>")
    rows.append(
        f"<p>Zeros: {contract['root_bounds']['zero_count']} total, "
        f"{contract['root_bounds']['outside_unit_circle_zero_count']} outside unit circle. "
        f"Poles: {contract['root_bounds']['pole_count']} total.</p>"
    )
    return "\n".join(rows)


def write_html(family_reports: list[dict[str, Any]]) -> None:
    css = """
body { margin: 0; background: #070a09; color: #dce6df; font-family: Segoe UI, Arial, sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 28px 24px 56px; }
h1 { font-size: 28px; margin: 0 0 8px; }
h2 { margin-top: 34px; border-top: 1px solid #26342f; padding-top: 22px; }
p, li { color: #aebbb4; line-height: 1.45; }
.note { border: 1px solid #26342f; background: #0c1210; padding: 12px 14px; }
.plot { width: 100%; border: 1px solid #26342f; background: #090d0c; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
table { width: 100%; border-collapse: collapse; font-size: 12px; margin: 10px 0 16px; }
th, td { border: 1px solid #26342f; padding: 6px 7px; vertical-align: top; }
th { color: #f1f5ef; background: #101713; }
a { color: #77d7ff; }
code { color: #ffe6a7; }
"""
    body = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>X3/P2K Family Browser</title>",
        f"<style>{css}</style></head><body><main>",
        "<h1>X3/P2K Family-Aware Reference Browser</h1>",
        "<p class='note'>Study-only clean-room taxonomy. X3 is used as class grammar; P2K is used as behavior evidence inside each family. Do not ship reference words, coefficients, curves, names, or preset data.</p>",
    ]
    for item in family_reports:
        contract = item["contract"]
        body += [
            f"<h2>{html.escape(contract['title'])}</h2>",
            f"<p><b>Intent:</b> {html.escape(contract['intent'])}<br><b>Contract bias:</b> {html.escape(contract['contract_bias'])}</p>",
            f"<p><a href='{html.escape(item['contract_file'])}'>contract JSON</a></p>",
            f"<img class='plot' src='{html.escape(item['root_plot_file'])}' alt='{html.escape(contract['title'])} root rails'>",
            f"<img class='plot' src='{html.escape(item['plot_file'])}' alt='{html.escape(contract['title'])} plot'>",
            "<div class='grid'><section><h3>X3 Nouns</h3>",
            summary_table(item["x3_curve_sets"], study_label=False),
            "</section><section><h3>P2K Verbs</h3>",
            summary_table(item["p2k_curve_sets"], study_label=True),
            "</section></div>",
            "<h3>Aggregate Actor Bounds</h3>",
            contract_table(contract),
            "<h3>Zero/Pole Root Bounds</h3>",
            root_table(contract),
        ]
        if contract["family"] == "morph_special":
            body.append(
                "<p class='note'>These X3 classes are generated writer classes, not fixed runtime blocks. "
                "See <a href='../x3_generated_writers/README.md'>the generated-writer report</a> "
                "for the decoded writer structure and support-table inventory.</p>"
            )
    body.append("</main></body></html>")
    (OUT / "index.html").write_text("\n".join(body), encoding="utf-8")


def main() -> None:
    if not trench_ffi.available():
        raise SystemExit("trench-core unavailable; build cargo release first")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "contracts").mkdir(exist_ok=True)
    (OUT / "plots").mkdir(exist_ok=True)

    manifest = x3.load_manifest()
    fixed_by_name = {entry["name"]: entry for entry in x3.fixed_entries(manifest)}
    generated_names = {entry["name"] for entry in manifest["menu"] if entry.get("kind") in {"generated_class", "designer_compiler"}}

    family_reports = []
    report: dict[str, Any] = {
        "format": "x3-p2k-family-browser-v1",
        "clean_room_policy": {
            "study_only": True,
            "no_reference_bytes_exported": True,
            "contracts_are_aggregate_bounds": True,
        },
        "families": {},
    }

    for key, family in FAMILIES.items():
        x3_curve_sets = {}
        for name in family["x3"]:
            if name in fixed_by_name:
                x3_curve_sets[name] = refmap.x3_corner_responses(fixed_by_name[name])
            elif name in generated_names:
                x3_curve_sets[name] = []

        x3_scored = {name: curves for name, curves in x3_curve_sets.items() if curves}
        p2k_curve_sets = {
            path.stem: refmap.p2k_corner_responses(path)
            for path in family_p2k_paths(family["p2k_contains"])
        }
        root_points = []
        for name in x3_scored:
            root_points.extend(x3_roots_for_entry(fixed_by_name[name]))
        for path in family_p2k_paths(family["p2k_contains"]):
            root_points.extend(p2k_roots_for_path(path))

        contract = contract_from_family(key, family, x3_scored, p2k_curve_sets, root_points)
        if family.get("generated_only"):
            contract["unscored_x3_classes"] = [name for name, curves in x3_curve_sets.items() if not curves]
            contract["decode_gap"] = "generated/morph writer classes have support tables but no scored runtime response blocks in this report"

        plot_rel = f"plots/{key}.png"
        root_plot_rel = f"plots/{key}_roots.png"
        contract_rel = f"contracts/{key}.json"
        plot_family(key, family, x3_scored, p2k_curve_sets, OUT / plot_rel)
        plot_roots(family, root_points, OUT / root_plot_rel)
        (OUT / contract_rel).write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

        family_reports.append({
            "key": key,
            "plot_file": plot_rel,
            "root_plot_file": root_plot_rel,
            "contract_file": contract_rel,
            "contract": contract,
            "x3_curve_sets": x3_scored,
            "p2k_curve_sets": p2k_curve_sets,
        })
        report["families"][key] = {
            "title": family["title"],
            "x3_scored": list(x3_scored.keys()),
            "x3_unscored": [name for name, curves in x3_curve_sets.items() if not curves],
            "p2k_study_refs": [refmap.clean_label(name) for name in p2k_curve_sets],
            "contract": contract_rel,
            "plot": plot_rel,
            "root_plot": root_plot_rel,
        }

    write_html(family_reports)
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'index.html'}")
    print(f"wrote {OUT / 'report.json'}")
    for key in FAMILIES:
        print(f"{key}: {OUT / 'contracts' / (key + '.json')}")


if __name__ == "__main__":
    main()
