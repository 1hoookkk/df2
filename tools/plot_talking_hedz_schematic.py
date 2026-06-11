"""Study-only engineering plots for the P2K Talking Hedz cartridge.

This does not export vendor packed words or coefficient tables. It reads the
local study cartridge, asks the shipped packed-runtime FFI to probe each corner,
then plots derived DSP structure: per-section transfer functions and pole/zero
root locations.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi as ff  # noqa: E402

CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
CORNER_POS = {
    "M0_Q0": (0.0, 0.0),
    "M100_Q0": (1.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q100": (1.0, 1.0),
}
FREQ_MIN_HZ = 40.0
FREQ_MAX_HZ = 16_000.0
EPS = 1e-20


@dataclass(frozen=True)
class RootPoint:
    section: int
    kind: str
    freq_hz: float
    radius: float
    angle_rad: float
    imag_sign: int


def load_body_bytes(cartridge_path: Path) -> tuple[bytes, float, str]:
    data = json.loads(cartridge_path.read_text(encoding="utf-8"))
    keyframes = {frame["label"]: frame for frame in data["keyframes"]}
    flat = bytearray()
    for label in CORNER_ORDER:
        if label not in keyframes:
            raise ValueError(f"missing keyframe {label}")
        rows = keyframes[label]["packedWords"]
        if len(rows) != ff.NUM_STAGES:
            raise ValueError(f"{label} has {len(rows)} sections; expected {ff.NUM_STAGES}")
        for row in rows:
            if len(row) != ff.NUM_COEFFS:
                raise ValueError(f"{label} has a row with {len(row)} words; expected {ff.NUM_COEFFS}")
            for word in row:
                flat += (int(word) & 0xFFFF).to_bytes(2, "little")
    body = bytes(flat)
    if len(body) != ff.BODY_BYTES:
        raise ValueError(f"serialized body is {len(body)} bytes; expected {ff.BODY_BYTES}")
    sr = float(data.get("authoring_sample_rate_hz") or data.get("sampleRate") or 39062.5)
    return body, sr, str(data.get("name") or cartridge_path.stem)


def response_db_biquad(bq: tuple[float, float, float, float, float], freqs: np.ndarray, sr: float) -> np.ndarray:
    b0, b1, b2, a1, a2 = bq
    z1 = np.exp(-1j * 2.0 * np.pi * freqs / sr)
    z2 = z1 * z1
    h = (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), EPS))


def response_db_cascade(biquads: list[tuple[float, float, float, float, float]], freqs: np.ndarray, sr: float) -> np.ndarray:
    h = np.ones_like(freqs, dtype=np.complex128)
    z1 = np.exp(-1j * 2.0 * np.pi * freqs / sr)
    z2 = z1 * z1
    for b0, b1, b2, a1, a2 in biquads:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), EPS))


def roots_for_section(section: int, bq: tuple[float, float, float, float, float], sr: float) -> list[RootPoint]:
    b0, b1, b2, a1, a2 = bq
    roots: list[RootPoint] = []
    for kind, coeffs in (("zero", (b0, b1, b2)), ("pole", (1.0, a1, a2))):
        if abs(coeffs[0]) < 1e-18:
            continue
        for z in np.roots(np.asarray(coeffs, dtype=np.float64)):
            angle = float(np.angle(z))
            # Keep both real roots. For conjugate complex pairs, keep one
            # positive-frequency point in the plots/table.
            if abs(z.imag) > 1e-8 and angle < 0.0:
                continue
            freq_hz = abs(angle) * sr / (2.0 * math.pi)
            roots.append(
                RootPoint(
                    section=section,
                    kind=kind,
                    freq_hz=float(freq_hz),
                    radius=float(abs(z)),
                    angle_rad=abs(angle),
                    imag_sign=0 if abs(z.imag) <= 1e-8 else (1 if z.imag > 0 else -1),
                )
            )
    return roots


def probe_corners(body: bytes) -> dict[str, dict]:
    out = {}
    for label in CORNER_ORDER:
        morph, q = CORNER_POS[label]
        out[label] = ff.packed_probe(body, morph, q)
    return out


def section_summary_rows(corners: dict[str, dict], freqs: np.ndarray, sr: float) -> tuple[list[dict], dict[str, list[np.ndarray]], dict[str, np.ndarray]]:
    rows: list[dict] = []
    section_curves: dict[str, list[np.ndarray]] = {}
    cascade_curves: dict[str, np.ndarray] = {}
    for label in CORNER_ORDER:
        biquads = [tuple(map(float, bq)) for bq in corners[label]["biquad"]]
        section_curves[label] = [response_db_biquad(bq, freqs, sr) for bq in biquads]
        cascade_curves[label] = response_db_cascade(biquads, freqs, sr)
        for section, (bq, curve) in enumerate(zip(biquads, section_curves[label]), start=1):
            roots = roots_for_section(section, bq, sr)
            pole_roots = [r for r in roots if r.kind == "pole"]
            zero_roots = [r for r in roots if r.kind == "zero"]
            roots_in_band = [r for r in roots if FREQ_MIN_HZ <= r.freq_hz <= FREQ_MAX_HZ]
            curve_peak_i = int(np.argmax(curve))
            curve_min_i = int(np.argmin(curve))
            base = {
                "corner": label,
                "morph": CORNER_POS[label][0],
                "q": CORNER_POS[label][1],
                "section": section,
                "section_peak_db": float(curve[curve_peak_i]),
                "section_peak_hz": float(freqs[curve_peak_i]),
                "section_min_db": float(curve[curve_min_i]),
                "section_min_hz": float(freqs[curve_min_i]),
                "dc_db": float(curve[0]),
                "nyquist_side_db": float(curve[-1]),
                "max_pole_radius_at_corner": float(corners[label]["max_pole_radius"]),
                "unstable_mask": int(corners[label]["unstable_mask"]),
                "nonfinite_mask": int(corners[label]["nonfinite_mask"]),
            }
            for root in roots_in_band:
                root_row = dict(base)
                root_row.update(
                    {
                        "root_kind": root.kind,
                        "root_freq_hz": root.freq_hz,
                        "root_radius": root.radius,
                        "root_angle_rad": root.angle_rad,
                        "root_imag_sign": root.imag_sign,
                    }
                )
                rows.append(root_row)
            if not roots_in_band:
                root_row = dict(base)
                root_row.update(
                    {
                        "root_kind": "none_in_band",
                        "root_freq_hz": "",
                        "root_radius": "",
                        "root_angle_rad": "",
                        "root_imag_sign": "",
                    }
                )
                rows.append(root_row)
            # Add compact section-level root lists for the Markdown summary.
            base["pole_freqs_hz"] = ";".join(f"{r.freq_hz:.1f}" for r in pole_roots)
            base["pole_radii"] = ";".join(f"{r.radius:.5f}" for r in pole_roots)
            base["zero_freqs_hz"] = ";".join(f"{r.freq_hz:.1f}" for r in zero_roots)
            base["zero_radii"] = ";".join(f"{r.radius:.5f}" for r in zero_roots)
    return rows, section_curves, cascade_curves


def root_y(curve: np.ndarray, freqs: np.ndarray, freq_hz: float) -> float:
    return float(curve[int(np.argmin(np.abs(freqs - freq_hz)))])


def plot_section_schematic(
    corners: dict[str, dict],
    section_curves: dict[str, list[np.ndarray]],
    freqs: np.ndarray,
    sr: float,
    out_path: Path,
    title: str,
) -> None:
    fig, axes = plt.subplots(
        ff.NUM_STAGES,
        len(CORNER_ORDER),
        figsize=(18.0, 15.0),
        dpi=150,
        sharex=True,
        sharey=False,
    )
    fig.patch.set_facecolor("#f7f3ea")
    pole_color = "#b72d2d"
    zero_color = "#2459a6"
    curve_color = "#202020"
    for col, label in enumerate(CORNER_ORDER):
        axes[0, col].set_title(f"{label}  M={CORNER_POS[label][0]:.0f} Q={CORNER_POS[label][1]:.0f}", fontsize=11)
        for row in range(ff.NUM_STAGES):
            ax = axes[row, col]
            curve = section_curves[label][row]
            ax.semilogx(freqs, curve, color=curve_color, lw=1.35)
            lo = float(np.nanmin(curve)) - 4.0
            hi = float(np.nanmax(curve)) + 4.0
            if hi - lo < 14.0:
                mid = 0.5 * (hi + lo)
                lo = mid - 7.0
                hi = mid + 7.0
            ax.axhline(0.0, color="#999999", lw=0.6, alpha=0.5)
            ax.grid(True, which="both", lw=0.35, alpha=0.25)
            ax.set_facecolor("#fffaf0")
            ax.set_xlim(FREQ_MIN_HZ, FREQ_MAX_HZ)
            ax.set_ylim(lo, hi)
            ax.text(0.02, 0.88, f"S{row + 1}", transform=ax.transAxes, fontsize=9, weight="bold")
            ax.text(
                0.98,
                0.88,
                f"{lo:.0f}..{hi:.0f} dB",
                transform=ax.transAxes,
                fontsize=6.5,
                ha="right",
                color="#666666",
            )
            bq = tuple(map(float, corners[label]["biquad"][row]))
            for root in roots_for_section(row + 1, bq, sr):
                if not (FREQ_MIN_HZ <= root.freq_hz <= FREQ_MAX_HZ):
                    continue
                y = root_y(curve, freqs, root.freq_hz)
                if root.kind == "pole":
                    ax.scatter(
                        [root.freq_hz],
                        [y],
                        marker="^",
                        s=42 + 260 * max(0.0, root.radius - 0.75),
                        color=pole_color,
                        edgecolor="white",
                        linewidth=0.5,
                        zorder=5,
                    )
                    dy = 4.0
                else:
                    ax.scatter(
                        [root.freq_hz],
                        [y],
                        marker="v",
                        s=42 + 260 * max(0.0, root.radius - 0.75),
                        color=zero_color,
                        edgecolor="white",
                        linewidth=0.5,
                        zorder=5,
                    )
                    dy = -5.0
                if root.freq_hz > 65.0:
                    ax.annotate(
                        f"{root.kind[0].upper()} {root.freq_hz:.0f}\nr={root.radius:.3f}",
                        xy=(root.freq_hz, y),
                        xytext=(root.freq_hz, y + dy),
                        textcoords="data",
                        ha="center",
                        va="bottom" if dy > 0 else "top",
                        fontsize=6.2,
                        color=pole_color if root.kind == "pole" else zero_color,
                    )
            if col == 0:
                ax.set_ylabel("dB")
            if row == ff.NUM_STAGES - 1:
                ax.set_xlabel("Hz")
    fig.suptitle(f"{title}: section transfer functions by corner", fontsize=15, y=0.995)
    fig.text(
        0.5,
        0.006,
        "Each cell is one second-order section. Red triangles are denominator roots (poles). Blue triangles are numerator roots (zeros).",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0.018, 0.025, 0.995, 0.975))
    fig.savefig(out_path)
    plt.close(fig)


def _section_kind_roots(corners: dict[str, dict], sr: float, section: int, kind: str) -> dict[str, list[RootPoint]]:
    found: dict[str, list[RootPoint]] = {}
    for label in CORNER_ORDER:
        bq = tuple(map(float, corners[label]["biquad"][section - 1]))
        roots = [
            root
            for root in roots_for_section(section, bq, sr)
            if root.kind == kind and FREQ_MIN_HZ <= root.freq_hz <= FREQ_MAX_HZ
        ]
        found[label] = sorted(roots, key=lambda r: r.freq_hz)
    return found


def plot_root_frequency_schematic(corners: dict[str, dict], sr: float, out_path: Path, title: str) -> None:
    fig, axes = plt.subplots(ff.NUM_STAGES, 2, figsize=(11.2, 14.0), dpi=160, sharex=True, sharey=True)
    fig.patch.set_facecolor("#f7f3ea")
    kinds = (("pole", "#b72d2d"), ("zero", "#2459a6"))
    q_lines = (
        ("Q0", "M0_Q0", "M100_Q0", "-", 0.0),
        ("Q100", "M0_Q100", "M100_Q100", "--", 1.0),
    )
    for section in range(1, ff.NUM_STAGES + 1):
        for col, (kind, color) in enumerate(kinds):
            ax = axes[section - 1, col]
            ax.set_facecolor("#fffaf0")
            ax.set_yscale("log")
            ax.set_ylim(FREQ_MIN_HZ, FREQ_MAX_HZ)
            ax.set_xlim(-0.07, 1.07)
            ax.grid(True, which="both", lw=0.35, alpha=0.28)
            ax.set_xticks([0.0, 1.0])
            ax.set_xticklabels(["M0", "M100"])
            if section == 1:
                ax.set_title(f"{kind} frequency by Morph endpoint", fontsize=11)
            if col == 0:
                ax.set_ylabel(f"S{section}\nHz")
            roots_by_corner = _section_kind_roots(corners, sr, section, kind)
            for q_label, left_label, right_label, linestyle, y_jitter in q_lines:
                left_roots = roots_by_corner[left_label]
                right_roots = roots_by_corner[right_label]
                max_len = max(len(left_roots), len(right_roots))
                for idx in range(max_len):
                    xs: list[float] = []
                    ys: list[float] = []
                    radii: list[float] = []
                    for x, roots in ((0.0, left_roots), (1.0, right_roots)):
                        if idx >= len(roots):
                            continue
                        root = roots[idx]
                        xs.append(x)
                        ys.append(root.freq_hz)
                        radii.append(root.radius)
                    if len(xs) == 2:
                        ax.plot(xs, ys, color=color, lw=1.25, linestyle=linestyle, alpha=0.85)
                    for x, y, radius in zip(xs, ys, radii):
                        marker = "^" if kind == "pole" else "v"
                        ax.scatter(
                            [x],
                            [y],
                            marker=marker,
                            s=42 + 260 * max(0.0, radius - 0.75),
                            color=color,
                            edgecolor="white",
                            linewidth=0.6,
                            zorder=4,
                        )
                        ax.annotate(
                            f"{y:.0f}\nr={radius:.3f}",
                            xy=(x, y),
                            xytext=(5 if x < 0.5 else -5, 3 + 7 * y_jitter),
                            textcoords="offset points",
                            ha="left" if x < 0.5 else "right",
                            va="bottom",
                            fontsize=6.2,
                            color=color,
                        )
            ax.text(
                0.02,
                0.04,
                "solid Q0 / dashed Q100",
                transform=ax.transAxes,
                fontsize=6.5,
                color="#666666",
            )
    fig.suptitle(f"{title}: root-frequency schematic by section", y=0.992, fontsize=14)
    fig.tight_layout(rect=(0.03, 0.02, 0.99, 0.975))
    fig.savefig(out_path)
    plt.close(fig)


def plot_cascade(cascade_curves: dict[str, np.ndarray], freqs: np.ndarray, corners: dict[str, dict], out_path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(11.0, 5.7), dpi=160)
    fig.patch.set_facecolor("#f7f3ea")
    ax.set_facecolor("#fffaf0")
    colors = {
        "M0_Q0": "#111111",
        "M100_Q0": "#2878b5",
        "M0_Q100": "#d35d2e",
        "M100_Q100": "#6f4dbf",
    }
    for label in CORNER_ORDER:
        curve = cascade_curves[label]
        max_r = corners[label]["max_pole_radius"]
        ax.semilogx(freqs, curve, lw=2.0, color=colors[label], label=f"{label}  max pole r={max_r:.5f}")
    ax.axhline(0.0, color="#777777", lw=0.8, alpha=0.6)
    ax.set_xlim(FREQ_MIN_HZ, FREQ_MAX_HZ)
    vals = np.concatenate(list(cascade_curves.values()))
    ax.set_ylim(max(-90.0, float(np.percentile(vals, 1.0)) - 5.0), min(90.0, float(np.percentile(vals, 99.0)) + 5.0))
    ax.grid(True, which="both", lw=0.4, alpha=0.3)
    ax.set_title(f"{title}: full cascade at four corners")
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("magnitude (dB)")
    ax.legend(loc="best", fontsize=8, frameon=True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def plot_zplane(corners: dict[str, dict], sr: float, out_path: Path, title: str) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(10.0, 10.0), dpi=160)
    fig.patch.set_facecolor("#f7f3ea")
    theta = np.linspace(0.0, 2.0 * np.pi, 720)
    section_colors = plt.cm.tab10(np.linspace(0.0, 1.0, ff.NUM_STAGES))
    for ax, label in zip(axes.ravel(), CORNER_ORDER):
        ax.plot(np.cos(theta), np.sin(theta), color="#444444", lw=0.9)
        ax.axhline(0.0, color="#999999", lw=0.6, alpha=0.5)
        ax.axvline(0.0, color="#999999", lw=0.6, alpha=0.5)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(-1.08, 1.08)
        ax.set_ylim(-1.08, 1.08)
        ax.set_facecolor("#fffaf0")
        ax.grid(True, lw=0.35, alpha=0.25)
        ax.set_title(label)
        for section, bq in enumerate(corners[label]["biquad"], start=1):
            color = section_colors[section - 1]
            for root in roots_for_section(section, tuple(map(float, bq)), sr):
                x = root.radius * math.cos(root.angle_rad)
                y = root.radius * math.sin(root.angle_rad)
                marker = "^" if root.kind == "pole" else "o"
                face = color if root.kind == "pole" else "none"
                ax.scatter([x], [y], marker=marker, s=46, facecolors=face, edgecolors=color, linewidth=1.2)
                ax.text(x, y, f" {section}", fontsize=7, color=color, ha="left", va="center")
                if root.imag_sign != 0:
                    ax.scatter([x], [-y], marker=marker, s=30, facecolors=face, edgecolors=color, linewidth=1.0, alpha=0.55)
    handles = []
    for section, color in enumerate(section_colors, start=1):
        handles.append(plt.Line2D([0], [0], marker="o", color="none", markeredgecolor=color, markerfacecolor=color, label=f"S{section}"))
    fig.legend(handles=handles, loc="lower center", ncol=6, fontsize=8, frameon=False)
    fig.suptitle(f"{title}: z-plane roots by section", y=0.985, fontsize=14)
    fig.tight_layout(rect=(0.02, 0.04, 0.98, 0.965))
    fig.savefig(out_path)
    plt.close(fig)


def write_csv(rows: list[dict], out_path: Path) -> None:
    fieldnames = [
        "corner",
        "morph",
        "q",
        "section",
        "root_kind",
        "root_freq_hz",
        "root_radius",
        "root_angle_rad",
        "root_imag_sign",
        "section_peak_db",
        "section_peak_hz",
        "section_min_db",
        "section_min_hz",
        "dc_db",
        "nyquist_side_db",
        "max_pole_radius_at_corner",
        "unstable_mask",
        "nonfinite_mask",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def summarize_corner(cascade_curve: np.ndarray, freqs: np.ndarray) -> str:
    peak_i = int(np.argmax(cascade_curve))
    min_i = int(np.argmin(cascade_curve))
    return (
        f"peak {cascade_curve[peak_i]:+.1f} dB at {freqs[peak_i]:.0f} Hz; "
        f"minimum {cascade_curve[min_i]:+.1f} dB at {freqs[min_i]:.0f} Hz"
    )


def write_readme(
    out_path: Path,
    title: str,
    source: Path,
    sr: float,
    corners: dict[str, dict],
    cascade_curves: dict[str, np.ndarray],
    freqs: np.ndarray,
) -> None:
    lines = [
        f"# {title} engineering schematic",
        "",
        "Study-only derived plots. This report does not print packed words or coefficient tables.",
        "",
        "## DSP interpretation",
        "",
        "- OBSERVED: The local cartridge is a `compiled-v1` packed body with four corner coefficient sets over Morph and Q.",
        "- OBSERVED: The runtime probe returns six second-order sections per corner. Each section has a numerator quadratic, a denominator quadratic, and gain folded into the numerator.",
        "- OBSERVED: Denominator roots are poles. Numerator roots are zeros.",
        "- OBSERVED: Runtime interpolation is Morph/Q bilinear over packed body data before the probed biquad coefficients are used.",
        "- INFERRED: Section number is best treated as correspondence across the four corners, not as a low-to-high frequency ordering. For a linear time-invariant cascade, section order does not change the magnitude response.",
        "",
        "## Files",
        "",
        "- `talking_hedz_engineering_schematic.png`: 6 sections x 4 corners; one section transfer function per cell.",
        "- `talking_hedz_root_frequency_schematic.png`: per-section pole/zero frequency movement from M0 to M100, split by Q0/Q100.",
        "- `talking_hedz_cascade_corners.png`: product of all six sections at each corner.",
        "- `talking_hedz_zplane_roots.png`: pole/zero locations for all six sections at all four corners.",
        "- `talking_hedz_section_roots.csv`: derived root Hz/radius and response metrics; no packed words.",
        "",
        "## Corner response summary",
        "",
    ]
    for label in CORNER_ORDER:
        probe = corners[label]
        lines.append(
            f"- {label}: {summarize_corner(cascade_curves[label], freqs)}; "
            f"max pole radius {probe['max_pole_radius']:.6f}; "
            f"unstable mask {probe['unstable_mask']}; nonfinite mask {probe['nonfinite_mask']}."
        )
    lines.extend(
        [
            "",
            "## Source",
            "",
            f"- Cartridge: `{source}`",
            f"- Runtime sample rate: `{sr}`",
            f"- Runtime FFI: `{ff.lib_path()}`",
            "",
        ]
    )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cartridge",
        type=Path,
        default=ROOT / "juce-shell" / "assets" / "cartridges" / "P2k_013_talking_hedz.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "dev" / "tmp" / "talking_hedz_schematic",
    )
    parser.add_argument("--points", type=int, default=2048)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    body, sr, name = load_body_bytes(args.cartridge)
    if not ff.available():
        raise RuntimeError("trench_core.dll is required; build target/release/trench_core.dll")

    freqs = np.logspace(math.log10(FREQ_MIN_HZ), math.log10(FREQ_MAX_HZ), int(args.points))
    corners = probe_corners(body)
    rows, section_curves, cascade_curves = section_summary_rows(corners, freqs, sr)

    plot_section_schematic(
        corners,
        section_curves,
        freqs,
        sr,
        out_dir / "talking_hedz_engineering_schematic.png",
        name,
    )
    plot_root_frequency_schematic(corners, sr, out_dir / "talking_hedz_root_frequency_schematic.png", name)
    plot_cascade(cascade_curves, freqs, corners, out_dir / "talking_hedz_cascade_corners.png", name)
    plot_zplane(corners, sr, out_dir / "talking_hedz_zplane_roots.png", name)
    write_csv(rows, out_dir / "talking_hedz_section_roots.csv")
    write_readme(out_dir / "README.md", name, args.cartridge, sr, corners, cascade_curves, freqs)

    print(f"wrote {out_dir}")
    for label in CORNER_ORDER:
        print(f"{label}: {summarize_corner(cascade_curves[label], freqs)}")


if __name__ == "__main__":
    main()
