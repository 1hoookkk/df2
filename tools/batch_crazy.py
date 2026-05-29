#!/usr/bin/env python3
"""batch_crazy — generate a shit-tonne of random bodies, keep the craziest stable
ones, REPRODUCIBLY. The keeper_04 loop at scale.

Each candidate is fully determined by (base, index) via a per-candidate seed, so
every body written carries the seed that regenerates it byte-for-byte. Gate =
stability + no-pedestal (by construction in packed_random). Score "crazy" =
emergence (how far the M50/Q50 middle diverges from its four corners) x peak
complexity — the same metric that surfaced keeper_04.

  python -m tools.batch_crazy [N=4000] [base=1] [K=20]

Writes bodies/crazy/crazy_NN.cart.json (compiled-v1, packedWords authority) +
manifest.json (name, seed, crazy/emergence/peaks). Audition in the player; the
ones that slap, you keep — regenerate any from its seed.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.packed_interp import packed_bilinear, words_to_coeffs
from tools.packed_random import clean_response, count_peaks, rand_corner, words_db

FREQS = freq_points()
KEYS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
MQ = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
SEED_STRIDE = 1_000_003


def score(corners):
    cdbs = np.array([words_db(c) for c in corners])
    lo_n = max(4, cdbs.shape[1] // 12)
    for cdb in cdbs:  # gate EVERY corner (they're what you drag to)
        if not clean_response(cdb, lo_n):
            return None
    cw = {k: corners[i] for i, k in enumerate(["A", "B", "C", "D"])}
    mid = packed_bilinear(cw, 0.5, 0.5)
    mid_db = cascade_response_db([EncodedCoeffs(*c) for c in mid], FREQS)
    if not clean_response(mid_db, lo_n):
        return None
    emergence = float(np.mean(np.abs(mid_db - cdbs.mean(axis=0))))
    peaks = count_peaks(mid_db)
    return emergence * (1.0 + 0.4 * peaks), emergence, peaks


def cartridge(name, corners):
    kf = []
    for ci, cw in enumerate(corners):
        m, q = MQ[ci]
        stages = []
        for w in cw:
            c = words_to_coeffs(w)
            stages.append({"c0": c[0], "c1": c[1], "c2": c[2], "c3": c[3], "c4": c[4]})
        kf.append(
            {
                "label": KEYS[ci],
                "morph": m,
                "q": q,
                "boost": 1.0,
                "packedWords": [list(int(x) & 0xFFFF for x in w) for w in cw],
                "stages": stages,
            }
        )
    return {
        "format": "compiled-v1",
        "name": name,
        "provenance": "batch-crazy",
        "sampleRate": 39062.5,
        "authoring_sample_rate_hz": 39062.5,
        "stages": 6,
        "cornerOrder": KEYS,
        "keyframes": kf,
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    base = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    kept = []
    for i in range(n):
        seed = base * SEED_STRIDE + i
        random.seed(seed)
        corners = [rand_corner() for _ in range(4)]
        s = score(corners)
        if s:
            kept.append((s[0], seed, corners, s))
    kept.sort(key=lambda x: -x[0])

    out = ROOT / "bodies" / "crazy"
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for rank, (crazy, seed, corners, s) in enumerate(kept[:k], 1):
        name = f"crazy_{rank:02d}"
        (out / f"{name}.cart.json").write_text(json.dumps(cartridge(name, corners), indent=2))
        manifest.append(
            {
                "name": name,
                "seed": seed,
                "crazy": round(crazy, 1),
                "emergence_db": round(s[1], 1),
                "peaks": s[2],
            }
        )
        print(f"  {name}: crazy={crazy:6.1f}  emerge={s[1]:5.1f}dB  peaks={s[2]:2d}  seed={seed}")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"evaluated {n} (base {base}), kept {len(kept)} stable, wrote top {min(k, len(kept))} -> {out}")


if __name__ == "__main__":
    main()
