"""Rule-first letter classification + per-letter distribution fitting.

Rules encode the grammar facts measured 2026-07-05 (full-ROM sweep + STATE.md
dossier). Output desk/letters.json carries AGGREGATE distributions only."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from tools.stage_features import MUSICAL_33, body_features, load_body

LETTERS = ["FOUNDATION", "PAD", "REALROOT", "RESON", "CANYON", "SCOOP", "AIRCUT", "CROWN"]


def _med_zero_ratio_depth(lane):
    ratios, depths = [], []
    for c in lane["corners"]:
        zs = [z for z in c["zeros"] if not z["real"]]
        ps = [p for p in c["poles"] if not p["real"]]
        if zs and ps and ps[0]["f"] > 25:
            ratios.append(zs[0]["f"] / ps[0]["f"])
            depths.append(zs[0]["r"])
    if not ratios:
        return None, None
    return float(np.median(ratios)), float(np.median(depths))


def classify_lane(lane) -> str:
    if all(c["zr1"] for c in lane["corners"]):
        return "FOUNDATION"
    if all(c["flat"] < 3.0 for c in lane["corners"]):
        return "PAD"
    for c in lane["corners"]:
        if any(p["real"] and p["r"] > 0.01 for p in c["poles"]) or \
           any(z["real"] and z["r"] > 0.01 for z in c["zeros"]):
            return "REALROOT"
    if not any(c["has_zero"] for c in lane["corners"]):
        return "RESON"
    ratio, depth = _med_zero_ratio_depth(lane)
    if ratio is None or depth is None or depth < 0.85:
        return "CROWN"
    if ratio < 0.7:
        return "SCOOP"
    if ratio < 1.4:
        return "CANYON"
    return "AIRCUT"


def _dist(values):
    v = np.array([x for x in values if x is not None and np.isfinite(x)])
    if len(v) == 0:
        return None
    return {"n": int(len(v)),
            "p5": float(np.percentile(v, 5)), "p25": float(np.percentile(v, 25)),
            "p50": float(np.percentile(v, 50)), "p75": float(np.percentile(v, 75)),
            "p95": float(np.percentile(v, 95))}


def trace(out_path: str = os.path.join("desk", "letters.json")) -> dict:
    buckets = {name: {"pole_f": [], "pole_r": [], "zero_f": [], "zero_r": [],
                      "dc": [], "pole_travel_oct": [], "count": 0,
                      "mover": 0, "bank": 0} for name in LETTERS}
    lanes_total = 0
    for d in MUSICAL_33:
        for lane in body_features(load_body(d)):
            lanes_total += 1
            name = classify_lane(lane)
            b = buckets[name]
            b["count"] += 1
            b["pole_travel_oct"].append(abs(lane["pole_travel_oct"]))
            b["mover"] += 1 if abs(lane["pole_travel_oct"]) > 0.5 else 0
            b["bank"] += 1 if lane["max_dc"] >= 30.0 else 0
            for c in lane["corners"]:
                for p in c["poles"]:
                    if not p["real"] and p["f"] > 25:
                        b["pole_f"].append(p["f"]); b["pole_r"].append(p["r"])
                for z in c["zeros"]:
                    if not z["real"] and z["f"] > 25:
                        b["zero_f"].append(z["f"]); b["zero_r"].append(z["r"])
                b["dc"].append(c["dc"])
    letters = {}
    for name, b in buckets.items():
        if b["count"] == 0:
            continue
        letters[name] = {
            "lanes": b["count"],
            "mover_frac": b["mover"] / b["count"],
            "bank_frac": b["bank"] / b["count"],
            "pole_f": _dist(b["pole_f"]), "pole_r": _dist(b["pole_r"]),
            "zero_f": _dist(b["zero_f"]), "zero_r": _dist(b["zero_r"]),
            "dc": _dist(b["dc"]), "pole_travel_oct": _dist(b["pole_travel_oct"]),
        }
    doc = {"version": 1, "sr": 39062.5,
           "source": "aggregate of ref/p2k_variants musical 33 (clean-room, no per-body tables)",
           "lanes_total": lanes_total, "letters": letters}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    return doc


if __name__ == "__main__":
    doc = trace()
    for name, l in sorted(doc["letters"].items(), key=lambda kv: -kv[1]["lanes"]):
        print(f"{name:10s} lanes {l['lanes']:3d}  mover {l['mover_frac']:.2f}  bank {l['bank_frac']:.2f}")
    print(f"total lanes {doc['lanes_total']} (expect 198 = 33 bodies x 6)")
