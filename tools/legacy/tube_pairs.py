#!/usr/bin/env python3
"""Coupled-cavity A/B — test the "tube vs EQ" hypothesis by ear.

Tyson's claim: a vocal filter sounds like a physical tube (not resonant EQ bands)
when its poles and zeros COUPLE into cavity pairs — each formant pole gets an
anti-resonance (zero) in the valley above it, the way a real vocal tract's side
branches carve inter-formant notches. The vocal atlas backs this: the ROM/Hedz
bodies carry a zero on ~100% of their poles; the all-pole rack left them off.

This takes each rack body and adds COUPLED ZEROS to the three vowel formants
(F1/F2/F3) — turning them into 3 cavity pairs — WITHOUT moving any pole (identity
+ morph kinship preserved). It renders the coupled version next to the original
all-pole one so the difference ("clean vowel" vs "squeezed tube") is audible.

  python tools/tube_pairs.py
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
import teleport_stress as ts  # noqa: E402
import vocal_rack as vr  # noqa: E402  (reuse resonator / normalize_peak / render)

RACK = os.path.join(ROOT, "dev", "tmp", "vocal_rack")
OUT = os.path.join(ROOT, "dev", "tmp", "vocal_rack_tube")
SR = vr.AUTH_SR
TAU = 2.0 * math.pi
ZERO_RADIUS = 0.88  # cavity anti-resonance depth (real notch, not infinite)
# stage roles, in the order vocal_rack authored them
ROLES = ["sub", "F1_throat", "F2_tongue", "F3_presence", "edge", "air"]
CAVITY_STAGES = [1, 2, 3]  # F1, F2, F3 get a coupled zero -> 3 cavity pairs


def pole_of(stage):
    a1, a2 = stage[2] - 2.0, 1.0 - stage[3]
    r = max(a2, 0.0) ** 0.5
    f = math.acos(max(-1.0, min(1.0, -a1 / (2.0 * r)))) * SR / TAU if r > 1e-6 else None
    return f, r


def load_corners(bid):
    d = json.load(io.open(os.path.join(RACK, f"{bid}.cart.json"), encoding="utf-8"))
    by = {kf["label"]: [pi.words_to_coeffs(tuple(w)) for w in kf["packedWords"]] for kf in d["keyframes"]}
    return d["name"], by


def couple_corner(stages):
    """Add an inter-formant coupled zero to F1/F2/F3; keep their poles; renorm."""
    poles = [pole_of(s) for s in stages]
    out = list(stages)
    for i in CAVITY_STAGES:
        pf, pr = poles[i]
        if pf is None:
            continue
        nf, _ = poles[i + 1] if i + 1 < len(poles) else (None, None)
        # zero in the valley toward the next formant (geometric mean) = the cavity
        # anti-resonance. If no next pole, sit it ~2/3 octave above.
        zf = math.sqrt(pf * nf) if nf and nf > pf else pf * 1.6
        g = stages[i][4]  # keep this stage's existing gain; only add the zero shape
        out[i] = vr.resonator(pf, pr, g, zf, ZERO_RADIUS)
    return vr.normalize_peak(out, target=0.5)


def main():
    os.makedirs(OUT, exist_ok=True)
    report = json.load(io.open(os.path.join(RACK, "report.json"), encoding="utf-8"))
    ids = list(report["bodies"].keys())
    sr = ts.SR_DEFAULT
    out_report = {"experiment": "coupled-cavity A/B (tube-vs-EQ test)",
                  "zero_radius": ZERO_RADIUS, "cavity_stages": CAVITY_STAGES, "bodies": {}}
    print(f"Building coupled-cavity variants for {len(ids)} bodies -> {os.path.relpath(OUT, ROOT)}")

    for bid in ids:
        name, corners = load_corners(bid)
        coupled = {lbl: couple_corner(corners[lbl]) for lbl in vr.CORNER_ORDER}

        # pack -> body240 + cart.json
        raw = bytearray()
        keyframes = []
        for lbl in vr.CORNER_ORDER:
            words = [list(pi.coeffs_to_words(*s)) for s in coupled[lbl]]
            for w in words:
                for x in w:
                    raw += int(x & 0xFFFF).to_bytes(2, "little")
            keyframes.append({"label": lbl, "boost": vr.BOOST, "packedWords": words,
                              "stages": [{"c0": s[0], "c1": s[1], "c2": s[2], "c3": s[3], "c4": s[4]} for s in coupled[lbl]]})
        with open(os.path.join(OUT, f"{bid}_tube.body240"), "wb") as f:
            f.write(bytes(raw))
        json.dump({"format": "compiled-v1", "name": f"{name} (tube)",
                   "provenance": "tube_pairs coupled-cavity variant (poles preserved, inter-formant zeros added)",
                   "sampleRate": SR, "authoring_sample_rate_hz": SR, "stages": vr.STAGES,
                   "cornerOrder": list(vr.CORNER_ORDER), "keyframes": keyframes},
                  open(os.path.join(OUT, f"{bid}_tube.cart.json"), "w", encoding="utf-8"), indent=2)

        # stability + render the coupled version (all-pole already rendered in vocal_rack/)
        words_dict = {vr.LABEL_TO_KEY[lbl]: [pi.coeffs_to_words(*s) for s in coupled[lbl]] for lbl in vr.CORNER_ORDER}
        gm = np.linspace(0, 1, 48)
        mm, qq = np.meshgrid(gm, gm)
        stab = ts.static_probe(words_dict, mm.ravel(), qq.ravel())

        vdir = os.path.join(OUT, bid)
        os.makedirs(vdir, exist_ok=True)
        n = int(4.0 * sr)
        x = ts.source_signal(n, sr)
        t = np.arange(n) / sr
        morph = 0.5 - 0.5 * np.cos(TAU * 0.4 * t / 4.0)
        q = 0.5 - 0.5 * np.cos(TAU * 0.9 * t / 4.0)
        sweep, nf = vr.render(words_dict, x, morph, q, sr)
        wavfile.write(os.path.join(vdir, "sweep.wav"), sr, sweep)
        xt = ts.source_signal(int(1.25 * sr), sr)
        md, qd = ts.drivers("derivative", xt, sr, 0x513DF2)
        wet, _ = ts.process_teleport(words_dict, xt, md, qd, sr, 4.0)
        wavfile.write(os.path.join(vdir, "teleport_derivative.wav"), sr, wet)

        # depth of inter-formant notches (the measurable "tube" signature)
        m0 = coupled["M0_Q0"]
        out_report["bodies"][bid] = {
            "name": name,
            "coupled_cavities": len(CAVITY_STAGES),
            "stability": {"max_pole_radius": round(stab["max_pole_radius"], 4),
                          "unstable_denominator_rows": stab["unstable_denominator_rows"],
                          "nonfinite_coeff_rows": stab["nonfinite_coeff_rows"]},
            "render_nonfinite": nf,
        }
        st = out_report["bodies"][bid]["stability"]
        print(f"  {name:<14} +3 cavity pairs  maxR={st['max_pole_radius']:.4f} "
              f"unstable={st['unstable_denominator_rows']} nonfinite={st['nonfinite_coeff_rows']}")

    json.dump(out_report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), indent=2)
    write_ab_html(out_report)
    print(f"\nA/B: {os.path.relpath(os.path.join(OUT, 'audition_ab.html'), ROOT)}")


def write_ab_html(r):
    blocks = []
    for bid, b in r["bodies"].items():
        st = b["stability"]
        blocks.append(
            f"<section><h2>{b['name']}</h2>"
            f"<p class=meta>same skeleton, same poles. left = clean resonators (all-pole). "
            f"right = +3 coupled cavity pairs (inter-formant zeros). "
            f"(stable: max r {st['max_pole_radius']})</p>"
            f"<div class=ab>"
            f"<div class=col><div class=tag>ALL-POLE (EQ-ish)</div>"
            f"<div class=row><b>sweep</b><audio controls preload=metadata src='../vocal_rack/{bid}/sweep.wav'></audio></div>"
            f"<div class=row><b>teleport</b><audio controls preload=metadata src='../vocal_rack/{bid}/teleport_derivative.wav'></audio></div></div>"
            f"<div class=col><div class=tag>COUPLED CAVITIES (tube)</div>"
            f"<div class=row><b>sweep</b><audio controls preload=metadata src='{bid}/sweep.wav'></audio></div>"
            f"<div class=row><b>teleport</b><audio controls preload=metadata src='{bid}/teleport_derivative.wav'></audio></div></div>"
            f"</div></section>"
        )
    html = (
        "<!doctype html><meta charset=utf-8><title>Tube vs EQ — A/B</title>"
        "<style>body{background:#0a0d0c;color:#bec5be;font:14px/1.6 monospace;margin:24px;max-width:900px}"
        "h1{color:#5bef6f}h2{color:#31c6c9;margin:28px 0 2px}.meta{color:#69836f;font-size:12px;margin:0 0 8px}"
        ".ab{display:flex;gap:24px}.col{flex:1}.tag{color:#e8a33d;font-size:12px;margin-bottom:4px}"
        ".row{margin:4px 0;display:flex;gap:8px;align-items:center}.row b{min-width:64px}audio{height:30px}</style>"
        "<h1>Tube vs EQ — the coupled-cavity test</h1>"
        "<p class=meta>Same bodies, same poles/skeleton. The only difference: the right column adds a "
        "coupled zero in the valley above F1/F2/F3 (3 cavity pairs), like the ROM bodies. "
        "Your ear's job: which side sounds like a plastic tube being squeezed, and which sounds like EQ bumps?</p>"
        + "\n".join(blocks)
    )
    open(os.path.join(OUT, "audition_ab.html"), "w", encoding="utf-8").write(html)


if __name__ == "__main__":
    main()
