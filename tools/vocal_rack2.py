#!/usr/bin/env python3
"""Response-first body generator (rewrite of the role-based vocal_rack.py).

The musical object is the WHOLE-CORNER RESPONSE, not a row of named stages.

  1. constellation(): build a target as a pole/zero constellation (a whole-corner
     shape). NO semantic roles (no "sub"/"throat"/"air"), NO mandatory sub stage.
     The low end is controlled by a zero where the response needs it, not a pole.
  2. factor_to_biquads(): factor that constellation into <=6 biquads — purely an
     implementation step. Stages are bookkeeping rows. Rows are ordered by pole
     frequency so row i corresponds across corners (kinship for interpolation),
     but a row carries no role.
  3. gain is DERIVED (normalize the cascade to a headroom reference), not a fixed
     boost. Cartridge boost stays 1.0.

Judged only by: full cascade magnitude response, low/body/bite/air band levels,
stability over the Morph x Q surface, and audition WAVs.

  python tools/vocal_rack2.py
"""
from __future__ import annotations

import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
from scipy.io import wavfile  # noqa: E402

from pyruntime import packed_interp as pi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
import teleport_stress as ts  # noqa: E402
import hedz_floor_profile as hf  # noqa: E402  (band_levels: low/body/bite/air)

OUT = os.path.join(ROOT, "dev", "tmp", "vocal_rack2")
SR = 39062.5
TAU = 2.0 * math.pi
STAGES = 6
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
PASS = (2.0, 1.0, 2.0, 1.0, 1.0)
FREQS = np.logspace(math.log10(20.0), math.log10(16000.0), 2048)

# Derived references (headroom + acoustic shaping), NOT per-body gain hard-codes:
PEAK_REF = 0.7            # normalize each corner's cascade peak here (gain derived)
LOW_ROLLOFF_OCT = 0.55   # the low-control zero sits this far below the lowest pole
LOW_ZERO_R = 0.9         # its radius (depth of the low rolloff)
AIR_ZERO_OCT = 0.6       # the top pole's rolloff zero sits this far above it
AIR_ZERO_R = 0.6


def load_vowels():
    d = json.load(io.open(os.path.join(ROOT, "tables", "vowel_formants.json"), encoding="utf-8"))
    return {v["key"]: v for v in d["vowels"]}


VOW = load_vowels()


def bw_to_r(bw, cap=0.9985):
    return min(cap, math.exp(-math.pi * bw / SR))


def tense(r, amount=0.55, cap=0.998):
    return min(cap, r + amount * (cap - r))


# ── 1. CONSTELLATION: whole-corner target (poles + zeros), no roles, no sub ──
def constellation(vow, tight, spec):
    """A whole-corner target shape: the vowel's formants as resonances, plus zeros
    that shape the response (low rolloff + optional inter-formant cavities + air).
    Returns an ordered (by freq) list of {pole:(f,r), zero:(f,r)|None}. Variable
    length — only as many resonances as the target needs."""
    forms = [(vow["f1"], vow["bw1"]), (vow["f2"], vow["bw2"]), (vow["f3"], vow["bw3"])]
    if spec.get("bright"):
        forms.append((min(0.42 * SR, vow["f3"] * 1.5), 180.0))  # a brightness resonance, derived from F3
    poles = []
    for f, bw in forms:
        r = bw_to_r(bw)
        if tight:
            r = tense(r)
        poles.append((f, r))
    n = len(poles)
    nodes = []
    for i, (f, r) in enumerate(poles):
        zero = None
        if i == 0:
            # low control: a zero below the lowest resonance rolls the sub off so
            # low energy EMERGES from the target, never from a mandatory sub pole.
            zero = (f * (2.0 ** -LOW_ROLLOFF_OCT), LOW_ZERO_R)
        elif spec.get("couple") and i < n - 1:
            # inter-formant cavity anti-resonance (the "tube" coupling)
            zero = (math.sqrt(f * poles[i + 1][0]), 0.85)
        elif i == n - 1:
            # roll the top so air never runs away
            zero = (f * (2.0 ** AIR_ZERO_OCT), AIR_ZERO_R)
        nodes.append({"pole": (f, r), "zero": zero})
    return nodes


# ── 2. FACTOR: constellation -> <=6 biquads (implementation step; rows = bookkeeping) ──
def _kernel(pf, pr, gain, zf, zr):
    theta = TAU * pf / SR
    a1, a2 = -2.0 * pr * math.cos(theta), pr * pr
    b0 = gain
    if zf and zr > 0.0:
        tz = TAU * zf / SR
        b1, b2 = gain * (-2.0 * zr * math.cos(tz)), gain * (zr * zr)
    else:
        b1 = b2 = 0.0
    return [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0]


def cascade_peak(stages):
    peak = 1e-12
    for i in range(160):
        f = 25.0 * (16000.0 / 25.0) ** (i / 159.0)
        w = TAU * f / SR
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
        stages[i] = _kernel(pf, pr, 1.0 - pr * pr, zf, zr)  # peak-tamed seed
    # derive gain: spread one scalar so the cascade peaks at the headroom reference
    peak = cascade_peak(stages)
    per = (PEAK_REF / peak) ** (1.0 / max(1, sum(1 for s in stages if s != list(PASS))))
    for s in stages:
        if s != list(PASS):
            s[4] *= per
    return stages


def build_body(spec):
    return {
        "M0_Q0": factor_to_biquads(constellation(VOW[spec["vowelA"]], False, spec)),
        "M100_Q0": factor_to_biquads(constellation(VOW[spec["vowelB"]], False, spec)),
        "M0_Q100": factor_to_biquads(constellation(VOW[spec["vowelA"]], True, spec)),
        "M100_Q100": factor_to_biquads(constellation(VOW[spec["vowelB"]], True, spec)),
    }


# whole-corner targets, expressed as musical intent (vowel pair + character flags).
# No roles, no sub, no boost.
BODIES = [
    {"id": "open_mouth", "name": "Open Mouth", "vowelA": "aa", "vowelB": "iy", "couple": True,
     "desc": "'ahh' opening to 'eee'."},
    {"id": "dark_throat", "name": "Dark Throat", "vowelA": "uw", "vowelB": "ao", "couple": True,
     "desc": "rounded 'ooo' to 'awww', dark."},
    {"id": "nasal_talk", "name": "Nasal Talk", "vowelA": "eh", "vowelB": "iy", "couple": True,
     "desc": "pinched talkbox 'ehh'-'eee'."},
    {"id": "bright_front", "name": "Bright Front", "vowelA": "ih", "vowelB": "iy", "couple": True, "bright": True,
     "desc": "forward, bright 'ihh'-'eee'."},
    {"id": "hollow_tube", "name": "Hollow Tube", "vowelA": "uw", "vowelB": "uh", "couple": True,
     "desc": "woody hollow 'ooo'-'uhh'."},
    {"id": "r_vox", "name": "R-Vox", "vowelA": "er", "vowelB": "aa", "couple": True,
     "desc": "'errr' opening to 'ahhh'."},
]


def band_levels(stages):
    enc = [EncodedCoeffs(*s) for s in stages]
    return hf.band_levels(enc, FREQS, SR, 1.0)  # boost 1.0 — gain already derived


def main():
    os.makedirs(OUT, exist_ok=True)
    report = {"generator": "response-first (no roles, no mandatory sub, derived gain, boost=1.0)",
              "peak_ref": PEAK_REF, "bodies": {}}
    print("Response-first generator — judged by bands / stability / audition (no roles):\n")
    print(f"{'body':<14} {'low':>6} {'body':>6} {'bite':>6} {'air':>6}   maxR  unst  poles")
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
        with open(os.path.join(OUT, f"{spec['id']}.body240"), "wb") as f:
            f.write(bytes(raw))
        json.dump({"format": "compiled-v1", "name": spec["name"],
                   "provenance": "vocal_rack2 response-first (whole-corner constellation -> 6 biquads)",
                   "sampleRate": SR, "authoring_sample_rate_hz": SR, "stages": STAGES,
                   "cornerOrder": list(CORNER_ORDER), "keyframes": keyframes},
                  open(os.path.join(OUT, f"{spec['id']}.cart.json"), "w", encoding="utf-8"), indent=2)

        # judge: bands (M0_Q0), stability (Morph x Q), audition
        lv = band_levels(body["M0_Q0"])
        words_dict = {LABEL_TO_KEY[lbl]: [pi.coeffs_to_words(*s) for s in body[lbl]] for lbl in CORNER_ORDER}
        gm = np.linspace(0, 1, 48)
        mm, qq = np.meshgrid(gm, gm)
        stab = ts.static_probe(words_dict, mm.ravel(), qq.ravel())
        npoles = sum(1 for s in body["M0_Q0"] if s != list(PASS))

        vdir = os.path.join(OUT, spec["id"])
        os.makedirs(vdir, exist_ok=True)
        sr = ts.SR_DEFAULT
        n = int(4.0 * sr)
        x = ts.source_signal(n, sr)
        t = np.arange(n) / sr
        morph = 0.5 - 0.5 * np.cos(TAU * 0.4 * t / 4.0)
        q = 0.5 - 0.5 * np.cos(TAU * 0.9 * t / 4.0)
        sweep, nf = render(words_dict, x, morph, q, sr)
        wavfile.write(os.path.join(vdir, "sweep.wav"), sr, sweep)

        report["bodies"][spec["id"]] = {
            "name": spec["name"], "desc": spec["desc"], "vowel_morph": f"{spec['vowelA']}->{spec['vowelB']}",
            "n_active_stages": npoles,
            "band_levels_db": {k: round(v, 2) for k, v in lv.items()},
            "low_minus_bite_db": round(lv["low"] - lv["bite"], 2),
            "stability": {"max_pole_radius": round(stab["max_pole_radius"], 4),
                          "unstable_denominator_rows": stab["unstable_denominator_rows"],
                          "nonfinite_coeff_rows": stab["nonfinite_coeff_rows"]},
            "render_nonfinite": nf,
        }
        print(f"{spec['name']:<14} {lv['low']:>6.1f} {lv['body']:>6.1f} {lv['bite']:>6.1f} {lv['air']:>6.1f}   "
              f"{stab['max_pole_radius']:.3f}  {stab['unstable_denominator_rows']:>3}   {npoles}")

    json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), indent=2)
    print(f"\n-> {os.path.relpath(OUT, ROOT)}  (report.json + per-body cart/body240/sweep)")


def render(words_dict, x, morph, q, sr, drive=4.0):
    states = np.zeros((STAGES, 2))
    raw = np.zeros(len(x))
    nf = 0
    for i in range(len(x)):
        rows = pi.packed_bilinear(words_dict, float(morph[i]), float(q[i]))
        v = float(x[i])
        for si, row in enumerate(rows):
            b0, b1, b2, a1, a2 = pi.kernel_to_biquad(row)
            y = b0 * v + states[si, 0]
            w1 = b1 * v - a1 * y + states[si, 1]
            w2 = b2 * v - a2 * y
            if not (math.isfinite(y) and math.isfinite(w1) and math.isfinite(w2)):
                y = w1 = w2 = 0.0
                nf += 1
            states[si, 0], states[si, 1] = w1, w2
            v = y
        raw[i] = v if math.isfinite(v) else 0.0
    wet = ts.dc_block(raw, sr)
    wet = np.tanh(wet * drive)
    peak = float(np.max(np.abs(wet)) + 1e-12)
    if peak > 0.98:
        wet *= 0.98 / peak
    return wet.astype(np.float32), nf


if __name__ == "__main__":
    main()
