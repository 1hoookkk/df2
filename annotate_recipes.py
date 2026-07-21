"""Annotate each recipe with stage structure: which stages are frame (air/body) vs voice."""
from __future__ import annotations
import json, math, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad
from tools.filter_cli import load as _validate, RUNTIME_SR
import numpy as np

LIB = Path(r"C:\Users\hooki\preset_library")

SR = RUNTIME_SR

def stage_role(pole_hz, pole_r, zero_hz, zero_r):
    """Classify a single stage's role from its geometry."""
    if pole_r > 0.85:
        if pole_hz >= 6000: return "air"
        if pole_hz <= 500: return "body"
        return "voice"
    if zero_r > 0.95: return "notch"
    if pole_r > 0.3 and zero_r > 0.3 and abs(pole_hz - zero_hz) > 1.0:
        if max(pole_hz, zero_hz) / max(min(pole_hz, zero_hz), 1.0) > 2.0:
            return "shelf"
    return "flat"

def analyze_stage(stage):
    """Return role + label for one corner-stage."""
    p_hz = stage.get("pole_hz", 0)
    p_r = stage.get("pole_r", 0)
    z_hz = stage.get("zero_hz", 0)
    z_r = stage.get("zero_r", 0)
    r = stage_role(p_hz, p_r, z_hz, z_r)
    if r == "air": return r, f"air @{p_hz:.0f}Hz"
    if r == "body": return r, f"body @{p_hz:.0f}Hz"
    if r == "voice": return r, f"voice @{p_hz:.0f}Hz"
    if r == "notch": return r, f"notch @{z_hz:.0f}Hz"
    if r == "shelf": return r, f"shelf @{p_hz:.0f}Hz"
    return r, f"flat @{p_hz:.0f}Hz"

def is_fixed(corners, si, key="pole_hz"):
    """Check if a stage is fixed (same value) across all 4 corners."""
    vals = [c[si].get(key, 0) for c in corners]
    return max(vals) - min(vals) < 20

annotations = []
for recipe_dir in sorted(LIB.iterdir()):
    if not recipe_dir.is_dir():
        continue
    geo_path = recipe_dir / f"{recipe_dir.name}.geometry.json"
    if not geo_path.exists():
        continue
    
    try:
        d = json.loads(geo_path.read_text())
    except:
        continue
    
    if "decodedFrom" in d:
        continue  # skip decoded
    
    corners = d.get("corners", [])
    if len(corners) != 4:
        continue
    
    name = d.get("name", recipe_dir.name)
    
    # Analyze per-stage across corners
    stage_info = []
    for si in range(6):
        roles = []
        labels = []
        for ci in range(4):
            s = corners[ci][si]
            r, l = analyze_stage(s)
            roles.append(r)
            labels.append(l)
        
        # Dominant role
        role_counts = defaultdict(int)
        for r in roles:
            role_counts[r] += 1
        dom_role = max(role_counts, key=role_counts.get)
        
        # Is it fixed?
        fixed_pole = is_fixed(corners, si, "pole_hz")
        fixed_zero = is_fixed(corners, si, "zero_hz")
        
        # Get center frequency
        hzs = [corners[ci][si].get("pole_hz", 0) for ci in range(4)]
        avg_hz = round(sum(hzs) / 4, 0)
        
        stage_info.append({
            "stage": si,
            "role": dom_role,
            "hz": avg_hz,
            "fixed": fixed_pole,
            "corners": [{"role": roles[ci], "label": labels[ci]} for ci in range(4)],
        })
    
    # Determine frame vs voice
    frame_stages = [s for s in stage_info if s["role"] in ("air", "body")]
    voice_stages = [s for s in stage_info if s["role"] == "voice"]
    other_stages = [s for s in stage_info if s["role"] not in ("air", "body", "voice")]
    
    annotations.append({
        "name": name,
        "stage_structure": stage_info,
        "frame": [s["stage"] for s in frame_stages],
        "voice": [s["stage"] for s in voice_stages],
        "other": [s["stage"] for s in other_stages],
        "n_frame": len(frame_stages),
        "n_voice": len(voice_stages),
    })

# Output
print(f"{'Recipe':<45} {'S0':<25} {'S1':<25} {'S2':<25} {'S3':<25} {'S4':<25} {'S5':<25}")
print("-" * 195)
for a in sorted(annotations, key=lambda x: x["name"].lower()):
    cells = []
    for s in a["stage_structure"]:
        label = s["role"]
        if s["role"] in ("air", "body", "voice"):
            label += f" @{s['hz']:.0f}"
        if s["fixed"] and s["role"] in ("air", "body", "voice"):
            label += " ✦"
        cells.append(f"{label:<23}")
    print(f"{a['name']:<45} {' | '.join(cells)}")

# Save JSON
out_path = LIB / "stage_annotations.json"
with open(out_path, "w") as f:
    json.dump(annotations, f, indent=1)
print(f"\nWrote {out_path}")

# Count frame types
from collections import Counter
frame_counts = Counter()
for a in annotations:
    key = tuple(a["frame"])
    frame_counts[key] += 1

print(f"\nFrame patterns (air+body stages) across {len(annotations)} recipes:")
for pattern, count in sorted(frame_counts.items(), key=lambda x: -x[1])[:15]:
    stages = ", ".join(f"S{s}" for s in pattern) if pattern else "(none)"
    print(f"  [{stages}] x{count}")
