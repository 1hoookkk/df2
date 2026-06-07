#!/usr/bin/env python
"""make_targets.py - sample reference filter-type RESPONSE CURVES as a dev-only
calibration yardstick for the Forge ghost overlay.

CLEAN-ROOM: this writes sampled MAGNITUDE BEHAVIOUR (dB curves on a freq grid),
anonymized to functional labels - NOT coefficients, NOT packed bytes, NOT vendor
names. It is a study yardstick inside the dev tool, never shipped in the product.
We measure behaviour to learn the grammar, then author ORIGINAL bodies. We do not
copy or ship the structure of any specific reference.
"""
import os, math, sys, json, cmath
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyruntime import minifloat

SR = 39062.5
F_LO, F_HI, N = 30.0, 18000.0, 128
GRID = [F_LO*(F_HI/F_LO)**(i/(N-1)) for i in range(N)]
MS = [0.0, 0.5, 1.0]
QS = [0.0, 0.5, 1.0]

# (folder, functional label, type) - labels are FUNCTIONAL descriptions, never the names.
REFS = [
    ("P2k_013_talking_hedz", "vowel glide", "VOW"),
    ("P2k_029_lucifer_s_q",  "violent Q",   "REZ"),
    ("P2k_001_megasweepz",   "hard sweep",  "LPF"),
    ("P2k_022_deep_bouche",  "deep cavity", "VOW"),
    ("P2k_018_razor_blades", "razor cut",   "EQ-"),
]

def lerp_u16(a, b, frac):
    diff = (b & 0xffff) - (a & 0xffff)
    delta = int(math.trunc(diff*frac))
    u = delta & 0xffff
    delta = u-0x10000 if u >= 0x8000 else u
    return (delta + (a & 0xffff)) & 0xffff

def words_at(C, m, q):
    A, B, Cc, D = C
    out = []
    for s in range(6):
        row = []
        for w in range(5):
            e0 = lerp_u16(A[s][w], B[s][w], m)
            e1 = lerp_u16(Cc[s][w], D[s][w], m)
            row.append(lerp_u16(e0, e1, q))
        out.append(row)
    return out

def mag(words, f):
    z = cmath.exp(-1j*2*math.pi*f/SR)
    tot = 0.0
    for w in words:
        d = [minifloat.decode(x) for x in w]
        c0, c1, c2, c3, c4 = 4*d[0]+d[1], d[1], 4*d[2]+d[3], d[3], 4*d[4]
        b = [c4, (c0-2)*c4, (1-c1)*c4, c2-2, 1-c3]
        num = b[0]+b[1]*z+b[2]*z*z
        den = 1+b[3]*z+b[4]*z*z
        tot += 20*math.log10(max(1e-9, abs(num)/max(1e-9, abs(den))))
    return tot

def corners_of(path):
    b = open(path, "rb").read()
    C, p = [], 0
    for _ in range(4):
        st = []
        for _ in range(6):
            st.append([b[p+2*k] | (b[p+2*k+1] << 8) for k in range(5)]); p += 10
        C.append(st)
    return C

def main():
    out = []
    for folder, label, typ in REFS:
        d = os.path.join(ROOT, "ref/p2k_variants", folder)
        fn = next(x for x in os.listdir(d) if x.startswith("variant_0_"))
        C = corners_of(os.path.join(d, fn))
        grid = [[[round(mag(words_at(C, m, q), f), 2) for f in GRID] for q in QS] for m in MS]
        out.append({"label": label, "type": typ, "grid": grid})
        print(f"  {label} ({typ})")
    path = os.path.join(ROOT, "forge-web/data/targets.js")
    with open(path, "w") as fp:
        fp.write("/* DEV STUDY ONLY - sampled magnitude behaviour of reference filter types,\n")
        fp.write("   anonymized to functional labels, as a calibration yardstick. NOT coefficients,\n")
        fp.write("   NOT shipped in the product. Measure behaviour -> learn grammar -> author originals. */\n")
        fp.write(f"export const TARGET_FLO={F_LO}, TARGET_FHI={F_HI};\n")
        fp.write("export const TARGETS=" + json.dumps(out, separators=(",", ":")) + ";\n")
    print(f"\nwrote {len(out)} targets -> {path}")

if __name__ == "__main__":
    main()
