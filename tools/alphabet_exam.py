"""The alphabet exam: (1) census/coverage, (2) re-spell round-trip — sample
stages from each letter's distributions, rebuild lane features, classify back.
Report -> dev/tmp/alphabet/exam.md. Phase 2 is blocked until this passes AND
Tyson blesses the sheet pile."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from tools.alphabet_trace import classify_lane
from tools.stage_features import SR, stage_info

OUT = os.path.join("dev", "tmp", "alphabet")


def _draw(dist, rng, log=False):
    """Sample between p25..p75 (the letter's home range), uniform."""
    lo = dist["p25"]
    hi = max(dist["p75"], lo * 1.0001 if lo > 0 else dist["p75"])
    if log and lo > 0:
        return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
    return float(rng.uniform(lo, hi))


def _norm_gain(a1, a2, nb1, nb2):
    """Unity-DC gain; if the numerator kills DC, anchor at Nyquist instead."""
    den_dc = 1 + nb1 + nb2
    if abs(den_dc) > 1e-3:
        return (1 + a1 + a2) / den_dc
    return (1 - a1 + a2) / max(abs(1 - nb1 + nb2), 1e-3)


def synth_biquad(name: str, letter: dict, rng) -> list:
    """One stage from letter distributions -> [b0,b1,b2,a1,a2].

    Letterform fidelity: REALROOT plants a real pair (traced signed values);
    ratio letters (CANYON/SCOOP/AIRCUT/CROWN) derive the zero from the pole via
    the traced zero/pole RATIO — the ratio IS the letter's defining parameter.
    Depth bounds come from the class definitions (>= .85 deep, < .85 crown)."""
    fp = _draw(letter["pole_f"], rng, log=True) if letter["pole_f"] else 800.0
    rp = min(0.9998, max(0.5, _draw(letter["pole_r"], rng))) if letter["pole_r"] else 0.95
    wp = 2 * np.pi * fp / SR
    a1, a2 = -2 * rp * np.cos(wp), rp * rp

    if name == "REALROOT":
        rzv = letter.get("real_zero_v")
        if rzv and rzv["n"] >= 4:
            v1, v2 = _draw(rzv, rng), _draw(rzv, rng)
            nb1, nb2 = -(v1 + v2), v1 * v2
            g = _norm_gain(a1, a2, nb1, nb2)
            return [g, g * nb1, g * nb2, a1, a2]
        rpv = letter.get("real_pole_v")
        p1 = min(0.998, max(-0.998, _draw(rpv, rng)))
        p2 = min(0.998, max(-0.998, _draw(rpv, rng)))
        a1, a2 = -(p1 + p2), p1 * p2
        g = _norm_gain(a1, a2, 0.0, 0.0)
        return [g, 0.0, 0.0, a1, a2]

    if name == "RESON" or not letter["zero_f"]:
        g = (1 - rp * rp)
        return [g, 0.0, 0.0, a1, a2]

    if name == "FOUNDATION":
        fz, rz = _draw(letter["zero_f"], rng, log=True), 1.0
    else:
        ratio = _draw(letter["zero_ratio"], rng, log=True) if letter.get("zero_ratio") else 1.0
        fz = min(SR * 0.49, max(25.0, fp * ratio))
        rz = _draw(letter["zero_r"], rng)
        if name == "CROWN":
            rz = min(0.849, rz)
        else:
            rz = min(0.999, max(0.85, rz))
    wz = 2 * np.pi * fz / SR
    nb1, nb2 = -2 * rz * np.cos(wz), rz * rz
    g = _norm_gain(a1, a2, nb1, nb2)
    return [g, g * nb1, g * nb2, a1, a2]


def _lane_from_biquads(biquads) -> dict:
    """Rebuild the lane-feature dict from 4 corner biquads (bypasses packing —
    the exam tests the ALPHABET, the rust compiler re-tests packing later)."""
    corners = []
    for b in biquads:
        b0, b1, b2, a1, a2 = b
        c4 = b0
        c0 = (b1 / c4 + 2.0) if c4 else 2.0
        c1 = (1.0 - b2 / c4) if c4 else 1.0
        row = [c0, c1, a1 + 2.0, 1.0 - a2, c4]
        corners.append(stage_info(row))
    pf = [c["poles"][0]["f"] if c["poles"] else None for c in corners]
    return {"corners": corners,
            "pole_travel_oct": float(np.log2(pf[1] / pf[0])) if (pf[0] and pf[1]) else 0.0,
            "zero_travel_oct": 0.0,
            "max_dc": max(c["dc"] for c in corners),
            "q_pole_df": 0.0, "q_pole_dr": 0.0}


def sample_lane(name: str, letter: dict, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    return _lane_from_biquads([synth_biquad(name, letter, rng) for _ in range(4)])


def respell_roundtrip(seed: int = 0, k: int = 24):
    doc = json.load(open(os.path.join("desk", "letters.json"), encoding="utf-8"))
    rng = np.random.default_rng(seed)
    ok, total, per_letter = 0, 0, {}
    for name, letter in doc["letters"].items():
        hits = 0
        for _ in range(k):
            lane = sample_lane(name, letter, seed=int(rng.integers(1 << 30)))
            hits += 1 if classify_lane(lane) == name else 0
        per_letter[name] = hits / k
        ok += hits
        total += k
    return ok / total, per_letter


def main():
    os.makedirs(OUT, exist_ok=True)
    rate, per_letter = respell_roundtrip(seed=11, k=24)
    doc = json.load(open(os.path.join("desk", "letters.json"), encoding="utf-8"))
    lines = ["# Alphabet exam", "",
             f"lanes total: {doc['lanes_total']}",
             f"re-spell round-trip: {rate:.3f} (gate: >= 0.9)", ""]
    for name, r in sorted(per_letter.items()):
        lines.append(f"- {name}: {r:.2f} round-trip, {doc['letters'][name]['lanes']} lanes traced")
    verdict = "PASS" if rate >= 0.9 else "FAIL"
    lines += ["", f"VERDICT: {verdict} (Tyson's sheet-pile blessing still required)"]
    p = os.path.join(OUT, "exam.md")
    open(p, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    print("wrote", p)


if __name__ == "__main__":
    main()
