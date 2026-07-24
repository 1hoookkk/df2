"""Inspect measured actor bodies — per-stage pole/zero from corner M0_Q0."""
import struct, sys, math, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"C:\Users\hooki\df2")))
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad

BODIES = Path(r"C:\Users\hooki\df2-workstation\out\candidates_partial_20260720_2103\bodies")
SR = 39062.5
PAD = (0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000)

actors = [
    "ACTOR__Kalimba-Resonance-Full.body240",
    "ACTOR__Steel-Pan-Medium-Sweep-1.body240",
    "ACTOR__China-Cymbal-Contact-Resonant.body240",
    "ACTOR__Violin-Body-Resonant.body240",
    "ACTOR__middle-tunnel-4way-mono.body240",
    "ACTOR__mine-site1-2way-mono.body240",
    "ACTOR__Winter-Upright-Open-Sustain.body240",
    "ACTOR__Glockenspiel-Sweep-1.body240",
]

for aname in actors:
    fp = BODIES / aname
    if not fp.exists(): continue
    data = fp.read_bytes()
    w = struct.unpack("<120H", data)
    
    print(f"\n{aname}:")
    # Show corner M0_Q0 poles
    for si in range(6):
        w5 = tuple(w[(0*6+si)*5:(0*6+si)*5+5])
        if w5 == PAD:
            print(f"  S{si}: PAD"); continue
        coeffs = words_to_coeffs(w5)
        b0,b1,b2,a1,a2 = kernel_to_biquad(coeffs)
        poles = np.roots([1.0,a1,a2])
        zeros = np.roots([b0,b1,b2])
        pi = np.argmax(np.abs(poles))
        zi = np.argmax(np.abs(zeros))
        pr = float(abs(poles[pi]))
        zr = float(abs(zeros[zi]))
        pw = abs(math.atan2(poles[pi].imag, poles[pi].real))
        zw = abs(math.atan2(zeros[zi].imag, zeros[zi].real))
        phz = pw/(2*math.pi)*SR
        zhz = zw/(2*math.pi)*SR
        crown_db = 20*math.log10(abs(b0)) if abs(b0)>1e-12 else -120
        print(f"  S{si}: pole {pr:.3f}@{phz:.0f}Hz  zero {zr:.3f}@{zhz:.0f}Hz  b0={b0:.3f}  crown={crown_db:.1f}dB")
