"""Stage cards: just the biquads + pole/zero per corner per stage. No abstraction."""
import sys, struct, math, json
from pathlib import Path
sys.path.insert(0, str(Path(r"C:\Users\hooki\df2-workstation")))
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad
import numpy as np

SR = 39062.5; PAD = (0xdfff,0xffff,0xdfff,0xffff,0xe000)
FACTORY = Path(r"C:\Users\hooki\df2\dev\tmp\factory")
OUT = Path(r"C:\Users\hooki\filter_index")

def corner_card(words5):
    """Return {words, coeffs, biquad, pole, zero} for one corner-stage."""
    w = tuple(words5)
    if w == PAD: return None
    coeffs = words_to_coeffs(w)
    b0,b1,b2,a1,a2 = kernel_to_biquad(coeffs)
    poles = np.roots([1.0,a1,a2])
    zeros = np.roots([b0,b1,b2])
    return {
        "words": list(w),
        "coeffs": [round(c,6) for c in coeffs],
        "biquad": [round(b0,6), round(b1,6), round(b2,6), round(a1,6), round(a2,6)],
        "pole": [{"r":round(abs(p),4), "hz":round(abs(math.atan2(p.imag,p.real))/(2*math.pi)*SR,1) if abs(p)>0 else 0} for p in poles],
        "zero": [{"r":round(abs(z),4), "hz":round(abs(math.atan2(z.imag,z.real))/(2*math.pi)*SR,1) if abs(z)>0 else 0} for z in zeros],
    }

CORNERS = ["A(M0R0)", "B(M100R0)", "C(M0R100)", "D(M100R100)"]
all_cards = []

for fp in sorted(FACTORY.glob("P2k_*.body240")):
    data = fp.read_bytes()
    w = struct.unpack("<120H", data)
    stages = []
    for si in range(6):
        corners = []
        for ci in range(4):
            w5 = tuple(w[(ci*6+si)*5:(ci*6+si)*5+5])
            card = corner_card(w5)
            corners.append(card)
        stages.append(corners)
    all_cards.append({"name": fp.stem, "stages": stages})

# Print talking hedz as demonstration
print("P2k_013 (Talking Hedz) — per stage per corner")
print("="*120)
for si in range(6):
    print(f"\nStage {si}:")
    for ci, cl in enumerate(CORNERS):
        c = all_cards[13]["stages"][si][ci]
        if c is None:
            print(f"  {cl:<20}: PAD"); continue
        p = c["pole"]; z = c["zero"]
        print(f"  {cl:<20}: words={c['words']}")
        print(f"  {'':20}  biquad=({','.join(str(round(x,4)) for x in c['biquad'])})")
        print(f"  {'':20}  pole={p[0]['r']:.4f}@{p[0]['hz']:.1f}Hz, {p[1]['r']:.4f}@{p[1]['hz']:.1f}Hz")
        print(f"  {'':20}  zero={z[0]['r']:.4f}@{z[0]['hz']:.1f}Hz, {z[1]['r']:.4f}@{z[1]['hz']:.1f}Hz")

with open(OUT / "stage_cards.json","w") as f:
    json.dump(all_cards, f, indent=1)
print(f"\nWrote {OUT / 'stage_cards.json'} ({len(all_cards)} bodies)")
