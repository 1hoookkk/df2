#!/usr/bin/env python3
"""Non-formant rack — same complexity as the X3 aggressive frames, but original.

The X3 frames (DJ Alkaline / Dead Ringer / Lucifer's Q ...) are NOT vowels: 7 razor
poles per corner (r 0.92-0.998), inharmonic, carved. We match that COMPLEXITY in our
6-stage / 4-corner format: 6 dense razor poles placed on inharmonic mode sets
(tables/metallic_modes.json) instead of the vowel ladder, with deep zeros carving the
gaps (the anti-formant "teeth"). We copy no X3 values and never touch MorphDesigner —
this is response-first + budget-gated, like the vocal rack.

  python tools/metal_rack.py            # bodies + budget + plots
  python tools/metal_rack.py --audio    # + sweeps + audition.html
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

OUT = os.path.join(ROOT, "dev", "tmp", "metal_rack")          # analysis
CANON = os.path.join(ROOT, "bodies", "non_formant")           # canonical filters
SR = 39062.5
TAU = 2.0 * math.pi
STAGES = 6
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
PASS = (2.0, 1.0, 2.0, 1.0, 1.0)
PEAK_REF = 0.7
NYQ = 0.45 * SR

MODES = {m["key"]: m["ratios"] for m in json.load(io.open(
    os.path.join(ROOT, "tables", "metallic_modes.json"), encoding="utf-8"))["objects"]}


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


def constellation(ratios, fund, tight):
    """6 inharmonic razor poles (ratios x fundamental) + deep zeros carved into the
    WIDE gaps between partials (the metallic 'teeth'/anti-formants) — far from the
    poles so they deepen valleys without eating peaks."""
    f = sorted(min(NYQ, r * fund) for r in ratios)[:STAGES]
    n = len(f)
    nodes = []
    for i, fi in enumerate(f):
        # metal rings hard: high Q even relaxed; Q100 pins to the razor edge
        r0 = 0.986 if fi < 5000 else 0.978
        r = min(0.9985 if fi < 6000 else 0.99, r0 + 0.85 * ((0.9985 if fi < 6000 else 0.99) - r0)) if tight else r0
        zero = None
        if i == 0:
            zero = (fi * (2.0 ** -0.6), 0.9)                     # low control -> no pedestal
        elif i < n and i < len(f):
            # deep notch in the gap toward the next partial, only if the gap is wide
            nxt = f[i + 1] if i + 1 < n else fi * 1.6
            if nxt / fi > 1.6:
                zero = (math.sqrt(fi * nxt), 0.93)               # deep tooth in a wide gap
            else:
                zero = (fi * (2.0 ** 0.5), 0.55)                 # shallow rolloff in a tight cluster
        nodes.append((fi, r, zero))
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
        zf, zr = (z if z else (None, 0.0))
        stages[i] = _kernel(pf, pr, 1.0 - pr * pr, zf, zr)
    peak = cascade_peak(stages)
    active = sum(1 for s in stages if s != list(PASS))
    per = (PEAK_REF / peak) ** (1.0 / max(1, active))
    for s in stages:
        if s != list(PASS):
            s[4] *= per
    return stages


def build_body(spec):
    """Morph A->B is a real structural change of the inharmonic set (different mode
    family and/or fundamental) -> the middle reorganizes (emergent), not a smear."""
    body = {}
    for lbl, which, tight in [("M0_Q0", "A", False), ("M100_Q0", "B", False),
                              ("M0_Q100", "A", True), ("M100_Q100", "B", True)]:
        ratios = MODES[spec["modeA"]] if which == "A" else MODES[spec["modeB"]]
        fund = spec["fundA"] if which == "A" else spec["fundB"]
        body[lbl] = factor_and_gain(constellation(ratios, fund, tight))
    return body


# non-formant materials. modeA/B = inharmonic family, fundA/B = fundamental (Hz).
# the morph reorganizes the mode set (sparse clang <-> dense shimmer, etc.).
MATERIALS = [
    {"id": "clang", "name": "Clang (bar -> plate)", "modeA": "free_bar", "fundA": 260,
     "modeB": "free_plate", "fundB": 520},
    {"id": "bell", "name": "Bell (low -> ringing)", "modeA": "bell", "fundA": 360,
     "modeB": "bell", "fundB": 720},
    {"id": "gong", "name": "Gong (bloom up)", "modeA": "gong", "fundA": 180,
     "modeB": "gong", "fundB": 540},
    {"id": "anvil_plate", "name": "Anvil Plate (shimmer)", "modeA": "free_plate", "fundA": 320,
     "modeB": "free_plate", "fundB": 760},
    {"id": "tine_scream", "name": "Tine Scream (clamped bar)", "modeA": "clamped_bar", "fundA": 300,
     "modeB": "clamped_bar", "fundB": 620},
    {"id": "gong_to_bell", "name": "Gong -> Bell", "modeA": "gong", "fundA": 220,
     "modeB": "bell", "fundB": 640},
]


def main():
    audio = "--audio" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CANON, exist_ok=True)
    rpl.NEW = CANON
    rpl.OUT = os.path.join(OUT, "plots")
    os.makedirs(rpl.OUT, exist_ok=True)
    report = {"generator": "metal_rack (non-formant, inharmonic, X3-complexity; budget=reject filter)", "bodies": {}}
    print(f"{'body':<26} {'low':>5} {'body':>5} {'bite':>5} {'air':>6} poles maxR  budget")
    for spec in MATERIALS:
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
        cart = os.path.join(CANON, f"{spec['id']}.cart.json")
        with open(os.path.join(CANON, f"{spec['id']}.body240"), "wb") as fp:
            fp.write(bytes(raw))
        json.dump({"format": "compiled-v1", "name": spec["name"],
                   "provenance": "metal_rack non-formant (inharmonic mode sets, X3-complexity, response-first)",
                   "sampleRate": SR, "authoring_sample_rate_hz": SR, "stages": STAGES,
                   "cornerOrder": list(CORNER_ORDER), "keyframes": kfs},
                  open(cart, "w", encoding="utf-8"), indent=2)

        v = rb.judge(cart)
        npeaks = sum(1 for s in body["M0_Q0"] if s != list(PASS))
        b = v["bands"]
        verdict = "PASS" if v["pass"] else "REJECT(" + ",".join(k for k, ok in v["gates"].items() if not ok) + ")"
        report["bodies"][spec["id"]] = {"name": spec["name"], "bands": b, "poles": npeaks,
                                        "max_radius": v["max_radius"], "budget": verdict, "pass": v["pass"]}
        print(f"{spec['name']:<26} {b['low']:>5} {b['body']:>5} {b['bite']:>5} {b['air']:>6} "
              f"{npeaks:>4}  {v['max_radius']:.3f} {verdict}")
        rpl.plot_body(spec["id"], spec["name"], f"non-formant · {verdict}")

    json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), indent=2)
    print(f"\ncanonical filters -> {os.path.relpath(CANON, ROOT)}")
    print(f"plots -> {os.path.relpath(rpl.OUT, ROOT)}")
    if audio:
        render_all(report)


def render_all(report):
    from scipy.io import wavfile
    sr = ts.SR_DEFAULT
    rows = []
    for bid, b in report["bodies"].items():
        wd = rpl.words_dict(os.path.join(CANON, f"{bid}.cart.json"))
        n = int(4.0 * sr)
        x = ts.source_signal(n, sr)
        t = np.arange(n) / sr
        morph = 0.5 - 0.5 * np.cos(TAU * 0.4 * t / 4.0)
        q = 0.5 - 0.5 * np.cos(TAU * 0.9 * t / 4.0)
        states = np.zeros((STAGES, 2)); raw = np.zeros(n)
        for i in range(n):
            rws = pi.packed_bilinear(wd, float(morph[i]), float(q[i])); vv = float(x[i])
            for si, row in enumerate(rws):
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
        rows.append((bid, b["name"], b["budget"]))
    html = ("<!doctype html><meta charset=utf-8><title>non-formant rack</title>"
            "<style>body{background:#0a0d0c;color:#bec5be;font:14px/1.6 monospace;margin:24px;max-width:780px}"
            "h1{color:#5bef6f}.b{color:#69836f}img{width:100%;border:1px solid #1c2722;margin:4px 0}</style>"
            "<h1>Non-formant rack — metal / bell / gong (X3-complexity)</h1>")
    for bid, name, verdict in rows:
        html += (f"<div><b>{name}</b> <span class=b>{verdict}</span><br>"
                 f"<audio controls preload=metadata src='{bid}_sweep.wav'></audio>"
                 f"<img src='plots/{bid}.png'></div>")
    open(os.path.join(OUT, "audition.html"), "w", encoding="utf-8").write(html)
    print(f"audio + audition.html -> {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
