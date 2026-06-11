#!/usr/bin/env python3
"""Build a clean-room X3-menu-to-P2K response reference map.

Study only. This decodes local reference shapes, compares offset-normalized
response curves, and writes reports. It does not emit body240 files or copy
reference bytes into product artifacts.
"""
from __future__ import annotations

import json
import math
import re
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
from pyruntime.freq_response import cascade_response_db  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from src.utils.body240 import PACKED_KEYS  # noqa: E402
from tools import x3_fixed_class_cleanroom as x3  # noqa: E402


OUT = ROOT / "dev" / "tmp" / "x3_p2k_reference_map"
P2K_DIR = ROOT / "juce-shell" / "assets" / "cartridges"
CORNER_LABELS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
COMMON_FREQS = np.geomspace(60.0, 15_000.0, 320)
COMPARE_MASK = (COMMON_FREQS >= 80.0) & (COMMON_FREQS <= 12_000.0)
P2K_SR = 39_062.5
X3_SR = 48_000.0


def clean_label(name: str) -> str:
    return re.sub(r"^P2k_\d+_", "", name.removesuffix(".json")).replace("_", " ")


def load_p2k_body(path: Path) -> bytes:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != "compiled-v1":
        raise ValueError(f"{path}: not compiled-v1")
    corners: dict[str, list[tuple[int, ...]]] = {}
    for keyframe in doc.get("keyframes", []):
        label = keyframe.get("label")
        if label not in CORNER_LABELS:
            continue
        packed = keyframe.get("packedWords")
        if not isinstance(packed, list) or len(packed) < 6:
            raise ValueError(f"{path}: keyframe {label} missing six packed rows")
        corners[PACKED_KEYS[label]] = [
            tuple(int(word) & 0xFFFF for word in row)
            for row in packed[:6]
        ]
    if sorted(corners) != ["A", "B", "C", "D"]:
        raise ValueError(f"{path}: missing packed corner labels")
    return trench_ffi.body_bytes_from_corner_words(corners)


def p2k_corner_responses(path: Path) -> list[np.ndarray]:
    body = load_p2k_body(path)
    out = []
    for morph, q in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
        rows = trench_ffi.packed_interpolate(body, morph, q)
        stages = [EncodedCoeffs(*row) for row in rows]
        out.append(cascade_response_db(stages, COMMON_FREQS, P2K_SR))
    return out


def x3_corner_responses(entry: dict[str, Any]) -> list[np.ndarray]:
    corners = x3.read_target_corners(entry, int(X3_SR), COMMON_FREQS)
    return [corner.response_db for corner in corners]


def normalize(curve: np.ndarray) -> np.ndarray:
    band = curve[COMPARE_MASK]
    return curve - float(np.mean(band))


def score(a: list[np.ndarray], b: list[np.ndarray]) -> dict[str, float]:
    rms = []
    max_abs = []
    corr = []
    for ca, cb in zip(a, b):
        aa = normalize(ca)[COMPARE_MASK]
        bb = normalize(cb)[COMPARE_MASK]
        delta = aa - bb
        rms.append(float(np.sqrt(np.mean(delta * delta))))
        max_abs.append(float(np.max(np.abs(delta))))
        if float(np.std(aa)) > 1e-6 and float(np.std(bb)) > 1e-6:
            corr.append(float(np.corrcoef(aa, bb)[0, 1]))
    return {
        "mean_rms_db": round(float(np.mean(rms)), 4),
        "max_rms_db": round(float(np.max(rms)), 4),
        "mean_max_abs_db": round(float(np.mean(max_abs)), 4),
        "mean_corr": round(float(np.mean(corr)) if corr else 0.0, 4),
    }


def landmarks(curve: np.ndarray, limit: int = 5) -> dict[str, list[dict[str, float]]]:
    y = normalize(curve)
    peaks: list[tuple[float, int]] = []
    valleys: list[tuple[float, int]] = []
    for i in range(3, len(y) - 3):
        local = y[max(0, i - 18):min(len(y), i + 19)]
        if y[i] >= y[i - 1] and y[i] > y[i + 1]:
            p = float(y[i] - np.percentile(local, 20))
            if p >= 2.0:
                peaks.append((p, i))
        if y[i] <= y[i - 1] and y[i] < y[i + 1]:
            p = float(np.percentile(local, 80) - y[i])
            if p >= 2.0:
                valleys.append((p, i))

    def pack(items: list[tuple[float, int]]) -> list[dict[str, float]]:
        out = []
        for prominence, index in sorted(items, reverse=True)[:limit]:
            out.append({
                "freq_hz": round(float(COMMON_FREQS[index]), 2),
                "level_db": round(float(y[index]), 2),
                "prominence_db": round(float(prominence), 2),
            })
        return sorted(out, key=lambda item: item["freq_hz"])

    return {"peaks": pack(peaks), "valleys": pack(valleys)}


def summarize_curve_set(curves: list[np.ndarray]) -> dict[str, Any]:
    avg = np.mean(np.vstack(curves), axis=0)
    low = float(np.mean(avg[(COMMON_FREQS >= 80.0) & (COMMON_FREQS <= 180.0)]))
    mid = float(np.mean(avg[(COMMON_FREQS >= 600.0) & (COMMON_FREQS <= 1800.0)]))
    high = float(np.mean(avg[(COMMON_FREQS >= 6000.0) & (COMMON_FREQS <= 12_000.0)]))
    morph_delta = normalize(curves[1]) - normalize(curves[0])
    q_delta = normalize(curves[2]) - normalize(curves[0])
    return {
        "tilt_low_minus_high_db": round(low - high, 3),
        "mid_minus_low_db": round(mid - low, 3),
        "morph_motion_rms_db": round(float(np.sqrt(np.mean(morph_delta[COMPARE_MASK] ** 2))), 3),
        "q_pressure_rms_db": round(float(np.sqrt(np.mean(q_delta[COMPARE_MASK] ** 2))), 3),
        "landmarks": landmarks(avg),
    }


def family_hint(x3_name: str, p2k_name: str) -> str:
    xn = x3_name.lower()
    pn = p2k_name.lower()
    if "phaser" in xn or "flanger" in xn:
        if any(w in pn for w in ("vox", "ringer", "comb", "kling", "ear", "shifta", "gizmo", "fuzzi")):
            return "phaser/comb candidate"
    if "vocal" in xn:
        if any(w in pn for w in ("ooh", "eeh", "ubu", "talking", "vox", "bouche", "orator")):
            return "vocal/formant candidate"
    if "lowpass" in xn:
        if any(w in pn for w in ("bass", "303", "tracer", "boland", "ace", "klub")):
            return "bass/lowpass candidate"
    if "highpass" in xn:
        if any(w in pn for w in ("razor", "radio", "alkaline", "hertz", "freak")):
            return "highpass/cut candidate"
    if "bandpass" in xn:
        if any(w in pn for w in ("bouche", "vox", "talking", "orator", "dead", "ear", "peaks")):
            return "bandpass/formant candidate"
    if "swept" in xn or "eq" in xn:
        if any(w in pn for w in ("sweep", "peaks", "alkaline", "ravage", "razor", "rizer", "millennium")):
            return "swept-eq candidate"
    return "shape-neighbor"


def plot_heatmap(rows: list[dict[str, Any]], x3_names: list[str], p2k_names: list[str], out: Path) -> None:
    matrix = np.full((len(x3_names), len(p2k_names)), np.nan)
    xi = {name: i for i, name in enumerate(x3_names)}
    pi = {name: i for i, name in enumerate(p2k_names)}
    for row in rows:
        matrix[xi[row["x3_name"]], pi[row["p2k_name"]]] = row["score"]["mean_rms_db"]
    capped = np.clip(matrix, 0.0, np.nanpercentile(matrix, 95))

    fig, ax = plt.subplots(figsize=(14.8, 8.2), facecolor="#070a09")
    ax.set_facecolor("#090d0c")
    im = ax.imshow(capped, aspect="auto", cmap="magma_r")
    ax.set_title("X3 fixed-class menu vs P2K bodies: lower RMS = closer response shape", color="#e9efe9", fontsize=13)
    ax.set_yticks(range(len(x3_names)))
    ax.set_yticklabels(x3_names, color="#dce6df", fontsize=8)
    ax.set_xticks(range(len(p2k_names)))
    ax.set_xticklabels([name.replace("P2k_", "") for name in p2k_names], rotation=70, ha="right", color="#dce6df", fontsize=7)
    ax.tick_params(colors="#a7b4ad")
    for spine in ax.spines.values():
        spine.set_color("#25352e")
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    cbar.ax.tick_params(colors="#a7b4ad")
    cbar.set_label("offset-normalized RMS dB", color="#dce6df")
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def write_markdown(report: dict[str, Any], out: Path) -> None:
    lines = [
        "# X3 Menu To P2K Reference Map",
        "",
        "Clean-room study reference. This compares response shape only. It does not authorize copying reference bytes, coefficient words, curves, names, or presets into products.",
        "",
        "## X3 -> Nearest P2K Neighbors",
        "",
        "| X3 menu class | closest shape neighbors | family-relevant P2K references | read |",
        "|---|---|---|---|",
    ]
    for row in report["x3_to_p2k"]:
        best = "; ".join(
            f"{hit['rank']}. {hit['p2k_study_label']} ({hit['score']['mean_rms_db']} dB, {hit['hint']})"
            for hit in row["nearest_p2k"][:5]
        )
        family = "; ".join(
            f"{hit['rank']}. {hit['p2k_study_label']} ({hit['score']['mean_rms_db']} dB)"
            for hit in row.get("nearest_family_p2k", [])[:5]
        ) or "none tagged yet"
        lines.append(f"| {row['x3_name']} | {best} | {family} | {row['interpretation']} |")
    lines += [
        "",
        "## Generated/Morph Classes",
        "",
    ]
    for item in report["generated_menu_classes"]:
        lines.append(f"- {item['x3_name']}: {item['status']}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    if not trench_ffi.available():
        raise SystemExit("trench-core unavailable; build cargo release first")
    OUT.mkdir(parents=True, exist_ok=True)

    manifest = x3.load_manifest()
    x3_entries = [entry for entry in x3.fixed_entries(manifest) if entry.get("name") != "No Filter"]
    p2k_paths = sorted(P2K_DIR.glob("P2k_*.json"))

    x3_curves = {entry["name"]: x3_corner_responses(entry) for entry in x3_entries}
    p2k_curves = {path.stem: p2k_corner_responses(path) for path in p2k_paths}

    all_scores: list[dict[str, Any]] = []
    x3_to_p2k = []
    for entry in x3_entries:
        xname = entry["name"]
        scores = []
        for pname, pcurves in p2k_curves.items():
            s = score(x3_curves[xname], pcurves)
            scores.append({
                "p2k_name": pname,
                "p2k_study_label": clean_label(pname),
                "score": s,
                "hint": family_hint(xname, pname),
            })
            all_scores.append({"x3_name": xname, "p2k_name": pname, "score": s})
        scores.sort(key=lambda item: (item["score"]["mean_rms_db"], -item["score"]["mean_corr"]))
        for rank, item in enumerate(scores, 1):
            item["rank"] = rank

        summary = summarize_curve_set(x3_curves[xname])
        if "phaser" in xname.lower() or "flanger" in xname.lower():
            interp = "comb/phaser foundation reference; expect zero/canyon-led motion in P2K neighbors"
        elif "vocal" in xname.lower():
            interp = "formant ladder reference; use as vocal range and correspondence evidence"
        elif "lowpass" in xname.lower() or "highpass" in xname.lower():
            interp = "fixed filter primitive; use for slope/floor/cap grammar"
        else:
            interp = "fixed menu primitive; use as shape grammar, not body source"

        family_scores = [item for item in scores if item["hint"] != "shape-neighbor"]
        x3_to_p2k.append({
            "x3_name": xname,
            "class": entry.get("class"),
            "rom_table": entry.get("rom_table"),
            "output_stages": entry.get("output_stages"),
            "summary": summary,
            "nearest_p2k": scores[:10],
            "nearest_family_p2k": family_scores[:10],
            "interpretation": interp,
        })

    generated = []
    for entry in manifest["menu"]:
        if entry.get("kind") in {"generated_class", "designer_compiler"}:
            generated.append({
                "x3_name": entry["name"],
                "class": entry.get("class"),
                "kind": entry.get("kind"),
                "status": "support tables exist, but no runtime response blocks were scored here; next step is writer/model decode or live capture",
            })

    p2k_to_x3 = []
    for pname, pcurves in p2k_curves.items():
        scores = []
        for entry in x3_entries:
            xname = entry["name"]
            scores.append({
                "x3_name": xname,
                "score": score(pcurves, x3_curves[xname]),
                "hint": family_hint(xname, pname),
            })
        scores.sort(key=lambda item: (item["score"]["mean_rms_db"], -item["score"]["mean_corr"]))
        p2k_to_x3.append({
            "p2k_name": pname,
            "p2k_study_label": clean_label(pname),
            "summary": summarize_curve_set(pcurves),
            "nearest_x3": scores[:6],
        })

    report = {
        "format": "x3-menu-to-p2k-reference-map-v1",
        "clean_room_policy": {
            "study_only": True,
            "copied_into_products": False,
            "score_domain": "offset-normalized response magnitude, four corners",
            "no_reference_bytes_exported": True,
        },
        "x3_decode": {
            "observed_candidate": "direct DF2T, i16/16384, word order raw slots 2,3,4,0,1 -> b0,b1,b2,a1,a2",
            "source": "ref/x3_menu/runtime_blocks",
            "sample_rate_hz": int(X3_SR),
        },
        "p2k_source": {
            "source": "juce-shell/assets/cartridges/P2k_*.json",
            "runtime": "trench-core packed interpolate/decode",
            "sample_rate_hz": P2K_SR,
        },
        "x3_to_p2k": x3_to_p2k,
        "p2k_to_x3": p2k_to_x3,
        "generated_menu_classes": generated,
        "outputs": {
            "heatmap": "heatmap.png",
            "markdown": "README.md",
        },
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, OUT / "README.md")
    plot_heatmap(all_scores, [entry["name"] for entry in x3_entries], list(p2k_curves.keys()), OUT / "heatmap.png")

    print(f"wrote {OUT / 'report.json'}")
    print(f"wrote {OUT / 'README.md'}")
    print(f"wrote {OUT / 'heatmap.png'}")
    for row in x3_to_p2k:
        best = row["nearest_p2k"][0]
        print(f"{row['x3_name']}: {best['p2k_study_label']} ({best['score']['mean_rms_db']} dB)")


if __name__ == "__main__":
    main()
