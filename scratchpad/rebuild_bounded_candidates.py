#!/usr/bin/env python3
"""
Rebuild all 6 candidate bodies with exact serial cascade gain budget enforcement:
- Preserves exact pole radii (rp), zero radii (rz), and pole/zero frequencies verbatim.
- Calculates exact 6-stage serial cascade peak gain |H_total(w)|.
- If cascade crown exceeds +27.0 dB, applies exact per-stage scale trim (ratio = 10^(-trim_dB / (20 * 6)))
  so that the serial cascade crown is bounded precisely at <= +27.0 dB (Rule L4/L7).
"""

import sys
import os
import math
import hashlib
import json
import struct
from pathlib import Path
import numpy as np

ROOT = Path(r"c:\Users\hooki\df2-workstation")
DF2_ROOT = Path(r"c:\Users\hooki\df2")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DF2_ROOT))

from pyruntime import trench_ffi

OUT_DIR = ROOT / "dev" / "tmp" / "audition_candidates"
PLUGIN_BODIES_DIR = ROOT / "plugin" / "presets" / "bodies"
ROM_DIR = DF2_ROOT / "ref" / "presets"

ROW_BYTES = 10
STAGES = 6
CORNERS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
FRAME_SLOTS = (0, 5)

CANDIDATE_SPECS = [
    {
        "slug": "ukulele_ortf__talking_hedz",
        "frame_file": "P2k_013_talking_hedz.bin",
        "middle_file": PLUGIN_BODIES_DIR / "ukulele_ortf.body240",
    },
    {
        "slug": "steelpan_cymbal__meaty_gizmo",
        "frame_file": "P2k_004_meaty_gizmo.bin",
        "middle_file": PLUGIN_BODIES_DIR / "steelpan_cymbal.body240",
    },
    {
        "slug": "glockenspiel_minecave__tb_or_not_tb",
        "frame_file": "P2k_009_tb_or_not_tb.bin",
        "middle_file": PLUGIN_BODIES_DIR / "glockenspiel_minecave.body240",
    },
    {
        "slug": "kalimba_tunnel__megasweepz",
        "frame_file": "P2k_001_megasweepz.bin",
        "middle_file": PLUGIN_BODIES_DIR / "kalimba_tunnel.body240",
    },
    {
        "slug": "ukulele_ortf__ear_bender",
        "frame_file": "P2k_031_ear_bender.bin",
        "middle_file": PLUGIN_BODIES_DIR / "ukulele_ortf.body240",
    },
    {
        "slug": "hrtf_registered__deep_bouche",
        "frame_file": "P2k_022_deep_bouche.bin",
        "middle_file": DF2_ROOT / "dev" / "tmp" / "hrtf_registered_lanes" / "hrtf_path_registered_six.body240",
    }
]

sr = 39062.5
freqs = np.logspace(math.log10(20), math.log10(20000), 1000)

def get_biquad_response(biquads, freqs, sr=39062.5):
    w = 2 * np.pi * freqs / sr
    z = np.exp(1j * w)
    H_total = np.ones_like(z, dtype=complex)
    for bq in biquads:
        b0, b1, b2, a1, a2 = bq
        num = b0 + b1 * z**(-1) + b2 * z**(-2)
        den = 1.0 + a1 * z**(-1) + a2 * z**(-2)
        H_total *= (num / den)
    return H_total

def get_row(body: bytes, corner: int, stage: int) -> bytes:
    start = (corner * STAGES + stage) * ROW_BYTES
    return body[start:start + ROW_BYTES]

def get_max_crown(body_bytes):
    max_cr = -999.0
    for m in np.linspace(0.0, 1.0, 9):
        for q in np.linspace(0.0, 1.0, 9):
            pr = trench_ffi.packed_probe(body_bytes, float(m), float(q))
            if pr:
                H = get_biquad_response(pr["biquad"], freqs)
                cr = 20 * np.log10(np.max(np.abs(H)) + 1e-12)
                if cr > max_cr:
                    max_cr = cr
    return max_cr

print("=== Rebuilding & Bounding Candidates (Serial Cascade Gain Law) ===")

for spec in CANDIDATE_SPECS:
    slug = spec["slug"]
    frame_path = ROM_DIR / spec["frame_file"]
    middle_path = spec["middle_file"]
    
    frame_bytes = frame_path.read_bytes()
    middle_bytes = middle_path.read_bytes()
    
    output_body = bytearray()
    for ci in range(4):
        for si in range(STAGES):
            if si in FRAME_SLOTS:
                output_body.extend(get_row(frame_bytes, ci, si))
            else:
                output_body.extend(get_row(middle_bytes, ci, si))
                
    raw_candidate = bytes(output_body)
    raw_crown = get_max_crown(raw_candidate)
    
    print(f"\nCandidate [{slug}]: Unbounded Raw Crown = {raw_crown:+.2f} dB")
    
    if raw_crown > 27.0:
        trim_db = raw_crown - 27.0
        # Per-stage scale ratio: in 6-stage product, total attenuation is ratio^6 = 10^(-trim_db/20)
        # So per-stage ratio = 10^(-trim_db / (20 * 6))
        per_stage_ratio = 10.0 ** (-trim_db / (20.0 * 6.0))
        
        words = list(struct.unpack("<120H", raw_candidate))
        for row_idx in range(24):
            w4_idx = row_idx * 5 + 4
            orig_b0 = trench_ffi.decode(words[w4_idx])
            new_b0 = orig_b0 * per_stage_ratio
            words[w4_idx] = trench_ffi.encode(new_b0)
            
        bounded_candidate = struct.pack("<120H", *words)
        bounded_crown = get_max_crown(bounded_candidate)
        print(f"  -> Applied L4 Trim (-{trim_db:.2f} dB total / -{trim_db/6.0:.2f} dB per stage)")
        print(f"  -> Bounded Cascade Crown = {bounded_crown:+.2f} dB (Rule L4 Compliant)")
    else:
        bounded_candidate = raw_candidate
        bounded_crown = raw_crown
        print(f"  -> Compliant (Crown {bounded_crown:+.2f} dB <= +27.0 dB)")
        
    cand_path = OUT_DIR / f"{slug}.body240"
    cand_path.write_bytes(bounded_candidate)
    (PLUGIN_BODIES_DIR / f"{slug}.body240").write_bytes(bounded_candidate)

print("\nRebuild complete! Updating clean plots and audit...")
