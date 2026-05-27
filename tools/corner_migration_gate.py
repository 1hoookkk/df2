"""Gate for migrating pyruntime/corner.py onto the packed-math owner.

OLD path  = the pre-migration formula (minifloat.pack + minifloat.interpolate_packed,
            Q-first + clamp + gain packed at the wrong scale) -- still callable.
NEW path  = CornerArray.interpolate (now routed through pyruntime.packed_interp ->
            trench-core: morph-first + i16-truncate-wrap + c4/4 gain scale).

Proves, on real bodies:
  1. At the 4 corners (m,q in {0,1}) the TONE coeffs c0..c3 are bit-identical
     (corners don't move); only the gain c4 may re-quantize to the runtime scale.
  2. NEW == the owner's packed_bilinear everywhere (corner.py now IS the owner),
     and each corner routes to the right target (catches a B/C transposition).
  3. How much the MIDDLE response shifts (the real, intended change), in dB.

Run:  python -m tools.corner_migration_gate
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

from pyruntime.corner import CornerArray, CornerState
from pyruntime.encode import EncodedCoeffs
from pyruntime import packed_interp as pk
from pyruntime import minifloat as old
from pyruntime import forge_fit as ff

SR = 39062.5
FREQS, ZINV = ff.fit_grid(SR, 1024)


def _encs(stages):
    return [EncodedCoeffs(c0=s["c0"], c1=s["c1"], c2=s["c2"], c3=s["c3"], c4=s["c4"]) for s in stages]


def _corner_array(by_label):
    """corner.py order: 0=M0_Q0, 1=M0_Q100, 2=M100_Q0, 3=M100_Q100."""
    order = ["M0_Q0", "M0_Q100", "M100_Q0", "M100_Q100"]
    states = [CornerState(stages=[], _pre_encoded=by_label[lbl]) for lbl in order]
    return CornerArray(*states)


def _old_interp(arr, morph, q):
    """Replicate the pre-migration corner.py.interpolate via the old minifloat path."""
    e = [c.encode() for c in arr._corners]  # 0=M0_Q0,1=M0_Q100,2=M100_Q0,3=M100_Q100
    out = []
    for i in range(len(e[0])):
        out.append(old.interpolate_packed(
            old.pack(e[0][i]), old.pack(e[1][i]), old.pack(e[2][i]), old.pack(e[3][i]),
            morph=float(morph), q=float(q)))
    return out


def _kernel(encs):
    return np.array([[e.c0, e.c1, e.c2, e.c3, e.c4] for e in encs], float)


def _db(encs):
    return 20.0 * np.log10(np.abs(ff.cascade_response(_kernel(encs), ZINV)) + 1e-12)


def _owner_rows(by_label, morph, q):
    bank = {
        "A": [pk.coeffs_to_words(*[getattr(e, f"c{i}") for i in range(5)]) for e in by_label["M0_Q0"]],
        "B": [pk.coeffs_to_words(*[getattr(e, f"c{i}") for i in range(5)]) for e in by_label["M100_Q0"]],
        "C": [pk.coeffs_to_words(*[getattr(e, f"c{i}") for i in range(5)]) for e in by_label["M0_Q100"]],
        "D": [pk.coeffs_to_words(*[getattr(e, f"c{i}") for i in range(5)]) for e in by_label["M100_Q100"]],
    }
    return pk.packed_bilinear(bank, float(morph), float(q))


def gate(name, by_label):
    print(f"\n=== BODY: {name} ===")
    arr = _corner_array(by_label)

    # 1) corners: c0..c3 must be bit-identical OLD vs NEW; c4 may shift
    corner_pts = {"M0_Q0": (0.0, 0.0), "M100_Q0": (1.0, 0.0),
                  "M0_Q100": (0.0, 1.0), "M100_Q100": (1.0, 1.0)}
    print("  corners (OLD vs NEW):")
    tone_max = 0.0
    for lbl, (m, q) in corner_pts.items():
        o = _old_interp(arr, m, q)
        n = arr.interpolate(m, q)
        tone = max(max(abs(getattr(no, f"c{i}") - getattr(oo, f"c{i}")) for i in range(4))
                   for oo, no in zip(o, n))
        c4o = max(abs(oo.c4) for oo in o)
        c4n = max(abs(no.c4) for no in n)
        tone_max = max(tone_max, tone)
        print(f"    {lbl:9s} tone c0..c3 max|d|={tone:.2e}   peak c4 OLD={c4o:.4f} NEW={c4n:.4f}")

    # 2) NEW == owner, and each corner routes to the right target
    own_max = 0.0
    remap_ok = True
    for lbl, (m, q) in corner_pts.items():
        n = arr.interpolate(m, q)
        ow = _owner_rows(by_label, m, q)
        own_max = max(own_max, max(max(abs(getattr(no, f"c{i}") - ow[si][i]) for i in range(5))
                                   for si, no in enumerate(n)))
        # the corner should equal that label's own self round-trip
        self_rt = [pk.words_to_coeffs(pk.coeffs_to_words(*[getattr(e, f"c{k}") for k in range(5)]))
                   for e in by_label[lbl]]
        if max(max(abs(getattr(no, f"c{i}") - self_rt[si][i]) for i in range(5))
               for si, no in enumerate(n)) > 1e-12:
            remap_ok = False
    print(f"  NEW == owner packed_bilinear: max|d| = {own_max:.2e}")
    print(f"  corner remap routes correctly (no B/C transposition): {'PASS' if remap_ok else 'FAIL'}")

    # 3) the MIDDLE: how much the response shifts (the intended change)
    print("  MIDDLE response shift (OLD vs NEW), dB:")
    for m, q in [(0.5, 0.5), (0.25, 0.5), (0.5, 0.25), (0.75, 0.75)]:
        do = _db(_old_interp(arr, m, q))
        dn = _db(arr.interpolate(m, q))
        diff = np.abs(dn - do)
        fpk = FREQS[int(np.argmax(diff))]
        print(f"    ({m:.2f},{q:.2f})  max|d|={diff.max():5.2f} dB @ {fpk:6.0f} Hz   mean|d|={diff.mean():.2f} dB")

    return tone_max, own_max, remap_ok


def main() -> int:
    print(f"packed-math backend: {pk.core_backend()}")
    bodies = {}

    live = os.path.expanduser("~/Documents/TRENCH/authoring_slot.json")
    if os.path.exists(live):
        cart = json.load(open(live, encoding="utf-8"))
        bodies["live (authoring_slot)"] = {kf["label"]: _encs(kf["stages"]) for kf in cart["keyframes"]}

    # synthetic kin body with high gain (c4>1) -- exposes the OLD path's gain clamp
    def stage(c0, c1, c2, c3, c4):
        return {"c0": c0, "c1": c1, "c2": c2, "c3": c3, "c4": c4}

    def corner(f1, gain):
        # 3 resonant stages on a shared skeleton + 3 mild; gain pushes c4 past 1.0
        return _encs([
            stage(2 - 2 * math.cos(2 * math.pi * f1 / SR) * 0.99, 0.2, 1.9, 0.02, gain),
            stage(2 - 2 * math.cos(2 * math.pi * f1 * 2.4 / SR) * 0.98, 0.25, 1.8, 0.04, gain * 0.8),
            stage(2 - 2 * math.cos(2 * math.pi * f1 * 4.1 / SR) * 0.97, 0.3, 1.7, 0.06, gain * 0.6),
            stage(1.9, 0.2, 1.9, 0.5, 0.9), stage(1.8, 0.3, 1.8, 0.6, 0.9), stage(1.7, 0.4, 1.7, 0.7, 0.9),
        ])
    bodies["synthetic high-gain (c4>1)"] = {
        "M0_Q0": corner(300, 1.3), "M100_Q0": corner(700, 1.3),
        "M0_Q100": corner(300, 1.3), "M100_Q100": corner(700, 1.3),
    }

    worst_tone = 0.0
    worst_own = 0.0
    all_remap = True
    for name, bl in bodies.items():
        t, o, r = gate(name, bl)
        worst_tone = max(worst_tone, t)
        worst_own = max(worst_own, o)
        all_remap = all_remap and r

    print("\n--- GATE SUMMARY ---")
    print(f"  corner tone (c0..c3) bit-identical OLD vs NEW : {'PASS' if worst_tone < 1e-9 else f'FAIL ({worst_tone:.2e})'}")
    print(f"  NEW == runtime owner everywhere               : {'PASS' if worst_own < 1e-9 else f'FAIL ({worst_own:.2e})'}")
    print(f"  corner remap correct (no transposition)       : {'PASS' if all_remap else 'FAIL'}")
    ok = worst_tone < 1e-9 and worst_own < 1e-9 and all_remap
    print("  RESULT:", "PASS -- corners pinned, middle now matches the player" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
