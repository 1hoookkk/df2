"""Decompose a body into fundamental biquad STAGES — the real test of the
"P2K = assembled fundamental biquads" claim.

Vocabulary = every fundamental's (corner, stage) biquad decoded from the ROM
runtime blocks (minifloat codec). For each of a body's 24 stage-slots (4 corners
x 6 stages, pad stages skipped) find the nearest vocabulary biquad by physical-Hz
magnitude-response RMS error. Report the corner x stage grid + the match error, so
lone-resonator ambiguity (vocal vs BP vs EQ) is visible, not hidden.
"""
from __future__ import annotations
import struct, sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad

BLK = r"C:\Users\hooki\df2\ref\x3_menu\runtime_blocks"
PAD = (0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000)
FUND_SR, BODY_SR = 48000.0, 39062.5
GRID = np.geomspace(40, 18000, 400)
NS = {"2_pole_lowpass":1,"4_pole_lowpass":2,"6_pole_lowpass":3,"2_pole_highpass":1,
      "4_pole_highpass":2,"2_pole_bandpass":1,"4_pole_bandpass":2,"contrary_bandpass":1,
      "swept_eq_1_octave":1,"swept_eq_2_1_octave":1,"swept_eq_3_1_octave":1,
      "phaser_1":2,"phaser_2":2,"bat_phaser":2,"flanger_lite":3,
      "vocal_ah_ay_ee":3,"vocal_oo_ah":3}
CUSTOM_RMS = 4.0   # dB; nearest-vocab RMS above this -> the stage is CUSTOM voice


def resp(biquad, sr):
    b0, b1, b2, a1, a2 = biquad
    z = np.exp(-1j * 2 * np.pi * GRID / sr)
    m = 20 * np.log10(np.abs(b0 + b1*z + b2*z*z) / np.abs(1 + a1*z + a2*z*z) + 1e-9)
    return m - np.median(m)


def vocab():
    V = []
    for stem, ns in NS.items():
        raw = open(rf"{BLK}\{stem}_48000.raw", "rb").read()
        w = struct.unpack(f"<{len(raw)//2}H", raw); per = ns * 5
        for c in range(4):
            for s in range(ns):
                words = w[c*per+s*5: c*per+s*5+5]
                if words == PAD: continue
                V.append((stem, resp(kernel_to_biquad(words_to_coeffs(words)), FUND_SR)))
    return V


def body_stages(path):
    w = struct.unpack("<120H", open(path, "rb").read())
    out = []
    for c in range(4):
        row = []
        for s in range(6):
            words = w[(c*6+s)*5:(c*6+s)*5+5]
            row.append(None if words == PAD else kernel_to_biquad(words_to_coeffs(words)))
        out.append(row)
    return out


def main():
    path = sys.argv[1]
    V = vocab()
    Vresp = np.array([r for _, r in V]); Vname = [n for n, _ in V]
    stages = body_stages(path)
    print(f"\n{os.path.basename(path)} — stage decomposition (nearest fundamental biquad, RMS dB):")
    print("        " + "  ".join(f"{'S'+str(s):>16s}" for s in range(6)))
    tally = {}
    for c in range(4):
        cells = []
        for s in range(6):
            bq = stages[c][s]
            if bq is None:
                cells.append(f"{'(pad)':>16s}"); continue
            r = resp(bq, BODY_SR)
            err = np.sqrt(np.mean((Vresp - r) ** 2, axis=1))
            i = int(np.argmin(err))
            name = Vname[i] if err[i] <= CUSTOM_RMS else "CUSTOM"
            tally[name] = tally.get(name, 0) + 1
            cells.append(f"{name[:11]:>11s}:{err[i]:4.1f}")
        print(f"  C{c}   " + "  ".join(cells))
    n = sum(tally.values())
    cust = tally.get("CUSTOM", 0)
    print(f"\n  matched stages: {n-cust}/{n}   CUSTOM: {cust} ({100*cust//max(n,1)}%)")
    print("  tally:", dict(sorted(tally.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
