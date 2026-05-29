"""Midpoint search — RNG the VERBATIM PACKED WORDS, hunt the craziest middle.

No stage design. No freq/radius. We generate random u16 minifloat words (the
native 240-byte format), gate only for stability + no-pedestal, render the
M50/Q50 blend, and score how far the middle diverges from its four corners
(emergence). The unique tones live in the middle; the words are the search
space. Generate -> score the middle -> you pick.

    python tools/midpoint_search.py [N]      # default 1500 candidates
"""
from __future__ import annotations
import sys, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

from tools.corner_words import build_toml_words
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from pyruntime.packed_interp import packed_bilinear
# Single owner for the random packed body + the stability / no-pedestal gate.
# The corner bench imports the SAME helpers, so the search and the bench judge a
# body identically — no re-implementation drift (memory `packed-math-triplicated`).
from tools.packed_random import (  # noqa: E402
    stable, rand_word_stage, rand_corner, words_db, count_peaks,
    clean_response as _clean, FREQS,
)

LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
KEYS = ["A", "B", "C", "D"]


def evaluate(corners):
    corner_dbs = np.array([words_db(c) for c in corners])
    lo_n = max(4, corner_dbs.shape[1] // 12)
    # GATE EVERY CORNER (not just the midpoint) — the corners are what you drag to.
    for cdb in corner_dbs:
        if not _clean(cdb, lo_n):
            return None
    cw = {KEYS[i]: corners[i] for i in range(4)}
    mid = packed_bilinear(cw, 0.5, 0.5)
    mid_db = cascade_response_db([EncodedCoeffs(*c) for c in mid], FREQS)
    if not _clean(mid_db, lo_n):
        return None
    mean_db = corner_dbs.mean(axis=0)
    emergence = float(np.mean(np.abs(mid_db - mean_db)))
    peaks = count_peaks(mid_db)
    return emergence * (1.0 + 0.4 * peaks), emergence, peaks, mid_db, corner_dbs


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    random.seed()
    best = []
    for _ in range(N):
        corners = [rand_corner() for _ in range(4)]
        r = evaluate(corners)
        if r:
            best.append((r[0], corners, r))
    best.sort(key=lambda x: -x[0])
    top = best[:6]
    print(f"evaluated {N}, kept {len(best)}; top (verbatim-word bodies):")

    out = ROOT / "dev" / "tmp" / "factory"
    plt.rcParams["figure.facecolor"] = "#0b0f0e"
    fig, axs = plt.subplots(2, 3, figsize=(17, 8.5))
    col = ["#2ec4ff", "#ffd23e", "#ff6b6b", "#9b8cff"]
    for idx, (ax, (crazy, corners, r)) in enumerate(zip(axs.flat, top), 1):
        _, emergence, peaks, mid_db, corner_dbs = r
        name = f"search_{idx:02d}"
        (out / f"{name}.packed.toml").write_text(
            build_toml_words(name, dict(zip(LABELS, corners))))
        for i, cdb in enumerate(corner_dbs):
            ax.semilogx(FREQS, np.clip(cdb, -54, 18), color=col[i], lw=1, alpha=.25)
        ax.semilogx(FREQS, np.clip(mid_db, -54, 18), color="#f6f8ff", lw=2.4)
        ax.axhline(0, color="#36c828", lw=1, alpha=.7)
        ax.set_xlim(120, 12000); ax.set_ylim(-54, 18)
        ax.set_facecolor("#0b0f0e"); ax.grid(True, which="both", alpha=.12)
        ax.set_title(f"{name}  crazy={crazy:.1f}  emerge={emergence:.1f}dB  peaks={peaks}",
                     color="#eaeaea", fontsize=10)
        ax.tick_params(colors="#888", labelsize=7)
        for s in ax.spines.values(): s.set_color("#333")
        print(f"  {name}: crazy={crazy:.1f}  emergence={emergence:.1f} dB  peaks={peaks}")
    fig.suptitle("Midpoint search (verbatim packed words) — faint = 4 random corners, WHITE = emergent middle",
                 color="#eaeaea", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out / "midpoint_search.png", dpi=110)
    print(f"wrote {out / 'midpoint_search.png'} + search_01..06.packed.toml")


if __name__ == "__main__":
    main()
