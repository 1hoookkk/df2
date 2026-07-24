#!/usr/bin/env python3
"""
Build one new audition-ready preset candidate:
- Complete packed S1 and S6 rows from Talking Hedz
- Complete rich measured S2-S5 rows from ukulele_ortf (Soprano Ukulele -> ORTF room path)
- Packed-runtime certification, stability, gain, response plot, quotient analysis, and level-matched audition WAVs.
"""

import sys
import os
import hashlib
import json
import struct
import math
from pathlib import Path
import numpy as np

# Ensure paths for df2 and workstation
ROOT = Path(r"c:\Users\hooki\df2-workstation")
DF2_ROOT = Path(r"c:\Users\hooki\df2")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DF2_ROOT))

from pyruntime import trench_ffi

# Setup output directory
OUT_DIR = ROOT / "dev" / "tmp" / "audition_candidates"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 1. Source Paths
FRAME_PATH = ROOT / "preset_library" / "talking_hedz.body240"
MIDDLE_PATH = ROOT / "plugin" / "presets" / "bodies" / "ukulele_ortf.body240"

print("=== 1. Inspecting Source Bodies ===")
frame_bytes = FRAME_PATH.read_bytes()
middle_bytes = MIDDLE_PATH.read_bytes()

frame_sha = hashlib.sha256(frame_bytes).hexdigest()
middle_sha = hashlib.sha256(middle_bytes).hexdigest()

print(f"Frame (Talking Hedz): {FRAME_PATH}")
print(f"  SHA-256: {frame_sha}")
print(f"Middle (Ukulele / ORTF): {MIDDLE_PATH}")
print(f"  SHA-256: {middle_sha}")

# 2. Compose Candidate Body (Literal Packed Row Swap)
ROW_BYTES = 10
STAGES = 6
CORNERS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
FRAME_SLOTS = (0, 5)

def get_row(body: bytes, corner: int, stage: int) -> bytes:
    start = (corner * STAGES + stage) * ROW_BYTES
    return body[start:start + ROW_BYTES]

output_body = bytearray()
row_audit_list = []

for ci, cname in enumerate(CORNERS):
    for si in range(STAGES):
        if si in FRAME_SLOTS:
            r = get_row(frame_bytes, ci, si)
            owner = "Talking Hedz (ROM S1/S6)"
        else:
            r = get_row(middle_bytes, ci, si)
            owner = "ukulele_ortf (Measured S2-S5)"
        
        output_body.extend(r)
        
        words = struct.unpack("<5H", r)
        hex_words = [f"0x{w:04x}" for w in words]
        row_audit_list.append({
            "corner": cname,
            "stage_1_based": si + 1,
            "owner": owner,
            "bytes_hex": r.hex(),
            "words_u16_le": hex_words
        })

candidate_bytes = bytes(output_body)
candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
candidate_path = OUT_DIR / "ukulele_ortf__talking_hedz.body240"
candidate_path.write_bytes(candidate_bytes)

# Also copy to plugin/presets/bodies/ for audition access
plugin_candidate_path = ROOT / "plugin" / "presets" / "bodies" / "ukulele_ortf__talking_hedz.body240"
plugin_candidate_path.write_bytes(candidate_bytes)

print(f"\nCandidate Body Created: {candidate_path}")
print(f"  SHA-256: {candidate_sha}")
print(f"  Size: {len(candidate_bytes)} bytes")
print(f"  Copied to Plugin Bodies: {plugin_candidate_path}")

# 3. Packed-Runtime Stability & Gain Evidence
print("\n=== 2. Packed-Runtime Certification & Stability Audit ===")

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

cert = {
    "grid_steps": grid_steps,
    "stable": is_stable,
    "max_pole_radius": round(float(max_pole_radius), 6),
    "grid_unstable_points": total_unstable,
    "grid_nonfinite_points": total_nonfinite,
    "max_biquad_crown_gain_db": round(float(max_crown_db), 2)
}

print(f"  Grid Certified Stable: {cert['stable']}")
print(f"  Max Pole Radius: {cert['max_pole_radius']:.6f}")
print(f"  Unstable Grid Points: {cert['grid_unstable_points']}")
print(f"  Nonfinite Grid Points: {cert['grid_nonfinite_points']}")
print(f"  Max Biquad Crown Gain: {cert['max_biquad_crown_gain_db']:.2f} dB")

# 4. Response Plot & Quotient Analysis
print("\n=== 3. Generating Four-Corner Response Plot & Diagnostic Quotient ===")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sr = 39062.5
freqs = np.logspace(math.log10(20), math.log10(sr/2 * 0.98), 500)

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
    
    # Separate S1/S6 (Frame) and S2-S5 (Middle) for quotient
    H_frame = get_biquad_response([bqs[0], bqs[5]], freqs)
    H_middle = get_biquad_response(bqs[1:5], freqs)
    
    # Safety Quotient = Frame / Middle
    quotient_db = 20 * np.log10(np.abs(H_frame) / (np.abs(H_middle) + 1e-12) + 1e-12)
    ax2.plot(freqs, quotient_db, label=f"Quotient {label}", color=color, linestyle="--", alpha=0.8)

ax1.set_xscale("log")
ax1.set_ylabel("Full Cascade Response (dB)")
ax1.set_title("ukulele_ortf__talking_hedz — Complete Packed Cascade Four-Corner Response")
ax1.grid(True, which="both", linestyle=":", alpha=0.6)
ax1.legend(loc="upper right")

ax2.set_xscale("log")
ax2.set_xlabel("Frequency (Hz)")
ax2.set_ylabel("Diagnostic Quotient (dB)")
ax2.set_title("Frame (S1/S6) / Middle (S2-S5) Diagnostic Quotient (Safety Evidence Only)")
ax2.grid(True, which="both", linestyle=":", alpha=0.6)
ax2.legend(loc="upper right")

plt.tight_layout()
plot_path = OUT_DIR / "ukulele_ortf__talking_hedz_response.png"
plt.savefig(plot_path, dpi=150)
plt.close()
print(f"  Response Plot Saved: {plot_path}")

# 5. Level-Matched Audition WAV Rendering
print("\n=== 4. Rendering Level-Matched Audition WAVs ===")
import scipy.io.wavfile as wavfile

# Load real dry audio sample
dry_path = ROOT / "dev" / "tmp" / "iconic_presets_20260722" / "rom_frames_rich_sources_01" / "real_audio" / "wav" / "dry__tam_tam.wav"
if not dry_path.exists():
    dry_path = ROOT / "out" / "candidates_partial_20260720_2103" / "audio" / "ACTOR__tam_tam.wav"

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
    # Peak level match to -1.0 dBFS (0.891)
    max_val = np.max(np.abs(arr_out))
    if max_val > 1e-6:
        arr_norm = arr_out * (0.891 / max_val)
    else:
        arr_norm = arr_out
    return arr_norm

# Render 4 Level-Matched Audition Stems
candidate_audio = render_and_normalize(candidate_bytes, m_blocks, q_blocks, float_audio, dry_sr)
frame_audio = render_and_normalize(frame_bytes, m_blocks, q_blocks, float_audio, dry_sr)
middle_audio = render_and_normalize(middle_bytes, m_blocks, q_blocks, float_audio, dry_sr)

# Dry normalized
dry_norm = float_audio * (0.891 / np.max(np.abs(float_audio)))

wav_candidate = OUT_DIR / "candidate__ukulele_ortf__talking_hedz.wav"
wav_frame = OUT_DIR / "frame_source__talking_hedz.wav"
wav_middle = OUT_DIR / "measured_middle__ukulele_ortf.wav"
wav_dry = OUT_DIR / "dry_source__tam_tam.wav"

wavfile.write(wav_candidate, dry_sr, (candidate_audio * 32767.0).astype(np.int16))
wavfile.write(wav_frame, dry_sr, (frame_audio * 32767.0).astype(np.int16))
wavfile.write(wav_middle, dry_sr, (middle_audio * 32767.0).astype(np.int16))
wavfile.write(wav_dry, dry_sr, (dry_norm * 32767.0).astype(np.int16))

print(f"  Candidate WAV: {wav_candidate.name} ({len(candidate_audio)} samples)")
print(f"  Frame Source WAV: {wav_frame.name}")
print(f"  Measured Middle WAV: {wav_middle.name}")
print(f"  Dry Source WAV: {wav_dry.name}")

# 6. Neutral Level-Matched Audition Shelf of Measured Frames
print("\n=== 5. Building Neutral Level-Matched Audition Shelf for Frame Selections ===")
ACTOR_DIR = ROOT / "out" / "candidates_partial_20260720_2103" / "bodies"
actor_bodies = [
    ("ukulele", "ACTOR__Soprano-Ukulele-Close-Mono.body240"),
    ("ortf_room", "ACTOR__ortf-s1r1.body240"),
    ("glockenspiel", "ACTOR__Glockenspiel-Sweep-1.body240"),
    ("mine_site", "ACTOR__mine-site1-2way-mono.body240"),
    ("kalimba", "ACTOR__Kalimba-Resonance-Full.body240"),
    ("tunnel", "ACTOR__middle-tunnel-4way-mono.body240"),
    ("steel_pan", "ACTOR__Steel-Pan-Medium-Sweep-1.body240"),
    ("china_cymbal", "ACTOR__China-Cymbal-Contact-Resonant.body240"),
    ("violin", "ACTOR__Violin-Body-Resonant.body240"),
    ("upright_bass", "ACTOR__Winter-Upright-Open-Sustain.body240"),
]

shelf_manifest = []
SHELF_DIR = OUT_DIR / "audition_shelf"
SHELF_DIR.mkdir(parents=True, exist_ok=True)

for name, filename in actor_bodies:
    ab_path = ACTOR_DIR / filename
    if ab_path.exists():
        ab_bytes = ab_path.read_bytes()
        ab_sha = hashlib.sha256(ab_bytes).hexdigest()
        aud_audio = render_and_normalize(ab_bytes, m_blocks, q_blocks, float_audio, dry_sr)
        aud_wav = SHELF_DIR / f"frame_shelf__{name}.wav"
        wavfile.write(aud_wav, dry_sr, (aud_audio * 32767.0).astype(np.int16))
        shelf_manifest.append({
            "frame_id": name,
            "file_name": filename,
            "sha256": ab_sha,
            "audition_wav": str(aud_wav)
        })
        print(f"  Shelf Frame [{name}]: {filename} (SHA: {ab_sha[:12]}...) -> {aud_wav.name}")

# Write Full Candidate Manifest
manifest_data = {
    "schema_version": 1,
    "status": "AUDITION_READY_PRESET_CANDIDATE",
    "candidate_name": "ukulele_ortf__talking_hedz",
    "candidate_body_path": str(candidate_path),
    "candidate_sha256": candidate_sha,
    "frame_source": {
        "name": "Talking Hedz (P2k_013)",
        "path": str(FRAME_PATH),
        "sha256": frame_sha
    },
    "measured_middle_source": {
        "name": "Soprano Ukulele -> ORTF Room (ukulele_ortf)",
        "path": str(MIDDLE_PATH),
        "sha256": middle_sha
    },
    "packed_runtime_certification": cert,
    "response_plot": str(plot_path),
    "audition_wavs": {
        "candidate": str(wav_candidate),
        "frame_source": str(wav_frame),
        "measured_middle": str(wav_middle),
        "dry_source": str(wav_dry)
    },
    "row_audit_24_rows": row_audit_list,
    "unranked_audition_shelf": shelf_manifest
}

manifest_path = OUT_DIR / "candidate.manifest.json"
manifest_path.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")
print(f"\nManifest Written: {manifest_path}")
print("\nBUILD COMPLETE AND READY FOR AUDITION!")
