#!/usr/bin/env python3
"""Smallest real proof for the 6-pole lowpass workhorse.
Build ONE body via the typed compiler, certify (stable + crown<=27), decode the
morph sweep, and confirm the -3 dB cutoff walks log-evenly across morph (the
reason a log-morph LP 'sounds super good'). Writes to dev/tmp, NOT the roster."""
import math, sys
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\hooki\df2-workstation")
DF2 = Path(r"C:\Users\hooki\df2")
for p in [str(DF2 / "pyruntime"), str(DF2)]:
    sys.path.insert(0, p)
from pyruntime import trench_ffi

ENGINE_SR = 39062.5
EVAL = np.logspace(math.log10(20), math.log10(18000), 1000)
Z1 = np.exp(-2j * np.pi * EVAL / ENGINE_SR); Z2 = Z1 * Z1
PEAK, LOW_SHELF, NOTCH, LP, HP, BP, HIGH_SHELF = 0, 1, 2, 3, 4, 5, 6

def card(t, fcA, fcB, qlo, qhi, g, en=1.0):
    return [float(t), float(fcA), float(fcB), float(qlo), float(qhi), float(g), float(en)]

# 6-pole LP: 3 cascaded 2-pole LP rows, cutoff sweeps 100->10000 Hz across morph.
# Q adds a resonant peak at cutoff (concentrated on the last stage).
CARDS = [
    card(LP, 100, 10000, 0.707, 0.707, 0),
    card(LP, 100, 10000, 0.707, 1.5,   0),
    card(LP, 100, 10000, 0.707, 6.0,   0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
]

def resp(body, m, q):
    pr = trench_ffi.packed_probe(body, float(m), float(q))
    mag = np.ones_like(EVAL, dtype=complex)
    for b0, b1, b2, a1, a2 in pr["biquad"]:
        mag *= (b0 + b1*Z1 + b2*Z2) / (1.0 + a1*Z1 + a2*Z2)
    return 20*np.log10(np.abs(mag) + 1e-12), pr

def cutoff_hz(db):
    ref = db[np.argmin(np.abs(EVAL - 25))]  # passband ref near DC
    below = np.where(db <= ref - 3.0)[0]
    return EVAL[below[0]] if len(below) else EVAL[-1]

body = trench_ffi.compile_body_typed([v for c in CARDS for v in c])
assert len(body) == 240, len(body)

# certify
unstable = nonfinite = 0; maxr = 0.0; crown = -999.0
for m in np.linspace(0, 1, 25):
    for q in np.linspace(0, 1, 25):
        db, pr = resp(body, m, q)
        unstable += int(pr["unstable_mask"]); nonfinite += int(pr["nonfinite_mask"])
        maxr = max(maxr, float(pr["max_pole_radius"])); crown = max(crown, float(db.max()))
ok = unstable == 0 and nonfinite == 0 and maxr < 1.0 and crown <= 27.0
print(f"certify: {'PASS' if ok else 'FAIL'}  unstable={unstable} maxR={maxr:.4f} crown={crown:+.1f}dB")

# log-even cutoff walk at Q0
print("\nmorph -> -3dB cutoff (Q0):")
cuts = []
for m in np.linspace(0, 1, 9):
    db, _ = resp(body, m, 0.0)
    fc = cutoff_hz(db); cuts.append(fc)
    print(f"  m={m:.2f}  fc={fc:6.0f} Hz   log2(fc)={math.log2(fc):.2f}")
oct_steps = np.diff(np.log2(cuts))
print(f"\noctaves/step: mean={oct_steps.mean():.2f}  std={oct_steps.std():.3f}  "
      f"(low std = log-even = musical)")

# Q blooms a resonant peak at cutoff
db0, _ = resp(body, 0.5, 0.0); db1, _ = resp(body, 0.5, 1.0)
print(f"\nQ bloom at m=0.5: crown Q0={db0.max():+.1f}dB -> Q100={db1.max():+.1f}dB "
      f"(+{db1.max()-db0.max():.1f}dB resonant peak)")

out = ROOT / "dev" / "tmp" / "workhorse_proof"; out.mkdir(parents=True, exist_ok=True)
(out / "lp6.body240").write_bytes(body)
print(f"\nwrote {out/'lp6.body240'} (proof only, not rostered)")
