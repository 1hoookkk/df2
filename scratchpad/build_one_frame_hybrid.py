#!/usr/bin/env python3
"""One real frame-middle character preset, ALL numbers from real data:
- 4 poses = the 4 corners of a real ROM frame (S1/S6 rows kept verbatim).
- Middle S2-S5 = fit_corner_from_magnitude to REAL measured wav IR spectra.
Reuses the proven build_frame_specific_middles fit. Writes to dev/tmp only
(carries ROM bytes -> needs micro-shift before ship). Certify + bound<=27 + plot."""
import sys, struct, math
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(r"C:\Users\hooki\df2-workstation"); DF2 = Path(r"C:\Users\hooki\df2")
for p in [str(ROOT/"scratchpad"), str(ROOT/"tools"), str(DF2), str(DF2/"pyruntime")]:
    sys.path.insert(0, p)
import build_frame_specific_middles as bf   # reuse the proven fit + helpers
from pyruntime import trench_ffi
from pyruntime.packed_interp import coeffs_to_words

IRL = ROOT/"wav-source-library"/"measured_objects"/"ir_library"
# Real measured corners: violin (call/warm) -> cymbal (response/metal); damped/resonant on Q.
bf.WAVS = {
    "M0_Q0":     IRL/"violin"/"Violin Body Dampened.wav",
    "M100_Q0":   IRL/"cymbals"/"China Cymbal Contact Damped.wav",
    "M0_Q100":   IRL/"violin"/"Violin Body Resonant.wav",
    "M100_Q100": IRL/"cymbals"/"China Cymbal Contact Resonant.wav",
}
FRAME = ("talking_hedz", "P2k_013_talking_hedz.bin")
frame_bytes = (DF2/"ref"/"presets"/FRAME[1]).read_bytes()

print(f"frame = {FRAME[0]} (real ROM 4-corner) x violin->cymbal (real IRs)")
opt_middle = bf.build_residual_middle(frame_bytes)   # SLSQP fit to measured targets

# Splice: S1 + fitted S2-S5 + S6, per corner (exactly bf.main's assembly).
out = bytearray()
for ci in range(4):
    words = list(struct.unpack("<5H", bf.get_row(frame_bytes, ci, 0)))
    for si in range(4):
        words.extend(coeffs_to_words(*opt_middle[ci][si]))
    words.extend(struct.unpack("<5H", bf.get_row(frame_bytes, ci, 5)))
    out.extend(struct.pack("<30H", *words))
raw = bytes(out)

# Bound crown <= 27 with a per-stage SCALE trim (bf.main's logic).
EVAL = bf.FREQS; Z1 = bf.Z1; Z2 = bf.Z2
def crown_of(b):
    mx = -999
    for m in np.linspace(0,1,9):
        for q in np.linspace(0,1,9):
            pr = trench_ffi.packed_probe(b, float(m), float(q))
            mx = max(mx, float(np.max(bf.cascade_mag_db(pr["biquad"]))))
    return mx
cr = crown_of(raw); trim = 0.0
if cr > 27.0:
    trim = cr - 27.0
    ratio = 10.0 ** (-trim / (20.0*6.0))
    w = list(struct.unpack("<120H", raw))
    for r in range(24):
        w[r*5+4] = trench_ffi.encode(trench_ffi.decode(w[r*5+4]) * ratio)
    body = struct.pack("<120H", *w)
else:
    body = raw

# Certify on packed runtime.
un=nf=0; mr=0.0
for m in np.linspace(0,1,25):
    for q in np.linspace(0,1,25):
        pr=trench_ffi.packed_probe(body,float(m),float(q))
        un+=int(pr["unstable_mask"]); nf+=int(pr["nonfinite_mask"]); mr=max(mr,float(pr["max_pole_radius"]))
print(f"certify: {'PASS' if (un==0 and nf==0 and mr<1.0) else 'FAIL'} "
      f"unstable={un} maxR={mr:.4f} crown={crown_of(body):+.1f}dB trim={-trim:.1f}dB")

# Plot the 4 real poses.
plt.style.use("dark_background"); fig,ax=plt.subplots(figsize=(12,6),dpi=150)
poses=[(0,0,"M0/Q0  violin damp (CALL)","#00e5ff"),(1,0,"M100/Q0  cymbal damp (RESP)","#ff9100"),
       (0,1,"M0/Q100 violin reso","#7c4dff"),(1,1,"M100/Q100 cymbal reso","#ff1744")]
for m,q,lab,col in poses:
    pr=trench_ffi.packed_probe(body,m,q); ax.plot(EVAL, bf.cascade_mag_db(pr["biquad"]), col, lw=2, label=lab)
ax.set_xscale("log"); ax.set_xlim(40,16000); ax.set_ylim(-40,30)
ax.set_title("talking_hedz frame x violin->cymbal  (4 real poses, real IR middles)", color="w")
ax.set_xlabel("Hz"); ax.grid(True,alpha=0.3); ax.legend(fontsize=9)
OUT=ROOT/"dev"/"tmp"/"real_hybrids"; OUT.mkdir(parents=True, exist_ok=True)
plt.tight_layout(); plt.savefig(OUT/"talkinghedz_violin_cymbal.png",dpi=150,facecolor=fig.get_facecolor())
(OUT/"talkinghedz_violin_cymbal.body240").write_bytes(body)
print(f"wrote {OUT/'talkinghedz_violin_cymbal.body240'} + plot (dev/tmp; pre micro-shift)")
