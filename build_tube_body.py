"""Graft tube partials into talking_hedz frame (S0+S5 kept, S1-S4 = tube harmonics)."""
import json, subprocess, sys, math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"
LIB = ROOT / "preset_library" / "gold_templates"
OUT = ROOT / "preset_library" / "grafts"
OUT.mkdir(parents=True, exist_ok=True)

# ── talking_hedz frame ────────────────────────────────────────────────────
th = json.loads((LIB / "talking_hedz.geometry.json").read_text())

# ── Tube data from tube_resonances.json ───────────────────────────────────
# oo_50cm = [343, 686, 1029, 1372, 1715, 2058]
# oo_10cm = [1715, 3430, 5145, 6860, 8575] (5 partials)
# co_50cm = [172, 515, 858, 1201, 1544, 1887]
# co_25cm = [343, 1029, 1715, 2401, 3087]
# 
# Morph: oo_50cm (long, low) -> oo_10cm (short, bright)
# S1-S4 = 4 partials that scale with length

tube_long = [343, 1029, 1715, 2058]   # oo_50cm partials 1,3,5,6
tube_short = [1715, 3430, 6860, 8575]  # oo_10cm partials 1,3,5,6 (scaled ~5x)

# ── Build the graft ───────────────────────────────────────────────────────
graft = json.loads(json.dumps(th))

for ci in range(4):
    # Morph fraction across corners A→B (same as talking_hedz)
    morph = 0.0 if ci in (0, 2) else 1.0
    q = 0.0 if ci in (0, 1) else 1.0
    
    # Interpolate tube partials
    partials = [tl + (ts - tl) * morph for tl, ts in zip(tube_long, tube_short)]
    
    # Radius: broad at Q=0, sharp at Q=100
    r_base = 0.95 + 0.045 * q  # 0.95 -> 0.995
    
    for si, freq in zip([1, 2, 3, 4], partials):
        # Band-peak: pole at freq, zero ~7 semitones below (DC nulling)
        zero_below_hz = freq * (2.0 ** (-7.0 / 12.0))
        graft["corners"][ci][si] = {
            "pole_hz": round(freq, 1),
            "pole_r": round(r_base, 4),
            "zero_hz": round(zero_below_hz, 1),
            "zero_r": 0.5,
            "scale": 0.56,
        }

graft["name"] = "tube_oo_morph"

out_path = OUT / "tube_oo_morph.geometry.json"
with open(out_path, "w") as f:
    json.dump(graft, f, indent=1)

packed = OUT / "tube_oo_morph.body240"
r = subprocess.run(
    [str(COMPILER), str(out_path), str(packed)],
    capture_output=True, text=True, timeout=30,
)
output = (r.stdout or r.stderr or "").strip()
status = "PASS" if r.returncode == 0 else "FAIL"
print(f"tube_oo_morph: {status}")
print(f"  {output[:200]}")

# Show structure
for ci, cl in enumerate(["M0_Q0 (long)", "M100_Q0 (short)", "M0_Q100 (long+res)", "M100_Q100 (short+res)"]):
    print(f"\n  {cl}:")
    for si in range(6):
        s = graft["corners"][ci][si]
        marker = " [FRAME]" if si in (0, 5) else " [TUBE]"
        print(f"    S{si}: pole {s['pole_r']:.3f}@{s['pole_hz']:.0f}Hz  zero {s['zero_r']:.3f}@{s['zero_hz']:.0f}Hz{marker}")

# ── Also build metal bell body ────────────────────────────────────────────
# Bell partials at 500Hz prime: [250, 500, 600, 750, 1000, 1250, 1335, 1500, 2000]
# Pick 4 for S1-S4: 500, 750, 1000, 1250 (prime, quint, nominal, deciem)
graft2 = json.loads(json.dumps(th))
bell_partials = [500, 750, 1000, 1250]

for ci in range(4):
    q = 0.0 if ci in (0, 1) else 1.0
    r_base = 0.95 + 0.045 * q
    for si, freq in zip([1, 2, 3, 4], bell_partials):
        zero_below = freq * (2.0 ** (-7.0 / 12.0))
        graft2["corners"][ci][si] = {
            "pole_hz": round(freq, 1),
            "pole_r": round(r_base, 4),
            "zero_hz": round(zero_below, 1),
            "zero_r": 0.5,
            "scale": 0.56,
        }

graft2["name"] = "metal_bell_strike"
out2 = OUT / "metal_bell_strike.geometry.json"
with open(out2, "w") as f:
    json.dump(graft2, f, indent=1)
packed2 = OUT / "metal_bell_strike.body240"
r2 = subprocess.run([str(COMPILER), str(out2), str(packed2)], capture_output=True, text=True, timeout=30)
print(f"\nmetal_bell_strike: {'PASS' if r2.returncode == 0 else 'FAIL'}")
print(f"  {(r2.stdout or r2.stderr or '').strip()[:200]}")
