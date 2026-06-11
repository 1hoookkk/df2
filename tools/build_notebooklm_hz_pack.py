#!/usr/bin/env python3
"""build_notebooklm_hz_pack.py — assemble a NotebookLM source pack grounded ONLY
in Hz language and the 240-byte packed-words reality.

Sources (clean-room study, structure/frequencies only — NO coefficients):
  dev/tmp/p2k_full_vocabulary/frequency_rails.csv   (measured pole/zero rails, Hz)
  dev/tmp/p2k_full_vocabulary/report.md             (move + row-role vocabulary)
  dev/tmp/p2k_reference_fundamentals/report.md      (foundation construction methods)

Writes the data-driven rails doc + pack manifest. The prose docs are authored
alongside. Output: dev/tmp/notebooklm_hz_pack/.
"""
import csv
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dev" / "tmp" / "notebooklm_hz_pack"
OUT.mkdir(parents=True, exist_ok=True)

rails = list(csv.DictReader((ROOT / "dev/tmp/p2k_full_vocabulary/frequency_rails.csv").open()))


def lands_on_physics(r):
    """True only if the rail sits within a quartertone (50 cents) of a real
    measured frequency (vowel formant / tube partial / metal mode). That match is
    the ONLY non-arbitrary meaning a rail has — not a vibe-band label."""
    try:
        return bool(r.get("nearest_table_label")) and abs(float(r["nearest_table_cents"])) <= 50.0
    except (TypeError, ValueError):
        return False


def hz(r):
    return float(r["rail_hz"])


matched = sorted((r for r in rails if lands_on_physics(r)), key=hz)
unmatched = sorted((r for r in rails if not lands_on_physics(r)), key=lambda r: -int(r["endpoint_hits"]))

lines = [
    "# P2K Frequency Rails (measured Hz)",
    "",
    "Where poles and zeros actually LAND across 50 P2K skins / 200 variant bodies,",
    "measured through the shipped engine (`trench_core.dll`) over a 5x5 Morph x",
    "Secondary grid. Clean-room: landing FREQUENCIES only, no coefficients.",
    "`bodies` = how many of the 50 skins use the rail. `hits` = uses at a body",
    "corner (HOME / AWAY / PUSH HOME / PUSH AWAY).",
    "",
    "No vibe-bands. A rail means something ONLY when it sits on a real measured",
    "frequency (a vowel formant, a tube partial, a metal mode) within a quartertone.",
    "Everything else is just a frequency the engine returns to.",
    "",
    "## Rails that land on known physics (within 50 cents)",
    "",
    "Category = the physical model that makes the resonance. For tubes, open vs",
    "closed is a SUBcategory (not its own category).",
    "",
]


def model_cat(r):
    """(category, subcategory) — physical model is the category; open/closed is a
    tube subcategory."""
    t = r["nearest_table"]
    if t in ("vowel", "klatt", "mullen"):
        return ("vowel formant", "")
    if t == "tube":
        lbl = r["nearest_table_label"]
        return ("tube", "open-open" if lbl.startswith("oo") else "closed-open" if lbl.startswith("co") else "")
    if t == "metal":
        return ("metal mode", "")
    return (t, "")


CAT_ORDER = ["vowel formant", "tube", "metal mode"]
groups = defaultdict(lambda: defaultdict(list))
for r in matched:
    cat, sub = model_cat(r)
    groups[cat][sub].append(r)

for cat in CAT_ORDER + [c for c in groups if c not in CAT_ORDER]:
    if cat not in groups:
        continue
    lines.append(f"### {cat}")
    for sub in sorted(groups[cat]):
        if sub:
            lines.append(f"\n**{sub}**")
        lines += ["", "| Hz | pole/zero | lands on | bodies | hits |", "|---:|---|---|---:|---:|"]
        for r in sorted(groups[cat][sub], key=hz):
            anchor = f"{r['nearest_table_label']} = {r['nearest_table_target_hz']} Hz ({float(r['nearest_table_cents']):+.0f}c)"
            lines.append(f"| {hz(r):.0f} | {r['kind']} | {anchor} | {r['skin_count']} | {r['endpoint_hits']} |")
        lines.append("")

lines += [
    "",
    "## Strongest rails with NO physics match (the engine's own landing spots, by use)",
    "",
    "These are real measured frequencies too — they just don't coincide with a vowel,",
    "tube, or metal frequency. Sorted by how load-bearing they are.",
    "",
    "| Hz | pole/zero | bodies | hits |",
    "|---:|---|---:|---:|",
]
for r in unmatched[:40]:
    lines.append(f"| {hz(r):.0f} | {r['kind']} | {r['skin_count']} | {r['endpoint_hits']} |")
lines.append("")

(OUT / "04_frequency_rails.md").write_text("\n".join(lines), encoding="utf-8")
print(f"wrote 01_frequency_rails.md ({len(matched)} land on physics, {len(unmatched)} unmatched)")
