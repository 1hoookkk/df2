#!/usr/bin/env python
"""mine_frames.py - quarry rich real-physics frames for the df2 Forge picker.

Runs the physical-corners skill across its presets, takes each corner's REAL
poles (modal/formant resonances), and COMPILES a full talking_hedz-shaped
frame from them: a low-shelf BODY (low pole + banished-high zero -> broad
hump), the physical resonances as formant PEAKS (each a pole + a hugging zero
just above for definition), and descending terrain. Every section is a real
pole+zero pair - no bare resonators. Engine-faithful packed words via the
canonical pyruntime.minifloat owner.

DO NOT INVENT POLES: the character poles are the physical model's own
resonances. The body shelf is a deterministic low-frequency foundation; the
zeros are articulation on real poles.
"""
import json, math, os, subprocess, sys, cmath

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyruntime import minifloat

SKILL = os.path.join(ROOT, ".claude/skills/physical-corners/physical_corners.py")
SLOT = os.path.expanduser("~/Documents/TRENCH/authoring_slot.json")
SR = 39062.5
NY = SR * 0.49
PRESETS = ["vox", "pipes", "bells", "glass", "skins", "cavern",
           "morph_worlds", "throat_metal", "string_voice"]

def clampf(f): return max(20.0, min(NY, f))

def section_words(pf, pr, zf, zr, loud):
    """One pole+zero section -> 5 packed words (unity-DC gain * loud)."""
    pf, zf = clampf(pf), clampf(zf)
    wp = 2*math.pi*pf/SR
    a1, a2 = -2*pr*math.cos(wp), pr*pr
    wz = 2*math.pi*zf/SR
    nb1, nb2 = -2*zr*math.cos(wz), zr*zr
    g = (1+a1+a2)/((1+nb1+nb2) or 1e-9) * loud
    b0, b1, b2 = g, g*nb1, g*nb2
    c4 = b0
    c0 = b1/c4+2 if c4 else 2.0
    c1 = 1-b2/c4 if c4 else 1.0
    c2, c3 = a1+2, 1-a2
    d = [(c0-c1)/4.0, c1, (c2-c3)/4.0, c3, c4/4.0]
    return [minifloat.encode(x) for x in d]

def lift_r(r):
    return min(0.9985, r + (1.0-r)*0.6) if r > 1e-4 else r

def pole_of_stage(s):
    a1, a2 = s["c2"]-2.0, 1.0-s["c3"]
    if a2 <= 0: return None
    r = math.sqrt(a2)
    if r < 0.5: return None
    c = max(-1.0, min(1.0, -a1/(2*r)))
    f = math.acos(c)*SR/(2*math.pi)
    return (f, min(r, 0.9982)) if 40 < f < NY else None

def build_sections(poles):
    """poles: sorted (f,r) ascending. -> 6 sections: body shelf + 5 formant peaks."""
    body_f = max(85.0, min(185.0, poles[0][0]*0.42))
    secs = [(body_f, 0.965, 7000.0, 0.62, 0.40)]         # low-shelf BODY (lighter; was swamping)
    for i, (pf, pr) in enumerate(poles[:5]):
        loud = 0.85 * (0.90**i)                           # gentler descending terrain
        secs.append((pf, pr, pf*1.18, min(0.97, pr*0.93), loud))   # formant peak + hugging zero
    while len(secs) < 6:
        secs.append((6000.0, 0.7, 7000.0, 0.6, 0.2))      # air pad (rare)
    return secs[:6]

# ---- analysis (centroid + roundtrip self-check) ----
def words_biquad(w):
    d = [minifloat.decode(x) for x in w]
    c0, c1, c2, c3, c4 = 4*d[0]+d[1], d[1], 4*d[2]+d[3], d[3], 4*d[4]
    return [c4, (c0-2)*c4, (1-c1)*c4, c2-2, 1-c3]
def mag_db(b, f):
    z = cmath.exp(-1j*2*math.pi*f/SR)
    return 20*math.log10(max(1e-9, abs(b[0]+b[1]*z+b[2]*z*z)/max(1e-9, abs(1+b[3]*z+b[4]*z*z))))
# character frequency = loudness-weighted geometric mean of the FORMANT pole
# frequencies (skip the shared body). This is what makes a frame dark or bright,
# so the strip sorts/colours by character, not by the body every frame has.
def char_hz(secs):
    num = den = 0.0
    for (pf, pr, zf, zr, loud) in secs[1:]:
        num += math.log(pf)*loud; den += loud
    return math.exp(num/den) if den > 0 else 1000.0

def main():
    frames = []
    for p in PRESETS:
        subprocess.run([sys.executable, SKILL, "--preset", p], capture_output=True, text=True)
        if not os.path.exists(SLOT):
            print(f"  !! {p}: no slot"); continue
        d = json.load(open(SLOT))
        for i, kf in enumerate(d["keyframes"]):
            poles = sorted(filter(None, (pole_of_stage(s) for s in kf["stages"])), key=lambda x: x[0])
            if len(poles) < 2:
                print(f"  ~~ {p}-{i}: only {len(poles)} poles, skipped"); continue
            secs = build_sections(poles)
            words = [section_words(*s) for s in secs]
            words_hi = [section_words(s[0], lift_r(s[1]), s[2], s[3], s[4]) for s in secs]
            frames.append({"id": f"{p}-{i}", "source": p, "words": words,
                           "wordsHiQ": words_hi, "centroid": round(char_hz(secs), 1)})
        print(f"  {p}: {sum(1 for f in frames if f['source']==p)} frames")
    frames.sort(key=lambda f: f["centroid"])
    out = os.path.join(ROOT, "forge-web/data/frames.js")
    with open(out, "w") as fp:
        fp.write("/* mined by tools/mine_frames.py - real-physics poles compiled into rich\n")
        fp.write("   body-shelf + formant-peak frames (every section pole+zero). Engine-faithful\n")
        fp.write(f"   packed words. {len(frames)} frames, sorted low->high by spectral centroid. */\n")
        fp.write("export const FRAMES=" + json.dumps(frames, separators=(",", ":")) + ";\n")
    print(f"\nwrote {len(frames)} frames -> {out}")

if __name__ == "__main__":
    main()
