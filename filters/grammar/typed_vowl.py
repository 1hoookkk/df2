#!/usr/bin/env python3
"""VOWL aa->iy reconfigured on the REAL section-type grammar
(ref/ghidra_extracts morphdesigner_types + tables/morph_designer_type_primitives):

  Type 1  local_peak_notch   pole+zero co-located  -> formant ridges
  Type 2  high_zero_cliff     moving pole, zero on the high rail -> dark cap
  Type 3  low_zero_sub_cut    moving pole, zero on the low rail  -> bass boundary

...and the Type-3 high-freq compression guard applied to any deep cut above the
~7.15 kHz anchor (a unit notch can't sit at 16 kHz on this family -- it lands at
~7 kHz). Expressed in the clean pole/zero encoder (type grammar as vocabulary),
NOT the firmware-integer emit (the 39k-domain lowpass-mush dead end).
"""
import os, sys
import numpy as np
ROOT = r"C:\Users\hooki\df2"
sys.path.insert(0, ROOT)
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from tools import morph_designer as md
from tools.morph_designer import Lane, compile_lanes
from src.utils.packed_runtime import evaluate_body

FREQS = md.FREQS
SR = md.SR
F_ANCHOR = 7152.0   # Type-3 compression anchor at SR 39062.5 (probe.py pin)

def t3_compress(f_hz, cut_norm):
    """Type-3 guard in Hz: a deep cut above the anchor is pulled toward it,
    harder the deeper the cut. cut_norm in [0,1], 1 = unit notch -> snaps to anchor.
    Mirrors ((fv-220)*(go+32)>>5)+220 with (go+32)/32 -> (1-cut_norm)."""
    if f_hz > F_ANCHOR and cut_norm > 0:
        return (f_hz - F_ANCHOR) * (1.0 - cut_norm) + F_ANCHOR
    return f_hz

V = {v["key"]: v for v in __import__("json").loads(
    open(os.path.join(ROOT, "tables", "vowel_formants.json"), encoding="utf-8").read())["vowels"]}
vh, va = V["aa"], V["iy"]
src = "vowel_formants.json aa->iy (Peterson&Barney 1952)"
g23h, g23a = (vh["f2"] * vh["f3"]) ** 0.5, (va["f2"] * va["f3"]) ** 0.5
g12h = (vh["f1"] * vh["f2"]) ** 0.5   # F1F2 valley (table-traced anti-resonance rail)

def t1r(v, n):
    """Pole radius from the vowel's MEASURED formant bandwidth (P&B/table bw1..bw3)."""
    import math
    return math.exp(-math.pi * v[f"bw{n}"] / SR)

# ONE Secondary law, fully measured. The ROM recapture r -> r^0.356 is a bandwidth
# scaling: 1-r -> 0.356*(1-r) at every radius (the firmware's byte-additive gain
# offset expressed in radius space). Q100 transposes every POLE's bandwidth by that
# factor, direction from the lane's authored dominance: pole-dominant lanes sharpen
# (bw*0.356), zero-dominant lanes loosen (bw/0.356 — the canyon wall recedes, the
# notch widens). Zeros hold (measured: zeros untouched). No lane is an exception.
QBW = 0.356

def qsplit(pr, zr):
    """(tighten, zero_tighten) for the one Q law: measured pole-bandwidth transpose."""
    k = QBW if pr >= zr else 1.0 / QBW
    return (1.0 - (1.0 - pr) * k) - pr, 0.0

# canyon top would author to 16 kHz; the guard pulls the deep (unit) cut to the anchor
canyon_hi = t3_compress(16000.0, 1.0)          # -> 7152
print(f"type-3 compression: canyon top cut 16000 Hz -> {canyon_hi:.0f} Hz (pulled to anchor)")

def tlane(p_lo, p_hi, z_lo, z_hi, source):
    """A typed lane: author (freq, radius) rails + source; the Q split is DERIVED."""
    t, zt = qsplit((p_lo[1] + p_hi[1]) / 2, (z_lo[1] + z_hi[1]) / 2)
    return Lane(p_lo, p_hi, z_lo, z_hi, t, source, zero_tighten=zt)

# each lane = (tlane, type_id, role).
# T1 radius law = firmware symmetric split around one base (c1=rad+go, c3=rad-go,
# |go| bounded): zero co-located at pole radius - 0.005 (the Q0 gain byte);
# T1 pole radius from the table's measured formant bandwidths: r = exp(-pi*bw/SR).
# Cliff/sub-cut pole radii are their gain-byte slots (INFERRED, not table-traced).
LANES = [
    (tlane((150, 0.93), (120, 0.95), (52, 0.99), (52, 0.99), f"T3 sub-cut bass boundary: {src}"),
     3, "sub-cut floor"),
    # F1 lane: tight split at aa, WIDE split at iy — the away pose uncovers the F1
    # pole and a low resonance blooms in across the sweep (the ROM's low-mid
    # crossing). Split authored by the curve; centers stay table-pinned.
    (tlane((vh["f1"], t1r(vh, 1)), (va["f1"], t1r(va, 1)), (vh["f1"], t1r(vh, 1) - 0.005), (va["f1"], 0.93), f"T1 F1 ridge: {src}"),
     1, "F1 ridge"),
    (tlane((vh["f2"], t1r(vh, 2)), (va["f2"], t1r(va, 2)), (vh["f2"], t1r(vh, 2) - 0.005), (va["f2"], t1r(va, 2) - 0.005), f"T1 F2 ridge: {src}"),
     1, "F2 ridge"),
    (tlane((vh["f3"], t1r(vh, 3)), (va["f3"], t1r(va, 3)), (vh["f3"], t1r(vh, 3) - 0.005), (va["f3"], t1r(va, 3) - 0.005), f"T1 F3 ridge: {src}"),
     1, "F3 ridge"),
    # T2 = RESONANT formant against the high-rail zero (firmware: c3 = rad - go)
    (tlane((3200, 0.90), (4600, 0.90), (14000, 0.90), (14000, 0.90), f"T2 high-zero cliff cap: {src}"),
     2, "high cliff"),
    # canyon pole NEAR-LOCAL to its unit zero (T1 "mountain against a nearby canyon");
    # zero-dominant, so under the one Q law the notch deepens and the wall recedes.
    # Start valley = F1F2 geometric mean (table-traced): travel 892->7152 Hz = 3.0 oct,
    # matching the ROM's measured zero motion (3.07 oct)
    (tlane((g12h * 0.85, 0.97), (canyon_hi * 0.85, 0.985), (g12h, 1.0), (canyon_hi, 1.0),
           f"T1 traveling canyon notch (guarded): {src}"),
     1, "canyon notch"),
]
lanes = [l for l, _t, _r in LANES]
labels = [f"S{i+1} T{t} {r}" for i, (_l, t, r) in enumerate(LANES)]

# The type grammar's THIRD ingredient (heritage_coeffs OBSERVED): a type-specific c4
# gain word tied to the pole freq — T1 c4=0xE000 const, T2 c4=fv+0xF5, T3
# c4=(fv-18)*(-12)-8192. Behaviorally: the section's gain word cancels the natural
# passband gain of its own geometry. Clean-domain form: normalize at the passband
# EDGE away from the zero; co-located pairs are natural (g=1, the constant c4).
_bmag = md.biquad_mag_db
def _type_c4_gain(ph, pr, zh, zr):
    if zh > ph * 1.5:      ref = FREQS[0]      # T2-like: zero high -> passband is low side
    elif zh < ph / 1.5:    ref = FREQS[-1]     # T3-like: zero low -> passband is high side
    else:                  return 1.0          # T1 co-located: natural, c4 constant
    k = md._kernel_raw(ph, pr, zh, zr, 1.0)
    ref_db = float(_bmag(k, np.array([ref]), SR)[0])
    return 10.0 ** (max(-40.0, min(40.0, -ref_db)) / 20.0)
md._lane_gain = _type_c4_gain

body = compile_lanes("VOWL_TYPED_aa_to_iy", lanes)
ev = evaluate_body(body, 17)
bad = ev["grid_unstable_rows"] + ev["interior_unstable_rows"] + ev["grid_nonfinite_rows"] + ev["interior_nonfinite_rows"]
print(f"TYPED VOWL  len={len(body)}B  maxR={ev['max_pole_radius']:.5f}  span={ev['endpoint_span_db_mean']:.0f}dB  "
      f"morphR={ev['morph_contrast_rms_db']:.1f}  Qbloom={ev['secondary_contrast_rms_db']:.1f}  "
      f"zmot={ev['max_zero_motion_octaves']:.2f}oct  {'STABLE' if not bad else f'BROKEN({bad})'}")

# corner x stage plot, each stage labeled by its TYPE
CORNERS = [("C0 LOW·Q0", 0.0, 0.0), ("C1 HIGH·Q0", 1.0, 0.0),
           ("C2 LOW·Q100", 0.0, 1.0), ("C3 HIGH·Q100", 1.0, 1.0)]
COL = ["#8b8ff0", "#e6a13b", "#ee6a3c", "#56ed70", "#2fc8cc", "#e0d24a"]
def stage_db(row): return cascade_response_db([EncodedCoeffs(*row)], FREQS, SR)

crowns = []
fig, axs = plt.subplots(2, 2, figsize=(15, 8.6), facecolor="#0a0c0b")
for ci, (name, m, q) in enumerate(CORNERS):
    a = axs[ci // 2][ci % 2]; a.set_facecolor("#111318")
    rows = trench_ffi.packed_interpolate(body, float(m), float(q))
    for k, row in enumerate(rows):
        a.semilogx(FREQS, stage_db(row), lw=1.1, color=COL[k], alpha=0.85, label=labels[k])
    prod = cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, SR)
    crowns.append(float(prod.max()))
    a.semilogx(FREQS, prod, lw=2.6, color="#ffffff", label="PRODUCT (cascade)")
    a.axvline(F_ANCHOR, color="#ee493c", ls=":", lw=1.0, alpha=0.6)
    a.set_xlim(60, 18000); a.set_ylim(-48, 30)
    a.grid(True, which="both", alpha=0.15, color="#3a4048")
    a.set_title(name, color="#cfe9df", fontsize=11)
    a.tick_params(colors="#8a968f", labelsize=7)
    a.set_ylabel("|H| dB", color="#8a968f", fontsize=8); a.set_xlabel("Hz", color="#8a968f", fontsize=8)
    if ci == 0:
        a.legend(fontsize=7, facecolor="#181b20", edgecolor="#2a2e35", labelcolor="#cfe9df", ncol=2, loc="lower center")
fig.suptitle("VOWL aa→iy TYPED  ·  T1 ridge / T2 cliff / T3 sub-cut · red dots = type-3 anchor 7.15k · white = cascade",
             color="#cfe9df", fontsize=11)
fig.tight_layout(rect=(0, 0, 1, 0.96))
PASS = os.environ.get("TYPED_VOWL_PASS", "")
png = rf"C:\WINDOWS\TEMP\claude\C--Users-hooki-df2\b91610d7-d580-445b-852e-fb459683bb74\scratchpad\typed_vowl_corners_stages{PASS}.png"
fig.savefig(png, dpi=120, facecolor="#0a0c0b"); plt.close(fig)
print("crowns C0={:.1f} C1={:.1f} C2={:.1f} C3={:.1f}".format(*crowns))
print("wrote", png)
