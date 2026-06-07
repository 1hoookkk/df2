#!/usr/bin/env python3
"""Rank Target Browser candidates for faster auditioning.

This is not a shipping score and not a substitute for ears. It is a shortlist
score over existing Target Browser reports: stable survivors with strong visible
character, useful Morph movement, manageable Q drift, and low packed drift rise
to the top.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ROOT = ROOT / "dev" / "tmp" / "target_browser"


FAMILY_WEIGHTS: dict[str, dict[str, float]] = {
    "vocal": {"character": 0.30, "motion": 0.22, "q": 0.18, "drift": 0.16, "clean": 0.14},
    "comb_fracture": {"character": 0.34, "motion": 0.24, "q": 0.08, "drift": 0.14, "clean": 0.20},
    "bass_destruction": {"character": 0.26, "motion": 0.18, "q": 0.14, "drift": 0.18, "clean": 0.24},
    "metallic": {"character": 0.32, "motion": 0.18, "q": 0.16, "drift": 0.14, "clean": 0.20},
    "cavity": {"character": 0.28, "motion": 0.20, "q": 0.14, "drift": 0.18, "clean": 0.20},
    "air_pressure": {"character": 0.34, "motion": 0.24, "q": 0.06, "drift": 0.12, "clean": 0.24},
}

PEAK_RE = re.compile(r"peaks?\s+([0-9/]+)\s+Hz")
NOTCH_RE = re.compile(r"notch\s+([0-9/]+)\s+Hz")


# Spectral tilt — the "they all descend" axis the other columns don't capture.
# Measured through the shipped DLL. Guarded: if numpy/DLL are unavailable, tilt
# is left blank and the rest of the scorer is unaffected.
try:
    import sys as _sys
    _sys.path.insert(0, str(ROOT))
    import numpy as _np
    from pyruntime.trench_ffi import packed_probe as _packed_probe
    _TF = _np.exp(_np.linspace(math.log(50.0), math.log(16000.0), 200))
    _TW = 2.0 * math.pi * _TF / 39062.5
    _TZ1, _TZ2 = _np.exp(-1j * _TW), _np.exp(-2j * _TW)
    _TLX = _np.log10(_TF)
    _TILT_OK = True
except Exception:
    _TILT_OK = False


def _cascade_db(biquad):
    total = _np.zeros(len(_TF))
    for (b0, b1, b2, a1, a2) in biquad:
        num = b0 + b1 * _TZ1 + b2 * _TZ2
        den = 1.0 + a1 * _TZ1 + a2 * _TZ2
        total += 20.0 * _np.log10(_np.maximum(_np.abs(num / den), 1e-12))
    return total


def tilt_facts(body_path: Path) -> dict[str, Any]:
    """Mean spectral tilt (dB/decade) across the Morph/Q grid, through the engine.
    Negative = descends (dark), positive = rises (bright). Blank if unavailable."""
    if not _TILT_OK or not body_path.exists():
        return {"tilt_db_per_decade": "", "tilt_class": ""}
    try:
        b = body_path.read_bytes()
        slopes = [
            float(_np.polyfit(_TLX, _cascade_db(_packed_probe(b, m, q)["biquad"]), 1)[0])
            for m in (0.0, 0.5, 1.0) for q in (0.0, 1.0)
        ]
        tilt = round(sum(slopes) / len(slopes), 1)
    except Exception:
        return {"tilt_db_per_decade": "", "tilt_class": ""}
    cls = "T0_dark" if tilt < -4 else "T2_bright" if tilt > 1 else "T1_balanced"
    return {"tilt_db_per_decade": tilt, "tilt_class": cls}


def clamp01(x: float) -> float:
    if not math.isfinite(x):
        return 0.0
    return max(0.0, min(1.0, x))


def saturate(value: float, full_scale: float) -> float:
    return clamp01(value / max(full_scale, 1e-9))


def score_report(report: dict[str, Any], family: str = "") -> dict[str, Any]:
    gate = report["gate"]
    summary = gate["summary"]
    weights = FAMILY_WEIGHTS.get(family, {"character": 0.30, "motion": 0.20, "q": 0.14, "drift": 0.16, "clean": 0.20})

    if not gate.get("pass"):
        return {
            "score": 0.0,
            "tier": "CULLED",
            "components": {},
            "reason": ", ".join(gate.get("hard_failed", [])),
        }

    character = saturate(float(summary.get("character_score", 0.0)), 34.0)
    motion = saturate(float(summary.get("moves_on_morph_hz", 0.0)), 1200.0)
    q = 1.0 - saturate(float(summary.get("q_relocate_hz", 0.0)), 1400.0)
    drift = 1.0 - saturate(float(summary.get("packed_drift_db", 0.0)), 24.0)
    peak = 1.0 - saturate(max(0.0, float(summary.get("peak_db", -99.0)) - 3.0), 9.0)
    radius = 1.0 - saturate(max(0.0, float(summary.get("max_pole_radius", 0.0)) - 0.9992), 0.0008)

    advisory = set(gate.get("advisory_failed", []))
    chaos_penalty = 0.08 if "morph_chaos" in advisory else 0.0
    q_penalty = 0.05 if "q_center_shift" in advisory and weights["q"] >= 0.1 else 0.0
    drift_penalty = 0.07 if "packed_residual" in advisory else 0.0

    clean = 0.65 * peak + 0.35 * radius
    raw = (
        weights["character"] * character
        + weights["motion"] * motion
        + weights["q"] * q
        + weights["drift"] * drift
        + weights["clean"] * clean
        - chaos_penalty
        - q_penalty
        - drift_penalty
    )
    score = round(100.0 * clamp01(raw), 1)
    tier = "A" if score >= 72 else "B" if score >= 58 else "C"
    return {
        "score": score,
        "tier": tier,
        "components": {
            "character": round(character, 3),
            "motion": round(motion, 3),
            "q_discipline": round(q, 3),
            "packed_fit": round(drift, 3),
            "clean_headroom": round(clean, 3),
        },
        "reason": "",
    }


def _freqs_from_match(pattern: re.Pattern[str], text: str) -> list[int]:
    match = pattern.search(text)
    if not match:
        return []
    return [int(part) for part in match.group(1).split("/") if part.isdigit()]


def frequency_facts(provenance: str) -> dict[str, Any]:
    peaks = _freqs_from_match(PEAK_RE, provenance)
    notches = _freqs_from_match(NOTCH_RE, provenance)

    def first_in(lo: int, hi: int, values: list[int]) -> int | None:
        hits = [v for v in values if lo <= v < hi]
        return hits[0] if hits else None

    return {
        "peak_count": len(peaks),
        "notch_count": len(notches),
        "low_anchor_hz": first_in(40, 400, peaks),
        "mouth_peak_hz": first_in(400, 2500, peaks),
        "bite_or_air_peak_hz": first_in(2500, 18_000, peaks),
        "primary_notch_hz": notches[0] if notches else None,
        "peak_hz": "/".join(str(v) for v in peaks),
        "notch_hz": "/".join(str(v) for v in notches),
    }


def measured_classes(summary: dict[str, Any], provenance: str) -> dict[str, Any]:
    motion = float(summary.get("moves_on_morph_hz", 0.0))
    q_shift = float(summary.get("q_relocate_hz", 0.0))
    drift = float(summary.get("packed_drift_db", 0.0))
    radius = float(summary.get("max_pole_radius", 0.0))
    freqs = frequency_facts(provenance)

    if motion < 500:
        morph_class = "M0_static"
    elif motion < 1500:
        morph_class = "M1_moving"
    elif motion < 3000:
        morph_class = "M2_wide"
    else:
        morph_class = "M3_extreme"

    if q_shift < 700:
        q_class = "Q0_tightens"
    elif q_shift < 2000:
        q_class = "Q1_repositions"
    else:
        q_class = "Q2_identity_shift"

    if drift <= 6:
        fit_class = "F0_tight"
    elif drift <= 14:
        fit_class = "F1_usable"
    else:
        fit_class = "F2_loose"

    if radius >= 1.0:
        stability_class = "R3_unstable"
    elif radius >= 0.9992:
        stability_class = "R2_edge"
    elif radius >= 0.995:
        stability_class = "R1_hot"
    else:
        stability_class = "R0_safe"

    low_class = "L1_low_anchor" if freqs["low_anchor_hz"] is not None else "L0_no_low_anchor"
    zero_class = "Z0_no_notch" if freqs["notch_count"] == 0 else f"Z{min(freqs['notch_count'], 4)}_notches"
    signature = f"{low_class}_{zero_class}_{morph_class}_{q_class}_{fit_class}_{stability_class}"
    return {
        **freqs,
        "morph_class": morph_class,
        "q_class": q_class,
        "fit_class": fit_class,
        "stability_class": stability_class,
        "low_class": low_class,
        "zero_class": zero_class,
        "measured_signature": signature,
    }


def load_template_families() -> dict[str, str]:
    path = ROOT / "tools" / "target_templates.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["name"]: item.get("family", "") for item in data.get("templates", [])}


def iter_reports(run_dirs: list[Path]) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    for run_dir in run_dirs:
        for report_path in sorted(run_dir.glob("cand_*/report.json")):
            try:
                out.append((report_path, json.loads(report_path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                continue
    return out


def run_name(path: Path) -> str:
    return path.parents[1].name


def write_outputs(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ranking.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    with (out_dir / "ranking.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "rank", "score", "tier", "template", "run", "candidate", "provenance",
                "moves_on_morph_hz", "q_relocate_hz", "packed_drift_db",
                "character_score", "max_pole_radius",
                "peak_count", "notch_count", "low_anchor_hz", "mouth_peak_hz",
                "bite_or_air_peak_hz", "primary_notch_hz", "peak_hz", "notch_hz",
                "morph_class", "q_class", "fit_class", "stability_class",
                "tilt_db_per_decade", "tilt_class",
                "low_class", "zero_class", "measured_signature", "report",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})

    cards = []
    for row in rows:
        report_rel = Path(row["report"]).as_posix()
        audition = Path(row["report"]).parents[1] / "audition.html"
        cards.append(
            "<section>"
            f"<h2>#{row['rank']} {html.escape(row['tier'])} {html.escape(row['candidate'])} "
            f"<span>{row['score']:.1f}</span></h2>"
            f"<p>{html.escape(row['template'])} / {html.escape(row['run'])}</p>"
            f"<p>{html.escape(row['provenance'])}</p>"
            f"<p>{html.escape(row['measured_signature'])}</p>"
            f"<p>Morph {row['moves_on_morph_hz']:.0f} Hz · Q shift {row['q_relocate_hz']:.0f} Hz · "
            f"packed drift {row['packed_drift_db']:.1f} dB · character {row['character_score']:.1f}</p>"
            f"<p><a href='{html.escape(audition.as_posix())}'>audition page</a> · "
            f"<a href='{html.escape(report_rel)}'>report</a></p>"
            "</section>"
        )
    html_doc = """<!doctype html>
<meta charset="utf-8">
<title>Target Browser Ranking</title>
<style>
body{margin:0;background:#080a09;color:#e9eee9;font:14px Segoe UI,Arial,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 22px 56px}
h1{font-size:28px;margin:0 0 8px}
p{color:#aab6af;line-height:1.45}
section{border-top:1px solid #26342f;padding:14px 0}
h2{font-size:19px;margin:0 0 4px;color:#9de8bd}
h2 span{color:#f0d879}
a{color:#78d7ff}
</style>
<main>
<h1>Target Browser Shortlist Ranking</h1>
<p>Ranking for audition order only. It cannot hear taste; it pushes stable, vivid, moving, pack-faithful candidates upward.</p>
""" + "\n".join(cards) + "\n</main>\n"
    (out_dir / "shortlist.html").write_text(html_doc, encoding="utf-8")


def write_spread(out_dir: Path, rows: list[dict[str, Any]], n: int) -> None:
    """A tilt-balanced top-N: round-robin the highest-ranked bright/balanced/dark
    so a shortlist can't come out all one tilt. Highest rank wins within a class."""
    buckets: dict[str, list[dict[str, Any]]] = {"T2_bright": [], "T1_balanced": [], "T0_dark": []}
    for r in rows:                                   # rows already in rank order
        if r.get("tier") in ("A", "B") and r.get("tilt_class") in buckets:
            buckets[r["tilt_class"]].append(r)
    idx = {c: 0 for c in buckets}
    picked: list[dict[str, Any]] = []
    while len(picked) < n:
        progressed = False
        for c in buckets:
            if len(picked) < n and idx[c] < len(buckets[c]):
                picked.append(buckets[c][idx[c]]); idx[c] += 1; progressed = True
        if not progressed:
            break
    picked.sort(key=lambda r: r["rank"])
    with (out_dir / "spread.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["rank", "score", "tier", "tilt_class",
                           "tilt_db_per_decade", "run", "candidate", "measured_signature"])
        w.writeheader()
        for r in picked:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
    from collections import Counter
    print(f"spread top-{len(picked)}: {dict(Counter(r['tilt_class'] for r in picked))} -> {out_dir / 'spread.csv'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="*", type=Path, help="Target Browser run directories")
    parser.add_argument("--latest", type=int, default=0, help="rank N most recent run directories")
    parser.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "target_browser_rankings")
    parser.add_argument("--spread", type=int, default=0, help="also write a tilt-balanced top-N shortlist (spread.csv)")
    args = parser.parse_args()

    run_dirs = [p.resolve() for p in args.runs]
    if args.latest:
        dirs = [p for p in DEFAULT_RUN_ROOT.iterdir() if p.is_dir()]
        dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        run_dirs.extend(dirs[:args.latest])
    if not run_dirs:
        raise SystemExit("pass run directories or use --latest N")

    families = load_template_families()
    rows = []
    for report_path, report in iter_reports(run_dirs):
        template = report.get("template", "")
        scored = score_report(report, families.get(template, ""))
        summary = report["gate"]["summary"]
        provenance = report.get("provenance", "")
        classes = measured_classes(summary, provenance)
        candidate = report.get("candidate", report_path.parent.name)
        tilt = tilt_facts(report_path.parent / f"{candidate}.body240")
        rows.append({
            "score": scored["score"],
            "tier": scored["tier"],
            "components": scored["components"],
            "template": template,
            "run": run_name(report_path),
            "candidate": candidate,
            "provenance": provenance,
            "moves_on_morph_hz": float(summary.get("moves_on_morph_hz", 0.0)),
            "q_relocate_hz": float(summary.get("q_relocate_hz", 0.0)),
            "packed_drift_db": float(summary.get("packed_drift_db", 0.0)),
            "character_score": float(summary.get("character_score", 0.0)),
            "max_pole_radius": float(summary.get("max_pole_radius", 0.0)),
            "pass": bool(report["gate"].get("pass")),
            "report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
            **classes,
            **tilt,
        })
    rows.sort(key=lambda r: (r["pass"], r["score"], r["character_score"]), reverse=True)
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    write_outputs(args.out, rows)
    if args.spread:
        write_spread(args.out, rows, args.spread)
    print(f"ranked {len(rows)} candidates")
    print(f"wrote {args.out / 'ranking.json'}")
    print(f"wrote {args.out / 'ranking.csv'}")
    print(f"wrote {args.out / 'shortlist.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
