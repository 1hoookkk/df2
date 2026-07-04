"""Exact per-stage anatomy from packed words: poles/zeros/gain at the 4 corners.

Companion to tools/plot_stages.py — the sheets show the shapes, this prints
the numbers the dossier quotes. Same legal pipeline: 240-byte packed body ->
pyruntime.packed_interp.packed_bilinear (real trench-core lerp_u16 via FFI)
-> kernel_to_biquad -> root-find numerator/denominator. No reductions.

Usage:
  python tools/stage_anatomy.py P2k_004_meaty_gizmo P2k_029_lucifer_s_q
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from pyruntime import packed_interp as pi

SR = 39062.5
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CORNERS = [("M0Q0", 0.0, 0.0), ("M100Q0", 1.0, 0.0),
           ("M0Q100", 0.0, 1.0), ("M100Q100", 1.0, 1.0)]


def load_body(body: str) -> dict:
    pat = os.path.join(ROOT, "ref", "p2k_variants", body, "variant_0_*.bin")
    hits = glob.glob(pat)
    if not hits:
        if os.path.isfile(body) and os.path.getsize(body) == 240:
            hits = [body]
        else:
            raise SystemExit(f"no body found: {pat}")
    raw = open(hits[0], "rb").read()
    assert len(raw) == 240, f"{hits[0]}: {len(raw)} bytes != 240"
    w = np.frombuffer(raw, dtype="<u2").reshape(4, 6, 5)
    return {k: [tuple(int(x) for x in w[c, s]) for s in range(6)] for c, k in enumerate("ABCD")}


def roots2(c2, c1, c0):
    if abs(c2) < 1e-18:
        return [] if abs(c1) < 1e-18 else [-c0 / c1]
    return list(np.roots([c2, c1, c0]))


def fmt_root(r) -> str:
    r = complex(r)
    mag = abs(r)
    if abs(r.imag) < 1e-9:
        return f"REAL {r.real:+.4f} (|r|={mag:.4f})"
    f = abs(np.angle(r)) / (2 * np.pi) * SR
    return f"{f:7.0f} Hz r={mag:.4f}"


def report(body: str) -> None:
    cw = load_body(body)
    print(f"=== {body} ===")
    for lb, m, q in CORNERS:
        rows = pi.packed_bilinear(cw, m, q)
        print(f"\n-- {lb} --")
        for s, row in enumerate(rows):
            b0, b1, b2, a1, a2 = pi.kernel_to_biquad(row)
            poles = roots2(1.0, a1, a2)
            zeros = roots2(b0, b1, b2)
            w = 2 * np.pi * 1000.0 / SR
            z1 = np.exp(-1j * w)
            h1k = abs((b0 + b1 * z1 + b2 * z1 * z1) / (1 + a1 * z1 + a2 * z1 * z1))
            dc = abs((b0 + b1 + b2) / (1 + a1 + a2))
            ps = " | ".join(fmt_root(p) for p in sorted(poles, key=lambda r: abs(np.angle(complex(r)))))
            zs = " | ".join(fmt_root(z) for z in sorted(zeros, key=lambda r: abs(np.angle(complex(r))))) or "none"
            print(f" st{s+1}: pole {ps:44s} zero {zs:44s} "
                  f"DC {20*np.log10(max(dc,1e-9)):+6.1f} dB  @1k {20*np.log10(max(h1k,1e-9)):+6.1f} dB")


if __name__ == "__main__":
    for b in sys.argv[1:] or ["P2k_013_talking_hedz"]:
        report(b)
