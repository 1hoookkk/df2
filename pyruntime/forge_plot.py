"""Plot frequency responses for TRENCH bodies.

Usage:
    python pyruntime/forge_plot.py vault/body.json
    python pyruntime/forge_plot.py vault/body.json --compare datasets/p2k_skins/P2k_012.json
    python pyruntime/forge_plot.py vault/dir/ --top 10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pyruntime.body import Body
from pyruntime.constants import SR
from pyruntime.freq_response import cascade_response_db, freq_points

FREQS = freq_points()


def plot_body(body: Body, out_path: str | None = None, compare: Body | None = None):
    """Plot frequency response at 5 morph positions."""
    fig, ax = plt.subplots(figsize=(10, 5))

    for morph in [0.0, 0.25, 0.5, 0.75, 1.0]:
        enc = body.corners.interpolate(morph, 0.5)
        db = cascade_response_db(enc, FREQS, SR)
        alpha = 1.0 if morph in (0.0, 0.5, 1.0) else 0.4
        lw = 2.0 if morph == 0.5 else 1.0
        ax.semilogx(FREQS, db, label=f"M{int(morph*100)}",
                     alpha=alpha, linewidth=lw, color=plt.cm.viridis(morph))

    if compare:
        enc = compare.corners.interpolate(0.5, 0.5)
        db = cascade_response_db(enc, FREQS, SR)
        ax.semilogx(FREQS, db, label=f"REF: {compare.name}", color="red",
                     linestyle="--", alpha=0.8, linewidth=1.5)

    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude (dB)")
    ax.set_title(f"{body.name} — Morph Sweep @ Q50")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(20, SR / 2)
    plt.tight_layout()

    if out_path is None:
        out_path = f"{body.name}_response.png"
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"Saved: {out_path}")


def plot_directory(dir_path: Path, top_n: int = 10):
    """Plot top N bodies from a directory."""
    bodies = []
    for f in sorted(dir_path.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            body = Body.from_json(str(f))
            enc = body.corners.interpolate(0.5, 0.5)
            db = cascade_response_db(enc, FREQS, SR)
            peak = float(np.max(db))
            bodies.append((body, peak))
        except Exception:
            continue

    bodies.sort(key=lambda x: -x[1])
    top = bodies[:top_n]

    fig, ax = plt.subplots(figsize=(12, 6))
    for body, _ in top:
        enc = body.corners.interpolate(0.5, 0.5)
        db = cascade_response_db(enc, FREQS, SR)
        ax.semilogx(FREQS, db, label=body.name, alpha=0.7)

    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude (dB)")
    ax.set_title(f"Top {top_n} bodies from {dir_path.name}")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(20, SR / 2)
    plt.tight_layout()

    out = dir_path / "top_responses.png"
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"Saved: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Body JSON or directory")
    parser.add_argument("--compare", help="Reference body to overlay")
    parser.add_argument("--top", type=int, default=10, help="Top N for directory mode")
    args = parser.parse_args()

    p = Path(args.path)
    if p.is_dir():
        plot_directory(p, args.top)
    else:
        body = Body.from_json(str(p))
        compare = Body.from_json(args.compare) if args.compare else None
        plot_body(body, compare=compare)
