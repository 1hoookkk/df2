#!/usr/bin/env python3
"""p2k_corner_stage_patterns.py — disaggregate the rails BY stage and BY corner.

Doc 04's rails are AGGREGATE (lumped across all corners+stages). This recovers the
per-stage and per-corner patterns: which actual Hz rails each stage lands on, which
each corner uses, and what role each stage/corner tends to play. Measured across all
50 P2K skins. Hz only, no invented numbers.

Writes dev/tmp/notebooklm_hz_pack/06_corner_and_stage_patterns.md
"""
import csv, re
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
SUMM = ROOT / "dev/tmp/p2k_full_vocabulary/skin_summaries.csv"
RAILS = ROOT / "dev/tmp/p2k_full_vocabulary/frequency_rails.csv"
OUT = ROOT / "dev/tmp/notebooklm_hz_pack/06_corner_and_stage_patterns.md"

skins = list(csv.DictReader(SUMM.open()))
rails = list(csv.DictReader(RAILS.open()))
N = len(skins)
STAGES = [f"S{i}" for i in range(1, 7)]
CORNERS = ["HOME", "AWAY", "PUSH_HOME", "PUSH_AWAY"]


def parse_hits(field):
    """'S6:162;S5:161;...' -> [('S6',162), ...]"""
    out = []
    for tok in field.split(";"):
        tok = tok.strip()
        if ":" in tok:
            k, v = tok.rsplit(":", 1)
            try:
                out.append((k.strip(), int(v)))
            except ValueError:
                pass
    return out


# --- aggregate the rails BY stage and BY corner (the actual Hz) ---
stage_hz = defaultdict(Counter)   # stage -> {hz: hits}
corner_hz = defaultdict(Counter)  # corner state -> {hz: hits}
for r in rails:
    hz = round(float(r["rail_hz"]))
    for s, n in parse_hits(r.get("top_stages", "")):
        stage_hz[s][hz] += n
    for st, n in parse_hits(r.get("top_states", "")):
        corner_hz[st][hz] += n

# --- per-stage role + per-corner character (functional, from the study) ---
stage_role = defaultdict(Counter)
corner_char = defaultdict(Counter)
for sk in skins:
    for tok in sk["row_roles"].split(";"):
        if ":" in tok:
            s, role = tok.split(":", 1)
            stage_role[s.strip()][role.strip()] += 1
    for seg in sk["home_to_away_to_push_plain"].split("->"):
        m = re.match(r"\s*(HOME|AWAY|PUSH HOME|PUSH AWAY)\s+(.*)", seg)
        if m:
            corner_char[m.group(1).replace(" ", "_")][m.group(2).strip()] += 1


def top_hz(counter, k=6):
    return " · ".join(f"{hz} Hz" for hz, _ in counter.most_common(k))


def top_roles(counter, k=3):
    return ", ".join(f"{v} ({n})" for v, n in counter.most_common(k))


L = [
    "# Patterns of each corner and stage",
    "",
    f"The rails in doc 04 are AGGREGATE. Here they are disaggregated BY stage and BY",
    f"corner, across all {N} P2K skins, measured through the shipped engine. A body is a",
    "4x6 grid: 4 corners (HOME, AWAY, PUSH HOME, PUSH AWAY) x 6 stages. Hz only.",
    "",
    "## Which Hz rails each STAGE lands on (most-used first)",
    "",
    "| stage | top rails |",
    "|---|---|",
]
for s in STAGES:
    L.append(f"| {s} | {top_hz(stage_hz[s])} |")

L += ["", "## Which Hz rails each CORNER uses (most-used first)", "",
      "| corner | top rails |", "|---|---|"]
for c in CORNERS:
    L.append(f"| {c.replace('_',' ')} | {top_hz(corner_hz[c])} |")
if corner_hz.get("CENTER"):
    L.append(f"| CENTER (the morph middle) | {top_hz(corner_hz['CENTER'])} |")

L += ["", "## What each STAGE tends to do (its role at HOME)", "",
      "Functional roles from the study (counts = how many of the 50 skins).", "",
      "| stage | most common roles |", "|---|---|"]
for s in STAGES:
    L.append(f"| {s} | {top_roles(stage_role[s])} |")

L += ["", "## What each CORNER tends to be", "", "| corner | most common character |", "|---|---|"]
for c in CORNERS:
    L.append(f"| {c.replace('_',' ')} | {top_roles(corner_char[c])} |")

OUT.write_text("\n".join(L), encoding="utf-8")
print(f"wrote {OUT.name} from {N} skins")
for s in STAGES:
    print(f"  {s} rails: {top_hz(stage_hz[s], 5)}")
for c in CORNERS:
    print(f"  {c} rails: {top_hz(corner_hz[c], 5)}")
