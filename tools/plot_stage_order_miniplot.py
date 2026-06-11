#!/usr/bin/env python3
"""Section-row ordered mini-plots for one packed body.

Study/debug tool. Reads a raw 240-byte body or compiled-v1 JSON, probes the
shipped packed runtime at the four corners, then plots serialized section-row
order: previous cumulative response, current row-only response, and new
cumulative response after adding that row.

No packed words or coefficient tables are emitted.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import struct
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi as ff  # noqa: E402

CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
CORNER_POS = {
    "M0_Q0": (0.0, 0.0),
    "M100_Q0": (1.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q100": (1.0, 1.0),
}
SR = 39_062.5
FREQ_MIN_HZ = 40.0
FREQ_MAX_HZ = 16_000.0
EPS = 1.0e-24


def slugify(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "body"


def load_body(path: Path) -> tuple[str, bytes]:
    payload = path.read_bytes()
    if len(payload) == ff.BODY_BYTES:
        return path.stem, payload
    doc = json.loads(payload.decode("utf-8"))
    if doc.get("format") != "compiled-v1":
        raise ValueError(f"{path}: expected raw 240-byte body or compiled-v1 JSON")
    by_label = {str(kf.get("label", "")): kf for kf in doc.get("keyframes", []) if isinstance(kf, dict)}
    words: list[int] = []
    for label in CORNER_ORDER:
        frame = by_label.get(label)
        if not frame:
            raise ValueError(f"{path}: missing keyframe {label}")
        rows = frame.get("packedWords")
        if not isinstance(rows, list) or len(rows) != ff.NUM_STAGES:
            raise ValueError(f"{path}: {label} needs six packedWords rows")
        for row in rows:
            if not isinstance(row, list) or len(row) != ff.NUM_COEFFS:
                raise ValueError(f"{path}: {label} packedWords rows need five words")
            words.extend(int(word) & 0xFFFF for word in row)
    body = struct.pack("<" + "H" * len(words), *words)
    if len(body) != ff.BODY_BYTES:
        raise ValueError(f"{path}: serialized body is {len(body)} bytes")
    return str(doc.get("name") or path.stem), body


def response_db_biquad(bq: tuple[float, float, float, float, float], freqs: np.ndarray) -> np.ndarray:
    b0, b1, b2, a1, a2 = bq
    z1 = np.exp(-1j * 2.0 * np.pi * freqs / SR)
    z2 = z1 * z1
    h = (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), EPS))


def response_db_cascade(
    biquads: list[tuple[float, float, float, float, float]],
    freqs: np.ndarray,
) -> np.ndarray:
    z1 = np.exp(-1j * 2.0 * np.pi * freqs / SR)
    z2 = z1 * z1
    h = np.ones_like(freqs, dtype=np.complex128)
    for b0, b1, b2, a1, a2 in biquads:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), EPS))


def curve_summary(curve: np.ndarray, freqs: np.ndarray) -> dict[str, float]:
    peak_i = int(np.argmax(curve))
    min_i = int(np.argmin(curve))
    low = (freqs >= 60.0) & (freqs <= 240.0)
    mid = (freqs >= 500.0) & (freqs <= 1800.0)
    high = (freqs >= 6000.0) & (freqs <= 12_000.0)
    return {
        "peak_db": float(curve[peak_i]),
        "peak_hz": float(freqs[peak_i]),
        "min_db": float(curve[min_i]),
        "min_hz": float(freqs[min_i]),
        "low_median_db": float(np.median(curve[low])),
        "mid_median_db": float(np.median(curve[mid])),
        "high_median_db": float(np.median(curve[high])),
        "high_minus_low_db": float(np.median(curve[high]) - np.median(curve[low])),
    }


def plot_order(name: str, body: bytes, out_dir: Path, points: int) -> list[dict[str, float | str | int]]:
    freqs = np.logspace(math.log10(FREQ_MIN_HZ), math.log10(FREQ_MAX_HZ), int(points))
    fig, axes = plt.subplots(
        len(CORNER_ORDER),
        ff.NUM_STAGES,
        figsize=(18.0, 8.2),
        dpi=155,
        sharex=True,
        sharey=True,
    )
    fig.patch.set_facecolor("#f7f3ea")
    rows: list[dict[str, float | str | int]] = []

    row_color = "#2a67a5"
    cumulative_color = "#111111"
    previous_color = "#a9a095"
    full_color = "#bc3d32"
    for row_index, corner in enumerate(CORNER_ORDER):
        probe = ff.packed_probe(body, *CORNER_POS[corner])
        biquads = [tuple(map(float, bq)) for bq in probe["biquad"]]
        full = response_db_cascade(biquads, freqs)
        previous = np.zeros_like(freqs)
        for section_index, bq in enumerate(biquads, start=1):
            ax = axes[row_index, section_index - 1]
            row_curve = response_db_biquad(bq, freqs)
            cumulative = previous + row_curve
            ax.semilogx(freqs, full, color=full_color, lw=0.85, alpha=0.28)
            if section_index > 1:
                ax.semilogx(freqs, previous, color=previous_color, lw=0.9, alpha=0.8)
            ax.semilogx(freqs, row_curve, color=row_color, lw=0.85, alpha=0.74)
            ax.semilogx(freqs, cumulative, color=cumulative_color, lw=1.3)
            ax.axhline(0.0, color="#777777", lw=0.55, alpha=0.5)
            ax.grid(True, which="both", lw=0.32, alpha=0.24)
            ax.set_facecolor("#fffaf0")
            ax.set_xlim(FREQ_MIN_HZ, FREQ_MAX_HZ)
            ax.set_ylim(-70.0, 70.0)
            if row_index == 0:
                ax.set_title(f"row {section_index}", fontsize=10)
            if section_index == 1:
                ax.set_ylabel(f"{corner}\ndB", fontsize=8)
            if row_index == len(CORNER_ORDER) - 1:
                ax.set_xlabel("Hz", fontsize=8)
            row_sum = curve_summary(row_curve, freqs)
            cum_sum = curve_summary(cumulative, freqs)
            ax.text(
                0.025,
                0.05,
                f"+row {section_index}\npeak {cum_sum['peak_hz']:.0f} Hz",
                transform=ax.transAxes,
                fontsize=6.5,
                color="#333333",
                bbox={"facecolor": "#fffaf0", "edgecolor": "#d5ccbd", "alpha": 0.84, "pad": 2.0},
            )
            rows.append(
                {
                    "corner": corner,
                    "section_row": section_index,
                    **{f"row_{key}": value for key, value in row_sum.items()},
                    **{f"cumulative_{key}": value for key, value in cum_sum.items()},
                    "max_pole_radius_at_corner": float(probe["max_pole_radius"]),
                    "unstable_mask": int(probe["unstable_mask"]),
                    "nonfinite_mask": int(probe["nonfinite_mask"]),
                }
            )
            previous = cumulative

    fig.suptitle(f"{name}: serialized section-row accumulation", fontsize=14, y=0.992)
    fig.text(
        0.5,
        0.008,
        "black=new cumulative after this row; blue=row only; gray=previous cumulative; red=final full cascade. Row order is serialization, not a musical stage hierarchy.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0.02, 0.035, 0.995, 0.965))
    fig.savefig(out_dir / "section_row_order_miniplot.png")
    plt.close(fig)
    return rows


def write_csv(path: Path, rows: list[dict[str, float | str | int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "body",
        type=Path,
        nargs="?",
        default=ROOT / "juce-shell" / "assets" / "cartridges" / "P2k_013_talking_hedz.json",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "stage_order_miniplot")
    parser.add_argument("--points", type=int, default=1800)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not ff.available():
        raise RuntimeError("trench_core packed FFI unavailable; build target/release/trench_core.dll")
    name, body = load_body(args.body)
    out_dir = args.out / slugify(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = plot_order(name, body, out_dir, int(args.points))
    write_csv(out_dir / "stage_order_summary.csv", rows)
    (out_dir / "README.md").write_text(
        "\n".join(
            [
                f"# {name} Section-Row Order Miniplot",
                "",
                "OBSERVED: rows are plotted in serialized section-row order 1 through 6.",
                "OBSERVED: black is cumulative response after adding that row.",
                "OBSERVED: red is final full cascade at the same corner.",
                "INFERRED: any foundation claim should be read from the cumulative curve, not from fixed row labels.",
                "REJECTED: row number is not a fixed musical stage or low-to-high hierarchy.",
                "",
                "## Files",
                "",
                "- `section_row_order_miniplot.png`",
                "- `stage_order_summary.csv`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
