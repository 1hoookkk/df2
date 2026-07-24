#!/usr/bin/env python3
"""build_typed_utils — workhorse utility presets via typed card compiler.

Typed cards: [type_id, fc_A, fc_B, q_lo, q_hi, gain_db, enabled]
  0=PEAK, 1=LOW_SHELF, 2=NOTCH, 3=LP, 4=HP, 5=BP, 6=HIGH_SHELF
  fc geom-interps between fc_A (M=0) and fc_B (M=100)
  Q geom-interps between q_lo (Q=0) and q_hi (Q=100)
  gain_db static per stage
"""
import hashlib, json, math
from pathlib import Path
import numpy as np
import struct

ROOT = Path(r"C:\Users\hooki\df2-workstation")
DF2 = Path(r"C:\Users\hooki\df2")
for p in [str(DF2 / "pyruntime"), str(DF2)]:
    import sys; sys.path.insert(0, p)

from pyruntime import trench_ffi

ENGINE_SR = 39062.5
NY = ENGINE_SR / 2
BODIES_DIR = ROOT / "plugin" / "presets" / "bodies"
EVAL_FREQS = np.logspace(math.log10(20), math.log10(20000), 1000)
Z1 = np.exp(-2j * np.pi * EVAL_FREQS / ENGINE_SR)
Z2 = Z1 * Z1

PEAK, LOW_SHELF, NOTCH, LP, HP, BP, HIGH_SHELF = 0, 1, 2, 3, 4, 5, 6

def card(type_id, fc_A, fc_B, q_lo, q_hi, gain_db, enabled=1.0):
    return [float(type_id), float(fc_A), float(fc_B), float(q_lo), float(q_hi), float(gain_db), float(enabled)]


PRESETS = []

# 1. Sweeping Peak
PRESETS.append(("sweep_peak", "Sweeping Peak — resonant peak sweeps across the spectrum",
    "peak frequency 200→8000 Hz", "peak sharpness (pole radius)", [
    card(PEAK, 200, 8000, 0.5, 6.0, 6.0),
    card(LOW_SHELF, 60, 60, 0.7, 0.7, -3.0),
    card(HIGH_SHELF, 16000, 16000, 0.7, 0.7, -3.0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
]))

# 2. Tilt EQ
PRESETS.append(("tilt_eq", "Tilt EQ — one-knob tonal balance",
    "dark → bright", "pivot resonance", [
    card(LOW_SHELF, 200, NY, 0.7, 2.0, 6.0),
    card(HIGH_SHELF, NY, 200, 0.7, 2.0, 6.0),
    card(PEAK, 600, 1200, 0.5, 4.0, 0),  # gentle moving peak for Q resonance
    card(LOW_SHELF, 60, 60, 0.5, 2.0, -3.0),
    card(HIGH_SHELF, 15000, 15000, 0.5, 2.0, -3.0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
]))

# 3. Peak/Shelf Morph (simplified EMU style)
PRESETS.append(("peak_shelf_morph", "Peak/Shelf Morph — dark LP to bright HS",
    "246 Hz LP → 4488 Hz HS", "Q = FilRes resonance at transition", [
    card(LP, 246, 4488, 0.7, 5.0, 0),
    card(PEAK, 246, 4488, 0.5, 6.0, 4.0),
    card(HIGH_SHELF, 3000, 6000, 0.7, 3.0, -2.0),
    card(LOW_SHELF, 100, 100, 0.7, 3.0, -6.0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
]))

# 4. Sweeping Bandpass (BP + resonance anchors)
PRESETS.append(("sweep_bp", "Sweeping Bandpass — center 800→8000 Hz",
    "center frequency up", "bandwidth narrow + center resonance", [
    card(BP, 800, 8000, 0.7, 6.0, 0),
    card(HIGH_SHELF, 14000, 14000, 0.7, 0.7, -12.0),
    card(LOW_SHELF, 60, 60, 0.7, 0.7, -12.0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
    card(PEAK, 10000, 10000, 0.5, 0.5, 0, 0),
]))


def pack_typed(cards):
    flat = [v for card in cards for v in card]
    return trench_ffi.compile_body_typed(flat)


def max_crown(body):
    max_cr = -999.0
    for m in np.linspace(0.0, 1.0, 13):
        for q in np.linspace(0.0, 1.0, 13):
            pr = trench_ffi.packed_probe(body, float(m), float(q))
            mag = np.ones_like(EVAL_FREQS, dtype=complex)
            for b0, b1, b2, a1, a2 in pr["biquad"]:
                mag *= (b0 + b1 * Z1 + b2 * Z2) / (1.0 + a1 * Z1 + a2 * Z2)
            cr = float(np.max(20 * np.log10(np.abs(mag) + 1e-12)))
            if cr > max_cr:
                max_cr = cr
    return max_cr


def certify(body):
    unstable = nonfinite = 0
    max_r = 0.0
    for m in np.linspace(0, 1, 25):
        for q_val in np.linspace(0, 1, 25):
            pr = trench_ffi.packed_probe(body, float(m), float(q_val))
            unstable += int(pr["unstable_mask"])
            nonfinite += int(pr["nonfinite_mask"])
            max_r = max(max_r, float(pr["max_pole_radius"]))
    crown = max_crown(body)
    return (unstable == 0 and nonfinite == 0 and max_r < 1.0 and crown <= 27.0,
            unstable, max_r, crown)


def main():
    for slug, title, ax_x, ax_y, cards in PRESETS:
        print(f"\n{'='*60}")
        print(f"Building: {slug}  —  {title}")
        print(f"{'='*60}")

        try:
            body = pack_typed(cards)
        except Exception as e:
            print(f"  COMPILE FAILED: {e}")
            continue
        print(f"  compiled to 240 bytes")

        ok, unstable, max_r, crown = certify(body)
        print(f"  certify: {'PASS' if ok else 'FAIL'} unstable={unstable} maxR={max_r:.4f} crown={crown:+.1f} dB")
        if not ok:
            print(f"  SKIPPED (does not certify)")
            continue

        out_dir = ROOT / "dev" / "tmp" / "utility_presets"
        out_dir.mkdir(parents=True, exist_ok=True)
        body_path = out_dir / f"{slug}.body240"
        body_path.write_bytes(body)
        plugin_path = BODIES_DIR / f"{slug}.body240"
        plugin_path.write_bytes(body)
        print(f"  body -> {plugin_path}")

        sha = hashlib.sha256(body).hexdigest()
        man = {
            "slug": slug, "title": title,
            "axis_morph": ax_x, "axis_q": ax_y,
            "method": "compile_body_typed", "cards": cards,
            "sha256": sha, "crown_db": round(crown, 2),
        }
        man_path = out_dir / f"{slug}.manifest.json"
        man_path.write_text(json.dumps(man, indent=2) + "\n")

        for cl, m, q in [('M0_Q0',0,0),('M100_Q0',1,0),('M0_Q100',0,1),('M100_Q100',1,1)]:
            pr = trench_ffi.packed_probe(body, m, q)
            mag = np.ones_like(EVAL_FREQS, dtype=complex)
            for b0,b1,b2,a1,a2 in pr['biquad']:
                mag *= (b0 + b1*Z1 + b2*Z2) / (1.0 + a1*Z1 + a2*Z2)
            db = 20*np.log10(np.abs(mag) + 1e-12)
            pk = np.argmax(db)
            print(f'  {cl}: median={np.median(db):+.1f} peak={db.max():+.1f} @ {EVAL_FREQS[pk]:.0f} Hz')

        # Q sweep at M=0.5
        print(f'  Q sweep at M=0.5:')
        for qv in [0, 0.33, 0.67, 1.0]:
            pr = trench_ffi.packed_probe(body, 0.5, qv)
            mag = np.ones_like(EVAL_FREQS, dtype=complex)
            for b0,b1,b2,a1,a2 in pr['biquad']:
                mag *= (b0 + b1*Z1 + b2*Z2) / (1.0 + a1*Z1 + a2*Z2)
            db = 20*np.log10(np.abs(mag) + 1e-12)
            pk = np.argmax(db)
            print(f'    Q{qv:.2f}: median={np.median(db):+.1f} peak={db.max():+.1f} @ {EVAL_FREQS[pk]:.0f} Hz')

        # M sweep at Q=0
        print(f'  M sweep at Q=0:')
        for mv in [0, 0.25, 0.5, 0.75, 1.0]:
            pr = trench_ffi.packed_probe(body, mv, 0)
            mag = np.ones_like(EVAL_FREQS, dtype=complex)
            for b0,b1,b2,a1,a2 in pr['biquad']:
                mag *= (b0 + b1*Z1 + b2*Z2) / (1.0 + a1*Z1 + a2*Z2)
            db = 20*np.log10(np.abs(mag) + 1e-12)
            a30 = db[np.argmin(np.abs(EVAL_FREQS-30))]
            a1k = db[np.argmin(np.abs(EVAL_FREQS-1000))]
            a10k = db[np.argmin(np.abs(EVAL_FREQS-10000))]
            print(f'    M{mv:.2f}: 30Hz={a30:+.1f} 1kHz={a1k:+.1f} 10kHz={a10k:+.1f}')

        print(f"  Done.\n")


if __name__ == "__main__":
    main()
