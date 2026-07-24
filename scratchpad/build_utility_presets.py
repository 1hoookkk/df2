#!/usr/bin/env python3
"""
Build Utility Presets: Peak Shelf Morph & Contrary Bandpass
- Fits mathematical transfer functions directly into 240-byte DF2 bodies.
- Saves generated bodies to plugin/presets/bodies/ and outputs audition plots.
"""

import sys, json, struct
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(r"c:\Users\hooki\df2-workstation")
DF2_ROOT = Path(r"c:\Users\hooki\df2")
for p in [str(ROOT / "tools"), str(DF2_ROOT), str(DF2_ROOT / "pyruntime")]:
    sys.path.insert(0, p)

from pyruntime import trench_ffi
from pyruntime.packed_interp import coeffs_to_words, kernel_to_biquad

OUT_DIR = ROOT / "dev" / "tmp" / "audition_candidates"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PLUGIN_BODIES_DIR = ROOT / "plugin" / "presets" / "bodies"

SR = 39062.5
FREQS = np.geomspace(30.0, 19200.0, 1024)
W = 2 * np.pi * FREQS / SR
Z = np.exp(1j * W)
Z1, Z2 = Z**(-1), Z**(-2)

def _db(mag):
    return 20.0 * np.log10(np.maximum(np.asarray(mag, dtype=float), 1e-9))

def _bump(f, fc, gain_db, width_oct=0.18):
    return gain_db * np.exp(-0.5 * (np.log2(f / fc) / width_oct) ** 2)

# --- 1. Peak Shelf Morph Transfer Function ---
def peak_shelf_morph(f, m, q):
    # E-MU Tutorial Specs:
    # m=0: Freq=246Hz, Shelf=-50 (lowpass heavy), Peak=-24dB
    # m=1: Freq=4488Hz, Shelf=+30 (mid-shelf/highpass), Peak=+1.5dB
    fc = 246.0 * ((4488.0 / 246.0) ** m)
    shelf = -50.0 + 80.0 * m   # -50 -> +30
    peak_base = -24.0 + 25.5 * m # -24 -> +1.5 dB
    
    # Tilt & rolloff shape based on shelf value
    tilt = (shelf / 50.0) * 8.0 * np.log2(f / fc)
    
    # Lowpass / Highpass weighting
    lp_weight = max(0.0, -shelf / 64.0)
    hp_weight = max(0.0, shelf / 64.0)
    
    lp_mag = 1.0 / np.sqrt(1.0 + (f / fc) ** 4)
    hp_mag = 1.0 / np.sqrt(1.0 + (fc / f) ** 4)
    
    base_db = lp_weight * _db(lp_mag) + hp_weight * _db(hp_mag) + (1.0 - lp_weight - hp_weight) * tilt
    
    # Peak bump height scales with q (pole radius resonance)
    peak_height = peak_base + 14.0 * q
    bump_db = _bump(f, fc, peak_height, width_oct=0.25)
    
    total_db = base_db + bump_db
    return np.clip(total_db, -60.0, 24.0)

# --- 2. Contrary Bandpass Transfer Function ---
def contrary_bp(f, m, q):
    # Low edge sweeps down 700 -> 285 Hz
    # High edge sweeps up 1400 -> 5200 Hz
    f_lo = 700.0 * (2.0 ** (-1.3 * m))
    f_hi = 1400.0 * (2.0 ** (1.9 * m))
    
    band = (1.0 / np.sqrt(1.0 + (f_lo / f) ** 8)) * (1.0 / np.sqrt(1.0 + (f / f_hi) ** 8))
    
    # Resonant bumps at both edges controlled by Q (pole radius)
    bump_lo = _bump(f, f_lo, 12.0 * q, 0.16)
    bump_hi = _bump(f, f_hi, 12.0 * q, 0.16)
    
    return _db(band) + bump_lo + bump_hi

PRESETS = [
    {
        "slug": "utility_peak_shelf_morph",
        "title": "Utility: Peak Shelf Morph (E-MU)",
        "fn": peak_shelf_morph
    },
    {
        "slug": "utility_contrary_bandpass",
        "title": "Utility: Contrary Bandpass (X3)",
        "fn": contrary_bp
    }
]

def cascade_mag_db(biquads):
    H = np.ones_like(Z, dtype=complex)
    for (b0, b1, b2, a1, a2) in biquads:
        H *= (b0 + b1*Z1 + b2*Z2) / (1 + a1*Z1 + a2*Z2)
    return 20 * np.log10(np.abs(H) + 1e-12)

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

def build_utility_preset(preset):
    title = preset["title"]
    fn = preset["fn"]
    slug = preset["slug"]
    
    print(f"Building {title}...")
    c_coords = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
    output_body = bytearray()
    
    band = (FREQS >= 30.0) & (FREQS <= 19200.0)
    
    for ci, (m, q) in enumerate(c_coords):
        target_db = fn(FREQS, m, q)
        
        # Fit 6 biquad stages directly using FFI
        ffi_rows = trench_ffi.fit_corner_from_magnitude(
            list(zip(FREQS[band].tolist(), target_db[band].tolist())), SR)
        
        words = []
        for r in ffi_rows:
            words.extend(coeffs_to_words(*r))
            
        output_body.extend(struct.pack("<30H", *words))
        
    raw_candidate = bytes(output_body)
    
    # Check max crown gain and apply global SCALE trim if > 27 dB
    max_cr = -999.0
    for m_val in np.linspace(0, 1, 9):
        for q_val in np.linspace(0, 1, 9):
            pr = trench_ffi.packed_probe(raw_candidate, float(m_val), float(q_val))
            cr = np.max(cascade_mag_db(pr["biquad"]))
            if cr > max_cr: max_cr = cr
            
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
        
    cand_path = OUT_DIR / f"{slug}.body240"
    cand_path.write_bytes(bounded_candidate)
    (PLUGIN_BODIES_DIR / f"{slug}.body240").write_bytes(bounded_candidate)
    
    plot_path = OUT_DIR / f"{slug}_response.png"
    generate_clean_plot(bounded_candidate, title, plot_path)
    print(f"  Saved preset {slug}.body240 to plugin/presets/bodies/")

def main():
    for p in PRESETS:
        build_utility_preset(p)
    print("Done building utility presets!")

if __name__ == "__main__":
    main()
