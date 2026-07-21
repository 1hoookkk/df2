"""Null a real ROM filter through OUR ENGINE (trench-core) — corners AND midpoint.

Decode a ROM block (df2/ref/x3_menu/runtime_blocks) into corner words, build a
240-byte body, and run it through the shipping engine (trench_packed_probe in
target/release/trench_core.dll, i.e. PackedCorners::interpolate_biquad). Null the
engine's per-stage biquads against the independent oracle decode
(pyruntime.packed_interp reference) at each morph/q point, including (0.5, 0.5).

If the null is at the f32 floor, our engine faithfully reproduces the ROM filter
and its interpolated midpoints — not just the stored corners.
"""
from __future__ import annotations
import ctypes as C
import os, struct, sys
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyruntime.packed_interp import (_packed_bilinear_reference, kernel_to_biquad,
                                     words_to_coeffs)

DLL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "target", "release", "trench_core.dll")
BLK = r"C:\Users\hooki\df2\ref\x3_menu\runtime_blocks"
PAD = (0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000)   # DAT_1806d7500 — oracle pad row
STAGE_SR = 39_062.5


def rom_corner_words(stem, ns, sr=48000):
    raw = open(rf"{BLK}\{stem}_{sr}.raw", "rb").read()
    w = struct.unpack(f"<{len(raw)//2}H", raw); per = ns * 5
    # -> dict A/B/C/D, each a list of 6 stage-word-tuples (pad to 6 stages)
    keys = ["A", "B", "C", "D"]
    out = {}
    for c in range(4):
        stages = [tuple(w[c*per+s*5: c*per+s*5+5]) for s in range(ns)]
        stages += [PAD] * (6 - ns)
        out[keys[c]] = stages
    return out


def body_bytes(cw):
    b = bytearray()
    for k in ["A", "B", "C", "D"]:
        for stage in cw[k]:
            for word in stage:
                b += struct.pack("<H", word)
    assert len(b) == 240, len(b)
    return bytes(b)


def engine_probe(lib, body, morph, q):
    out = (C.c_double * 30)()
    mr = C.c_double(); um = C.c_uint32(); nm = C.c_uint32()
    rc = lib.trench_packed_probe(body, len(body), C.c_double(morph), C.c_double(q),
                                 out, C.byref(mr), C.byref(um), C.byref(nm))
    if rc != 0:
        raise RuntimeError(f"trench_packed_probe rc={rc}")
    return np.array(out).reshape(6, 5), mr.value


def ref_probe(cw, morph, q):
    rows = _packed_bilinear_reference(cw, morph, q)          # 6 × (c0..c4)
    return np.array([kernel_to_biquad(r) for r in rows])     # 6 × (b0..a2)


def mag_db(biquads, freqs, sr):
    z = np.exp(-1j * 2 * np.pi * freqs / sr); t = np.zeros_like(freqs)
    for b0, b1, b2, a1, a2 in biquads:
        t += 20 * np.log10(np.abs(b0 + b1*z + b2*z*z) / np.abs(1 + a1*z + a2*z*z) + 1e-12)
    return t


def main():
    lib = C.CDLL(DLL)
    lib.trench_packed_probe.restype = C.c_int32
    lib.trench_packed_probe.argtypes = [C.c_char_p, C.c_size_t, C.c_double, C.c_double,
                                        C.POINTER(C.c_double), C.POINTER(C.c_double),
                                        C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]

    stem, ns = "phaser_1", 2
    cw = rom_corner_words(stem, ns)
    body = body_bytes(cw)

    pts = [("M0/Q0", 0.0, 0.0), ("M100/Q0", 1.0, 0.0), ("M0/Q100", 0.0, 1.0),
           ("M100/Q100", 1.0, 1.0), ("MIDPOINT 0.5/0.5", 0.5, 0.5),
           ("0.25/0.75", 0.25, 0.75)]

    print(f"ROM filter '{stem}' nulled through trench-core engine (corners + midpoint):")
    print(f"{'point':18s} {'engine max|coeff|':>18s} {'max |engine-ref|':>18s} {'resp null dB':>14s}")
    freqs = np.geomspace(30, STAGE_SR * 0.49, 1024)
    worst = 0.0
    mid = None
    for name, m, q in pts:
        eng, mr = engine_probe(lib, body, m, q)
        ref = ref_probe(cw, m, q)
        cdiff = float(np.max(np.abs(eng - ref)))
        rnull = float(np.max(np.abs(mag_db(eng, freqs, STAGE_SR) - mag_db(ref, freqs, STAGE_SR))))
        worst = max(worst, cdiff)
        print(f"{name:18s} {np.abs(eng).max():18.6g} {cdiff:18.3e} {rnull:14.2e}")
        if "MID" in name:
            mid = (eng, ref)

    print(f"\nworst coeff null across all points: {worst:.3e}  "
          f"({'PASS — engine == oracle' if worst < 1e-5 else 'FAIL'})")

    eng, ref = mid
    fig, (ax, axn) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [3, 1]})
    ax.semilogx(freqs, mag_db(ref, freqs, STAGE_SR), color="black", lw=3, label="oracle decode of ROM words")
    ax.semilogx(freqs, mag_db(eng, freqs, STAGE_SR), color="orange", lw=1.3, ls="--", label="our engine (trench-core)")
    ax.set_title(f"{stem} @ MIDPOINT (morph=0.5, res=0.5) — engine vs oracle"); ax.legend()
    ax.grid(True, which="both", alpha=0.25); ax.set_ylabel("dB"); ax.set_xlim(30, STAGE_SR/2)
    axn.semilogx(freqs, mag_db(eng, freqs, STAGE_SR) - mag_db(ref, freqs, STAGE_SR), color="crimson", lw=1)
    axn.set_title("null (engine − oracle), dB"); axn.grid(True, which="both", alpha=0.25)
    axn.set_xlim(30, STAGE_SR/2); axn.set_xlabel("Hz")
    fig.tight_layout()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scratchpad", "engine_null_phaser1.png")
    fig.savefig(out, dpi=115); print("wrote", os.path.abspath(out))


if __name__ == "__main__":
    main()
