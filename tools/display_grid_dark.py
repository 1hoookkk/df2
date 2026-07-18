# Re-issue the X3 log-grid display bed as a DEEP OXIDIZED TEAL-BLACK stage.
#
# The navy-era face read best because of its tonal architecture: a near-black
# screen sunk in the light plate, the curve the only bright thing. This keeps
# the MEASURED X3 rule geometry (from the checked-in 156x69 source) and the
# teal family, but flips the value structure: bed drops to near-black, rules
# ride slightly LIGHTER than the bed (dark-on-dark ruling, navy-style).
# Per-rule ink strength is carried from the source (strong rules = brighter).
#
# NOT idempotent: `git checkout -- plugin/assets/display_bitmap4613.png`
# before every rerun (needs the 156x69 source).
import numpy as np
from PIL import Image
from pathlib import Path

ASSET = Path(r"C:\Users\hooki\df2-workstation\plugin\assets\display_bitmap4613.png")
S = 6  # 156x69 -> 936x414

# MURKY WORKSTATION LCD (Tyson 2026-07-18: "too dark and clean... we want
# identity"): not black glass — a dim, slightly wrong late-2000s green LCD.
# Bed = lit swamp-phosphor green-grey, clearly a SCREEN; rules = darker ink
# pressed into the glass (the real X3 relation), stronger rules inkier.
BED_LO = np.array([30, 46, 39], dtype=np.float32)    # floor of the glass
BED_HI = np.array([58, 82, 68], dtype=np.float32)    # lit crown of the gradient
RULE_LO = np.array([24, 38, 32], dtype=np.float32)   # faint rules (barely inked)
RULE_HI = np.array([13, 24, 20], dtype=np.float32)   # strong rules (deep ink)

src = np.array(Image.open(ASSET).convert("RGB"), dtype=np.float32)
H, W = src.shape[:2]
assert (W, H) == (156, 69), "run `git checkout -- plugin/assets/display_bitmap4613.png` first"


def rule_positions(profile, win=9, delta=2.0):
    pad = np.pad(profile, win // 2, mode="edge")
    base = np.convolve(pad, np.ones(win) / win, mode="valid")
    hit = np.nonzero(profile < base - delta)[0]
    groups = []
    for x in hit:
        if groups and x - groups[-1][-1] <= 1:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [int(np.mean(g)) for g in groups]


lum = src.mean(axis=2)
vx = rule_positions(lum.mean(axis=0))
hy = rule_positions(lum.mean(axis=1))
print(f"vertical rules ({len(vx)}):", vx)
print(f"horizontal rules ({len(hy)}):", hy)

# --- bed: interpolate rules away, keep the source's luminance GRADIENT,
# remap it into the dark range ---
bed = src.copy()
for x in vx:
    l, r = max(0, x - 1), min(W - 1, x + 1)
    bed[:, x] = 0.5 * (bed[:, l] + bed[:, r])
for y in hy:
    t, b = max(0, y - 1), min(H - 1, y + 1)
    bed[y, :] = 0.5 * (bed[t, :] + bed[b, :])
bl = bed.mean(axis=2)
bl = (bl - bl.min()) / max(bl.max() - bl.min(), 1e-4)
bed_dark = BED_LO[None, None] + (BED_HI - BED_LO)[None, None] * bl[..., None]
bed_hi = np.array(
    Image.fromarray(bed_dark.astype(np.uint8)).resize((W * S, H * S), Image.BILINEAR),
    dtype=np.float32)

# --- rules: crisp lines at measured positions; source ink STRENGTH (how much
# darker than the bed the rule ran) maps to how much lighter it now rides ---
out = bed_hi
LINE = 4  # px at 6x -> ~1px on the 1x glass


def rule_tone(strength):
    s = np.clip(strength, 0.0, 1.0)[..., None]
    return RULE_LO[None, :] * (1.0 - s) + RULE_HI[None, :] * s


def draw_v(x):
    depth = np.clip((bed[:, x].mean(axis=1) - src[:, x].mean(axis=1)) / 26.0, 0.0, 1.0)
    shade = rule_tone(depth)
    shade_hi = np.array(Image.fromarray(shade[None].astype(np.uint8))
                        .resize((H * S, 1), Image.BILINEAR), dtype=np.float32)[0]
    cx = int(round((x + 0.5) * S))
    out[:, cx - LINE // 2: cx + LINE - LINE // 2, :] = shade_hi[:, None, :]


def draw_h(y):
    depth = np.clip((bed[y, :].mean(axis=1) - src[y, :].mean(axis=1)) / 26.0, 0.0, 1.0)
    shade = rule_tone(depth)
    shade_hi = np.array(Image.fromarray(shade[None].astype(np.uint8))
                        .resize((W * S, 1), Image.BILINEAR), dtype=np.float32)[0]
    cy = int(round((y + 0.5) * S))
    out[cy - LINE // 2: cy + LINE - LINE // 2, :, :] = shade_hi[None, :, :]


for x in vx:
    draw_v(x)
for y in hy:
    draw_h(y)

Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(ASSET)
print("wrote", ASSET, f"{W*S}x{H*S} (deep oxidized teal-black)")
