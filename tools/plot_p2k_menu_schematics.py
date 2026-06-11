#!/usr/bin/env python3
"""Batch P2K menu reference pole/zero schematics.

Study-only. Reads local 240-byte P2K reference bodies from ref/presets,
probes them through the shipped trench-core packed runtime, and writes
derived plots/tables:

- section transfer functions by corner
- pole/zero root-frequency movement by section
- z-plane root positions by corner
- full-cascade corner responses
- 17x17 Morph/Secondary stability audit summary

The output does not print packed words or biquad coefficient tables.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi as ff  # noqa: E402
from tools.plot_talking_hedz_schematic import (  # noqa: E402
    CORNER_ORDER,
    FREQ_MIN_HZ,
    FREQ_MAX_HZ,
    plot_cascade,
    plot_root_frequency_schematic,
    plot_section_schematic,
    plot_zplane,
    probe_corners,
    section_summary_rows,
    summarize_corner,
    write_csv as write_roots_csv,
)

P2K_DIR = ROOT / "ref" / "presets"
MANIFEST = P2K_DIR / "P2K_MANIFEST.json"
DEFAULT_OUT = ROOT / "dev" / "tmp" / "p2k_menu_schematics"
DEFAULT_IDS = "33-49"
SR = 39_062.5


def parse_id_spec(spec: str) -> set[int]:
    selected: set[int] = set()
    for part in spec.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            left, right = item.split("-", 1)
            selected.update(range(int(left), int(right) + 1))
        else:
            selected.add(int(item))
    return selected


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "reference"


def load_manifest_entries(ids: set[int]) -> list[dict[str, object]]:
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = []
    for entry in doc.get("entries", []):
        entry_id = str(entry["id"])
        number = int(entry_id.split("_", 1)[1])
        if number not in ids:
            continue
        path = P2K_DIR / str(entry["file"])
        if not path.exists():
            raise FileNotFoundError(path)
        entries.append(
            {
                "number": number,
                "id": entry_id,
                "name": str(entry.get("name") or path.stem),
                "file": path,
                "sha256": str(entry.get("sha256") or ""),
            }
        )
    entries.sort(key=lambda row: int(row["number"]))
    missing = sorted(ids.difference(int(row["number"]) for row in entries))
    if missing:
        raise FileNotFoundError(f"missing P2K ids in manifest: {missing}")
    return entries


def audit_grid(body: bytes, steps: int) -> dict[str, object]:
    axis = np.linspace(0.0, 1.0, int(steps))
    points = 0
    unstable_rows = 0
    nonfinite_rows = 0
    max_radius = 0.0
    max_radius_at = (0.0, 0.0)
    for secondary in axis:
        for morph in axis:
            probe = ff.packed_probe(body, float(morph), float(secondary))
            points += 1
            unstable_rows += int(probe["unstable_mask"]).bit_count()
            nonfinite_rows += int(probe["nonfinite_mask"]).bit_count()
            radius = float(probe["max_pole_radius"])
            if radius > max_radius:
                max_radius = radius
                max_radius_at = (float(morph), float(secondary))
    return {
        "grid_steps": int(steps),
        "grid_points": points,
        "unstable_rows": unstable_rows,
        "nonfinite_rows": nonfinite_rows,
        "max_pole_radius": max_radius,
        "max_pole_radius_morph": max_radius_at[0],
        "max_pole_radius_secondary": max_radius_at[1],
        "stable": unstable_rows == 0 and nonfinite_rows == 0,
    }


def root_counts(rows: list[dict]) -> dict[str, int]:
    counts = {"pole_roots_in_band": 0, "zero_roots_in_band": 0}
    for row in rows:
        if row.get("root_kind") == "pole":
            counts["pole_roots_in_band"] += 1
        elif row.get("root_kind") == "zero":
            counts["zero_roots_in_band"] += 1
    return counts


def write_reference_summary(
    path: Path,
    title: str,
    source: Path,
    sha256: str,
    corners: dict[str, dict],
    cascade_curves: dict[str, np.ndarray],
    freqs: np.ndarray,
    audit: dict[str, object],
) -> None:
    lines = [
        f"# {title} pole-zero schematic",
        "",
        "Study-only derived plots. No packed words or coefficient tables are emitted.",
        "",
        "## Claims",
        "",
        "- OBSERVED: Source is one 240-byte packed P2K reference body.",
        "- OBSERVED: `trench_core.dll` `packed_probe` returns six second-order sections at each probed Morph/Secondary coordinate.",
        "- OBSERVED: Denominator roots are plotted as poles; numerator roots are plotted as zeros.",
        "- INFERRED: Section index is interpolation correspondence across corners, not a fixed spectral role.",
        "",
        "## Files",
        "",
        "- `engineering_schematic.png`: section transfer functions by corner.",
        "- `root_frequency_schematic.png`: pole/zero frequency movement by section.",
        "- `cascade_corners.png`: full cascade at the four corners.",
        "- `zplane_roots.png`: root positions by corner.",
        "- `section_roots.csv`: derived root Hz/radius and response metrics.",
        "",
        "## Packed-runtime audit",
        "",
        f"- Grid: `{audit['grid_steps']}x{audit['grid_steps']}` Morph/Secondary.",
        f"- Strict `packed_probe` gate pass: `{audit['stable']}`.",
        f"- Unstable rows: `{audit['unstable_rows']}`.",
        f"- Nonfinite rows: `{audit['nonfinite_rows']}`.",
        f"- Max pole radius: `{float(audit['max_pole_radius']):.8f}` at "
        f"M=`{float(audit['max_pole_radius_morph']):.3f}`, "
        f"Secondary=`{float(audit['max_pole_radius_secondary']):.3f}`.",
        "- Gate definition: the shipped probe flags pole radius `>= 1.0`. "
        "Exact unit-radius reference rows are therefore study evidence, not "
        "permission for a production clean-room body to fail the strict gate.",
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
            f"- File: `{source.relative_to(ROOT).as_posix()}`",
            f"- SHA-256: `{sha256}`" if sha256 else "- SHA-256: `not recorded in manifest`",
            f"- Runtime sample rate used for root-frequency conversion: `{SR}`",
            f"- Runtime FFI: `{ff.lib_path()}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_index(out_dir: Path, rows: list[dict[str, object]]) -> None:
    lines = [
        "# P2K Menu Pole-Zero Schematics",
        "",
        "Study-only derived plots for local P2K 240-byte references.",
        "No packed words or coefficient tables are emitted.",
        "",
        "## Summary",
        "",
        "| id | reference | strict gate | max pole radius | poles | zeros | packet |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        rel = Path(str(row["directory"])).relative_to(out_dir).as_posix()
        title = str(row["title"])
        lines.append(
            f"| `{row['id']}` | {title} | `{row['stable']}` | "
            f"{float(row['max_pole_radius']):.8f} | {row['pole_roots_in_band']} | "
            f"{row['zero_roots_in_band']} | [{rel}/README.md]({rel}/README.md) |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- OBSERVED: these references contain first-class numerator-zero structure.",
            "- INFERRED: the reusable clean-room idea is topology class plus motion and gain budget, not copied packed data.",
            "- UNKNOWN: whether any one clean-room generator is sufficient until a generated body is packed and audited through the shipped runtime.",
            "",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")

    cards = []
    for row in rows:
        rel = Path(str(row["directory"])).relative_to(out_dir).as_posix()
        title = html.escape(str(row["title"]))
        cards.append(
            f"""
            <section>
              <h2>{html.escape(str(row['id']))} - {title}</h2>
              <p>strict packed_probe gate={html.escape(str(row['stable']))}; max pole radius={float(row['max_pole_radius']):.8f}</p>
              <a href="{rel}/README.md">reference report</a>
              <img src="{rel}/engineering_schematic.png" alt="{title} engineering schematic">
              <img src="{rel}/root_frequency_schematic.png" alt="{title} root frequency schematic">
              <img src="{rel}/cascade_corners.png" alt="{title} cascade corners">
              <img src="{rel}/zplane_roots.png" alt="{title} z-plane roots">
            </section>
            """
        )
    html_doc = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>P2K Menu Pole-Zero Schematics</title>
<style>
body {{ margin: 0; background: #f7f3ea; color: #171a17; font: 15px/1.45 system-ui, sans-serif; }}
header {{ padding: 24px 32px 14px; border-bottom: 1px solid #cbc3b5; }}
main {{ max-width: 1400px; margin: 0 auto; padding: 22px 28px 60px; }}
h1 {{ margin: 0 0 8px; font-size: 28px; }}
h2 {{ margin: 0 0 6px; font-size: 19px; }}
section {{ margin: 0 0 34px; padding-bottom: 24px; border-bottom: 1px solid #d8d0c2; }}
p {{ margin: 4px 0 8px; color: #555b54; }}
a {{ color: #2459a6; }}
img {{ display: block; width: 100%; max-width: 100%; margin: 12px 0; border: 1px solid #cfc6b8; background: #fffaf0; }}
</style>
<body>
<header>
  <h1>P2K Menu Pole-Zero Schematics</h1>
  <p>Study-only derived plots. Packed words and coefficient tables are not shown.</p>
  <p><a href="README.md">Markdown summary</a> | <a href="schematic_summary.csv">CSV summary</a></p>
</header>
<main>
{''.join(cards)}
</main>
</body>
</html>
"""
    (out_dir / "index.html").write_text(html_doc, encoding="utf-8")


def process_entry(entry: dict[str, object], out_root: Path, freqs: np.ndarray, grid_steps: int) -> dict[str, object]:
    source = Path(entry["file"])
    body = source.read_bytes()
    if len(body) != ff.BODY_BYTES:
        raise ValueError(f"{source}: expected {ff.BODY_BYTES} bytes, got {len(body)}")

    title = f"{entry['id']} {entry['name']}"
    out_dir = out_root / f"{int(entry['number']):03d}_{slugify(str(entry['name']))}"
    out_dir.mkdir(parents=True, exist_ok=True)

    corners = probe_corners(body)
    rows, section_curves, cascade_curves = section_summary_rows(corners, freqs, SR)
    audit = audit_grid(body, grid_steps)
    counts = root_counts(rows)

    plot_section_schematic(corners, section_curves, freqs, SR, out_dir / "engineering_schematic.png", title)
    plot_root_frequency_schematic(corners, SR, out_dir / "root_frequency_schematic.png", title)
    plot_cascade(cascade_curves, freqs, corners, out_dir / "cascade_corners.png", title)
    plot_zplane(corners, SR, out_dir / "zplane_roots.png", title)
    write_roots_csv(rows, out_dir / "section_roots.csv")
    write_reference_summary(
        out_dir / "README.md",
        title,
        source,
        str(entry.get("sha256") or ""),
        corners,
        cascade_curves,
        freqs,
        audit,
    )

    summary = {
        "id": entry["id"],
        "number": int(entry["number"]),
        "name": entry["name"],
        "title": title,
        "source": source.relative_to(ROOT).as_posix(),
        "directory": str(out_dir),
        **audit,
        **counts,
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", default=DEFAULT_IDS, help="P2K ids, e.g. 33-49 or 13,33-49")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--points", type=int, default=2048)
    parser.add_argument("--grid", type=int, default=17)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not ff.available():
        raise RuntimeError("trench_core.dll is required; build target/release/trench_core.dll")

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    freqs = np.logspace(math.log10(FREQ_MIN_HZ), math.log10(FREQ_MAX_HZ), int(args.points))
    entries = load_manifest_entries(parse_id_spec(str(args.ids)))

    summaries = []
    for entry in entries:
        summary = process_entry(entry, out_dir, freqs, int(args.grid))
        summaries.append(summary)
        print(
            f"{summary['id']} {summary['name']}: strict_gate={summary['stable']} "
            f"max_r={float(summary['max_pole_radius']):.8f} "
            f"poles={summary['pole_roots_in_band']} zeros={summary['zero_roots_in_band']}"
        )

    write_csv(out_dir / "schematic_summary.csv", summaries)
    write_index(out_dir, summaries)
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
