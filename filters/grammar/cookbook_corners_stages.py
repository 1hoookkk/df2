#!/usr/bin/env python3
"""Cookbook VOWL aa->iy, laid open: the 4 packed corners x 6 stages. Each panel
= one corner; the 6 thin curves are the stages, the bold white curve is their
PRODUCT (the multiplied serial cascade = that corner's filter response)."""
import os, sys
import numpy as np
ROOT = r"C:\Users\hooki\df2"
sys.path.insert(0, ROOT)
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from tools import morph_designer as md

FREQS = md.FREQS
SR = md.SR
body = md.compile_patch(md.vowel_patch("aa", "iy"))

# CLAUDE.md corner map: C0=LOW.Q0 C1=HIGH.Q0 C2=LOW.Q100 C3=HIGH.Q100
CORNERS = [("C0  LOW · Q0", 0.0, 0.0), ("C1  HIGH · Q0", 1.0, 0.0),
           ("C2  LOW · Q100", 0.0, 1.0), ("C3  HIGH · Q100", 1.0, 1.0)]
STAGE_LABELS = ["S1 glottal shelf", "S2 F1", "S3 F2", "S4 F3", "S5 canyon", "S6 LP roll-off"]
STAGE_COL = ["#e6a13b", "#ee6a3c", "#e0d24a", "#56ed70", "#2fc8cc", "#8b8ff0"]

def stage_db(row):
    return cascade_response_db([EncodedCoeffs(*row)], FREQS, SR)

fig, axs = plt.subplots(2, 2, figsize=(15, 8.6), facecolor="#0a0c0b")
for ci, (name, m, q) in enumerate(CORNERS):
    a = axs[ci // 2][ci % 2]; a.set_facecolor("#111318")
    rows = trench_ffi.packed_interpolate(body, float(m), float(q))
    for k, row in enumerate(rows):
        a.semilogx(FREQS, stage_db(row), lw=1.1, color=STAGE_COL[k], alpha=0.8,
                   label=STAGE_LABELS[k])
    product = cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, SR)
    a.semilogx(FREQS, product, lw=2.6, color="#ffffff", label="PRODUCT (cascade)")
    a.set_xlim(60, 18000); a.set_ylim(-48, 30)
    a.grid(True, which="both", alpha=0.16, color="#3a4048")
    a.set_title(name, color="#cfe9df", fontsize=11)
    a.tick_params(colors="#8a968f", labelsize=7)
    a.set_ylabel("|H| dB", color="#8a968f", fontsize=8)
    a.set_xlabel("Hz", color="#8a968f", fontsize=8)
    if ci == 0:
        a.legend(fontsize=7.5, facecolor="#181b20", edgecolor="#2a2e35",
                 labelcolor="#cfe9df", ncol=2, loc="upper left")
fig.suptitle("COOKBOOK VOWL aa→iy  ·  4 corners × 6 stages  ·  thin = stage, white = multiplied cascade",
             color="#cfe9df", fontsize=12)
fig.tight_layout(rect=(0, 0, 1, 0.96))
png = r"C:\WINDOWS\TEMP\claude\C--Users-hooki-df2\48d7b98f-5ea2-4a58-9173-1fc2bd217790\scratchpad\cookbook_corners_stages.png"
fig.savefig(png, dpi=120, facecolor="#0a0c0b"); plt.close(fig)
print("wrote", png)
