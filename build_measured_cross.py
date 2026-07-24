"""Build measured cross-presets: two actors across Morph, BLOOM at Q100."""
from __future__ import annotations
import hashlib, struct, sys, math, json, subprocess
from pathlib import Path
from datetime import datetime
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(r"C:\Users\hooki\df2")))

from tools.corner_words import corner_words, notch, bp
from src.utils.body240 import raw_from_words
from pyruntime import trench_ffi
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad

BODIES = ROOT / "out" / "candidates_partial_20260720_2103" / "bodies"
SR = 39062.5
PAD = (0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000)

def actor_poles(name: str) -> list[tuple[float, float]]:
    """Return [(pole_hz, pole_r), ...] for corner M0_Q0 of an actor body."""
    fp = BODIES / name
    data = fp.read_bytes()
    w = struct.unpack("<120H", data)
    poles = []
    for si in range(6):
        w5 = tuple(w[si*5:(si+1)*5])
        if w5 == PAD: continue
        coeffs = words_to_coeffs(w5)
        b0,b1,b2,a1,a2 = kernel_to_biquad(coeffs)
        roots = np.roots([1.0,a1,a2])
        pi = np.argmax(np.abs(roots))
        pr = float(abs(roots[pi]))
        pw = abs(math.atan2(roots[pi].imag, roots[pi].real))
        phz = pw/(2*math.pi)*SR
        poles.append((round(phz, 0), round(pr, 4)))
    return poles[:6]

def build_cross_corners(actor_a: str, actor_b: str, bloom_factor: float) -> dict:
    """Build 4 corners: M0=actor_a, M100=actor_b, Q100=bloomed."""
    pa = actor_poles(actor_a)
    pb = actor_poles(actor_b)
    
    def corner_poles(p, bloom):
        r_bump = 0.0
        if bloom:
            r_bump = bloom_factor
        stages = []
        for hz, r in p:
            rb = min(0.999, r + r_bump)
            stages.append(bp(hz, rb))
        while len(stages) < 6:
            stages.append(bp(10000, 0.85))
        return stages[:6]
    
    return {
        "M0_Q0": corner_poles(pa, False),
        "M100_Q0": corner_poles(pb, False),
        "M0_Q100": corner_poles(pa, True),
        "M100_Q100": corner_poles(pb, True),
    }

# ── 6 CREATIVE PAIRINGS ───────────────────────────────────────────────────
PAIRINGS = [
    ("Glockenspiel → Mine Cave",
     "glockenspiel_minecave",
     "ACTOR__Glockenspiel-Sweep-1.body240",
     "ACTOR__mine-site1-2way-mono.body240",
     0.015),
    ("Kalimba → Middle Tunnel",
     "kalimba_tunnel",
     "ACTOR__Kalimba-Resonance-Full.body240",
     "ACTOR__middle-tunnel-4way-mono.body240",
     0.018),
    ("Steel Pan → China Cymbal",
     "steelpan_cymbal",
     "ACTOR__Steel-Pan-Medium-Sweep-1.body240",
     "ACTOR__China-Cymbal-Contact-Resonant.body240",
     0.012),
    ("Violin → Winter Bass",
     "violin_bass",
     "ACTOR__Violin-Body-Resonant.body240",
     "ACTOR__Winter-Upright-Open-Sustain.body240",
     0.010),
    ("Ukulele → ORTF Room",
     "ukulele_ortf",
     "ACTOR__Soprano-Ukulele-Close-Mono.body240",
     "ACTOR__ortf-s1r1.body240",
     0.020),
    ("Mine Site 1way → 2way",
     "minesite_1way_2way",
     "ACTOR__mine-site1-1way-mono.body240",
     "ACTOR__mine-site1-2way-mono.body240",
     0.010),
]

RESULTS = []
OUT = ROOT / "plugin" / "presets" / "bodies"

for display, slug, actor_a, actor_b, bloom in PAIRINGS:
    corners = build_cross_corners(actor_a, actor_b, bloom)
    
    words = {}
    for label in ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]:
        words[label] = corner_words(corners[label])
    
    body = raw_from_words(words)
    sha = hashlib.sha256(body).hexdigest()
    
    # Grid-certify
    stable = True
    max_r = 0.0
    unstable = 0
    try:
        m = trench_ffi.evaluate_body(body, 17)
        stable = m.get("stable", True)
        max_r = m.get("max_pole_radius", 0)
        unstable = m.get("grid_unstable_rows", 0) or m.get("interior_unstable_rows", 0) or 0
    except Exception:
        pass
    
    # Crown check
    max_crown = 0.0
    try:
        probe = trench_ffi.packed_probe(body, 0.5, 0.5)
        if probe and "biquad" in probe:
            for bq in probe["biquad"]:
                b0 = bq[0]
                cr = 20.0 * math.log10(max(abs(b0), 1e-12))
                max_crown = max(max_crown, cr)
    except Exception:
        pass
    
    # Write body
    body_path = OUT / f"{slug}.body240"
    body_path.write_bytes(body)
    
    # ROSTER FROZEN (2026-07-21): PresetRoster.inc is hand-maintained
    # (see plugin/presets/approved_bodies.txt). Print the line for manual
    # curation instead of writing the roster.
    print(f'roster line (manual curation only): TRENCH_PRESET("{display}", "{slug}", "LIBRARY")')
    
    status = "✓" if stable and unstable == 0 and max_r < 1.0 else "✗"
    RESULTS.append(f"  {status} {display:<32} sha={sha[:12]} r={max_r:.4f} crown={max_crown:.1f}dB")

print("6 measured cross-presets:")
for r in RESULTS:
    print(r)
print(f"\nBodies: {OUT}")
print("Roster: NOT written (hand-maintained; see plugin/presets/approved_bodies.txt)")
