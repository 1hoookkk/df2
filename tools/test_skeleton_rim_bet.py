#!/usr/bin/env python3
"""Probe the "type skeleton + Secondary/Q rim" bet on study bodies.

DEV STUDY ONLY: this reads local reference `.body240` study fixtures and emits
aggregate pole/zero/radius/response metrics. It does not write shipping laws,
copy bytes into recipes, or promote any reference table.
"""
from __future__ import annotations

import argparse
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

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.capture_compiler import ActorGeometry, describe_stage  # noqa: E402
from tools.law_author import FREQS, cascade_db  # noqa: E402

TARGETS = (
    {
        "type": "REZ",
        "label": "violent Q",
        "folder": ROOT / "ref" / "p2k_variants" / "P2k_029_lucifer_s_q",
    },
    {
        "type": "LPF",
        "label": "hard sweep",
        "folder": ROOT / "ref" / "p2k_variants" / "P2k_001_megasweepz",
    },
)

MORPHS = (0.0, 0.5, 1.0)


@dataclass(frozen=True)
class StageDelta:
    stage: int
    pole_freq_q0_hz: float
    pole_freq_q1_hz: float
    pole_freq_drift_oct: float
    pole_radius_q0: float
    pole_radius_q1: float
    pole_radius_delta: float
    zero_freq_q0_hz: float | None
    zero_freq_q1_hz: float | None
    zero_freq_drift_oct: float | None
    zero_radius_q0: float | None
    zero_radius_q1: float | None
    zero_radius_delta: float | None
    gain_delta_db: float


def octave_distance(a: float, b: float) -> float:
    return abs(math.log2(max(float(a), 20.0) / max(float(b), 20.0)))


def gain_delta_db(a: float, b: float) -> float:
    return 20.0 * math.log10(max(float(b), 1.0e-12) / max(float(a), 1.0e-12))


def response_db(body: bytes, morph: float, q: float) -> np.ndarray:
    probe = trench_ffi.packed_probe(body, morph, q)
    return cascade_db(probe["biquad"])


def stage_delta(index: int, q0: ActorGeometry, q1: ActorGeometry) -> StageDelta:
    zero_q0 = q0.zero
    zero_q1 = q1.zero
    zero_drift = None
    zero_radius_delta = None
    if zero_q0 is not None and zero_q1 is not None:
        zero_drift = octave_distance(zero_q0.freq_hz, zero_q1.freq_hz)
        zero_radius_delta = float(zero_q1.radius - zero_q0.radius)
    return StageDelta(
        stage=index + 1,
        pole_freq_q0_hz=float(q0.pole.freq_hz),
        pole_freq_q1_hz=float(q1.pole.freq_hz),
        pole_freq_drift_oct=octave_distance(q0.pole.freq_hz, q1.pole.freq_hz),
        pole_radius_q0=float(q0.pole.radius),
        pole_radius_q1=float(q1.pole.radius),
        pole_radius_delta=float(q1.pole.radius - q0.pole.radius),
        zero_freq_q0_hz=None if zero_q0 is None else float(zero_q0.freq_hz),
        zero_freq_q1_hz=None if zero_q1 is None else float(zero_q1.freq_hz),
        zero_freq_drift_oct=zero_drift,
        zero_radius_q0=None if zero_q0 is None else float(zero_q0.radius),
        zero_radius_q1=None if zero_q1 is None else float(zero_q1.radius),
        zero_radius_delta=zero_radius_delta,
        gain_delta_db=gain_delta_db(q0.gain, q1.gain),
    )


def summarize(values: list[float]) -> dict[str, float]:
    arr = np.asarray([v for v in values if np.isfinite(v)], dtype=np.float64)
    if arr.size == 0:
        return {"median": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "median": float(np.median(arr)),
        "p90": float(np.percentile(arr, 90.0)),
        "max": float(np.max(arr)),
    }


def probe_body(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    if len(body) != trench_ffi.BODY_BYTES:
        raise ValueError(f"{path}: expected {trench_ffi.BODY_BYTES} bytes, got {len(body)}")

    morph_reports = []
    for morph in MORPHS:
        rows_q0 = trench_ffi.packed_interpolate(body, morph, 0.0)
        rows_q1 = trench_ffi.packed_interpolate(body, morph, 1.0)
        geom_q0 = [describe_stage(np.asarray(row, dtype=np.float64), 39062.5) for row in rows_q0]
        geom_q1 = [describe_stage(np.asarray(row, dtype=np.float64), 39062.5) for row in rows_q1]
        deltas = [stage_delta(i, a, b) for i, (a, b) in enumerate(zip(geom_q0, geom_q1))]

        db0 = response_db(body, morph, 0.0)
        db1 = response_db(body, morph, 1.0)
        diff = db1 - db0
        q0_probe = trench_ffi.packed_probe(body, morph, 0.0)
        q1_probe = trench_ffi.packed_probe(body, morph, 1.0)
        morph_reports.append(
            {
                "morph": morph,
                "q0_max_pole_radius": float(q0_probe["max_pole_radius"]),
                "q1_max_pole_radius": float(q1_probe["max_pole_radius"]),
                "q_max_radius_delta": float(q1_probe["max_pole_radius"] - q0_probe["max_pole_radius"]),
                "response_rms_delta_db": float(np.sqrt(np.mean(diff * diff))),
                "response_max_lift_db": float(np.max(diff)),
                "response_max_cut_db": float(np.min(diff)),
                "stage_deltas": [asdict(delta) for delta in deltas],
            }
        )
    return {"body": str(path.relative_to(ROOT)), "morphs": morph_reports}


def summarize_target(body_reports: list[dict[str, Any]]) -> dict[str, Any]:
    pole_freq_drifts = []
    zero_freq_drifts = []
    pole_radius_deltas = []
    zero_radius_deltas = []
    q_radius_deltas = []
    response_rms = []
    for body in body_reports:
        for morph in body["morphs"]:
            q_radius_deltas.append(float(morph["q_max_radius_delta"]))
            response_rms.append(float(morph["response_rms_delta_db"]))
            for stage in morph["stage_deltas"]:
                pole_freq_drifts.append(float(stage["pole_freq_drift_oct"]))
                pole_radius_deltas.append(float(stage["pole_radius_delta"]))
                if stage["zero_freq_drift_oct"] is not None:
                    zero_freq_drifts.append(float(stage["zero_freq_drift_oct"]))
                if stage["zero_radius_delta"] is not None:
                    zero_radius_deltas.append(float(stage["zero_radius_delta"]))

    # This is a deliberately soft evidence tag. It only says the sampled body
    # looks more like "edge pressure on a recognizable frame" than "new map."
    supports_bet = (
        summarize(pole_freq_drifts)["median"] <= 0.45
        and summarize(q_radius_deltas)["median"] >= 0.02
        and summarize(response_rms)["median"] >= 3.0
    )
    return {
        "pole_freq_drift_oct": summarize(pole_freq_drifts),
        "zero_freq_drift_oct": summarize(zero_freq_drifts),
        "pole_radius_delta": summarize(pole_radius_deltas),
        "zero_radius_delta": summarize(zero_radius_deltas),
        "q_max_radius_delta": summarize(q_radius_deltas),
        "response_rms_delta_db": summarize(response_rms),
        "supports_skeleton_plus_rim_bet": bool(supports_bet),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Skeleton + Rim Bet Probe",
        "",
        "DEV STUDY ONLY. Reads local reference `.body240` fixtures, probes them through `trench_core`, and reports aggregate behavior. This is one test, not doctrine.",
        "",
        "## Verdict",
        "",
    ]
    for target in report["targets"]:
        summary = target["summary"]
        verdict = "SUPPORTS" if summary["supports_skeleton_plus_rim_bet"] else "MIXED"
        lines += [
            f"### {target['type']} - {target['label']}: {verdict}",
            "",
            f"- bodies: {len(target['bodies'])}",
            f"- median pole frequency drift under Q: {summary['pole_freq_drift_oct']['median']:.3f} oct",
            f"- median zero frequency drift under Q: {summary['zero_freq_drift_oct']['median']:.3f} oct",
            f"- median max-pole-radius delta under Q: {summary['q_max_radius_delta']['median']:.4f}",
            f"- median response RMS delta under Q: {summary['response_rms_delta_db']['median']:.2f} dB",
            "",
        ]
    lines += [
        "## Evidence Labels",
        "",
        "- OBSERVED: Metrics come from packed interpolation/probe via `trench_core` against 240-byte study bodies.",
        "- INFERRED: `supports_skeleton_plus_rim_bet` is a soft threshold for low frequency remap plus meaningful radius/response change.",
        "- UNKNOWN: Whether this generalizes to all 50 types without running the same probe over the full menu.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_plot(report: dict[str, Any], path: Path) -> None:
    labels = [target["type"] for target in report["targets"]]
    pole_drift = [target["summary"]["pole_freq_drift_oct"]["median"] for target in report["targets"]]
    radius_delta = [target["summary"]["q_max_radius_delta"]["median"] for target in report["targets"]]
    response_rms = [target["summary"]["response_rms_delta_db"]["median"] for target in report["targets"]]

    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.2), facecolor="#f4efe4")
    specs = (
        ("Pole Frequency Drift", pole_drift, "oct", "#2d6f9f"),
        ("Max Radius Delta", radius_delta, "radius", "#7a8530"),
        ("Response RMS Delta", response_rms, "dB", "#9a4f2c"),
    )
    for ax, (title, values, ylabel, color) in zip(axes, specs):
        ax.bar(labels, values, color=color, width=0.52)
        ax.set_title(title, fontsize=10)
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", alpha=0.25)
        for i, value in enumerate(values):
            ax.text(i, value, f"{value:.2f}", ha="center", va="bottom", fontsize=8)
    fig.suptitle("Skeleton + Secondary/Q Rim Probe", x=0.02, ha="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "skeleton_rim_bet")
    args = parser.parse_args(argv)

    if not trench_ffi.available():
        print("error: trench_core packed probe unavailable; build with cargo build --release -p trench-core", file=sys.stderr)
        return 1

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    targets = []
    for target in TARGETS:
        paths = sorted(Path(target["folder"]).glob("variant_*.bin"))
        if not paths:
            raise FileNotFoundError(f"no variants found in {target['folder']}")
        body_reports = [probe_body(path) for path in paths]
        targets.append(
            {
                "type": target["type"],
                "label": target["label"],
                "folder": str(Path(target["folder"]).relative_to(ROOT)),
                "bodies": body_reports,
                "summary": summarize_target(body_reports),
            }
        )

    report = {
        "provenance": "dev-study-only; local reference bodies are probed, not copied into shipping artifacts",
        "body_bytes": trench_ffi.BODY_BYTES,
        "runtime": str(trench_ffi.lib_path()),
        "morphs": list(MORPHS),
        "targets": targets,
    }

    report_path = out / "report.json"
    md_path = out / "report.md"
    plot_path = out / "summary.png"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, md_path)
    write_plot(report, plot_path)

    print(f"report -> {report_path}")
    print(f"notes  -> {md_path}")
    print(f"plot   -> {plot_path}")
    for target in targets:
        summary = target["summary"]
        verdict = "SUPPORTS" if summary["supports_skeleton_plus_rim_bet"] else "MIXED"
        print(
            f"{target['type']:>3} {verdict}: "
            f"pole drift median {summary['pole_freq_drift_oct']['median']:.3f} oct, "
            f"radius delta median {summary['q_max_radius_delta']['median']:.4f}, "
            f"response delta median {summary['response_rms_delta_db']['median']:.2f} dB"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
