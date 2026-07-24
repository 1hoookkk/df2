#!/usr/bin/env python3
"""Finish the workhorses: bake the REAL E-mu heritage filter XMLs -> body240 via
the RE-verified xml_to_body pipeline (zero invented numbers). Certify stable,
bound crown<=27, deploy to the plugin. SR caveat: heritage coeffs are 44.1k-
domain, ~2 semitones low at 39062.5 -- negligible for utility filters."""
import sys, struct, math
from pathlib import Path
import numpy as np

DF2 = Path(r"C:\Users\hooki\df2")
sys.path.insert(0, str(DF2))
from tools.compare_p2k_corners_to_heritage_xml import xml_to_body
from pyruntime import trench_ffi

HER = DF2/"ref"/"heritage"
BODIES = Path(r"C:\Users\hooki\df2-workstation")/"plugin"/"presets"/"bodies"
SR = 39062.5
EVAL = np.logspace(math.log10(20), math.log10(18000), 600)
Z1 = np.exp(-2j*np.pi*EVAL/SR); Z2 = Z1*Z1

# Real E-mu families -> the utility workhorse roster. XML name : ship stem.
WORKHORSES = {
    "Six Pole Exteme Q": "wh_six_pole_q",
    "ContrarySweeps":    "wh_contrary_sweeps",
    "Notch Sweeper":     "wh_notch_sweeper",
    "Super Lo Pass":     "wh_super_lopass",
    "Super Hi Pass":     "wh_super_hipass",
    "Peak Shifter 1":    "wh_peak_shifter",
    "Twin Peaks":        "wh_twin_peaks",
    "Three Point Morph": "wh_three_point_morph",
    "Wah Wah 1":         "wh_wah_wah",
    "Modern Lo Pass":    "wh_modern_lopass",
}

def resp(body, m, q):
    pr = trench_ffi.packed_probe(body, float(m), float(q))
    mag = np.ones_like(EVAL, dtype=complex)
    for b0,b1,b2,a1,a2 in pr["biquad"]:
        mag *= (b0+b1*Z1+b2*Z2)/(1.0+a1*Z1+a2*Z2)
    return 20*np.log10(np.abs(mag)+1e-12), pr

def crown_max(body):
    mx=-999
    for m in np.linspace(0,1,11):
        for q in np.linspace(0,1,11):
            db,_=resp(body,m,q); mx=max(mx,float(db.max()))
    return mx

def bound27(body):
    cr = crown_max(body)
    if cr <= 27.0: return body, cr, 0.0
    trim = cr - 27.0
    ratio = 10.0 ** (-trim/(20.0*6.0))
    w = list(struct.unpack("<120H", body))
    for r in range(24):
        w[r*5+4] = trench_ffi.encode(trench_ffi.decode(w[r*5+4]) * ratio)
    b2 = struct.pack("<120H", *w)
    return b2, crown_max(b2), trim

results=[]
for xml_name, stem in WORKHORSES.items():
    xml = HER/f"{xml_name}.xml"
    if not xml.exists():
        print(f"{stem:22s} MISSING XML: {xml_name}"); continue
    try:
        body = xml_to_body(xml)
    except Exception as e:
        print(f"{stem:22s} COMPILE FAIL: {e}"); continue
    body, cr, trim = bound27(body)
    un=nf=0; mr=0.0
    for m in np.linspace(0,1,17):
        for q in np.linspace(0,1,17):
            pr=trench_ffi.packed_probe(body,float(m),float(q))
            un+=int(pr["unstable_mask"]); nf+=int(pr["nonfinite_mask"]); mr=max(mr,float(pr["max_pole_radius"]))
    ok = un==0 and nf==0 and mr<1.0 and len(body)==240
    peak=[int(EVAL[np.argmax(resp(body,m,0.0)[0])]) for m in (0.0,0.5,1.0)]
    print(f"{stem:22s} {'PASS' if ok else 'FAIL'} un={un} maxR={mr:.4f} crown={cr:+.1f}dB "
          f"trim={-trim:.0f} peak@Q0:{peak}Hz  <- {xml_name}")
    if ok:
        (BODIES/f"{stem}.body240").write_bytes(body)
        results.append(stem)

print(f"\n{len(results)}/{len(WORKHORSES)} baked + deployed from real E-mu XMLs:")
for s in results: print(f"  {s}")
