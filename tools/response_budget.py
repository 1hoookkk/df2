#!/usr/bin/env python3
"""Response budget — judge a body by its cascade response, not by hard-coded recipe.

A body passes if its full-cascade magnitude response (log grid) clears the gates.
Talking Hedz is a calibration GUARDRAIL (floor level + radius ceiling), never a
recipe — we do not copy its poles/zeros.

Gates (all gain-INDEPENDENT shape gates first; gain/floor derived only after):
  - low-body delta cap          |low - body|  <= LOW_BODY_CAP
  - low-bite delta cap          |low - bite|  <= LOW_BITE_CAP   (catches pedestals)
  - bite present                bite >= body - BITE_BURY_CAP
  - peak / drive sane           derived floor lands peak in [PEAK_LO, PEAK_HI]
  - stable                      max pole radius < 1.0, no unstable rows
  - finite                      no nonfinite coeffs
  - per-stage DC gain           DIAGNOSTIC ONLY — flags pedestal bugs, never gates

  python tools/response_budget.py <cart.json> [<cart.json> ...]
  (no args: compares the old pedestal rack vs the response-first rack)
"""
from __future__ import annotations
import glob, io, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from pyruntime import packed_interp as pi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
import teleport_stress as ts  # noqa: E402
import hedz_floor_profile as hf  # noqa: E402

SR = 39062.5
FREQS = np.logspace(math.log10(20.0), math.log10(16000.0), 2048)
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}

# ── THE BUDGET (tunable gates; this is the spec, not per-body constants) ──
LOW_BODY_CAP = 9.0    # dB
LOW_BITE_CAP = 16.0   # dB — a pedestal makes low >> bite; this catches it
BITE_BURY_CAP = 22.0  # dB bite may sit below body (dark vowels allowed, not buried)
PEAK_LO, PEAK_HI = -12.0, 6.0  # dB — derived floor must land the peak here (headroom)
DC_DIAG_DB = 18.0     # per-stage DC gain above this = likely pedestal bug (diagnostic)


def load(cart):
    d = json.load(io.open(cart, encoding="utf-8"))
    by = {k["label"]: k for k in d["keyframes"]}
    boost = float(by["M0_Q0"].get("boost", d.get("boost", 1.0)))
    wd = {LABEL_TO_KEY[l]: [tuple(int(x) & 0xFFFF for x in w) for w in by[l]["packedWords"]] for l in CORNER_ORDER}
    m0 = [pi.words_to_coeffs(w) for w in wd["A"]]
    return d.get("name", os.path.basename(cart)), boost, wd, m0


def dc_gain_db(s):
    den = s[2] - s[3]
    return 20 * math.log10(abs(s[4] * (s[0] - s[1]) / den) + 1e-30) if abs(den) > 1e-12 else 999.0


def judge(cart):
    name, boost, wd, m0 = load(cart)
    # SHAPE: bands on a log grid (gain-independent deltas)
    bands = hf.band_levels([EncodedCoeffs(*s) for s in m0], FREQS, SR, boost)
    low, body, bite, air, peak = bands["low"], bands["body"], bands["bite"], bands["air"], bands["peak"]
    # stability over the Morph x Q surface
    gm = np.linspace(0, 1, 40)
    mm, qq = np.meshgrid(gm, gm)
    stab = ts.static_probe(wd, mm.ravel(), qq.ravel())
    # per-stage DC diagnostic (NOT a gate)
    dcs = [dc_gain_db(s) for s in m0 if s != [2.0, 1.0, 2.0, 1.0, 1.0]]
    dc_flag = max(dcs) if dcs else float("nan")

    # HARD gates = brokenness ONLY (per directive: budget is a reject filter, not the
    # sound target). Band balance is advisory — extreme dark/bright is a valid sound,
    # not a failure. A body is rejected only if it pedestals, blows up, or goes NaN.
    gates = {
        "no-pedestal": dc_flag <= DC_DIAG_DB,
        "stable": stab["max_pole_radius"] < 1.0 and stab["unstable_denominator_rows"] == 0,
        "finite": stab["nonfinite_coeff_rows"] == 0,
        "peak-sane": PEAK_LO <= peak <= PEAK_HI,
    }
    return {
        "name": name, "bands": {k: round(bands[k], 1) for k in ("low", "body", "bite", "air", "peak")},
        "low_minus_bite": round(low - bite, 1), "low_minus_body": round(low - body, 1),
        "max_radius": round(stab["max_pole_radius"], 4),
        "dc_diag_max_db": round(dc_flag, 1), "dc_pedestal_warn": dc_flag > DC_DIAG_DB,
        # advisory (reported, NOT gated): how the band balance sits vs the Hedz guardrail
        "advisory": {"low_body_delta": round(low - body, 1), "low_bite_delta": round(low - bite, 1)},
        "gates": gates, "pass": all(gates.values()),
    }


def main():
    carts = sys.argv[1:]
    if not carts:
        carts = sorted(glob.glob(os.path.join(ROOT, "dev/tmp/vocal_rack_tube/*_tube.cart.json")))[:3] \
            + sorted(glob.glob(os.path.join(ROOT, "dev/tmp/vocal_rack2/*.cart.json")))
    print(f"{'body':<22} {'low':>5} {'body':>5} {'bite':>5} {'air':>6} | lo-bite  maxR   DCdiag  verdict  failed")
    for c in carts:
        r = judge(c)
        b = r["bands"]
        failed = [k for k, v in r["gates"].items() if not v]
        warn = " PEDESTAL!" if r["dc_pedestal_warn"] else ""
        tag = os.path.basename(c).replace(".cart.json", "")
        print(f"{tag:<22} {b['low']:>5} {b['body']:>5} {b['bite']:>5} {b['air']:>6} | "
              f"{r['low_minus_bite']:>6}  {r['max_radius']:.3f}  {r['dc_diag_max_db']:>5}{warn}  "
              f"{'PASS' if r['pass'] else 'FAIL':<5}  {','.join(failed)}")


if __name__ == "__main__":
    main()
