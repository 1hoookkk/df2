#!/usr/bin/env python3
"""
Intent-Driven Single Candidate Builder
- Frame: Talking Hedz (S1, S6)
- Middle: Violin Cave (S2-S5)
- Poses:
  - M0 Q0: Talking Hedz + Violin Body Dampened
  - M100 Q0: Talking Hedz + Mine Site 1
  - M0 Q100: Talking Hedz + Violin Body Resonant
  - M100 Q100: Talking Hedz + Mine Site 2
- Gain law: One global scale trim across all 24 rows if unbounded crown > +27 dB.
- Audition: 7 renders (4 holds, 2 M sweeps, 1 Q sweep) using ONE shared global gain.
"""

import sys
import os
import math
import hashlib
import json
import struct
from pathlib import Path
import numpy as np
import scipy.io.wavfile as wavfile
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(r"c:\Users\hooki\df2-workstation")
DF2_ROOT = Path(r"c:\Users\hooki\df2")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DF2_ROOT))

from pyruntime import trench_ffi

OUT_DIR = ROOT / "dev" / "tmp" / "audition_candidates"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PLUGIN_BODIES_DIR = ROOT / "plugin" / "presets" / "bodies"

FRAME_PATH = DF2_ROOT / "ref" / "presets" / "P2k_013_talking_hedz.bin"
MIDDLE_PATH = ROOT / "dev" / "tmp" / "measured_objects" / "violin_cave.body240"
SLUG = "violin_cave__talking_hedz"
TITLE = "Bowed Headz to Mine Mouth"

INTENT_SENTENCE = "HOME speaks through a tight, damped violin body; AWAY becomes a hollow mine chamber; Q opens and deepens the resonance—damped violin becomes resonant violin, while the near mine becomes the deeper mine."

POSES = {
    "M0_Q0": "Tight, woody, controlled speaking body",
    "M100_Q0": "The voice leaves the instrument and enters a near mine chamber",
    "M0_Q100": "Same wooden identity, opened into ringing body resonance",
    "M100_Q100": "The mine becomes deeper, wider and more enveloping"
}

ROW_BYTES = 10
STAGES = 6

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

def measure_max_crown(body_bytes, freqs):
    max_cr = -999.0
    for m in np.linspace(0.0, 1.0, 9):
        for q in np.linspace(0.0, 1.0, 9):
            pr = trench_ffi.packed_probe(body_bytes, float(m), float(q))
            if pr:
                H = get_biquad_response(pr["biquad"], freqs)
                cr = 20 * np.log10(np.max(np.abs(H)) + 1e-12)
                if cr > max_cr: max_cr = cr
    return max_cr

def generate_clean_plot(candidate_bytes, title, output_path, freqs):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=200)
    fig.patch.set_facecolor('#0f1117')
    ax.set_facecolor('#161822')
    
    morph_steps = [(0.25, 'M25 Q0', '#00e5ff', 0.35, ':'),
                   (0.50, 'M50 Q0', '#00e5ff', 0.55, '--'),
                   (0.75, 'M75 Q0', '#00e5ff', 0.75, '-.')]
    
    for m_val, label, col, alpha, ls in morph_steps:
        pr = trench_ffi.packed_probe(candidate_bytes, m_val, 0.0)
        H = get_biquad_response(pr["biquad"], freqs)
        mag_db = 20 * np.log10(np.abs(H) + 1e-12)
        ax.plot(freqs, mag_db, color='#4dd0e1', linestyle=ls, linewidth=1.5, alpha=alpha, label=label)
    
    corners = [
        (0.0, 0.0, 'HOME (M0 Q0)', '#00e5ff', 2.8),
        (1.0, 0.0, 'AWAY (M100 Q0)', '#76ff03', 2.8),
        (0.0, 1.0, 'PUSH HOME (M0 Q100)', '#e040fb', 2.8),
        (1.0, 1.0, 'PUSH AWAY (M100 Q100)', '#ff3d00', 2.8)
    ]
    
    all_mags = []
    for m_val, q_val, label, col, lw in corners:
        pr = trench_ffi.packed_probe(candidate_bytes, m_val, q_val)
        H = get_biquad_response(pr["biquad"], freqs)
        mag_db = 20 * np.log10(np.abs(H) + 1e-12)
        all_mags.extend(mag_db)
        ax.plot(freqs, mag_db, color=col, linewidth=lw, label=label, zorder=5)
    
    all_mags = np.array(all_mags)
    min_db = max(-70.0, np.percentile(all_mags, 1) - 5.0)
    max_db = min(40.0, np.percentile(all_mags, 99) + 8.0)
    ax.set_ylim(min_db, max_db)
    ax.set_xscale("log")
    ax.set_xlim(20, 20000)
    
    xticks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
    xticklabels = ['20', '50', '100', '200', '500', '1k', '2k', '5k', '10k', '20k']
    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels, fontsize=10, color='#b0bec5')
    ax.tick_params(colors='#b0bec5', labelsize=10)
    
    ax.set_xlabel("Frequency (Hz)", fontsize=11, fontweight='bold', color='#eceff1', labelpad=8)
    ax.set_ylabel("Magnitude Response (dB)", fontsize=11, fontweight='bold', color='#eceff1', labelpad=8)
    ax.set_title(title, fontsize=14, fontweight='bold', color='#ffffff', pad=12)
    ax.grid(True, which="major", color='#263238', linestyle='-', linewidth=0.8, alpha=0.8)
    ax.grid(True, which="minor", color='#1c242c', linestyle=':', linewidth=0.5, alpha=0.5)
    
    legend = ax.legend(frameon=True, facecolor='#1e2230', edgecolor='#37474f', fontsize=9.5, loc='upper right')
    for text in legend.get_texts(): text.set_color('#eceff1')
        
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()

def main():
    print(f"=== Assembling Intent Candidate: {TITLE} ===")
    
    frame_bytes = FRAME_PATH.read_bytes()
    middle_bytes = MIDDLE_PATH.read_bytes()
    
    # 1. Compose the raw body
    output_body = bytearray()
    for ci in range(4):
        for si in range(STAGES):
            if si in (0, 5):
                output_body.extend(get_row(frame_bytes, ci, si))
            else:
                output_body.extend(get_row(middle_bytes, ci, si))
    
    raw_candidate = bytes(output_body)
    
    # 2. Measure & Bound
    freqs = np.logspace(math.log10(20), math.log10(20000), 1000)
    raw_crown = measure_max_crown(raw_candidate, freqs)
    print(f"Raw Cascade Crown: {raw_crown:+.2f} dB")
    
    trim_db = 0.0
    if raw_crown > 27.0:
        trim_db = raw_crown - 27.0
        per_stage_ratio = 10.0 ** (-trim_db / (20.0 * 6.0))
        
        words = list(struct.unpack("<120H", raw_candidate))
        for row_idx in range(24):
            w4_idx = row_idx * 5 + 4
            orig_b0 = trench_ffi.decode(words[w4_idx])
            words[w4_idx] = trench_ffi.encode(orig_b0 * per_stage_ratio)
            
        bounded_candidate = struct.pack("<120H", *words)
        bounded_crown = measure_max_crown(bounded_candidate, freqs)
        print(f"Bounded Cascade Crown: {bounded_crown:+.2f} dB (Global Trim: -{trim_db:.2f} dB total)")
    else:
        bounded_candidate = raw_candidate
        bounded_crown = raw_crown
    
    cand_path = OUT_DIR / f"{SLUG}.body240"
    cand_path.write_bytes(bounded_candidate)
    (PLUGIN_BODIES_DIR / f"{SLUG}.body240").write_bytes(bounded_candidate)
    
    # 3. Generate Clean Plot
    plot_path = OUT_DIR / f"{SLUG}_response.png"
    generate_clean_plot(bounded_candidate, TITLE, plot_path, freqs)
    
    # 4. Generate JSON Manifest & Row Audit
    row_audit_list = []
    cnames = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
    for ci, cname in enumerate(cnames):
        for si in range(STAGES):
            r = get_row(bounded_candidate, ci, si)
            owner = "Talking Hedz (S1/S6 Frame)" if si in (0,5) else "Violin Cave (S2-S5 Middle)"
            words = struct.unpack("<5H", r)
            row_audit_list.append({
                "corner": cname,
                "stage": si + 1,
                "owner": owner,
                "bytes_hex": r.hex(),
                "words_u16_le": [f"0x{w:04x}" for w in words]
            })
            
    manifest = {
        "slug": SLUG,
        "title": TITLE,
        "intent": INTENT_SENTENCE,
        "poses": POSES,
        "source_frame": str(FRAME_PATH),
        "source_middle": str(MIDDLE_PATH),
        "candidate_body": str(cand_path),
        "candidate_sha256": hashlib.sha256(bounded_candidate).hexdigest(),
        "applied_global_trim_db": round(-trim_db, 2),
        "bounded_crown_db": round(bounded_crown, 2),
        "row_audit": row_audit_list
    }
    
    man_path = OUT_DIR / f"{SLUG}.manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    
    # 5. Shared-Gain Audition Rendering
    print("Generating 7 Shared-Gain Auditions...")
    
    dry_path = ROOT / "dev" / "tmp" / "iconic_presets_20260722" / "rom_frames_rich_sources_01" / "real_audio" / "wav" / "dry__tam_tam.wav"
    dry_sr, dry_data = wavfile.read(dry_path)
    if dry_data.dtype == np.int16:
        float_audio = dry_data.astype(np.float32) / 32768.0
    elif dry_data.dtype == np.float32:
        float_audio = dry_data
    else:
        float_audio = dry_data.astype(np.float32) / np.max(np.abs(dry_data))
    if float_audio.ndim > 1: float_audio = float_audio[:, 0]
    
    num_samples = len(float_audio)
    block_size = 64
    num_blocks = num_samples // block_size
    
    renders = {}
    
    # Render definitions (Hold/Sweep)
    def make_blocks(m_start, m_end, q_start, q_end):
        m = np.linspace(m_start, m_end, num_blocks, dtype=np.float32)
        q = np.linspace(q_start, q_end, num_blocks, dtype=np.float32)
        return m, q
        
    tasks = {
        "hold_M0_Q0": make_blocks(0.0, 0.0, 0.0, 0.0),
        "hold_M100_Q0": make_blocks(1.0, 1.0, 0.0, 0.0),
        "hold_M0_Q100": make_blocks(0.0, 0.0, 1.0, 1.0),
        "hold_M100_Q100": make_blocks(1.0, 1.0, 1.0, 1.0),
        "sweep_M_at_Q0": make_blocks(0.0, 1.0, 0.0, 0.0),
        "sweep_M_at_Q100": make_blocks(0.0, 1.0, 1.0, 1.0),
        "sweep_Q_at_M50": make_blocks(0.5, 0.5, 0.0, 1.0)
    }
    
    global_max = 0.0
    
    # Pass 1: Render and find global max peak
    for name, (m_arr, q_arr) in tasks.items():
        raw_out = trench_ffi.engine_render_automated(
            bounded_candidate, m_arr.tolist(), q_arr.tolist(), float_audio.tobytes(), float(dry_sr), block=block_size
        )
        arr_out = np.frombuffer(raw_out, dtype=np.float32)
        renders[name] = arr_out
        peak = np.max(np.abs(arr_out))
        if peak > global_max:
            global_max = peak
            
    print(f"Global max absolute peak across all 7 renders: {global_max:.6f}")
    
    # Pass 2: Apply shared gain normalization
    if global_max > 1e-6:
        shared_gain_scalar = 0.891 / global_max
    else:
        shared_gain_scalar = 1.0
        
    for name, arr_out in renders.items():
        arr_norm = arr_out * shared_gain_scalar
        wav_path = OUT_DIR / f"{SLUG}__{name}.wav"
        wavfile.write(wav_path, dry_sr, (arr_norm * 32767.0).astype(np.int16))
        
    print(f"Success! {SLUG} pipeline completed.")

if __name__ == "__main__":
    main()
