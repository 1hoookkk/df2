"""Is the compiler spine wired correctly? End-to-end checks, PASS/FAIL with numbers.

C1 catalogue paths resolve
C2 emit path: decode -> re-encode (coeffs_to_words) -> reassemble -> engine == original
C3 sentinel/phantom stage plays as passthrough through the engine
C4 author-from-frequency: (fc, zero_offset) -> kernel -> words -> engine lands on target
"""
from __future__ import annotations
import ctypes as C, struct, json, os, glob, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyruntime.packed_interp import (words_to_coeffs, coeffs_to_words, kernel_to_biquad)

H = os.path.expanduser("~"); SR = 39062.5; PAD = (0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000)
F = np.geomspace(30, 19000, 1500)
DLL = os.path.join(ROOT, "target", "release", "trench_core.dll")
lib = C.CDLL(DLL)
lib.trench_packed_probe.restype = C.c_int32
lib.trench_packed_probe.argtypes = [C.c_char_p, C.c_size_t, C.c_double, C.c_double,
    C.POINTER(C.c_double), C.POINTER(C.c_double), C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]


def eng(body, m, q):
    out = (C.c_double*30)(); a = C.c_double(); b = C.c_uint32(); c = C.c_uint32()
    lib.trench_packed_probe(body, 240, C.c_double(m), C.c_double(q), out, C.byref(a), C.byref(b), C.byref(c))
    return np.array(out).reshape(6, 5)


def resp(biqs):
    z = np.exp(-1j*2*np.pi*F/SR); t = np.zeros_like(F)
    for b0, b1, b2, a1, a2 in biqs:
        t += 20*np.log10(np.abs(b0+b1*z+b2*z*z)/np.abs(1+a1*z+a2*z*z)+1e-9)
    return t


def biquad_to_kernel(b0, b1, b2, a1, a2):
    c4 = b0
    return (b1/c4 + 2.0, 1.0 - b2/c4, a1 + 2.0, 1.0 - a2, c4)


def hz(root): return abs(np.angle(root))/(2*np.pi)*SR

results = []

# C1 — catalogue paths resolve
cat = json.load(open(os.path.join(ROOT, "catalogue.json")))
paths = [f["path"] for f in cat["frames"]] + cat["recipes"]["family_laws"] + [cat["recipes"]["recipe_index"]]
for v in cat["voice_tables"].values():
    paths += v if isinstance(v, list) else [v]
paths += [cat["fundamentals"]["runtime_blocks"], cat["fundamentals"]["decoded_manifest"], cat["wav_sources"]["root"]]
missing = [p for p in paths if not os.path.exists(os.path.join(H, p))]
results.append(("C1 catalogue paths resolve", not missing, f"{len(paths)-len(missing)}/{len(paths)} exist" + (f"  MISSING {missing[:3]}" if missing else "")))

# C2 — emit path round-trip on a real gold body
gp = glob.glob(rf"{H}\surface-forge\out\foundry\ROM_GOLD\P2k_013_talking_hedz.body240")[0]
orig = open(gp, "rb").read()
w = struct.unpack("<120H", orig)
repacked = bytearray()
for i in range(24):
    words = w[i*5:i*5+5]
    if words == PAD:
        newwords = PAD
    else:
        newwords = coeffs_to_words(*words_to_coeffs(words))
    for x in newwords:
        repacked += struct.pack("<H", x)
reasm = bytes(repacked)
errs = []
for m, q in [(0.,0.), (1.,0.), (0.,1.), (1.,1.), (0.5,0.5)]:
    errs.append(float(np.max(np.abs(resp(eng(orig, m, q)) - resp(eng(reasm, m, q))))))
c2err = max(errs)
results.append(("C2 emit round-trip (pack->assemble->engine)", c2err < 0.75, f"max resp err {c2err:.3f} dB across corners+midpoint"))

# C3 — sentinel passthrough (a body of all sentinels -> flat)
allpad = b"".join(struct.pack("<H", x) for _ in range(24) for x in PAD)
c3 = float(np.max(np.abs(resp(eng(allpad, 0.5, 0.5)))))
results.append(("C3 sentinel/phantom = passthrough", c3 < 0.5, f"all-sentinel body flat to {c3:.4f} dB"))

# C4 — author from frequency: pole@fc, zero@fc*2^offset -> words -> engine lands on target
fc, zoff, rp, rz = 637.0, 0.075, 0.98, 0.9
wp, wz = 2*np.pi*fc/SR, 2*np.pi*(fc*2**zoff)/SR
biq = (1.0, -2*rz*np.cos(wz), rz**2, -2*rp*np.cos(wp), rp**2)  # b0,b1,b2,a1,a2
words = coeffs_to_words(*biquad_to_kernel(*biq))
body = bytearray()
for s in range(6):
    ww = words if s == 0 else PAD
    for x in ww: body += struct.pack("<H", x)
got = eng(bytes(body), 0.0, 0.0)[0]
gp_hz = hz(np.roots([1, got[3], got[4]])[np.argmax(np.abs(np.roots([1, got[3], got[4]])))])
gz_hz = hz(np.roots([got[0], got[1], got[2]])[np.argmax(np.abs(np.roots([got[0], got[1], got[2]])))])
tgt_z = fc*2**zoff
c4ok = abs(gp_hz-fc) < 15 and abs(gz_hz-tgt_z) < 25
results.append(("C4 author-from-freq lands on target", c4ok, f"pole {gp_hz:.0f}Hz (want {fc:.0f}), zero {gz_hz:.0f}Hz (want {tgt_z:.0f})"))

print("\nCOMPILER SPINE VERIFICATION")
print("="*70)
allpass = True
for name, ok, detail in results:
    allpass &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}]  {name}\n           {detail}")
print("="*70)
print("ALL WIRED" if allpass else "NOT READY — see FAILs above")
