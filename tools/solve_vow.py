#!/usr/bin/env python
"""solve_vow.py - VOW filter type: clean-room formant CORE + solver-filled rest.

CORE (do-not-invent-poles): formant poles at public Klatt vowel frequencies,
Frame A = vowel1, Frame B = vowel2 (the glide IS the type). The morph moves them.

FILL (solver): the body shelf, the air, and every section's zero (the
articulation), plus gains and the Q radius-lift. The solver searches these to
satisfy the GRAMMAR - stable, body present, formants prominent, descending
terrain - NOT to clone any preset. Output is an original VOW body.
"""
import json, math, os, sys, cmath, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyruntime import minifloat

SR = 39062.5
NY = SR*0.49
random.seed(7)

KLATT = {"ah": [730, 1090, 2440], "ee": [270, 2290, 3010], "oo": [300, 870, 2240],
         "eh": [530, 1840, 2480], "uh": [640, 1190, 2390]}

def section_words(pf, pr, zf, zr, loud):
    pf = max(20.0, min(NY, pf)); zf = max(20.0, min(NY, zf))
    wp = 2*math.pi*pf/SR; a1, a2 = -2*pr*math.cos(wp), pr*pr
    wz = 2*math.pi*zf/SR; nb1, nb2 = -2*zr*math.cos(wz), zr*zr
    g = (1+a1+a2)/((1+nb1+nb2) or 1e-9)*loud
    b0, b1, b2 = g, g*nb1, g*nb2
    c4 = b0; c0 = b1/c4+2 if c4 else 2.0; c1 = 1-b2/c4 if c4 else 1.0
    return [minifloat.encode(x) for x in [(c0-c1)/4.0, c1, (b1*0+a1)+2-(0)+0, 0, 0]] if False else \
           [minifloat.encode(x) for x in [(c0-c1)/4.0, c1, ((a1+2)-(1-a2))/4.0, 1-a2, c4/4.0]]

def lift(r, amt): return min(0.9985, r+(1.0-r)*amt) if r > 1e-4 else r

def frame(vowel_f, P, hi):
    """Build one 6-section frame: body + 3 formants + air-formant + top cap."""
    fr = lift(P["fr"], P["ql"]) if hi else P["fr"]
    br = lift(P["br"], P["ql"]) if hi else P["br"]
    ar = lift(P["ar"], P["ql"]) if hi else P["ar"]
    secs = [(P["bf"], br, P["bzf"], P["bzr"], P["bl"])]          # body shelf
    for i, pf in enumerate(vowel_f):                             # formants (core poles)
        secs.append((pf, fr, pf*P["zrat"], P["zr"], P["L"]*P["dec"]**i))
    secs.append((P["af"], ar, P["af"]*P["zrat"], P["zr"], P["L"]*P["dec"]**3))  # air formant
    secs.append((P["tf"], lift(0.9, P["ql"]) if hi else 0.9, P["tf"]*3, 0.7, P["L"]*0.18))  # top cap
    return [section_words(*s) for s in secs]

def body(va, vb, P):
    return {"M0_Q0": frame(va, P, 0), "M100_Q0": frame(vb, P, 0),
            "M0_Q100": frame(va, P, 1), "M100_Q100": frame(vb, P, 1)}

# ---- engine-faithful eval ----
def dec(w): return [minifloat.decode(x) for x in w]
def biq(w):
    d = dec(w); c0, c1, c2, c3, c4 = 4*d[0]+d[1], d[1], 4*d[2]+d[3], d[3], 4*d[4]
    return [c4, (c0-2)*c4, (1-c1)*c4, c2-2, 1-c3]
def i16(n): u = n & 0xffff; return u-0x10000 if u >= 0x8000 else u
def lerpw(a, b, f): d = (b & 0xffff)-(a & 0xffff); return (i16(int(math.trunc(d*f)))+(a & 0xffff)) & 0xffff
def words_at(C, m, q):
    A, B, Cc, D = C["M0_Q0"], C["M100_Q0"], C["M0_Q100"], C["M100_Q100"]
    return [[lerpw(lerpw(A[s][k], B[s][k], m), lerpw(Cc[s][k], D[s][k], m), q) for k in range(5)] for s in range(6)]
def mag(rows, f):
    z = cmath.exp(-1j*2*math.pi*f/SR); tot = 0.0
    for w in rows:
        b = biq(w); tot += 20*math.log10(max(1e-9, abs(b[0]+b[1]*z+b[2]*z*z)/max(1e-9, abs(1+b[3]*z+b[4]*z*z))))
    return tot
def worstR(rows):
    w = 0
    for r in rows:
        b = biq(r); a1, a2 = b[3], b[4]; disc = a1*a1-4*a2
        rad = math.sqrt(max(0, a2)) if disc < 0 else max(abs((-a1+math.sqrt(disc))/2), abs((-a1-math.sqrt(disc))/2))
        w = max(w, rad)
    return w

def prominence(rows, fc):
    return mag(rows, fc) - 0.5*(mag(rows, fc/1.7)+mag(rows, fc*1.7))
def band(rows, lo, hi):
    fs = [lo*(hi/lo)**(i/9) for i in range(10)]; return sum(mag(rows, f) for f in fs)/10

def cost(P, va, vb):
    C = body(va, vb, P)
    pen = 0.0
    # stability across the m/q grid
    wr = max(worstR(words_at(C, m, q)) for m in (0, .5, 1) for q in (0, .5, 1))
    if wr >= 1.0: return 1e6+(wr-1)*1e6
    if wr > 0.9985: pen += (wr-0.9985)*4000
    score = 0.0
    for v, (m, q) in ((va, (0, 0)), (vb, (1, 0))):
        rows = words_at(C, m, q)
        # formants must be prominent (vowel readable) - capped so it can't buy prominence with mud
        for fc in v: score += min(prominence(rows, fc), 11)
        # body matched to the REFERENCE (~+16 dB on this metric), not a guessed range
        bdy = band(rows, 60, 250) - band(rows, v[0], v[2])
        pen += max(0, 8-bdy)*4 + max(0, bdy-22)*8         # want body ~[8,22], centered on ref +16.6
        # descending tilt matched to the reference (~+39 dB)
        tilt = band(rows, 60, 300) - band(rows, 5000, 15000)
        pen += max(0, 30-tilt)*3 + max(0, tilt-44)*5      # want tilt ~[30,44], centered on ref +39
    return pen - score

def search(va, vb, iters=9000):
    R = {"bf": (90, 200), "br": (0.94, 0.985), "bzf": (4000, 9000), "bzr": (0.55, 0.9), "bl": (0.4, 1.3),
         "fr": (0.965, 0.992), "zrat": (1.08, 1.30), "zr": (0.88, 0.96), "L": (0.4, 1.0),
         "dec": (0.6, 0.92), "af": (3000, 5200), "ar": (0.94, 0.99), "tf": (8000, 13000), "ql": (0.4, 0.75)}
    rnd = lambda: {k: random.uniform(*v) for k, v in R.items()}
    best = None; bc = 1e18
    for _ in range(iters):
        P = rnd(); c = cost(P, va, vb)
        if c < bc: bc, best = c, P
    # local refine
    for _ in range(4000):
        P = {k: min(R[k][1], max(R[k][0], best[k]+random.uniform(-1, 1)*(R[k][1]-R[k][0])*0.06)) for k in best}
        c = cost(P, va, vb)
        if c < bc: bc, best = c, P
    return best, bc

def to_bytes(C):
    out = bytearray()
    for key in ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"):
        for s in range(6):
            for k in range(5): out += int(C[key][s][k] & 0xffff).to_bytes(2, "little")
    return bytes(out)

def report(C, va, vb):
    wr = max(worstR(words_at(C, m, q)) for m in (0, .5, 1) for q in (0, .5, 1))
    print(f"  worst pole radius (m/q grid): {wr:.4f}  -> {'STABLE' if wr<0.999 else 'EDGE' if wr<1 else 'UNSTABLE'}")
    for name, v, (m, q) in (("ah/M0", va, (0, 0)), ("ee/M100", vb, (1, 0))):
        rows = words_at(C, m, q)
        proms = [round(prominence(rows, fc), 1) for fc in v]
        bdy = band(rows, 60, 250)-band(rows, v[0], v[2])
        tilt = band(rows, 60, 300)-band(rows, 5000, 15000)
        print(f"  {name:8} formant prominence {proms} dB   body {bdy:+.1f} dB   tilt {tilt:+.1f} dB")

if __name__ == "__main__":
    va, vb = KLATT["ah"], KLATT["ee"]
    print("solving VOW ah->ee (formant core + solver fill)...")
    P, c = search(va, vb)
    C = body(va, vb, P)
    print(f"\nbest cost {c:.1f}  params:")
    for k in sorted(P): print(f"    {k:5} {P[k]:.4f}")
    print()
    report(C, va, vb)
    out = os.path.join(ROOT, "dev/tmp/solved_vow_ah_ee.body240")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "wb").write(to_bytes(C))
    print(f"\nwrote {out} ({len(to_bytes(C))} bytes)")
