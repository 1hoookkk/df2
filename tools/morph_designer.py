"""MORPH DESIGNER — the sanitised, canonical authoring model.

Matches the real E-mu Morph Designer UI exactly: 6 stages, each with a SHAPE,
a FREQ (Hz) and a GAIN (dB), authored at a LOW morph frame and a HIGH morph
frame. Q is the secondary axis. NO firmware integers, NO 44.1k/39k domain
mess — every stage is a textbook RBJ-grammar second-order section expressed in
pole/zero form, packed through the real df2 encoder, audited through the real
engine.

SHAPES (all flat off-resonance where it matters, so they COMPOSE in the serial
cascade):
  PEAK   (EQ+/EQ-)  pole+zero co-located; gain sign = boost/cut; flat off f0
  LOSHELF/HISHELF   step; flat on the far side
  LP / HP           resonant pole at fc; zero pinned at Nyquist / DC
Q sets pole radius via r = exp(-pi * (f/Q) / SR)  (bandwidth = f/Q, textbook).
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from pyruntime.packed_interp import coeffs_to_words
from src.utils.body240 import CORNER_ORDER, raw_from_words
from src.utils.packed_runtime import evaluate_body
from tools.three_layer_acoustic_forge import hz_radius_to_kernel, biquad_mag_db, CORNER_POINTS

ROOT = Path(__file__).resolve().parents[1]
SR = 39062.5
NYQ = SR / 2.0
FREQS = np.logspace(math.log10(40.0), math.log10(18000.0), 700)
RP_MAX, RZ_MAX = 0.9992, 0.9995
OUT = ROOT / "dev" / "tmp" / "morph_designer"; OUT.mkdir(parents=True, exist_ok=True)


class Shape(Enum):
    PEAK = "EQ"        # EQ+/EQ- depending on gain sign
    LOSHELF = "LoShelf"
    HISHELF = "HiShelf"
    LP = "LP"
    HP = "HP"


# SECONDARY LAW — the E-mu Morph Designer manual, verbatim (docs/study/
# EMU_MORPH_DESIGNER_MANUAL.md): the Gain/Q wheel is a GLOBAL ADDITIVE OFFSET on
# every section simultaneously — gain -24..+24 dB on EQ sections (clipped to the
# +/-24 dB parameter range), Q -50..+50% on LP/HP. The authored design sits at
# the wheel CENTER; the four packed corners are the offset extremes. Q corners
# are derived, never authored.
GAIN_RANGE_DB = 24.0          # EQ gain parameter range +/-24 dB (manual)
GAIN_OFFSET_DB = 24.0         # Secondary extreme = +/-24 dB offset (manual)
R_BASE = 0.9862709            # q_radius_table.json idx 0 (132/252 corpus hits) = Q 50%
R_COLD = 0.93686              # q_radius_table.json idx 20 = Q 0% (wheel-min, wide)
R_HOT = 0.99965               # measured ROM Q100 pole-radius ceiling = Q 100%


def _pin0(ph, pr, zh, zr, anchors):
    k = hz_radius_to_kernel(ph, pr, zh, zr, 1.0, SR)
    return -float(np.mean(biquad_mag_db(k, np.array(anchors), SR)))


def _eq_gain(gain_db: float, qx: int) -> float:
    """EQ section gain at a Secondary corner: authored +/- the global offset, clipped."""
    off = GAIN_OFFSET_DB if qx else -GAIN_OFFSET_DB
    return max(-GAIN_RANGE_DB, min(GAIN_RANGE_DB, gain_db + off))


def shape_pz(shape: Shape, freq: float, gain_db: float, qx: int):
    """One shape -> (pole_hz, pole_r, zero_hz, zero_r, gain_db) at Secondary corner qx (0/1)."""
    f = min(16000.0, max(30.0, freq))
    if shape is Shape.PEAK:
        g_eff = _eq_gain(gain_db, qx)
        if g_eff >= 0:
            rp = R_BASE
            rz = max(0.0, min(RZ_MAX, 1.0 - (10.0 ** (g_eff / 20.0)) * (1.0 - R_BASE)))
        else:
            rz = R_BASE
            rp = max(0.5, 1.0 - (1.0 - R_BASE) * (10.0 ** (-g_eff / 20.0)))
        g = _pin0(f, rp, f, rz, [max(40, f / 4), min(17000, f * 4)])
        return (f, rp, f, rz, g)
    # LP/HP: Secondary adds -50/+50% Q -> radius rail R_COLD / R_HOT (q_radius table + ROM ceiling)
    rp = R_HOT if qx else R_COLD
    if shape is Shape.LP:
        # resonant pole at fc, double zero at Nyquist -> 2-pole lowpass
        g = _pin0(f, rp, 17000.0, RZ_MAX, [max(40, f / 8)])  # pin DC to 0
        return (f, rp, 17000.0, RZ_MAX, g)
    if shape is Shape.HP:
        g = _pin0(f, rp, 31.0, RZ_MAX, [min(17000, f * 8)])  # pin Nyquist to 0
        return (f, rp, 31.0, RZ_MAX, g)
    if shape is Shape.LOSHELF:
        g_eff = _eq_gain(gain_db, qx)
        ratio = 10.0 ** (abs(g_eff) / 24.0)
        pf, zf = (f / ratio, f * ratio) if g_eff >= 0 else (f * ratio, f / ratio)
        g = _pin0(pf, 0.5, zf, 0.5, [min(17000, f * 12)])    # flat above
        return (max(30, pf), 0.5, min(16000, zf), 0.5, g)
    if shape is Shape.HISHELF:
        g_eff = _eq_gain(gain_db, qx)
        ratio = 10.0 ** (abs(g_eff) / 24.0)
        pf, zf = (f * ratio, f / ratio) if g_eff >= 0 else (f / ratio, f * ratio)
        g = _pin0(min(16000, pf), 0.5, max(30, zf), 0.5, [max(40, f / 12)])  # flat below
        return (min(16000, pf), 0.5, max(30, zf), 0.5, g)
    raise ValueError(shape)


@dataclass
class Stage:
    shape: Shape
    lo_freq: float
    lo_gain: float
    hi_freq: float
    hi_gain: float
    source: str = ""        # PROVENANCE — table/academia citation for the FREQs. Empty = refused.
    on: bool = True


@dataclass
class Patch:
    name: str
    stages: list[Stage]          # up to 6
    # Secondary axis is the radius law (R_BASE -> R_HOT); no per-patch Q numbers.
    q_lo: float = 0.0            # kept for signature stability; unused
    q_hi: float = 0.0


def compile_patch(p: Patch) -> bytes:
    stages = [s for s in p.stages if s.on][:6]
    for s in stages:                                   # PROVENANCE GATE
        if not s.source.strip():
            raise ValueError(f"REFUSED: stage {s.shape.name}@{s.lo_freq}->{s.hi_freq}Hz has no table/academia source")
    corners: dict[str, list] = {}
    for label in CORNER_ORDER:
        morph, qx = CORNER_POINTS[label]
        rows = []
        for st in stages:
            freq = st.hi_freq if morph >= 0.5 else st.lo_freq
            gain = st.hi_gain if morph >= 0.5 else st.lo_gain
            ph, pr, zh, zr, gdb = shape_pz(st.shape, freq, gain, int(qx >= 0.5))
            k = hz_radius_to_kernel(ph, pr, zh, zr, 10 ** (gdb / 20), SR)
            rows.append(tuple(int(v) for v in coeffs_to_words(*k)))
        while len(rows) < 6:                       # unused stages -> flat passthrough
            rows.append(tuple(int(v) for v in coeffs_to_words(2.0, 1.0, 2.0, 1.0, 1.0)))
        corners[label] = rows
    return raw_from_words(corners)


def resp(body, m, q):
    rows = trench_ffi.packed_interpolate(body, float(m), float(q))
    return cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, SR)


def _corridor_gates():
    """Iconic-15 corridor gates from configs/model/smoke.yaml (the calibrated ruler)."""
    import yaml
    from types import SimpleNamespace
    cfg = yaml.safe_load((ROOT / "configs" / "model" / "smoke.yaml").read_text())
    return SimpleNamespace(**cfg["gates"])


GATES = _corridor_gates()
REFERENCE = {"median_endpoint_span_db": 0.0, "median_morph_contrast_db": 0.0,
             "median_secondary_contrast_db": 0.0}   # corridor floors are already reference-derived


def render(p: Patch):
    _render_body(p.name, compile_patch(p))


def _render_body(name: str, body: bytes):
    from src.utils.packed_runtime import gate_failures
    ev = evaluate_body(body, 17)
    fails = gate_failures(ev, GATES, REFERENCE)
    bad = ev["grid_unstable_rows"] + ev["interior_unstable_rows"] + ev["grid_nonfinite_rows"] + ev["interior_nonfinite_rows"]
    fig, ax = plt.subplots(1, 2, figsize=(15, 4.4), facecolor="#0a0c0b")
    morphs = np.linspace(0, 1, 160)
    img = np.array([resp(body, m, 1.0) for m in morphs]).T
    ax[0].pcolormesh(morphs, FREQS, img, cmap="magma", shading="auto", vmin=-30, vmax=18)
    ax[0].set_yscale("log"); ax[0].set_ylim(60, 18000); ax[0].set_title(f"{name} morph (sharp Q)", color="#cfe9df")
    ax[0].tick_params(colors="#8a968f", labelsize=7)
    for m, q, l, c in ((0, 0, "LO", "#e6a13b"), (1, 0, "HI", "#2fc8cc"),
                       (0.5, 0, "M50 Qlo", "#56ed70"), (0.5, 1, "M50 Qhi", "#ee493c")):
        ax[1].semilogx(FREQS, resp(body, m, q), label=l, lw=1.3, color=c)
    ax[1].set_xlim(60, 18000); ax[1].set_ylim(-32, 22); ax[1].grid(True, alpha=0.25); ax[1].legend(fontsize=8)
    ax[1].set_title("LO->HI + Q", color="#cfe9df"); ax[1].tick_params(colors="#8a968f", labelsize=7)
    fig.tight_layout(); png = OUT / f"{name}.png"; fig.savefig(png, dpi=110, facecolor="#0a0c0b"); plt.close(fig)
    (OUT / f"{name}.body240").write_bytes(body)
    verdict = "GATE PASS" if not fails else "GATE FAIL: " + "; ".join(fails)
    print(f"{name:22} {len(body)}B maxR={ev['max_pole_radius']:.5f} span={ev['endpoint_span_db_mean']:.0f} "
          f"morphR={ev['morph_contrast_rms_db']:.1f} Qbloom={ev['secondary_contrast_rms_db']:.1f} "
          f"pk={ev['center_response_peaks']} vly={ev['center_response_valleys']} "
          f"zmot={ev['max_zero_motion_octaves']:.2f}oct "
          f"{'STABLE' if not bad else 'BROKEN'}  {verdict}")


# ---- table-sourced patches: every FREQ pulled from tables/academia, cited ----
import json
VOWELS = {v["key"]: v for v in json.loads((ROOT / "tables" / "vowel_formants.json").read_text())["vowels"]}
CUT = json.loads((ROOT / "tables" / "family_intents.json").read_text())["families"]["cut"]["intents"]


def vowel_patch(home: str, away: str) -> Patch:
    """Three-layer vowel: MOUNTAIN (glottal low-shelf) + F1-F3 peaks +
    CANYON (the F2-F3 valley, a moving zero pair) + radiation roll-off.
    Formants from Peterson&Barney 1952; canyon = geometric mean of the
    vowel's own F2/F3 (table-derived, glides with them)."""
    vh, va = VOWELS[home], VOWELS[away]
    src = "vowel_formants.json (Peterson&Barney 1952)"
    cyn_h = math.sqrt(vh["f1"] * vh["f2"])   # LO: valley between F1-F2
    cyn_a = math.sqrt(va["f2"] * va["f3"])   # HI: valley between F2-F3 (leader travels ~1.6 oct)
    stages = [
        Stage(Shape.LOSHELF, vh["f1"] / 2, 12, va["f1"] / 2, -4,
              f"MOUNTAIN glottal shelf below F1 (open->closed tilt): {src}"),
        Stage(Shape.PEAK, vh["f1"], 24, va["f1"], 12, f"F1 {home}->{away} (fades): {src}"),
        Stage(Shape.PEAK, vh["f2"], 12, va["f2"], 24, f"F2 {home}->{away} (rises): {src}"),
        Stage(Shape.PEAK, vh["f3"], 10, va["f3"], 20, f"F3 {home}->{away} (rises): {src}"),
        Stage(Shape.PEAK, cyn_h, -26, cyn_a, -26,
              f"CANYON between F2-F3 (geom mean of table F2,F3): {src}"),
        Stage(Shape.LP, 7000, 0, 9000, 0, "MOUNTAIN spectral roll-off above F-stack [Klatt 1980 source model]"),
    ]
    return Patch(f"VOW_{home}_to_{away}", stages, q_lo=4.0, q_hi=18.0)


def bass_patch(home: str, away: str) -> Patch:
    """Bass sweep: LP cutoff rides the full cut-family rail (body_low->tear_hi),
    rez at the cutoff, static bass shelf floor, canyon travels scoop->tear."""
    h, a = CUT[home]["freqs"], CUT[away]["freqs"]   # slots: body_low, body_mid, scoop_notch, tear_lo, tear_hi
    src = f"family_intents.json cut {home}->{away}"
    stages = [
        Stage(Shape.LOSHELF, h[0], 12, h[0], 12, f"MOUNTAIN bass floor body_low (held): {src}"),
        Stage(Shape.LP, h[0] * 2, 0, a[4], 0, f"MOUNTAIN cutoff 2*body_low->tear_hi sweeps: {src}"),
        Stage(Shape.PEAK, h[0] * 2, 12, a[4], 12, f"rez rides the cutoff: {src}"),
        Stage(Shape.PEAK, h[1], 8, a[1], 16, f"squelch body_mid: {src}"),
        Stage(Shape.PEAK, h[2], -16, a[3], -16, f"CANYON scoop_notch->tear_lo travels: {src}"),
    ]
    return Patch(f"BASS_{home}_to_{away}", stages)


TUBES = {t["key"]: t for t in json.loads((ROOT / "tables" / "tube_resonances.json").read_text())["tubes"]}
METALS = {o["key"]: o for o in json.loads((ROOT / "tables" / "metallic_modes.json").read_text())["objects"]}
COMB = json.loads((ROOT / "tables" / "family_intents.json").read_text())["families"]["comb"]["intents"]


def tube_patch(home: str, away: str) -> Patch:
    """ONE pipe changing length (slide whistle). Every partial slides in
    lock-step by the same ratio — the SCALE morph the table describes. Equal
    ring on all partials; no decorations. Partials from tube_resonances.json."""
    th, ta = TUBES[home], TUBES[away]
    src = f"tube_resonances.json {home}->{away} (f_n=n*c/2L pipe acoustics)"
    ph, pa = th["partials_hz"], ta["partials_hz"]
    n = min(6, len(ph), len(pa))
    stages = [Stage(Shape.PEAK, ph[i], 14, pa[i], 14, f"partial {i+1}: {src}") for i in range(n)]
    return Patch(f"TUBE_{home}_to_{away}", stages)


def metallic_patch(obj: str) -> Patch:
    """ONE struck object, strike -> ring (table morph_guidance (a): which
    partials dominate). Modes stay at their measured ratios; the energy
    migrates from the fundamental to the upper partials across Morph."""
    m = METALS[obj]
    f = [min(r * m["fundamental_hint_hz"], 16000) for r in m["ratios"]]
    src = f"metallic_modes.json {obj} (Rossing/Fletcher modal ratios)"
    n = min(6, len(f))
    stages = []
    for i in range(n):
        w = i / max(1, n - 1)                  # 0 = fundamental .. 1 = highest mode
        lo = 16.0 - 10.0 * w                   # strike: fundamental dominates
        hi = 6.0 + 10.0 * w                    # ring: upper partials dominate
        stages.append(Stage(Shape.PEAK, f[i], lo, f[i], hi, f"mode {i+1} strike->ring: {src}"))
    return Patch(f"METAL_{obj}_strike_to_ring", stages)


def comb_patch(f0_lo: float = 343.0, f0_hi: float = 953.0) -> Patch:
    """A REAL comb: delay-line interference puts notches at n*f0 (harmonic
    spacing). Morph = delay change, so every tooth scales by the same ratio.
    f0 endpoints = open-open tube fundamentals (343 Hz @ 50 cm, 953 Hz @ 18 cm,
    tube_resonances.json) — the physical delay lengths."""
    src = "comb interference notches at n*f0; f0 from tube_resonances.json fundamentals"
    stages = [Stage(Shape.PEAK, n * f0_lo, -18, n * f0_hi, -18, f"tooth n={n}: {src}")
              for n in range(1, 7)]
    return Patch("COMB_delay_scale", stages)


def lp_rez_patch(home: str, away: str) -> Patch:
    """The canonical resonant lowpass: TWO LP sections stacked at one cutoff
    (4-pole ladder, 24 dB/oct) + rez peak riding the cutoff. Cutoff rail body_low*2 ->
    tear_hi from family_intents cut. Nothing else."""
    h, a = CUT[home]["freqs"], CUT[away]["freqs"]
    src = f"family_intents.json cut {home}->{away}"
    fl, fh = h[0] * 2, a[4]
    stages = [Stage(Shape.LP, fl, 0, fh, 0, f"LP pole pair {i+1}/2 at cutoff: {src}") for i in range(2)]
    stages.append(Stage(Shape.PEAK, fl, 10, fh, 10, f"rez rides the cutoff: {src}"))
    return Patch(f"LPREZ_{home}_to_{away}", stages)




# ============================================================================
# LANE GRAMMAR — the native format of the ROM best-of (studied in the decoded
# atlas, dev/tmp/p2k/atlas). What the study measured:
#   * zeros are INDEPENDENT of poles: own freq rails, counter-moving;
#   * one lane carries a UNIT-CIRCLE zero (r=1.0) — a true notch — traveling
#     octaves (all 15 iconic bodies);
#   * radii are moderate (0.85-0.99); violence = motion, not hot poles;
#   * anchors + movers: vowel bodies hold formant lanes, 1-2 lanes do the work;
#   * Q corners = small per-lane pole tightenings (median +0.02, p75 +0.06,
#     ~45% of lanes; zeros untouched).
# Shapes above remain for the designer UI; lanes are what the best-of are made of.
# ============================================================================

@dataclass
class Lane:
    p_lo: tuple   # (hz, radius) pole at Morph 0
    p_hi: tuple   # pole at Morph 100
    z_lo: tuple   # zero at Morph 0
    z_hi: tuple   # zero at Morph 100
    tighten: float = 0.0   # Q100 pole-radius add (measured: 0 / +0.02 / +0.06)
    source: str = ""       # PROVENANCE for the freq rails
    zero_tighten: float = 0.0  # Q100 zero-radius add; centers stay fixed


def _kernel_raw(ph, pr, zh, zr, g):
    """hz/radius -> DF2T kernel WITHOUT the constructor zero clamp (unit zeros legal)."""
    ph = min(max(ph, 25.0), 0.47 * SR); zh = min(max(zh, 25.0), 0.47 * SR)
    pr = min(max(pr, 0.05), 0.9989); zr = min(max(zr, 0.0), 1.0)
    wp = 2 * math.pi * ph / SR; wz = 2 * math.pi * zh / SR
    return (2 - 2 * zr * math.cos(wz), 1 - zr * zr,
            2 - 2 * pr * math.cos(wp), 1 - pr * pr, g)


def _lane_gain(ph, pr, zh, zr):
    """Survival law: normalize the lane mean dB over the band to 0 so six
    lanes cascade without tilting (the ROM bakes per-corner gains the same way)."""
    k = _kernel_raw(ph, pr, zh, zr, 1.0)
    mean_db = float(np.mean(biquad_mag_db(k, FREQS, SR)))
    return 10.0 ** (max(-40.0, min(40.0, -mean_db)) / 20.0)


def compile_lanes(name: str, lanes: list) -> bytes:
    lanes = lanes[:6]
    for ln in lanes:
        if not ln.source.strip():
            raise ValueError(f"REFUSED: lane {ln.p_lo}->{ln.p_hi} has no table/academia source")
    corners: dict[str, list] = {}
    k_lo, k_hi = land_frame(lanes, False), land_frame(lanes, True)
    for label in CORNER_ORDER:
        morph, qx = CORNER_POINTS[label]
        k = k_hi if morph >= 0.5 else k_lo         # root-snap transpose, ratios exact
        # each lane at this corner, normalized flat off-resonance (mean ~0 dB)
        params = []
        for ln in lanes:
            (ph, pr), (zh, zr) = (ln.p_hi, ln.z_hi) if morph >= 0.5 else (ln.p_lo, ln.z_lo)
            ph, zh = ph * k, zh * k
            if qx >= 0.5:
                pr = min(0.9989, pr + ln.tighten)     # measured Q law: poles tighten, zeros hold
                zr = min(1.0, zr + getattr(ln, "zero_tighten", 0.0))
            params.append((ph, pr, zh, zr, _lane_gain(ph, pr, zh, zr)))
        # SERIES law: six flat-baseline lanes compose as H = PRODUCT of stages
        # (sum of dB). NO per-lane "survival makeup" — in a serial cascade that
        # boost MULTIPLIES across stages and pins the whole spectrum to the rail
        # (the ceiling). A peak the other lanes bury is genuinely buried; fix it
        # by moving poles/zeros, not by fabricating gain.
        rows = [tuple(int(v) for v in coeffs_to_words(*_kernel_raw(ph, pr, zh, zr, g)))
                for (ph, pr, zh, zr, g) in params]
        while len(rows) < 6:
            rows.append(tuple(int(v) for v in coeffs_to_words(2.0, 1.0, 2.0, 1.0, 1.0)))
        corners[label] = rows
    return raw_from_words(corners)


@dataclass
class LanePatch:
    name: str
    lanes: list


def render_lanes(p) -> None:
    _render_body(p.name, compile_lanes(p.name, p.lanes))


# ---- archetype builders: best-of STRUCTURE, our table FREQUENCIES ----------

def vow_lanes(home: str, away: str):
    """TalkingHedz structure: formant anchors held, zeros between formants
    (vocal-tract anti-resonances), a low mover lane, and the traveling
    unit-notch canyon. Formants: Peterson&Barney 1952."""
    vh, va = VOWELS[home], VOWELS[away]
    src = f"vowel_formants.json {home}->{away} (Peterson&Barney 1952)"
    g12h, g12a = math.sqrt(vh["f1"] * vh["f2"]), math.sqrt(va["f1"] * va["f2"])
    g23h, g23a = math.sqrt(vh["f2"] * vh["f3"]), math.sqrt(va["f2"] * va["f3"])
    return LanePatch(f"VOWL_{home}_to_{away}", [
        Lane((vh["f1"], 0.987), (va["f1"], 0.987), (g12h, 0.95), (g12a, 0.95), 0.02, f"F1 + F1F2 antiresonance: {src}"),
        Lane((vh["f2"], 0.986), (va["f2"], 0.986), (g23h, 0.95), (g23a, 0.95), 0.02, f"F2 + F2F3 antiresonance: {src}"),
        Lane((vh["f3"], 0.985), (va["f3"], 0.985), (vh["f3"] * 1.6, 0.93), (va["f3"] * 1.6, 0.93), 0.02, f"F3 + upper antiresonance: {src}"),
        Lane((vh["f1"], 0.975), (va["f1"] / 2.2, 0.99), (vh["f1"] * 1.3, 0.94), (va["f1"] * 0.9, 0.96), 0.06, f"throat mover below F1: {src}"),
        Lane((9000, 0.972), (8400, 0.962), (vh["f1"] / 2, 0.935), (va["f2"] * 0.75, 0.944), 0.02, f"parked top pole, sub-formant zero rail: {src}"),
        Lane((g23h / 2, 0.99), (16000 / 2, 0.995), (g23h, 1.0), (16000, 1.0), 0.0, f"unit-notch canyon F2F3 valley -> top: {src}"),
    ])


def tube_lanes(home: str, away: str):
    """ToothComb structure (harmonic peaks shift in unison): poles at the
    partials sliding lock-step, zeros at the pipe anti-resonances midway
    between partials, unit-notch canyon riding above the stack."""
    th, ta = TUBES[home], TUBES[away]
    src = f"tube_resonances.json {home}->{away} (f_n=n*c/2L pipe acoustics)"
    ph_, pa_ = th["partials_hz"], ta["partials_hz"]
    lanes = []
    for i in range(5):
        zh = math.sqrt(ph_[i] * ph_[min(i + 1, len(ph_) - 1)])
        za = math.sqrt(pa_[i] * pa_[min(i + 1, len(pa_) - 1)])
        lanes.append(Lane((ph_[i], 0.985), (pa_[i], 0.985), (zh, 0.955), (za, 0.955), 0.06,
                          f"partial {i+1} + inter-partial antiresonance: {src}"))
    lanes.append(Lane((ph_[-1] * 1.2, 0.97), (pa_[-1] * 1.2, 0.97), (ph_[-1] * 1.4, 1.0), (pa_[-1] * 1.4, 1.0), 0.0,
                      f"unit-notch canyon above the stack: {src}"))
    return LanePatch(f"TUBEL_{home}_to_{away}", lanes)


def metal_lanes(obj: str):
    """DeadRinger/KlangKling structure: modes anchored (they physically cannot
    move), zeros parked in the dead gaps; morph slides the unit-notch canyon
    through the gaps = strike->ring spectral migration by ZERO MOTION."""
    m = METALS[obj]
    f = [min(r * m["fundamental_hint_hz"], 16000) for r in m["ratios"]][:5]
    src = f"metallic_modes.json {obj} (Rossing/Fletcher modal ratios)"
    lanes = []
    for i in range(len(f)):
        gap = math.sqrt(f[i] * f[min(i + 1, len(f) - 1)]) if i + 1 < len(f) else f[i] * 1.5
        lanes.append(Lane((f[i], 0.987), (f[i], 0.987), (gap, 0.96), (gap, 0.96), 0.06,
                          f"mode {i+1} anchored + dead-gap zero: {src}"))
    g1 = math.sqrt(f[0] * f[1]); g2 = math.sqrt(f[-2] * f[-1])
    lanes.append(Lane((g1 / 2, 0.99), (g2 / 2, 0.99), (g1, 1.0), (g2, 1.0), 0.0,
                      f"unit-notch canyon migrates gap1->gap{len(f)-1}: {src}"))
    return LanePatch(f"METALL_{obj}", lanes)


def comb_lanes(f0_lo: float = 343.0, f0_hi: float = 953.0):
    """PhazeShift structure: notches harmonically spaced (delay interference),
    ALL unit zeros, poles parked between the teeth as ridges; morph scales the
    delay. f0 endpoints = open-pipe fundamentals (tube_resonances.json)."""
    src = "comb interference notches at n*f0; f0 rails from tube_resonances.json fundamentals"
    lanes = []
    for n in range(1, 6):
        lanes.append(Lane(((n + 0.5) * f0_lo, 0.93), ((n + 0.5) * f0_hi, 0.93),
                          (n * f0_lo, 1.0), (n * f0_hi, 1.0), 0.05,
                          f"tooth n={n} (unit zero) + ridge pole: {src}"))
    lanes.append(Lane((6 * f0_lo, 0.95), (6 * f0_hi, 0.95), (6.5 * f0_lo, 1.0), (6.5 * f0_hi, 1.0), 0.05,
                      f"tooth n=6.5 + ridge: {src}"))
    return LanePatch("COMBL_delay_scale", lanes)


def lprez_lanes(home: str, away: str):
    """EarlyRizer structure: one hot rez pole sweeping the whole rail, the
    rolloff mass stacked behind it, zeros descending ahead of the sweep, and
    the unit-notch canyon opening above. Rails from family_intents cut."""
    h, a = CUT[home]["freqs"], CUT[away]["freqs"]
    src = f"family_intents.json cut {home}->{away}"
    fl, fh = h[0] * 2, a[4]                       # 400 -> 11000: the rail
    return LanePatch(f"LPREZL_{home}_to_{away}", [
        Lane((fl, 0.985), (fh, 0.985), (fl * 4, 0.93), (fh * 1.3, 0.93), 0.06, f"rez leader on the rail: {src}"),
        Lane((fl * 0.85, 0.94), (fh * 0.85, 0.94), (fl * 6, 0.90), (fh * 1.5, 0.90), 0.02, f"rolloff mass 1: {src}"),
        Lane((h[1], 0.93), (a[1], 0.93), (h[2], 0.90), (a[2], 0.90), 0.02, f"body_mid color: {src}"),
        Lane((fl * 0.5, 0.96), (fh * 0.4, 0.96), (16000, 0.95), (16000, 0.95), 0.0, f"low support, top zero parked: {src}"),
        Lane((h[2] / 2, 0.97), (a[3] / 2, 0.97), (h[2], 1.0), (a[3], 1.0), 0.0, f"unit-notch canyon scoop->tear: {src}"),
    ])


RAZOR_NOTCHES = ((420.0, 760.0), (900.0, 1650.0), (1800.0, 3300.0),
                 (3600.0, 6400.0), (7000.0, 11500.0))


def razor_lanes():
    """Lucifer/Razor structure: five moving zero-led canyons over broad poles.

    Frequencies are the registered clean-room razor rail from
    surfaceforge.recipes.archetypes._RAZOR_NOTCHES. Secondary deepens the zero
    radii only; pole/zero centers are held at both Morph endpoints.
    """
    src = "surfaceforge.recipes.archetypes._RAZOR_NOTCHES clean-room aggregate grammar"
    lanes = [
        Lane((130.0, 0.86), (130.0, 0.86), (130.0, 0.45), (130.0, 0.45),
             0.02, f"low anchor from archetypes.razor_cut: {src}"),
    ]
    for i, (flo, fhi) in enumerate(RAZOR_NOTCHES):
        lanes.append(Lane((flo, 0.55), (fhi, 0.55), (flo, 0.995), (fhi, 0.995),
                          0.0, f"razor notch {i + 1}: {src}", zero_tighten=0.004))
    return LanePatch("RAZORL_cleanroom_lucifers_q", lanes)




CAVITY = json.loads((ROOT / "tables" / "family_intents.json").read_text())["families"]["cavity"]["intents"]


def cavity_lanes(home: str, away: str):
    """Helmholtz vessel swap: resonator + body modes anchored per vessel, morph
    carries the unit-notch canyon between the mode stacks. Freqs from
    family_intents cavity (measured Helmholtz + closed-pipe body modes)."""
    h, a = CAVITY[home]["freqs"], CAVITY[away]["freqs"]
    src = f"family_intents.json cavity {home}->{away} (Helmholtz + body modes)"
    n = min(4, len(h), len(a))
    lanes = []
    for i in range(n):
        zh = math.sqrt(h[i] * h[min(i + 1, n - 1)]) if i + 1 < n else h[i] * 1.5
        za = math.sqrt(a[i] * a[min(i + 1, n - 1)]) if i + 1 < n else a[i] * 1.5
        r = 0.988 if i == 0 else 0.985            # the Helmholtz fundamental rings hardest
        lanes.append(Lane((h[i], r), (a[i], r), (zh, 0.955), (za, 0.955), 0.06,
                          f"mode {i+1} + inter-mode antiresonance: {src}"))
    lanes.append(Lane((h[0] * 1.4, 0.99), (a[0] * 1.4, 0.99), (h[0] * 2, 1.0), (a[-1] * 1.4, 1.0), 0.0,
                      f"unit-notch canyon across the swap: {src}"))
    lanes.append(Lane((h[-1] * 2, 0.96), (a[-1] * 2, 0.96), (h[-1] * 3, 0.95), (a[-1] * 3, 0.95), 0.02,
                      f"upper body color: {src}"))
    return LanePatch(f"CAVL_{home}_to_{away}", lanes)


def riser_lanes(home: str, away: str):
    """Deeper-HPF / tb riser structure (the corpus top scorer): poles AND the
    unit zero sweep UP together from the floor — the cutoff climbs and takes
    the body with it. Rails from family_intents cut."""
    h, a = CUT[home]["freqs"], CUT[away]["freqs"]
    src = f"family_intents.json cut {home}->{away}"
    fl, fh = h[0], a[3]                            # 200 -> 7000: the climb
    return LanePatch(f"RISERL_{home}_to_{away}", [
        Lane((fl, 0.97), (fh, 0.985), (fl / 2, 1.0), (fh / 2, 1.0), 0.06, f"leader pole climbs, unit zero floors below: {src}"),
        Lane((fl * 1.6, 0.94), (fh * 1.3, 0.96), (fl * 0.7, 0.97), (fh * 0.6, 0.97), 0.02, f"second edge: {src}"),
        Lane((h[1], 0.985), (a[1], 0.985), (math.sqrt(h[1] * h[2]), 0.95), (math.sqrt(a[1] * a[2]), 0.95), 0.02, f"body_mid anchor: {src}"),
        Lane((h[2], 0.982), (a[2], 0.982), (h[2] * 1.5, 0.94), (a[2] * 1.5, 0.94), 0.02, f"upper anchor: {src}"),
        Lane((16000, 0.93), (16000, 0.93), (30, 0.9), (30, 0.9), 0.0, f"top air parked: {src}"),
    ])




# ---- CROSS-IDENTITY MORPHS ------------------------------------------------
# A body should not morph into itself. Frame LO = one physical identity,
# frame HI = a DIFFERENT one (vowel -> tube, bell -> bottle...). Lanes are
# paired across the two identities in BARK order (perceptual frequency rank),
# so each lane glides to its perceptual counterpart while the identity flips.

def snap(f: float) -> float:
    """Nearest 12-TET note (A440)."""
    return 440.0 * 2.0 ** (round(12.0 * math.log2(max(f, 20.0) / 440.0)) / 12.0)


def land_frame(lanes: list, hi: bool) -> float:
    """ROOT-snap transpose factor for one frame: the lowest pole lands on
    12-TET; every other freq keeps its EXACT table ratio to it. The body rings
    in tune with the track; internal intervals stay true to the physics
    (harmonic pipes stay harmonic, inharmonic bars stay inharmonic)."""
    cands = [(ln.p_hi if hi else ln.p_lo)[0] for ln in lanes]
    active = [f for f in cands if f < 16000.0]     # parked lanes are not the root
    root = min(active) if active else min(cands)
    return snap(root) / root


def _bark(f: float) -> float:
    return 13.0 * math.atan(0.00076 * f) + 3.5 * math.atan((f / 7500.0) ** 2)


def _frame_sort(frame: list) -> list:
    """frame = list of (pole(hz,r), zero(hz,r), tighten, label); sort by Bark of the pole."""
    return sorted(frame, key=lambda x: _bark(x[0][0]))


# a PARKED half-lane: pole and zero co-located (same hz, same r) -> the biquad
# is identically 1 = flat. Millennium's M0 frame parks five of six lanes above
# 10 kHz; the morph is sections WALKING ONSTAGE. Simpler frame = fewer rows.
PARKED = ((16800.0, 0.88), (16800.0, 0.88), 0.0, "parked (flat)")


def cross_lanes(name: str, frame_lo: list, frame_hi: list, source: str):
    """Pair two identities by Bark rank into one LanePatch. A frame with fewer
    rows gets PARKED half-lanes — that corner is genuinely SIMPLE (Millennium
    contrast: one bass pole at M0, full 12th-order at M100)."""
    a, b = _frame_sort(frame_lo), _frame_sort(frame_hi)
    n = min(6, max(len(a), len(b)))
    a = (a + [PARKED] * 6)[:n]
    b = (b + [PARKED] * 6)[:n]
    lanes = []
    for i in range(n):
        (pl, zl, tl, ll), (ph_, zh_, th_, lh) = a[i], b[i]
        lanes.append(Lane(pl, ph_, zl, zh_, max(tl, th_), f"{ll} -> {lh}: {source}"))
    return LanePatch(name, lanes)


def simple_frame(f: float, r: float = 0.992, label: str = "single tone") -> list:
    """A SIMPLE identity: one strong pole (zero parked far above), nothing else.
    The other lanes arrive via PARKED padding in cross_lanes."""
    return [((f, r), (f * 12, 0.85), 0.06, f"{label} {f:.0f}Hz")]


# frame builders: 6 half-lanes per identity, all freqs table-pulled ----------

def vowel_frame(key: str) -> list:
    v = VOWELS[key]
    g12, g23 = math.sqrt(v["f1"] * v["f2"]), math.sqrt(v["f2"] * v["f3"])
    return [
        ((v["f1"], 0.987), (g12, 0.95), 0.02, f"vowel {key} F1"),
        ((v["f2"], 0.986), (g23, 0.95), 0.02, f"vowel {key} F2"),
        ((v["f3"], 0.985), (v["f3"] * 1.6, 0.93), 0.02, f"vowel {key} F3"),
        ((v["f1"] * 0.6, 0.975), (v["f1"] * 1.3, 0.94), 0.06, f"vowel {key} throat"),
        ((9000, 0.97), (v["f1"] / 2, 0.935), 0.02, f"vowel {key} top"),
        ((g23 / 2, 0.99), (g23, 1.0), 0.0, f"vowel {key} canyon"),
    ]


def tube_frame(key: str) -> list:
    t = TUBES[key]
    ph_ = t["partials_hz"]
    out = []
    for i in range(min(5, len(ph_))):
        z = math.sqrt(ph_[i] * ph_[min(i + 1, len(ph_) - 1)])
        out.append(((ph_[i], 0.985), (z, 0.955), 0.06, f"tube {key} partial {i+1}"))
    out.append(((ph_[-1] * 1.2, 0.97), (ph_[-1] * 1.4, 1.0), 0.0, f"tube {key} canyon"))
    return out


def metal_frame(key: str) -> list:
    m = METALS[key]
    f = [min(r * m["fundamental_hint_hz"], 16000) for r in m["ratios"]][:5]
    out = []
    for i in range(len(f)):
        gap = math.sqrt(f[i] * f[min(i + 1, len(f) - 1)]) if i + 1 < len(f) else f[i] * 1.5
        out.append(((f[i], 0.987), (gap, 0.96), 0.06, f"metal {key} mode {i+1}"))
    out.append(((math.sqrt(f[0] * f[1]) / 2, 0.99), (math.sqrt(f[0] * f[1]), 1.0), 0.0, f"metal {key} canyon"))
    return out


def cavity_frame(key: str) -> list:
    c = CAVITY[key]["freqs"]
    out = []
    for i in range(min(4, len(c))):
        z = math.sqrt(c[i] * c[min(i + 1, len(c) - 1)]) if i + 1 < len(c) else c[i] * 1.5
        r = 0.988 if i == 0 else 0.985
        out.append(((c[i], r), (z, 0.955), 0.06, f"cavity {key} mode {i+1}"))
    out.append(((c[0] * 1.4, 0.99), (c[0] * 2, 1.0), 0.0, f"cavity {key} canyon"))
    out.append(((c[-1] * 2, 0.96), (c[-1] * 3, 0.95), 0.02, f"cavity {key} upper"))
    return out


def comb_frame(f0: float) -> list:
    out = []
    for n in range(1, 6):
        out.append((((n + 0.5) * f0, 0.93), (n * f0, 1.0), 0.05, f"comb tooth {n} (f0={f0:.0f})"))
    out.append(((6 * f0, 0.95), (6.5 * f0, 1.0), 0.05, f"comb tooth 6 (f0={f0:.0f})"))
    return out


if __name__ == "__main__":
    # Millennium contrast: a SIMPLE corner walking into a complex one
    render_lanes(cross_lanes("M_sub55_to_vowel_aa", simple_frame(55.0, 0.995, "sub"), vowel_frame("aa"),
                             "single sub pole + vowel_formants.json"))
    render_lanes(cross_lanes("M_tone220_to_gong", simple_frame(220.0, 0.993, "tone"), metal_frame("gong"),
                             "single tone pole + metallic_modes.json"))
    render_lanes(cross_lanes("M_tube25_to_sub80", tube_frame("oo_25cm"), simple_frame(80.0, 0.995, "sub"),
                             "tube_resonances.json + single sub pole"))
    render_lanes(cross_lanes("M_sub60_to_beerbottle", simple_frame(60.0, 0.995, "sub"), cavity_frame("beer_bottle"),
                             "single sub pole + family_intents.json cavity"))
    render_lanes(cross_lanes("M_sub70_to_freeplate", simple_frame(70.0, 0.994, "sub"), metal_frame("free_plate"),
                             "single sub pole + metallic_modes.json"))

    # cross-identity morphs
    render_lanes(cross_lanes("X_vowel_aa_to_tube25", vowel_frame("aa"), tube_frame("oo_25cm"),
                             "vowel_formants.json + tube_resonances.json"))
    render_lanes(cross_lanes("X_bell_to_winebottle", metal_frame("bell"), cavity_frame("wine_bottle"),
                             "metallic_modes.json + family_intents.json cavity"))
    render_lanes(cross_lanes("X_vowel_iy_to_freebar", vowel_frame("iy"), metal_frame("free_bar"),
                             "vowel_formants.json + metallic_modes.json"))
    render_lanes(cross_lanes("X_comb343_to_vowel_er", comb_frame(343.0), vowel_frame("er"),
                             "tube_resonances.json f0 + vowel_formants.json"))
    render_lanes(cross_lanes("X_tincan_to_vowel_ae", cavity_frame("tin_can"), vowel_frame("ae"),
                             "family_intents.json cavity + vowel_formants.json"))
    render_lanes(cross_lanes("X_tube_co50_to_gong", tube_frame("co_50cm"), metal_frame("gong"),
                             "tube_resonances.json + metallic_modes.json"))
    render_lanes(cross_lanes("X_uw_to_comb953", vowel_frame("uw"), comb_frame(953.0),
                             "vowel_formants.json + tube f0"))
    render_lanes(cross_lanes("X_clampedbar_to_jug", metal_frame("clamped_bar"), cavity_frame("plastic_jug"),
                             "metallic_modes.json + family_intents.json cavity"))
    render_lanes(cross_lanes("X_vowel_ih_to_freeplate", vowel_frame("ih"), metal_frame("free_plate"),
                             "vowel_formants.json + metallic_modes.json"))
    render_lanes(cross_lanes("X_vowel_eh_to_masonjar", vowel_frame("eh"), cavity_frame("mason_jar"),
                             "vowel_formants.json + family_intents.json cavity"))
    render_lanes(cross_lanes("X_bathtub_to_vowel_uh", cavity_frame("bathtub"), vowel_frame("uh"),
                             "family_intents.json cavity + vowel_formants.json"))
    render_lanes(cross_lanes("X_beerbottle_to_vowel_uu", cavity_frame("beer_bottle"), vowel_frame("uu"),
                             "family_intents.json cavity + vowel_formants.json"))
    render_lanes(cross_lanes("X_stonepipe_to_co25cm", cavity_frame("stone_pipe"), tube_frame("co_25cm"),
                             "family_intents.json cavity + tube_resonances.json"))

    # same-object keepers
    render_lanes(vow_lanes("aa", "iy"))
    render_lanes(vow_lanes("uw", "ae"))
    render_lanes(vow_lanes("ih", "uu"))
    render_lanes(vow_lanes("eh", "ao"))
    render_lanes(riser_lanes("low_carve", "high_razor"))
    render_lanes(cavity_lanes("wine_bottle", "tin_can"))
    render_lanes(cavity_lanes("beer_bottle", "mason_jar"))
    render_lanes(cavity_lanes("stone_pipe", "bathtub"))
    render_lanes(tube_lanes("oo_50cm", "oo_10cm"))
    render_lanes(tube_lanes("co_25cm", "co_18cm"))
    render_lanes(metal_lanes("free_plate"))
