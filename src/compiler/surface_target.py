"""Target Morph x Q response surfaces (the truth the compiler aims at)."""
from __future__ import annotations
import json
import math
from pathlib import Path
import numpy as np
from pyruntime import trench_ffi
from src.architectures.trajectory_program import AUTHORING_SR as SR

FREQS = np.geomspace(40.0, 16000.0, 256)
GRID = [(m, q) for q in (0.0, .25, .5, .75, 1.0) for m in (0.0, .25, .5, .75, 1.0)]
# tables/family_intents.json OWNS the freqs (never invented). from_family consumes it.
_FAMILIES = json.loads((Path(__file__).resolve().parents[2] / "tables/family_intents.json").read_text())["families"]


def mag_db(biquads, f) -> float:
    w = 2 * math.pi * f / SR
    s = 0.0
    for (b0, b1, b2, a1, a2) in biquads:
        c, sn, c2, s2 = math.cos(w), math.sin(w), math.cos(2 * w), math.sin(2 * w)
        nr, ni = b0 + b1 * c + b2 * c2, -(b1 * sn + b2 * s2)
        dr, di = 1 + a1 * c + a2 * c2, -(a1 * sn + a2 * s2)
        s += 20 * math.log10(max(1e-12, math.hypot(nr, ni) / max(1e-12, math.hypot(dr, di))))
    return s


def surface_from_body(body: bytes) -> np.ndarray:
    out = np.empty((len(GRID), len(FREQS)))
    for gi, (m, q) in enumerate(GRID):
        bq = trench_ffi.packed_probe(body, float(m), float(q))["biquad"]
        out[gi] = [mag_db(bq, f) for f in FREQS]
    return out


# ---------------------------------------------------------------------------
# target_from_tables: ONE method (table-driven, clean-room) -> a target surface.
#
# A body = (template, intent_family, HOME intent -> AWAY intent). EVERY number is
# table-pulled, NONE invented (the doctrine): slot FREQS from family_intents.json,
# slot KIND / gain / bandwidth + the morph & Q rules from target_templates.json.
# The pole radius is bounded by the REAL corpus ceiling 0.9863 (tables/q_radius_table.json)
# at fit time -- not the invented 0.999. This target feeds the ONE verified core
# (compile_surface, fit=True) which fits (theta, r, g) through the shipped runtime and
# corridor-gates. Other methods (LPC/Prony fit of real audio, surface re-hit, hand-author)
# feed the SAME core -- multiple methods, one right DSP.
# ---------------------------------------------------------------------------
_TEMPLATES = {t["name"]: t for t in json.loads(
    (Path(__file__).resolve().parents[2] / "tools/target_templates.json").read_text())["templates"]}
# Real pole-radius ceiling = the ATLAS-measured max of the iconic-15 (max 0.9997, p90 0.999;
# 42% of real poles EXCEED 0.986). The q_radius_table 0.986 is NOT a pole-radius bound (it is the
# Q-table-index radius) -- capping the fit there yields tame bodies that fail the corridor. OBSERVED.
Q_RADIUS_MAX = 0.9994


def _mid(lohi):
    return 0.5 * (float(lohi[0]) + float(lohi[1]))


def _q_rule(rule):
    """(bw_scale, peak_boost_db, dip_boost_db) at Q=1, from a target_templates q_axis_rule."""
    bw_scale = _mid(rule.get("bw_scale", [1.0, 1.0]))
    peak = _mid(rule.get("gain_boost_db", rule.get("peak_boost_db", [0.0, 0.0])))
    dip = _mid(rule.get("dip_boost_db", rule.get("notch_extra_db", [0.0, 0.0])))
    return bw_scale, peak, dip


def target_from_tables(template, intent_family, home, away):
    """Table-driven target surface dB(f, Morph, Q). No invented numbers — freqs from
    family_intents, kind/gain/bandwidth + morph/Q rules from target_templates."""
    tmpl = _TEMPLATES[template]
    feats = tmpl["features"]
    intents = _FAMILIES[intent_family]["intents"]
    hf, af = intents[home]["freqs"], intents[away]["freqs"]
    n = min(len(feats), len(hf), len(af))
    bw_scale, peak_boost, dip_boost = _q_rule(tmpl["q_axis_rule"])
    logf = np.log2(FREQS)
    tgt = np.zeros((len(GRID), len(FREQS)))
    for gi, (m, q) in enumerate(GRID):
        db = np.zeros(len(FREQS))
        for i in range(n):
            f = feats[i]
            fc = float(hf[i]) * (float(af[i]) / float(hf[i])) ** m              # glide home->away (log)
            sig = max(_mid(f["bw_oct"]) * (1.0 - (1.0 - bw_scale) * q) / 2.0, 0.03)  # Q narrows the band
            shape = np.exp(-((logf - np.log2(fc)) ** 2) / (2.0 * sig * sig))
            if f["kind"] == "notch":
                db = db - (_mid(f["gain_db"]) + dip_boost * q) * shape
            else:
                db = db + (_mid(f["gain_db"]) + peak_boost * q) * shape
        tgt[gi] = db
    return tgt
