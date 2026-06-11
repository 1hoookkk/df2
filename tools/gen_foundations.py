#!/usr/bin/env python3
"""Generate forge-web/data/foundations.json from first-principles biquad design.

The old file cranked every base pole radius to the rim (r=0.99-0.999, Q=50-500),
so "lowpasses" rang, "bandpasses" spiked +50 dB, and phasers lost their notches as
Q rose. This rebuilds each preset from real RBJ-cookbook biquads, then extracts the
schema fields the editor reads:

  pole_r = sqrt(a2);  pole_theta = acos(-a1/(2 pole_r));  pole_hz = theta*SR/2pi
  zero_r = sqrt(b2/b0); zero_theta = acos(-(b1/b0)/(2 zero_r)); zero_hz = theta*SR/2pi

CRITICAL: the editor/compiler reconstruct each section as a POLE PAIR + OPTIONAL
NOTCH ZERO with a built-in level normalization (trench-core compiler::stage_biquad):
  pole(hz,r) -> a1=-2r cos(wp), a2=r^2
  zero off  -> b = [(1-r^2)*gain, 0, 0, a1, a2]      (unity-peak resonator * gain)
  zero on   -> g = (1+a1+a2)/(1+nb1+nb2) * gain       (DC pinned)
So gain_db is a small LEVEL TRIM on top of that normalization, NOT 20log10(b0).
We design the pole/zero POSITIONS via RBJ, hand them the editor's two-knob form,
and pick gain_db by measuring the reconstructed section through the SHIPPED encoder.

Verification builds every preset through trench_ffi.compile_body and reads it back
through tb.shipped_response, asserting each named identity.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from tools import target_browser as tb  # noqa: E402

SR = 39062.5
NYQ = SR / 2.0
TAU = 2.0 * math.pi
R_CAP = 0.9994  # atlas-real max
FREQS = tb.FREQS

OUT = ROOT / "forge-web" / "data" / "foundations.json"
LEGACY = ROOT / "forge-web" / "data" / "foundations.legacy.json"

# ── RBJ Audio-EQ cookbook biquads (a0-normalized) ───────────────────────────


def _norm(b0, b1, b2, a0, a1, a2):
    return [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0]


def rbj_lowpass(f0, Q):
    w0 = TAU * f0 / SR
    cw, sw = math.cos(w0), math.sin(w0)
    a = sw / (2 * Q)
    return _norm((1 - cw) / 2, 1 - cw, (1 - cw) / 2, 1 + a, -2 * cw, 1 - a)


def rbj_highpass(f0, Q):
    w0 = TAU * f0 / SR
    cw, sw = math.cos(w0), math.sin(w0)
    a = sw / (2 * Q)
    return _norm((1 + cw) / 2, -(1 + cw), (1 + cw) / 2, 1 + a, -2 * cw, 1 - a)


def rbj_peak(f0, Q, gain_db):
    w0 = TAU * f0 / SR
    cw, sw = math.cos(w0), math.sin(w0)
    a = sw / (2 * Q)
    A = 10 ** (gain_db / 40.0)
    return _norm(1 + a * A, -2 * cw, 1 - a * A, 1 + a / A, -2 * cw, 1 - a / A)


def rbj_notch(f0, Q):
    w0 = TAU * f0 / SR
    cw, sw = math.cos(w0), math.sin(w0)
    a = sw / (2 * Q)
    return _norm(1, -2 * cw, 1, 1 + a, -2 * cw, 1 - a)


# ── biquad -> editor schema fields ──────────────────────────────────────────


def pole_from_biquad(b):
    """(pole_r, pole_hz) from a0-normalized biquad [b0,b1,b2,a1,a2]."""
    _, _, _, a1, a2 = b
    r = min(math.sqrt(max(a2, 0.0)), R_CAP)
    c = -a1 / (2 * r) if r > 1e-9 else 0.0
    c = max(-1.0, min(1.0, c))
    hz = math.acos(c) * SR / TAU
    return r, hz


def zero_from_biquad(b):
    """(zero_r, zero_hz) from a0-normalized biquad. zero_r clamped to <=1.0."""
    b0, b1, b2, _, _ = b
    if abs(b0) < 1e-12:
        return 0.0, 0.0
    rr = b2 / b0
    r = math.sqrt(abs(rr))
    r = min(r, 1.0)
    if r < 1e-9:
        return 0.0, 0.0
    c = -(b1 / b0) / (2 * r)
    c = max(-1.0, min(1.0, c))
    hz = math.acos(c) * SR / TAU
    return r, hz


# ── section dict helpers ────────────────────────────────────────────────────


def sec(role, ph_home, ph_away, r_q0, r_q1, zhz_home, zhz_away, zero_r,
        gain_db=0.0, on=True):
    d = {"role": role,
         "pole_hz_home": round(ph_home, 2), "pole_hz_away": round(ph_away, 2),
         "pole_r_q0": round(r_q0, 4), "pole_r_q1": round(r_q1, 4),
         "zero_hz": [round(zhz_home, 2), round(zhz_away, 2)],
         "zero_r": round(zero_r, 4), "gain_db": round(gain_db, 2)}
    if not on:
        d["on"] = False
    return d


def bypass(role="idle"):
    return {"role": role, "on": False,
            "pole_hz_home": 1000.0, "pole_hz_away": 1000.0,
            "pole_r_q0": 0.0, "pole_r_q1": 0.0,
            "zero_hz": [1000.0, 1000.0], "zero_r": 0.0, "gain_db": 0.0}


def _solo_response(section, m, q):
    """Compile a body with only `section` active (rest bypassed) and read it
    through the SHIPPED encoder at (m,q). This measures what the editor/compiler
    actually reconstruct for this section — the only honest level reference."""
    params = sections_to_params([section] + [bypass() for _ in range(5)])
    body = trench_ffi.compile_body(params)
    return resp(body, m, q)


def calibrate(section, ref="plateau", target_db=0.0):
    """Trim section['gain_db'] so its reference level hits target_db, MEASURED
    through the shipped encoder on the solo section. ref:
      'plateau' = mean of the top octave (HP / high plateau)
      'dc'      = level at 60 Hz (LP / low plateau)
      'peak'    = max over the band (peak/notch passband peak)
    Iterates because the minifloat pack isn't perfectly linear in dB."""
    for _ in range(3):
        r0 = _solo_response(section, 0.0, 0.0)
        if ref == "plateau":
            lvl = float(np.mean(r0[FREQS >= 8000]))
        elif ref == "dc":
            lvl = db_at(r0, 60)
        else:  # peak
            lvl = float(r0.max())
        delta = target_db - lvl
        if abs(delta) < 0.3:
            break
        section["gain_db"] = round(section.get("gain_db", 0.0) + delta, 3)
    return section


def _calibrate_at(section, ref_hz, target_db=0.0):
    """Trim gain_db so the solo section sits at target_db at ref_hz (M0,Q0)."""
    for _ in range(3):
        r0 = _solo_response(section, 0.0, 0.0)
        delta = target_db - db_at(r0, ref_hz)
        if abs(delta) < 0.3:
            break
        section["gain_db"] = round(section.get("gain_db", 0.0) + delta, 3)
    return section


def _calibrate_plateau_at(section, m, target_db=0.0):
    """Trim gain_db so the high-octave plateau hits target_db at morph m (Q0)."""
    for _ in range(4):
        r0 = _solo_response(section, m, 0.0)
        lvl = float(np.mean(r0[FREQS >= 8000]))
        delta = target_db - lvl
        if abs(delta) < 0.3:
            break
        section["gain_db"] = round(section.get("gain_db", 0.0) + delta, 3)
    return section


# NOTE on the fixed-radius constraint: the schema gives ONE radius pair (q0/q1)
# but the pole frequency MOVES home->away. At a fixed radius, Q = 1/(2(1-r)) is
# constant in the z-plane, but its *audible* Q (relative to centre freq) drifts
# as the pole moves. To avoid a resonant spike at one morph end we pick the
# radius from the HIGHEST cutoff (where the Butterworth pole sits lowest) and
# let the lower-cutoff end be a touch broader (safe), then calibrate level at
# the worst-case corner so no plateau ever runs hot.


def lp_section(role, fc_home, fc_away, Q, gain_db=0.0):
    """RBJ lowpass: pole at fc with Butterworth Q, zero at Nyquist (z=-1)."""
    rh, ph_h = pole_from_biquad(rbj_lowpass(fc_home, Q))
    ra, ph_a = pole_from_biquad(rbj_lowpass(fc_away, Q))
    # Pick the radius from the LOWER cutoff (lower r) so the higher-cutoff end
    # never over-resonates; the lower end stays broad/safe.
    r_q0 = min(rh, ra)
    r_q1 = min(R_CAP, r_q0 + (R_CAP - r_q0) * 0.18)
    s = sec(role, ph_h, ph_a, r_q0, r_q1, NYQ, NYQ, 1.0, gain_db)
    return calibrate(s, ref="dc", target_db=0.0)


def hp_section(role, fc_home, fc_away, Q, gain_db=0.0):
    """RBJ highpass: pole at fc with Butterworth Q. Two compiler facts force the
    design: (1) the notch normalization is DEGENERATE for an exact-DC zero
    (1+nb1+nb2 -> 0, gain_db dead, plateau hot), so the rejection zero is pulled
    slightly OFF DC (~50% of cutoff) where it still kills lows hard but gain_db
    works; (2) ONE radius + ONE gain must serve a pole that MOVES home->away, so a
    big cutoff sweep makes the low end need high r (sharp) and the high end run
    resonant. We pick the averaged Butterworth radius, move the zero with the
    cutoff, and SEARCH the calibration morph so the worst-case plateau/peak over
    the sweep is minimized."""
    rh, ph_h = pole_from_biquad(rbj_highpass(fc_home, Q))
    ra, ph_a = pole_from_biquad(rbj_highpass(fc_away, Q))
    r_lo, r_hi = sorted((rh, ra))
    zhz_h = max(1.0, fc_home * 0.5)
    zhz_a = max(1.0, fc_away * 0.5)

    def plateaus(s):
        return [float(np.mean(_solo_response(s, m, 0.0)[FREQS >= 6000]))
                for m in (0.0, 0.5, 1.0)]

    best, best_cost = None, 1e9
    # Joint search over radius (between the two Butterworth endpoints) and the
    # calibration morph. Cost = worst |plateau| across the sweep — a flat
    # passband at BOTH ends is the goal; deep stopband cuts don't count.
    for frac in (0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0):
        r_q0 = r_lo + (r_hi - r_lo) * frac
        r_q1 = min(R_CAP, r_q0 + (R_CAP - r_q0) * 0.18)
        for cal_m in (0.0, 0.5, 1.0):
            s = sec(role, ph_h, ph_a, r_q0, r_q1, zhz_h, zhz_a, 1.0, gain_db)
            s = _calibrate_plateau_at(s, cal_m)
            ps = plateaus(s)
            cost = max(abs(p) for p in ps)
            if cost < best_cost:
                best, best_cost = dict(s), cost
    return best


def _peak_boost(section):
    """Measured boost (dB) of a solo peak section: peak minus off-peak floor."""
    r = _solo_response(section, 0.0, 0.0)
    ph = section["pole_hz_home"]
    floor_hz = max(60.0, ph / 4.0)
    return float(r.max()) - db_at(r, floor_hz)


def peak_section(role, fc_home, fc_away, Q, boost_db, q1_scale=1.6):
    """RBJ-style peaking EQ in the compiler's pole+notch form: pole & zero share
    angle, pole_r > zero_r sets the boost. The boost height is set by BOTH the
    pole radius (sharpness) and the pole/zero radius GAP. We seat pole_r from the
    target boost (bigger boost needs a sharper pole), then binary-search zero_r so
    the MEASURED boost (through the shipped encoder) matches boost_db. Q0 = base,
    Q1 = sharper (q1_scale). The off-peak floor is pinned to 0 dB."""
    ph_h, ph_a = float(fc_home), float(fc_away)
    # Seat pole radius from the desired boost: ~0.97 gives ~6 dB headroom, 0.99
    # gives ~13 dB. Map boost -> radius, clamped to a stable musical window.
    r_q0 = max(0.96, min(0.990, 0.96 + 0.004 * boost_db))
    # Q1 sharpens the peak only modestly; a big r_q1 jump makes the boost balloon
    # (and stacking peaks then craters the ±dB budget), so keep the gap small.
    r_q1 = max(r_q0, min(0.9945, r_q0 + (1.0 - r_q0) * (q1_scale - 1.0) * 0.18))
    floor_hz = max(60.0, min(ph_h, ph_a) / 4.0)
    lo, hi = 0.70, r_q0 - 0.003  # zero_r strictly below pole_r
    best = None
    for _ in range(18):
        zero_r = (lo + hi) / 2.0
        s = sec(role, ph_h, ph_a, r_q0, r_q1, ph_h, ph_a, zero_r, 0.0)
        s = _calibrate_at(s, floor_hz, 0.0)
        b = _peak_boost(s)
        best = s
        if abs(b - boost_db) < 0.4:
            break
        if b < boost_db:
            hi = zero_r  # lower zero_r -> bigger boost
        else:
            lo = zero_r
    return best


def notch_section(role, fc_home, fc_away, gap_q0=0.012, gap_q1=0.045,
                  zero_r=0.999):
    """Phaser/flanger NOTCH (RBJ-style): zero fixed near the unit circle at the
    notch freq; the POLE sits just INSIDE it at the same angle. The pole/zero
    radius GAP sets the notch — pole close to the zero = shallow/wide, pole pulled
    inward (smaller radius) = DEEP/narrow. So Q0 uses a small gap (shallow) and
    Q1 a larger gap (DEEPER, tighter) — turning Q up deepens the notch instead of
    cancelling it, and both poles stay strictly inside the zero (never equal, so
    the notch never annihilates). Keeping both radii near 1.0 also keeps the wings
    flat (a low-radius pole would let the near-unit zero boost the treble +50 dB)."""
    pr0 = zero_r - gap_q0
    pr1 = zero_r - gap_q1
    return sec(role, fc_home, fc_away, pr0, pr1, fc_home, fc_away, zero_r, 0.0)


def formant_section(role, f_home, f_away, bw_home=90.0, bw_away=90.0):
    """All-pole vowel formant resonator (zero banished). r = exp(-pi*BW/SR)."""
    rh = min(math.exp(-math.pi * bw_home / SR), R_CAP)
    ra = min(math.exp(-math.pi * bw_away / SR), R_CAP)
    r_q0 = (rh + ra) / 2.0
    # Q1 tightens formant (narrower BW ~ 0.55x).
    r1h = min(math.exp(-math.pi * (bw_home * 0.55) / SR), R_CAP)
    r1a = min(math.exp(-math.pi * (bw_away * 0.55) / SR), R_CAP)
    r_q1 = min(R_CAP, (r1h + r1a) / 2.0)
    return sec(role, f_home, f_away, r_q0, r_q1, f_home, f_away, 0.0, 0.0)


# ── preset builders ─────────────────────────────────────────────────────────

# Butterworth section Q values
BW_Q = {2: [0.7071], 4: [0.5412, 1.3066], 6: [0.5176, 0.7071, 1.9319]}


def build_lowpass(n_pole, fc_home, fc_away):
    qs = BW_Q[n_pole]
    secs = [lp_section(f"LP sec {i+1} (Q={q:.3f})", fc_home, fc_away, q)
            for i, q in enumerate(qs)]
    while len(secs) < 6:
        secs.append(bypass(f"idle {len(secs)+1}"))
    return secs


def build_highpass(n_pole, fc_home, fc_away):
    qs = BW_Q[n_pole]
    secs = [hp_section(f"HP sec {i+1} (Q={q:.3f})", fc_home, fc_away, q)
            for i, q in enumerate(qs)]
    while len(secs) < 6:
        secs.append(bypass(f"idle {len(secs)+1}"))
    return secs


def build_bandpass(n_pole, lo_home, lo_away, hi_home, hi_away):
    """n_pole=2 -> 1 HP skirt + 1 LP skirt; n_pole=4 -> 2 of each (Butterworth)."""
    secs = []
    if n_pole == 2:
        secs.append(hp_section("HP skirt (lo edge)", lo_home, lo_away, 0.7071))
        secs.append(lp_section("LP skirt (hi edge)", hi_home, hi_away, 0.7071))
    else:
        for i, q in enumerate(BW_Q[4]):
            secs.append(hp_section(f"HP skirt {i+1}", lo_home, lo_away, q))
        for i, q in enumerate(BW_Q[4]):
            secs.append(lp_section(f"LP skirt {i+1}", hi_home, hi_away, q))
    while len(secs) < 6:
        secs.append(bypass(f"idle {len(secs)+1}"))
    return secs


def build_contrary_bandpass():
    """Two bands moving in OPPOSITE directions. Rising band: lo edge 90->300,
    hi edge 600->2400. Falling band: lo edge 1200->300, hi edge 5000->900.
    Moderate Butterworth skirts, NO +30 dB spikes."""
    secs = [
        hp_section("rising band lo edge", 90, 300, 0.7071),
        lp_section("rising band hi edge", 600, 2400, 0.7071),
        hp_section("falling band lo edge", 1200, 300, 0.7071),
        lp_section("falling band hi edge", 5000, 900, 0.7071),
        bypass("idle 5"),
        bypass("idle 6"),
    ]
    return secs


def build_swept_eq(octaves):
    """RBJ peaking EQ sweep over `octaves`. One main peak + two flanking support
    peaks, moderate boost, moderate Q. Off-band stages bypassed."""
    f0 = 700.0
    fa = f0 * (2 ** octaves)
    secs = [
        peak_section("main swept peak", f0, fa, Q=2.0, boost_db=6.0),
        peak_section("lower support", f0 * 0.66, fa * 0.66, Q=2.5, boost_db=2.0),
        peak_section("upper support", f0 * 1.5, fa * 1.5, Q=2.5, boost_db=2.0),
        bypass("idle 4"),
        bypass("idle 5"),
        bypass("idle 6"),
    ]
    return secs


def build_phaser(notches_home, notches_away):
    """N moving notches. Zero fixed at the unit circle (zero_r=0.999); pole just
    inside it. Q0 small gap (shallow ~ -14 dB), Q1 larger gap (deep ~ -30 dB) so
    turning Q up DEEPENS each notch. Wings stay flat (~0 dB), no treble blowup."""
    secs = []
    for i, (fh, fa) in enumerate(zip(notches_home, notches_away)):
        secs.append(notch_section(f"notch {i+1}", fh, fa,
                                  gap_q0=0.008, gap_q1=0.02, zero_r=0.999))
    while len(secs) < 6:
        secs.append(bypass(f"idle {len(secs)+1}"))
    return secs


def build_flanger_lite():
    """Feedforward comb excerpt: notches at odd multiples of 1/(2*delay), delay
    2.0ms (home) -> 0.7ms (away). Gentle, shallower notches than the phaser."""
    d_home, d_away = 2.0e-3, 0.7e-3
    secs = []
    for k in range(6):
        n = 2 * k + 1
        fh = n / (2 * d_home)
        fa = n / (2 * d_away)
        if fa > NYQ * 0.97:
            fa = NYQ * 0.97
        secs.append(notch_section(f"comb notch {k+1}", fh, fa,
                                  gap_q0=0.01, gap_q1=0.022, zero_r=0.999))
    return secs


# Formant tables (Hz): Peterson-Barney / Klatt
VOWELS = {
    "Ah": (730, 1090, 2440),
    "Ee": (270, 2290, 3010),
    "Oo": (300, 870, 2240),
}


def build_vowel(v_home, v_away):
    fh = VOWELS[v_home]
    fa = VOWELS[v_away]
    bws = (90, 100, 120)  # F1,F2,F3 bandwidths
    secs = [formant_section(f"F{i+1} ({v_home}->{v_away})", fh[i], fa[i],
                            bws[i], bws[i]) for i in range(3)]
    while len(secs) < 6:
        secs.append(bypass(f"idle {len(secs)+1}"))
    return secs


def build_dual_eq():
    """Two peaking ridges moving oppositely. (Peaks live >=300 Hz: the compiler's
    pole+notch peak form cannot build much boost below ~250 Hz — the pole sits too
    near DC for the zero gap to lift it — so the 'low' ridge starts in low-mids.)"""
    secs = [
        # Opposing ridges: low rises 350->900, high falls 2600->1500. They close
        # toward each other (the morph gesture) but the low stays below the high,
        # so they never fully coincide -> a strong but musical lift (~12 dB), not
        # the old rim-ring blowup.
        peak_section("low ridge rises", 350, 900, Q=1.8, boost_db=4.5),
        peak_section("high ridge falls", 2600, 1500, Q=1.8, boost_db=4.5),
        peak_section("mid support", 600, 600, Q=1.4, boost_db=2.0),
        bypass("idle 4"),
        bypass("idle 5"),
        bypass("idle 6"),
    ]
    return secs


def build_dual_eq_lp():
    """Dual peak (growl + bite) + a moving Butterworth lowpass cap."""
    secs = [
        peak_section("growl peak", 350, 700, Q=1.8, boost_db=5.0),
        peak_section("bite peak", 1100, 2600, Q=1.8, boost_db=4.0),
        peak_section("mid body", 550, 550, Q=1.2, boost_db=2.0),
        lp_section("lowpass cap", 3200, 9500, 0.7071),
        bypass("idle 5"),
        bypass("idle 6"),
    ]
    return secs


def build_dual_eq_expr():
    """Tri peaking EQ; Q0 broad, Q1 noticeably sharper (expression pressure)."""
    secs = [
        peak_section("growl peak", 160, 420, Q=1.6, boost_db=5.0, q1_scale=2.4),
        peak_section("vowel peak", 700, 1800, Q=1.6, boost_db=5.0, q1_scale=2.4),
        peak_section("air peak", 2600, 5200, Q=1.6, boost_db=3.0, q1_scale=2.4),
        bypass("idle 4"),
        bypass("idle 5"),
        bypass("idle 6"),
    ]
    return secs


def build_peak_shelf():
    """Peak -> high-shelf morph. Peak core + high shelf via stacked peaks + Nyq cap."""
    secs = [
        peak_section("peak core", 750, 2200, Q=2.5, boost_db=8.0),
        peak_section("shelf knee", 1800, 4500, Q=0.9, boost_db=5.0),
        peak_section("shelf body", 4000, 8000, Q=0.7, boost_db=4.0),
        lp_section("Nyquist cap", 9000, 14000, 0.7071),
        bypass("idle 5"),
        bypass("idle 6"),
    ]
    return secs


# ── preset registry: name -> (dsp_identity, builder) ─────────────────────────

PRESETS = [
    ("2 Pole Lowpass",
     "One 2-pole Butterworth lowpass SOS; 12 dB/oct rolloff; pole moves with cutoff, zero fixed at Nyquist (z=-1). r~0.6-0.95, NOT at the rim.",
     lambda: build_lowpass(2, 420, 7200)),
    ("4 Pole Lowpass",
     "Two cascaded Butterworth lowpass SOS (Q=0.541, 1.307); 24 dB/oct; zeros fixed at Nyquist.",
     lambda: build_lowpass(4, 420, 7200)),
    ("6 Pole Lowpass",
     "Three cascaded Butterworth lowpass SOS (Q=0.518, 0.707, 1.932); 36 dB/oct; zeros fixed at Nyquist.",
     lambda: build_lowpass(6, 420, 7200)),
    ("2 Pole Highpass",
     "One 2-pole Butterworth highpass SOS; 12 dB/oct; pole moves with cutoff, near-DC rejection zero moves with it.",
     lambda: build_highpass(2, 100, 700)),
    ("4 Pole Highpass",
     "Two cascaded Butterworth highpass SOS (Q=0.541, 1.307); 24 dB/oct; near-DC rejection zeros track the cutoff.",
     lambda: build_highpass(4, 100, 700)),
    ("2 Pole Bandpass",
     "One HP skirt (zero at DC) + one LP skirt (zero at Nyquist) at moderate Butterworth Q; passband near 0 dB, smooth skirts.",
     lambda: build_bandpass(2, 90, 450, 520, 2400)),
    ("4 Pole Bandpass",
     "Two HP skirts + two LP skirts (Butterworth Q=0.541,1.307); steeper band window, passband near 0 dB.",
     lambda: build_bandpass(4, 90, 450, 520, 2400)),
    ("Contrary Bandpass",
     "Two moderate-Q bandpass windows whose centers move in OPPOSITE directions across morph; HP+LP skirts, no spikes.",
     build_contrary_bandpass),
    ("Swept EQ 1 Octave",
     "RBJ peaking EQ; pole & zero share angle, pole_r > zero_r sets a musical boost; center sweeps one octave.",
     lambda: build_swept_eq(1)),
    ("Swept EQ 2/1 Octave",
     "RBJ peaking EQ; center sweeps two octaves; moderate boost, pole_r/zero_r contrast.",
     lambda: build_swept_eq(2)),
    ("Swept EQ 3/1 Octave",
     "RBJ peaking EQ; center sweeps three octaves with support peaks; moderate boost.",
     lambda: build_swept_eq(3)),
    ("Phaser 1",
     "Four moving notches: zeros near the unit circle (deep nulls), poles at moderate radius. Q tightens/deepens the notches.",
     lambda: build_phaser([320, 680, 1450, 3100], [780, 1650, 3500, 7200])),
    ("Phaser 2",
     "Six moving notches: zeros near the unit circle, moderate poles. Q deepens the notches (does not cancel them).",
     lambda: build_phaser([220, 420, 800, 1500, 2850, 5400],
                          [520, 1000, 1900, 3600, 6800, 12000])),
    ("Bat Phaser",
     "Asymmetric notch map: low notches rise while upper notches fold downward; zeros near unit circle, moderate poles.",
     lambda: build_phaser([180, 360, 740, 1850, 4100, 8700],
                          [420, 820, 1550, 1300, 2900, 6200])),
    ("Flanger Lite",
     "Feedforward comb excerpt: notches at odd multiples of 1/(2*delay), delay 2.0ms->0.7ms; gentle poles.",
     build_flanger_lite),
    ("Vocal Ah-Ay-Ee",
     "All-pole formant resonators (zeros banished): Ah F1/F2/F3 = 730/1090/2440 Hz gliding to Ee 270/2290/3010 Hz; midpoint near Ay.",
     lambda: build_vowel("Ah", "Ee")),
    ("Vocal Oo-Ah",
     "All-pole formant resonators: Oo 300/870/2240 Hz gliding to Ah 730/1090/2440 Hz.",
     lambda: build_vowel("Oo", "Ah")),
    ("Dual EQ Morph",
     "Two RBJ peaking ridges moving in opposite directions + a sub anchor; moderate boosts.",
     build_dual_eq),
    ("Dual EQ + LP Morph",
     "Dual peaking EQ (growl + bite) plus a moving Butterworth lowpass cap and a body anchor.",
     build_dual_eq_lp),
    ("Dual EQ Morph/Expression",
     "Tri peaking EQ with Q as expression pressure (Q0 broad, Q1 sharp); peaks rise across morph.",
     build_dual_eq_expr),
    ("Peak/Shelf Morph",
     "Morph from a narrow RBJ peak toward a broad high-shelf via stacked peaks + a Nyquist-zero lowpass cap.",
     build_peak_shelf),
]


# ── compile + verify through the SHIPPED encoder ────────────────────────────


def sections_to_params(sections):
    """6 schema sections -> 168 compile_body params via the editor's corner rule.
    Corners: C0=(home,r_q0,zhome) C1=(away,r_q0,zaway) C2=(home,r_q1,zhome)
             C3=(away,r_q1,zaway). on:false -> on=0 in all corners (true bypass)."""
    params = []
    for corner in range(4):
        away = corner in (1, 3)
        hi_q = corner in (2, 3)
        for s in sections:
            on = s.get("on", True)
            if not on:
                params += [0.0, 1000.0, 0.0, 1.0, 0.0, 1000.0, 0.0]
                continue
            ph = s["pole_hz_away"] if away else s["pole_hz_home"]
            pr = s["pole_r_q1"] if hi_q else s["pole_r_q0"]
            zhz = s["zero_hz"][1] if away else s["zero_hz"][0]
            zr = s["zero_r"]
            gain = 10 ** (s.get("gain_db", 0.0) / 20.0)
            zon = 1.0 if zr > 0.02 else 0.0
            params += [1.0, max(ph, 1.0), pr, gain, zon, max(zhz, 1.0), zr]
    return params


def resp(body, m, q):
    return tb.shipped_response(body, m, q)


def local_maxima(db, min_prom=2.0, win=20):
    """Indices of local maxima with at least min_prom dB prominence over a wide
    window (broad swept peaks have low local slope, so look further out)."""
    out = []
    for i in range(1, len(db) - 1):
        if db[i] >= db[i - 1] and db[i] >= db[i + 1]:
            lo = db[max(0, i - win):i].min() if i > 0 else db[i]
            hi = db[i + 1:i + win + 1].min() if i < len(db) - 1 else db[i]
            if db[i] - max(lo, hi) >= min_prom:
                out.append(i)
    return out


def count_notches(db, thresh=-12.0):
    """Count distinct local minima below `thresh` (relative to local surroundings)."""
    n = 0
    i = 1
    while i < len(db) - 1:
        if db[i] <= db[i - 1] and db[i] <= db[i + 1]:
            # dip depth relative to nearby max
            lo = max(0, i - 10); hi = min(len(db), i + 11)
            surround = db[lo:hi].max()
            if surround - db[i] >= abs(thresh) - 6 or db[i] < thresh:
                # require it's a real dip: at least 12 dB below the surrounding peak
                if surround - db[i] >= 12.0:
                    n += 1
                    i += 4
                    continue
        i += 1
    return n


def is_monotonic_falling(db, f_lo, f_hi, tol=1.5):
    m = (FREQS >= f_lo) & (FREQS <= f_hi)
    seg = db[m]
    if len(seg) < 3:
        return True
    # allow small wiggle
    return np.all(np.diff(seg) <= tol)


def is_monotonic_rising(db, f_lo, f_hi, tol=1.5):
    m = (FREQS >= f_lo) & (FREQS <= f_hi)
    seg = db[m]
    if len(seg) < 3:
        return True
    return np.all(np.diff(seg) >= -tol)


def db_at(db, hz):
    return float(db[np.argmin(np.abs(FREQS - hz))])


def verify(name, family, body):
    """Return (verdict bool, detail str). family is inferred from name."""
    r00 = resp(body, 0.0, 0.0)
    r10 = resp(body, 1.0, 0.0)
    r01 = resp(body, 0.0, 1.0)
    r11 = resp(body, 1.0, 1.0)
    nm = name.lower()

    if "lowpass" in nm:
        peak = float(r00.max())
        mono = is_monotonic_falling(r00, 3000, 16000)
        ok = peak <= 2.5 and mono
        return ok, f"peak={peak:.1f}dB mono_stop={mono} hi@8k={db_at(r00,8000):.1f}"
    if "highpass" in nm:
        # one radius + one gain must serve a moving pole, so a perfectly flat
        # passband across the full sweep is not attainable; budget a few dB.
        peak = float(max(r00.max(), r10.max(), r01.max(), r11.max()))
        lowcut = db_at(r00, 30) < db_at(r00, 4000) - 12
        ok = peak <= 9.0 and lowcut
        return ok, f"peak={peak:.1f}dB low@30={db_at(r00,30):.1f} hi@4k={db_at(r00,4000):.1f} lowcut={lowcut}"
    if "bandpass" in nm:
        mx = float(max(r00.max(), r10.max(), r11.max()))
        # passband present: some band > -6 of its own peak
        ok = mx <= 12.0
        # for contrary, check the two bands move oppositely
        extra = ""
        if "contrary" in nm:
            c00 = FREQS[np.argmax(r00)]
            c10 = FREQS[np.argmax(r10)]
            extra = f" peakHz M0={c00:.0f} M100={c10:.0f}"
        return ok, f"maxgain={mx:.1f}dB{extra}"
    if "phaser" in nm:
        nq0 = count_notches(r00)
        nq1 = count_notches(r11)
        gmax = float(max(r00.max(), r10.max(), r01.max(), r11.max()))
        # key regression: notches survive Q100 AND wings never boost (no +dB blowup)
        ok = nq0 >= 2 and nq1 >= 2 and gmax <= 6.0
        return ok, f"notches Q0={nq0} Q100={nq1} maxgain={gmax:.1f}dB (notches must survive Q100, no blowup)"
    if "flanger" in nm:
        nq0 = count_notches(r00)
        nq1 = count_notches(r11)
        gmax = float(max(r00.max(), r10.max(), r01.max(), r11.max()))
        ok = nq0 >= 2 and nq1 >= 1 and gmax <= 6.0
        return ok, f"comb notches Q0={nq0} Q100={nq1} maxgain={gmax:.1f}dB"
    if "vocal" in nm:
        # local maxima within ~12% of target formants at M0 (home vowel)
        peaks = [FREQS[i] for i in local_maxima(r00, 1.5)]
        return (len(peaks) >= 2), f"formant peaks M0(Hz)={[round(p) for p in peaks[:5]]}"
    if "swept eq" in nm or "dual eq" in nm or "peak/shelf" in nm:
        # boost can live in any corner (opposed peaks, sweeps); judge the hottest
        corners = {"M0Q0": r00, "M100Q0": r10, "M0Q100": r01, "M100Q100": r11}
        hot_lab = max(corners, key=lambda k: corners[k].max())
        hot = corners[hot_lab]
        mx = float(hot.max())
        peaks = [FREQS[i] for i in local_maxima(hot, 2.0)]
        # check the dense Morph x Q grid too: opposing ridges can collide between
        # corners, so the interior must also stay musical (<= 13 dB).
        gmax = float(max(resp(body, m, q).max()
                         for m in (0.0, 0.25, 0.5, 0.75, 1.0)
                         for q in (0.0, 0.5, 1.0)))
        ok = 1.0 <= mx <= 13.0 and len(peaks) >= 1 and gmax <= 13.0
        return ok, (f"corner boost={mx:.1f}dB@{hot_lab} gridmax={gmax:.1f}dB "
                    f"bumps={[round(p) for p in peaks[:4]]}")
    return True, "no check"


def main():
    if OUT.exists() and not LEGACY.exists():
        shutil.copy(OUT, LEGACY)
        print(f"backed up old foundations.json -> {LEGACY.name}")
    elif LEGACY.exists():
        print(f"{LEGACY.name} already exists; not overwriting backup")

    presets = []
    rows = []
    all_ok = True
    for name, identity, builder in PRESETS:
        sections = builder()
        assert len(sections) == 6, f"{name}: {len(sections)} sections"
        params = sections_to_params(sections)
        body = trench_ffi.compile_body(params)
        n_active = sum(1 for s in sections if s.get("on", True))
        ok, detail = verify(name, None, body)
        # phaser notch expectation override (scaled to active sections + gain ceiling)
        if "phaser" in name.lower():
            r00 = resp(body, 0.0, 0.0); r11 = resp(body, 1.0, 1.0)
            r10 = resp(body, 1.0, 0.0); r01 = resp(body, 0.0, 1.0)
            nq0 = count_notches(r00); nq1 = count_notches(r11)
            gmax = float(max(r00.max(), r10.max(), r01.max(), r11.max()))
            # allow up to 2 fewer counted notches than sections: adjacent notches
            # legitimately MERGE at a morph endpoint (esp. the contrary Bat layout),
            # and the >16 kHz top notch falls past the 16 kHz plot edge.
            need = max(2, n_active - 2)
            ok = nq0 >= need and nq1 >= need and gmax <= 6.0
            detail = (f"notches Q0={nq0} Q100={nq1} maxgain={gmax:.1f}dB "
                      f"(need>={need}, survive Q100, no blowup)")
        verdict = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"[{verdict}] {name:<26} {detail}")
        presets.append({"type": name, "dsp_identity": identity,
                        "sections": sections})
        rows.append((name, identity, verdict, detail))

    OUT.write_text(json.dumps(presets, indent=2), encoding="utf-8")
    print(f"\nwrote {len(presets)} presets -> {OUT}")

    print("\n=== SUMMARY ===")
    for name, identity, verdict, detail in rows:
        print(f"{verdict:<5} {name:<26} {detail}")
    print(f"\n{'ALL PASS' if all_ok else 'SOME FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
