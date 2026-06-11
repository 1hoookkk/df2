#!/usr/bin/env python3
"""Block-diagram style authoring plot for Talking Hedz.

This is an analysis view, not a claim that the packed runtime contains seven
serial blocks. The first panel is a derived smooth foundation envelope from the
full cascade. The next six panels are the six shipped packed section rows shown
as zero-aware EQ actors.
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
ACTOR_NAMES = (
    "Actor 1\nAir / edge cap",
    "Actor 2\nLow-mouth mover",
    "Actor 3\nMid vowel",
    "Actor 4\nBite / tear",
    "Actor 5\nUpper formant cut",
    "Actor 6\nBody / canyon anchor",
)
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


def smooth_log_curve(curve: np.ndarray, width: int) -> np.ndarray:
    width = max(5, int(width) | 1)
    kernel_x = np.linspace(-2.7, 2.7, width)
    kernel = np.exp(-0.5 * kernel_x * kernel_x)
    kernel /= np.sum(kernel)
    pad = width // 2
    padded = np.pad(curve, pad_width=pad, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def curve_summary(curve: np.ndarray, freqs: np.ndarray) -> dict[str, float]:
    peak_i = int(np.argmax(curve))
    min_i = int(np.argmin(curve))
    return {
        "peak_db": float(curve[peak_i]),
        "peak_hz": float(freqs[peak_i]),
        "min_db": float(curve[min_i]),
        "min_hz": float(freqs[min_i]),
    }


def plot_stage_format(name: str, body: bytes, out_dir: Path, points: int) -> list[dict[str, float | str | int]]:
    freqs = np.logspace(math.log10(FREQ_MIN_HZ), math.log10(FREQ_MAX_HZ), int(points))
    fig, axes = plt.subplots(
        len(CORNER_ORDER),
        1 + ff.NUM_STAGES,
        figsize=(21.0, 8.2),
        dpi=155,
        sharex=True,
        sharey=False,
    )
    fig.patch.set_facecolor("#f7f3ea")

    rows: list[dict[str, float | str | int]] = []
    foundation_color = "#7a5a20"
    actor_color = "#2467a8"
    final_color = "#bd3d32"
    zero_color = "#2459a6"
    pole_color = "#b72d2d"

    for row_index, corner in enumerate(CORNER_ORDER):
        probe = ff.packed_probe(body, *CORNER_POS[corner])
        biquads = [tuple(map(float, bq)) for bq in probe["biquad"]]
        full = response_db_cascade(biquads, freqs)
        foundation = smooth_log_curve(full, max(61, int(points // 12)))
        panels = [foundation] + [response_db_biquad(bq, freqs) for bq in biquads]
        panel_names = ["Foundation\nenvelope"] + list(ACTOR_NAMES)

        for col_index, (curve, panel_name) in enumerate(zip(panels, panel_names)):
            ax = axes[row_index, col_index]
            ax.set_facecolor("#fffaf0")
            ax.semilogx(freqs, full, color=final_color, lw=0.8, alpha=0.20)
            ax.semilogx(
                freqs,
                curve,
                color=foundation_color if col_index == 0 else actor_color,
                lw=1.45,
                alpha=0.96,
            )
            ax.axhline(0.0, color="#777777", lw=0.55, alpha=0.52)
            ax.grid(True, which="both", lw=0.32, alpha=0.24)
            ax.set_xlim(FREQ_MIN_HZ, FREQ_MAX_HZ)
            lo = float(np.nanpercentile(curve, 1.0)) - 5.0
            hi = float(np.nanpercentile(curve, 99.0)) + 5.0
            if col_index == 0:
                lo = min(lo, float(np.nanmin(full)) + 15.0)
                hi = max(hi, float(np.nanmax(foundation)) + 4.0)
            if hi - lo < 18.0:
                mid = 0.5 * (hi + lo)
                lo = mid - 9.0
                hi = mid + 9.0
            ax.set_ylim(max(-75.0, lo), min(85.0, hi))

            if col_index > 0:
                bq = biquads[col_index - 1]
                b0, b1, b2, a1, a2 = bq
                for kind, coeffs in (("zero", (b0, b1, b2)), ("pole", (1.0, a1, a2))):
                    if abs(coeffs[0]) < 1e-18:
                        continue
                    for root in np.roots(np.asarray(coeffs, dtype=np.float64)):
                        if abs(root.imag) > 1e-8 and np.angle(root) < 0.0:
                            continue
                        freq_hz = abs(float(np.angle(root))) * SR / (2.0 * math.pi)
                        if not (FREQ_MIN_HZ <= freq_hz <= FREQ_MAX_HZ):
                            continue
                        point_i = int(np.argmin(np.abs(freqs - freq_hz)))
                        ax.scatter(
                            [freq_hz],
                            [curve[point_i]],
                            marker="v" if kind == "zero" else "^",
                            color=zero_color if kind == "zero" else pole_color,
                            edgecolor="white",
                            linewidth=0.45,
                            s=32 + 210 * max(0.0, min(0.25, abs(root) - 0.75)),
                            zorder=5,
                        )

            summary = curve_summary(curve, freqs)
            ax.text(
                0.03,
                0.06,
                f"peak {summary['peak_hz']:.0f} Hz\nmin {summary['min_hz']:.0f} Hz",
                transform=ax.transAxes,
                fontsize=6.4,
                color="#333333",
                bbox={"facecolor": "#fffaf0", "edgecolor": "#d5ccbd", "alpha": 0.84, "pad": 2.0},
            )
            if row_index == 0:
                ax.set_title(panel_name, fontsize=9.2)
            if col_index == 0:
                ax.set_ylabel(f"{corner}\ndB", fontsize=8)
            if row_index == len(CORNER_ORDER) - 1:
                ax.set_xlabel("Hz", fontsize=8)

            rows.append(
                {
                    "corner": corner,
                    "panel": "foundation" if col_index == 0 else f"actor_{col_index}",
                    "label": panel_name.replace("\n", " "),
                    **summary,
                    "max_pole_radius_at_corner": float(probe["max_pole_radius"]),
                    "unstable_mask": int(probe["unstable_mask"]),
                    "nonfinite_mask": int(probe["nonfinite_mask"]),
                }
            )

    fig.suptitle(f"{name}: block-diagram authoring stages", fontsize=14, y=0.992)
    fig.text(
        0.5,
        0.008,
        "brown=derived foundation envelope from final cascade; blue=six shipped section-row actors; red=faint final cascade. This is a 1+6 authoring view, not a seven-block runtime claim.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0.015, 0.035, 0.995, 0.965))
    fig.savefig(out_dir / "talking_hedz_block_stage_format.png")
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
    parser.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "talking_hedz_stage_format")
    parser.add_argument("--points", type=int, default=1800)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not ff.available():
        raise RuntimeError("trench_core packed FFI unavailable; build target/release/trench_core.dll")
    name, body = load_body(args.body)
    out_dir = args.out / slugify(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = plot_stage_format(name, body, out_dir, int(args.points))
    write_csv(out_dir / "block_stage_format_summary.csv", rows)
    (out_dir / "README.md").write_text(
        "\n".join(
            [
                f"# {name} Block-Stage Format Plot",
                "",
                "OBSERVED: the packed runtime exposes six second-order section rows.",
                "OBSERVED: blue panels are the six shipped section-row actors.",
                "INFERRED: the brown foundation panel is a derived smooth envelope from the full cascade.",
                "REJECTED: this plot does not prove a hidden seventh runtime block.",
                "",
                "## Files",
                "",
                "- `talking_hedz_block_stage_format.png`",
                "- `block_stage_format_summary.csv`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
