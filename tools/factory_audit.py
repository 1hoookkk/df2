#!/usr/bin/env python3
"""factory_audit — Phase-1 evidence: measure every factory body's failure modes on
a FINE morph x Q grid (the emit gate only sampled 5x5). No fixes — just evidence.

    python tools/factory_audit.py
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pyruntime import trench_ffi                       # noqa: E402
from pyruntime.packed_interp import kernel_to_biquad   # noqa: E402

SR = 39062.5
FREQS = np.logspace(math.log10(40.0), math.log10(17000.0), 300)
W = 2.0 * math.pi * FREQS / SR
Z1 = np.exp(-1j * W); Z2 = Z1 * Z1
FAC = ROOT / "dev" / "tmp" / "factory"
G = 21                                                  # fine grid (emit used 5)


def mag(body, m, q):
    rows = trench_ffi.packed_interpolate(body, m, q)
    h = np.ones_like(Z1)
    for r in rows:
        b0, b1, b2, a1, a2 = kernel_to_biquad(r)
        h = h * ((b0 + b1 * Z1 + b2 * Z2) / (1.0 + a1 * Z1 + a2 * Z2))
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-9))


def peakhz(body, m, q):
    return float(FREQS[int(np.argmax(mag(body, m, q)))])


def main():
    mani = json.loads((FAC / "manifest.json").read_text())
    hashes, defects = {}, Counter()
    rows = []
    for e in mani:
        body = (FAC / f"{e['id']}.body240").read_bytes()
        maxr, unst, nonf, hot = 0.0, 0, 0, -99.0
        for qi in range(G):
            for mi in range(G):
                p = trench_ffi.packed_probe(body, mi / (G - 1), qi / (G - 1))
                maxr = max(maxr, float(p["max_pole_radius"]))
                unst += int(p["unstable_mask"]).bit_count()
                nonf += int(p["nonfinite_mask"]).bit_count()
        mid = mag(body, 0.5, 0.5)
        hot = float(np.max(mid) - np.median(mid))
        p0, p1 = peakhz(body, 0.0, 1.0), peakhz(body, 1.0, 1.0)
        travel = abs(math.log2(p1 / p0))
        # how much the CURVE itself moves M0->M100 (catches notch-sweeps the peak metric misses)
        curve_delta = float(np.sqrt(np.mean((mag(body, 0.0, 1.0) - mag(body, 1.0, 1.0)) ** 2)))
        ranges = [float(np.ptp(mag(body, m, q))) for m in (0.0, 1.0) for q in (0.0, 1.0)]
        h = hashlib.md5(body).hexdigest()[:8]
        hashes.setdefault(h, []).append(e["id"])
        flags = []
        if maxr >= 1.0 or unst or nonf:
            flags.append("UNSTABLE")
        if curve_delta < 3.0:                               # the curve barely changes = truly static
            flags.append("DEAD")
        if min(ranges) < 6.0:
            flags.append("FLATCORNER")
        if hot > 55.0:
            flags.append("SINGULAR")
        for f in flags:
            defects[f] += 1
        rows.append((e["id"], e["family"], maxr, unst, travel, min(ranges), hot, flags))
        print(f"  {e['id']:10} {e['family'][:18]:18} maxR{maxr:.4f} dCurve{curve_delta:4.1f}dB "
              f"travel{travel:4.2f}oct minRange{min(ranges):3.0f} hot{hot:4.0f}  {' '.join(flags)}")

    dups = {h: ids for h, ids in hashes.items() if len(ids) > 1}
    print("\n=== DEFECT SUMMARY (of {} bodies, fine {}x{} grid) ===".format(len(mani), G, G))
    for d, n in defects.most_common():
        print(f"  {d}: {n}")
    print(f"  DUPLICATE bodies: {sum(len(v) for v in dups.values())} in {len(dups)} groups -> {list(dups.values())[:6]}")
    clean = [r for r in rows if not r[7]]
    print(f"  CLEAN (no defect): {len(clean)}/{len(mani)}")


if __name__ == "__main__":
    main()
