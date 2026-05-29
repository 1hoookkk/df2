#!/usr/bin/env python3
"""plot_crazy — visualize batch_crazy output, and prove whether ZEROS (notches)
are present. Each body: 4 corner responses (faint) + the M50/Q50 emergent middle
(white), with notches marked (red ▽) and a per-body zero-stage count in the title.
A stage carries a zero when its numerator is non-trivial (|c0-2|>eps or |c1-1|>eps).

  python -m tools.plot_crazy
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.packed_interp import packed_bilinear, words_to_coeffs

F = freq_points()
COLS = ["#2ec4ff", "#ffd23e", "#ff6b6b", "#9b8cff"]


def stage_has_zero(c) -> bool:
    return abs(c[0] - 2.0) > 0.05 or abs(c[1] - 1.0) > 0.05


def notches(db):
    out = []
    for j in range(4, len(db) - 4):
        lo = max(0, j - 14)
        if db[j] == min(db[j - 4 : j + 5]) and (max(db[lo : j + 14]) - db[j]) > 10.0:
            out.append(j)
    return out


def main():
    files = sorted(glob.glob(str(ROOT / "bodies" / "crazy" / "crazy_*.cart.json")))
    if not files:
        print("no bodies/crazy/crazy_*.cart.json — run tools.batch_crazy first")
        return
    n = len(files)
    cols_n = 4
    rows_n = (n + cols_n - 1) // cols_n
    fig, axs = plt.subplots(rows_n, cols_n, figsize=(4.2 * cols_n, 4.2 * rows_n))
    fig.patch.set_facecolor("#0b0f0e")
    total_zero_stages = 0
    for ax, fp in zip(axs.flat, files):
        d = json.loads(Path(fp).read_text())
        cw = {
            k: [tuple(w) for w in d["keyframes"][i]["packedWords"]]
            for i, k in enumerate(["A", "B", "C", "D"])
        }
        nz = 0
        for kf in d["keyframes"]:
            for w in kf["packedWords"]:
                if stage_has_zero(words_to_coeffs(tuple(w))):
                    nz += 1
        total_zero_stages += nz
        for i, kf in enumerate(d["keyframes"]):
            enc = [EncodedCoeffs(*words_to_coeffs(tuple(w))) for w in kf["packedWords"]]
            ax.semilogx(F, np.clip(cascade_response_db(enc, F), -60, 24), color=COLS[i], lw=1, alpha=0.30)
        mid = packed_bilinear(cw, 0.5, 0.5)
        mdb = cascade_response_db([EncodedCoeffs(*c) for c in mid], F)
        ax.semilogx(F, np.clip(mdb, -60, 24), color="#f6f8ff", lw=2.2)
        for j in notches(mdb):
            ax.plot(F[j], float(np.clip(mdb[j], -60, 24)), "v", color="#ff3b3b", ms=6)
        name = os.path.basename(fp).replace(".cart.json", "")
        ax.set_title(f"{name}  zero-stages={nz}/24  notches={len(notches(mdb))}", color="#eaeaea", fontsize=9)
        ax.set_xlim(80, 16000)
        ax.set_ylim(-60, 24)
        ax.set_box_aspect(1)  # square cells
        ax.set_facecolor("#0b0f0e")
        ax.grid(True, which="both", alpha=0.12)
        ax.axhline(0, color="#36c828", lw=0.8, alpha=0.6)
        ax.tick_params(colors="#888", labelsize=6)
        for s in ax.spines.values():
            s.set_color("#333")
    for ax in axs.flat[n:]:
        ax.set_visible(False)
    fig.suptitle(
        f"batch_crazy — faint=4 corners, WHITE=emergent middle, RED ▽=notch(zero).  "
        f"TOTAL zero-stages across all bodies = {total_zero_stages}",
        color="#eaeaea",
        fontsize=13,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    outp = ROOT / "bodies" / "crazy" / "crazy_plot.png"
    fig.savefig(outp, dpi=110, facecolor="#0b0f0e")
    print(f"TOTAL zero-stages across {n} bodies = {total_zero_stages} (out of {n*24})")
    print(f"wrote {outp}")


if __name__ == "__main__":
    main()
