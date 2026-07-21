"""Graft measured biquads into talking_hedz frame (S0+S5 kept, S1-S4 replaced)."""
import json, subprocess, sys
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"

LIB = ROOT / "preset_library" / "gold_templates"
OUT = ROOT / "preset_library" / "grafts"
OUT.mkdir(parents=True, exist_ok=True)

# Load talking_hedz template (the frame)
th = json.loads((LIB / "talking_hedz.geometry.json").read_text())

# Load a measured fit — body-parity-probe-s1-14-ach-x (German /x/ as in "ach")
# This is in the recipe library with the full 6-stage geometry
measured_name = "body-parity-probe-s1-14-ach-x.measured.fit"
measured_path = None
for p in [ROOT / "dev" / "tmp" / "bytes_fix", ROOT / "dev" / "tmp"]:
    candidate = p / f"{measured_name}.geometry.json"
    if candidate.exists():
        measured_path = candidate
        break

if not measured_path:
    # Look in the full harvest temp
    measured_path = ROOT / "dev" / "tmp" / "bytes_fix" / "body-parity-probe-s1-14-ach-x.measured.fit.geometry.json"
    if not measured_path.exists():
        print("Measured fit not found, using formant table instead")
        # Build from formant table instead
        measured = None

if measured_path and measured_path.exists():
    measured = json.loads(measured_path.read_text())
    print(f"Using measured fit: {measured_path.name}")
    print(f"  Stages: S0={measured['corners'][0][0]['pole_hz']:.0f}Hz  S1={measured['corners'][0][1]['pole_hz']:.0f}Hz  "
          f"S2={measured['corners'][0][2]['pole_hz']:.0f}Hz  S3={measured['corners'][0][3]['pole_hz']:.0f}Hz  "
          f"S4={measured['corners'][0][4]['pole_hz']:.0f}Hz  S5={measured['corners'][0][5]['pole_hz']:.0f}Hz")
else:
    print("No measured fit found, building demo from vowel table")
    measured = None

# Graft: keep talking_hedz S0 and S5, replace S1-S4 with measured body's S1-S4
graft = json.loads(th["name"]) if False else json.loads(json.dumps(th))

for ci in range(4):
    # Keep S0 and S5 from talking_hedz
    # Replace S1, S2, S3, S4 with measured data
    if measured:
        for si in [1, 2, 3, 4]:
            graft["corners"][ci][si] = json.loads(json.dumps(measured["corners"][ci][si]))
    else:
        # Build from Klatt table: /a/ vowel (bard)
        import math
        f1, f2, f3, f4 = 700, 1220, 2600, 3300
        # Simple resonator stages
        graft["corners"][ci][1] = {"pole_hz": f1, "pole_r": 0.98, "zero_hz": max(f1-200, 50), "zero_r": 0.5, "scale": 0.5}
        graft["corners"][ci][2] = {"pole_hz": f2, "pole_r": 0.97, "zero_hz": max(f2-300, 50), "zero_r": 0.5, "scale": 0.5}
        graft["corners"][ci][3] = {"pole_hz": f3, "pole_r": 0.96, "zero_hz": max(f3-400, 50), "zero_r": 0.5, "scale": 0.5}
        graft["corners"][ci][4] = {"pole_hz": f4, "pole_r": 0.94, "zero_hz": max(f4-500, 50), "zero_r": 0.5, "scale": 0.5}

graft["name"] = "talking_hedz_ach_graft"

# Write and compile
out_path = OUT / "talking_hedz_ach_graft.geometry.json"
with open(out_path, "w") as f:
    json.dump(graft, f, indent=1)

packed = OUT / "talking_hedz_ach_graft.body240"
r = subprocess.run(
    [str(COMPILER), str(out_path), str(packed)],
    capture_output=True, text=True, timeout=30,
)
output = (r.stdout or r.stderr or "").strip()
print(f"\nCompiler: {'PASS' if r.returncode == 0 else 'FAIL'}")
print(f"Output: {output[:200] if output else '(none)'}")

# Also print what we did
print(f"\nGraft result: talking_hedz_ach_graft")
print(f"  S0 (air): kept from talking_hedz")
for ci, cl in enumerate(["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]):
    print(f"  {cl}:")
    for si in range(6):
        s = graft["corners"][ci][si]
        marker = " [KEPT]" if si in (0, 5) else " [GRAFTED]"
        print(f"    S{si}: pole {s['pole_r']:.3f}@{s['pole_hz']:.0f}Hz  zero {s['zero_r']:.3f}@{s['zero_hz']:.0f}Hz{marker}")
