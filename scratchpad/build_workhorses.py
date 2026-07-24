#!/usr/bin/env python3
"""Workhorse ship set — parametric log-morph filters via the typed compiler.
Each = filter-type cards with two morph frames (fc@M0 -> fc@M100) and Q as
resonance. Certifies stable + crown<=27 on the packed runtime, then deploys to
plugin/presets/bodies. These exploit the log morph (musically even sweeps)."""
import math, sys, json, hashlib
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\hooki\df2-workstation")
DF2 = Path(r"C:\Users\hooki\df2")
for p in [str(DF2 / "pyruntime"), str(DF2)]:
    sys.path.insert(0, p)
from pyruntime import trench_ffi

SR = 39062.5
EVAL = np.logspace(math.log10(20), math.log10(18000), 800)
Z1 = np.exp(-2j*np.pi*EVAL/SR); Z2 = Z1*Z1
PEAK, LOW_SHELF, NOTCH, LP, HP, BP, HIGH_SHELF = 0,1,2,3,4,5,6
BODIES = ROOT/"plugin"/"presets"/"bodies"
OUT = ROOT/"dev"/"tmp"/"workhorses"; OUT.mkdir(parents=True, exist_ok=True)

def c(t, fa, fb, ql, qh, g, en=1.0):
    return [float(t),float(fa),float(fb),float(ql),float(qh),float(g),float(en)]

OFF = c(PEAK,10000,10000,0.5,0.5,0,0)

# Named after the user's workhorses + the everyday moves.
PRESETS = {
 # 6-pole lowpass: cutoff sweeps 100->10k, Q = resonant peak at cutoff (proven).
 "wh_lowpass_6p": [c(LP,100,10000,0.707,0.707,0), c(LP,100,10000,0.707,1.5,0),
                   c(LP,100,10000,0.707,6.0,0), OFF, OFF, OFF],
 # Contrary bandpass: low edge RISES (HP 80->1500) while high edge FALLS
 # (LP 10k->2.5k) -> band closes contrarily across morph; Q sharpens edges.
 "wh_contrary_bp": [c(HP,80,1500,0.707,3.0,0), c(HP,80,1500,0.707,1.5,0),
                    c(LP,10000,2500,0.707,3.0,0), c(LP,10000,2500,0.707,1.5,0),
                    OFF, OFF],
 # Peak/Shelf morph (E-mu, PDF-exact): dark LP 246 -> bright HS 4488, Q=FilRes.
 "wh_peak_shelf": [c(LP,246,4488,0.7,5.0,0), c(PEAK,246,4488,0.5,6.0,4.0),
                   c(HIGH_SHELF,3000,6000,0.7,3.0,-2.0), c(LOW_SHELF,100,100,0.7,3.0,-6.0),
                   OFF, OFF],
 # Highpass sweep: rolloff climbs 30->3000, Q = resonant edge.
 "wh_highpass_sweep": [c(HP,30,3000,0.707,0.707,0), c(HP,30,3000,0.707,1.2,0),
                       c(HP,30,3000,0.707,2.5,0), c(LOW_SHELF,60,60,0.7,0.7,-3.0), OFF, OFF],
 # Notch sweep: a moving notch 200->4000 (+ a second offset notch for comb feel).
 "wh_notch_sweep": [c(NOTCH,200,4000,0.7,4.0,0), c(NOTCH,400,8000,0.7,4.0,0),
                    c(LOW_SHELF,60,60,0.7,0.7,-2.0), c(HIGH_SHELF,15000,15000,0.7,0.7,-2.0),
                    OFF, OFF],
 # Tilt EQ: dark<->bright one-knob balance (shelves complement across morph).
 "wh_tilt": [c(LOW_SHELF,200,SR/2,0.7,2.0,6.0), c(HIGH_SHELF,SR/2,200,0.7,2.0,6.0),
             c(LOW_SHELF,60,60,0.5,2.0,-3.0), c(HIGH_SHELF,15000,15000,0.5,2.0,-3.0),
             OFF, OFF],
}

def resp(body,m,q):
    pr=trench_ffi.packed_probe(body,float(m),float(q))
    mag=np.ones_like(EVAL,dtype=complex)
    for b0,b1,b2,a1,a2 in pr["biquad"]:
        mag*=(b0+b1*Z1+b2*Z2)/(1.0+a1*Z1+a2*Z2)
    return 20*np.log10(np.abs(mag)+1e-12), pr

results={}
for slug,cards in PRESETS.items():
    body=trench_ffi.compile_body_typed([v for cc in cards for v in cc])
    un=nf=0; mr=0.0; crown=-999
    for m in np.linspace(0,1,25):
        for q in np.linspace(0,1,25):
            db,pr=resp(body,m,q); un+=int(pr["unstable_mask"]); nf+=int(pr["nonfinite_mask"])
            mr=max(mr,float(pr["max_pole_radius"])); crown=max(crown,float(db.max()))
    ok = un==0 and nf==0 and mr<1.0 and crown<=27.0
    # morph character: peak-freq walk at Q0
    walk=[]
    for m in np.linspace(0,1,5):
        db,_=resp(body,m,0.0); walk.append(int(EVAL[np.argmax(db)]))
    status="PASS" if ok else f"FAIL(un={un} r={mr:.3f} cr={crown:+.0f})"
    print(f"{slug:20s} {status:24s} crown={crown:+5.1f}dB  peak@Q0: {walk} Hz")
    results[slug]=ok
    if ok:
        (OUT/f"{slug}.body240").write_bytes(body)
        (BODIES/f"{slug}.body240").write_bytes(body)

npass=sum(results.values())
print(f"\n{npass}/{len(PRESETS)} PASS, deployed to {BODIES}")
