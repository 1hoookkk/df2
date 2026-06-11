#!/usr/bin/env python3
"""Study-only P2K template/foundation stage plots and reuse checks.

Reads local 240-byte P2K reference bodies, decodes them through the shipped
packed runtime, and emits derived plots/tables:

- six-section x four-corner engineering plots for P2k_033..P2k_049;
- exact row-reuse counts against P2k_000..P2k_032, without dumping words;
- nearest response-shape matches from iconic rows to template rows.

Clean-room boundary: this script never writes packed words, coefficient tables,
or endpoint bodies. It only writes derived plots, row labels, and aggregate
similarity metrics for local study.
"""
from __future__ import annotations

import csv
import html
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402

P2K_DIR = ROOT / "ref" / "presets"
OUT = ROOT / "dev" / "tmp" / "p2k_template_foundation_stages"

FREQS = np.geomspace(40.0, 16_000.0, 520)
COMPARE_MASK = (FREQS >= 80.0) & (FREQS <= 12_000.0)
SR = 39_062.5
EPS = 1e-20

CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
CORNER_POS = {
    "M0_Q0": (0.0, 0.0),
    "M100_Q0": (1.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q100": (1.0, 1.0),
}

TEMPLATE_IDS = tuple(range(33, 50))
ICONIC_IDS = tuple(range(0, 33))

DISPLAY_NAMES = {
    "P2k_033_classic_4_lpf": "4 Pole Lowpass / Classic 4 LPF",
    "P2k_034_smooth_2_lpf": "2 Pole Lowpass / Smooth 2 LPF",
    "P2k_035_steeper_6_lpf": "6 Pole Lowpass / Steeper 6 LPF",
    "P2k_036_shallow_2_hpf": "2 Pole Highpass / Shallow 2 HPF",
    "P2k_037_deeper_4_hpf": "4 Pole Highpass / Deeper 4 HPF",
    "P2k_038_band_pass1_2_bpf": "2 Pole Bandpass / Band Pass 1",
    "P2k_039_band_pass2_4_bpf": "4 Pole Bandpass / Band Pass 2",
    "P2k_040_contraband_6_bpf": "Contrary Bandpass / Contraband",
    "P2k_041_swept1oct_6_eq": "Swept EQ 1 Octave",
    "P2k_042_swept2_to_1oct_6_eq": "Swept EQ 2-to-1 Octave",
    "P2k_043_swept3_to_1oct_6_eq": "Swept EQ 3-to-1 Octave",
    "P2k_044_phazeshift1_6_pha": "Phaser 1 / Phaze Shift 1",
    "P2k_045_phazeshift2_6_pha": "Phaser 2 / Phaze Shift 2",
    "P2k_046_blissbatz_6_pha": "Bat Phaser / Bliss Batz",
    "P2k_047_flangerlite_6_flg": "Flanger Lite",
    "P2k_048_aah_ay_eeh_6_vow": "Vocal Ah-Ay-Ee",
    "P2k_049_ooh_to_aah_6_vow": "Vocal Oo-Ah",
}


@dataclass(frozen=True)
class Signature:
    preset: str
    corner: str
    stage: int
    curve: np.ndarray
    norm_curve: np.ndarray


def preset_paths(ids: tuple[int, ...]) -> list[Path]:
    out = []
    for number in ids:
        matches = sorted(P2K_DIR.glob(f"P2k_{number:03d}_*.bin"))
        if not matches:
            raise FileNotFoundError(f"missing P2k_{number:03d}_*.bin in {P2K_DIR}")
        out.append(matches[0])
    return out


def body_rows(body: bytes) -> dict[str, list[tuple[int, ...]]]:
    if len(body) != trench_ffi.BODY_BYTES:
        raise ValueError(f"body must be {trench_ffi.BODY_BYTES} bytes")
    out: dict[str, list[tuple[int, ...]]] = {}
    offset = 0
    for corner in CORNER_ORDER:
        rows = []
        for _stage in range(trench_ffi.NUM_STAGES):
            words = []
            for _coeff in range(trench_ffi.NUM_COEFFS):
                words.append(int.from_bytes(body[offset:offset + 2], "little"))
                offset += 2
            rows.append(tuple(words))
        out[corner] = rows
    return out


def response_db_biquad(bq: tuple[float, float, float, float, float]) -> np.ndarray:
    b0, b1, b2, a1, a2 = bq
    z1 = np.exp(-1j * 2.0 * np.pi * FREQS / SR)
    z2 = z1 * z1
    h = (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), EPS))


def response_db_cascade(biquads: list[tuple[float, float, float, float, float]]) -> np.ndarray:
    z1 = np.exp(-1j * 2.0 * np.pi * FREQS / SR)
    z2 = z1 * z1
    h = np.ones_like(FREQS, dtype=np.complex128)
    for b0, b1, b2, a1, a2 in biquads:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), EPS))


def normalize_curve(curve: np.ndarray) -> np.ndarray:
    return curve - float(np.mean(curve[COMPARE_MASK]))


def rms_db(a: np.ndarray, b: np.ndarray) -> float:
    d = a[COMPARE_MASK] - b[COMPARE_MASK]
    return float(np.sqrt(np.mean(d * d)))


def roots_for_biquad(bq: tuple[float, float, float, float, float]) -> list[dict[str, float | str]]:
    b0, b1, b2, a1, a2 = bq
    roots = []
    for kind, coeffs in (("zero", (b0, b1, b2)), ("pole", (1.0, a1, a2))):
        if abs(coeffs[0]) < 1e-18:
            continue
        for root in np.roots(np.asarray(coeffs, dtype=np.float64)):
            angle = float(np.angle(root))
            if abs(root.imag) > 1e-8 and angle < 0.0:
                continue
            roots.append({
                "kind": kind,
                "freq_hz": abs(angle) * SR / (2.0 * math.pi),
                "radius": float(abs(root)),
            })
    return roots


def probe_body(body: bytes) -> dict[str, dict]:
    return {
        corner: trench_ffi.packed_probe(body, *CORNER_POS[corner])
        for corner in CORNER_ORDER
    }


def body_signatures(path: Path) -> list[Signature]:
    body = path.read_bytes()
    corners = probe_body(body)
    out: list[Signature] = []
    for corner in CORNER_ORDER:
        for stage, bq in enumerate(corners[corner]["biquad"], start=1):
            curve = response_db_biquad(tuple(map(float, bq)))
            out.append(Signature(path.stem, corner, stage, curve, normalize_curve(curve)))
    return out


def plot_template(path: Path) -> dict[str, object]:
    body = path.read_bytes()
    corners = probe_body(body)
    title = DISPLAY_NAMES.get(path.stem, path.stem)
    image_name = f"{path.stem}_stages.png"
    image_path = OUT / image_name
    csv_rows = []

    fig, axes = plt.subplots(
        trench_ffi.NUM_STAGES,
        len(CORNER_ORDER),
        figsize=(17.5, 13.8),
        dpi=145,
        sharex=True,
    )
    fig.patch.set_facecolor("#fbf8ef")
    fig.suptitle(title, fontsize=15, y=0.995)

    for col, corner in enumerate(CORNER_ORDER):
        axes[0, col].set_title(corner.replace("_", " "), fontsize=10)
        biquads = [tuple(map(float, bq)) for bq in corners[corner]["biquad"]]
        for row, bq in enumerate(biquads):
            stage = row + 1
            ax = axes[row, col]
            curve = response_db_biquad(bq)
            ax.semilogx(FREQS, curve, color="#1d1d1d", lw=1.25)
            ax.axhline(0.0, color="#777777", lw=0.55, alpha=0.45)
            ax.grid(True, which="both", lw=0.35, alpha=0.23)
            ax.set_facecolor("#fffdf7")
            ax.set_xlim(float(FREQS[0]), float(FREQS[-1]))
            lo = float(np.nanpercentile(curve, 1.0)) - 4.0
            hi = float(np.nanpercentile(curve, 99.0)) + 4.0
            if hi - lo < 14.0:
                mid = 0.5 * (lo + hi)
                lo = mid - 7.0
                hi = mid + 7.0
            ax.set_ylim(lo, hi)
            ax.text(0.02, 0.83, f"S{stage}", transform=ax.transAxes, weight="bold", fontsize=8)
            if col == 0:
                ax.set_ylabel("dB", fontsize=8)
            if row == trench_ffi.NUM_STAGES - 1:
                ax.set_xlabel("Hz", fontsize=8)
            roots = roots_for_biquad(bq)
            for root in roots:
                freq = float(root["freq_hz"])
                if not (FREQS[0] <= freq <= FREQS[-1]):
                    continue
                y = float(curve[int(np.argmin(np.abs(FREQS - freq)))])
                if root["kind"] == "pole":
                    ax.scatter([freq], [y], marker="^", s=56, color="#b6302f", edgecolor="white", lw=0.45, zorder=5)
                else:
                    ax.scatter([freq], [y], marker="v", s=56, color="#275aa8", edgecolor="white", lw=0.45, zorder=5)
            peak_i = int(np.argmax(curve))
            min_i = int(np.argmin(curve))
            csv_rows.append({
                "preset": path.stem,
                "display": title,
                "corner": corner,
                "stage": stage,
                "stage_peak_hz": round(float(FREQS[peak_i]), 4),
                "stage_peak_db": round(float(curve[peak_i]), 4),
                "stage_min_hz": round(float(FREQS[min_i]), 4),
                "stage_min_db": round(float(curve[min_i]), 4),
                "max_pole_radius_at_corner": round(float(corners[corner]["max_pole_radius"]), 8),
                "unstable_mask": int(corners[corner]["unstable_mask"]),
                "nonfinite_mask": int(corners[corner]["nonfinite_mask"]),
            })

    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.985))
    fig.savefig(image_path)
    plt.close(fig)

    cascade_path = OUT / f"{path.stem}_cascade_corners.png"
    fig2, ax2 = plt.subplots(figsize=(8.5, 4.8), dpi=150)
    fig2.patch.set_facecolor("#fbf8ef")
    ax2.set_facecolor("#fffdf7")
    for corner in CORNER_ORDER:
        biquads = [tuple(map(float, bq)) for bq in corners[corner]["biquad"]]
        curve = response_db_cascade(biquads)
        ax2.semilogx(FREQS, normalize_curve(curve), lw=1.5, label=corner.replace("_", " "))
    ax2.axhline(0.0, color="#777777", lw=0.6, alpha=0.5)
    ax2.set_title(f"{title}: normalized cascade corners", fontsize=11)
    ax2.set_xlabel("Hz")
    ax2.set_ylabel("normalized dB")
    ax2.grid(True, which="both", lw=0.35, alpha=0.25)
    ax2.legend(fontsize=7)
    fig2.tight_layout()
    fig2.savefig(cascade_path)
    plt.close(fig2)

    return {
        "preset": path.stem,
        "display": title,
        "stage_image": image_name,
        "cascade_image": cascade_path.name,
        "rows": csv_rows,
    }


def exact_reuse_rows(template_paths: list[Path], iconic_paths: list[Path]) -> list[dict[str, object]]:
    template_index: dict[tuple[int, ...], list[tuple[str, str, int]]] = defaultdict(list)
    for path in template_paths:
        rows_by_corner = body_rows(path.read_bytes())
        for corner, rows in rows_by_corner.items():
            for stage, row in enumerate(rows, start=1):
                template_index[row].append((path.stem, corner, stage))

    rows = []
    for path in iconic_paths:
        rows_by_corner = body_rows(path.read_bytes())
        for corner, stage_rows in rows_by_corner.items():
            for stage, row in enumerate(stage_rows, start=1):
                for template, template_corner, template_stage in template_index.get(row, []):
                    rows.append({
                        "iconic_preset": path.stem,
                        "iconic_corner": corner,
                        "iconic_stage": stage,
                        "template_preset": template,
                        "template_corner": template_corner,
                        "template_stage": template_stage,
                    })
    return rows


def nearest_response_rows(template_paths: list[Path], iconic_paths: list[Path]) -> list[dict[str, object]]:
    templates = [sig for path in template_paths for sig in body_signatures(path)]
    iconics = [sig for path in iconic_paths for sig in body_signatures(path)]
    out = []
    for iconic in iconics:
        best = min(templates, key=lambda tmpl: rms_db(iconic.norm_curve, tmpl.norm_curve))
        score = rms_db(iconic.norm_curve, best.norm_curve)
        out.append({
            "iconic_preset": iconic.preset,
            "iconic_corner": iconic.corner,
            "iconic_stage": iconic.stage,
            "nearest_template": best.preset,
            "nearest_template_corner": best.corner,
            "nearest_template_stage": best.stage,
            "normalized_rms_db": round(score, 5),
            "strength": "exact_like" if score < 0.75 else "strong" if score < 2.0 else "family" if score < 4.0 else "weak",
        })
    return out


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    templates: list[dict[str, object]],
    exact_rows: list[dict[str, object]],
    nearest_rows: list[dict[str, object]],
) -> None:
    exact_by_iconic = Counter(row["iconic_preset"] for row in exact_rows)
    exact_by_template = Counter(row["template_preset"] for row in exact_rows)
    strong_by_iconic = Counter(
        row["iconic_preset"]
        for row in nearest_rows
        if row["strength"] in {"exact_like", "strong"}
    )
    strong_by_template = Counter(
        row["nearest_template"]
        for row in nearest_rows
        if row["strength"] in {"exact_like", "strong"}
    )
    strength_counts = Counter(row["strength"] for row in nearest_rows)

    lines = [
        "# P2K Template Foundation Stage Study",
        "",
        "Study-only clean-room report. Derived plots and aggregate row-label matches only.",
        "No packed words, coefficient tables, endpoint bodies, or reconstructable vendor data are emitted.",
        "",
        "## Answer",
        "",
        "- Exact packed-row reuse is counted separately from response-shape similarity.",
        "- If a row has an exact match, that is strong local evidence of direct foundation reuse.",
        "- If a row only has a low response RMS, that is evidence of shared DSP topology, not byte-level reuse.",
        "",
        "## Exact Row-Reuse Summary",
        "",
        f"- Exact iconic-to-template row matches found: `{len(exact_rows)}`.",
        "",
    ]
    if exact_by_iconic:
        lines += ["Top iconic bodies by exact template-row reuse:", ""]
        for preset, count in exact_by_iconic.most_common(12):
            lines.append(f"- `{preset}`: `{count}` exact row matches")
        lines += ["", "Template rows most often reused exactly:", ""]
        for preset, count in exact_by_template.most_common(12):
            lines.append(f"- `{preset}`: `{count}` exact row matches")
    else:
        lines.append("No exact packed-row reuse was found between P2k_000..032 and P2k_033..049.")

    lines += [
        "",
        "## Response-Shape Similarity Summary",
        "",
        "Nearest template-stage strength counts:",
        "",
    ]
    for strength in ("exact_like", "strong", "family", "weak"):
        lines.append(f"- `{strength}`: `{strength_counts[strength]}` iconic stage-corners")
    lines += ["", "Iconic bodies with the most strong template-stage neighbors:", ""]
    for preset, count in strong_by_iconic.most_common(16):
        lines.append(f"- `{preset}`: `{count}` strong/exact-like stage-corners")
    lines += ["", "Template foundations most often selected by strong neighbors:", ""]
    for preset, count in strong_by_template.most_common(16):
        label = DISPLAY_NAMES.get(str(preset), str(preset))
        lines.append(f"- `{preset}` ({label}): `{count}` strong/exact-like neighbors")

    lines += [
        "",
        "## Template Stage Plots",
        "",
    ]
    for item in templates:
        display = html.escape(str(item["display"]))
        stage_image = html.escape(str(item["stage_image"]))
        cascade_image = html.escape(str(item["cascade_image"]))
        lines += [
            f"### {display}",
            "",
            f"![{display} stages]({stage_image})",
            "",
            f"![{display} cascade]({cascade_image})",
            "",
        ]

    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows = []
    for preset, count in exact_by_iconic.items():
        rows.append({
            "iconic_preset": preset,
            "exact_template_row_matches": count,
            "strong_or_exact_like_response_neighbors": strong_by_iconic[preset],
        })
    for preset in strong_by_iconic:
        if preset not in exact_by_iconic:
            rows.append({
                "iconic_preset": preset,
                "exact_template_row_matches": 0,
                "strong_or_exact_like_response_neighbors": strong_by_iconic[preset],
            })
    rows.sort(key=lambda row: (-int(row["exact_template_row_matches"]), -int(row["strong_or_exact_like_response_neighbors"]), str(row["iconic_preset"])))
    write_csv(OUT / "iconic_foundation_summary.csv", rows)


def write_html(templates: list[dict[str, object]]) -> None:
    cards = []
    for item in templates:
        title = html.escape(str(item["display"]))
        stage_image = html.escape(str(item["stage_image"]))
        cascade_image = html.escape(str(item["cascade_image"]))
        cards.append(
            f"""
            <section>
              <h2>{title}</h2>
              <img src="{stage_image}" alt="{title} stage plot">
              <img src="{cascade_image}" alt="{title} cascade plot">
            </section>
            """
        )
    doc = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>P2K Template Foundation Stages</title>
<style>
body {{ margin: 0; font: 15px/1.4 system-ui, sans-serif; background: #f6f1e7; color: #1e2320; }}
header {{ padding: 24px 32px 12px; border-bottom: 1px solid #cfc6b6; }}
main {{ padding: 20px 32px 40px; }}
section {{ margin: 0 0 34px; }}
h1 {{ margin: 0 0 8px; font-size: 28px; }}
h2 {{ margin: 0 0 12px; font-size: 20px; }}
img {{ display: block; max-width: 100%; margin: 0 0 14px; border: 1px solid #cfc6b6; background: #fffdf7; }}
a {{ color: #174f88; }}
</style>
<body>
<header>
  <h1>P2K Template Foundation Stages</h1>
  <p>Study-only derived plots. No packed words or coefficients are shown.</p>
  <p><a href="README.md">Read summary</a> | <a href="foundation_reuse_nearest_response.csv">nearest response CSV</a> | <a href="foundation_reuse_exact_rows.csv">exact row-reuse CSV</a></p>
</header>
<main>
{''.join(cards)}
</main>
</body>
</html>
"""
    (OUT / "index.html").write_text(doc, encoding="utf-8")


def main() -> None:
    if not trench_ffi.available():
        raise SystemExit("trench-core packed runtime is unavailable; build target/release/trench_core.dll first")

    OUT.mkdir(parents=True, exist_ok=True)
    template_paths = preset_paths(TEMPLATE_IDS)
    iconic_paths = preset_paths(ICONIC_IDS)

    template_reports = [plot_template(path) for path in template_paths]
    stage_rows = [row for item in template_reports for row in item["rows"]]
    write_csv(OUT / "template_stage_summary.csv", stage_rows)

    exact_rows = exact_reuse_rows(template_paths, iconic_paths)
    write_csv(OUT / "foundation_reuse_exact_rows.csv", exact_rows)

    nearest_rows = nearest_response_rows(template_paths, iconic_paths)
    write_csv(OUT / "foundation_reuse_nearest_response.csv", nearest_rows)

    write_report(template_reports, exact_rows, nearest_rows)
    write_html(template_reports)

    print(f"wrote {OUT}")
    print(f"template plots: {len(template_reports)}")
    print(f"exact row matches: {len(exact_rows)}")


if __name__ == "__main__":
    main()
