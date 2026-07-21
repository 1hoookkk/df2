"""Frame+Voice compiler — embodies what this session proved.

A recipe is 6 stage-slots. Each slot has a ROLE and per-corner (fc, r, zero_offset):
  air    - high dipole (the crown)            } FRAME
  body   - low pole inside a notch            } FRAME
  notch  - structural unit-ish notch          } FRAME
  voice  - a formant peak (your measured data){ VOICE (fill from wav/IR/table)
  s5     - the mandatory S5 unit-circle notch (auto-enforced on stage 5)
Unused slots are filled with the SENTINEL (phantom passthrough).

Laws enforced (all measured this session):
  - biquad budget = 6
  - stage 5 is always a unit-circle notch (zero r = 1.0)
  - contrast = zero placed zero_offset octaves from the pole
Pack path (coeffs_to_words -> assemble) and author-from-freq are the ones
verify_pipeline.py proved bit-exact. Output is engine-null checked before it's kept.
"""
from __future__ import annotations
import ctypes as C, struct, json, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyruntime.packed_interp import coeffs_to_words

SR = 39062.5
PAD = (0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000)          # sentinel / phantom passthrough
CORNERS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
DLL = os.path.join(ROOT, "target", "release", "trench_core.dll")
_lib = C.CDLL(DLL)
_lib.trench_packed_probe.restype = C.c_int32
_lib.trench_packed_probe.argtypes = [C.c_char_p, C.c_size_t, C.c_double, C.c_double,
    C.POINTER(C.c_double), C.POINTER(C.c_double), C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]


def biquad_to_kernel(b0, b1, b2, a1, a2):
    return (b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


def biquad(fc, pole_r, zero_off_oct, zero_r, gain=1.0):
    """Pole at fc (radius pole_r); zero at fc*2^off (radius zero_r). The zero_off
    IS the contrast dial; zero_r=1.0 gives a true (on-circle) notch."""
    wp = 2 * np.pi * fc / SR
    wz = 2 * np.pi * (fc * 2.0 ** zero_off_oct) / SR
    return (gain, -2 * zero_r * np.cos(wz) * gain, zero_r ** 2 * gain,
            -2 * pole_r * np.cos(wp), pole_r ** 2)


def stage_words(role, p):
    """p = {fc, r, zoff}. -> 5 packed u16 words for one stage at one corner."""
    fc = p.get("fc", 1000.0); r = p.get("r", 0.97); zoff = p.get("zoff", 0.0)
    if role == "s5" or role == "notch":
        zr = 1.0 if role == "s5" else p.get("zero_r", 0.97)
        bq = biquad(fc, r, zoff, zr)
    elif role == "body":
        bq = biquad(fc, r, p.get("zoff", 1.4), 1.0)          # low pole under an on-circle notch
    elif role == "air":
        bq = biquad(fc, r, p.get("zoff", 0.4), 0.85)         # high dipole with a scoop
    else:  # voice formant
        bq = biquad(fc, r, zoff, p.get("zero_r", 0.9))
    return coeffs_to_words(*biquad_to_kernel(*bq))


def compile_recipe(recipe):
    stages = recipe["stages"]
    assert len(stages) == 6, "biquad budget is 6"
    words = {c: [] for c in CORNERS}
    for si, st in enumerate(stages):
        role = st["role"]
        if si == 5 and role != "s5":
            role = "s5"                                       # enforce the S5 unit-notch law
        for c in CORNERS:
            if role == "sentinel":
                words[c].append(PAD)
            else:
                p = st.get(c) or st.get("all") or {}
                words[c].append(tuple(stage_words(role, p)))
    body = bytearray()
    for c in CORNERS:
        for row in words[c]:
            for w in row:
                body += struct.pack("<H", int(w) & 0xFFFF)
    return bytes(body)


def engine_check(body):
    """-> (max_pole_radius, unstable_mask, nonfinite_mask) at the 4 corners+mid."""
    worst = 0.0; unst = 0; nonf = 0
    for m, q in [(0., 0.), (1., 0.), (0., 1.), (1., 1.), (0.5, 0.5)]:
        out = (C.c_double * 30)(); mr = C.c_double(); um = C.c_uint32(); nm = C.c_uint32()
        rc = _lib.trench_packed_probe(body, 240, C.c_double(m), C.c_double(q), out,
                                      C.byref(mr), C.byref(um), C.byref(nm))
        assert rc == 0, rc
        worst = max(worst, mr.value); unst |= um.value; nonf |= nm.value
    return worst, unst, nonf


def main():
    recipe = json.loads(open(sys.argv[1]).read())
    body = compile_recipe(recipe)
    worst, unst, nonf = engine_check(body)
    ok = worst < 1.0 and nonf == 0
    out_dir = os.path.join(ROOT, "plugin", "presets", "bodies")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{recipe['name']}.body240")
    if ok:
        open(out, "wb").write(body)
    print(f"{recipe['name']}: max_pole_r={worst:.3f} unstable_mask={unst:04b} nonfinite={nonf}")
    print("WROTE " + out if ok else "REJECTED (unstable/nonfinite) — not written")


if __name__ == "__main__":
    main()
