"""Null the 8 gold P2K bodies through OUR engine (corners + midpoint) and, for the
ones that null, print the FRAME: which stages are air / body / voice / notch.

Gate (Tyson): only trust a frame if the gold body reproduces through trench-core.
Frame = air (high pole) + body (low pole, usually in a notch) + the S5 unit-circle
notch + structural notches. Voice = mid formant PEAKS (swappable with measured data).
"""
from __future__ import annotations
import ctypes as C, struct, glob, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyruntime.packed_interp import _packed_bilinear_reference, kernel_to_biquad, words_to_coeffs

DLL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "target", "release", "trench_core.dll")
GOLD = r"C:\Users\hooki\surface-forge\out\foundry\ROM_GOLD"
PAD = (0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000); SR = 39062.5
F = np.geomspace(30, 19000, 1500)

lib = C.CDLL(DLL)
lib.trench_packed_probe.restype = C.c_int32
lib.trench_packed_probe.argtypes = [C.c_char_p, C.c_size_t, C.c_double, C.c_double,
    C.POINTER(C.c_double), C.POINTER(C.c_double), C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]


def corner_words(body):
    w = struct.unpack("<120H", body)
    keys = ["A", "B", "C", "D"]
    return {keys[c]: [tuple(w[(c*6+s)*5:(c*6+s)*5+5]) for s in range(6)] for c in range(4)}


def engine(body, m, q):
    out = (C.c_double*30)(); mr = C.c_double(); um = C.c_uint32(); nm = C.c_uint32()
    rc = lib.trench_packed_probe(body, len(body), C.c_double(m), C.c_double(q), out, C.byref(mr), C.byref(um), C.byref(nm))
    assert rc == 0, rc
    return np.array(out).reshape(6, 5)


def oracle(cw, m, q):
    return np.array([kernel_to_biquad(r) for r in _packed_bilinear_reference(cw, m, q)])


def stage_role(words):
    if words == PAD: return "pad", None, None
    b0, b1, b2, a1, a2 = kernel_to_biquad(words_to_coeffs(words))
    z = np.exp(-1j*2*np.pi*F/SR)
    mag = 20*np.log10(np.abs(b0+b1*z+b2*z*z)/np.abs(1+a1*z+a2*z*z)+1e-9); mag -= np.median(mag)
    poles = np.roots([1, a1, a2]); ph = abs(np.angle(poles[np.argmax(np.abs(poles))]))/(2*np.pi)*SR
    zr = max(abs(x) for x in np.roots([b0, b1, b2]))
    notch = mag.min() < -6 and mag.min() < -mag.max()
    if notch: role = "NOTCH"
    elif mag.max() > 6 and mag.min() < -6: role = "DIPOLE"
    elif mag.max() > 1.5: role = "PEAK"
    else: role = "flat"
    band = "air" if ph >= 5000 else "body" if ph < 420 else "voice"
    return role, band, ph


NAMES = ["003_millennium", "004_meaty_gizmo", "010_ooh_to_eee", "013_talking_hedz",
         "018_razor_blades", "022_deep_bouche", "029_lucifer_s_q", "030_tooth_comb"]
PTS = [(0.,0.), (1.,0.), (0.,1.), (1.,1.), (0.5,0.5)]

for nm in NAMES:
    fp = glob.glob(GOLD+rf"\P2k_{nm}.body240")
    if not fp: continue
    body = open(fp[0], "rb").read()
    cw = corner_words(body)
    worst = max(float(np.max(np.abs(engine(body, m, q) - oracle(cw, m, q)))) for m, q in PTS)
    verdict = "NULLS" if worst < 1e-6 else f"FAIL({worst:.1e})"
    print(f"\n{nm:16s}  [{verdict}]   (engine vs oracle, corners+midpoint)")
    frame_ix, voice_ix = [], []
    for s in range(6):
        role, band, ph = stage_role(cw["A"][s])
        if role == "pad": continue
        is_voice = role in ("PEAK", "DIPOLE") and 420 <= ph < 5000
        (voice_ix if is_voice else frame_ix).append(s)
        tag = "voice" if is_voice else "FRAME"
        cen = f"@{ph:5.0f}Hz" if ph else ""
        print(f"    S{s}: {tag:5s} {role:6s} {band:4s} {cen}")
    print(f"    => FRAME stages {frame_ix}   |   VOICE stages {voice_ix}")
