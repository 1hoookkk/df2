#!/usr/bin/env python3
"""Vocal rack — author a batch of SKELETAL vocal bodies to audition.

Each body is ONE anatomy: 6 bones (sub · F1 throat · F2 tongue · F3 presence ·
edge · air). The four corners are NOT four independent presets — they are four
photographs of the same skeleton under stress:

    M0_Q0     = vowel A, relaxed   (the floor)
    M100_Q0   = vowel B, relaxed   (same bones, slid to the other vowel)
    M0_Q100   = vowel A, tense     (same freqs, radii cranked)
    M100_Q100 = vowel B, tense     (the ceiling)

Stage i is the same bone in every corner, so the morph middle GLIDES instead of
mushing. Frequencies come from Peterson & Barney (tables/vowel_formants.json);
radii from the bandwidth (r = exp(-pi*bw/sr)) and the vocal atlas corridor; air
is kept on a leash. Pressure is set by a per-corner peak-normalize (gain), never
by moving poles.

Authoring-collect: emits candidates + audio, hands back paths. Picks no winners.

  python tools/vocal_rack.py
"""
from __future__ import annotations

import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)  # ROOT first so pyruntime.* all resolve

import numpy as np  # noqa: E402
from scipy.io import wavfile  # noqa: E402

from pyruntime import packed_interp as pi  # noqa: E402
import teleport_stress as ts  # noqa: E402

OUT = os.path.join(ROOT, "dev", "tmp", "vocal_rack")
AUTH_SR = 39062.5
STAGES = 6
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
BOOST = 3.5
TAU = 2.0 * math.pi


def load_vowels():
    d = json.load(io.open(os.path.join(ROOT, "tables", "vowel_formants.json"), encoding="utf-8"))
    return {v["key"]: v for v in d["vowels"]}


VOW = load_vowels()


def bw_to_r(bw, cap=0.9985):
    return min(cap, math.exp(-math.pi * bw / AUTH_SR))


def tense(r, amount=0.6, cap=0.998):
    """Crank a radius toward the unit circle (narrower/sharper) — the Q axis."""
    return min(cap, r + amount * (cap - r))


# ── one resonant stage (+ optional zero) -> kernel [c0..c4] ──
def resonator(freq, radius, gain, zero_freq=None, zero_radius=0.0):
    theta = TAU * freq / AUTH_SR
    a1 = -2.0 * radius * math.cos(theta)
    a2 = radius * radius
    b0 = gain
    if zero_freq and zero_radius > 0.0:
        tz = TAU * zero_freq / AUTH_SR
        b1 = gain * (-2.0 * zero_radius * math.cos(tz))
        b2 = gain * (zero_radius * zero_radius)
    else:
        b1 = b2 = 0.0
    # kernel: c0=2+b1/b0, c1=1-b2/b0, c2=a1+2, c3=1-a2, c4=b0
    return (2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


def cascade_peak(stages):
    peak = 1e-12
    for i in range(160):
        f = 30.0 * (16000.0 / 30.0) ** (i / 159.0)
        w = TAU * f / AUTH_SR
        mag = 1.0
        for c in stages:
            b0, b1, b2, a1, a2 = c[4], (c[0] - 2) * c[4], (1 - c[1]) * c[4], c[2] - 2, 1 - c[3]
            cw, c2w, sw, s2w = math.cos(w), math.cos(2 * w), math.sin(w), math.sin(2 * w)
            nr, ni = b0 + b1 * cw + b2 * c2w, -b1 * sw - b2 * s2w
            dr, di = 1 + a1 * cw + a2 * c2w, -a1 * sw - a2 * s2w
            mag *= ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)) ** 0.5
        peak = max(peak, mag)
    return peak


def normalize_peak(stages, target=0.5):
    """Spread one scalar gain across stages so the cascade peaks at `target`.
    Pressure/floor discipline: gain only — poles/zeros untouched."""
    peak = cascade_peak(stages)
    per = (target / peak) ** (1.0 / max(1, len(stages)))
    return [(c[0], c[1], c[2], c[3], c[4] * per) for c in stages]


# ── a body = one skeleton; 4 corners are stress photographs of it ──
def build_body(spec):
    va, vb = VOW[spec["vowelA"]], VOW[spec["vowelB"]]
    # 6 bones: (role, freqA, freqB, bw, is_air, nasal_zero?)
    bones = [
        ("sub", spec.get("sub", 150.0), spec.get("sub", 150.0), 110.0, False, None),
        ("F1_throat", va["f1"], vb["f1"], va["bw1"], False, None),
        ("F2_tongue", va["f2"], vb["f2"], va["bw2"], False, spec.get("nasal_zero")),
        ("F3_presence", va["f3"], vb["f3"], va["bw3"], False, None),
        ("edge", spec.get("edge", 3500.0), spec.get("edge", 3500.0), 220.0, False, None),
        ("air", spec.get("air", 7000.0), spec.get("air", 7000.0), 650.0, True, None),
    ]

    def corner(use_b, tight):
        stages = []
        for (_role, fa, fb, bw, is_air, nz) in bones:
            f = fb if use_b else fa
            r = bw_to_r(bw)
            if tight:
                r = tense(r, amount=0.35 if is_air else 0.6, cap=0.965 if is_air else 0.998)
            g = 1.0 - r * r  # peak-tamed seed; normalize sets the floor
            # air: a leash zero above the pole rolls the very top off (atlas: zeros
            # ride near/above the pole). nasal: an anti-formant just below F2.
            zf, zr = (None, 0.0)
            if is_air:
                zf, zr = f * 1.5, 0.55
            elif nz:
                zf, zr = nz, 0.7
            stages.append(resonator(f, r, g, zf, zr))
        return normalize_peak(stages, target=0.5)

    return {
        "M0_Q0": corner(False, False),
        "M100_Q0": corner(True, False),
        "M0_Q100": corner(False, True),
        "M100_Q100": corner(True, True),
    }


# distinct vocal characters; plain-language desc is the audition surface
RACK = [
    {"id": "open_mouth", "name": "Open Mouth", "vowelA": "aa", "vowelB": "iy",
     "desc": "An 'ahh' that opens into 'eee' as you sweep Morph. Big talking vowel."},
    {"id": "dark_throat", "name": "Dark Throat", "vowelA": "uw", "vowelB": "ao",
     "desc": "Deep rounded 'ooo' rolling to 'awww'. Dark, chesty, behind-the-teeth."},
    {"id": "nasal_talk", "name": "Nasal Talk", "vowelA": "eh", "vowelB": "iy",
     "nasal_zero": 1050.0,
     "desc": "Pinched, talkbox-nasal 'ehh' to 'eee' with a hollow notch in the middle."},
    {"id": "bright_front", "name": "Bright Front", "vowelA": "ih", "vowelB": "iy",
     "edge": 3300.0, "air": 7500.0,
     "desc": "Forward, thin, bright 'ihh'-'eee'. Sits up top, in your face."},
    {"id": "hollow_tube", "name": "Hollow Tube", "vowelA": "uw", "vowelB": "uh",
     "sub": 130.0, "edge": 3200.0, "air": 6000.0,
     "desc": "Woody, hollow 'ooo'-'uhh' like blowing across a bottle. Round and dim."},
    {"id": "r_vox", "name": "R-Vox", "vowelA": "er", "vowelB": "aa",
     "desc": "The 'errr' signature opening to 'ahhh'. Vowel-y, characterful, talky."},
]


def main():
    os.makedirs(OUT, exist_ok=True)
    report = {"experiment": "vocal rack — skeletal vocal bodies (audition-collect)",
              "authoring_sr_hz": AUTH_SR, "boost": BOOST, "bodies": {}}
    print(f"Authoring {len(RACK)} skeletal vocal bodies -> {os.path.relpath(OUT, ROOT)}")

    for spec in RACK:
        bid = spec["id"]
        body = build_body(spec)

        # export .body240 + .cart.json (packedWords authority)
        raw = bytearray()
        keyframes = []
        for label in CORNER_ORDER:
            stages = body[label]
            words = [list(pi.coeffs_to_words(*s)) for s in stages]
            for w in words:
                for x in w:
                    raw += int(x & 0xFFFF).to_bytes(2, "little")
            keyframes.append({"label": label, "boost": BOOST, "packedWords": words,
                              "stages": [{"c0": s[0], "c1": s[1], "c2": s[2], "c3": s[3], "c4": s[4]}
                                         for s in stages]})
        assert len(raw) == 240
        with open(os.path.join(OUT, f"{bid}.body240"), "wb") as f:
            f.write(bytes(raw))
        json.dump({"format": "compiled-v1", "name": spec["name"],
                   "provenance": "vocal_rack skeletal author (formant-placed, not ROM-copied)",
                   "sampleRate": AUTH_SR, "authoring_sample_rate_hz": AUTH_SR,
                   "stages": STAGES, "cornerOrder": list(CORNER_ORDER), "keyframes": keyframes},
                  open(os.path.join(OUT, f"{bid}.cart.json"), "w", encoding="utf-8"), indent=2)

        # stability over the morph x Q surface + render (runtime-style path)
        words_dict = {LABEL_TO_KEY[lbl]: [pi.coeffs_to_words(*s) for s in body[lbl]] for lbl in CORNER_ORDER}
        gm = np.linspace(0, 1, 48)
        mm, qq = np.meshgrid(gm, gm)
        stab = ts.static_probe(words_dict, mm.ravel(), qq.ravel())

        vdir = os.path.join(OUT, bid)
        os.makedirs(vdir, exist_ok=True)
        sr = ts.SR_DEFAULT
        n = int(4.0 * sr)
        x = ts.source_signal(n, sr)
        t = np.arange(n) / sr
        morph = 0.5 - 0.5 * np.cos(TAU * 0.4 * t / 4.0)
        q = 0.5 - 0.5 * np.cos(TAU * 0.9 * t / 4.0)
        sweep, _ = render(words_dict, x, morph, q, sr)
        wavfile.write(os.path.join(vdir, "sweep.wav"), sr, sweep)
        xt = ts.source_signal(int(1.25 * sr), sr)
        for mode in ("noise", "square_150hz", "derivative"):
            md, qd = ts.drivers(mode, xt, sr, 0x513DF2)
            wet, _dyn = ts.process_teleport(words_dict, xt, md, qd, sr, 4.0)
            wavfile.write(os.path.join(vdir, f"teleport_{mode}.wav"), sr, wet)

        # skeleton readout (engineering record, not the audition surface)
        def pole_hz(s):
            a1, a2 = s[2] - 2, 1 - s[3]
            r = max(a2, 0) ** 0.5
            return round(math.acos(max(-1, min(1, -a1 / (2 * r)))) * AUTH_SR / TAU, 1) if r > 1e-6 else None
        skeleton = {role: [pole_hz(body[lbl][i]) for lbl in CORNER_ORDER]
                    for i, role in enumerate(["sub", "F1_throat", "F2_tongue", "F3_presence", "edge", "air"])}

        report["bodies"][bid] = {
            "name": spec["name"], "desc": spec["desc"],
            "vowel_morph": f"{spec['vowelA']} -> {spec['vowelB']}",
            "skeleton_pole_hz_per_corner": {"corners": list(CORNER_ORDER), **skeleton},
            "stability": {"max_pole_radius": round(stab["max_pole_radius"], 4),
                          "unstable_denominator_rows": stab["unstable_denominator_rows"],
                          "nonfinite_coeff_rows": stab["nonfinite_coeff_rows"]},
            "files": {"body240": f"{bid}.body240", "cart": f"{bid}.cart.json",
                      "audio_dir": f"{bid}/"},
        }
        st = report["bodies"][bid]["stability"]
        print(f"  {spec['name']:<14} {spec['vowelA']}->{spec['vowelB']:<4} "
              f"maxR={st['max_pole_radius']:.4f} unstable={st['unstable_denominator_rows']} "
              f"nonfinite={st['nonfinite_coeff_rows']}")

    json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), indent=2)
    write_audition_html(report)
    print(f"\nAudition: {os.path.relpath(os.path.join(OUT, 'audition.html'), ROOT)}")


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


def write_audition_html(r):
    blocks = []
    for bid, b in r["bodies"].items():
        st = b["stability"]
        rows = "".join(
            f"<div class=row><b>{lbl}</b><audio controls preload=metadata src='{bid}/{f}'></audio></div>"
            for lbl, f in [("sweep (Morph×Q)", "sweep.wav"),
                           ("teleport · noise", "teleport_noise.wav"),
                           ("teleport · 150 Hz", "teleport_square_150hz.wav"),
                           ("teleport · derivative", "teleport_derivative.wav")]
        )
        blocks.append(
            f"<section><h2>{b['name']}</h2><p class=desc>{b['desc']}</p>"
            f"<p class=meta>Morph sweeps the vowel; Q tightens it. "
            f"(stable: max radius {st['max_pole_radius']}, unstable {st['unstable_denominator_rows']})</p>"
            f"{rows}</section>"
        )
    html = (
        "<!doctype html><meta charset=utf-8><title>Vocal rack — audition</title>"
        "<style>body{background:#0a0d0c;color:#bec5be;font:14px/1.6 monospace;margin:24px;max-width:780px}"
        "h1{color:#5bef6f}h2{color:#31c6c9;margin-top:30px;margin-bottom:2px}.desc{color:#cdd8cf;margin:2px 0 6px}"
        ".meta{color:#69836f;font-size:12px;margin:0 0 8px}.row{margin:5px 0;display:flex;gap:10px;align-items:center}"
        ".row b{display:inline-block;min-width:150px}audio{height:30px}</style>"
        "<h1>Vocal rack — pick the ones that talk to you</h1>"
        "<p class=meta>Each is one vocal 'instrument'. Drag-feel: <b>sweep</b> = slow Morph×Q glide; "
        "<b>teleport</b> = the same body slammed around the pad. Listen, keep the winners, ignore the rest.</p>"
        + "\n".join(blocks)
    )
    open(os.path.join(OUT, "audition.html"), "w", encoding="utf-8").write(html)


if __name__ == "__main__":
    main()
