"""Probe the X3 menu fixed-point decode using a known filter as the oracle.

The runtime_blocks hold raw i16 words, 5 per corner per stage, corner-major
(see tools/extract_x3_menu_filters.py: compact_corner_snapshot). The scale and
word order are 'intentionally unclassified'. This script brute-forces the
plausible (word-order, fixed-point scale, representation) combinations and keeps
the ones where the *2 Pole Lowpass* decodes to four STABLE, LOWPASS-shaped
corners — the behaviour its name guarantees. That pins the decode for the whole
fixed-class family (they share the writer math).

Run: python tools/probe_x3_decode.py
"""

from __future__ import annotations

import struct
from itertools import permutations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BLOCKS = ROOT / "ref" / "x3_menu" / "runtime_blocks"
CORNERS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]


def read_block(name: str, n_stages: int) -> list[list[list[int]]]:
    """Return corners[4][stage][5 i16]."""
    raw = (BLOCKS / f"{name}.raw").read_bytes()
    words = list(struct.unpack(f"<{len(raw)//2}h", raw))  # little-endian i16
    per_corner = n_stages * 5
    out = []
    for c in range(4):
        seg = words[c * per_corner : (c + 1) * per_corner]
        out.append([seg[s * 5 : s * 5 + 5] for s in range(n_stages)])
    return out


def biquad_mag(b, a, sr, freqs):
    w = 2 * np.pi * freqs / sr
    z = np.exp(-1j * w)
    num = b[0] + b[1] * z + b[2] * z * z
    den = 1.0 + a[0] * z + a[1] * z * z
    return 20 * np.log10(np.abs(num / den) + 1e-12)


def poles_stable(a1, a2) -> bool:
    # roots of 1 + a1 z^-1 + a2 z^-2 inside unit circle  <=>  |a2|<1 and |a1|<1+a2
    return abs(a2) < 0.999 and abs(a1) < 1.0 + a2


def evaluate(words5, scale, order, rep):
    """Decode one stage's 5 words into DF2T (b0,b1,b2,a1,a2). Return None if junk."""
    v = [w / scale for w in words5]
    o = [v[i] for i in order]  # reorder to canonical slots
    if rep == "df2t":  # [b0,b1,b2,a1,a2]
        b0, b1, b2, a1, a2 = o
    else:  # 'kernel' shifted form [2+b1, 1-b2, a1+2, 1-a2, g]
        b1 = o[0] - 2.0
        b2 = 1.0 - o[1]
        a1 = o[2] - 2.0
        a2 = 1.0 - o[3]
        b0 = o[4]
    return (b0, b1, b2, a1, a2)


def main():
    sr = 48000
    name = "2_pole_lowpass_48000"
    corners = read_block(name, 1)
    freqs = np.geomspace(20, sr / 2 * 0.99, 256)
    scales = [32768.0, 16384.0, 8192.0, 4096.0, 2048.0]
    # only orderings where 3 slots are numerator, 2 denominator — try a few sane ones
    orders = [
        (0, 1, 2, 3, 4),
        (2, 3, 4, 0, 1),
        (4, 3, 2, 1, 0),
        (0, 1, 2, 4, 3),
    ]
    print(f"oracle: {name} — all 4 corners must be STABLE and LOWPASS\n")
    hits = 0
    for rep in ("df2t", "kernel"):
        for scale in scales:
            for order in orders:
                ok = True
                shapes = []
                for c in range(4):
                    dec = evaluate(corners[c][0], scale, order, rep)
                    b0, b1, b2, a1, a2 = dec
                    if not all(np.isfinite(dec)) or not poles_stable(a1, a2):
                        ok = False
                        break
                    mag = biquad_mag([b0, b1, b2], [a1, a2], sr, freqs)
                    lowpass = mag[0] - mag[-1]  # low minus high; >0 = lowpass
                    shapes.append(lowpass)
                if ok and all(s > 3.0 for s in shapes):
                    hits += 1
                    print(f"CANDIDATE rep={rep:6} scale={scale:>8.0f} order={order} "
                          f"LP_rolloff_dB={[f'{s:.1f}' for s in shapes]}")
                    # dump corner 0 decoded coeffs
                    d0 = evaluate(corners[0][0], scale, order, rep)
                    print(f"   M0_Q0 coeffs b0,b1,b2,a1,a2 = {[f'{x:+.4f}' for x in d0]}")
    if not hits:
        print("no candidate passed — widen scales/orders or the words aren't raw DF2T.")
    else:
        print(f"\n{hits} candidate decode(s) found.")


if __name__ == "__main__":
    main()
