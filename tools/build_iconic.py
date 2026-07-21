#!/usr/bin/env python3
"""build_iconic.py - Declarative intent-based compiler for DF2 filters.

Reads a semantic JSON recipe and compiles it to a 240-byte .body240 artifact
using author_lanes.py, bypassing the need for raw pole/zero manual entry.
"""

import sys
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.author_lanes import body_to_packed_v1, AUTHORING_SR, CORNER_LABELS

NY = AUTHORING_SR / 2.0


def raw_from_words(words):
    """Flatten {corner: [[5 words] x 6 stages]} -> 240 little-endian u16 bytes.
    Corner byte order is CORNER_LABELS (== body240 CORNER_ORDER)."""
    import numpy as np
    flat = []
    for label in CORNER_LABELS:
        for row in words[label]:
            flat.extend(int(w) for w in row)
    if any(w < 0 or w > 0xFFFF for w in flat):
        raise ValueError("body240 words must be unsigned 16-bit values")
    return np.array(flat, dtype="<u2").tobytes()

def apply_motif(pole_hz, pole_r, next_pole_hz, motif):
    if motif == "trailing_zero" or motif == "trailing_zero_scoop":
        if next_pole_hz is None:
            zh = pole_hz * 1.6
        else:
            zh = math.sqrt(pole_hz * next_pole_hz)
        return {"pole_hz": pole_hz, "pole_r": pole_r, "zero_hz": zh, "zero_r": 0.70}
    elif motif == "leading_zero" or motif == "leading_zero_de-ess":
        return {"pole_hz": pole_hz, "pole_r": pole_r, "zero_hz": pole_hz * 1.6, "zero_r": 0.85}
    elif motif == "tooth" or motif == "tooth_cut":
        return {"pole_hz": pole_hz, "pole_r": pole_r, "zero_hz": pole_hz * 0.9, "zero_r": 0.95}
    elif motif == "high_cliff":
        return {"pole_hz": pole_hz, "pole_r": pole_r, "zero_hz": NY * 0.999, "zero_r": 1.0}
    elif motif == "locked_anchor":
        return {"pole_hz": 60.0, "pole_r": 0.92, "zero_hz": NY * 0.999, "zero_r": 1.0}
    elif motif == "identity_sentinel":
        # The new identity sentinel for parked/unused stages
        # encodes to DFFF FFFF DFFF FFFF DFFF
        return {"pole_hz": 0.0, "pole_r": 0.0, "zero_hz": 0.0, "zero_r": 0.0, "gain": 1.0}
    else:
        # Default: no zero
        return {"pole_hz": pole_hz, "pole_r": pole_r}

def compile_vowel(recipe):
    out_corners = {}
    for label in CORNER_LABELS:
        if label not in recipe["corners"]:
            raise ValueError(f"Recipe missing corner {label}")
        
        c = recipe["corners"][label]
        formants = c["formants"]
        motifs = c["motifs"]
        pole_r = c["pole_r"]
        
        lanes = []
        for i in range(5):
            hz = formants[i]
            motif = motifs[i]
            next_hz = formants[i+1] if i < 4 else None
            l = apply_motif(hz, pole_r, next_hz, motif)
            lanes.append(l)
            
        # Stage 6 is always the locked bass anchor for vowels
        lanes.append(apply_motif(60.0, 0.92, None, "locked_anchor"))
        
        # Apply global gain to normalize 60Hz to 0dB
        def mag(lanes_list, f):
            z = math.e**(-1j*2*math.pi*f/AUTHORING_SR)
            H = 1.0
            for l in lanes_list:
                wp = 2*math.pi*min(l["pole_hz"], NY*0.999)/AUTHORING_SR
                a1, a2 = -2*l["pole_r"]*math.cos(wp), l["pole_r"]**2
                wz = 2*math.pi*min(l.get("zero_hz", NY*0.999), NY*0.999)/AUTHORING_SR
                zr = l.get("zero_r", 0.0)
                b1, b2 = -2*zr*math.cos(wz), zr**2
                g = l.get("gain", 1.0)
                H *= (g + g*b1*z + g*b2*z*z)/(1+a1*z+a2*z*z)
            return abs(H)
            
        g = (1.0/max(1e-9, mag(lanes, 60.0)))**(1/6)
        for l in lanes:
            l["gain"] = g
            
        out_corners[label] = lanes
        
    return out_corners

def compile_flanger(recipe):
    out_corners = {}
    for label in CORNER_LABELS:
        if label not in recipe["corners"]:
            raise ValueError(f"Recipe missing corner {label}")
            
        c = recipe["corners"][label]
        notches = c["notches_hz"]
        peaks = c["peaks_hz"]
        notch_r = c["notch_r"]
        peak_r = c["peak_r"]
        global_gain = c.get("gain", 1.0)
        
        stages_used = len(notches)
        if stages_used > 6:
            raise ValueError("Cannot use more than 6 stages.")
            
        lanes = []
        for i in range(stages_used):
            lanes.append({
                "pole_hz": peaks[i],
                "pole_r": peak_r,
                "zero_hz": notches[i],
                "zero_r": notch_r,
                "gain": global_gain if i == 0 else 1.0 # apply global gain to first stage
            })
            
        # Pad remaining stages with identity_sentinel
        for _ in range(6 - stages_used):
            lanes.append(apply_motif(0.0, 0.0, None, "identity_sentinel"))
            
        out_corners[label] = lanes
        
    return out_corners

def compile_violent_eq(recipe):
    out_corners = {}
    for label in CORNER_LABELS:
        if label not in recipe["corners"]:
            raise ValueError(f"Recipe missing corner {label}")
            
        c = recipe["corners"][label]
        peaks = c["peaks"] # list of dicts: {"hz": 800, "r": 0.999, "motif": "high_cliff"}
        global_gain = c.get("gain", 1.0)
        
        stages_used = len(peaks)
        if stages_used > 6:
            raise ValueError("Cannot use more than 6 stages.")
            
        lanes = []
        for i, peak in enumerate(peaks):
            l = apply_motif(peak["hz"], peak["r"], None, peak.get("motif", "none"))
            if i == 0:
                l["gain"] = global_gain
            lanes.append(l)
            
        # Pad remaining stages with identity_sentinel
        for _ in range(6 - stages_used):
            lanes.append(apply_motif(0.0, 0.0, None, "identity_sentinel"))
            
        out_corners[label] = lanes
        
    return out_corners

def main():
    if len(sys.argv) < 2:
        print("Usage: python build_iconic.py <recipe.json>")
        sys.exit(1)
        
    recipe_path = Path(sys.argv[1])
    recipe = json.loads(recipe_path.read_text())
    
    name = recipe["name"]
    archetype = recipe.get("archetype", "vowel")
    
    print(f"Compiling {name} [{archetype}]...")
    
    if archetype == "vowel":
        corners = compile_vowel(recipe)
    elif archetype == "flanger":
        corners = compile_flanger(recipe)
    elif archetype == "violent_eq":
        corners = compile_violent_eq(recipe)
    else:
        print(f"Archetype {archetype} not implemented yet.")
        sys.exit(1)
        
    packed_v1 = body_to_packed_v1(name, corners)
    
    # Save the raw 240 bytes
    words_dict = packed_v1["corner"]
    from tools.author_lanes import lane_words
    
    raw_dict = {}
    for label, corner_data in words_dict.items():
        raw_dict[label] = corner_data["words"]
        
    body_bytes = raw_from_words(raw_dict)
    
    out_dir = ROOT / "plugin" / "presets" / "bodies"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.body240"
    out_path.write_bytes(body_bytes)
    
    print(f"Success! Wrote {len(body_bytes)} bytes to {out_path}")

if __name__ == "__main__":
    main()
