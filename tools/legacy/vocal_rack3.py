#!/usr/bin/env python3
"""Response-first generator v3 — lean into complexity, gated by the budget.

Same core as v2 (whole-corner constellation -> 6 biquads, no roles, no mandatory
sub, gain derived AFTER the shape passes), but it USES the whole instrument:

  - all 6 stages, placed on a LOG-frequency grid
  - coupled pole/zero CAVITIES (the tube character)
  - inter-formant NOTCHES (hollow, not EQ bumps)
  - a SHEEN resonance up top (the Hedz-style air bite)
  - optional deliberate ANTI-FORMANT (nasal / growl)
  - a low-control zero so the low NEVER pedestals

Every candidate is run through the response budget (tools/response_budget.py).
Complexity is allowed only if it still passes: no pedestal, bite present, stable.

  python tools/vocal_rack3.py
"""
from __future__ import annotations
import io, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from pyruntime import packed_interp as pi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
import teleport_stress as ts  # noqa: E402
import hedz_floor_profile as hf  # noqa: E402
import response_budget as rb  # noqa: E402  (single budget spec)

OUT = os.path.join(ROOT, "dev", "tmp", "vocal_rack3")
SR = 39062.5
TAU = 2.0 * math.pi
STAGES = 6
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
PASS = (2.0, 1.0, 2.0, 1.0, 1.0)
FREQS = np.logspace(math.log10(20.0), math.log10(16000.0), 2048)

PEAK_REF = 0.7
LOW_ZERO_OCT = 0.6      # low-control zero this far (log) below the lowest pole
LOW_ZERO_R = 0.92


def load_vowels():
    d = json.load(io.open(os.path.join(ROOT, "tables", "vowel_formants.json"), encoding="utf-8"))
    return {v["key"]: v for v in d["vowels"]}


VOW = load_vowels()


def bw_to_r(bw, cap=0.9985):
    return min(cap, math.exp(-math.pi * bw / SR))


def tense(r, amt, cap=0.998):
    return min(cap, r + amt * (cap - r))


def _kernel(pf, pr, gain, zf, zr):
    th = TAU * pf / SR
    a1, a2 = -2.0 * pr * math.cos(th), pr * pr
    b0 = gain
    if zf and zr > 0.0:
        tz = TAU * zf / SR
        b1, b2 = gain * (-2.0 * zr * math.cos(tz)), gain * (zr * zr)
    else:
        b1 = b2 = 0.0
    return [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0]


# ── CONSTELLATION: a rich whole-corner target on a log grid (no roles) ──
def constellation(vow, tight, spec):
    """A whole-corner shape: the vowel's formants PLUS a presence and sheen pole
    derived FROM the vowel (so the entire constellation differs between corners,
    not just F1-F3). The morph A->B then moves every resonance along its own natural
    vowel trajectory (F1 falls, F2/F3/F4 climb) — the middle EMERGES as a shape
    neither corner holds. NO uniform pitch-slide, NO roles."""
    f3 = vow["f3"]
    # upper poles tracked to the vowel's brightness so they MOVE across the morph
    f = [vow["f1"], vow["f2"], f3, max(3000.0, f3 * 1.2), min(9500.0, max(5500.0, f3 * 2.4))]
    bw = [vow["bw1"], vow["bw2"], vow["bw3"], 200.0, 750.0]
    if spec.get("sixth"):  # extra density, vowel-relative so it moves too
        f.append(vow["f2"] * spec["sixth"]); bw.append(150.0)
    pairs = sorted((min(0.42 * SR, fi), bi) for fi, bi in zip(f, bw))[:STAGES]
    f = [p[0] for p in pairs]
    bw = [p[1] for p in pairs]
    n = len(f)

    nodes = []
    for i, (fi, bwi) in enumerate(zip(f, bw)):
        # Q0 is the RELAXED floor: broaden the natural bandwidth so the poles sit
        # soft (r ~0.95-0.97). Q100 then tightens HARD toward the razor ceiling, so
        # the Q axis is a real journey (breathy -> screaming), not a 0.002 nudge.
        r0 = min(0.970, bw_to_r(bwi * 4.0))
        if tight:
            ceil = 0.985 if fi > 4500 else 0.9975  # air stays controlled even at Q100
            r = min(ceil, r0 + 0.9 * (ceil - r0))   # razor at Q100
        else:
            r = r0                                   # relaxed floor
        zero = None
        if i == 0:
            zero = (fi * (2.0 ** -LOW_ZERO_OCT), LOW_ZERO_R)        # low control (no pedestal)
        elif i < n - 1 and spec.get("couple", True):
            zero = (math.sqrt(fi * f[i + 1]), 0.86)                  # inter-formant cavity notch
        else:
            zero = (fi * (2.0 ** 0.55), 0.6)                         # air rolloff up top
        nodes.append({"pole": (fi, r), "zero": zero})
    # a deliberate anti-formant (nasal/growl) replaces one cavity zero, if asked
    if spec.get("antiformant"):
        af = vow["f2"] * spec["antiformant"]  # notch tracks the vowel -> moves across morph
        # attach a deep notch near `af` to the nearest pole stage
        j = min(range(n), key=lambda k: abs(math.log2(f[k] / af)))
        nodes[j]["zero"] = (af, 0.94)
    return nodes


def cascade_peak(stages):
    peak = 1e-12
    for i in range(180):
        fr = 25.0 * (16000.0 / 25.0) ** (i / 179.0)
        w = TAU * fr / SR
        mag = 1.0
        for c in stages:
            b0, b1, b2, a1, a2 = c[4], (c[0] - 2) * c[4], (1 - c[1]) * c[4], c[2] - 2, 1 - c[3]
            cw, c2w, sw, s2w = math.cos(w), math.cos(2 * w), math.sin(w), math.sin(2 * w)
            nr, ni = b0 + b1 * cw + b2 * c2w, -b1 * sw - b2 * s2w
            dr, di = 1 + a1 * cw + a2 * c2w, -a1 * sw - a2 * s2w
            mag *= ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)) ** 0.5
        peak = max(peak, mag)
    return peak


def factor_to_biquads(nodes):
    stages = [list(PASS) for _ in range(STAGES)]
    for i, nd in enumerate(nodes[:STAGES]):
        (pf, pr), z = nd["pole"], nd["zero"]
        zf, zr = (z if z else (None, 0.0))
        stages[i] = _kernel(pf, pr, 1.0 - pr * pr, zf, zr)  # peak-tamed seed; gain derived later
    return stages


def derive_gain(stages, target=PEAK_REF):
    peak = cascade_peak(stages)
    active = sum(1 for s in stages if s != list(PASS))
    per = (target / peak) ** (1.0 / max(1, active))
    for s in stages:
        if s != list(PASS):
            s[4] *= per
    return stages


def build_body(spec):
    """4 corners as one constellation under two stresses: morph = log-shift UP
    (low->high sweep), Q = relaxed->razor. The middle EMERGES from the packed
    interpolation of these — that emergence is the ROM-preset magic, not the corners."""
    vow = VOW[spec["vowel"]]
    shift = 2.0 ** spec.get("morph_oct", 0.8)  # how far the morph sweeps up
    body = {}
    for lbl, mshift, tight in [("M0_Q0", 1.0, False), ("M100_Q0", shift, False),
                               ("M0_Q100", 1.0, True), ("M100_Q100", shift, True)]:
        body[lbl] = derive_gain(factor_to_biquads(constellation(vow, tight, mshift, spec)))
    return body


# richer bodies: every one uses all 6 stages + tricks. intent only, no roles.
BODIES = [
    # one base vowel (the body's identity) + morph_oct (how far the sweep rises).
    {"id": "open_mouth", "name": "Open Mouth", "vowel": "aa", "morph_oct": 0.95, "sheen": 7500},
    {"id": "dark_throat", "name": "Dark Throat", "vowel": "uw", "morph_oct": 0.8, "sheen": 6000,
     "sixth": (1500.0, 140.0)},
    {"id": "nasal_talk", "name": "Nasal Talk", "vowel": "eh", "morph_oct": 0.7, "sheen": 7000,
     "antiformant": 1150.0},
    {"id": "bright_front", "name": "Bright Front", "vowel": "ih", "morph_oct": 0.85, "sheen": 8500},
    {"id": "hollow_tube", "name": "Hollow Tube", "vowel": "uw", "morph_oct": 1.0, "sheen": 5500,
     "antiformant": 1900.0},
    {"id": "r_vox", "name": "R-Vox", "vowel": "er", "morph_oct": 0.8, "sheen": 6500,
     "sixth": (1000.0, 130.0)},
    {"id": "razor_talk", "name": "Razor Talk", "vowel": "ae", "morph_oct": 0.95, "sheen": 9000,
     "sixth": (2900.0, 120.0)},
]


def main():
    os.makedirs(OUT, exist_ok=True)
    report = {"generator": "response-first v3 (rich, log-grid, budget-gated, no pedestal, derived gain)",
              "bodies": {}}
    print("v3 — richer constellations, gated by the response budget:\n")
    print(f"{'body':<14} {'low':>5} {'body':>5} {'bite':>5} {'air':>6} | lo-bite maxR  poles  DCdiag  verdict")
    for spec in BODIES:
        body = build_body(spec)
        raw = bytearray()
        keyframes = []
        for lbl in CORNER_ORDER:
            words = [list(pi.coeffs_to_words(*s)) for s in body[lbl]]
            for w in words:
                for x in w:
                    raw += int(x & 0xFFFF).to_bytes(2, "little")
            keyframes.append({"label": lbl, "boost": 1.0, "packedWords": words,
                              "stages": [{"c0": s[0], "c1": s[1], "c2": s[2], "c3": s[3], "c4": s[4]} for s in body[lbl]]})
        cart = os.path.join(OUT, f"{spec['id']}.cart.json")
        with open(os.path.join(OUT, f"{spec['id']}.body240"), "wb") as fp:
            fp.write(bytes(raw))
        json.dump({"format": "compiled-v1", "name": spec["name"],
                   "provenance": "vocal_rack3 response-first rich (constellation -> 6 biquads, budget-gated)",
                   "sampleRate": SR, "authoring_sample_rate_hz": SR, "stages": STAGES,
                   "cornerOrder": list(CORNER_ORDER), "keyframes": keyframes},
                  open(cart, "w", encoding="utf-8"), indent=2)

        # gate by the SAME response budget
        v = rb.judge(cart)
        npoles = sum(1 for s in body["M0_Q0"] if s != list(PASS))
        b = v["bands"]
        failed = [k for k, ok in v["gates"].items() if not ok]
        report["bodies"][spec["id"]] = {"name": spec["name"], "bands": b, "n_poles": npoles,
                                        "max_radius": v["max_radius"], "dc_diag": v["dc_diag_max_db"],
                                        "pass": v["pass"], "failed": failed}
        warn = " PED!" if v["dc_pedestal_warn"] else ""
        print(f"{spec['name']:<14} {b['low']:>5} {b['body']:>5} {b['bite']:>5} {b['air']:>6} | "
              f"{v['low_minus_bite']:>6} {v['max_radius']:.3f}  {npoles}    {v['dc_diag_max_db']:>5}{warn}  "
              f"{'PASS' if v['pass'] else 'FAIL '+','.join(failed)}")

    json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), indent=2)
    npass = sum(1 for b in report["bodies"].values() if b["pass"])
    print(f"\n{npass}/{len(BODIES)} pass the budget -> {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
