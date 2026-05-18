"""Extract the canonical q_radius_table from the RE calibration corpus.

The verified RE finding (per `re_provenance.q_radius_table_size`) says E-mu /
P2K firmware ships a 512-entry pole-radius lookup table indexed by an internal
Q value. Each `TrenchCal__*.json` calibration record annotates every measured
biquad with `q_table_index` and `q_table_radius`, plus the observed `q_table_error`
(measured radius − table radius).

This script unions those annotations across all corpus filters, asserts that
every observed `q_table_index` resolves to a single canonical radius (within a
tolerance), and writes the recovered table to `authoring/tables/q_radius_table.json`.

Read-only with respect to source. Writes a single new asset file.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

TRENCH_ROOT = Path(r"C:\Users\hooki\Trench")
CAL_DIR = TRENCH_ROOT / "docs" / "notebooklm" / "local_ground_truth_pack_2026-05-14" / "03_calibration_and_reference_measurements"
OUT_DIR = TRENCH_ROOT / "authoring" / "tables"
OUT_PATH = OUT_DIR / "q_radius_table.json"
TABLE_SIZE = 512
CONSISTENCY_TOL = 1e-6


def iter_stages(cal_doc: dict):
    corners = cal_doc.get("corners") or {}
    for corner_label, corner in corners.items():
        for stage in corner.get("stages", []):
            yield corner_label, stage


def main() -> int:
    if not CAL_DIR.exists():
        print(f"FATAL: calibration dir not found at {CAL_DIR}", file=sys.stderr)
        return 1

    cal_files = sorted(CAL_DIR.glob("TrenchCal__*.json"))
    cal_files = [f for f in cal_files if "index" not in f.name and "MANIFEST" not in f.name and "PROVENANCE" not in f.name]
    if not cal_files:
        print(f"FATAL: no TrenchCal__*.json in {CAL_DIR}", file=sys.stderr)
        return 1

    by_index: dict[int, list[tuple[float, str, str, int]]] = defaultdict(list)
    rejected_round_radii: list[tuple[str, str, int, float]] = []
    n_stages = 0

    for cal_path in cal_files:
        try:
            doc = json.loads(cal_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  SKIP {cal_path.name}: {exc}", file=sys.stderr)
            continue
        cart_name = doc.get("name", cal_path.stem)
        for corner_label, stage in iter_stages(doc):
            n_stages += 1
            idx = stage.get("q_table_index")
            radius = stage.get("q_table_radius")
            if idx is None or radius is None:
                continue
            try:
                idx_i = int(idx)
                r_f = float(radius)
            except (TypeError, ValueError):
                continue
            if not (0.0 <= r_f <= 1.0):
                continue
            by_index[idx_i].append((r_f, cart_name, corner_label, int(stage.get("stage", -1))))

    if not by_index:
        print("FATAL: no q_table_radius annotations found in corpus", file=sys.stderr)
        return 1

    # Consistency check: every index must resolve to a single radius within tolerance.
    canonical: dict[int, float] = {}
    conflicts: list[str] = []
    for idx, hits in sorted(by_index.items()):
        radii = [h[0] for h in hits]
        rmin, rmax = min(radii), max(radii)
        if rmax - rmin > CONSISTENCY_TOL:
            conflicts.append(f"index {idx}: range [{rmin:.7f}, {rmax:.7f}] across {len(hits)} hits")
        canonical[idx] = sum(radii) / len(radii)

    if conflicts:
        print("FATAL: q_table_radius inconsistencies in corpus:", file=sys.stderr)
        for c in conflicts:
            print(f"  {c}", file=sys.stderr)
        return 2

    # Output: list ordered by index, with hit counts for transparency.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_entries = []
    for idx in sorted(canonical):
        out_entries.append({
            "q_table_index": idx,
            "radius": canonical[idx],
            "corpus_hits": len(by_index[idx]),
        })
    payload = {
        "source": "TrenchCal__*.json (RE corpus, q_table_index + q_table_radius)",
        "table_size_declared": TABLE_SIZE,
        "table_size_observed": len(out_entries),
        "consistency_tolerance": CONSISTENCY_TOL,
        "corpus_files": [p.name for p in cal_files],
        "stages_scanned": n_stages,
        "entries": out_entries,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    radii_only = [e["radius"] for e in out_entries]
    print(f"wrote {OUT_PATH}")
    print(f"  entries: {len(out_entries)} / {TABLE_SIZE} declared")
    print(f"  scanned: {n_stages} stages across {len(cal_files)} calibration files")
    print(f"  radius range: [{min(radii_only):.7f}, {max(radii_only):.7f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
