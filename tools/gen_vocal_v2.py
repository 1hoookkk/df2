"""Klatt-pinned direct-biquad vocal bodies — razor radii, anti-formant zeros,
AGC-engagement peaks. No factorizer in the path, no smoothing. Each body is a
named vowel-pair morph; first one drops into the Forge Audition slot."""
import json, math, random, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pyruntime.packed_interp import coeffs_to_words
from tools import target_browser as tb
from tools.sweep_roster import (
    _biquad_from_pole_zero, _biquad_to_kernel, _normalize_corner_peak,
)

# Klatt 1980 reference adult-male voice — F1/F2/F3 + three upper formants
# extrapolated. The body has 6 stages = exactly 6 formant poles per vowel.
KLATT = {
    "ee": [270, 2290, 3010, 4500, 7500, 11500],
    "ih": [390, 1990, 2550, 4400, 7300, 11200],
    "eh": [530, 1840, 2480, 4300, 7100, 11000],
    "ae": [660, 1720, 2410, 4200, 7000, 10800],
    "ah": [730, 1090, 2440, 4100, 6900, 10600],
    "aw": [570, 840,  2410, 4000, 6800, 10500],
    "uh": [640, 1190, 2390, 4000, 6700, 10400],
    "oo": [300, 870,  2240, 3900, 6500, 10200],
    "uu": [440, 1020, 2240, 3800, 6400, 10000],
    "er": [490, 1350, 1690, 3500, 6000, 9500],
}

LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
AUTH_SR = 39062.5
SLOT_PATHS = [
    Path.home() / "OneDrive" / "Documents" / "TRENCH" / "authoring_slot.json",
    Path.home() / "Documents"               / "TRENCH" / "authoring_slot.json",
]


def vocal_corner(rng, vowel, tight=False):
    """6 biquads — 6 Klatt formants pinned, razor radii, anti-formant zeros
    between consecutive formants. Tight version sharpens radii further."""
    formants = KLATT[vowel]
    pole_rs = [rng.uniform(0.985 if tight else 0.97,
                           0.999 if tight else 0.996) for _ in formants]
    zero_fs = [math.sqrt(formants[i] * formants[min(i + 1, 5)]) for i in range(6)]
    zero_rs = [rng.uniform(0.93, 0.99) for _ in formants]
    gains   = [rng.uniform(0.7, 1.3) for _ in formants]
    stages = []
    for pf, pr, zf, zr, g in zip(formants, pole_rs, zero_fs, zero_rs, gains):
        b = _biquad_from_pole_zero(pf, pr, zf, zr, g, AUTH_SR)
        stages.append(_biquad_to_kernel(*b))
    # Push to AGC sweet spot — +24 dB peaks engage the compressor's biting indices.
    return _normalize_corner_peak(stages, target_db=24.0)


# Five vocal-pair morphs spanning the vowel space
PAIRS = [
    ("ah", "ee"),   # classic open -> bright glide
    ("oo", "ah"),   # rounded back -> open
    ("ee", "uu"),   # bright -> dark rounded
    ("er", "ih"),   # rhotic -> bright
    ("aw", "ae"),   # rounded -> bright open
]

OUT = ROOT / "dev" / "tmp" / "vocal_v2"
OUT.mkdir(parents=True, exist_ok=True)

print("Generated Klatt-direct vocal bodies (peak ~+24 dB -> AGC active):\n")
for i, (home, away) in enumerate(PAIRS, 1):
    rng = random.Random(20000 + i)
    corner_kernels = {
        "M0_Q0":    vocal_corner(rng, home),
        "M100_Q0":  vocal_corner(rng, away),
        "M0_Q100":  vocal_corner(rng, home, tight=True),
        "M100_Q100": vocal_corner(rng, away, tight=True),
    }
    corner_words = {KEY[lab]: [coeffs_to_words(*k) for k in corner_kernels[lab]] for lab in LABELS}
    body = tb.body_bytes(corner_words)
    cart = tb.build_cart(f"Voice {home}-{away}", corner_words, 1.0, "vocal_v2", 20000 + i)
    cart["provenance"] = f"klatt-direct-biquad vocal: {home} -> {away}  AGC-engaged"
    (OUT / f"vocal_v2_{i:02d}.cart.json").write_text(json.dumps(cart, indent=2), encoding="utf-8")
    print(f"  #{i}  {home:>2} -> {away:<2}")

# Pick which body to drop into the Forge Audition slot
n = 1
if len(sys.argv) > 1:
    try:
        n = int(sys.argv[1])
    except ValueError:
        pass
n = max(1, min(len(PAIRS), n))
src = OUT / f"vocal_v2_{n:02d}.cart.json"
for p in SLOT_PATHS:
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, p)
home, away = PAIRS[n - 1]
print(f"\n#{n} ({home} -> {away}) now in Forge Audition slot.")
print("Click 'Forge Audition' in TRENCH body strip.\n")
print(f"Swap to others:  python tools/gen_vocal_v2.py <N>   (N = 1..{len(PAIRS)})")
