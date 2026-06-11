#!/usr/bin/env python3
"""null_sweep — the standing proof that there is ONE forward encoder.

THE ONE ENCODER = pyruntime.trench_ffi.compile_body (== forge-web WASM GUI, byte-exact;
exposed in Python via src.compiler.encode.body_from_params / body_from_kernels).

This tool proves three things and fails (exit 1) if any breaks:

  A. DIVERGENCE — the legacy `coeffs_to_words` path is a genuinely different encoder.
     We compile the SAME params both ways and measure byte-diff + dB divergence on the
     morph x q grid. (Documents WHY unification matters; expected to be large.)

  B. DETERMINISM — compile_body is byte-deterministic, so "null == 0" is a meaningful
     gate (same params -> same 240 bytes every time).

  C. BOUNDARY (the regression guard) — no ACTIVE body-producing path may write a
     .body240 via the rogue path. Exploratory tools that still do are listed in
     QUARANTINE below (the one-line note lives here, in one place, not scattered).
     Any *new* file that writes rogue bodies and isn't quarantined -> FAIL.

Run:  python -m tools.null_sweep
"""
from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.compiler import encode
from src.utils.body240 import raw_from_words
from tools import target_browser as tb

# Exploratory tools that still write .body240 through the rogue (non-normalized)
# coeffs_to_words path. NOT engine-faithful — diverges up to ~80 dB from what the
# shipped engine plays. Quarantined, not shipping. To promote one, route its body
# writes through src.compiler.encode.body_from_kernels / body_from_params and drop
# it from this list. (Decode/inspect-only uses of coeffs_to_words are fine and are
# NOT listed here — only paths that WRITE bodies.)
QUARANTINE = {
    "tools/author_bass_sharpener_surgical.py",
    "tools/forge_method.py",
    "tools/forge_gen_server.py",
    "tools/forge_compiler.py",
    "tools/three_layer_acoustic_forge.py",
    "tools/test_zero_dominance.py",
    "tools/verified_body_forge.py",
    "tools/real_source_surface_rack.py",
    "tools/fit_two_audio_arma.py",
    "tools/experiment_20_biquad_terrain.py",
    "tools/physical_mountains.py",
    "tools/reference_brief.py",
    "tools/voxbench.py",
    "tools/metal_rack.py",
    "tools/vocal_rack2.py",
    "tools/vocal_rack2_low_to_high.py",
    # target_browser defines body_bytes() (the rogue packer helper) and a few legacy
    # CLI writers; the ACTIVE callers (sweep_roster) no longer use it for body writes.
    "tools/target_browser.py",
}

# Active body-producing paths: must route through compile_body. The guard fails if
# any of these calls the rogue write helpers.
ACTIVE = {
    "tools/sweep_roster.py",
    "src/compiler/encode.py",  # body_from_params/kernels ARE compile_body; words_from_params is legacy/inspection
}

# A rogue body WRITE = compiles coeffs via the non-normalized coeffs_to_words path
# AND emits a .body240. (A player that re-packs already-stored words is faithful and
# does NOT import coeffs_to_words, so it is not caught.)
_ROGUE_ENCODE = re.compile(r"\bcoeffs_to_words\b")
# the .body240 file extension in a string literal — NOT the dotted module path
# `src.utils.body240` (which has no quote after it).
_BODY_WRITE = re.compile(r"\.body240[\"']")


def _rand_P(rng):
    P = []
    for _ in range(4):
        corner = []
        for _ in range(6):
            corner.append((rng.uniform(0.05, 3.0), rng.uniform(0.5, 0.999),
                           rng.uniform(0.05, 3.0), rng.uniform(0.0, 0.99),
                           rng.uniform(0.2, 3.0)))
        P.append(corner)
    return P


def prove_divergence(n=25, seed=42):
    rng = random.Random(seed)
    bytediffs, maxdb = [], []
    for _ in range(n):
        P = _rand_P(rng)
        bytediffs.append(encode.null_vs_engine(P))
        be = encode.body_from_params(P)               # compile_body (engine)
        br = raw_from_words(encode.words_from_params(P))  # rogue
        md = 0.0
        for m in np.linspace(0, 1, 6):
            for q in np.linspace(0, 1, 6):
                re_ = tb.shipped_response(be, float(m), float(q))
                rr_ = tb.shipped_response(br, float(m), float(q))
                md = max(md, float(np.nanmax(np.abs(re_ - rr_))))
        maxdb.append(md)
    print(f"[A] DIVERGENCE  (engine compile_body  vs  rogue coeffs_to_words), n={n}")
    print(f"    byte-diff /240 : min={min(bytediffs)} max={max(bytediffs)} mean={sum(bytediffs)/n:.1f}")
    print(f"    dB divergence  : min={min(maxdb):.1f} max={max(maxdb):.1f} mean={sum(maxdb)/n:.1f} dB")
    ok = min(bytediffs) > 0  # they ARE different encoders; 0 would mean the rogue secretly matched
    print(f"    -> rogue is a distinct encoder: {'CONFIRMED' if ok else 'UNEXPECTED (paths matched)'}")
    return ok


def prove_determinism(n=50, seed=7):
    rng = random.Random(seed)
    bad = 0
    for _ in range(n):
        P = _rand_P(rng)
        if encode.body_from_params(P) != encode.body_from_params(P):
            bad += 1
    print(f"[B] DETERMINISM  compile_body re-run byte-identical: {n - bad}/{n}")
    return bad == 0


def prove_boundary():
    print("[C] BOUNDARY  active paths must not write rogue bodies")
    offenders = []
    for path in sorted(set().union(*[set(p.rglob('*.py')) for p in [ROOT / 'tools', ROOT / 'pyruntime', ROOT / 'src']])):
        rel = path.relative_to(ROOT).as_posix()
        try:
            t = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        writes_rogue = bool(_ROGUE_ENCODE.search(t)) and bool(_BODY_WRITE.search(t))
        if not writes_rogue:
            continue
        if rel in QUARANTINE:
            continue
        if rel == 'tools/null_sweep.py':
            continue
        offenders.append(rel)
    if offenders:
        print(f"    FAIL — coeffs_to_words + .body240 write outside QUARANTINE:")
        for o in offenders:
            print(f"      {o}")
    else:
        print(f"    OK — {len(QUARANTINE)} quarantined exploratory tools; no un-listed rogue writers")
    # encode.py references coeffs_to_words ONLY as the null-reference (words_from_params,
    # diffed inside null_vs_engine); it emits no .body240 literal, so it is not an offender.
    # sweep_roster no longer imports coeffs_to_words. Confirm the active set is offender-free.
    bad_active = [a for a in sorted(ACTIVE) if a in offenders]
    if bad_active:
        print(f"    FAIL — ACTIVE path went rogue: {bad_active}")
    else:
        print(f"    OK — active paths {sorted(ACTIVE)} route through compile_body")
    return not offenders and not bad_active


def main():
    print("=== null_sweep: ONE encoder == compile_body ===\n")
    a = prove_divergence()
    print()
    b = prove_determinism()
    print()
    c = prove_boundary()
    print()
    ok = a and b and c
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
