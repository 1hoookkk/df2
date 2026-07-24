#!/usr/bin/env python3
"""
Regenerate high-definition, crystal-clear response plots for all preset candidates:
- Single clean panel per candidate (NO ghost lines, NO dashed quotient overlays).
- Clear, distinct corner curves (HOME, AWAY, PUSH HOME, PUSH AWAY) in high-contrast vibrant colors.
- Smooth interior Morph trajectory steps (M25, M50, M75) showing motion clearly.
- Dark theme, clean grid lines, professional typography.
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
OUT_DIR.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

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

def generate_clean_plot(candidate_bytes, title, output_path):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=200)
    fig.patch.set_facecolor('#0f1117')
    ax.set_facecolor('#161822')
    
    # Interior Morph Trajectory (Q=0 at M=0.25, M=0.50, M=0.75)
    morph_steps = [(0.25, 'M25 Q0', '#00e5ff', 0.35, ':'),
                   (0.50, 'M50 Q0', '#00e5ff', 0.55, '--'),
                   (0.75, 'M75 Q0', '#00e5ff', 0.75, '-.')]
    
    for m_val, label, col, alpha, ls in morph_steps:
        pr = trench_ffi.packed_probe(candidate_bytes, m_val, 0.0)
        H = get_biquad_response(pr["biquad"], freqs)
        mag_db = 20 * np.log10(np.abs(H) + 1e-12)
        ax.plot(freqs, mag_db, color='#4dd0e1', linestyle=ls, linewidth=1.5, alpha=alpha, label=label)
    
    # 4 Main Authored Corner Poses
    corners = [
        (0.0, 0.0, 'HOME (M0 Q0)', '#00e5ff', 2.8),       # Cyan
        (1.0, 0.0, 'AWAY (M100 Q0)', '#76ff03', 2.8),     # Lime Green
        (0.0, 1.0, 'PUSH HOME (M0 Q100)', '#e040fb', 2.8), # Magenta
        (1.0, 1.0, 'PUSH AWAY (M100 Q100)', '#ff3d00', 2.8) # Red-Orange
    ]
    
    all_mags = []
    for m_val, q_val, label, col, lw in corners:
        pr = trench_ffi.packed_probe(candidate_bytes, m_val, q_val)
        H = get_biquad_response(pr["biquad"], freqs)
        mag_db = 20 * np.log10(np.abs(H) + 1e-12)
        all_mags.extend(mag_db)
        ax.plot(freqs, mag_db, color=col, linewidth=lw, label=label, zorder=5)
    
    # Calculate dB bounds cleanly
    all_mags = np.array(all_mags)
    min_db = max(-70.0, np.percentile(all_mags, 1) - 5.0)
    max_db = min(40.0, np.percentile(all_mags, 99) + 8.0)
    ax.set_ylim(min_db, max_db)
    
    ax.set_xscale("log")
    ax.set_xlim(20, 20000)
    
    # Custom Log Frequency Ticks
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
    
    # Clean Legend Outside Plot
    legend = ax.legend(frameon=True, facecolor='#1e2230', edgecolor='#37474f', fontsize=9.5, loc='upper right')
    for text in legend.get_texts():
        text.set_color('#eceff1')
        
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print(f"Generated clean plot: {output_path.name}")

candidates = [
    ("ukulele_ortf__talking_hedz", "Talking Hedz + Ukulele ORTF (Complete Cascade Response)"),
    ("steelpan_cymbal__meaty_gizmo", "Meaty Gizmo + Steelpan Cymbal (Complete Cascade Response)"),
    ("glockenspiel_minecave__tb_or_not_tb", "TB or Not TB + Glockenspiel Mine Cave (Complete Cascade Response)"),
    ("kalimba_tunnel__megasweepz", "MegaSweepz + Kalimba Tunnel (Complete Cascade Response)"),
    ("ukulele_ortf__ear_bender", "Ear Bender + Ukulele ORTF (Complete Cascade Response)"),
    ("hrtf_registered__deep_bouche", "Deep Bouche + HRTF Spatial (Complete Cascade Response)")
]

print("=== Regenerating All Plots with Clean Method ===")
for slug, title in candidates:
    body_file = OUT_DIR / f"{slug}.body240"
    if body_file.exists():
        plot_file = OUT_DIR / f"{slug}_response.png"
        generate_clean_plot(body_file.read_bytes(), title, plot_file)
    else:
        print(f"File not found: {body_file}")
