#!/usr/bin/env python3
"""
Deep Gain Budget, Pole Radii (rp), and Zero Radii (rz) Audit across all 6 candidates:
Analyzes per-stage biquad parameters, individual stage peak gains, cumulative serial cascade gain,
and zero depth / valley carving efficacy.
"""

import sys
import os
import math
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT = Path(r"c:\Users\hooki\df2-workstation")
DF2_ROOT = Path(r"c:\Users\hooki\df2")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DF2_ROOT))

from pyruntime import trench_ffi

OUT_DIR = ROOT / "dev" / "tmp" / "audition_candidates"

CANDIDATE_SLUGS = [
    "ukulele_ortf__talking_hedz",
    "steelpan_cymbal__meaty_gizmo",
    "glockenspiel_minecave__tb_or_not_tb",
    "kalimba_tunnel__megasweepz",
    "ukulele_ortf__ear_bender",
    "hrtf_registered__deep_bouche"
]

sr = 39062.5
freqs = np.logspace(math.log10(20), math.log10(20000), 2000)
w = 2 * np.pi * freqs / sr
z = np.exp(1j * w)

def analyze_biquad(b0, b1, b2, a1, a2, sr=39062.5):
    # Numerator roots (Zeros)
    num_roots = np.roots([1.0, b1/b0 if abs(b0)>1e-12 else b1, b2/b0 if abs(b0)>1e-12 else b2])
    # Denominator roots (Poles)
    den_roots = np.roots([1.0, a1, a2])
    
    # Poles
    p_idx = np.argmax(np.abs(den_roots))
    p_root = den_roots[p_idx]
    rp = float(np.abs(p_root))
    p_ang = float(np.abs(np.angle(p_root)))
    fp = (p_ang / (2 * np.pi)) * sr
    
    # Zeros
    z_idx = np.argmax(np.abs(num_roots))
    z_root = num_roots[z_idx]
    rz = float(np.abs(z_root))
    z_ang = float(np.abs(np.angle(z_root)))
    fz = (z_ang / (2 * np.pi)) * sr
    
    # Stage Response
    num = b0 + b1 * z**(-1) + b2 * z**(-2)
    den = 1.0 + a1 * z**(-1) + a2 * z**(-2)
    H_stage = num / den
    max_stage_db = 20 * np.log10(np.max(np.abs(H_stage)) + 1e-12)
    min_stage_db = 20 * np.log10(np.min(np.abs(H_stage)) + 1e-12)
    
    return {
        "b0": b0,
        "fp_hz": round(fp, 1),
        "rp": round(rp, 6),
        "fz_hz": round(fz, 1),
        "rz": round(rz, 6),
        "max_stage_db": round(max_stage_db, 2),
        "min_stage_db": round(min_stage_db, 2)
    }

corners = [("M0_Q0", 0.0, 0.0), ("M100_Q0", 1.0, 0.0), ("M0_Q100", 0.0, 1.0), ("M100_Q100", 1.0, 1.0)]

full_audit = {}

for slug in CANDIDATE_SLUGS:
    body_file = OUT_DIR / f"{slug}.body240"
    if not body_file.exists():
        continue
    
    body_bytes = body_file.read_bytes()
    cand_audit = {"slug": slug, "corners": {}}
    
    for cname, m_val, q_val in corners:
        pr = trench_ffi.packed_probe(body_bytes, m_val, q_val)
        bqs = pr["biquad"]
        
        # Calculate Serial Cascade Response
        H_cascade = np.ones_like(z, dtype=complex)
        stage_details = []
        for si, bq in enumerate(bqs):
            b0, b1, b2, a1, a2 = bq
            st_info = analyze_biquad(b0, b1, b2, a1, a2, sr)
            st_info["stage"] = si + 1
            stage_details.append(st_info)
            
            num = b0 + b1 * z**(-1) + b2 * z**(-2)
            den = 1.0 + a1 * z**(-1) + a2 * z**(-2)
            H_cascade *= (num / den)
            
        cascade_mag_db = 20 * np.log10(np.abs(H_cascade) + 1e-12)
        crown_db = float(np.max(cascade_mag_db))
        floor_db = float(np.median(cascade_mag_db))
        min_dB = float(np.min(cascade_mag_db))
        contrast_db = crown_db - floor_db
        
        cand_audit["corners"][cname] = {
            "cascade_crown_db": round(crown_db, 2),
            "cascade_floor_db": round(floor_db, 2),
            "cascade_min_db": round(min_dB, 2),
            "contrast_db": round(contrast_db, 2),
            "stages": stage_details
        }
        
    full_audit[slug] = cand_audit

# Output Clean Table
print("====================================================================================================")
print("                       DSP GAIN BUDGET, POLE RADII & ZERO RADII AUDIT                               ")
print("====================================================================================================\n")

for slug, data in full_audit.items():
    print(f"=== Candidate: {slug} ===")
    for cname, cdata in data["corners"].items():
        print(f"\n  Corner {cname}: Crown = {cdata['cascade_crown_db']:+.2f} dB | Floor = {cdata['cascade_floor_db']:+.2f} dB | Contrast = {cdata['contrast_db']:.2f} dB")
        print(f"  {'Stage':<6} {'b0 (Scale)':<12} {'fp (Hz)':<10} {'rp (Pole Radius)':<18} {'fz (Hz)':<10} {'rz (Zero Radius)':<18} {'Stage Peak (dB)':<15}")
        print(f"  {'-'*95}")
        for st in cdata["stages"]:
            print(f"  S{st['stage']:<5} {st['b0']:<12.6f} {st['fp_hz']:<10.1f} {st['rp']:<18.6f} {st['fz_hz']:<10.1f} {st['rz']:<18.6f} {st['max_stage_db']:<+15.2f}")
    print("\n" + "="*100 + "\n")

audit_json = OUT_DIR / "gain_budget_poles_zeros_audit.json"
audit_json.write_text(json.dumps(full_audit, indent=2) + "\n", encoding="utf-8")
print(f"Full Gain Budget Audit saved: {audit_json}")
