#!/usr/bin/env python3
"""Compare generated bodies against the P2K calibration envelope — as a GUARDRAIL.

Uses dev/tmp/p2k_response_calibration (the machine-readable P2K refs) to define a
healthy neighborhood from the proven vocal presets (talking_hedz + P2k_013):
contrast range, low-minus-bite range. Then scores each generated candidate with the
EXACT same metrics (p2k's cascade_response_db + curve_features). This is calibration,
not copying — we never match P2K poles, we just check our shape sits in a sane place
(enough contrast = sparse not bland; bite below low = vocal; air rolled).

  python tools/calibration_compare.py [<cart.json> ...]   (default: the low->high rack)
"""
from __future__ import annotations
import csv, glob, io, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
import p2k_response_calibration as p2k  # noqa: E402
from pyruntime import packed_interp as pi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402

CAL = os.path.join(ROOT, "dev", "tmp", "p2k_response_calibration")
SR = 39062.5
VOCAL_REFS = {"talking_hedz", "P2k_013"}  # the proven vocal guardrail (not a recipe)
POINTS = [("M0_Q0", 0.0, 0.0), ("M50_Q50", 0.5, 0.5), ("M100_Q100", 1.0, 1.0)]


def grid():
    ref = json.load(io.open(os.path.join(CAL, "talking_hedz", "response.json"), encoding="utf-8"))
    return np.array(ref["curves"]["M0_Q0"]["freq_hz"], dtype=float)


def envelope():
    rows = list(csv.DictReader(io.open(os.path.join(CAL, "summary.csv"), encoding="utf-8")))
    v = [r for r in rows if r["preset"] in VOCAL_REFS]
    c = [float(r["contrast"]) for r in v]
    lb = [float(r["low_minus_bite"]) for r in v]
    return (min(c), max(c)), (min(lb), max(lb))


def words_of(cart):
    d = json.load(io.open(cart, encoding="utf-8"))
    by = {k["label"]: [tuple(int(x) & 0xFFFF for x in w) for w in k["packedWords"]] for k in d["keyframes"]}
    return d.get("name", os.path.basename(cart)), {"A": by["M0_Q0"], "B": by["M100_Q0"], "C": by["M0_Q100"], "D": by["M100_Q100"]}


def main():
    carts = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, "dev/tmp/vocal_rack2_low_to_high/*.cart.json")))
    freqs = grid()
    (c_lo, c_hi), (lb_lo, lb_hi) = envelope()
    print(f"P2K vocal guardrail (talking_hedz + P2k_013): contrast {c_lo:.0f}-{c_hi:.0f} dB, "
          f"low-bite {lb_lo:.0f}-{lb_hi:.0f} dB  (Hedz M0_Q0: contrast 85, low-bite 20)\n")
    print(f"{'candidate':<26} {'pt':<10} {'contrast':>8} {'low-bite':>8} {'peaks':>5}  verdict")
    for cart in carts:
        name, wd = words_of(cart)
        for label, m, q in POINTS:
            rows = pi.packed_bilinear(wd, m, q)
            db = p2k.cascade_response_db([EncodedCoeffs(*r) for r in rows], freqs, SR)  # boost 1.0
            f = p2k.curve_features(freqs, db)
            con, lb, npk = f["contrast_db"], f["low_minus_bite_db"], len(f["peaks"])
            # guardrail checks (generous: enough contrast to be sparse-not-bland; vocal tilt)
            in_con = con >= 0.7 * c_lo
            verdict = []
            if con < 0.7 * c_lo:
                verdict.append("BLAND(low contrast)")
            if lb < 3:
                verdict.append("bite>=low(not vocal)")
            tag = "ok" if not verdict else " ".join(verdict)
            mark = "" if in_con else "  <-- too filled-in" if con < 0.7 * c_lo else ""
            print(f"{name[:25]:<26} {label:<10} {con:>8.1f} {lb:>8.1f} {npk:>5}  {tag}{mark}")
        print()


if __name__ == "__main__":
    main()
