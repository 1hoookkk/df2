#!/usr/bin/env python3
"""
Build 5 audition-ready preset candidates for the requested 5 ROM frames:
1. Meaty Gizmo (P2k_004) + Steel Pan / China Cymbal (steelpan_cymbal)
2. TB or Not TB (P2k_009) + Glockenspiel / Mine Site (glockenspiel_minecave)
3. MegaSweepz (P2k_001) + Kalimba / Middle Tunnel (kalimba_tunnel)
4. Ear Bender (P2k_031) + Soprano Ukulele / ORTF Room (ukulele_ortf)
5. Deep Bouche (P2k_022) + SONICOM HRTF Registered Lanes (hrtf_registered)

Optimized for articulate, non-sub-heavy, high-character material.
"""

import sys
import os
import hashlib
import json
import struct
import math
from pathlib import Path
import numpy as np

ROOT = Path(r"c:\Users\hooki\df2-workstation")
DF2_ROOT = Path(r"c:\Users\hooki\df2")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DF2_ROOT))

from pyruntime import trench_ffi

OUT_DIR = ROOT / "dev" / "tmp" / "audition_candidates"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PLUGIN_BODIES_DIR = ROOT / "plugin" / "presets" / "bodies"

ROW_BYTES = 10
STAGES = 6
CORNERS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
FRAME_SLOTS = (0, 5)

ROM_DIR = DF2_ROOT / "ref" / "presets"

CANDIDATE_SPECS = [
    {
        "slug": "steelpan_cymbal__meaty_gizmo",
        "title": "Steelpan Cymbal Meaty Gizmo",
        "frame_name": "Meaty Gizmo (P2k_004)",
        "frame_file": "P2k_004_meaty_gizmo.bin",
        "middle_name": "Steel Pan / China Cymbal (steelpan_cymbal)",
        "middle_file": PLUGIN_BODIES_DIR / "steelpan_cymbal.body240",
        "desc": "Heavy metallic iron frame with articulate steel pan resonance and contact cymbal high formants."
    },
    {
        "slug": "glockenspiel_minecave__tb_or_not_tb",
        "title": "Glockenspiel Mine Cave 303",
        "frame_name": "TB or Not TB (P2k_009)",
        "frame_file": "P2k_009_tb_or_not_tb.bin",
        "middle_name": "Glockenspiel / Mine Site (glockenspiel_minecave)",
        "middle_file": PLUGIN_BODIES_DIR / "glockenspiel_minecave.body240",
        "desc": "Acid 303 resonant sweep frame with ringing glockenspiel harmonics and subterranean cave air."
    },
    {
        "slug": "kalimba_tunnel__megasweepz",
        "title": "Kalimba Tunnel MegaSweepz",
        "frame_name": "MegaSweepz (P2k_001)",
        "frame_file": "P2k_001_megasweepz.bin",
        "middle_name": "Kalimba / Middle Tunnel (kalimba_tunnel)",
        "middle_file": PLUGIN_BODIES_DIR / "kalimba_tunnel.body240",
        "desc": "Ultra-wide 6-stage resonant sweep frame with plucked kalimba tines and 4-way tunnel acoustic space."
    },
    {
        "slug": "ukulele_ortf__ear_bender",
        "title": "Ukulele ORTF Ear Bender",
        "frame_name": "Ear Bender (P2k_031)",
        "frame_file": "P2k_031_ear_bender.bin",
        "middle_name": "Soprano Ukulele / ORTF Room (ukulele_ortf)",
        "middle_file": PLUGIN_BODIES_DIR / "ukulele_ortf.body240",
        "desc": "High-Q ear-bending notch/peak frame with articulate ukulele string body and 3D ORTF room air."
    },
    {
        "slug": "hrtf_registered__deep_bouche",
        "title": "HRTF Spatial Deep Bouche",
        "frame_name": "Deep Bouche (P2k_022)",
        "frame_file": "P2k_022_deep_bouche.bin",
        "middle_name": "SONICOM HRTF Registered Lanes (hrtf_registered)",
        "middle_file": DF2_ROOT / "dev" / "tmp" / "hrtf_registered_lanes" / "hrtf_path_registered_six.body240",
        "desc": "Deep formant vocal frame with 3D HRTF directional spatial path trajectories in S2-S5."
    }
]

def get_row(body: bytes, corner: int, stage: int) -> bytes:
    start = (corner * STAGES + stage) * ROW_BYTES
    return body[start:start + ROW_BYTES]

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

# Load dry audio sample for audition WAVs
dry_path = ROOT / "dev" / "tmp" / "iconic_presets_20260722" / "rom_frames_rich_sources_01" / "real_audio" / "wav" / "dry__tam_tam.wav"
if not dry_path.exists():
    dry_path = ROOT / "out" / "candidates_partial_20260720_2103" / "audio" / "ACTOR__tam_tam.wav"

import scipy.io.wavfile as wavfile
dry_sr, dry_data = wavfile.read(dry_path)
if dry_data.dtype == np.int16:
    float_audio = dry_data.astype(np.float32) / 32768.0
elif dry_data.dtype == np.float32:
    float_audio = dry_data
else:
    float_audio = dry_data.astype(np.float32) / np.max(np.abs(dry_data))

if float_audio.ndim > 1:
    float_audio = float_audio[:, 0]

num_samples = len(float_audio)
block_size = 64
num_blocks = num_samples // block_size
m_blocks = np.linspace(0.0, 1.0, num_blocks).astype(np.float32)
q_blocks = np.linspace(0.0, 1.0, num_blocks).astype(np.float32)

def render_and_normalize(body_bytes, m_blocks, q_blocks, audio_in, sr):
    raw_out = trench_ffi.engine_render_automated(
        body_bytes, m_blocks.tolist(), q_blocks.tolist(), audio_in.tobytes(), float(sr), block=block_size
    )
    arr_out = np.frombuffer(raw_out, dtype=np.float32)
    max_val = np.max(np.abs(arr_out))
    if max_val > 1e-6:
        arr_norm = arr_out * (0.891 / max_val)
    else:
        arr_norm = arr_out
    return arr_norm

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sr = 39062.5
freqs = np.logspace(math.log10(20), math.log10(sr/2 * 0.98), 500)

results = []

print("=== Building 5 Audition-Ready Presets ===")

for spec in CANDIDATE_SPECS:
    slug = spec["slug"]
    frame_path = ROM_DIR / spec["frame_file"]
    middle_path = spec["middle_file"]
    
    frame_bytes = frame_path.read_bytes()
    middle_bytes = middle_path.read_bytes()
    
    frame_sha = hashlib.sha256(frame_bytes).hexdigest()
    middle_sha = hashlib.sha256(middle_bytes).hexdigest()
    
    output_body = bytearray()
    row_audit_list = []
    
    for ci, cname in enumerate(CORNERS):
        for si in range(STAGES):
            if si in FRAME_SLOTS:
                r = get_row(frame_bytes, ci, si)
                owner = f"{spec['frame_name']} (ROM S1/S6)"
            else:
                r = get_row(middle_bytes, ci, si)
                owner = f"{spec['middle_name']} (Measured S2-S5)"
            
            output_body.extend(r)
            words = struct.unpack("<5H", r)
            row_audit_list.append({
                "corner": cname,
                "stage_1_based": si + 1,
                "owner": owner,
                "bytes_hex": r.hex(),
                "words_u16_le": [f"0x{w:04x}" for w in words]
            })
    
    candidate_bytes = bytes(output_body)
    candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
    
    cand_path = OUT_DIR / f"{slug}.body240"
    cand_path.write_bytes(candidate_bytes)
    
    # Also write to plugin/presets/bodies
    plugin_cand_path = PLUGIN_BODIES_DIR / f"{slug}.body240"
    plugin_cand_path.write_bytes(candidate_bytes)
    
    # Certification
    grid_steps = 17
    max_pole_radius = 0.0
    total_unstable = 0
    total_nonfinite = 0
    max_crown_db = -999.0
    
    for m in np.linspace(0.0, 1.0, grid_steps):
        for q in np.linspace(0.0, 1.0, grid_steps):
            pr = trench_ffi.packed_probe(candidate_bytes, float(m), float(q))
            if pr:
                max_pole_radius = max(max_pole_radius, pr.get("max_pole_radius", 0.0))
                if pr.get("unstable_mask", 0) != 0:
                    total_unstable += 1
                if pr.get("nonfinite_mask", 0) != 0:
                    total_nonfinite += 1
                for bq in pr.get("biquad", []):
                    b0 = bq[0]
                    cr = 20.0 * math.log10(max(abs(b0), 1e-12))
                    if cr > max_crown_db:
                        max_crown_db = cr
                        
    is_stable = (total_unstable == 0) and (total_nonfinite == 0) and (max_pole_radius < 1.0)
    
    # Response plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    corner_coords = [(0.0, 0.0, "M0 Q0 (HOME)", "blue"),
                     (1.0, 0.0, "M100 Q0 (AWAY)", "green"),
                     (0.0, 1.0, "M0 Q100 (PUSH HOME)", "purple"),
                     (1.0, 1.0, "M100 Q100 (PUSH AWAY)", "red")]
    
    for m_val, q_val, label, color in corner_coords:
        pr = trench_ffi.packed_probe(candidate_bytes, m_val, q_val)
        bqs = pr["biquad"]
        H = get_biquad_response(bqs, freqs)
        mag_db = 20 * np.log10(np.abs(H) + 1e-12)
        ax1.plot(freqs, mag_db, label=label, color=color, linewidth=2)
        
        H_frame = get_biquad_response([bqs[0], bqs[5]], freqs)
        H_middle = get_biquad_response(bqs[1:5], freqs)
        quotient_db = 20 * np.log10(np.abs(H_frame) / (np.abs(H_middle) + 1e-12) + 1e-12)
        ax2.plot(freqs, quotient_db, label=f"Quotient {label}", color=color, linestyle="--", alpha=0.8)
        
    ax1.set_xscale("log")
    ax1.set_ylabel("Full Cascade Response (dB)")
    ax1.set_title(f"{spec['title']} — Four-Corner Response")
    ax1.grid(True, which="both", linestyle=":", alpha=0.6)
    ax1.legend(loc="upper right")
    
    ax2.set_xscale("log")
    ax2.set_xlabel("Frequency (Hz)")
    ax2.set_ylabel("Diagnostic Quotient (dB)")
    ax2.set_title("Frame (S1/S6) / Middle (S2-S5) Quotient (Safety Only)")
    ax2.grid(True, which="both", linestyle=":", alpha=0.6)
    ax2.legend(loc="upper right")
    
    plt.tight_layout()
    plot_path = OUT_DIR / f"{slug}_response.png"
    plt.savefig(plot_path, dpi=150)
    plt.close()
    
    # WAV Renders
    cand_wav = OUT_DIR / f"candidate__{slug}.wav"
    frame_wav = OUT_DIR / f"frame__{slug}.wav"
    middle_wav = OUT_DIR / f"middle__{slug}.wav"
    
    aud_cand = render_and_normalize(candidate_bytes, m_blocks, q_blocks, float_audio, dry_sr)
    aud_frame = render_and_normalize(frame_bytes, m_blocks, q_blocks, float_audio, dry_sr)
    aud_middle = render_and_normalize(middle_bytes, m_blocks, q_blocks, float_audio, dry_sr)
    
    wavfile.write(cand_wav, dry_sr, (aud_cand * 32767.0).astype(np.int16))
    wavfile.write(frame_wav, dry_sr, (aud_frame * 32767.0).astype(np.int16))
    wavfile.write(middle_wav, dry_sr, (aud_middle * 32767.0).astype(np.int16))
    
    res = {
        "slug": slug,
        "title": spec["title"],
        "description": spec["desc"],
        "candidate_body": str(cand_path),
        "candidate_sha256": candidate_sha,
        "frame_source": {"name": spec["frame_name"], "path": str(frame_path), "sha256": frame_sha},
        "middle_source": {"name": spec["middle_name"], "path": str(middle_path), "sha256": middle_sha},
        "certification": {
            "stable": is_stable,
            "max_pole_radius": round(float(max_pole_radius), 6),
            "max_crown_gain_db": round(float(max_crown_db), 2)
        },
        "response_plot": str(plot_path),
        "audition_wavs": {
            "candidate": str(cand_wav),
            "frame": str(frame_wav),
            "middle": str(middle_wav)
        },
        "row_audit": row_audit_list
    }
    results.append(res)
    print(f"Built [{slug}]: r_max={max_pole_radius:.6f}, max_crown={max_crown_db:.2f}dB, stable={is_stable}")

manifest_path = OUT_DIR / "five_candidates.manifest.json"
manifest_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
print(f"\nAll 5 candidates built and certified! Manifest: {manifest_path}")
