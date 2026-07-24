#!/usr/bin/env python3
"""Proof: bake a REAL E-mu heritage filter XML -> body240 via the RE-verified
designer_compile pipeline. Every number from E-mu firmware, zero invented.
Certify on the packed runtime + show the morph character."""
import sys, struct, math
from pathlib import Path
import numpy as np

DF2 = Path(r"C:\Users\hooki\df2")
sys.path.insert(0, str(DF2))
from pyruntime.designer_compile import parse_xml, compile_designer
from pyruntime import trench_ffi

SR = 39062.5
EVAL = np.logspace(math.log10(20), math.log10(18000), 800)
Z1 = np.exp(-2j*np.pi*EVAL/SR); Z2 = Z1*Z1
HER = DF2/"ref"/"heritage"

def pack_corner(corner_state):
    b = bytearray()
    for e in corner_state.encode():
        b += struct.pack("<5H", e.c0, e.c1, e.c2, e.c3, e.c4)
    return bytes(b)

def resp(body, m, q):
    pr = trench_ffi.packed_probe(body, float(m), float(q))
    mag = np.ones_like(EVAL, dtype=complex)
    for b0,b1,b2,a1,a2 in pr["biquad"]:
        mag *= (b0+b1*Z1+b2*Z2)/(1.0+a1*Z1+a2*Z2)
    return 20*np.log10(np.abs(mag)+1e-12), pr

for name in ["Six Pole Exteme Q", "ContrarySweeps", "Notch Sweeper"]:
    xml = HER/f"{name}.xml"
    arr = compile_designer(parse_xml(str(xml)))
    nc = len(arr._corners)
    # body = 4 corners x 6 stages x 5 words. Use the 4 designer corners in order.
    body = b"".join(pack_corner(arr._corners[ci]) for ci in range(4))
    assert len(body) == 240, (name, len(body), nc)
    un=nf=0; mr=0.0; crown=-999
    for m in np.linspace(0,1,15):
        for q in np.linspace(0,1,15):
            db,pr = resp(body, m, q)
            un+=int(pr["unstable_mask"]); nf+=int(pr["nonfinite_mask"])
            mr=max(mr,float(pr["max_pole_radius"])); crown=max(crown,float(db.max()))
    peak = [int(EVAL[np.argmax(resp(body,m,0.0)[0])]) for m in np.linspace(0,1,5)]
    ok = un==0 and nf==0 and mr<1.0
    print(f"{name:20s} corners={nc} certify={'PASS' if ok else 'FAIL'} "
          f"un={un} maxR={mr:.4f} crown={crown:+.1f}dB  peak@Q0:{peak}Hz")
