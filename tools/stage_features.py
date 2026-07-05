"""Per-lane stage features from packed 240-byte bodies (study-only).

Legal pipeline ONLY: packed words -> pyruntime.packed_interp.packed_bilinear
(real trench-core lerp_u16 via FFI) -> kernel_to_biquad -> roots.
Output is measurements for AGGREGATE use (clean-room)."""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from pyruntime import packed_interp as pi

SR = 39062.5
CORNERS = [("M0Q0", 0.0, 0.0), ("M100Q0", 1.0, 0.0), ("M0Q100", 0.0, 1.0), ("M100Q100", 1.0, 1.0)]
FGRID = np.geomspace(20.0, SR * 0.499, 160)


def load_body(path: str) -> dict:
    """dir with variant_0_*.bin, or a bare 240-byte file -> corner-word dict."""
    hits = glob.glob(os.path.join(path, "variant_0_*.bin")) if os.path.isdir(path) else [path]
    raw = open(hits[0], "rb").read()
    assert len(raw) == 240, f"{hits[0]}: {len(raw)} bytes != 240"
    w = np.frombuffer(raw, dtype="<u2").reshape(4, 6, 5)
    return {k: [tuple(int(x) for x in w[c, s]) for s in range(6)] for c, k in enumerate("ABCD")}


def _roots(c2, c1, c0):
    if abs(c2) < 1e-18:
        return [] if abs(c1) < 1e-18 else [complex(-c0 / c1)]
    return [complex(r) for r in np.roots([c2, c1, c0])]


def _facts(rs):
    out = []
    for r in rs:
        out.append({"real": abs(r.imag) < 1e-9, "f": abs(np.angle(r)) / (2 * np.pi) * SR, "r": abs(r)})
    return out


def stage_info(row) -> dict:
    b0, b1, b2, a1, a2 = pi.kernel_to_biquad(row)
    poles = _facts(_roots(1.0, a1, a2) if (a1 or a2) else [])
    zeros = _facts(_roots(b0, b1, b2) if b0 else [])
    z = np.exp(-1j * 2 * np.pi * FGRID / SR)
    h = (b0 + b1 * z + b2 * z**2) / (1 + a1 * z + a2 * z**2)
    mag = 20 * np.log10(np.maximum(np.abs(h), 1e-12))
    dc = 20 * np.log10(max(abs((b0 + b1 + b2) / (1 + a1 + a2 + 1e-18)), 1e-12))
    zr1_exact = bool(b0) and abs(b2 - b0) <= 1e-12 * max(abs(b0), 1e-18) and abs(b2 / b0) > 0.5
    zr1 = zr1_exact or any(zz["r"] >= 0.99995 and not zz["real"] for zz in zeros)
    return {"poles": poles, "zeros": zeros, "dc": float(dc),
            "flat": float(mag.max() - mag.min()), "zr1": bool(zr1), "has_zero": len(zeros) > 0,
            "biquad": [float(b0), float(b1), float(b2), float(a1), float(a2)]}


def _conj_pole_f(info):
    cs = [p for p in info["poles"] if not p["real"]]
    return cs[0]["f"] if cs else None


def _conj_zero(info):
    cs = [z for z in info["zeros"] if not z["real"]]
    return cs[0] if cs else None


def _travel_oct(f0, f1):
    if f0 and f1 and f0 > 25 and f1 > 25:
        return float(np.log2(f1 / f0))
    return 0.0


def body_features(cw: dict) -> list:
    """6 lane dicts: per-corner stage_info + journey + Q-repose attributes."""
    info = [[stage_info(r) for r in pi.packed_bilinear(cw, m, q)] for _, m, q in CORNERS]
    lanes = []
    for s in range(6):
        corners = [info[c][s] for c in range(4)]
        pf = [_conj_pole_f(c) for c in corners]
        zf = [(_conj_zero(c) or {"f": None})["f"] for c in corners]
        qp0, qp2 = _conj_pole_f(corners[0]), _conj_pole_f(corners[2])
        r0 = corners[0]["poles"][0]["r"] if corners[0]["poles"] else 0.0
        r2 = corners[2]["poles"][0]["r"] if corners[2]["poles"] else 0.0
        lanes.append({
            "corners": corners,
            "pole_travel_oct": _travel_oct(pf[0], pf[1]),
            "zero_travel_oct": _travel_oct(zf[0], zf[1]) if (zf[0] and zf[1]) else 0.0,
            "max_dc": max(c["dc"] for c in corners),
            "q_pole_df": float((qp2 or 0.0) - (qp0 or 0.0)),
            "q_pole_dr": float(r2 - r0),
        })
    return lanes


MUSICAL_33 = sorted(glob.glob(os.path.join("ref", "p2k_variants", "P2k_0[0-2]*")) +
                    glob.glob(os.path.join("ref", "p2k_variants", "P2k_03[0-2]*")))

if __name__ == "__main__":
    for d in MUSICAL_33:
        lanes = body_features(load_body(d))
        found = [i + 1 for i, l in enumerate(lanes) if all(c["zr1"] for c in l["corners"])]
        print(f"{os.path.basename(d):34s} foundation@{found}")
