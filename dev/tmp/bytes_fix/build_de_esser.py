"""DE-ESSER — the Q axis IS the de-ess.

Three true notches at the sibilance centers (5 / 7 / 9 kHz, his numbers),
air (12 k+) untouched. Q0 pose = exact pole-zero cancellation (flat, H=1);
Q100 pose = zeros pushed to the unit circle (acoustic black holes). Motion
CHOP (React 0.85) drives Q from the input envelope: an S opens the notches
in one control block (32 smp @ 39062.5 = 0.82 ms), then they cancel back
to flat. M0 == M100 (static body — MORPH is not the actor here).

Gates: Q0 flatness, notch depth + air preservation at Q100, 25x25 certify
(inside body-from-geometry), packed-runtime plots.
"""
from __future__ import annotations
import json, math, subprocess, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path("C:/Users/hooki/df2")
WS = Path("C:/Users/hooki/df2-workstation")
OUT = WS / "dev/tmp/bytes_fix"
BIN = WS / "target/release/body-from-geometry.exe"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "pyruntime"))
sys.path.insert(0, str(OUT))
from fix_bodies import FREQS
from build_all_archetypes import packed_db

SR = 39062.5
CENTERS = [5000.0, 7000.0, 9000.0]
POLE_R = 0.95  # notch width: BW ~ (1-r)*SR/pi ~ 620 Hz

IDENT = {"pole_hz": 0.0, "pole_r": 0.0, "zero_hz": 0.0, "zero_r": 0.0, "scale": 1.0}


def dc_scale(hz, rz, rp):
    """scale so H(DC)=1: |A(1)|/|B(1)| for zeros/poles at (hz, r)."""
    w = 2 * math.pi * hz / SR
    a = 1 - 2 * rp * math.cos(w) + rp * rp
    b = 1 - 2 * rz * math.cos(w) + rz * rz
    return a / b


def corner(deess):
    stages = []
    for hz in CENTERS:
        rz = 1.0 if deess else POLE_R
        stages.append({"pole_hz": hz, "pole_r": POLE_R, "zero_hz": hz,
                       "zero_r": rz, "scale": dc_scale(hz, rz, POLE_R) if deess else 1.0})
    stages += [dict(IDENT)] * 3
    return stages


geo = {"name": "DEMO_de_esser",
       "corners": [corner(False), corner(False), corner(True), corner(True)]}
gpath = OUT / "de_esser.geometry.json"
gpath.write_text(json.dumps(geo, indent=1))
bpath = OUT / "DEMO_de_esser.body240"
print(subprocess.run([str(BIN), str(gpath), str(bpath)],
                     capture_output=True, text=True).stdout.strip())
body = bpath.read_bytes()

# ---- gates on the PACKED runtime ----
fig, ax = plt.subplots(figsize=(12, 6))
fails = []
for q, color in [(0.0, "0.6"), (0.25, "#7fb"), (0.5, "#3a8"), (0.75, "#186"), (1.0, "#d33")]:
    db = packed_db(body, 0.0, q)
    ax.semilogx(FREQS, db, color=color, lw=2 if q in (0, 1) else 1, label=f"Q {q:g}")
    if q == 0.0:
        flat = np.max(np.abs(db))
        print(f"Q0 flatness: max |dB| = {flat:.4f}")
        if flat > 0.1: fails.append(f"Q0 not flat ({flat:.3f} dB)")
    if q == 1.0:
        for hz in CENTERS:
            d = db[np.argmin(np.abs(FREQS - hz))]
            print(f"Q100 depth at {hz:.0f} Hz: {d:.1f} dB")
            if d > -12: fails.append(f"shallow notch at {hz:.0f} ({d:.1f} dB)")
        air = db[FREQS >= 12000]
        print(f"Q100 air (12k+): {air.min():+.2f}..{air.max():+.2f} dB")
        if np.max(np.abs(air)) > 1.0: fails.append(f"air disturbed ({np.max(np.abs(air)):.2f} dB)")
        low = db[FREQS <= 3000]
        print(f"Q100 body (<3k): {low.min():+.2f}..{low.max():+.2f} dB")
# morph must be inert (static body)
inert = np.max(np.abs(packed_db(body, 1.0, 1.0) - packed_db(body, 0.0, 1.0)))
print(f"morph inertness: max delta {inert:.4f} dB")
if inert > 0.05: fails.append(f"morph not inert ({inert:.3f} dB)")

for hz in CENTERS: ax.axvline(hz, color="r", ls=":", alpha=0.4)
ax.axvspan(12000, 19200, color="g", alpha=0.06)
ax.set_xlim(30, 19200); ax.set_ylim(-42, 6)
ax.grid(True, which="both", alpha=0.3)
ax.set_xlabel("Hz"); ax.set_ylabel("dB")
ax.set_title("DE-ESSER — packed runtime, Q sweep (flat -> black holes at 5/7/9 kHz, air intact)")
ax.legend()
fig.tight_layout(); fig.savefig(OUT / "de_esser_tf.png", dpi=110)
print(f"plot -> {OUT / 'de_esser_tf.png'}")
print("GATES:", "ALL PASS" if not fails else f"FAIL: {fails}")
