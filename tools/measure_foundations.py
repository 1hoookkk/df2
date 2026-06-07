#!/usr/bin/env python3
"""Measure neutral foundation/fundamental facts from decoded study artifacts.

This does not read or emit packed body bytes, coefficient rows, endpoint tables,
or reference names for authoring. It reduces existing decode reports into
aggregate facts Forge can use as root-law evidence.
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VOCAB = ROOT / "dev" / "tmp" / "p2k_full_vocabulary"
REF = ROOT / "dev" / "tmp" / "p2k_reference_fundamentals"
OUT = ROOT / "dev" / "tmp" / "measured_foundations"


def parse_counts(text: str) -> Counter[str]:
    out: Counter[str] = Counter()
    for part in str(text or "").split(";"):
        if ":" not in part:
            continue
        key, value = part.rsplit(":", 1)
        key = key.strip()
        try:
            out[key] += int(float(value.strip()))
        except ValueError:
            continue
    return out


def median(rows: list[dict[str, str]], key: str) -> float | None:
    vals = []
    for row in rows:
        try:
            vals.append(float(row.get(key, "")))
        except ValueError:
            pass
    return round(statistics.median(vals), 3) if vals else None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def top(counter: Counter[str], n: int = 8) -> list[dict[str, Any]]:
    return [{"name": key, "count": value} for key, value in counter.most_common(n)]


def measure_families(skins: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in skins:
        grouped[row.get("move_family", "unknown")].append(row)

    families = []
    for name, rows in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        roles: Counter[str] = Counter()
        motions: Counter[str] = Counter()
        frames: Counter[str] = Counter()
        takeaways: Counter[str] = Counter()
        for row in rows:
            roles.update(parse_counts(row.get("dominant_rows", "")))
            motions.update(parse_counts(row.get("motion_tags", "")))
            takeaways.update(x.strip() for x in row.get("forge_takeaway", "").split(";") if x.strip())
            for token in row.get("home_to_away_to_push_plain", "").replace("HOME", "").replace("AWAY", "").replace("PUSH", "").split("->"):
                token = token.strip()
                if token:
                    frames[token] += 1

        families.append(
            {
                "id": "root_" + name.replace("/", "_").replace("-", "_").replace(" ", "_"),
                "label": name,
                "skin_count": len(rows),
                "stable_all_5x5_count": sum(1 for row in rows if row.get("stable_all_5x5") == "True"),
                "median": {
                    "morph_rms_db": median(rows, "morph_rms_db_median"),
                    "secondary_rms_db": median(rows, "secondary_rms_db_median"),
                    "center_span_db": median(rows, "center_span_db_median"),
                    "center_sag_db": median(rows, "center_sag_db_median"),
                    "rail_fraction": median(rows, "rail_fraction"),
                },
                "dominant_rows": top(roles),
                "motion_tags": top(motions),
                "foundation_frames": top(frames, 6),
                "takeaways": top(takeaways, 5),
            }
        )
    return families


def measure_rails(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rails = []
    for row in rows:
        try:
            hz = float(row["rail_hz"])
            hits = int(row["total_hits"])
            skins = int(row["skin_count"])
        except (KeyError, ValueError):
            continue
        if hz < 20.0:
            continue
        rails.append(
            {
                "kind": row.get("kind", ""),
                "hz": hz,
                "band": row.get("band", ""),
                "total_hits": hits,
                "skin_count": skins,
                "top_stages": row.get("top_stages", ""),
                "top_states": row.get("top_states", ""),
            }
        )
    rails.sort(key=lambda r: (r["total_hits"], r["skin_count"], -r["hz"]), reverse=True)
    return rails[:32]


def measure_selected_references() -> dict[str, Any]:
    path = REF / "summary.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return {}
    grammar: Counter[str] = Counter()
    foundation: Counter[str] = Counter()
    base_roles: Counter[str] = Counter()
    motion_tags: Counter[str] = Counter()
    tilts: list[float] = []
    for body in data:
        grammar[body.get("grammar", "unknown")] += 1
        foundation[body.get("foundation_method", "unknown")] += 1
        try:
            tilts.append(float(body.get("cascade_tilt_db")))
        except (TypeError, ValueError):
            pass
        for row in body.get("rows", []):
            base_roles[row.get("base_role", "unknown")] += 1
            motion_tags.update(row.get("motion_tags", []))
    return {
        "body_count": len(data),
        "grammar": top(grammar, 10),
        "foundation_methods": top(foundation, 10),
        "base_roles": top(base_roles, 10),
        "motion_tags": top(motion_tags, 10),
        "cascade_tilt_db_median": round(statistics.median(tilts), 3) if tilts else None,
    }


def write_report(payload: dict[str, Any]) -> None:
    lines = [
        "# Measured Foundation Facts",
        "",
        "Neutral aggregate measurement for Forge root-law authoring.",
        "",
        "Boundary: this report contains counts, medians, rails, and labels derived",
        "from decoded study reports. It does not contain packed words, coefficient",
        "rows, endpoint curves, preset names, or reconstructable corner tables.",
        "",
        "## Root Families",
        "",
    ]
    for fam in payload["root_families"]:
        med = fam["median"]
        lines += [
            f"### {fam['label']}",
            "",
            f"- skins: `{fam['skin_count']}`; stable 5x5: `{fam['stable_all_5x5_count']}`",
            f"- median motion: Morph `{med['morph_rms_db']}` dB, Secondary `{med['secondary_rms_db']}` dB, span `{med['center_span_db']}` dB",
            "- dominant rows: " + ", ".join(f"`{x['name']}` {x['count']}" for x in fam["dominant_rows"][:5]),
            "- motion tags: " + ", ".join(f"`{x['name']}` {x['count']}" for x in fam["motion_tags"][:5]),
            "",
        ]
    lines += [
        "## Top Authoring Rails",
        "",
        "| kind | Hz | band | hits | skins |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for rail in payload["authoring_rails"][:16]:
        lines.append(f"| {rail['kind']} | {rail['hz']:.1f} | {rail['band']} | {rail['total_hits']} | {rail['skin_count']} |")
    lines.append("")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    skins = read_csv(VOCAB / "skin_summaries.csv")
    rails = read_csv(VOCAB / "frequency_rails.csv")
    payload = {
        "format": "df2-measured-foundations-v1",
        "boundary": "aggregate measurement only; no packed words, coefficient rows, endpoint curves, preset names, or reconstructable corner tables",
        "sources": {
            "skin_summaries": str((VOCAB / "skin_summaries.csv").relative_to(ROOT)),
            "frequency_rails": str((VOCAB / "frequency_rails.csv").relative_to(ROOT)),
            "selected_reference_summary": str((REF / "summary.json").relative_to(ROOT)),
        },
        "root_families": measure_families(skins),
        "authoring_rails": measure_rails(rails),
        "selected_reference_reduction": measure_selected_references(),
    }
    (OUT / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with (OUT / "foundation_families.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["id", "label", "skin_count", "stable_all_5x5_count", "morph_rms_db", "secondary_rms_db", "center_span_db", "center_sag_db"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for fam in payload["root_families"]:
            med = fam["median"]
            writer.writerow(
                {
                    "id": fam["id"],
                    "label": fam["label"],
                    "skin_count": fam["skin_count"],
                    "stable_all_5x5_count": fam["stable_all_5x5_count"],
                    "morph_rms_db": med["morph_rms_db"],
                    "secondary_rms_db": med["secondary_rms_db"],
                    "center_span_db": med["center_span_db"],
                    "center_sag_db": med["center_sag_db"],
                }
            )
    with (OUT / "authoring_rails.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["kind", "hz", "band", "total_hits", "skin_count", "top_stages", "top_states"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(payload["authoring_rails"])
    write_report(payload)
    print(f"wrote {OUT / 'summary.json'}")
    print(f"wrote {OUT / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
