#!/usr/bin/env python3
"""batch_complex — generate ACTUALLY complex bodies, not thin single-resonance junk.

Random words gave one dominant pole → the normalizer crushed everything else → a
dog whistle over silence. Fix: randomize the proven `hedz_body` STRUCTURE instead
(4 anchor poles at comparable radii + 2 crossing formants that swap across Morph +
Q tightens all radii). Comparable radii = no single pole hogs the normalizer =
the whole body stays loud and rich. Gated against "thin" (band spread cap) and
scored for balance + peak count + crosser movement. Reproducible per seed.

  python -m tools.batch_complex [N=3000] [base=1] [K=16]
Writes bodies/crazy/crazy_NN.cart.json (overwrites the thin batch) + manifest.json.
"""
from __future__ import annotations

import json
import random
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.packed_interp import packed_bilinear, words_to_coeffs
from pyruntime.packed_interp import coeffs_to_words
from tools.corner_words import peak_eq_words
from tools.packed_random import clean_response, count_peaks

PASS_W = coeffs_to_words(2.0, 1.0, 2.0, 1.0, 1.0)  # passthrough stage words

F = freq_points()
LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
MQ = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
BANDS = [(20, 200), (200, 1200), (1200, 5500), (5500, 16000)]
SEED_STRIDE = 1_000_003


def _corner_eq(freqs, gains, bws):
    w = [peak_eq_words(f, max(bw, 30.0), g) for f, g, bw in zip(freqs, gains, bws)]
    while len(w) < 6:
        w.append(PASS_W)
    return w[:6]


MOTIONS = ["translate", "glide", "comb_fixed", "anchored"]


def rand_body(rng):
    # Bumps + notches on a FLAT baseline (peaking EQ) — balanced by construction.
    # The MOTION strategy sets how the 4 corners relate (the trajectory), authored
    # into corner placement — the runtime stays the dumb bilinear lerp.
    n = rng.randint(4, 6)
    freqs = sorted(float(np.exp(rng.uniform(np.log(60), np.log(11000)))) for _ in range(n))
    gains = [rng.uniform(-16.0, 16.0) for _ in range(n)]  # mix of peaks and notches
    bws = [f / rng.uniform(0.7, 6.0) for f in freqs]  # Q per bump
    qhot = rng.uniform(1.4, 2.2)  # Q amplifies bumps/notches (the violence axis)
    motion = rng.choice(MOTIONS)

    # mult[i] = where bump i lands at Morph=100 (× its M0 freq); anchor[i] = frozen.
    if motion == "translate":
        s = rng.uniform(1.2, 1.7)
        mult = [s] * n
        anchor = [False] * n
    elif motion == "glide":  # independent destinations -> some rise, some fall, cross
        mult = [rng.uniform(0.6, 1.9) for _ in range(n)]
        anchor = [False] * n
    elif motion == "comb_fixed":  # notches locked, peaks travel
        s = rng.uniform(1.25, 1.7)
        mult = [1.0 if gains[i] < 0 else s for i in range(n)]
        anchor = [False] * n
    else:  # anchored — the low bump(s) hold (sub stays put), the top morphs
        s = rng.uniform(1.3, 1.8)
        lock = max(1, n // 3)
        mult = [1.0 if i < lock else s for i in range(n)]
        anchor = [i < lock for i in range(n)]

    def corner(morph, q):
        fs = [freqs[i] * (1.0 + (mult[i] - 1.0) * morph) for i in range(n)]
        gs = [gains[i] if anchor[i] else gains[i] * (1.0 + (qhot - 1.0) * q) for i in range(n)]
        bs = [bws[i] / (1.0 + 0.6 * q) for i in range(n)]
        return _corner_eq(fs, gs, bs)

    return {lab: corner(m, q) for lab, (m, q) in zip(LABELS, MQ)}, motion


def band_levels(db):
    return [float(np.mean(db[(F >= lo) & (F < hi)])) for lo, hi in BANDS]


def score(wb):
    cdbs = []
    for lab in LABELS:
        enc = [EncodedCoeffs(*words_to_coeffs(w)) for w in wb[lab]]
        cdbs.append(cascade_response_db(enc, F))
    cdbs = np.array(cdbs)
    lo_n = max(4, cdbs.shape[1] // 12)
    for cdb in cdbs:
        if not clean_response(cdb, lo_n):
            return None
    cw = {k: wb[LABELS[i]] for i, k in enumerate(["A", "B", "C", "D"])}
    mid = packed_bilinear(cw, 0.5, 0.5)
    mdb = cascade_response_db([EncodedCoeffs(*c) for c in mid], F)
    if not clean_response(mdb, lo_n):
        return None
    bl = band_levels(mdb)
    spread = max(bl) - min(bl)
    if spread > 42.0:  # thin = one band loud, the rest buried — REJECT
        return None
    peaks = count_peaks(mdb)
    if peaks < 3:  # not complex enough
        return None
    # crosser movement: how far the centroid shifts M0 -> M100 (the "talking")
    def centroid(db):
        w = 10.0 ** (db / 20.0)
        return float(np.sum(F * w) / max(np.sum(w), 1e-9))
    move = abs(centroid(cdbs[1]) - centroid(cdbs[0]))
    crazy = peaks * 2.0 + (42.0 - spread) * 0.15 + move / 400.0
    return crazy, peaks, round(spread, 1), round(move, 0)


def cartridge(name, wb):
    kf = []
    for ci, lab in enumerate(LABELS):
        m, q = MQ[ci]
        cwds = wb[lab]
        stages = []
        for w in cwds:
            c = words_to_coeffs(w)
            stages.append({"c0": c[0], "c1": c[1], "c2": c[2], "c3": c[3], "c4": c[4]})
        kf.append(
            {
                "label": lab,
                "morph": m,
                "q": q,
                "boost": 1.0,
                "packedWords": [list(int(x) & 0xFFFF for x in w) for w in cwds],
                "stages": stages,
            }
        )
    return {
        "format": "compiled-v1",
        "name": name,
        "provenance": "batch-complex (hedz-structured)",
        "sampleRate": 39062.5,
        "authoring_sample_rate_hz": 39062.5,
        "stages": 6,
        "cornerOrder": LABELS,
        "keyframes": kf,
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    base = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    kept = []
    for i in range(n):
        seed = base * SEED_STRIDE + i
        wb, motion = rand_body(random.Random(seed))
        s = score(wb)
        if s:
            kept.append((s[0], seed, motion, s))
    kept.sort(key=lambda x: -x[0])

    out = ROOT / "bodies" / "crazy"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("crazy_*.cart.json"):
        old.unlink()
    manifest = []
    for rank, (crazy, seed, motion, s) in enumerate(kept[:k], 1):
        name = f"crazy_{rank:02d}"
        wb, _ = rand_body(random.Random(seed))  # regenerate from seed (reproducible)
        (out / f"{name}.cart.json").write_text(json.dumps(cartridge(name, wb), indent=2))
        manifest.append({"name": name, "seed": seed, "motion": motion, "crazy": round(crazy, 1), "peaks": s[1], "spread_db": s[2], "move_hz": s[3]})
        print(f"  {name}: {motion:11s} crazy={crazy:5.1f} peaks={s[1]:2d} spread={s[2]:5.1f}dB move={s[3]:5.0f}Hz seed={seed}")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"evaluated {n} (base {base}), kept {len(kept)} balanced+complex, wrote top {min(k, len(kept))} -> {out}")


if __name__ == "__main__":
    main()
