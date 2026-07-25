"""Author the Filters category on the E-mu PEAK/SHELF MORPH model
(Dillusion tutorial), USING THE FULL 6-STAGE CASCADE for fat, steep filters.

Each frame = a staggered-Butterworth cascade at FREQ (corner lands at FREQ),
zeros placed by SHELF (Nyquist=LP, DC=HP, none=BP), PEAK = frame level. Two
frames only (morph A->B); Q is RUNTIME resonance. Every number computed;
compiled by the real body-from-geometry, response verified through the decode.
"""
import json, math, subprocess, struct, sys
from pathlib import Path

ROOT = Path(r"C:\Users\hooki\df2-workstation")
sys.path.insert(0, str(ROOT))
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad

SR = 39062.5
FMIN, FMAX = 25.0, SR * 0.49
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"
OUTDIR = Path(r"C:\Users\hooki\Documents\TRENCH\bodies\Filters")
OUTDIR.mkdir(parents=True, exist_ok=True)

# Butterworth section Q's per cascade order (each section = 2 poles).
BUTTER_Q = {
    3: [0.5176, 0.7071, 1.9319],                       # 6-pole  / 36 dB/oct
    4: [0.5098, 0.6013, 0.8999, 2.5629],               # 8-pole  / 48 dB/oct
    5: [0.5062, 0.5612, 0.7071, 1.1013, 3.1962],       # 10-pole / 60 dB/oct
}


def _biq_mag(pole_hz, pole_r, zero_hz, zero_r, scale, f):
    wp = 2 * math.pi * pole_hz / SR; wz = 2 * math.pi * zero_hz / SR
    w = 2 * math.pi * f / SR; z1 = complex(math.cos(-w), math.sin(-w)); z2 = z1 * z1
    num = 1 - 2 * zero_r * math.cos(wz) * z1 + zero_r * zero_r * z2
    den = 1 - 2 * pole_r * math.cos(wp) * z1 + pole_r * pole_r * z2
    return scale * abs(num / den)


def section(freq, shelf, qbutter):
    """One Butterworth cascade section at freq, tilted by SHELF, unity passband."""
    freq = min(max(freq, FMIN), FMAX)
    pole_r = min(0.9985, max(0.25, 1.0 - math.pi * freq / (qbutter * SR)))
    t = max(-1.0, min(1.0, shelf / 64.0))
    zero_r = 0.985 * abs(t)
    zero_hz = FMAX if t < 0 else FMIN
    zhz = zero_hz if abs(t) > 1e-6 else 1.0
    passf = FMIN if t < 0 else (FMAX * 0.97 if t > 0 else freq)
    scale = 1.0 / max(_biq_mag(freq, pole_r, zhz, zero_r, 1.0, passf), 1e-9)
    return {"pole_hz": round(freq, 3), "pole_r": round(pole_r, 6),
            "zero_hz": round(zhz, 3), "zero_r": round(zero_r, 6),
            "scale": round(scale, 8)}


def idle():
    return {"pole_hz": 1.0, "pole_r": 0.0, "zero_hz": 1.0, "zero_r": 0.0, "scale": 1.0}


def frame(freq, shelf, peak_db, order):
    secs = [section(freq, shelf, q) for q in BUTTER_Q[order]]
    secs[0]["scale"] = round(secs[0]["scale"] * 10.0 ** (peak_db / 20.0), 8)  # frame level
    return secs + [idle() for _ in range(6 - order)]


def build(name, lo, hi, order=3):
    fa = frame(*lo, order); fb = frame(*hi, order)
    corners = [fa, fb, fa, fb]   # two frames; Q0==Q100 (Q is runtime)
    gpath = OUTDIR / f"{name}.geometry.json"
    gpath.write_text(json.dumps({"name": name, "corners": corners}, indent=1))
    bpath = OUTDIR / f"{name}.body240"
    r = subprocess.run([str(COMPILER), str(gpath), str(bpath)], capture_output=True, text=True, timeout=30)
    ok = r.returncode == 0
    print(f"{name:16s}: {'PASS' if ok else 'FAIL'}  {(r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else ''}")
    return bpath if ok else None


def response(bpath, corner, freqs):
    words = struct.unpack("<120H", bpath.read_bytes()); base = corner * 30
    biqs = [kernel_to_biquad(words_to_coeffs(words[base+s*5:base+s*5+5])) for s in range(6)]
    out = []
    for f in freqs:
        w = 2*math.pi*f/SR; z1 = complex(math.cos(-w), math.sin(-w)); z2 = z1*z1
        h = 1+0j
        for b0, b1, b2, a1, a2 in biqs:
            h *= (b0 + b1*z1 + b2*z2) / (1 + a1*z1 + a2*z2)
        out.append(20*math.log10(abs(h)+1e-12))
    return out


# name -> (low frame, high frame, cascade order)
PRESETS = {
    "clean_lowpass":  ((300, -60, 0),   (6000, -60, 0),   3),
    "clean_bandpass": ((350,   0, 0),   (5000,   0, 0),   3),
    "clean_highpass": ((250, +60, 0),   (5000, +60, 0),   3),
    "lp_to_hp":       ((320, -60, 0),   (3800, +60, 0),   3),
    "reece_dnb":      ((246, -50, -24), (4488, +30, 1.5), 4),   # fat DnB filter
    "twin_scream":    ((180, -55, -6),  (2600, +40, 6),   5),   # steepest / wildest
}

if __name__ == "__main__":
    import numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    built = {n: build(n, lo, hi, o) for n, (lo, hi, o) in PRESETS.items()}
    freqs = list(np.logspace(np.log10(30), np.log10(19000), 300))
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), dpi=100)
    for ax, (name, (lo, hi, o)) in zip(axes.flat, PRESETS.items()):
        bp = built[name]
        if not bp: ax.set_title(f"{name} FAIL"); continue
        ax.semilogx(freqs, response(bp, 0, freqs), color="#4a9", lw=1.9, label="frame A")
        ax.semilogx(freqs, response(bp, 1, freqs), color="#c33", lw=1.9, label="frame B")
        ax.set_title(f"{name}  ({2*o}-pole)"); ax.set_xlim(30, 19000); ax.set_ylim(-60, 18)
        ax.grid(True, alpha=0.3, which="both"); ax.legend(fontsize=8, loc="lower left")
    out = r"C:\WINDOWS\TEMP\claude\C--Users-hooki-df2-workstation\ca68cbf1-ca63-4dc7-b83e-125e3a6c6763\scratchpad\filter_roster.png"
    plt.tight_layout(); plt.savefig(out); print("saved", out)
