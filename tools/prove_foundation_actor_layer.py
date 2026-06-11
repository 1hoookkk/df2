#!/usr/bin/env python3
"""Prove or reject the foundation + added pole/zero actor hypothesis.

Study-only ablation:
1. Decode packed bodies through trench_core.
2. Classify each row at each endpoint as broad foundation or added actor.
3. Compare full cascade response against foundation-only response.
4. Check whether the missing residual peaks line up with omitted actor poles/zeros.

No packed words, coefficients, endpoint tables, or source bytes are emitted.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_generated_presets import response_db
from tools.report_p2k_reference_fundamentals import classify_base, state_rows
from tools.study_p2k_reference_grammar import FREQS, load_calibration_records, load_records, one_stage_response_db
from pyruntime import trench_ffi

OUT = ROOT / "dev" / "tmp" / "foundation_actor_ablation"

POSITIONS = {
    "HOME": (0.0, 0.0),
    "AWAY": (1.0, 0.0),
    "PUSH_HOME": (0.0, 1.0),
    "PUSH_AWAY": (1.0, 1.0),
    "CENTER": (0.5, 0.5),
}

FOUNDATION_ROLES = {
    "broad tilt",
    "broad cavity",
    "rising slope",
    "descending cliff",
    "real-root shelf",
}


def rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(values * values)))


def best_gain_align(candidate: np.ndarray, target: np.ndarray) -> np.ndarray:
    return candidate + float(np.median(target - candidate))


def peak_freqs(curve: np.ndarray, n: int = 8) -> list[float]:
    centered = np.abs(curve - np.median(curve))
    if len(centered) < 3:
        return []
    idx = np.argpartition(centered, -min(n, len(centered)))[-min(n, len(centered)) :]
    idx = sorted(idx, key=lambda i: centered[i], reverse=True)
    out: list[float] = []
    for i in idx:
        f = float(FREQS[i])
        if all(abs(math.log2(f / g)) > 0.08 for g in out):
            out.append(f)
        if len(out) >= n:
            break
    return out


def nearest_octave(freq: float, roots: list[float]) -> float | None:
    roots = [r for r in roots if r and r > 0]
    if not roots or freq <= 0:
        return None
    return min(abs(math.log2(freq / root)) for root in roots)


def analyze_state(record: dict[str, Any], state_name: str, morph: float, secondary: float) -> dict[str, Any]:
    rows = trench_ffi.packed_probe(record["body"], morph, secondary)["biquad"]
    row_facts = state_rows(record["body"], morph, secondary)

    foundation_indices: list[int] = []
    actor_indices: list[int] = []
    actor_roots: list[float] = []
    role_counts: dict[str, int] = {}
    for i, fact in enumerate(row_facts):
        role = classify_base(fact)
        role_counts[role] = role_counts.get(role, 0) + 1
        if role in FOUNDATION_ROLES:
            foundation_indices.append(i)
        elif fact.get("active"):
            actor_indices.append(i)
            for key in ("pole_hz", "zero_hz"):
                value = fact.get(key)
                if value:
                    actor_roots.append(float(value))

    full = response_db(rows)
    foundation = np.zeros_like(full)
    for i in foundation_indices:
        foundation += one_stage_response_db(rows[i])
    foundation = best_gain_align(foundation, full)
    missing = full - foundation

    residual_freqs = peak_freqs(missing, 8)
    nearest = [nearest_octave(freq, actor_roots) for freq in residual_freqs]
    matched = [d for d in nearest if d is not None and d <= 0.18]

    return {
        "body_id": record.get("preset", "body"),
        "role": record.get("role", ""),
        "variant": record.get("variant", ""),
        "state": state_name,
        "foundation_rows": len(foundation_indices),
        "actor_rows": len(actor_indices),
        "role_counts": role_counts,
        "foundation_only_rms_error_db": round(rms(missing), 3),
        "foundation_only_peak_error_db": round(float(np.max(np.abs(missing))), 3),
        "residual_peak_freqs_hz": [round(f, 1) for f in residual_freqs],
        "residual_peaks_near_actor_fraction": round(len(matched) / max(1, len(residual_freqs)), 3),
        "nearest_actor_root_octaves_median": round(float(statistics.median([d for d in nearest if d is not None])), 3)
        if any(d is not None for d in nearest)
        else None,
    }


def representative_records() -> list[dict[str, Any]]:
    records = [r for r in load_records() if int(r.get("variant", 0)) == 0]
    records += [r for r in load_calibration_records() if int(r.get("variant", 0)) == 0]
    return records


def write_plot(rows: list[dict[str, Any]]) -> None:
    vals = sorted(float(r["foundation_only_rms_error_db"]) for r in rows)
    fig, ax = plt.subplots(figsize=(9.5, 4.8), facecolor="#101214")
    ax.set_facecolor("#101214")
    ax.plot(range(1, len(vals) + 1), vals, color="#f6a878", linewidth=2.0)
    ax.axhline(statistics.median(vals), color="#5fae6e", linewidth=1.0, linestyle="--")
    ax.set_title("Foundation-only ablation error across decoded states", color="#d9dde2")
    ax.set_xlabel("state sample sorted by RMS error", color="#c4cad2")
    ax.set_ylabel("RMS error after removing actor rows (dB)", color="#c4cad2")
    ax.tick_params(colors="#c4cad2")
    ax.grid(True, color="#24272d", linewidth=0.5)
    for spine in ax.spines.values():
        spine.set_color("#3b4048")
    fig.tight_layout()
    fig.savefig(OUT / "ablation_error.png", dpi=140)
    plt.close(fig)


def write_report(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Foundation + Actor Ablation Proof",
        "",
        "Study-only packed-runtime ablation.",
        "",
        "A foundation-only model is built by summing rows classified as broad",
        "tilt/cavity/shelf/cliff foundation rows, with one global gain alignment.",
        "The omitted rows are active pole/zero actors. If the foundation-only",
        "residual is large and its largest errors sit near omitted actor roots,",
        "then the missing layer is added poles/zeros, not another hidden stage.",
        "",
        "## Verdict",
        "",
        f"- samples: `{summary['samples']}` decoded body states",
        f"- median foundation-only RMS error: `{summary['median_foundation_only_rms_error_db']}` dB",
        f"- median foundation-only peak error: `{summary['median_foundation_only_peak_error_db']}` dB",
        f"- median residual peaks near omitted actor roots: `{summary['median_residual_peaks_near_actor_fraction']}`",
        f"- samples with actor rows: `{summary['samples_with_actor_rows']}`",
        "",
        "## Strongest Counterexamples To Foundation-Only",
        "",
        "| body | state | foundation rows | actor rows | RMS err dB | peak err dB | residual peak Hz | near actor frac |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for row in sorted(rows, key=lambda r: r["foundation_only_rms_error_db"], reverse=True)[:12]:
        freqs = ", ".join(str(f) for f in row["residual_peak_freqs_hz"][:4])
        lines.append(
            f"| {row['body_id']} | {row['state']} | {row['foundation_rows']} | {row['actor_rows']} | "
            f"{row['foundation_only_rms_error_db']} | {row['foundation_only_peak_error_db']} | {freqs} | "
            f"{row['residual_peaks_near_actor_fraction']} |"
        )
    lines += [
        "",
        "Boundary: this report does not emit packed words, coefficients, endpoint",
        "tables, source bytes, or reconstructable corner data.",
        "",
    ]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for record in representative_records():
        for name, (morph, secondary) in POSITIONS.items():
            rows.append(analyze_state(record, name, morph, secondary))

    rms_errors = [float(r["foundation_only_rms_error_db"]) for r in rows]
    peak_errors = [float(r["foundation_only_peak_error_db"]) for r in rows]
    near_fracs = [float(r["residual_peaks_near_actor_fraction"]) for r in rows]
    summary = {
        "format": "df2-foundation-actor-ablation-v1",
        "samples": len(rows),
        "body_count": len(representative_records()),
        "median_foundation_only_rms_error_db": round(float(statistics.median(rms_errors)), 3),
        "median_foundation_only_peak_error_db": round(float(statistics.median(peak_errors)), 3),
        "median_residual_peaks_near_actor_fraction": round(float(statistics.median(near_fracs)), 3),
        "samples_with_actor_rows": sum(1 for r in rows if int(r["actor_rows"]) > 0),
        "boundary": "study-only aggregate proof; no packed words, coefficient rows, endpoint tables, source bytes, or reconstructable corner data",
    }
    (OUT / "summary.json").write_text(json.dumps({"summary": summary, "samples": rows}, indent=2) + "\n", encoding="utf-8")
    with (OUT / "samples.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "body_id",
            "role",
            "variant",
            "state",
            "foundation_rows",
            "actor_rows",
            "foundation_only_rms_error_db",
            "foundation_only_peak_error_db",
            "residual_peaks_near_actor_fraction",
            "nearest_actor_root_octaves_median",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})
    write_report(rows, summary)
    write_plot(rows)
    print(json.dumps(summary, indent=2))
    print(f"wrote {OUT / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
