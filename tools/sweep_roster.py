#!/usr/bin/env python3
"""sweep_roster - overnight roster sweep across the filter-type families, BOLD.

Bold = twin-anchor corners. HOME (M0_Q0) and AWAY (M100_Q0) are INDEPENDENT draws
of the same skeleton (same feature count + bands), not a timid shift of one shape —
so the four corners are genuinely different (like the E-mu presets) yet kin enough
to glide. AWAY leans hotter, so HOME->AWAY spans tame->violent. Q tightens each
anchor into its TIGHT corner. The stability gate still culls blowups; mush is the
ear's call.

Two modes:
  worker:  python -m tools.sweep_roster --sweep <id> --family knock --seeds 7001,7002,7003 --count 48
           -> generate (bold), cull broken, publish survivors, write
              dev/tmp/sweep/<id>/families/<family>.json (+ .md readout).
  merge:   python -m tools.sweep_roster --sweep <id> --merge
           -> read every families/*.json, build ONE master audition.html grouped
              by family (shortlist first), + index.md.

Shortlist ordering is a SOFT pre-sort (advisory-clean + most motion + stable),
never a verdict. The ear chooses; this only makes the morning queue short + ordered.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import random
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HERE = str(Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", _HERE, str(ROOT))]
sys.path.insert(0, str(ROOT))

from tools import target_browser as tb
from tools import make_class_bodies as mc
from pyruntime import trench_ffi
from src.compiler import encode
from src.utils.body240 import CORNER_ORDER

SWEEP_ROOT = ROOT / "dev" / "tmp" / "sweep"
INTENTS_FILE = ROOT / "tables" / "family_intents.json"
LABELS = tb.LABELS
KEY = tb.KEY
FIT_FREQS = tb.FIT_FREQS
AUTH_SR = tb.AUTH_SR
SHORTLIST_K = 16

# safety clamp for intent freqs (the template's band is no longer authoritative
# for freq when an intent is set — intent owns the freq; clamp only against the
# musical/nyquist sanity range)
FREQ_SAFE = (40.0, 16000.0)


def _load_intents():
    try:
        return json.loads(INTENTS_FILE.read_text(encoding="utf-8")).get("families", {})
    except FileNotFoundError:
        return {}


def _smart_pairs(intents, max_oct_dist=0.32):
    """For each ordered (home, away) with home != away, find the named third intent
    whose freq vector best matches their geometric-midpoint. Keep pairs whose third-state
    distance is within `max_oct_dist` (log2 octaves, averaged across slots). The morph
    of these pairs naturally passes through a real named middle — no mush by design."""
    import math as _m
    names = list(intents)
    pairs = []
    for h in names:
        for a in names:
            if h == a:
                continue
            h_f = intents[h]["freqs"]
            a_f = intents[a]["freqs"]
            mid_f = [_m.sqrt(float(hi) * float(ai)) for hi, ai in zip(h_f, a_f)]
            best_c, best_d = None, float("inf")
            for c in names:
                if c == h or c == a:
                    continue
                c_f = intents[c]["freqs"]
                d = sum(abs(_m.log2(mi / float(ci))) for mi, ci in zip(mid_f, c_f)) / len(mid_f)
                if d < best_d:
                    best_c, best_d = c, d
            if best_c and best_d <= max_oct_dist:
                pairs.append((h, a, best_c, round(best_d, 3)))
    return pairs

SWEEP_CLIPS = [
    ("m0_q0.wav", "HOME", "M0 Q0"),
    ("m100_q0.wav", "AWAY", "M100 Q0"),
    ("m0_q100.wav", "TIGHT HOME", "M0 Q100"),
    ("m100_q100.wav", "TIGHT AWAY", "M100 Q100"),
    ("midpoint.wav", "MIDDLE", "M50 Q50"),
    ("morph_sweep.wav", "Morph sweep", "motion"),
    ("q_sweep.wav", "Q sweep", "motion"),
    ("diagonal_sweep.wav", "Diagonal sweep", "motion"),
]


# ── bold twin-anchor generation ──────────────────────────────────────────────

def _push_character(feats, rng, hotter=1.0):
    """Bias structured sweeps toward stronger visible terrain.

    This is intentionally authoring-side only. It does not alter runtime DSP; it
    makes the target curves more mountainous before the existing fitter packs
    them into legal six-row bodies.
    """
    out = []
    for feat in feats:
        f = dict(feat)
        f["gain"] *= rng.uniform(1.18, 1.62) * rng.uniform(1.0, hotter)
        f["bw"] *= rng.uniform(0.68, 0.92)
        out.append(f)
    return out


def _draw_anchor(spec, rng, hotter=1.0):
    """Random anchor — no named intent. Used only when a family has no intent table."""
    return _push_character(tb.sample_features(spec, rng), rng, hotter=hotter)


def _draw_anchor_intent(spec, rng, intent_freqs, hotter=1.0):
    """Anchor pinned to a NAMED intent's frequencies (slot-by-slot, with ~4% log-jitter so
    bodies sharing the same intent pair still vary). Gain / bw / kind still come from the
    template; the intent owns the freq."""
    feats = []
    for slot_freq, f in zip(intent_freqs, spec["features"]):
        jitter = rng.uniform(0.96, 1.04)
        freq = max(FREQ_SAFE[0], min(FREQ_SAFE[1], float(slot_freq) * jitter))
        feats.append({
            "kind": f["kind"],
            "freq": freq,
            "gain": rng.uniform(*f["gain_db"]),
            "bw": rng.uniform(*f["bw_oct"]),
        })
    return _push_character(feats, rng, hotter=hotter)


def generate_bold(spec, seed, count, intents=None, smart_pairs=None):
    """Bold twin-anchor generation. When `intents` is given, each body's HOME and AWAY
    corners are pinned to DIFFERENT named intents — the body has an identity. When
    `smart_pairs` is given, the (home, away) draw is restricted to pairs whose midpoint
    lands on a real named THIRD intent (no random pairings, no mushy middles by design).
    `smart_pairs`: list of (home, away, predicted_mid, oct_dist). Without it: any
    two distinct intents. Without intents at all: random skeleton draws (fallback)."""
    run = tb.RUN_ROOT / f"{spec['name']}_s{seed}"
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)
    q_rule = spec["q_axis_rule"]
    intent_names = list(intents) if intents else []
    cands = []
    for i in range(count):
        rng = random.Random(seed * 1_000_003 + i)
        predicted_mid = None
        if smart_pairs:
            h, a, predicted_mid, _d = rng.choice(smart_pairs)
            home_name, away_name = h, a
            home = _draw_anchor_intent(spec, rng, intents[home_name]["freqs"], hotter=1.0)
            away = _draw_anchor_intent(spec, rng, intents[away_name]["freqs"], hotter=1.30)
        elif intent_names and len(intent_names) >= 2:
            home_name, away_name = rng.sample(intent_names, 2)
            home = _draw_anchor_intent(spec, rng, intents[home_name]["freqs"], hotter=1.0)
            away = _draw_anchor_intent(spec, rng, intents[away_name]["freqs"], hotter=1.30)
        else:
            home_name, away_name = None, None
            home = _draw_anchor(spec, rng, hotter=1.0)
            away = _draw_anchor(spec, rng, hotter=1.30)
        qp = tb.sample_q_params(q_rule, rng)
        corner_feats = {
            "M0_Q0": home,
            "M100_Q0": away,
            "M0_Q100": tb.apply_q(home, q_rule, qp),
            "M100_Q100": tb.apply_q(away, q_rule, qp),
        }
        kern = {}
        for lab in LABELS:
            curve = tb.feats_to_curve(corner_feats[lab], spec["floor_db"], FIT_FREQS)
            kern[lab] = trench_ffi.fit_corner_from_magnitude(
                list(zip(FIT_FREQS.tolist(), curve.tolist())), AUTH_SR)
        body = encode.body_from_kernels([kern[c] for c in CORNER_ORDER])  # ONE encoder (compile_body)
        cw = encode.words_from_body(body)
        corner_words = {KEY[lab]: cw[lab] for lab in LABELS}
        boost = tb.derive_boost(body, spec["level_guidance_db"])
        gate = tb.evaluate_gates(body, corner_feats, spec, boost)
        name = f"cand_{i + 1:02d}"
        cdir = run / name
        cdir.mkdir()
        (cdir / f"{name}.body240").write_bytes(body)
        cart = tb.build_cart(name, corner_words, boost, spec["name"], seed)
        intent_tag = f"{home_name} -> {away_name}" if home_name else "random"
        cart["provenance"] = f"sweep-bold:{spec['name']} twin-anchor:{intent_tag} seed={seed}"
        cart["intent"] = {"home": home_name, "away": away_name} if home_name else None
        (cdir / f"{name}.cart.json").write_text(json.dumps(cart, indent=2), encoding="utf-8")
        (cdir / "report.json").write_text(json.dumps({
            "candidate": name, "template": spec["name"], "seed": seed, "index": i,
            "label": spec["label"],
            "intent": {"home": home_name, "away": away_name, "predicted_mid": predicted_mid},
            "provenance": tb.prov_string(spec, home), "away_prov": tb.prov_string(spec, away),
            "gate": gate}, indent=2), encoding="utf-8")
        if gate["pass"]:
            tb.render_candidate_audio(cdir, body)
        cands.append({"name": name, "body": body, "gate": gate, "dir": cdir,
                      "prov": tb.prov_string(spec, home),
                      "home_intent": home_name, "away_intent": away_name,
                      "predicted_mid": predicted_mid})
    return run, cands


# ── WILD: no template, no intent, no morph rule, no Q rule, no gates ─────────
# Four independent random corners. Bilinear middle is whatever it is. Stability
# and finite values are the only hard limits (the runtime explodes otherwise).

import math as _m
# Dense 48-point log grid across 40Hz–16kHz — ~1/8-octave spacing.
LOG_GRID = [_m.exp(_m.log(40.0) + i * (_m.log(16000.0) - _m.log(40.0)) / 47) for i in range(48)]
# Wider, slightly overlapping focus zones across the bigger grid.
_GRID_ZONES = {
    "low":  LOG_GRID[:20],          # 40 Hz – ~700 Hz
    "mid":  LOG_GRID[14:34],        # ~250 Hz – ~5500 Hz
    "high": LOG_GRID[28:],          # ~2.4 kHz – 16 kHz
    "any":  LOG_GRID,
}
_POLARITIES = [
    ("low",  "high"), ("high", "low"),
    ("low",  "mid"),  ("mid",  "high"),
    ("high", "mid"),  ("mid",  "low"),
    ("any",  "any"),  # full-spectrum draws each side
]


def _draw_grid_corner(rng, focus):
    """STUPID-DENSE: 20–28 razor-narrow features per corner, sampled from the
    log-grid points in `focus` zone. Big gain (20–40 dB), bandwidths 0.02–0.08 oct.
    The factorizer compresses this into its 12-pole budget — all 12 poles end up
    near the unit circle to approximate the razor-narrow targets."""
    pool = _GRID_ZONES[focus]
    n = min(rng.randint(20, 28), len(pool))
    chosen = rng.sample(pool, n)
    feats = []
    for f in chosen:
        feats.append({
            "kind": rng.choices(["peak", "notch"], weights=[3, 2])[0],
            "freq": f,                                     # sit on the grid, no jitter
            "gain": rng.uniform(20.0, 40.0),
            "bw":   _m.exp(rng.uniform(_m.log(0.02), _m.log(0.08))),  # razor only
        })
    return feats, focus


def generate_wild(seed, count):
    run = tb.RUN_ROOT / f"wild_s{seed}"
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)
    cands = []
    import numpy as _np
    for i in range(count):
        rng = random.Random(seed * 1_000_003 + i)
        # Vicious morph: HOME and AWAY draw from spectrally OPPOSITE zones of the
        # log grid. TIGHT corners follow their relaxed counterpart's zone (new draw).
        home_zone, away_zone = rng.choice(_POLARITIES)
        corner_feats = {}
        schemes = {}
        corner_feats["M0_Q0"],    schemes["M0_Q0"]    = _draw_grid_corner(rng, home_zone)
        corner_feats["M100_Q0"],  schemes["M100_Q0"]  = _draw_grid_corner(rng, away_zone)
        corner_feats["M0_Q100"],  schemes["M0_Q100"]  = _draw_grid_corner(rng, home_zone)
        corner_feats["M100_Q100"], schemes["M100_Q100"] = _draw_grid_corner(rng, away_zone)
        floors = {lab: rng.uniform(-30.0, -10.0) for lab in LABELS}
        kern = {}
        for lab in LABELS:
            curve = tb.feats_to_curve(corner_feats[lab], floors[lab], FIT_FREQS)
            kern[lab] = trench_ffi.fit_corner_from_magnitude(
                list(zip(FIT_FREQS.tolist(), curve.tolist())), AUTH_SR)
        body = encode.body_from_kernels([kern[c] for c in CORNER_ORDER])  # ONE encoder (compile_body)
        cw = encode.words_from_body(body)
        corner_words = {KEY[lab]: cw[lab] for lab in LABELS}
        maxr, unstable, nonfinite = tb.grid_stability(body)
        passes = (maxr < 1.0 and unstable == 0 and nonfinite == 0)
        name = f"cand_{i + 1:02d}"
        cdir = run / name
        cdir.mkdir()
        (cdir / f"{name}.body240").write_bytes(body)
        cart = tb.build_cart(name, corner_words, 1.0, "wild", seed)
        cart["provenance"] = (f"wild:structured seed={seed} "
                              f"HOME={schemes['M0_Q0']} AWAY={schemes['M100_Q0']} "
                              f"TH={schemes['M0_Q100']} TA={schemes['M100_Q100']}")
        (cdir / f"{name}.cart.json").write_text(json.dumps(cart, indent=2), encoding="utf-8")
        report = {"candidate": name, "seed": seed, "index": i,
                  "stable": bool(passes), "max_pole_radius": round(maxr, 4),
                  "unstable_mask_pop": int(unstable), "nonfinite_mask_pop": int(nonfinite),
                  "schemes": schemes,
                  "feature_counts": {lab: len(corner_feats[lab]) for lab in LABELS}}
        (cdir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if not passes:
            continue
        tb.render_candidate_audio(cdir, body)
        cs = [tb.centroid(tb.shipped_response(body, m, 0.0)) for m in _np.linspace(0, 1, 12)]
        net = abs(cs[-1] - cs[0])
        path = sum(abs(cs[k + 1] - cs[k]) for k in range(len(cs) - 1))
        terrain = tb.terrain_metrics([
            tb.shipped_response(body, 0.0, 0.0),
            tb.shipped_response(body, 1.0, 0.0),
            tb.shipped_response(body, 0.0, 1.0),
            tb.shipped_response(body, 1.0, 1.0),
        ])
        cands.append({"name": name, "dir": cdir, "max_pole_radius": maxr,
                      "motion": float(net), "path": float(path),
                      "home_scheme": schemes["M0_Q0"], "away_scheme": schemes["M100_Q0"],
                      "terrain": terrain})
    return run, cands


def run_wild(sweep_id, seeds, count):
    fam_dir = SWEEP_ROOT / sweep_id / "families"
    fam_dir.mkdir(parents=True, exist_ok=True)
    survivors = []
    totals = {"generated": 0, "survivors": 0, "broken": 0, "seeds": seeds}
    print(f"[wild] no template, no intent, no morph rule, no Q rule, no gates "
          f"(stability + finite only) — seeds={seeds} count={count}")
    for seed in seeds:
        try:
            _run, cands = generate_wild(seed, count)
        except Exception as e:
            print(f"  [s{seed}] FAILED: {e}", file=sys.stderr)
            continue
        totals["generated"] += count
        totals["broken"] += count - len(cands)
        survivors.extend(cands)
        print(f"  [s{seed}] {len(cands)}/{count} stable")
    totals["survivors"] = len(survivors)
    # Soft pre-sort: biggest terrain first, then motion, then stability margin.
    survivors.sort(key=lambda c: (-c.get("terrain", {}).get("character_score", 0.0),
                                  -c.get("terrain", {}).get("terrain_db", 0.0),
                                  -c["motion"], c["max_pole_radius"]))
    shortlist = survivors[:SHORTLIST_K]

    def _rec(c):
        cdir = Path(c["dir"])
        keep = f"python -m tools.make_class_bodies --keep {cdir.parent.as_posix()} {c['name']} --notes \"\""
        return {"name": c["name"], "dir": cdir.as_posix(),
                "prov": f"{c.get('home_scheme','?')} -> {c.get('away_scheme','?')}",
                # Re-use the intent slots so the existing thumbnail labeller picks them up.
                "home_intent": c.get("home_scheme"), "away_intent": c.get("away_scheme"),
                "predicted_mid": None,
                "advisory": [],
                "summary": {"moves_on_morph_hz": round(c["motion"]),
                            "max_pole_radius": round(c["max_pole_radius"], 4),
                            "peak_db": None, **c.get("terrain", {})},
                "keep_cmd": keep}

    out = {
        "campaign": "wild", "name": "Wild",
        "classes": ["CHAOS"], "job": "no rules — 4 independent random corners",
        "morph": "undefined — bilinear blend of unrelated bodies",
        "q": "undefined — TIGHT corners are also random",
        "good_on": ["discovery", "destruction", "happy accidents"],
        "avoid": ["nothing — the runtime stability is the only limit"],
        "mode": "wild-no-structure",
        "totals": totals,
        "intent_pool": [],
        "shortlist": [_rec(c) for c in shortlist],
        "pool": [_rec(c) for c in survivors],
    }
    (fam_dir / "wild.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[wild] DONE: {totals['survivors']} stable / {totals['generated']} generated "
          f"({totals['broken']} blown up).")


# ── INSANE: direct biquad design (no factorizer, no curve fitting) ───────────
# Each stage gets one explicit pole pair + one explicit zero pair, both at
# audible high radii. Bypasses the factorizer entirely → no wasted zero budget.
# Inverse of `kernel_to_biquad`:
#   kernel = [b1/c4 + 2, 1 - b2/c4, a1 + 2, 1 - a2, c4]
# where `c4 = b0`. Biquad coefs come from pole/zero placements:
#   pole pair (r, f):  a1 = -2r·cos(2πf/fs),  a2 = r²
#   zero pair (r, f):  b0 = gain,  b1 = -2r·cos·gain,  b2 = r²·gain


def _biquad_from_pole_zero(pole_f, pole_r, zero_f, zero_r, gain, fs):
    pa = 2.0 * _m.pi * pole_f / fs
    za = 2.0 * _m.pi * zero_f / fs
    b0 = gain
    b1 = -2.0 * zero_r * _m.cos(za) * gain
    b2 = zero_r * zero_r * gain
    a1 = -2.0 * pole_r * _m.cos(pa)
    a2 = pole_r * pole_r
    return b0, b1, b2, a1, a2


def _biquad_to_kernel(b0, b1, b2, a1, a2):
    """Inverse of trench_core kernel_to_biquad. Returns (c0,c1,c2,c3,c4)."""
    if abs(b0) < 1e-12:
        return (2.0, 0.0, a1 + 2.0, 1.0 - a2, 1e-12)
    return (b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


_INSANE_ARCHETYPES = ("interleaved", "razor_comb", "formant", "bell", "razor_top", "razor_low")


def _insane_corner(rng, focus="full"):
    """Returns (kernel_stages[6], archetype_name). Every stage has one audible pole
    pair + one audible zero pair, placed by archetype + focus."""
    arch = rng.choice(_INSANE_ARCHETYPES)
    if arch == "interleaved":
        anchors = {"low":  [280, 480, 820, 1400, 2400, 4200],
                   "high": [800, 1600, 2800, 4500, 7000, 11000],
                   "full": [320, 600, 1200, 2400, 5000, 10000]}[focus]
        pole_fs = [a * rng.uniform(0.92, 1.09) for a in anchors]
        zero_fs = [_m.sqrt(pole_fs[i] * pole_fs[min(i + 1, 5)]) * rng.uniform(0.93, 1.08)
                   for i in range(6)]
    elif arch == "razor_comb":
        anchors = {"low":  [300, 560, 1050, 1800, 3000, 4800],
                   "high": [1000, 2000, 3500, 5500, 8000, 12000],
                   "full": [340, 680, 1400, 2700, 5200, 10000]}[focus]
        pole_fs = [a * rng.uniform(0.94, 1.07) for a in anchors]
        zero_fs = [pole_fs[i] * 1.18 * rng.uniform(0.94, 1.07) for i in range(6)]
    elif arch == "formant":
        bands = [(320, 720), (900, 2300), (2400, 3500), (4000, 6500), (7000, 11000), (12000, 15000)]
        if focus == "low":  bands = bands[:3] + [(max(320, b[0]*0.7), b[1]*0.7) for b in bands[3:]]
        elif focus == "high": bands = [(b[0]*1.4, b[1]*1.4) for b in bands[:3]] + bands[3:]
        pole_fs = [_m.exp(rng.uniform(_m.log(lo), _m.log(hi))) for lo, hi in bands]
        zero_fs = [_m.sqrt(pole_fs[i] * pole_fs[min(i + 1, 5)]) for i in range(6)]
    elif arch == "bell":
        f0_base = {"low": 320, "high": 700, "full": 450}[focus]
        f0 = f0_base * rng.uniform(0.85, 1.4)
        ratios = [1.0, 2.4, 2.9, 4.0, 5.4, 6.8]
        pole_fs = [f0 * r * rng.uniform(0.96, 1.05) for r in ratios]
        zero_fs = [_m.sqrt(pole_fs[i] * pole_fs[min(i + 1, 5)]) for i in range(6)]
    elif arch == "razor_top":
        pole_fs = sorted(_m.exp(rng.uniform(_m.log(800), _m.log(12000))) for _ in range(6))
        zero_fs = sorted(_m.exp(rng.uniform(_m.log(600), _m.log(13000))) for _ in range(6))
    else:  # razor_low — sub-safe: starts at 320 Hz, NEVER below
        pole_fs = sorted(_m.exp(rng.uniform(_m.log(320), _m.log(2400))) for _ in range(6))
        zero_fs = sorted(_m.exp(rng.uniform(_m.log(350), _m.log(3000))) for _ in range(6))

    # HARD floor: nothing below 250 Hz. Pole skirts then can't reach the sub region.
    pole_fs = [max(250.0, min(15500.0, f)) for f in pole_fs]
    zero_fs = [max(250.0, min(15500.0, f)) for f in zero_fs]
    # All poles and zeros razor-narrow at high radii — even at low freqs. A 300 Hz
    # razor pole at r=0.997 is a TONAL RING (clean), not a broad hump (mud).
    pole_rs = [rng.uniform(0.965, 0.997) for _ in range(6)]
    zero_rs = [rng.uniform(0.91, 0.995) for _ in range(6)]
    gains = [rng.uniform(0.6, 1.4) for _ in range(6)]

    stages = []
    for pf, pr, zf, zr, g in zip(pole_fs, pole_rs, zero_fs, zero_rs, gains):
        b = _biquad_from_pole_zero(pf, pr, zf, zr, g, AUTH_SR)
        stages.append(_biquad_to_kernel(*b))
    # PEAK NORMALIZE TO AGC SWEET SPOT — bring every corner's max response to
    # ~+28 dB so the post-cascade AGC compressor is ALWAYS engaged:
    #   peak ~+24 dB → index hits 16 → `& 0xF` wraps to 0 (chaotic gating)
    #   peak ~+28 dB → indices oscillate 4-7 (table mults 0.92, 0.50, 0.20, 0.16)
    # That's where the E-mu glue lives. Below ~+15 dB the AGC is dormant and the
    # body sounds clinical; here it's saturated and alive.
    stages = _normalize_corner_peak(stages, target_db=28.0)
    return stages, arch


def _measure_corner_peak_db(kernel_stages):
    """Max cascade response in dB over 40 Hz – 16 kHz."""
    import numpy as _np
    fs = AUTH_SR
    freqs = _np.logspace(_np.log10(40.0), _np.log10(16000.0), 256)
    total_db = _np.zeros(len(freqs))
    for k in kernel_stages:
        b0 = k[4]; b1 = (k[0] - 2.0) * k[4]; b2 = (1.0 - k[1]) * k[4]
        a1 = k[2] - 2.0; a2 = 1.0 - k[3]
        ang = 2.0 * _np.pi * freqs / fs
        c1, s1 = _np.cos(ang), _np.sin(ang)
        c2, s2 = _np.cos(2.0 * ang), _np.sin(2.0 * ang)
        nr = b0 + b1 * c1 + b2 * c2
        ni = -b1 * s1 - b2 * s2
        dr = 1.0 + a1 * c1 + a2 * c2
        di = -a1 * s1 - a2 * s2
        total_db += 10.0 * _np.log10((nr * nr + ni * ni + 1e-12) / (dr * dr + di * di + 1e-12))
    return float(total_db.max())


def _normalize_corner_peak(kernel_stages, target_db: float = 15.0):
    """Scale every stage's c4 (gain) so the cascade's peak hits `target_db` dB.
    Scaling c4 only changes the level — pole and zero positions are unchanged
    (c0, c1 = b1/b0+2, 1-b2/b0 are gain-invariant; c2, c3 are pole-side)."""
    peak = _measure_corner_peak_db(kernel_stages)
    # cascade gain scales as λ^N where N=stages; in dB: ΔdB = 20·N·log10(λ).
    lam = 10.0 ** ((target_db - peak) / (20.0 * len(kernel_stages)))
    return [(c0, c1, c2, c3, c4 * lam) for (c0, c1, c2, c3, c4) in kernel_stages]


def generate_insane(seed, count):
    run = tb.RUN_ROOT / f"insane_s{seed}"
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)
    cands = []
    import numpy as _np
    for i in range(count):
        rng = random.Random(seed * 1_000_003 + i)
        home_focus, away_focus = rng.choice([
            ("low", "high"), ("high", "low"), ("low", "full"), ("high", "full"),
            ("full", "low"), ("full", "high"),
        ])
        home_k,   home_arch = _insane_corner(rng, focus=home_focus)
        away_k,   away_arch = _insane_corner(rng, focus=away_focus)
        tight_h_k, _        = _insane_corner(rng, focus=home_focus)
        tight_a_k, _        = _insane_corner(rng, focus=away_focus)
        corner_kernels = {"M0_Q0": home_k, "M100_Q0": away_k,
                          "M0_Q100": tight_h_k, "M100_Q100": tight_a_k}
        body = encode.body_from_kernels([corner_kernels[c] for c in CORNER_ORDER])  # ONE encoder (compile_body)
        cw = encode.words_from_body(body)
        corner_words = {KEY[lab]: cw[lab] for lab in LABELS}
        maxr, unstable, nonfinite = tb.grid_stability(body)
        passes = (maxr < 1.0 and unstable == 0 and nonfinite == 0)
        # Mud cull: the BALANCE rule. Low-mid peak (150–800 Hz) must NOT exceed the
        # mid+treble peak (800 Hz–16k). If 300 Hz screams alone, it's mud. If it
        # screams alongside an equal treble pole, it's a balanced ringing body.
        sub_clean = True
        if passes:
            low_mask = (tb.FREQS >= 150.0) & (tb.FREQS < 800.0)
            top_mask = tb.FREQS >= 800.0
            for sm, sq in [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]:
                resp = tb.shipped_response(body, sm, sq)
                if resp[low_mask].max() > resp[top_mask].max() + 0.5:
                    sub_clean = False
                    break
            passes = passes and sub_clean
        name = f"cand_{i + 1:02d}"
        cdir = run / name
        cdir.mkdir()
        (cdir / f"{name}.body240").write_bytes(body)
        cart = tb.build_cart(name, corner_words, 1.0, "insane", seed)
        cart["provenance"] = f"insane:direct-biquad seed={seed} HOME={home_arch}({home_focus}) AWAY={away_arch}({away_focus})"
        (cdir / f"{name}.cart.json").write_text(json.dumps(cart, indent=2), encoding="utf-8")
        report = {"candidate": name, "seed": seed, "index": i,
                  "stable": bool(passes), "sub_clean": sub_clean,
                  "max_pole_radius": round(maxr, 4),
                  "home_archetype": home_arch, "home_focus": home_focus,
                  "away_archetype": away_arch, "away_focus": away_focus}
        (cdir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if not passes:
            continue
        tb.render_candidate_audio(cdir, body)
        cs = [tb.centroid(tb.shipped_response(body, m, 0.0)) for m in _np.linspace(0, 1, 12)]
        net = abs(cs[-1] - cs[0])
        cands.append({"name": name, "dir": cdir, "max_pole_radius": maxr,
                      "motion": float(net),
                      "home_scheme": f"{home_arch}-{home_focus}",
                      "away_scheme": f"{away_arch}-{away_focus}"})
    return run, cands


def run_insane(sweep_id, seeds, count):
    fam_dir = SWEEP_ROOT / sweep_id / "families"
    fam_dir.mkdir(parents=True, exist_ok=True)
    survivors = []
    totals = {"generated": 0, "survivors": 0, "broken": 0, "seeds": seeds}
    print(f"[insane] direct biquad design (no factorizer, no curve fit) seeds={seeds} count={count}")
    for seed in seeds:
        try:
            _run, cands = generate_insane(seed, count)
        except Exception as e:
            print(f"  [s{seed}] FAILED: {e}", file=sys.stderr); continue
        totals["generated"] += count
        totals["broken"] += count - len(cands)
        survivors.extend(cands)
        print(f"  [s{seed}] {len(cands)}/{count} stable")
    totals["survivors"] = len(survivors)
    survivors.sort(key=lambda c: (-c["motion"], c["max_pole_radius"]))
    shortlist = survivors[:SHORTLIST_K]

    def _rec(c):
        cdir = Path(c["dir"])
        keep = f"python -m tools.make_class_bodies --keep {cdir.parent.as_posix()} {c['name']} --notes \"\""
        return {"name": c["name"], "dir": cdir.as_posix(),
                "prov": f"{c['home_scheme']} -> {c['away_scheme']}",
                "home_intent": c["home_scheme"], "away_intent": c["away_scheme"],
                "predicted_mid": None, "advisory": [],
                "summary": {"moves_on_morph_hz": round(c["motion"]),
                            "max_pole_radius": round(c["max_pole_radius"], 4),
                            "peak_db": None},
                "keep_cmd": keep}

    out = {"campaign": "insane", "name": "Insane",
           "classes": ["DESIGNER", "DIRECT_BIQUAD"],
           "job": "every pole and zero hand-placed at audible high radii — no factorizer",
           "morph": "spectrally-opposite HOME/AWAY focus zones",
           "q": "TIGHT corners are independent designs in the same focus",
           "good_on": ["everything insane"], "avoid": ["nothing"],
           "mode": "insane-direct-biquad", "totals": totals,
           "intent_pool": [], "shortlist": [_rec(c) for c in shortlist],
           "pool": [_rec(c) for c in survivors]}
    (fam_dir / "insane.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[insane] DONE: {totals['survivors']} stable / {totals['generated']}")


# ── soft pre-sort ─────────────────────────────────────────────────────────────

def soft_rank_key(c):
    g = c["gate"]
    s = g["summary"]
    return (
        -s.get("character_score", 0.0),
        -s.get("terrain_db", 0.0),
        -s.get("tilt_db", 0.0),
        len(g["advisory_failed"]),
        -s.get("moves_on_morph_hz", 0.0),
        s.get("max_pole_radius", 1.0),
    )


def _cand_record(c):
    g = c["gate"]
    cdir = Path(c["dir"])
    keep = f"python -m tools.make_class_bodies --keep {cdir.parent.as_posix()} {c['name']} --notes \"\""
    return {"name": c["name"], "dir": cdir.as_posix(), "prov": c["prov"],
            "home_intent": c.get("home_intent"), "away_intent": c.get("away_intent"),
            "predicted_mid": c.get("predicted_mid"),
            "advisory": g["advisory_failed"], "summary": g["summary"], "keep_cmd": keep}


def _intent_diverse_shortlist(survivors, k):
    """Soft-sort + dedupe by intent pair so the shortlist SPANS intent pairs rather than
    showing the same '(ah,ee)' six times. Falls back to plain soft order if survivors lack
    intent (random-mode bodies)."""
    pool = sorted(survivors, key=soft_rank_key)
    if not pool or pool[0].get("home_intent") is None:
        return pool[:k]
    seen, primary, extras = set(), [], []
    for c in pool:
        pair = (c.get("home_intent"), c.get("away_intent"))
        if pair not in seen:
            primary.append(c)
            seen.add(pair)
        else:
            extras.append(c)
    return (primary + extras)[:k]


# ── per-family worker ─────────────────────────────────────────────────────────

def run_family(sweep_id, campaign, seeds, count):
    classes, cards = mc.load_cards()
    if campaign not in cards:
        raise SystemExit(f"no family '{campaign}'. Families: {', '.join(cards)}")
    card = cards[campaign]
    templates = mc.load_templates()
    fam_dir = SWEEP_ROOT / sweep_id / "families"
    fam_dir.mkdir(parents=True, exist_ok=True)

    all_intents = _load_intents()
    fam_intents = (all_intents.get(campaign, {}) or {}).get("intents")
    intent_count = len(fam_intents) if fam_intents else 0
    smart = _smart_pairs(fam_intents) if intent_count >= 2 else None
    if smart:
        mode = "bold-twin-anchor + smart-pairs (3-state middle by design)"
    elif intent_count >= 2:
        mode = "bold-twin-anchor + named-intent"
    else:
        mode = "bold-twin-anchor (random)"
    survivors, totals = [], {"generated": 0, "survivors": 0, "broken": 0, "seeds": seeds,
                             "intents": intent_count, "smart_pairs": len(smart) if smart else 0}
    print(f"[{campaign}] {mode} — {card['name']} {card['classes']}  "
          f"seeds={seeds} count={count} intents={intent_count} smart_pairs={len(smart) if smart else 0}")
    for seed in seeds:
        spec = mc.enriched_spec(card, templates, seed)
        try:
            _run, cands = generate_bold(spec, seed, count, intents=fam_intents, smart_pairs=smart)
        except Exception as e:  # one bad seed must not sink the family
            print(f"  [s{seed}] FAILED: {e}", file=sys.stderr)
            continue
        passed = [c for c in cands if c["gate"]["pass"]]
        try:
            tb.publish(spec, seed, passed)
        except Exception as e:
            print(f"  [s{seed}] publish warn: {e}", file=sys.stderr)
        totals["generated"] += len(cands)
        totals["broken"] += len(cands) - len(passed)
        survivors.extend(passed)
        print(f"  [s{seed}] {len(passed)}/{len(cands)} survived")

    totals["survivors"] = len(survivors)
    shortlist = _intent_diverse_shortlist(survivors, SHORTLIST_K)
    out = {
        "campaign": campaign, "name": card["name"], "classes": card["classes"],
        "job": card["job"], "morph": card["morph"], "q": card["q"],
        "good_on": card.get("good_on", []), "avoid": card.get("avoid", []),
        "mode": mode, "totals": totals,
        "intent_pool": list(fam_intents.keys()) if fam_intents else [],
        "shortlist": [_cand_record(c) for c in shortlist],
        "pool": [_cand_record(c) for c in survivors],
    }
    (fam_dir / f"{campaign}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    _write_family_md(fam_dir / f"{campaign}.md", out)
    print(f"[{campaign}] DONE: {totals['survivors']} survivors / {totals['generated']} generated "
          f"({totals['broken']} broken) -> {fam_dir / (campaign + '.json')}")
    return out


def _write_family_md(path, out):
    t = out["totals"]
    pool = ", ".join(out.get("intent_pool") or []) or "none (random)"
    lines = [
        f"# {out['name']} — {out.get('mode', 'sweep')}", "",
        f"- job: {out['job']}", f"- morph: {out['morph']}", f"- Q: {out['q']}",
        f"- classes (internal): {', '.join(out['classes'])}",
        f"- intent pool: {pool}",
        f"- generated: {t['generated']} · survivors: {t['survivors']} · broken: {t['broken']} · seeds: {t['seeds']}",
        "", "## Shortlist (intent-diverse soft pre-sort — the EAR decides)", "",
    ]
    for i, c in enumerate(out["shortlist"], 1):
        s = c["summary"]
        adv = ", ".join(c["advisory"]) or "clean"
        ih, ia = c.get("home_intent"), c.get("away_intent")
        intent = f"**{ih} -> {ia}**" if ih else "(random)"
        lines.append(f"{i:>2}. {intent}  `{c['name']}`  motion={s.get('moves_on_morph_hz')}Hz "
                     f"char={s.get('character_score')} terrain={s.get('terrain_db')}dB "
                     f"tilt={s.get('tilt_db')}dB maxR={s.get('max_pole_radius')} "
                     f"peak={s.get('peak_db')}dB  [{adv}]")
        lines.append(f"    keep: `{c['keep_cmd']}`")
    lines += ["", "## Analysis", "",
              "_(per-family subagent appends its thorough readout below)_", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ── trajectory analyzer (Tyson's two properties) ──────────────────────────────
# (1) NATURAL ARRIVAL: the M=0->1 path is smooth + monotonic, no swerve/wobble.
# (2) EMERGENT MIDDLE: M=0.5 lands on a THIRD named intent — not HOME, not AWAY,
#     not a blurry blend. The middle is its own state.

import numpy as _np


def _intent_target_curve(intent_freqs, spec):
    """Idealised magnitude curve for a named intent: features pinned to the intent's
    freqs with the template's mid-range gains/bws. The reference an actual body's
    response can be compared against."""
    feats = []
    for slot, f in zip(intent_freqs, spec["features"]):
        feats.append({
            "kind": f["kind"], "freq": float(slot),
            "gain": 0.5 * (f["gain_db"][0] + f["gain_db"][1]),
            "bw": 0.5 * (f["bw_oct"][0] + f["bw_oct"][1]),
        })
    return tb.feats_to_curve(feats, spec["floor_db"], tb.FREQS)


def classify_middle(body, spec, intents, home_name, away_name, accept_db=8.0):
    """Find the named intent whose target shape best matches the body's actual midpoint.
    Returns (best_name, distance_dB, is_third_identity). A 'third identity' means the
    midpoint matches some named intent that is NEITHER home NOR away."""
    mid = tb.shipped_response(body, 0.5, 0.0)
    best = None; best_d = float("inf")
    for name, intent in intents.items():
        d = tb.shape_rms(mid, _intent_target_curve(intent["freqs"], spec))
        if d < best_d:
            best, best_d = name, d
    if best is None or best_d > accept_db:
        return (None, float(best_d), False)
    third = best != home_name and best != away_name
    return (best, float(best_d), third)


def trajectory_smoothness(body, spec, home_name, away_name, intents, steps=9):
    """How cleanly does the body glide from HOME to AWAY? Compare each step along
    M=0->1 (Q=0) to the IDEAL linear blend of the two intent target curves. The
    monotonicity score is path/net of the curve trajectory (1.0 = perfectly
    monotonic, >1.4 = swerves)."""
    home_t = _intent_target_curve(intents[home_name]["freqs"], spec)
    away_t = _intent_target_curve(intents[away_name]["freqs"], spec)
    actuals = [tb.shipped_response(body, i / (steps - 1), 0.0) for i in range(steps)]
    # deviation from the ideal linear blend
    devs = []
    for i, act in enumerate(actuals):
        m = i / (steps - 1)
        ideal = (1.0 - m) * home_t + m * away_t
        devs.append(tb.shape_rms(act, ideal))
    mean_dev = float(_np.mean(devs))
    # monotonicity: net curve travel HOME->AWAY vs sum of step travels
    net = tb.shape_rms(actuals[0], actuals[-1])
    path = sum(tb.shape_rms(actuals[i], actuals[i + 1]) for i in range(len(actuals) - 1))
    mono = float(path / max(net, 1e-6))
    return {"deviation_db": round(mean_dev, 2), "monotonicity": round(mono, 2)}


def _analyze_family(fam_path: Path, intents_root, templates):
    """Rewrite a family's JSON in place: tag every survivor (pool + shortlist) with
    mid_intent + third-state + trajectory + a complete-morph flag, and re-pick the
    shortlist preferring complete morphs (third-state middle + smooth arrival)."""
    out = json.loads(fam_path.read_text(encoding="utf-8"))
    fam = out["campaign"]
    fam_def = intents_root.get(fam) or {}
    intents = fam_def.get("intents")
    if not intents:
        print(f"  [{fam}] no intents; skipping analysis"); return out
    card_template = templates.get(fam_def.get("template"))
    if not card_template:
        print(f"  [{fam}] template missing; skipping"); return out
    spec = dict(card_template)
    spec["name"] = fam
    spec["label"] = out.get("name", fam)
    if "failure_modes" not in spec: spec["failure_modes"] = []

    analyzed = []
    third_count = 0; clean_traj = 0
    for c in out.get("pool", []):
        cdir = Path(c["dir"])
        body_path = cdir / f"{c['name']}.body240"
        if not body_path.exists():
            continue
        body = body_path.read_bytes()
        home_n, away_n = c.get("home_intent"), c.get("away_intent")
        if not (home_n and away_n) or home_n not in intents or away_n not in intents:
            continue
        mid_name, mid_db, third = classify_middle(body, spec, intents, home_n, away_n)
        traj = trajectory_smoothness(body, spec, home_n, away_n, intents)
        third_count += int(third)
        natural = traj["monotonicity"] <= 1.45 and traj["deviation_db"] <= 9.0
        clean_traj += int(natural)
        c2 = dict(c)
        c2["mid_intent"] = mid_name
        c2["mid_distance_db"] = round(mid_db, 2)
        c2["third_state"] = third
        c2["trajectory"] = traj
        c2["complete_morph"] = bool(third and natural)
        analyzed.append(c2)
    out["pool"] = analyzed
    out["totals"]["third_state"] = third_count
    out["totals"]["natural_arrival"] = clean_traj
    out["totals"]["complete_morphs"] = sum(1 for c in analyzed if c["complete_morph"])

    # new shortlist: complete morphs first, intent-pair diverse, then fall back
    def _rank(c):
        s = c.get("summary", {})
        adv = c.get("advisory", [])
        return (
            0 if c["complete_morph"] else 1,
            0 if c["third_state"] else 1,
            -s.get("character_score", 0.0),
            -s.get("terrain_db", 0.0),
            -s.get("tilt_db", 0.0),
            c["trajectory"]["monotonicity"],
            len(adv),
            -s.get("moves_on_morph_hz", 0.0),
        )
    pool_sorted = sorted(analyzed, key=_rank)
    seen, primary, extras = set(), [], []
    for c in pool_sorted:
        pair = (c.get("home_intent"), c.get("mid_intent"), c.get("away_intent"))
        if pair not in seen:
            primary.append(c); seen.add(pair)
        else:
            extras.append(c)
    out["shortlist"] = (primary + extras)[:SHORTLIST_K]

    fam_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  [{fam}] analyzed: third-state {third_count}/{len(analyzed)} · "
          f"natural arrival {clean_traj}/{len(analyzed)} · "
          f"complete morphs {out['totals']['complete_morphs']}")
    return out


def analyze_sweep(sweep_id):
    """Tag every body in a sweep with midpoint identity + trajectory smoothness,
    and rebuild family shortlists around 'complete morphs' (third-state middle +
    natural arrival). Reads + rewrites families/*.json in place."""
    sweep_dir = SWEEP_ROOT / sweep_id
    fam_dir = sweep_dir / "families"
    intents_root = _load_intents()
    templates = mc.load_templates()
    fams = sorted(fam_dir.glob("*.json"))
    if not fams:
        print(f"no families in {fam_dir}", file=sys.stderr); return 1
    print(f"analyzing trajectories + middles across {len(fams)} families")
    for fp in fams:
        _analyze_family(fp, intents_root, templates)
    return 0


# ── merge into the master audition queue ──────────────────────────────────────

def _save_shape_png(path, body, title):
    """The hero view: the response SHAPE at the 4 corners + the middle. Magnitude
    over frequency — no coefficients, poles, or DSP vocabulary. Shape first."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    series = [("HOME", 0.0, 0.0, "#6ee7a8"), ("AWAY", 1.0, 0.0, "#81d4ff"),
              ("TIGHT HOME", 0.0, 1.0, "#f1d76a"), ("TIGHT AWAY", 1.0, 1.0, "#ff9d6d")]
    fig, ax = plt.subplots(figsize=(7.4, 3.0), dpi=110)
    for lab, m, q, col in series:
        ax.semilogx(tb.FREQS, tb.shipped_response(body, m, q), lw=1.5, label=lab, color=col)
    ax.semilogx(tb.FREQS, tb.shipped_response(body, 0.5, 0.5), lw=1.0, ls="--", color="#9aa", label="middle")
    ax.set_xlim(40, 16000)
    ax.set_ylim(-60, 18)
    ax.grid(alpha=0.18)
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=7, ncol=5, loc="lower center")
    ax.set_xlabel("frequency", fontsize=7)
    ax.set_ylabel("shape (dB)", fontsize=7)
    ax.set_facecolor("#0c0f0e")
    fig.patch.set_facecolor("#0c0f0e")
    for s in ax.spines.values():
        s.set_color("#33433c")
    ax.tick_params(colors="#9aa", labelsize=7)
    ax.xaxis.label.set_color("#9aa")
    ax.yaxis.label.set_color("#9aa")
    ax.title.set_color("#cfe9dc")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _clip_cells(relprefix):
    cells = []
    for fname, code, sub in SWEEP_CLIPS:
        cells.append(
            f'<label>{html.escape(code)}<span>{html.escape(sub)}</span>'
            f'<audio controls preload="none" src="{relprefix}/{fname}"></audio></label>')
    return "\n".join(cells)


def merge(sweep_id):
    sweep_dir = SWEEP_ROOT / sweep_id
    fam_dir = sweep_dir / "families"
    fams = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(fam_dir.glob("*.json"))]
    if not fams:
        print(f"no family json in {fam_dir}", file=sys.stderr)
        return 1

    nav = " · ".join(f'<a href="#{f["campaign"]}">{html.escape(f["name"])} ({len(f["shortlist"])})</a>' for f in fams)
    sections = []
    for f in fams:
        t = f["totals"]
        cards_html = []
        for idx, c in enumerate(f["shortlist"], 1):
            cdir = Path(c["dir"])
            rel = os.path.relpath(cdir, sweep_dir).replace("\\", "/")
            adv = " · ".join(tb.GATE_WORDS.get(a, a) for a in c["advisory"]) or "clean enough for ears"
            # SHAPE FIRST: render the 4-corner response plot for this body (cache on disk).
            png = cdir / "response.png"
            if not png.exists():
                try:
                    _save_shape_png(png, (cdir / f"{c['name']}.body240").read_bytes(),
                                    f"{f['name']} · candidate {idx:02d}")
                except Exception as e:
                    print(f"  plot warn {cdir.name}/{c['name']}: {e}", file=sys.stderr)
            # unique vote key: same bare cand name recurs across seeds, so include the
            # seed run-dir (e.g. comb_s7002) or KEEP votes collide in localStorage.
            seedtag = cdir.parent.name
            key = f'{f["campaign"]}:{seedtag}:{c["name"]}'
            ih, ia, im = c.get("home_intent"), c.get("away_intent"), c.get("mid_intent")
            third = bool(c.get("third_state"))
            complete = bool(c.get("complete_morph"))
            if ih and third and im:
                intent_html = (f'<span class="intent three"><b>{html.escape(ih)}</b>'
                               f' &rarr; <b>{html.escape(im)}</b> &rarr; <b>{html.escape(ia)}</b></span>')
            elif ih:
                mid_lbl = im if im else "mushy"
                intent_html = (f'<span class="intent">{html.escape(ih)}'
                               f' &rarr; <i>{html.escape(mid_lbl)}</i> &rarr; {html.escape(ia)}</span>')
            else:
                intent_html = '<span class="intent random">random</span>'
            badge = '<span class="badge complete">complete morph</span>' if complete else ''
            cards_html.append(f"""
<section class="cand" data-key="{html.escape(key)}">
  <header><div><h3>{html.escape(f['name'])} · {intent_html} · #{idx:02d} {badge}</h3>
    <p class="warn">{html.escape(adv)}</p></div>
    <div class="vote"><button data-vote="KEEP">KEEP</button><button data-vote="MAYBE">MAYBE</button><button data-vote="REJECT">REJECT</button></div>
  </header>
  <img class="resp" loading="lazy" src="{rel}/response.png" alt="response shape">
  <div class="clips">{_clip_cells(rel)}</div>
  <textarea placeholder="producer notes"></textarea>
  <code>{html.escape(c['keep_cmd'])}</code>
</section>""")
        pool = " · ".join(f.get("intent_pool") or []) or "random (no intent pool)"
        sections.append(f"""
<section class="fam" id="{f['campaign']}">
  <h2>{html.escape(f['name'])} <span class="cls">{html.escape(' / '.join(f['classes']))}</span></h2>
  <p class="meta">{html.escape(f['job'])}</p>
  <p class="meta">Morph: {html.escape(f['morph'])} · Q: {html.escape(f['q'])}</p>
  <p class="meta"><b>intents:</b> {html.escape(pool)}</p>
  <p class="meta">{t['survivors']} survivors of {t['generated']} · showing top {len(f['shortlist'])} · <b>complete morphs:</b> {t.get('complete_morphs', '?')} · third-state middles: {t.get('third_state', '?')} · natural arrivals: {t.get('natural_arrival', '?')} · avoid: {html.escape(' · '.join(f['avoid']))}</p>
  {''.join(cards_html) if cards_html else '<p class="meta">no survivors</p>'}
</section>""")

    total_short = sum(len(f["shortlist"]) for f in fams)
    total_surv = sum(f["totals"]["survivors"] for f in fams)
    total_gen = sum(f["totals"]["generated"] for f in fams)
    doc = f"""<!doctype html>
<meta charset="utf-8">
<title>Roster Sweep — audition queue</title>
<style>
body{{margin:0;background:#080a0a;color:#eee9dc;font:14px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 18px 64px}}
h1{{font-size:27px;margin:0 0 4px}} h2{{font-size:22px;margin:0 0 4px;color:#9fe7c6}}
h3{{font-size:17px;margin:0 0 4px;color:#cfe9dc}}
.cls{{color:#f1c46a;font:12px ui-monospace,Consolas,monospace}}
.intent{{color:#9fe7c6;font:13px ui-monospace,Consolas,monospace;background:#0e1a16;border:1px solid #2a3d34;border-radius:4px;padding:2px 7px;margin:0 6px}}
.intent.random{{color:#a4aaa2;background:#101010;border-color:#2a2a2a}}
.intent.three{{color:#cfe9dc;background:#10271b;border-color:#3a6e52}}
.intent i{{color:#a4aaa2}}
.badge{{font:11px ui-monospace,Consolas,monospace;letter-spacing:.04em;padding:2px 7px;border-radius:4px;margin-left:6px;vertical-align:middle}}
.badge.complete{{background:#10271b;color:#6ee7a8;border:1px solid #3a6e52}}
.meta,.warn{{color:#a4aaa2;margin:0 0 5px}}
.topnav{{position:sticky;top:0;background:#080a0acc;backdrop-filter:blur(6px);padding:10px 0;border-bottom:1px solid #20342d;margin-bottom:16px;font:13px ui-monospace,Consolas,monospace}}
.topnav a{{color:#81d4ff;margin-right:14px;text-decoration:none}}
.fam{{border-top:1px solid #20342d;padding-top:14px;margin-top:26px}}
.cand{{border:1px solid #20342d;background:#0d1110;border-radius:8px;padding:13px;margin:12px 0}}
header{{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}}
.vote{{display:flex;gap:8px;flex-wrap:wrap}}
button{{background:#151a18;color:#eee9dc;border:1px solid #405247;border-radius:5px;padding:7px 10px;cursor:pointer}}
button.active[data-vote=KEEP]{{background:#17422c;border-color:#6ee7a8}}
button.active[data-vote=MAYBE]{{background:#433716;border-color:#e5c75f}}
button.active[data-vote=REJECT]{{background:#421d1d;border-color:#ff6d6d}}
img.resp{{display:block;width:100%;max-width:780px;border-radius:6px;margin:10px 0;border:1px solid #18221d}}
.clips{{display:grid;grid-template-columns:1fr 1fr;gap:9px 16px;margin-top:10px}}
label{{display:block;color:#f1d76a;font:12px ui-monospace,Consolas,monospace}}
label span{{color:#79827b;margin-left:8px}}
audio{{display:block;width:100%;margin-top:4px}}
textarea{{box-sizing:border-box;width:100%;min-height:48px;margin:10px 0 8px;background:#070908;color:#eee9dc;border:1px solid #28332d;border-radius:5px;padding:8px}}
code{{display:block;white-space:pre-wrap;color:#81d4ff;background:#070908;border:1px solid #18221d;border-radius:5px;padding:8px}}
@media(max-width:860px){{header{{display:block}}.vote{{margin-top:10px}}.clips{{grid-template-columns:1fr}}}}
</style>
<main>
  <h1>Roster Sweep — audition queue</h1>
  <p class="meta">{len(fams)} families · {total_short} shortlisted of {total_surv} survivors ({total_gen} generated, bold twin-anchor). Listen HOME→AWAY (should be GENUINELY different), then the sweeps. Mark KEEP / MAYBE / REJECT. Buttons + notes save in this browser; keep command is per body.</p>
  <div class="topnav">{nav}</div>
  {''.join(sections)}
</main>
<script>
const K="roster-sweep:{html.escape(sweep_id)}";
for(const card of document.querySelectorAll(".cand")){{
  const sk=K+":"+card.dataset.key;
  const saved=JSON.parse(localStorage.getItem(sk)||"{{}}");
  const notes=card.querySelector("textarea");
  if(saved.notes)notes.value=saved.notes;
  function save(v){{localStorage.setItem(sk,JSON.stringify({{vote:v,notes:notes.value}}));
    for(const b of card.querySelectorAll("button"))b.classList.toggle("active",b.dataset.vote===v);}}
  if(saved.vote)save(saved.vote);
  for(const b of card.querySelectorAll("button"))b.onclick=()=>save(b.dataset.vote);
  notes.oninput=()=>{{const a=card.querySelector("button.active");save(a?a.dataset.vote:"");}};
}}
</script>
"""
    (sweep_dir / "audition.html").write_text(doc, encoding="utf-8")
    idx = [f"# Roster sweep {sweep_id}", "",
           f"{len(fams)} families · {total_surv} survivors / {total_gen} generated (bold twin-anchor)", ""]
    for f in fams:
        t = f["totals"]
        idx.append(f"- **{f['name']}** ({f['campaign']}): {t['survivors']}/{t['generated']} survived, "
                   f"shortlist {len(f['shortlist'])} — {f['job']}")
    idx += ["", f"audition queue: `{(sweep_dir / 'audition.html').as_posix()}`"]
    (sweep_dir / "index.md").write_text("\n".join(idx), encoding="utf-8")
    print(f"merged {len(fams)} families -> {sweep_dir / 'audition.html'}  "
          f"({total_short} shortlisted / {total_surv} survivors)")
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", required=True, help="sweep id (shared run folder name)")
    ap.add_argument("--family", help="family campaign to generate (worker mode)")
    ap.add_argument("--seeds", help="comma-separated seeds, e.g. 7001,7002,7003")
    ap.add_argument("--count", type=int, default=48, help="candidates per seed")
    ap.add_argument("--merge", action="store_true", help="merge all families into the master queue")
    ap.add_argument("--analyze", action="store_true",
                    help="tag every body with midpoint identity + trajectory smoothness; "
                         "re-pick shortlists around complete morphs (3-state middle + natural arrival)")
    args = ap.parse_args()

    if args.analyze:
        return analyze_sweep(args.sweep)
    if args.merge:
        return merge(args.sweep)
    if args.family == "wild":
        if not trench_ffi.available() or not trench_ffi.engine_available():
            print("trench-core not built. Run: cargo build --release -p trench-core", file=sys.stderr)
            return 1
        seeds = [int(s) for s in (args.seeds or "13001").split(",") if s.strip()]
        run_wild(args.sweep, seeds, max(4, min(256, args.count)))
        return 0
    if args.family == "insane":
        if not trench_ffi.available() or not trench_ffi.engine_available():
            print("trench-core not built.", file=sys.stderr)
            return 1
        seeds = [int(s) for s in (args.seeds or "14001").split(",") if s.strip()]
        run_insane(args.sweep, seeds, max(4, min(256, args.count)))
        return 0

    if not args.family:
        print("worker mode needs --family (or use --merge)", file=sys.stderr)
        return 1
    if not trench_ffi.available() or not trench_ffi.engine_available():
        print("trench-core not built. Run: cargo build --release -p trench-core", file=sys.stderr)
        return 1
    seeds = [int(s) for s in (args.seeds or "7001").split(",") if s.strip()]
    run_family(args.sweep, args.family, seeds, max(4, min(96, args.count)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
