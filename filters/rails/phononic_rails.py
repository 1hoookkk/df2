#!/usr/bin/env python3
"""Phononic well -> metamaterial absorption rails (evidence surfaces).

CITE-OR-REFUSE provenance
-------------------------
Dataset: Zhang et al. 2023, "Learning to inversely design acoustic
metamaterials for enhanced performance", Acta Mech. Sin. 39:722426
(data/phononic/learning_inverse_design_acoustic_metamaterials/data/
data_20000_S-A_range1_smaller0-82.csv). 20,000 samples: 10 cavity-geometry
parameters (mm) -> sound-absorption spectrum alpha(f), 100-10000 Hz.
Band is ALREADY audio — no transpose.

Evidence reading: an absorption peak is energy the structure eats = a NOTCH
(zero rail) at that frequency; depth from alpha (residual = 10*log10(1-a)),
width from the peak's FWHM -> zero radius. A morph = a WALK THROUGH GEOMETRY
SPACE: we chain nearest neighbours from structure A to structure B and track
the peaks along the path — the notch trajectory is measured, not authored.

Output: out/phononic_rails/{phononic_rails.json, contact_sheet.png, plots/}
Run:    python tools/phononic_rails.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks

ROOT = Path(__file__).resolve().parent.parent
CSV = (ROOT / "data/phononic/learning_inverse_design_acoustic_metamaterials"
       / "data/data_20000_S-A_range1_smaller0-82.csv")
OUT = ROOT / "out" / "phononic_rails"
SR = 39062.5
F_LO, F_HI = 100.0, 10000.0
N_WAYPOINTS = 9

CITE = ("Zhang et al. 2023 Acta Mech. Sin. 39:722426 inverse-design dataset, "
        "data_20000_S-A_range1_smaller0-82.csv (alpha spectra 100-10000 Hz)")


def load():
    d = np.genfromtxt(CSV, delimiter=",", skip_header=1)
    S, A = d[:, :10], d[:, 10:]
    F = np.linspace(F_LO, F_HI, A.shape[1])
    return S, A, F


def peaks_of(a: np.ndarray, F: np.ndarray):
    """Absorption peaks -> notch rails: (hz, alpha, fwhm_hz)."""
    idx, props = find_peaks(a, height=0.4, prominence=0.10, width=1)
    out = []
    df = F[1] - F[0]
    for k, i in enumerate(idx):
        out.append(dict(hz=float(F[i]), alpha=float(a[i]),
                        fwhm_hz=float(props["widths"][k] * df)))
    return out


def zero_radius(hz: float, fwhm_hz: float) -> float:
    """Textbook bandwidth->radius at the engine rate (same law as poles)."""
    return float(np.clip(math.exp(-math.pi * fwhm_hz / SR), 0.5, 0.9995))


def geometry_chain(S: np.ndarray, a_idx: int, b_idx: int, n: int):
    """Greedy nearest-neighbour walk A->B in normalized geometry space:
    every waypoint is a REAL measured structure (no interpolation)."""
    lo, hi = S.min(0), S.max(0)
    Z = (S - lo) / np.maximum(hi - lo, 1e-9)
    path = [a_idx]
    current = a_idx
    for step in range(1, n - 1):
        t = step / (n - 1)
        target = Z[a_idx] * (1 - t) + Z[b_idx] * t
        d = np.linalg.norm(Z - target, axis=1)
        d[path] = 1e9
        nxt = int(np.argmin(d))
        path.append(nxt)
        current = nxt
    path.append(b_idx)
    return path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "plots").mkdir(exist_ok=True)
    S, A, F = load()

    # endpoints: deepest LOW single notch  ->  strongest SPLIT (2-peak) structure
    n_pk = np.zeros(len(A), int)
    score2 = np.zeros(len(A))
    low_score = np.zeros(len(A))
    for i, a in enumerate(A):
        pk = peaks_of(a, F)
        n_pk[i] = len(pk)
        if len(pk) >= 2:
            score2[i] = sum(p["alpha"] for p in pk)
        if len(pk) == 1 and pk[0]["hz"] < 2000:
            low_score[i] = pk[0]["alpha"] / pk[0]["fwhm_hz"]  # deep AND narrow
    a_idx = int(np.argmax(low_score))
    b_idx = int(np.argmax(score2))

    path = geometry_chain(S, a_idx, b_idx, N_WAYPOINTS)
    rails = []
    for w, i in enumerate(path):
        pk = peaks_of(A[i], F)
        rails.append(dict(
            waypoint=w, sample_index=int(i),
            geometry_mm=[round(float(v), 2) for v in S[i]],
            notches=[dict(hz=round(p["hz"], 1), alpha=round(p["alpha"], 4),
                          fwhm_hz=round(p["fwhm_hz"], 1),
                          residual_db=round(10 * math.log10(max(1e-4, 1 - p["alpha"])), 1),
                          zero_r=round(zero_radius(p["hz"], p["fwhm_hz"]), 4))
                     for p in pk],
        ))

    doc = dict(well="phononic", source=CITE, sr_target=SR,
               band_hz=[F_LO, F_HI], n_samples=len(A),
               trajectory="geometry-chain walk, every waypoint a real measured structure",
               endpoints=dict(low=dict(sample=int(a_idx), why="deepest narrow single notch <2kHz"),
                              high=dict(sample=int(b_idx), why="strongest two-peak mode split")),
               waypoints=rails)
    (OUT / "phononic_rails.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")

    # contact sheet: the walk, spectra in dB residual (his format: dB vs log-Hz)
    fig, axes = plt.subplots(3, 3, figsize=(15, 9), sharex=True, sharey=True)
    for ax, r in zip(axes.flat, rails):
        a = A[r["sample_index"]]
        ax.semilogx(F, 10 * np.log10(np.maximum(1e-4, 1 - a)), lw=1.6, color="#1f77b4")
        for nch in r["notches"]:
            ax.axvline(nch["hz"], color="#d62728", lw=0.8, alpha=0.6)
        ax.set_title(f"waypoint {r['waypoint']} (#{r['sample_index']}) "
                     f"{len(r['notches'])} notch", fontsize=9)
        ax.grid(True, which="both", lw=0.3, alpha=0.5)
        ax.set_ylim(-22, 2)
    fig.suptitle("PHONONIC WELL — measured notch trajectory (residual dB = 10log10(1-alpha))")
    fig.tight_layout()
    fig.savefig(OUT / "contact_sheet.png", dpi=110)
    plt.close(fig)

    for r in rails:
        print(f"wp{r['waypoint']} #{r['sample_index']}: " +
              " | ".join(f"{n['hz']:.0f}Hz a={n['alpha']:.2f} r={n['zero_r']}" for n in r["notches"]))
    print(OUT / "phononic_rails.json")
    print(OUT / "contact_sheet.png")


if __name__ == "__main__":
    main()
