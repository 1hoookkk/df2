#!/usr/bin/env python3
import sys, math, hashlib, json, struct
from pathlib import Path
import numpy as np
import scipy.io.wavfile as wavfile
from scipy.optimize import minimize, LinearConstraint
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(r"c:\Users\hooki\df2-workstation")
DF2_ROOT = Path(r"c:\Users\hooki\df2")
for p in [str(ROOT / "tools"), str(DF2_ROOT), str(DF2_ROOT / "pyruntime")]:
    sys.path.insert(0, p)

from tf_ingest import ir_to_tf, FREQS
from pyruntime import trench_ffi
from pyruntime.packed_interp import coeffs_to_words, kernel_to_biquad

OUT_DIR = ROOT / "dev" / "tmp" / "audition_candidates"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PLUGIN_BODIES_DIR = ROOT / "plugin" / "presets" / "bodies"

ENGINE_SR = 39062.5
ROW_BYTES = 10
STAGES = 6

PRESETS = [
    {
        "slug": "haunted_chapel_to_clockwork_tunnel",
        "title": "Haunted Chapel to Clockwork Tunnel",
        "frame": "P2k_022_deep_bouche.bin",
        "wavs": {
            "M0_Q0": ROOT / "wav-source-library/measured_objects/openair/st-patricks-church-patrington/st-patricks-church-patrington/stereo/ortf_s1r1.wav",
            "M100_Q0": ROOT / "wav-source-library/measured_objects/openair/innocent-railway-tunnel/innocent-railway-tunnel/mono/middle_tunnel_1way_mono.wav",
            "M0_Q100": ROOT / "wav-source-library/measured_objects/ir_library/misc/Glockenspiel Sweep 1.wav",
            "M100_Q100": ROOT / "wav-source-library/measured_objects/ir_library/misc/Steel Pan Medium Sweep 1.wav",
        }
    },
    {
        "slug": "intimate_wood_to_typewriter_cave",
        "title": "Intimate Wood to Typewriter Cave",
        "frame": "P2k_004_meaty_gizmo.bin",
        "wavs": {
            "M0_Q0": ROOT / "wav-source-library/measured_objects/ir_library/ukulele/Concert Ukulele Close Mono.wav",
            "M100_Q0": ROOT / "wav-source-library/measured_objects/openair/terrys-typing-room/terrys-typing-room/mono/terrys_typing_omni.wav",
            "M0_Q100": ROOT / "wav-source-library/measured_objects/ir_library/ukulele/Concert Ukulele Contact Mic.wav",
            "M100_Q100": ROOT / "wav-source-library/measured_objects/openair/gill-heads-mine/gill-heads-mine/mono/mine_site1_2way_mono.wav",
        }
    }
]

W = 2 * np.pi * FREQS / ENGINE_SR
Z = np.exp(1j * W)
Z1, Z2 = Z**(-1), Z**(-2)

def biquad_mag_db(bq):
    b0, b1, b2, a1, a2 = bq
    H = (b0 + b1*Z1 + b2*Z2) / (1 + a1*Z1 + a2*Z2)
    return 20 * np.log10(np.abs(H) + 1e-12)

def cascade_mag_db(biquads):
    H = np.ones_like(Z, dtype=complex)
    for (b0, b1, b2, a1, a2) in biquads:
        H *= (b0 + b1*Z1 + b2*Z2) / (1 + a1*Z1 + a2*Z2)
    return 20 * np.log10(np.abs(H) + 1e-12)

def get_row(body: bytes, corner: int, stage: int) -> bytes:
    start = (corner * STAGES + stage) * ROW_BYTES
    return body[start:start + ROW_BYTES]

def optimize_4_stages(target_db, init_biquads):
    def loss(x):
        H = np.ones_like(Z, dtype=complex)
        for i in range(4):
            b0, b1, b2, a1, a2 = x[i*5:(i+1)*5]
            H *= (b0 + b1*Z1 + b2*Z2) / (1 + a1*Z1 + a2*Z2)
        return np.mean((20 * np.log10(np.abs(H) + 1e-12) - target_db)**2)
    
    A = np.zeros((12, 20))
    ub = np.zeros(12)
    lb = np.full(12, -np.inf)
    for i in range(4):
        A[i*3, i*5 + 4] = 1.0; ub[i*3] = 0.998
        A[i*3+1, i*5 + 3] = 1.0; A[i*3+1, i*5 + 4] = -1.0; ub[i*3+1] = 0.998
        A[i*3+2, i*5 + 3] = -1.0; A[i*3+2, i*5 + 4] = -1.0; ub[i*3+2] = 0.998
    
    lc = LinearConstraint(A, lb, ub)
    x0 = np.array(init_biquads).flatten()
    res = minimize(loss, x0, constraints=[lc], method='SLSQP', options={'maxiter': 300, 'ftol': 1e-4})
    
    out_biquads = []
    for i in range(4):
        out_biquads.append(tuple(res.x[i*5:(i+1)*5]))
    return out_biquads, res.fun

def build_residual_middle(frame_bytes, wav_dict):
    middle_biquads = []
    cnames = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
    
    for ci, cname in enumerate(cnames):
        tf = ir_to_tf(wav_dict[cname], detilt=True)
        measured_db = np.array(tf["mag_db"])
        
        w1 = struct.unpack("<5H", get_row(frame_bytes, ci, 0))
        w6 = struct.unpack("<5H", get_row(frame_bytes, ci, 5))
        bq1 = kernel_to_biquad([trench_ffi.decode(w) for w in w1])
        bq6 = kernel_to_biquad([trench_ffi.decode(w) for w in w6])
        frame_db = biquad_mag_db(bq1) + biquad_mag_db(bq6)
        
        residual_db = measured_db - frame_db
        
        band = (FREQS >= 60.0) & (FREQS <= 16000.0)
        ffi_rows = trench_ffi.fit_corner_from_magnitude(
            list(zip(FREQS[band].tolist(), residual_db[band].tolist())), ENGINE_SR)
        
        ffi_biquads = [kernel_to_biquad(r) for r in ffi_rows]
        
        prominences = []
        for i, bq in enumerate(ffi_biquads):
            resp = biquad_mag_db(bq)
            prominences.append((np.max(np.abs(resp)), bq))
        prominences.sort(key=lambda x: x[0], reverse=True)
        top_4_biquads = [p[1] for p in prominences[:4]]
        
        print(f"    Optimizing {cname} residual...", end="", flush=True)
        opt_biquads, loss = optimize_4_stages(residual_db, top_4_biquads)
        print(f" MSE: {loss:.2f} dB²")
        middle_biquads.append(opt_biquads)
        
    return middle_biquads

def biquad_to_kernel(bq):
    return tuple(bq)

def generate_clean_plot(candidate_bytes, title, output_path):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=200)
    fig.patch.set_facecolor('#0f1117')
    ax.set_facecolor('#161822')
    
    morph_steps = [(0.25, 'M25 Q0', '#00e5ff', 0.35, ':'),
                   (0.50, 'M50 Q0', '#00e5ff', 0.55, '--'),
                   (0.75, 'M75 Q0', '#00e5ff', 0.75, '-.')]
    for m_val, label, col, alpha, ls in morph_steps:
        pr = trench_ffi.packed_probe(candidate_bytes, m_val, 0.0)
        ax.plot(FREQS, cascade_mag_db(pr["biquad"]), color='#4dd0e1', linestyle=ls, linewidth=1.5, alpha=alpha, label=label)
    
    corners = [(0.0, 0.0, 'HOME (M0 Q0)', '#00e5ff', 2.8),
               (1.0, 0.0, 'AWAY (M100 Q0)', '#76ff03', 2.8),
               (0.0, 1.0, 'PUSH HOME (M0 Q100)', '#e040fb', 2.8),
               (1.0, 1.0, 'PUSH AWAY (M100 Q100)', '#ff3d00', 2.8)]
    
    all_mags = []
    for m_val, q_val, label, col, lw in corners:
        pr = trench_ffi.packed_probe(candidate_bytes, m_val, q_val)
        mag_db = cascade_mag_db(pr["biquad"])
        all_mags.extend(mag_db)
        ax.plot(FREQS, mag_db, color=col, linewidth=lw, label=label, zorder=5)
    
    all_mags = np.array(all_mags)
    ax.set_ylim(max(-70.0, np.percentile(all_mags, 1) - 5.0), min(40.0, np.percentile(all_mags, 99) + 8.0))
    ax.set_xscale("log"); ax.set_xlim(20, 20000)
    ax.set_xticks([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000])
    ax.set_xticklabels(['20', '50', '100', '200', '500', '1k', '2k', '5k', '10k', '20k'], fontsize=10, color='#b0bec5')
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
    dry_path = ROOT / "dev" / "tmp" / "iconic_presets_20260722" / "rom_frames_rich_sources_01" / "real_audio" / "wav" / "dry__tam_tam.wav"
    dry_sr, dry_data = wavfile.read(dry_path)
    float_audio = dry_data.astype(np.float32) / 32768.0 if dry_data.dtype == np.int16 else dry_data
    if float_audio.ndim > 1: float_audio = float_audio[:, 0]
    num_blocks = len(float_audio) // 64
    tasks = {
        "hold_M0_Q0": (np.linspace(0.0, 0.0, num_blocks, dtype=np.float32), np.linspace(0.0, 0.0, num_blocks, dtype=np.float32)),
        "hold_M100_Q0": (np.linspace(1.0, 1.0, num_blocks, dtype=np.float32), np.linspace(0.0, 0.0, num_blocks, dtype=np.float32)),
        "hold_M0_Q100": (np.linspace(0.0, 0.0, num_blocks, dtype=np.float32), np.linspace(1.0, 1.0, num_blocks, dtype=np.float32)),
        "hold_M100_Q100": (np.linspace(1.0, 1.0, num_blocks, dtype=np.float32), np.linspace(1.0, 1.0, num_blocks, dtype=np.float32)),
        "sweep_M_at_Q0": (np.linspace(0.0, 1.0, num_blocks, dtype=np.float32), np.linspace(0.0, 0.0, num_blocks, dtype=np.float32)),
        "sweep_M_at_Q100": (np.linspace(0.0, 1.0, num_blocks, dtype=np.float32), np.linspace(1.0, 1.0, num_blocks, dtype=np.float32)),
        "sweep_Q_at_M50": (np.linspace(0.5, 0.5, num_blocks, dtype=np.float32), np.linspace(0.0, 1.0, num_blocks, dtype=np.float32))
    }

    all_renders = {}
    
    for preset in PRESETS:
        print(f"\nProcessing {preset['title']}...")
        frame_path = DF2_ROOT / "ref" / "presets" / preset["frame"]
        frame_bytes = frame_path.read_bytes()
        
        opt_middle = build_residual_middle(frame_bytes, preset["wavs"])
        
        output_body = bytearray()
        cnames = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
        for ci in range(4):
            words = []
            words.extend(struct.unpack("<5H", get_row(frame_bytes, ci, 0)))
            for si in range(4):
                k = biquad_to_kernel(opt_middle[ci][si])
                words.extend(coeffs_to_words(*k))
            words.extend(struct.unpack("<5H", get_row(frame_bytes, ci, 5)))
            output_body.extend(struct.pack("<30H", *words))
            
        raw_candidate = bytes(output_body)
        
        max_cr = -999.0
        for m in np.linspace(0, 1, 9):
            for q in np.linspace(0, 1, 9):
                pr = trench_ffi.packed_probe(raw_candidate, float(m), float(q))
                cr = np.max(cascade_mag_db(pr["biquad"]))
                if cr > max_cr: max_cr = cr
                
        trim_db = 0.0
        if max_cr > 27.0:
            trim_db = max_cr - 27.0
            per_stage_ratio = 10.0 ** (-trim_db / (20.0 * 6.0))
            words_b = list(struct.unpack("<120H", raw_candidate))
            for row_idx in range(24):
                w4_idx = row_idx * 5 + 4
                words_b[w4_idx] = trench_ffi.encode(trench_ffi.decode(words_b[w4_idx]) * per_stage_ratio)
            bounded_candidate = struct.pack("<120H", *words_b)
        else:
            bounded_candidate = raw_candidate
            
        slug = preset["slug"]
        cand_path = OUT_DIR / f"{slug}.body240"
        cand_path.write_bytes(bounded_candidate)
        (PLUGIN_BODIES_DIR / f"{slug}.body240").write_bytes(bounded_candidate)
        
        generate_clean_plot(bounded_candidate, preset["title"], OUT_DIR / f"{slug}_response.png")
        
        for name, (m_arr, q_arr) in tasks.items():
            raw_out = trench_ffi.engine_render_automated(bounded_candidate, m_arr.tolist(), q_arr.tolist(), float_audio.tobytes(), float(dry_sr), block=64)
            all_renders[f"{slug}__{name}"] = np.frombuffer(raw_out, dtype=np.float32)

    print("\n=== Global Normalization of both presets ===")
    global_max = max(np.max(np.abs(arr)) for arr in all_renders.values())
    print(f"Global absolute peak across renders: {global_max:.6f}")
    shared_gain = 0.891 / global_max if global_max > 1e-6 else 1.0
    
    for name, arr in all_renders.items():
        wavfile.write(OUT_DIR / f"{name}.wav", dry_sr, (arr * shared_gain * 32767.0).astype(np.int16))
    print("Success! Pipeline Complete.")

if __name__ == "__main__":
    main()
