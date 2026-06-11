#!/usr/bin/env python3
"""Reduce selected private P2K references to structural fundamentals.

Study-only clean-room report. This intentionally emits qualitative row roles and
aggregate motion, not packed words or reconstructable endpoint tables.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from tools.audit_generated_presets import response_db, stage_metrics  # noqa: E402
from tools.study_p2k_reference_grammar import (  # noqa: E402
    band_median,
    foundation_analysis,
    load_calibration_records,
    load_records,
    one_stage_response_db,
)

OUT = ROOT / "dev" / "tmp" / "p2k_reference_fundamentals"
POSITIONS = {
    "M0/S0": (0.0, 0.0),
    "M1/S0": (1.0, 0.0),
    "M0/S1": (0.0, 1.0),
    "M1/S1": (1.0, 1.0),
}


def compact_name(name: str) -> str:
    return name.removeprefix("P2k_")


def octave_move(a: float | None, b: float | None) -> float | None:
    if not a or not b or a <= 0.0 or b <= 0.0:
        return None
    return math.log2(b / a)


def fmt_signed(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}{suffix}"


def fmt_unsigned(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{value:.2f}{suffix}"


def state_rows(body: bytes, morph: float, secondary: float) -> list[dict]:
    rows = trench_ffi.packed_probe(body, morph, secondary)["biquad"]
    out = []
    for index, row in enumerate(rows):
        roots = stage_metrics(row)
        curve = one_stage_response_db(row)
        low = band_median(curve, 60.0, 180.0)
        mid = band_median(curve, 500.0, 1800.0)
        high = band_median(curve, 6000.0, 14000.0)
        out.append({
            **roots,
            "stage": index + 1,
            "low_db": low,
            "mid_db": mid,
            "high_db": high,
            "tilt_db": high - low,
            "span_db": float(np.max(curve) - np.min(curve)),
            "peak_db": float(np.max(curve)),
            "floor_db": float(np.min(curve)),
        })
    return out


def classify_base(row: dict) -> str:
    if not row.get("active"):
        return "identity"
    pole_kind = row.get("pole_kind")
    zero_kind = row.get("zero_kind")
    offset = row.get("zero_offset_octaves")
    tilt = float(row["tilt_db"])
    span = float(row["span_db"])
    if pole_kind == "real_pair" or zero_kind == "real_pair":
        if tilt >= 12.0:
            return "rising slope"
        if tilt <= -12.0:
            return "descending cliff"
        return "real-root shelf"
    if abs(tilt) >= 24.0:
        return "broad tilt"
    if offset is not None and abs(offset) > 1.5:
        return "remote-zero counterweight"
    if offset is not None and abs(offset) <= 1.0:
        return "local peak/canyon"
    if span >= 18.0:
        return "broad cavity"
    return "spectral actor"


def classify_motion(base: dict, m1: dict, s1: dict) -> list[str]:
    if not base.get("active"):
        return []
    tags = []
    morph_pole = octave_move(base.get("pole_hz"), m1.get("pole_hz"))
    morph_zero = octave_move(base.get("zero_hz"), m1.get("zero_hz"))
    sec_pole = octave_move(base.get("pole_hz"), s1.get("pole_hz"))
    sec_zero = octave_move(base.get("zero_hz"), s1.get("zero_hz"))
    if morph_pole is not None and abs(morph_pole) >= 1.0:
        tags.append("fast morph sweep")
    elif morph_pole is not None and abs(morph_pole) >= 0.35:
        tags.append("morph sweep")
    if sec_pole is not None and abs(sec_pole) >= 0.35:
        tags.append("secondary shift")
    if base.get("pole_radius") is not None and s1.get("pole_radius") is not None:
        if abs(float(s1["pole_radius"]) - float(base["pole_radius"])) >= 0.015:
            tags.append("secondary stress")
    if morph_pole is not None and morph_zero is not None:
        if morph_pole * morph_zero < 0.0 and abs(morph_pole - morph_zero) >= 0.5:
            tags.append("contrary crossing")
        elif abs(morph_pole - morph_zero) >= 1.0:
            tags.append("zero counter-motion")
    if sec_pole is not None and sec_zero is not None and abs(sec_pole - sec_zero) >= 1.0:
        tags.append("secondary zero counter-motion")
    return tags


def body_grammar(rows: list[dict], foundation: dict) -> str:
    base_roles = [row["base_role"] for row in rows]
    motion = [tag for row in rows for tag in row["motion_tags"]]
    broad = sum(role in {"descending cliff", "rising slope", "broad tilt", "real-root shelf"}
                for role in base_roles)
    local = sum(role == "local peak/canyon" for role in base_roles)
    remote = sum(role == "remote-zero counterweight" for role in base_roles)
    crossings = motion.count("contrary crossing")
    stress = motion.count("secondary stress")
    fast = motion.count("fast morph sweep")
    tilt = float(foundation["cascade_high_minus_low_db"])

    if crossings >= 1:
        return "opposed/crossing field: indexed rows travel against their zeros"
    if tilt >= 12.0:
        return "rising high-pass/shelf foundation with moving cuts or peaks"
    if tilt <= -55.0 and broad >= 1:
        return "hard descending cliff with layered character rows"
    if local >= 3 and stress >= 1:
        return "clustered vocal/cavity mountains sharpened by Secondary"
    if fast >= 2:
        return "distributed sweep field: several indexed rows travel together"
    if remote >= 2 or broad >= 2:
        return "distributed broad-stage field: no single polite EQ interpretation"
    return "mixed foundation plus indexed character actors"


def analyze(record: dict) -> dict:
    states = {name: state_rows(record["body"], *pos) for name, pos in POSITIONS.items()}
    foundation = foundation_analysis(record)
    rows = []
    for index in range(6):
        base = states["M0/S0"][index]
        m1 = states["M1/S0"][index]
        s1 = states["M0/S1"][index]
        rows.append({
            "stage": index + 1,
            "base_role": classify_base(base),
            "pole_kind": base.get("pole_kind", "none"),
            "zero_kind": base.get("zero_kind", "none"),
            "base_zero_offset_oct": base.get("zero_offset_octaves"),
            "base_tilt_db": base.get("tilt_db"),
            "base_span_db": base.get("span_db"),
            "morph_pole_move_oct": octave_move(base.get("pole_hz"), m1.get("pole_hz")),
            "morph_zero_move_oct": octave_move(base.get("zero_hz"), m1.get("zero_hz")),
            "secondary_pole_move_oct": octave_move(base.get("pole_hz"), s1.get("pole_hz")),
            "secondary_zero_move_oct": octave_move(base.get("zero_hz"), s1.get("zero_hz")),
            "motion_tags": classify_motion(base, m1, s1),
        })
    return {
        "preset": record["preset"],
        "role": record["role"],
        "foundation_method": foundation["method_heuristic"],
        "cascade_tilt_db": foundation["cascade_high_minus_low_db"],
        "strongest_foundation_stage": foundation["strongest_foundation_stage"] + 1,
        "broad_stage_count": foundation["broad_stage_count"],
        "grammar": body_grammar(rows, foundation),
        "rows": rows,
    }


def write_report(analyses: list[dict]) -> None:
    lines = [
        "# Selected Reference Fundamentals",
        "",
        "Study-only clean-room reduction of selected private reference fixtures.",
        "This report records structural behavior, not packed words or endpoint tables.",
        "",
        "## What The References Actually Say",
        "",
        "- The six stages are indexed correspondence rows. They are not universally",
        "  six semantic cavities and they are not merely disposable bookkeeping.",
        "- Every row preserves numerator and denominator behavior together.",
        "- The strongest references use several foundation methods: hard descending",
        "  cliffs, rising shelves, opposed windows, clustered vocal mountains, and",
        "  distributed sweep fields.",
        "- Local pole-zero tears and remote-zero counterweights coexist.",
        "- Morph and Secondary frequently change different aspects of the same row.",
        "  Rigid pole-zero co-motion is not the law.",
        "",
        "## Per-Reference Fundamentals",
        "",
    ]
    for body in analyses:
        suffix = " [CALIBRATION]" if body["role"] == "calibration" else ""
        lines += [
            f"### {compact_name(body['preset'])}{suffix}",
            "",
            f"- **Construction grammar:** {body['grammar']}.",
            f"- **Foundation at M0/S0:** {body['foundation_method']}; cascade tilt "
            f"`{fmt_signed(body['cascade_tilt_db'], ' dB')}`; strongest broad row "
            f"`S{body['strongest_foundation_stage']}`; broad rows `{body['broad_stage_count']}`.",
            "",
            "| Row | M0/S0 role | zero offset | tilt | Morph pole | Morph zero | Secondary pole | motion tags |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for row in body["rows"]:
            tags = ", ".join(row["motion_tags"]) or "-"
            lines.append(
                f"| S{row['stage']} | {row['base_role']} | "
                f"{fmt_signed(row['base_zero_offset_oct'], ' oct')} | "
                f"{fmt_signed(row['base_tilt_db'], ' dB')} | "
                f"{fmt_signed(row['morph_pole_move_oct'], ' oct')} | "
                f"{fmt_signed(row['morph_zero_move_oct'], ' oct')} | "
                f"{fmt_signed(row['secondary_pole_move_oct'], ' oct')} | {tags} |"
            )
        lines.append("")

    role_counts = Counter(row["base_role"] for body in analyses for row in body["rows"])
    tag_counts = Counter(tag for body in analyses for row in body["rows"] for tag in row["motion_tags"])
    lines += [
        "## Cross-Reference Construction Laws",
        "",
        "M0/S0 row-role counts across the selected set and calibration fixture:",
        "",
    ]
    for name, count in role_counts.most_common():
        lines.append(f"- `{name}`: `{count}` rows")
    lines += ["", "Motion-tag counts:", ""]
    for name, count in tag_counts.most_common():
        lines.append(f"- `{name}`: `{count}` rows")
    lines += [
        "",
        "## Forge Consequence",
        "",
        "The correct first Forge surface is response-led but row-aware:",
        "",
        "1. Hero: complete packed-runtime curve, corners, center, and sweep contact strip.",
        "2. Underlay: six indexed rows preserving numerator and denominator together.",
        "3. Constructors: lawful whole-program and bundle starters for cliff, shelf,",
        "   window, crossing, cavity cluster, and distributed sweep grammars.",
        "4. Repair mode: open an indexed row only when the packed trajectory needs a",
        "   precise correction.",
        "5. Batch mode: sweep deterministic program macros, not arbitrary roots.",
        "",
    ]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not trench_ffi.available():
        raise SystemExit("trench-core FFI unavailable; run cargo build --release -p trench-core")
    OUT.mkdir(parents=True, exist_ok=True)
    records = [row for row in load_records() if row["variant"] == 0]
    records += [row for row in load_calibration_records() if row["variant"] == 0]
    analyses = [analyze(row) for row in records]
    (OUT / "summary.json").write_text(json.dumps(analyses, indent=2), encoding="utf-8")
    write_report(analyses)
    print(f"wrote {OUT / 'report.md'}")
    print(f"wrote {OUT / 'summary.json'}")
    print(f"references: {len(analyses)}")


if __name__ == "__main__":
    main()

