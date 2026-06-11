#!/usr/bin/env python
"""match_frames.py - script the measurement.

For each reference grammar (study yardstick), search EVERY pairing of our
real-physics frames and rank by distance-to-grammar at the four corners
(level-normalized magnitude). Reports the closest pairs and, for the best,
which LAYER is still off (body / tilt / peaks / notches).

CLEAN-ROOM: the targets are sampled behaviour (a yardstick) used to LEARN how
close our original quarry gets and what's missing. We rank our own frames; we
do not copy or ship reference structure.
"""
import json, math, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyruntime import minifloat

SR = 39062.5
def load(js, key):
    t = open(os.path.join(ROOT, "forge-web/data", js)).read()
    i = t.index(key); i = t.index("=", i)+1; j = t.rindex(";")
    return json.loads(t[i:j])
FRAMES = load("frames.js", "FRAMES")
TARGETS = load("targets.js", "TARGETS")
F_LO, F_HI, N = 30.0, 18000.0, 128
GRID = [F_LO*(F_HI/F_LO)**(i/(N-1)) for i in range(N)]

def stage_mag(words, f):
    import cmath
    z = cmath.exp(-1j*2*math.pi*f/SR); tot = 0.0
    for w in words:
        d = [minifloat.decode(x) for x in w]
        c0, c1, c2, c3, c4 = 4*d[0]+d[1], d[1], 4*d[2]+d[3], d[3], 4*d[4]
        b = [c4, (c0-2)*c4, (1-c1)*c4, c2-2, 1-c3]
        tot += 20*math.log10(max(1e-9, abs(b[0]+b[1]*z+b[2]*z*z)/max(1e-9, abs(1+b[3]*z+b[4]*z*z))))
    return tot
def curve(words): return [stage_mag(words, f) for f in GRID]
def norm(c):
    m = sum(c)/len(c); return [v-m for v in c]
def rms(a, b): return math.sqrt(sum((a[k]-b[k])**2 for k in range(N))/N)
def band(c, lo, hi):
    s = n = 0
    for k in range(N):
        if lo <= GRID[k] <= hi: s += c[k]; n += 1
    return s/n if n else 0.0
def pk(c, up):
    n = 0
    for k in range(2, N-2):
        e = (c[k] > c[k-1] and c[k] >= c[k+1] and c[k]-min(c[k-2], c[k+2]) > 3) if up else \
            (c[k] < c[k-1] and c[k] <= c[k+1] and max(c[k-2], c[k+2])-c[k] > 3)
        if e: n += 1
    return n

# precompute every frame's loQ + hiQ corner curves (normalized)
print("precomputing frame curves...")
FC = []
for fr in FRAMES:
    FC.append({"id": fr["id"], "lo": norm(curve(fr["words"])), "hi": norm(curve(fr["wordsHiQ"]))})

print(f"\nsearching {len(FRAMES)}x{len(FRAMES)} pairings against {len(TARGETS)} grammars\n")
for tg in TARGETS:
    g = tg["grid"]
    T = {"00": norm(g[0][0]), "20": norm(g[2][0]), "02": norm(g[0][2]), "22": norm(g[2][2])}
    best = []
    for i in range(len(FC)):
        for j in range(len(FC)):
            if i == j: continue
            A, B = FC[i], FC[j]
            d = (rms(A["lo"], T["00"]) + rms(B["lo"], T["20"]) + rms(A["hi"], T["02"]) + rms(B["hi"], T["22"]))/4
            best.append((d, i, j))
    best.sort()
    print(f"=== {tg['label']} ({tg['type']}) ===")
    for d, i, j in best[:3]:
        print(f"   {FC[i]['id']:>14} + {FC[j]['id']:<14}  rms {d:.2f} dB")
    # layer gap for the winner, at C0 (A_lo vs target M0/Q0)
    d, i, j = best[0]; A, Tt = FC[i]["lo"], T["00"]
    body = band(A, F_LO, 300)-band(Tt, F_LO, 300)
    tilt = (band(A, 50, 300)-band(A, 4000, 16000)) - (band(Tt, 50, 300)-band(Tt, 4000, 16000))
    sg = lambda v: f"{v:+.0f}"
    print(f"   winner gap @C0:  body {sg(body)}dB  tilt {sg(tilt)}dB  "
          f"peaks {pk(A,1)}/{pk(Tt,1)}  notches {pk(A,0)}/{pk(Tt,0)}\n")
