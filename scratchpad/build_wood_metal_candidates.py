#!/usr/bin/env python3
"""
Intent-Driven Multi-Candidate Builder: Wooden Chest to Metal Storm
- Fits 4 raw WAVs into a measured object (S2-S5 source) with exact floor renorm.
- Pairs the measured middle with 4 purposeful ROM frames: MegaSweepz, Meaty Gizmo, Talking Hedz, Ear Bender.
- Bounds the crown to +27.0 dB with one global SCALE trim across all 24 rows per body.
- Generates 7 shared-gain auditions per candidate, plus plots and manifests.
"""

import sys
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
for p in [str(ROOT / "tools"), str(DF2_ROOT), str(DF2_ROOT / "pyruntime")]:
    sys.path.insert(0, p)

from tf_ingest import ir_to_tf, FREQS
from pyruntime import trench_ffi
from pyruntime.packed_interp import coeffs_to_words
from src.utils.body240 import raw_from_words

OUT_DIR = ROOT / "dev" / "tmp" / "audition_candidates"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PLUGIN_BODIES_DIR = ROOT / "plugin" / "presets" / "bodies"

ENGINE_SR = 39062.5
ROW_BYTES = 10
STAGES = 6

INTENT_SENTENCE = "HOME is a dark wooden bass chest; AWAY becomes a dry sheet-metal snarl; Q releases the stored resonance—the piano blooms sympathetically and the cymbal erupts into a sustained metallic storm."
TITLE_BASE = "Wooden Chest to Metal Storm"

WAVS = {
    "M0_Q0": ROOT / "wav-source-library/measured_objects/ir_library/piano_upright/Winter Upright Open Bass Sustain.wav",
    "M100_Q0": ROOT / "wav-source-library/measured_objects/ir_library/cymbals/China Cymbal Contact Damped.wav",
    "M0_Q100": ROOT / "wav-source-library/measured_objects/ir_library/piano_upright/Winter Upright Sympathetic Resonance.wav",
    "M100_Q100": ROOT / "wav-source-library/measured_objects/ir_library/cymbals/China Cymbal Contact Resonant.wav",
}

POSES_MEANING = {
    "M0_Q0": "Low wooden chest: fundamental around 140 Hz, dark and weighty",
    "M100_Q0": "Dry metal plate: bright 8-9 kHz structure without the full tail",
    "M0_Q100": "The bass chest opens: sympathetic modes bloom through the wood",
    "M100_Q100": "Full metallic storm: strong high shimmer plus low gong-like modes"
}

FRAMES = [
    ("megasweepz", "P2k_001_megasweepz.bin"),
    ("meaty_gizmo", "P2k_004_meaty_gizmo.bin"),
    ("talking_hedz", "P2k_013_talking_hedz.bin"),
    ("ear_bender", "P2k_031_ear_bender.bin")
]

def corner_rows(wav_path):
    tf = ir_to_tf(wav_path, detilt=True)
    db = np.array(tf["mag_db"])
    band = (FREQS >= 60.0) & (FREQS <= 16000.0)
    return trench_ffi.fit_corner_from_magnitude(
        list(zip(FREQS[band].tolist(), db[band].tolist())), ENGINE_SR)

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

def measure_max_crown(body_bytes, eval_freqs):
    max_cr = -999.0
    for m in np.linspace(0.0, 1.0, 9):
        for q in np.linspace(0.0, 1.0, 9):
            pr = trench_ffi.packed_probe(body_bytes, float(m), float(q))
            if pr:
                H = get_biquad_response(pr["biquad"], eval_freqs)
                cr = 20 * np.log10(np.max(np.abs(H)) + 1e-12)
                if cr > max_cr: max_cr = cr
    return max_cr

def generate_clean_plot(candidate_bytes, title, output_path, eval_freqs):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=200)
    fig.patch.set_facecolor('#0f1117')
    ax.set_facecolor('#161822')
    
    morph_steps = [(0.25, 'M25 Q0', '#00e5ff', 0.35, ':'),
                   (0.50, 'M50 Q0', '#00e5ff', 0.55, '--'),
                   (0.75, 'M75 Q0', '#00e5ff', 0.75, '-.')]
    
    for m_val, label, col, alpha, ls in morph_steps:
        pr = trench_ffi.packed_probe(candidate_bytes, m_val, 0.0)
        H = get_biquad_response(pr["biquad"], eval_freqs)
        mag_db = 20 * np.log10(np.abs(H) + 1e-12)
        ax.plot(eval_freqs, mag_db, color='#4dd0e1', linestyle=ls, linewidth=1.5, alpha=alpha, label=label)
    
    corners = [
        (0.0, 0.0, 'HOME (M0 Q0)', '#00e5ff', 2.8),
        (1.0, 0.0, 'AWAY (M100 Q0)', '#76ff03', 2.8),
        (0.0, 1.0, 'PUSH HOME (M0 Q100)', '#e040fb', 2.8),
        (1.0, 1.0, 'PUSH AWAY (M100 Q100)', '#ff3d00', 2.8)
    ]
    
    all_mags = []
    for m_val, q_val, label, col, lw in corners:
        pr = trench_ffi.packed_probe(candidate_bytes, m_val, q_val)
        H = get_biquad_response(pr["biquad"], eval_freqs)
        mag_db = 20 * np.log10(np.abs(H) + 1e-12)
        all_mags.extend(mag_db)
        ax.plot(eval_freqs, mag_db, color=col, linewidth=lw, label=label, zorder=5)
    
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
    print("=== Step 1: Fitting 4 Raw WAVs for the Middle Object ===")
    
    CORNER_MQ = {"M0_Q0": (0.0, 0.0), "M100_Q0": (1.0, 0.0), "M0_Q100": (0.0, 1.0), "M100_Q100": (1.0, 1.0)}
    Z1 = np.exp(-2j * np.pi * FREQS / ENGINE_SR); Z2n = Z1 * Z1

    def rows_db(rows_words):
        body1 = raw_from_words({c: rows_words for c in CORNER_MQ})
        pr = trench_ffi.packed_probe(body1, 0.0, 0.0)
        mag = np.ones_like(FREQS)
        for (b0, b1, b2, a1, a2) in pr["biquad"]:
            mag *= np.abs(b0 + b1 * Z1 + b2 * Z2n) / np.maximum(np.abs(1 + a1 * Z1 + a2 * Z2n), 1e-12)
        return 20 * np.log10(np.maximum(mag, 1e-9))

    words = {}
    for c, wpath in WAVS.items():
        print(f"  Fitting {c}: {wpath.name}...")
        rows = corner_rows(wpath)
        # Floor renorm
        wtmp = [tuple(int(v) for v in coeffs_to_words(*r)) for r in rows]
        med = float(np.median(rows_db(wtmp)))
        g = 10 ** (-med / 20.0 / 6.0)
        rows = [(c0, c1, c2, c3, c4 * g) for (c0, c1, c2, c3, c4) in rows]
        words[c] = [tuple(int(v) for v in coeffs_to_words(*r)) for r in rows]
        
    middle_bytes = raw_from_words(words)
    print("  -> Measured middle constructed (floor renorm applied).")
    
    eval_freqs = np.logspace(math.log10(20), math.log10(20000), 1000)
    
    dry_path = ROOT / "dev" / "tmp" / "iconic_presets_20260722" / "rom_frames_rich_sources_01" / "real_audio" / "wav" / "dry__tam_tam.wav"
    dry_sr, dry_data = wavfile.read(dry_path)
    if dry_data.dtype == np.int16: float_audio = dry_data.astype(np.float32) / 32768.0
    elif dry_data.dtype == np.float32: float_audio = dry_data
    else: float_audio = dry_data.astype(np.float32) / np.max(np.abs(dry_data))
    if float_audio.ndim > 1: float_audio = float_audio[:, 0]
    
    num_samples = len(float_audio)
    block_size = 64
    num_blocks = num_samples // block_size
    def make_blocks(m_start, m_end, q_start, q_end):
        return np.linspace(m_start, m_end, num_blocks, dtype=np.float32), np.linspace(q_start, q_end, num_blocks, dtype=np.float32)
        
    tasks = {
        "hold_M0_Q0": make_blocks(0.0, 0.0, 0.0, 0.0),
        "hold_M100_Q0": make_blocks(1.0, 1.0, 0.0, 0.0),
        "hold_M0_Q100": make_blocks(0.0, 0.0, 1.0, 1.0),
        "hold_M100_Q100": make_blocks(1.0, 1.0, 1.0, 1.0),
        "sweep_M_at_Q0": make_blocks(0.0, 1.0, 0.0, 0.0),
        "sweep_M_at_Q100": make_blocks(0.0, 1.0, 1.0, 1.0),
        "sweep_Q_at_M50": make_blocks(0.5, 0.5, 0.0, 1.0)
    }

    cnames = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]

    print("\n=== Step 2: Assembling 4 Candidates ===")
    
    for frame_name, frame_file in FRAMES:
        slug = f"wood_metal__{frame_name}"
        title = f"{TITLE_BASE} ({frame_name})"
        print(f"\nProcessing {title}...")
        
        frame_path = DF2_ROOT / "ref" / "presets" / frame_file
        frame_bytes = frame_path.read_bytes()
        
        output_body = bytearray()
        for ci in range(4):
            for si in range(STAGES):
                if si in (0, 5):
                    output_body.extend(get_row(frame_bytes, ci, si))
                else:
                    output_body.extend(get_row(middle_bytes, ci, si))
                    
        raw_candidate = bytes(output_body)
        raw_crown = measure_max_crown(raw_candidate, eval_freqs)
        
        trim_db = 0.0
        if raw_crown > 27.0:
            trim_db = raw_crown - 27.0
            per_stage_ratio = 10.0 ** (-trim_db / (20.0 * 6.0))
            words_b = list(struct.unpack("<120H", raw_candidate))
            for row_idx in range(24):
                w4_idx = row_idx * 5 + 4
                orig_b0 = trench_ffi.decode(words_b[w4_idx])
                words_b[w4_idx] = trench_ffi.encode(orig_b0 * per_stage_ratio)
            bounded_candidate = struct.pack("<120H", *words_b)
            bounded_crown = measure_max_crown(bounded_candidate, eval_freqs)
            print(f"  Raw Crown: {raw_crown:+.2f} dB -> Trim: -{trim_db:.2f} dB -> Bounded: {bounded_crown:+.2f} dB")
        else:
            bounded_candidate = raw_candidate
            bounded_crown = raw_crown
            print(f"  Raw Crown: {raw_crown:+.2f} dB -> Compliant (No trim)")
            
        cand_path = OUT_DIR / f"{slug}.body240"
        cand_path.write_bytes(bounded_candidate)
        (PLUGIN_BODIES_DIR / f"{slug}.body240").write_bytes(bounded_candidate)
        
        plot_path = OUT_DIR / f"{slug}_response.png"
        generate_clean_plot(bounded_candidate, title, plot_path, eval_freqs)
        
        row_audit_list = []
        for ci, cname in enumerate(cnames):
            for si in range(STAGES):
                r = get_row(bounded_candidate, ci, si)
                owner = f"{frame_name} (S1/S6 Frame)" if si in (0,5) else f"Wood-Metal Fit (S2-S5 Middle, {cname})"
                words_u = struct.unpack("<5H", r)
                row_audit_list.append({
                    "corner": cname, "stage": si + 1, "owner": owner,
                    "bytes_hex": r.hex(), "words_u16_le": [f"0x{w:04x}" for w in words_u]
                })
                
        manifest = {
            "slug": slug, "title": title, "intent": INTENT_SENTENCE, "poses": POSES_MEANING,
            "source_frame": str(frame_path), "source_wavs": {k: str(v) for k, v in WAVS.items()},
            "candidate_body": str(cand_path), "candidate_sha256": hashlib.sha256(bounded_candidate).hexdigest(),
            "applied_global_trim_db": round(-trim_db, 2), "bounded_crown_db": round(bounded_crown, 2),
            "row_audit": row_audit_list
        }
        man_path = OUT_DIR / f"{slug}.manifest.json"
        man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        
        # 5. Shared-Gain Auditions
        renders = {}
        global_max = 0.0
        for name, (m_arr, q_arr) in tasks.items():
            raw_out = trench_ffi.engine_render_automated(
                bounded_candidate, m_arr.tolist(), q_arr.tolist(), float_audio.tobytes(), float(dry_sr), block=block_size
            )
            arr_out = np.frombuffer(raw_out, dtype=np.float32)
            renders[name] = arr_out
            peak = np.max(np.abs(arr_out))
            if peak > global_max: global_max = peak
                
        shared_gain_scalar = 0.891 / global_max if global_max > 1e-6 else 1.0
        
        for name, arr_out in renders.items():
            arr_norm = arr_out * shared_gain_scalar
            wav_path = OUT_DIR / f"{slug}__{name}.wav"
            wavfile.write(wav_path, dry_sr, (arr_norm * 32767.0).astype(np.int16))
            
        print(f"  -> Generated {slug} (7 shared-gain WAVs, plot, manifest).")

    print("\n=== Success! Pipeline Complete. ===")

if __name__ == "__main__":
    main()
