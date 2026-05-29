#!/usr/bin/env python3
"""reference_brief - turn a P2K-style reference preset into ORIGINAL df2 bodies
that perform the same musical job, never a copy.

This is NOT a coefficient/byte/pole mutator and NOT machine learning. It:

  1. Analyzes a reference body's whole 4-corner Morph/Q response surface
     (M0_Q0, M100_Q0, M0_Q100, M100_Q100, midpoint, Morph/Q/diagonal sweeps).
  2. Extracts a REFERENCE BRIEF: one-line job, body mass region, identity
     feature, danger/fracture feature, Morph motion, Q motion, midpoint
     behaviour, failure modes. Musical behaviour only -- no coefficients, no
     poles, no packed words, no preset names carried forward.
  3. Converts the brief into a WIDENED target-template family (the musical
     grammar, with frequencies/gains/notches deliberately randomized in
     curve space -- exact values are NOT preserved).
  4. Generates whole 4-corner bodies through the same proven factorizer the
     Target Browser ships on, hard-culls the broken ones, then REJECTS any
     candidate that lands too close to the reference (curve distance, exact
     freq matches, near-identical corner/midpoint shapes). Only originals
     survive.
  5. Renders audition.html with a REFERENCE PREVIEW for A/B comparison plus
     each surviving candidate's corners / midpoint / Morph-Q-diagonal sweeps.
  6. --keep saves body240 + cart.json + brief + seed + gate report + notes +
     a response image for the winners the ear chooses.

Usage:
    python -m tools.reference_brief --list-refs
    python -m tools.reference_brief --reference razor_blades --seed 1001 --count 24
    python -m tools.reference_brief --keep <run_dir> cand_03 --notes "why it wins"

Clean-room rule: the reference is read for BEHAVIOUR, never copied. Reference
audio in the audition page is preview-only and is never published as a preset.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import random
import re
import shutil
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HERE = str(Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", _HERE, str(ROOT))]
sys.path.insert(0, str(ROOT))

import numpy as np

# Reuse the PROVEN generation/gate/render machinery -- single owner, no new DSP.
from tools import target_browser as tb
from pyruntime import trench_ffi
from pyruntime.packed_interp import coeffs_to_words

ROM_DIR = ROOT / "bodies" / "rom"
RUN_ROOT = ROOT / "dev" / "tmp" / "reference_brief"
KEEP_DIR = ROOT / "dev" / "tmp" / "keepers"

AUTH_SR = tb.AUTH_SR
FREQS = tb.FREQS
FIT_FREQS = tb.FIT_FREQS
LABELS = tb.LABELS
KEY = tb.KEY

BANDS = [("sub weight", 20.0, 120.0), ("low-mid body", 120.0, 800.0),
         ("forward midrange", 800.0, 4000.0), ("top-end sheen", 4000.0, 16000.0)]

# The fitter leaves the top octave unconstrained (it parks a Nyquist-edge
# resonance there -- STATE.md). Characterize the MUSICAL body, never that
# artifact: pick features only inside the band, and the identity only where a
# real body/formant lives.
ANALYSIS_BAND = (60.0, 10500.0)
IDENTITY_BAND = (120.0, 5200.0)
MIN_FEATURE_BW = 0.07   # octaves; below this it's an edge spike, not a musical feature

# similarity-rejection defaults (mean-removed band RMS in dB; tunable via CLI)
SIM_MIN_DB = 2.6           # nearest reference corner must differ by at least this
SIM_MID_MIN_DB = 2.2       # midpoint must differ by at least this
FREQ_MATCH_TOL = 0.030     # within 3% counts as an "exact" frequency match


# ── reference resolution + loading ───────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")


def list_references():
    refs = []
    for p in sorted(ROM_DIR.glob("P2k_*.json")):
        m = re.match(r"P2k_(\d+)_(.+)", p.stem)
        if not m:
            continue
        refs.append({"file": p, "num": m.group(1), "slug": m.group(2),
                     "name": json.loads(p.read_text(encoding="utf-8")).get("name", p.stem)})
    return refs


def resolve_reference(token: str) -> Path:
    """Match 'Razor_Blades', 'razor blades', 'P2k_018', '18', or a slug to a ROM file."""
    want = _norm(token)
    refs = list_references()
    # exact slug
    for r in refs:
        if r["slug"] == want or _norm(r["name"]) == want:
            return r["file"]
    # by number (P2k_018 / 18 / 018)
    num = re.sub(r"\D", "", token)
    if num:
        for r in refs:
            if r["num"].lstrip("0") == num.lstrip("0"):
                return r["file"]
    # contains
    hits = [r for r in refs if want and (want in r["slug"] or want in _norm(r["name"]))]
    if len(hits) == 1:
        return hits[0]["file"]
    if len(hits) > 1:
        raise SystemExit(f"'{token}' is ambiguous: " + ", ".join(h["slug"] for h in hits))
    raise SystemExit(f"no reference matches '{token}'. Try --list-refs.")


def load_reference_body(path: Path):
    """Build the 240-byte body from the ROM JSON's packedWords (NOT its coefficients)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    kf = {k["label"]: k for k in data["keyframes"]}
    missing = [lab for lab in LABELS if lab not in kf or "packedWords" not in kf[lab]]
    if missing:
        raise SystemExit(f"{path.name}: missing packedWords for {missing}")
    flat = []
    for lab in LABELS:
        for w in kf[lab]["packedWords"]:
            flat.extend(int(x) & 0xFFFF for x in w)
    return struct.pack("<" + "H" * 120, *flat), data.get("name", path.stem)


# ── response analysis (behaviour only) ───────────────────────────────────────

def corner_curves(body):
    curves = {lab: tb.shipped_response(body, *tb._mq(lab)) for lab in LABELS}
    curves["MID"] = tb.shipped_response(body, 0.5, 0.5)
    return curves


def _smooth(y, k=5):
    if k <= 1:
        return y
    return np.convolve(y, np.ones(k) / k, mode="same")


def _extrema(y):
    maxs, mins = [], []
    for i in range(1, len(y) - 1):
        if y[i] >= y[i - 1] and y[i] > y[i + 1]:
            maxs.append(i)
        elif y[i] <= y[i - 1] and y[i] < y[i + 1]:
            mins.append(i)
    return maxs, mins


def _bw_oct(y, freqs, i):
    """Octave width where the curve drops 3 dB off the (local) value at i."""
    thr = y[i] - 3.0
    lo = i
    while lo > 0 and y[lo] > thr:
        lo -= 1
    hi = i
    while hi < len(y) - 1 and y[hi] > thr:
        hi += 1
    if freqs[hi] <= freqs[lo]:
        return 0.25
    return float(min(1.5, max(0.08, math.log2(freqs[hi] / freqs[lo]))))


def find_features(db, freqs, prom_db=3.0, notch_db=4.0, max_feats=6, band=ANALYSIS_BAND):
    """Pick salient peaks + notches off a magnitude curve. Musical structure, not coeffs.
    Restricted to the musical band so the Nyquist-edge resonance is never mistaken for a feature."""
    s = _smooth(db, 5)
    out = []

    def _scan(curve, kind, thr):
        maxs, _ = _extrema(curve)
        feats = []
        for j, i in enumerate(maxs):
            if not (band[0] <= freqs[i] <= band[1]):
                continue
            prev_p = maxs[j - 1] if j > 0 else 0
            next_p = maxs[j + 1] if j < len(maxs) - 1 else len(curve) - 1
            col = max(curve[prev_p:i + 1].min(), curve[i:next_p + 1].min())
            prom = float(curve[i] - col)
            shoulder = max(curve[prev_p], curve[next_p])
            bw = _bw_oct(curve, freqs, i)
            if prom >= thr and shoulder > (curve.max() - 36.0) and bw >= MIN_FEATURE_BW:
                feats.append({"kind": kind, "idx": i, "freq": float(freqs[i]),
                              "gain": prom, "bw": bw})
        return feats

    out += _scan(s, "peak", prom_db)
    out += _scan(-s, "notch", notch_db)
    # de-cluster: drop the weaker of any two features within 0.22 octave
    out.sort(key=lambda f: -f["gain"])
    kept = []
    for f in out:
        if all(abs(math.log2(f["freq"] / k["freq"])) > 0.22 for k in kept):
            kept.append(f)
        if len(kept) >= max_feats:
            break
    kept.sort(key=lambda f: f["freq"])
    return kept


def band_energies(curves):
    avg = np.mean([curves[lab] for lab in LABELS], axis=0)
    return {name: tb.band_mean(avg, lo, hi) for name, lo, hi in BANDS}


def morph_trajectory(body, n=16):
    cs = [tb.centroid(tb.shipped_response(body, float(m), 0.0)) for m in np.linspace(0, 1, n)]
    net = cs[-1] - cs[0]
    path = sum(abs(cs[i + 1] - cs[i]) for i in range(len(cs) - 1))
    return cs, float(net), float(path)


def analyze_reference(body, name):
    curves = corner_curves(body)
    home = find_features(curves["M0_Q0"], FREQS)
    morphed = find_features(curves["M100_Q0"], FREQS)
    tens = find_features(curves["M0_Q100"], FREQS)
    energies = band_energies(curves)
    dominant = max(energies, key=energies.get)
    _, net, path = morph_trajectory(body)

    peaks = [f for f in home if f["kind"] == "peak"]
    notches = [f for f in home if f["kind"] == "notch"]

    # identity = strongest home peak in the body/formant band that survives the Morph move
    def _persists(f, ref):
        return any(abs(math.log2(f["freq"] / g["freq"])) < 0.45 for g in ref if g["kind"] == "peak")
    id_pool = [f for f in peaks if IDENTITY_BAND[0] <= f["freq"] <= IDENTITY_BAND[1]]
    stable = [f for f in id_pool if _persists(f, morphed)]
    identity = max(stable or id_pool or peaks, key=lambda f: f["gain"]) if peaks else None

    # danger/fracture = narrowest upper peak, else deepest upper notch
    upper = [f for f in home if f["freq"] > 1500.0]
    narrow = sorted([f for f in upper if f["kind"] == "peak"], key=lambda f: (f["bw"], -f["gain"]))
    deep = sorted([f for f in upper if f["kind"] == "notch"], key=lambda f: -f["gain"])
    fracture = (narrow[0] if narrow else (deep[0] if deep else None))

    # Morph motion classification
    low_home = tb.band_mean(curves["M0_Q0"], 20, 300)
    low_morph = tb.band_mean(curves["M100_Q0"], 20, 300)
    low_held = abs(low_morph - low_home) < 4.0
    wobble = path / max(abs(net), 1.0)
    if len(notches) >= 3:
        morph_kind, morph_word = "translate_comb", "the comb teeth slide together"
    elif low_held and abs(net) > 250:
        morph_kind, morph_word = "anchored", "the body holds while the upper structure moves"
    elif wobble > 2.2:
        morph_kind, morph_word = "glide", "each feature drifts on its own"
    else:
        morph_kind, morph_word = "shift", f"the whole body sweeps {'up' if net > 0 else 'down'}"

    # Q motion classification (M0_Q0 vs M0_Q100)
    bw_home = np.mean([f["bw"] for f in peaks]) if peaks else 0.5
    bw_tens = np.mean([f["bw"] for f in tens if f["kind"] == "peak"]) if tens else bw_home
    cent_shift = abs(tb.centroid(curves["M0_Q100"]) - tb.centroid(curves["M0_Q0"]))
    notch_home = np.mean([f["gain"] for f in notches]) if notches else 0.0
    notch_tens = np.mean([f["gain"] for f in tens if f["kind"] == "notch"]) if any(
        f["kind"] == "notch" for f in tens) else 0.0
    if notch_tens - notch_home > 3.0 and len(notches) >= 1:
        q_kind, q_word = "deepen", "Q digs the notches deeper"
    elif bw_tens < bw_home * 0.85 and cent_shift < 600:
        q_kind, q_word = "sharpen", "Q tightens the peaks in place"
    else:
        q_kind, q_word = "contrast", "Q pulls peaks up and dips down at once"

    # midpoint behaviour
    avg = np.mean([curves[lab] for lab in LABELS], axis=0)
    spread = np.mean([tb.shape_rms(curves[a], curves[b])
                      for ia, a in enumerate(LABELS) for b in LABELS[ia + 1:]])
    mid_novelty = tb.shape_rms(curves["MID"], avg) / max(spread, 1e-6)
    mid_word = ("the midpoint sits between the corners (clean glide)" if mid_novelty < 0.55
                else "the midpoint becomes its own emergent shape")

    failures = []
    if energies["sub weight"] > -2 and morph_kind != "anchored":
        failures.append("low end can pedestal into one-note boom")
    if fracture and fracture["kind"] == "peak":
        failures.append("the upper cut can dominate the whole body")
    if morph_kind in ("shift", "glide"):
        failures.append("identity can dissolve at the far end of Morph")
    failures.append("Q can turn a feature into a thin whistle")

    def _fhz(f):
        return None if not f else int(round(f["freq"]))

    brief = {
        "reference": name,
        "one_line_job": _one_line_job(dominant, identity, fracture, morph_word),
        "body_mass_region": dominant,
        "band_energies_db": {k: round(v, 1) for k, v in energies.items()},
        "identity_feature": {"hz": _fhz(identity), "lift_db": round(identity["gain"], 1) if identity else None,
                             "width_oct": round(identity["bw"], 2) if identity else None},
        "fracture_feature": ({"kind": fracture["kind"], "hz": _fhz(fracture),
                              "amount_db": round(fracture["gain"], 1), "width_oct": round(fracture["bw"], 2)}
                             if fracture else None),
        "morph_motion": {"kind": morph_kind, "describe": morph_word,
                         "centroid_shift_hz": round(net, 0), "path_hz": round(path, 0)},
        "q_motion": {"kind": q_kind, "describe": q_word},
        "midpoint_behaviour": {"describe": mid_word, "novelty_ratio": round(float(mid_novelty), 2)},
        "failure_modes": failures,
        "_home_features": [{"kind": f["kind"], "hz": _fhz(f), "amount_db": round(f["gain"], 1),
                            "width_oct": round(f["bw"], 2)} for f in home],
    }
    return brief, curves


def _one_line_job(dominant, identity, fracture, morph_word):
    bits = [str(dominant)]
    if identity:
        bits.append(f"anchored by a voice around {int(round(identity['freq']))} Hz")
    if fracture:
        bits.append("with an upper " + ("cutting tooth" if fracture["kind"] == "peak" else "hollow notch"))
    return ", ".join(bits) + f", where {morph_word}"


# ── brief -> widened target-template family ──────────────────────────────────

def _round_to(x, base):
    return int(round(x / base) * base)


def brief_to_spec(brief, name_slug, seed):
    """Convert the musical brief into a target_templates-schema spec, with WIDENED,
    OFFSET ranges. Preserves grammar (count/register/rules), not exact values."""
    feats_in = brief["_home_features"]
    features = []
    for f in feats_in:
        hz = f["hz"] or 500
        g = f["amount_db"]
        b = f["width_oct"]
        if f["kind"] == "peak":
            features.append({
                "kind": "peak",
                "freq_hz": [round(hz * 0.70), round(hz * 1.48)],
                "gain_db": [round(max(4.0, g - 4.0), 1), round(g + 5.0, 1)],
                "bw_oct": [round(max(0.09, b * 0.55), 2), round(min(1.3, b * 1.55), 2)],
            })
        else:
            features.append({
                "kind": "notch",
                "freq_hz": [round(hz * 0.68), round(hz * 1.50)],
                "gain_db": [round(max(5.0, g - 3.0), 1), round(g + 6.0, 1)],
                "bw_oct": [round(max(0.10, b * 0.6), 2), round(min(0.55, b * 1.4), 2)],
            })
    if not features:  # degenerate reference -> a safe broad body
        features = [{"kind": "peak", "freq_hz": [180, 520], "gain_db": [8, 15], "bw_oct": [0.35, 0.75]},
                    {"kind": "peak", "freq_hz": [900, 2600], "gain_db": [8, 16], "bw_oct": [0.28, 0.62]}]

    mk = brief["morph_motion"]["kind"]
    net = abs(brief["morph_motion"]["centroid_shift_hz"])
    if mk == "translate_comb":
        morph_rule = {"type": "translate_comb", "factor": [1.10, 1.46]}
    elif mk == "anchored":
        anchor = 700 if brief["body_mass_region"] in ("sub weight", "low-mid body") else 1800
        morph_rule = {"type": "anchored", "anchor_hz": anchor, "factor": [1.12, 1.55]}
    elif mk == "glide":
        morph_rule = {"type": "glide", "factor": [0.78, 1.40]}
    else:
        lo = 1.10 if net >= 0 else 0.70
        morph_rule = {"type": "shift", "factor": [lo, lo + 0.5]}

    qk = brief["q_motion"]["kind"]
    if qk == "sharpen":
        q_rule = {"type": "sharpen", "bw_scale": [0.44, 0.70], "gain_boost_db": [2.5, 7.5]}
    elif qk == "deepen":
        q_rule = {"type": "deepen", "bw_scale": [0.48, 0.72], "notch_extra_db": [3.5, 9.0]}
    else:
        q_rule = {"type": "contrast", "bw_scale": [0.48, 0.74],
                  "peak_boost_db": [1.5, 6.0], "dip_boost_db": [2.5, 8.5]}

    low_hot = brief["band_energies_db"]["sub weight"] > -3
    floor = -18 if brief["body_mass_region"] in ("sub weight", "low-mid body") else -22
    gates = {
        "low_rolloff_min_db": 0 if low_hot else 3,
        "peak_max_db": 7,
        "morph_motion_min_hz": int(max(60, min(140, 0.45 * net))),
        "morph_chaos_max": 1.0,
        "q_center_shift_max_hz": 850,
        "packed_residual_max_db": 19,
    }
    return {
        "name": name_slug,
        "label": f"brief of {brief['reference']}",
        "listening_goal": brief["one_line_job"],
        "family": "reference_brief",
        "floor_db": floor,
        "features": features,
        "morph_axis_rule": morph_rule,
        "q_axis_rule": q_rule,
        "level_guidance_db": -3,
        "failure_modes": brief["failure_modes"],
        "gates": gates,
    }


# ── similarity rejection (keep only originals) ───────────────────────────────

def candidate_corner_curves(body):
    c = {lab: tb.shipped_response(body, *tb._mq(lab)) for lab in LABELS}
    c["MID"] = tb.shipped_response(body, 0.5, 0.5)
    return c


def similarity_to_reference(cand_curves, ref_curves, min_db, mid_min_db):
    corner_dists = [tb.shape_rms(cand_curves[lab], ref_curves[lab]) for lab in LABELS]
    corner_min = float(min(corner_dists))
    mid_dist = float(tb.shape_rms(cand_curves["MID"], ref_curves["MID"]))

    ref_peaks = [f for f in find_features(ref_curves["M0_Q0"], FREQS) if f["kind"] == "peak"]
    cand_peaks = [f for f in find_features(cand_curves["M0_Q0"], FREQS) if f["kind"] == "peak"]
    matched = 0
    for rp in ref_peaks:
        if any(abs(math.log2(cp["freq"] / rp["freq"])) < math.log2(1 + FREQ_MATCH_TOL) for cp in cand_peaks):
            matched += 1
    needed = max(1, math.ceil(0.5 * len(ref_peaks))) if ref_peaks else 99
    freq_clone = matched >= needed

    reasons = []
    if corner_min < min_db:
        reasons.append(f"corner shape too close ({corner_min:.1f} dB)")
    if mid_dist < mid_min_db:
        reasons.append(f"midpoint too close ({mid_dist:.1f} dB)")
    if freq_clone and corner_min < min_db * 1.6:
        reasons.append(f"peak freqs clone the reference ({matched}/{len(ref_peaks)})")
    return {"corner_min_db": round(corner_min, 2), "mid_db": round(mid_dist, 2),
            "freq_matched": matched, "ref_peaks": len(ref_peaks),
            "original": not reasons, "reasons": reasons}


# ── generate ─────────────────────────────────────────────────────────────────

def generate(spec, ref_curves, seed, count, min_db, mid_min_db):
    run = RUN_ROOT / f"{spec['name']}_s{seed}"
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)
    morph_rule, q_rule = spec["morph_axis_rule"], spec["q_axis_rule"]
    cands = []
    for i in range(count):
        rng = random.Random(seed * 1_000_003 + i)
        base = tb.sample_features(spec, rng)
        mp = tb.sample_morph_params(morph_rule, len(base), rng)
        qp = tb.sample_q_params(q_rule, rng)
        morphed = tb.apply_morph(base, morph_rule, mp)
        corner_feats = {"M0_Q0": base, "M100_Q0": morphed,
                        "M0_Q100": tb.apply_q(base, q_rule, qp),
                        "M100_Q100": tb.apply_q(morphed, q_rule, qp)}
        corner_words = {}
        for lab in LABELS:
            curve = tb.feats_to_curve(corner_feats[lab], spec["floor_db"], FIT_FREQS)
            rows = trench_ffi.fit_corner_from_magnitude(list(zip(FIT_FREQS.tolist(), curve.tolist())), AUTH_SR)
            corner_words[KEY[lab]] = [coeffs_to_words(*r) for r in rows]
        body = tb.body_bytes(corner_words)
        boost = tb.derive_boost(body, spec["level_guidance_db"])
        gate = tb.evaluate_gates(body, corner_feats, spec, boost)
        name = f"cand_{i + 1:02d}"
        cdir = run / name
        cdir.mkdir()
        (cdir / f"{name}.body240").write_bytes(body)
        (cdir / f"{name}.cart.json").write_text(json.dumps(
            _build_cart(name, corner_words, boost, spec, seed), indent=2), encoding="utf-8")

        sim = None
        status = "broken"
        if gate["pass"]:
            sim = similarity_to_reference(candidate_corner_curves(body), ref_curves, min_db, mid_min_db)
            status = "original" if sim["original"] else "too_similar"
            if sim["original"]:
                tb.render_candidate_audio(cdir, body)
                _save_response_image(cdir / "response.png", body, name)

        (cdir / "report.json").write_text(json.dumps({
            "candidate": name, "template": spec["name"], "seed": seed, "index": i,
            "reference": spec["label"], "provenance": tb.prov_string(spec, base),
            "status": status, "gate": gate, "similarity": sim}, indent=2), encoding="utf-8")
        cands.append({"name": name, "body": body, "gate": gate, "sim": sim,
                      "status": status, "prov": tb.prov_string(spec, base), "dir": cdir})
    return run, cands


def _build_cart(name, corner_words, boost, spec, seed):
    cart = tb.build_cart(name, corner_words, boost, spec["name"], seed)
    cart["provenance"] = f"reference-brief:{spec['name']} seed={seed}"
    return cart


# ── response image (shape only -- no coefficients shown) ──────────────────────

def _save_response_image(path: Path, body, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=110)
    palette = {"M0_Q0": "#6ee7a8", "M100_Q0": "#81d4ff", "M0_Q100": "#f1d76a", "M100_Q100": "#ff9d6d"}
    for lab in LABELS:
        ax.semilogx(FREQS, tb.shipped_response(body, *tb._mq(lab)), lw=1.3, label=lab, color=palette[lab])
    ax.semilogx(FREQS, tb.shipped_response(body, 0.5, 0.5), lw=1.0, ls="--", color="#9aa", label="mid")
    ax.set_xlim(40, 16000)
    ax.set_ylim(-60, 18)
    ax.grid(alpha=0.18)
    ax.set_ylabel("dB")
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=7, ncol=5, loc="lower center")
    ax.set_facecolor("#0c0f0e")
    fig.patch.set_facecolor("#0c0f0e")
    for s in ax.spines.values():
        s.set_color("#33433c")
    ax.tick_params(colors="#9aa", labelsize=7)
    ax.yaxis.label.set_color("#9aa")
    ax.title.set_color("#cfe9dc")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ── reference preview audio ──────────────────────────────────────────────────

def render_reference_preview(run, ref_body, ref_name):
    refdir = run / "_reference"
    refdir.mkdir(exist_ok=True)
    tb.render_candidate_audio(refdir, ref_body)
    _save_response_image(refdir / "response.png", ref_body, f"reference: {ref_name}")
    (refdir / "NOTE.txt").write_text(
        "Reference preview audio for A/B comparison only. NEVER shipped or published.\n",
        encoding="utf-8")
    return refdir


# ── audition page ────────────────────────────────────────────────────────────

def _brief_html(brief):
    idf = brief["identity_feature"]
    fr = brief["fracture_feature"]
    rows = [
        ("Musical job", brief["one_line_job"]),
        ("Body mass", brief["body_mass_region"]),
        ("Identity", f"voice around {idf['hz']} Hz (+{idf['lift_db']} dB)" if idf and idf["hz"] else "broad, no single anchor"),
        ("Danger / fracture", (f"{fr['kind']} around {fr['hz']} Hz ({fr['amount_db']} dB)" if fr else "none salient")),
        ("Morph motion", brief["morph_motion"]["describe"]),
        ("Q motion", brief["q_motion"]["describe"]),
        ("Midpoint", brief["midpoint_behaviour"]["describe"]),
        ("Avoid", " · ".join(brief["failure_modes"])),
    ]
    return "\n".join(f'<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>' for k, v in rows)


def write_audition_page(run, spec, brief, seed, count, originals, too_similar, broken):
    rel = run.as_posix()
    ref_cells = tb.clip_players("_reference")
    cand_rows = []
    for c in originals:
        sim = c["sim"]
        dist = f"distance from reference: {sim['corner_min_db']} dB corners / {sim['mid_db']} dB mid"
        adv = [tb.GATE_WORDS[k] for k in c["gate"]["advisory_failed"]]
        warn = " · ".join(adv) if adv else "clean enough for ears"
        command = f"python -m tools.reference_brief --keep {rel} {c['name']} --notes \"\""
        cand_rows.append(f"""
<section class="candidate" data-name="{html.escape(c['name'])}">
  <header>
    <div>
      <h2>{html.escape(c['name'])}</h2>
      <p class="desc">{html.escape(c['prov'])}</p>
      <p class="dist">{html.escape(dist)}</p>
      <p class="warn">{html.escape(warn)}</p>
    </div>
    <div class="vote">
      <button data-vote="KEEP">KEEP</button>
      <button data-vote="MAYBE">MAYBE</button>
      <button data-vote="REJECT">REJECT</button>
    </div>
  </header>
  <img class="resp" loading="lazy" src="{html.escape(c['name'])}/response.png" alt="response">
  <div class="clips">
    {tb.clip_players(c['name'])}
  </div>
  <textarea placeholder="producer notes"></textarea>
  <code>{html.escape(command)}</code>
</section>""")

    doc = f"""<!doctype html>
<meta charset="utf-8">
<title>Reference Brief Audition — {html.escape(brief['reference'])}</title>
<style>
body{{margin:0;background:#080a0a;color:#eee9dc;font:14px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 18px 56px}}
h1{{font-size:26px;margin:0 0 6px}}
h2{{font-size:19px;margin:0 0 4px;color:#9fe7c6}}
.meta,.desc,.warn,.dist{{color:#a4aaa2;margin:0 0 5px}}
.dist{{color:#81d4ff;font:12px ui-monospace,Consolas,monospace}}
.brief{{border:1px solid #2a3d34;background:#0d1110;border-radius:8px;padding:14px 16px;margin:14px 0}}
.brief table{{border-collapse:collapse;width:100%}}
.brief th{{text-align:left;color:#f1d76a;font-weight:600;width:170px;vertical-align:top;padding:3px 8px 3px 0}}
.brief td{{padding:3px 0;color:#dfe7e0}}
.ref{{border:1px solid #5a3d18;background:#120d07;border-radius:8px;padding:14px;margin:14px 0}}
.ref h2{{color:#f1c46a}}
.candidate{{border:1px solid #20342d;background:#0d1110;border-radius:8px;padding:14px;margin:16px 0}}
header{{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}}
.vote{{display:flex;gap:8px;flex-wrap:wrap}}
button{{background:#151a18;color:#eee9dc;border:1px solid #405247;border-radius:5px;padding:7px 10px;cursor:pointer}}
button.active[data-vote=KEEP]{{background:#17422c;border-color:#6ee7a8}}
button.active[data-vote=MAYBE]{{background:#433716;border-color:#e5c75f}}
button.active[data-vote=REJECT]{{background:#421d1d;border-color:#ff6d6d}}
img.resp{{display:block;width:100%;max-width:720px;border-radius:6px;margin:10px 0;border:1px solid #18221d}}
.clips{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;margin-top:12px}}
label{{display:block;color:#f1d76a;font:12px ui-monospace,Consolas,monospace}}
label span{{color:#79827b;margin-left:8px}}
audio{{display:block;width:100%;margin-top:4px}}
textarea{{box-sizing:border-box;width:100%;min-height:54px;margin:12px 0 8px;background:#070908;color:#eee9dc;border:1px solid #28332d;border-radius:5px;padding:8px}}
code{{display:block;white-space:pre-wrap;color:#81d4ff;background:#070908;border:1px solid #18221d;border-radius:5px;padding:8px}}
@media(max-width:860px){{header{{display:block}}.vote{{margin-top:10px}}.clips{{grid-template-columns:1fr}}}}
</style>
<main>
  <h1>Reference Brief — {html.escape(brief['reference'])}</h1>
  <p class="meta">original candidates={len(originals)} · rejected as too-similar={len(too_similar)} · broken culled={len(broken)} · seed={seed} · count={count}</p>
  <p class="meta">Listen to the reference, then each candidate. The candidates do a similar musical job WITHOUT copying the reference. Buttons + notes save in this browser. Keep commands are per body.</p>

  <div class="brief">
    <h2>The brief (musical behaviour only)</h2>
    <table>{_brief_html(brief)}</table>
  </div>

  <div class="ref">
    <h2>REFERENCE preview — {html.escape(brief['reference'])}</h2>
    <p class="meta">For A/B comparison only. This is the source preset and is NEVER shipped or published.</p>
    <img class="resp" loading="lazy" src="_reference/response.png" alt="reference response">
    <div class="clips">{ref_cells}</div>
  </div>

  {''.join(cand_rows) if cand_rows else '<p class="meta">No original survivors — every candidate was broken or too close to the reference. Try a new seed or widen the brief.</p>'}
</main>
<script>
const runKey = "reference-brief:{html.escape(spec['name'])}:s{seed}";
for (const card of document.querySelectorAll(".candidate")) {{
  const name = card.dataset.name;
  const stateKey = runKey + ":" + name;
  const saved = JSON.parse(localStorage.getItem(stateKey) || "{{}}");
  const notes = card.querySelector("textarea");
  if (saved.notes) notes.value = saved.notes;
  function save(vote) {{
    localStorage.setItem(stateKey, JSON.stringify({{ vote, notes: notes.value }}));
    for (const b of card.querySelectorAll("button")) b.classList.toggle("active", b.dataset.vote === vote);
  }}
  if (saved.vote) save(saved.vote);
  for (const b of card.querySelectorAll("button")) b.onclick = () => save(b.dataset.vote);
  notes.oninput = () => {{
    const active = card.querySelector("button.active");
    save(active ? active.dataset.vote : "");
  }};
}}
</script>
"""
    (run / "audition.html").write_text(doc, encoding="utf-8")


# ── keep ──────────────────────────────────────────────────────────────────────

def do_keep(run_dir: Path, names, notes):
    KEEP_DIR.mkdir(parents=True, exist_ok=True)
    if not run_dir.exists():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 1
    brief_path = run_dir / "brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8")) if brief_path.exists() else {}
    for name in names:
        name = name if name.startswith("cand_") else f"cand_{int(name):02d}"
        cdir = run_dir / name
        report = json.loads((cdir / "report.json").read_text(encoding="utf-8"))
        stem = f"{report['template']}_s{report['seed']}_{name}"
        shutil.copy(cdir / f"{name}.body240", KEEP_DIR / f"{stem}.body240")
        shutil.copy(cdir / f"{name}.cart.json", KEEP_DIR / f"{stem}.cart.json")
        if (cdir / "response.png").exists():
            shutil.copy(cdir / "response.png", KEEP_DIR / f"{stem}.response.png")
        (KEEP_DIR / f"{stem}.keep.json").write_text(json.dumps({
            "kept_utc": datetime.now(timezone.utc).isoformat(),
            "template": report["template"], "seed": report["seed"], "index": report["index"],
            "reference": brief.get("reference", report.get("reference")),
            "provenance": report.get("provenance", ""),
            "reproduce": f"python -m tools.reference_brief --reference {brief.get('reference','?')} "
                         f"--seed {report['seed']} --count {report['index'] + 1}",
            "brief": brief, "gate": report["gate"], "similarity": report.get("similarity"),
            "notes": notes}, indent=2), encoding="utf-8")
        print(f"  kept {stem}")
    print(f"\nkept -> {KEEP_DIR}")
    return 0


# ── runnable (callable from make_class_bodies too) ───────────────────────────

def run_brief(reference, seed, count, min_distance_db=SIM_MIN_DB, framing=None):
    """Full reference→brief→generate→cull→similarity→audition flow. Returns the run dir.

    `framing` (optional) lets a caller (e.g. a filter-type card) override the
    producer-facing label/job/avoid so the reference body wears the card's name.
    """
    ref_path = resolve_reference(reference)
    ref_body, ref_name = load_reference_body(ref_path)
    print(f"REFERENCE  {ref_name}  ({ref_path.name})")

    brief, ref_curves = analyze_reference(ref_body, ref_name)
    name_slug = (framing.get("campaign") if framing else None) or \
        ("ref_" + _norm(ref_path.stem.split("_", 2)[-1]))
    spec = brief_to_spec(brief, name_slug, seed)
    if framing:
        spec["label"] = framing.get("label", spec["label"])
        spec["listening_goal"] = framing.get("job", spec["listening_goal"])
        if framing.get("avoid"):
            spec["failure_modes"] = framing["avoid"]
        brief["framed_as"] = {k: framing[k] for k in ("label", "classes") if k in framing}

    print(f"\nBRIEF — {brief['one_line_job']}")
    print(f"  body mass : {brief['body_mass_region']}")
    print(f"  identity  : {brief['identity_feature']}")
    print(f"  fracture  : {brief['fracture_feature']}")
    print(f"  morph     : {brief['morph_motion']['describe']}  ({brief['morph_motion']['kind']})")
    print(f"  Q         : {brief['q_motion']['describe']}  ({brief['q_motion']['kind']})")
    print(f"  midpoint  : {brief['midpoint_behaviour']['describe']}")

    count = max(8, min(64, count))
    mid_min = min_distance_db * (SIM_MID_MIN_DB / SIM_MIN_DB)
    print(f"\nGENERATE {count} candidates  seed={seed}  min_distance={min_distance_db} dB")
    run, cands = generate(spec, ref_curves, seed, count, min_distance_db, mid_min)

    originals = [c for c in cands if c["status"] == "original"]
    too_similar = [c for c in cands if c["status"] == "too_similar"]
    broken = [c for c in cands if c["status"] == "broken"]

    (run / "brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")
    (run / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    render_reference_preview(run, ref_body, ref_name)
    write_audition_page(run, spec, brief, seed, count, originals, too_similar, broken)

    dists = sorted(c["sim"]["corner_min_db"] for c in cands if c["sim"])
    if dists:
        print(f"\ncorner-distance distribution (dB): min={dists[0]} "
              f"median={dists[len(dists)//2]} max={dists[-1]}")
    for c in originals:
        print(f"  {c['name']}  {c['prov']}   [dist {c['sim']['corner_min_db']} dB]")
    if too_similar:
        print(f"\nrejected as too similar ({len(too_similar)}):")
        for c in too_similar:
            print(f"  {c['name']}  {'; '.join(c['sim']['reasons'])}")
    print(f"\n{len(originals)} original / {len(too_similar)} too-similar / {len(broken)} broken  of {count}")
    print(f"audition -> {run / 'audition.html'}")
    print("NEXT: open the audition page, A/B against the reference, mark KEEP/MAYBE/REJECT, then:")
    print(f"  python -m tools.reference_brief --keep {run.as_posix()} <NN> --notes \"why\"")
    return run


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", "-r", help="reference name/slug/number (see --list-refs)")
    ap.add_argument("--list-refs", action="store_true")
    ap.add_argument("--seed", type=int, default=1001)
    ap.add_argument("--count", type=int, default=24, help="candidates to generate (8-64)")
    ap.add_argument("--min-distance-db", type=float, default=SIM_MIN_DB,
                    help="reject candidates closer than this to the reference (corner shape)")
    ap.add_argument("--keep", nargs="+", metavar=("RUN_DIR", "CAND"))
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    if args.list_refs:
        print("\nP2K-style references (read for behaviour, never copied):\n")
        for r in list_references():
            print(f"  {r['slug']:<22} {r['name']}")
        return 0

    if args.keep:
        return do_keep(Path(args.keep[0]), args.keep[1:], args.notes)

    if not args.reference:
        print("pick a reference (or --list-refs):", file=sys.stderr)
        return 1
    if not trench_ffi.available() or not trench_ffi.engine_available():
        print("trench-core not built. Run: cargo build --release -p trench-core", file=sys.stderr)
        return 1

    run_brief(args.reference, args.seed, args.count, args.min_distance_db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
