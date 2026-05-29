#!/usr/bin/env python3
"""Sparse, high-contrast low->high vocal bodies. Built from vocal_rack2 logic
(sparse peaks, dark valleys) — NOT vocal_rack3 (too broad / filled-in).

Target look = dev/tmp/vocal_rack2/plots/{open_mouth,r_vox}.png:
  - 3-4 strong, distinct peaks (not 6 bland humps)
  - deep dark valleys / clear negative space between them
  - controlled low floor, no sub pedestal
  - Morph 0 = low/dark vowel, Morph 100 = high/bright vowel; peaks move UP along
    their own natural vowel trajectories (they cross — the middle is a real
    intermediate, not a uniform diagonal smear)

The response budget is a REJECT FILTER only (catches pedestal / instability); it is
not the sound target. Gain derived, boost = 1.0, no mandatory sub.

  python tools/vocal_rack2_low_to_high.py            # bodies + budget + plots (fast)
  python tools/vocal_rack2_low_to_high.py --audio     # + sweeps + audition.html (slow)
"""
from __future__ import annotations
import io, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from pyruntime import packed_interp as pi  # noqa: E402
import teleport_stress as ts  # noqa: E402
import response_budget as rb  # noqa: E402
import rack2_plots as rpl  # noqa: E402

OUT = os.path.join(ROOT, "dev", "tmp", "vocal_rack2_low_to_high")   # analysis (plots/audio/report)
CANON = os.path.join(ROOT, "bodies", "vocal_low_to_high")           # canonical filters (.cart.json + .body240)
SR = 39062.5
TAU = 2.0 * math.pi
STAGES = 6
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
PASS = (2.0, 1.0, 2.0, 1.0, 1.0)
PEAK_REF = 0.7


def load_vowels():
    d = json.load(io.open(os.path.join(ROOT, "tables", "vowel_formants.json"), encoding="utf-8"))
    return {v["key"]: v for v in d["vowels"]}


VOW = load_vowels()


def bw_to_r(bw, cap=0.9985):
    return min(cap, math.exp(-math.pi * bw / SR))


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


def constellation(vow, tight, spec, scale=1.0):
    """SPARSE: 3 vowel formants (+1 optional bright peak), the whole set frequency-
    scaled by `scale` to push the morph endpoints to crazy extremes (M0 dragged
    LOW/dark, M100 pushed HIGH/bright) — a wide excursion, not just sharper peaks.
    Sharp poles for distinct peaks; low-control + notches carve dark valleys."""
    forms = [(vow["f1"] * scale, vow["bw1"]), (vow["f2"] * scale, vow["bw2"]),
             (vow["f3"] * scale, vow["bw3"])]
    if spec.get("bright"):
        forms.append((min(0.42 * SR, vow["f3"] * 1.28 * scale), 170.0))  # a 4th high peak
    poles = []
    for f, bw in forms:
        # EXTREME: razor-tight poles even at Q0 -> tall narrow peaks + deep canyons
        # = high contrast / scream. Q100 pins to the unit-circle edge.
        r0 = min(0.9915, bw_to_r(bw * 0.9))                     # sharp relaxed floor
        r = min(0.9985, r0 + 0.9 * (0.9985 - r0)) if tight else r0
        poles.append((f, r))
    n = len(poles)
    nodes = []
    for i, (f, r) in enumerate(poles):
        if i == 0:
            zero = (f * (2.0 ** -0.6), 0.90)                    # low control -> no pedestal
        elif i < n - 1:
            zero = (math.sqrt(f * poles[i + 1][0]), 0.85)       # inter-formant notch (dark valley)
        else:
            zero = (f * (2.0 ** 0.55), 0.6)                     # air rolloff
        nodes.append((f, r, zero))
    return nodes


def cascade_peak(stages):
    peak = 1e-12
    for i in range(170):
        fr = 25.0 * (16000.0 / 25.0) ** (i / 169.0)
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


def factor_and_gain(nodes):
    stages = [list(PASS) for _ in range(STAGES)]
    for i, (pf, pr, z) in enumerate(nodes[:STAGES]):
        zf, zr = z
        stages[i] = _kernel(pf, pr, 1.0 - pr * pr, zf, zr)
    peak = cascade_peak(stages)
    active = sum(1 for s in stages if s != list(PASS))
    per = (PEAK_REF / peak) ** (1.0 / max(1, active))           # gain DERIVED after shape
    for s in stages:
        if s != list(PASS):
            s[4] *= per
    return stages


def build_body(spec):
    """One skeleton, 4 kin photographs. Morph drags the endpoints to crazy extremes:
    M0 = vowel A scaled DOWN (low/dark), M100 = vowel B scaled UP (high/bright). Q =
    relaxed->razor. The middle emerges from the packed interpolation of these four."""
    va, vb = VOW[spec["vowelA"]], VOW[spec["vowelB"]]
    lo = spec.get("low_factor", 0.72)   # drag Morph 0 LOW / dark
    hi = spec.get("high_factor", 1.55)  # push Morph 100 HIGH / bright
    body = {}
    for lbl, vow, scale, tight in [("M0_Q0", va, lo, False), ("M100_Q0", vb, hi, False),
                                   ("M0_Q100", va, lo, True), ("M100_Q100", vb, hi, True)]:
        body[lbl] = factor_and_gain(constellation(vow, tight, spec, scale))
    return body


# Morph 0 = low/dark vowel; Morph 100 = high/bright vowel (F2 rises) — low->high.
BODIES = [
    {"id": "ah_ee", "name": "Ah -> Ee", "vowelA": "aa", "vowelB": "iy", "bright": True},
    {"id": "oh_ee", "name": "Oh -> Ee", "vowelA": "ao", "vowelB": "iy", "bright": True},
    {"id": "uh_ih", "name": "Uh -> Ih", "vowelA": "uh", "vowelB": "ih"},
    {"id": "er_ee", "name": "Er -> Ee", "vowelA": "er", "vowelB": "iy", "bright": True},
    {"id": "er_aa", "name": "Er -> Ah", "vowelA": "er", "vowelB": "aa"},
    {"id": "dark_bright", "name": "Dark Throat -> Bright Front", "vowelA": "uw", "vowelB": "iy", "bright": True},
]


def main():
    audio = "--audio" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CANON, exist_ok=True)
    rpl.NEW = CANON                      # plots read the canonical filters
    rpl.OUT = os.path.join(OUT, "plots")
    os.makedirs(rpl.OUT, exist_ok=True)
    report = {"generator": "vocal_rack2_low_to_high (sparse, high-contrast, low->high; budget = reject filter only)",
              "bodies": {}}
    print(f"{'body':<26} {'low':>5} {'body':>5} {'bite':>5} {'air':>6} peaks maxR  budget")
    for spec in BODIES:
        body = build_body(spec)
        raw = bytearray()
        kfs = []
        for lbl in CORNER_ORDER:
            words = [list(pi.coeffs_to_words(*s)) for s in body[lbl]]
            for w in words:
                for x in w:
                    raw += int(x & 0xFFFF).to_bytes(2, "little")
            kfs.append({"label": lbl, "boost": 1.0, "packedWords": words,
                        "stages": [{"c0": s[0], "c1": s[1], "c2": s[2], "c3": s[3], "c4": s[4]} for s in body[lbl]]})
        cart = os.path.join(CANON, f"{spec['id']}.cart.json")   # canonical filter home
        with open(os.path.join(CANON, f"{spec['id']}.body240"), "wb") as fp:
            fp.write(bytes(raw))
        json.dump({"format": "compiled-v1", "name": spec["name"],
                   "provenance": "vocal_rack2_low_to_high (sparse low->high vowel morph)",
                   "sampleRate": SR, "authoring_sample_rate_hz": SR, "stages": STAGES,
                   "cornerOrder": list(CORNER_ORDER), "keyframes": kfs},
                  open(cart, "w", encoding="utf-8"), indent=2)

        v = rb.judge(cart)  # REJECT FILTER ONLY
        npeaks = sum(1 for s in body["M0_Q0"] if s != list(PASS))
        b = v["bands"]
        verdict = "PASS" if v["pass"] else "REJECT(" + ",".join(k for k, ok in v["gates"].items() if not ok) + ")"
        report["bodies"][spec["id"]] = {"name": spec["name"], "bands": b, "peaks": npeaks,
                                        "max_radius": v["max_radius"], "budget": verdict, "pass": v["pass"]}
        print(f"{spec['name']:<26} {b['low']:>5} {b['body']:>5} {b['bite']:>5} {b['air']:>6} "
              f"{npeaks:>4}  {v['max_radius']:.3f} {verdict}")
        rpl.plot_body(spec["id"], spec["name"], f"low->high · {verdict}")

    json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), indent=2)
    print(f"\ncanonical filters -> {os.path.relpath(CANON, ROOT)}  (.cart.json + .body240)")
    print(f"plots -> {os.path.relpath(rpl.OUT, ROOT)}")
    if audio:
        render_all(report)


def render_all(report):
    from scipy.io import wavfile
    sr = ts.SR_DEFAULT
    tags = []
    for bid, b in report["bodies"].items():
        wd = rpl.words_dict(os.path.join(CANON, f"{bid}.cart.json"))
        n = int(4.0 * sr)
        x = ts.source_signal(n, sr)
        t = np.arange(n) / sr
        morph = 0.5 - 0.5 * np.cos(TAU * 0.4 * t / 4.0)
        q = 0.5 - 0.5 * np.cos(TAU * 0.9 * t / 4.0)
        states = np.zeros((STAGES, 2)); raw = np.zeros(n)
        for i in range(n):
            rows = pi.packed_bilinear(wd, float(morph[i]), float(q[i])); vv = float(x[i])
            for si, row in enumerate(rows):
                b0, b1, b2, a1, a2 = pi.kernel_to_biquad(row)
                y = b0 * vv + states[si, 0]; w1 = b1 * vv - a1 * y + states[si, 1]; w2 = b2 * vv - a2 * y
                if not (math.isfinite(y) and math.isfinite(w1) and math.isfinite(w2)):
                    y = w1 = w2 = 0.0
                states[si, 0], states[si, 1] = w1, w2; vv = y
            raw[i] = vv if math.isfinite(vv) else 0.0
        wet = np.tanh(ts.dc_block(raw, sr) * 4.0)
        pk = float(np.max(np.abs(wet)) + 1e-12)
        if pk > 0.98:
            wet *= 0.98 / pk
        wavfile.write(os.path.join(OUT, f"{bid}_sweep.wav"), sr, wet.astype(np.float32))
        tags.append((bid, b["name"], b["budget"]))
    html = ("<!doctype html><meta charset=utf-8><title>low->high vocal — audition</title>"
            "<style>body{background:#0a0d0c;color:#bec5be;font:14px/1.6 monospace;margin:24px;max-width:760px}"
            "h1{color:#5bef6f}.row{margin:6px 0}.b{color:#69836f}img{width:100%;border:1px solid #1c2722;margin:4px 0}</style>"
            "<h1>Low -> high vocal — sparse / high-contrast</h1>")
    for bid, name, verdict in tags:
        html += (f"<div class=row><b>{name}</b> <span class=b>{verdict}</span><br>"
                 f"<audio controls preload=metadata src='{bid}_sweep.wav'></audio>"
                 f"<img src='plots/{bid}.png'></div>")
    open(os.path.join(OUT, "audition.html"), "w", encoding="utf-8").write(html)
    print(f"audio + audition.html -> {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
