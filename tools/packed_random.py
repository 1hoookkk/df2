"""packed_random — random packed bodies + the one stability / no-pedestal gate.

Single owner (see memory `packed-math-triplicated`): the midpoint search and the
corner bench both import these helpers, so a body is judged the SAME way on both
sides — no drift between "the search liked it" and "the bench renders it."

A body here is only ever raw packed u16 words. No stages, no roles, no freq/Q.
The one rule baked in: w0 is pinned near zero so the DC numerator vanishes and a
low-end pedestal is impossible by construction; everything else is free.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402
from pyruntime.packed_interp import packed_bilinear, words_to_coeffs  # noqa: E402

FREQS = freq_points()
CORNER_KEYS = ("A", "B", "C", "D")  # M0_Q0, M100_Q0, M0_Q100, M100_Q100


def stable(c) -> bool:
    """Stable 2nd-order: poles inside the unit circle, not silent."""
    c0, c1, c2, c3, c4 = c
    a1, a2 = c2 - 2.0, 1.0 - c3
    return abs(a2) < 0.9995 and abs(a1) < 1.0 + a2 and abs(c4) > 1e-3


def stage_stable(word) -> bool:
    """Stability test straight from one packed 5-word stage."""
    return stable(words_to_coeffs(tuple(word)))


def stage_radius_sq(c) -> float:
    """|a2| — the pole radius squared for a complex-conjugate pair."""
    return abs(1.0 - c[3])


def rand_word_stage(max_r: float = 0.97):
    """A random STABLE stage in raw packed words — w0 pinned near 0 so the DC
    numerator (c0-c1 = 4*decode(w0)) vanishes (no low-end pedestal, by math),
    and the pole radius capped at `max_r` so the morph PATH between random
    corners stays stable (no blow-ups mid-sweep). Pole frequency, zero, and the
    rest of the shape stay fully random — no roles, no design."""
    r2 = max_r * max_r
    for _ in range(300):
        w = (random.randint(0, 0x1000),) + tuple(random.randint(0, 0xFFFF) for _ in range(4))
        c = words_to_coeffs(w)
        if stable(c) and stage_radius_sq(c) <= r2:
            return w
    return (0, 0, 0, 0, 0)


def rand_corner(max_r: float = 0.97):
    return [rand_word_stage(max_r) for _ in range(6)]


def words_db(corner_words):
    enc = [EncodedCoeffs(*words_to_coeffs(w)) for w in corner_words]
    return cascade_response_db(enc, FREQS)


def count_peaks(db, prom=6.0):
    n = 0
    for i in range(2, len(db) - 2):
        if db[i] > db[i - 1] and db[i] >= db[i + 1]:
            lo = min(db[max(0, i - 12):i].min(), db[i:i + 12].min())
            if db[i] - lo > prom:
                n += 1
    return n


def clean_response(db, lo_n) -> bool:
    """Normalization-invariant gate: finite, has real spectral shape, and the
    low end is rolled off RELATIVE to the peak (no pedestal). Absolute level is
    the runtime's job (AGC + makeup), so it is deliberately NOT judged here —
    judging it was rejecting good low-gain bodies (even keepers)."""
    if not np.isfinite(db).all():
        return False
    pk = float(db.max())
    if pk - float(np.median(db)) < 3.0:        # dead-flat / featureless
        return False
    if db[:lo_n].max() > pk - 12.0:            # low end too hot vs peak = pedestal
        return False
    return True


def evaluate_emergence(corners):
    """Gate every corner AND the M50/Q50 middle for clean/no-pedestal, then score
    how far the emergent middle diverges from the corner average (the moat).
    Returns {'emergence','peaks'} or None if any corner/middle is dirty."""
    corner_dbs = np.array([words_db(c) for c in corners])
    lo_n = max(4, corner_dbs.shape[1] // 12)
    for cdb in corner_dbs:                      # gate EVERY corner, not just the middle
        if not clean_response(cdb, lo_n):
            return None
    cw = {CORNER_KEYS[i]: corners[i] for i in range(4)}
    mid = packed_bilinear(cw, 0.5, 0.5)
    mid_db = cascade_response_db([EncodedCoeffs(*c) for c in mid], FREQS)
    if not clean_response(mid_db, lo_n):
        return None
    mean_db = corner_dbs.mean(axis=0)
    return {
        "emergence": float(np.mean(np.abs(mid_db - mean_db))),
        "peaks": count_peaks(mid_db),
    }


def random_body(seed=None, attempts=6000, max_r: float = 0.97):
    """Roll random packed corners until one clears the gate (4 corners + the
    M50/Q50 middle all clean, no pedestal). Radius-capped so the morph path
    stays stable. Returns (corners_in_label_order, emergence_db). Falls back to
    the last roll if nothing clears in `attempts`."""
    if seed is not None:
        random.seed(seed)
    corners = [rand_corner(max_r) for _ in range(4)]
    for _ in range(attempts):
        corners = [rand_corner(max_r) for _ in range(4)]
        r = evaluate_emergence(corners)
        if r:
            return corners, r["emergence"]
    return corners, 0.0
