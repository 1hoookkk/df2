#!/usr/bin/env python3
"""physical_corners.py — build df2 TRENCH corners from REAL physical models.

A corner is a spectral shape (6 resonant sections). Physical models give the
resonances directly: their modal frequencies + dampings ARE the poles, and any
anti-resonances ARE the zeros. No WAV, no fitting. We build 4 distinct corners
(exactly like the ROM's 4 verbatim corners) and write a compiled-v1 cartridge to
~/Documents/TRENCH/authoring_slot.json — the running TRENCH hot-reloads it.

Models:
  tract  — Kelly-Lochbaum lossless tube from a vocal-tract area function
           (reflection coeffs -> all-pole polynomial -> roots = formants).
  tube   — open/closed cylindrical pipe resonances.
  modal  — bar / membrane / string / plate modal ratios.

Usage:
  python physical_corners.py                       # default: vowel morph u->a / i->ae
  python physical_corners.py --model modal --kind bell
  python physical_corners.py --list-formants       # print the physics, don't write
"""
from __future__ import annotations
import argparse, json, math, os
import numpy as np

SR       = 39062.5     # df2 authoring / cartridge rate
C_CM     = 35000.0     # speed of sound, cm/s
NSTAGES  = 6
PASS     = [2.0, 1.0, 2.0, 1.0, 1.0]
LABELS   = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]

# ── a resonant section (pole pair) + optional anti-resonance (zero pair) ────────
def kernel_section(f, bw, gain, sr=SR, zero_f=None, zero_r=0.0):
    rp  = min(math.exp(-math.pi * bw / sr), 0.9985)        # stable, musical cap
    thp = 2 * math.pi * f / sr
    a1, a2 = -2 * rp * math.cos(thp), rp * rp
    if zero_f and zero_f > 0:
        thz = 2 * math.pi * zero_f / sr
        b0, b1, b2 = gain, -2 * zero_r * math.cos(thz) * gain, zero_r * zero_r * gain
    else:
        b0, b1, b2 = gain, 0.0, 0.0
    return [2 + b1 / b0, 1 - b2 / b0, a1 + 2.0, 1 - a2, b0]   # df2 kernel form

def _section_mag(k, w):
    c0, c1, c2, c3, c4 = k
    b0, b1, b2, a1, a2 = c4, (c0 - 2) * c4, (1 - c1) * c4, c2 - 2, 1 - c3
    cw, c2w, sw, s2w = math.cos(w), math.cos(2 * w), math.sin(w), math.sin(2 * w)
    nr, ni = b0 + b1 * cw + b2 * c2w, -b1 * sw - b2 * s2w
    dr, di = 1 + a1 * cw + a2 * c2w, -a1 * sw - a2 * s2w
    return math.sqrt((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30))

def _peak(sections, sr=SR):
    peak = 1e-9
    for i in range(160):
        w = 2 * math.pi * (40.0 * (16000.0 / 40.0) ** (i / 159.0)) / sr
        m = 1.0
        for k in sections:
            m *= _section_mag(k, w)
        peak = max(peak, m)
    return peak

def build_corner(modes, zeros=None, target_peak=2.0):
    """modes: [(freq_hz, bandwidth_hz, gain)]; zeros: [freq_hz] anti-resonances."""
    modes = sorted(modes, key=lambda m: -m[2])[:NSTAGES]   # keep the strongest
    modes = sorted(modes, key=lambda m: m[0])              # order low->high
    zeros = zeros or []
    secs = []
    for f, bw, g in modes:
        zf = None
        if zeros:
            cand = min(zeros, key=lambda z: abs(math.log2(max(z, 1) / max(f, 1))))
            if abs(math.log2(max(cand, 1) / max(f, 1))) < 1.1:
                zf = cand
        secs.append(kernel_section(f, bw, g, zero_f=zf, zero_r=0.7 if zf else 0.0))
    while len(secs) < NSTAGES:
        secs.append(PASS[:])
    n_active = sum(1 for s in secs if s != PASS)
    if n_active:
        g = (target_peak / _peak(secs)) ** (1.0 / n_active)
        for s in secs:
            if s != PASS:
                s[4] *= g
    return secs

# ── 1. VOCAL TRACT (Kelly-Lochbaum lossless tube) ──────────────────────────────
def _rc_to_poly(rc):
    a = np.array([1.0])
    for k in rc:
        a = np.append(a, 0.0) + k * np.append(0.0, a[::-1])
    return a

def tract_formants(area, length_cm=17.5, n_form=6, sections=28):
    area = np.asarray(area, float)
    # resample the area function to `sections` cylinders (better formant resolution)
    if len(area) != sections:
        xp = np.linspace(0.0, 1.0, len(area))
        area = np.interp(np.linspace(0.0, 1.0, sections), xp, area)
    N = len(area)
    fs = C_CM / (2.0 * (length_cm / N))                    # tract's own sample rate
    rc = [(area[i] - area[i + 1]) / (area[i] + area[i + 1]) for i in range(N - 1)]
    rc.append(-0.9)                                        # open lip radiation
    roots = np.roots(_rc_to_poly(rc))
    poles = []
    for r in roots:
        if abs(r) < 1.0 and r.imag > 1e-6:
            f  = math.atan2(r.imag, r.real) * fs / (2 * math.pi)
            bw = -math.log(abs(r)) * fs / math.pi
            if 80 < f < min(fs / 2, 11000) and bw < 900:
                poles.append((f, max(bw, 45.0), 1.0))
    poles.sort(key=lambda p: p[0])
    return poles[:n_form]

# approximate vocal-tract area functions, glottis -> lip (cm^2)
VOWELS = {
    "schwa": [1, 1, 1, 1, 1, 1, 1, 1],
    # glottis -> lip (cm^2). Sharp constrictions; big cavities give low F1.
    "a":  [0.3, 0.3, 0.4, 0.6, 1.2, 3.0, 6.0, 8.0, 8.0],   # tight pharynx, wide mouth: HIGH F1
    "i":  [3.0, 5.0, 6.0, 6.0, 5.0, 0.25, 0.2, 1.2, 3.0],  # wide pharynx, tight palate: LOW F1 / HIGH F2
    "u":  [2.0, 4.0, 7.0, 7.0, 4.0, 1.5, 0.5, 0.2, 0.25],  # wide mid, tight lips: LOW F1 / LOW F2
    "ae": [0.4, 0.4, 0.6, 1.2, 2.5, 4.0, 4.5, 3.0, 2.0],   # near-open front
    "o":  [0.5, 0.8, 2.0, 4.5, 4.0, 1.5, 0.8, 0.7, 0.9],
    "e":  [2.0, 3.0, 4.0, 3.0, 1.5, 0.8, 1.5, 2.5],
}

def vowel_corner(name, length_cm=17.5):
    return build_corner(tract_formants(VOWELS[name], length_cm))

# ── 2. TUBE / HORN ──────────────────────────────────────────────────────────────
def tube_modes(length_cm, ends="closed-open", n=6, q=11):
    if ends == "closed-open":
        freqs = [(2 * k - 1) * C_CM / (4 * length_cm) for k in range(1, n + 1)]
    else:                                                  # open-open / closed-closed
        freqs = [k * C_CM / (2 * length_cm) for k in range(1, n + 1)]
    return [(f, f / q, 1.0) for f in freqs if f < 12000]

# ── 3. MODAL BODIES ─────────────────────────────────────────────────────────────
MODAL = {                          # modal frequency ratios
    "bar":      [1.0, 2.756, 5.404, 8.933, 13.35, 18.65],   # free-free bar
    "membrane": [1.0, 1.593, 2.136, 2.295, 2.653, 2.917],   # circular drum
    "plate":    [1.0, 1.71, 2.43, 3.18, 4.05, 5.06],
    "bell":     [0.5, 1.0, 1.183, 1.506, 2.0, 2.514],       # minor-third bell-ish
}
def modal_modes(kind, f0, q=55, n=6):
    if kind == "string":
        B = 0.0008
        ratios = [k * math.sqrt(1 + B * k * k) for k in range(1, n + 1)]
    else:
        ratios = MODAL[kind][:n]
    return [(f0 * r, f0 * r / q, 1.0 / (1 + i * 0.25)) for i, r in enumerate(ratios) if f0 * r < 13000]

# ── a deterministic starter corner from any physical model ─────────────────────
def corner_from_spec(spec):
    m = spec[0]
    if m == "tract":
        return vowel_corner(spec[1])
    if m == "tube":
        return build_corner(tube_modes(spec[1], spec[2] if len(spec) > 2 else "closed-open"))
    if m == "modal":
        return build_corner(modal_modes(spec[1], spec[2]))
    raise ValueError(f"unknown corner spec {spec}")

# Curated physical starters = 4 audition corners each (M0_S0 / M1_S0 / M0_S1 /
# M1_S1). They feed editable Forge lanes; they are not finished bodies.
PRESETS = {
    # single-domain morphs
    "vox":          [("tract", "u"), ("tract", "a"), ("tract", "i"), ("tract", "ae")],
    "pipes":        [("tube", 30.0), ("tube", 18.0), ("tube", 11.0), ("tube", 7.0)],
    "bells":        [("modal", "bell", 170.0), ("modal", "bell", 250.0), ("modal", "bell", 380.0), ("modal", "bell", 540.0)],
    "glass":        [("modal", "plate", 300.0), ("modal", "plate", 470.0), ("modal", "plate", 680.0), ("modal", "plate", 940.0)],
    "skins":        [("modal", "membrane", 90.0), ("modal", "membrane", 150.0), ("modal", "membrane", 240.0), ("modal", "membrane", 360.0)],
    # cross-physics morphs (the crazy filters)
    "throat_metal": [("tract", "a"), ("tract", "i"), ("modal", "bell", 300.0), ("modal", "membrane", 220.0)],
    "morph_worlds": [("tube", 24.0), ("tract", "a"), ("modal", "bell", 330.0), ("modal", "membrane", 180.0)],
    "cavern":       [("tube", 32.0), ("tube", 12.0), ("modal", "plate", 260.0), ("modal", "bell", 200.0)],
    "string_voice": [("modal", "string", 110.0), ("modal", "string", 220.0), ("tract", "i"), ("tract", "u")],
}

# ── cartridge assembly + hot-reload write ───────────────────────────────────────
def write_cartridge(corners, name, boost=1.5):
    kfs = []
    for lbl, corner in zip(LABELS, corners):
        kfs.append({"label": lbl, "boost": boost,
                    "stages": [{"c0": s[0], "c1": s[1], "c2": s[2], "c3": s[3], "c4": s[4]} for s in corner]})
    cart = {"format": "compiled-v1", "name": name, "sampleRate": SR, "stages": NSTAGES, "keyframes": kfs}
    js = json.dumps(cart, indent=1)
    slot = os.path.expanduser("~/Documents/TRENCH/authoring_slot.json")
    os.makedirs(os.path.dirname(slot), exist_ok=True)
    with open(slot, "w") as f:
        f.write(js)
    return slot

def report(corners, names):
    print(f"\n{'corner':<12} formants/modes (Hz, strongest 6)")
    print("-" * 60)
    for nm, c in zip(names, corners):
        fr = []
        for s in c:
            if s == PASS:
                continue
            a1, a2 = s[2] - 2, 1 - s[3]
            r = math.sqrt(max(a2, 0))
            if r > 1e-6:
                fr.append(int(round(math.acos(max(-1, min(1, -a1 / (2 * r)))) * SR / (2 * math.pi))))
        print(f"{nm:<12} {sorted(fr)}")

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", choices=sorted(PRESETS), default=None,
                    help="curated physical starter — 4 audition corners for Forge editing")
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--model", choices=["tract", "tube", "modal"], default="tract")
    ap.add_argument("--vowels", nargs=4, default=["u", "a", "i", "ae"])
    ap.add_argument("--length", type=float, default=17.5, help="tract/tube length cm")
    ap.add_argument("--kind", default="bell", help="modal: bar|membrane|plate|bell|string")
    ap.add_argument("--f0", type=float, default=180.0, help="modal fundamental Hz")
    ap.add_argument("--name", default=None)
    ap.add_argument("--list-formants", action="store_true", help="print physics, do not write")
    a = ap.parse_args()

    if a.list_presets:
        print("physical bodies (--preset):")
        for k in sorted(PRESETS):
            kinds = " -> ".join(s[1] if s[0] == "tract" else f"{s[0]}{s[1] if s[0]!='modal' else ' '+str(s[1])}" for s in PRESETS[k])
            print(f"  {k:<14} {kinds}")
        return

    if a.preset:
        names = [s[1] if s[0] == "tract" else f"{s[0]}:{s[1]}" for s in PRESETS[a.preset]]
        corners = [corner_from_spec(s) for s in PRESETS[a.preset]]
        report(corners, names)
        slot = write_cartridge(corners, a.name or f"phys_{a.preset}")
        print(f"\nwrote {a.preset}  ->  {slot}\n(running TRENCH hot-reloads within ~0.5s)")
        return

    if a.model == "tract":
        names = a.vowels
        corners = [vowel_corner(v, a.length) for v in names]
        name = a.name or "phys_tract_" + "".join(names)
    elif a.model == "tube":
        # four lengths = a morph through pipe sizes
        lens = [a.length * m for m in (1.6, 1.0, 0.66, 0.45)]
        names = [f"tube{int(l)}cm" for l in lens]
        corners = [build_corner(tube_modes(l)) for l in lens]
        name = a.name or "phys_tube"
    else:
        f0s = [a.f0, a.f0 * 1.5, a.f0 * 2.25, a.f0 * 3.0]
        names = [f"{a.kind}{int(f)}" for f in f0s]
        corners = [build_corner(modal_modes(a.kind, f)) for f in f0s]
        name = a.name or f"phys_{a.kind}"

    report(corners, names)
    if a.list_formants:
        print("\n(--list-formants: nothing written)")
        return
    slot = write_cartridge(corners, name)
    print(f"\nwrote {name}  ->  {slot}\n(running TRENCH hot-reloads within ~0.5s)")

if __name__ == "__main__":
    main()
