#!/usr/bin/env python3
"""Floor-transfer experiment — Hedz M0_Q0 floor/gain discipline onto Small Talk.

Analysis + audition only. We move ONLY per-row gain (kernel c4 = biquad b0),
keeping every pole (c2,c3) and every zero-ratio (c0,c1) exactly as Small Talk
authored them. So no Hedz pole frequency and no Hedz coefficient is copied — only
its loudness *floor* discipline (uniform per-stage b0, per-band target levels).

Variants per corner:
  A  original Small Talk
  B  set every row's b0/c4 to the Hedz floor b0 (uniform), poles preserved
  C  raise low/body/bite in-band rows toward the Hedz measured deltas
  D  B + C, then constrain air so it does not exceed the Hedz air floor

Each variant is exported as .body240 + .cart.json (packedWords authority), then
rendered (slow Morph×Q sweep + teleport stress) so it is auditionable.

  python tools/floor_transfer.py
"""
from __future__ import annotations

import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ROOT must precede tools/ on the path so `pyruntime.*` submodules all resolve
# from ROOT (a leading tools/ entry shadows later pyruntime submodule lookups).
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
from scipy.io import wavfile  # noqa: E402

from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime import packed_interp as pi  # noqa: E402
import teleport_stress as ts  # noqa: E402  (blessed runtime-style render path)
import hedz_floor_profile as hf  # noqa: E402  (exact band-measurement method)

SRC_BODY = os.path.join(ROOT, "bodies", "small_talk.cart.json")
RECIPE = os.path.join(ROOT, "dev", "tmp", "hedz_floor_profile", "recipe.json")
OUT = os.path.join(ROOT, "dev", "tmp", "floor_transfer")
AUTH_SR = 39062.5
STAGES = 6
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
BANDS = hf.BANDS  # (name, lo, hi) for low/body/bite/air
FREQS = np.logspace(math.log10(20.0), math.log10(16000.0), 2048)


# ── kernel helpers (c4-only edits; poles c2,c3 and zero-ratios c0,c1 untouched) ──
def pole_freq_radius(stage):
    c0, c1, c2, c3, c4 = stage
    a1, a2 = c2 - 2.0, 1.0 - c3
    r = max(a2, 0.0) ** 0.5
    if r <= 1e-9:
        return (None, r)
    if a1 * a1 - 4.0 * a2 >= 0.0:  # real poles, no resonant freq
        return (None, r)
    theta = math.acos(max(-1.0, min(1.0, -a1 / (2.0 * r))))
    return (theta * AUTH_SR / (2.0 * math.pi), r)


def band_of(freq):
    if freq is None:
        return None
    for name, lo, hi in BANDS:
        if lo <= freq < hi:
            return name
    return "air" if freq >= BANDS[-1][2] else "low"


def set_c4(stage, c4):
    return (stage[0], stage[1], stage[2], stage[3], c4)


def scale_c4(stage, gain):
    return (stage[0], stage[1], stage[2], stage[3], stage[4] * gain)


# ── load Small Talk: 4 corners x 6 kernel stages, by label ──
def load_small_talk():
    doc = json.load(open(SRC_BODY, encoding="utf-8"))
    by_label = {kf["label"]: kf for kf in doc["keyframes"]}
    boost = float(by_label["M0_Q0"].get("boost", doc.get("boost", 1.0)))
    corners = {}
    for label in CORNER_ORDER:
        kf = by_label[label]
        stages = []
        for st in kf["stages"][:STAGES]:
            stages.append((st["c0"], st["c1"], st["c2"], st["c3"], st["c4"]))
        corners[label] = stages
    return doc.get("name", "Small Talk"), boost, corners


# ── variant builders (operate per corner, edit c4 only) ──
def variant_A(corner, _ctx):
    return [tuple(s) for s in corner]


def variant_B(corner, ctx):
    return [set_c4(s, ctx["hedz_b0"]) for s in corner]


def apply_band_raises(corner, raises_db):
    """Multiply in-band rows' c4 by 10^(raise/20) for the named bands."""
    out = []
    for s in corner:
        f, _r = pole_freq_radius(s)
        b = band_of(f)
        g = 10.0 ** (raises_db.get(b, 0.0) / 20.0) if b else 1.0
        out.append(scale_c4(s, g))
    return out


def variant_C(corner, ctx):
    # raise low/body/bite toward the Hedz measured deltas; air untouched
    raises = {b: max(0.0, ctx["raise_db"][b]) for b in ("low", "body", "bite")}
    return apply_band_raises(corner, raises)


def variant_D(corner, ctx):
    # B floor, then low/body/bite raises, then cap air to the Hedz air floor
    base = variant_B(corner, ctx)
    raises = {b: max(0.0, ctx["raise_db"][b]) for b in ("low", "body", "bite")}
    raised = apply_band_raises(base, raises)
    # measure air on the raised corner; if over the Hedz air target, pull air rows down
    air_now = band_levels_of(raised, ctx["boost"])["air"]
    air_tgt = ctx["target"]["air"]
    out = raised
    if math.isfinite(air_now) and air_now > air_tgt:
        cut = 10.0 ** ((air_tgt - air_now) / 20.0)
        out = []
        for s in raised:
            f, _r = pole_freq_radius(s)
            out.append(scale_c4(s, cut) if band_of(f) == "air" else s)
    return out


VARIANTS = {
    "A_original": variant_A,
    "B_floor_b0": variant_B,
    "C_band_raise": variant_C,
    "D_floor_band_aircap": variant_D,
}


# ── measurement ──
def band_levels_of(corner_stages, boost):
    enc = [EncodedCoeffs(*s) for s in corner_stages]
    return hf.band_levels(enc, FREQS, AUTH_SR, boost)


def c4_product(corner_stages):
    p = 1.0
    for s in corner_stages:
        p *= s[4]
    return p


def pack_corner(corner_stages):
    """kernel stages -> 6 word-tuples (derived-packed-canonical)."""
    return [pi.coeffs_to_words(*s) for s in corner_stages]


def roundtrip_corner(corner_stages):
    """pack then decode -> kernel stages, the actual 240-byte path."""
    return [pi.words_to_coeffs(w) for w in pack_corner(corner_stages)]


def assemble_240(variant_corners):
    """variant_corners: {label: 6 kernel stages} -> 240 bytes, corner-major order."""
    out = bytearray()
    for label in CORNER_ORDER:
        for s in variant_corners[label]:
            for w in pi.coeffs_to_words(*s):
                out += int(w & 0xFFFF).to_bytes(2, "little")
    assert len(out) == 240, len(out)
    return bytes(out)


def write_cart(path, name, boost, variant_corners):
    keyframes = []
    for label in CORNER_ORDER:
        stages = variant_corners[label]
        words = [list(pi.coeffs_to_words(*s)) for s in stages]
        st_json = [{"c0": s[0], "c1": s[1], "c2": s[2], "c3": s[3], "c4": s[4]} for s in stages]
        keyframes.append({"label": label, "boost": boost, "packedWords": words, "stages": st_json})
    doc = {
        "format": "compiled-v1",
        "name": name,
        "provenance": "floor-transfer-experiment (gain-only; poles preserved)",
        "sampleRate": AUTH_SR,
        "authoring_sample_rate_hz": AUTH_SR,
        "stages": STAGES,
        "cornerOrder": list(CORNER_ORDER),
        "keyframes": keyframes,
    }
    json.dump(doc, open(path, "w", encoding="utf-8"), indent=2)


# ── render (in-process, mirrors teleport_stress containment so it "sounds like the runtime") ──
def corners_to_words_dict(variant_corners):
    return {LABEL_TO_KEY[label]: pack_corner(variant_corners[label]) for label in CORNER_ORDER}


def render_sweep(words_dict, sr, seconds, drive=4.0):
    n = int(seconds * sr)
    x = ts.source_signal(n, sr)
    t = np.arange(n) / sr
    T = seconds
    morph = 0.5 - 0.5 * np.cos(2.0 * math.pi * 0.4 / T * t)   # slow Morph traverse
    q = 0.5 - 0.5 * np.cos(2.0 * math.pi * 0.9 / T * t)       # different rate -> Lissajous
    states = np.zeros((STAGES, 2))
    raw = np.zeros(n)
    nonfinite = 0
    for i in range(n):
        rows = pi.packed_bilinear(words_dict, float(morph[i]), float(q[i]))
        v = float(x[i])
        for si, row in enumerate(rows):
            b0, b1, b2, a1, a2 = pi.kernel_to_biquad(row)
            y = b0 * v + states[si, 0]
            w1 = b1 * v - a1 * y + states[si, 1]
            w2 = b2 * v - a2 * y
            if not (math.isfinite(y) and math.isfinite(w1) and math.isfinite(w2)):
                y = w1 = w2 = 0.0
                nonfinite += 1
            states[si, 0], states[si, 1] = w1, w2
            v = y
        raw[i] = v if math.isfinite(v) else 0.0
    wet = ts.dc_block(raw, sr)
    wet = np.tanh(wet * drive)
    peak = float(np.max(np.abs(wet)) + 1e-12)
    if peak > 0.98:
        wet *= 0.98 / peak
    return wet.astype(np.float32), nonfinite


def main():
    os.makedirs(OUT, exist_ok=True)
    name, boost, st = load_small_talk()
    recipe = json.load(open(RECIPE, encoding="utf-8"))
    target = recipe["target_band_levels_db"]
    hedz_b0 = float(recipe["recipe"]["stages"][0]["b0"])
    # Small Talk M0_Q0 deltas (current - target) from the recipe candidate list
    st_cand = next(c for c in recipe["candidates"] if c["file"].replace("\\", "/").endswith("small_talk.cart.json"))
    deltas = st_cand["deltas"]  # low/body/bite/air = current - target
    raise_db = {b: -deltas[b] for b in ("low", "body", "bite", "air")}  # +ve = needs raising
    ctx = {"hedz_b0": hedz_b0, "target": target, "raise_db": raise_db, "boost": boost}

    print(f"Source: {name}  boost={boost}  Hedz floor b0={hedz_b0:.5f}")
    print(f"Small Talk M0_Q0 deltas (current-target): {deltas}")
    print(f"Band raises applied (low/body/bite): "
          f"{ {b: round(max(0.0, raise_db[b]),2) for b in ('low','body','bite')} }")

    # build all variants
    built = {}  # vkey -> {label: stages}
    for vkey, fn in VARIANTS.items():
        built[vkey] = {label: fn(st[label], ctx) for label in CORNER_ORDER}

    report = {
        "experiment": "floor-transfer (Hedz M0_Q0 floor onto Small Talk; gain-only, poles preserved)",
        "source_body": "bodies/small_talk.cart.json",
        "target_profile": "dev/tmp/hedz_floor_profile/recipe.json",
        "authoring_sr_hz": AUTH_SR,
        "boost": boost,
        "hedz_floor_b0": hedz_b0,
        "hedz_target_band_levels_db": target,
        "smalltalk_m0q0_deltas_current_minus_target": deltas,
        "band_raises_applied_db": {b: round(max(0.0, raise_db[b]), 3) for b in ("low", "body", "bite")},
        "variants": {},
        "method_note": (
            "Only kernel c4 (=biquad b0) is edited; c0,c1 (zero ratios) and c2,c3 "
            "(poles) are byte-for-byte preserved. The cascade is a SERIES product, so a "
            "per-stage b0 scale is a BROADBAND gain: it shifts overall loudness (and how "
            "hard the runtime tanh containment is driven) but cannot move one band relative "
            "to another. Band BALANCE lives in the poles/zeros, which were not copied."
        ),
    }

    # per-variant analysis + export + render
    pole_drift_global = 0.0
    for vkey, vcorners in built.items():
        # band levels on M0_Q0 (linear, pre-pack) + shape vs A
        m0 = vcorners["M0_Q0"]
        lv = band_levels_of(m0, boost)
        var_deltas = {b: lv[b] - target[b] for b in ("low", "body", "bite", "air")}
        dv = np.array([var_deltas[b] for b in ("low", "body", "bite", "air")])
        shape = dv - dv.mean()

        # packed roundtrip: pole freq drift (poles untouched -> only quantization)
        max_drift = 0.0
        pole_rows = {}
        for label in CORNER_ORDER:
            before = [pole_freq_radius(s) for s in vcorners[label]]
            after = [pole_freq_radius(s) for s in roundtrip_corner(vcorners[label])]
            fb = [round(f, 1) if f else None for f, _ in before]
            fa = [round(f, 1) if f else None for f, _ in after]
            pole_rows[label] = {"before_hz": fb, "after_hz": fa}
            for (f0, _), (f1, _) in zip(before, after):
                if f0 and f1:
                    max_drift = max(max_drift, abs(f1 - f0))
        pole_drift_global = max(pole_drift_global, max_drift)

        # export .body240 + .cart.json
        body240 = assemble_240(vcorners)
        with open(os.path.join(OUT, f"{vkey}.body240"), "wb") as f:
            f.write(body240)
        write_cart(os.path.join(OUT, f"{vkey}.cart.json"), f"{name} [{vkey}]", boost, vcorners)

        # stability over the morph x Q surface (runtime-consistent probe)
        words_dict = corners_to_words_dict(vcorners)
        gm = np.linspace(0, 1, 64)
        mm, qq = np.meshgrid(gm, gm)
        stab = ts.static_probe(words_dict, mm.ravel(), qq.ravel())

        # render: slow sweep + 3 teleport modes
        vdir = os.path.join(OUT, vkey)
        os.makedirs(vdir, exist_ok=True)
        sr = ts.SR_DEFAULT
        sweep, sweep_nf = render_sweep(words_dict, sr, seconds=4.0)
        wavfile.write(os.path.join(vdir, "sweep.wav"), sr, sweep)
        x = ts.source_signal(int(1.25 * sr), sr)
        teleport_nf = 0
        for mode in ("noise", "square_150hz", "derivative"):
            morph, q = ts.drivers(mode, x, sr, 0x513DF2)
            wet, dyn = ts.process_teleport(words_dict, x, morph, q, sr, 4.0)
            teleport_nf += int(dyn.get("nonfinite_events", 0))
            wavfile.write(os.path.join(vdir, f"teleport_{mode}.wav"), sr, wet)

        report["variants"][vkey] = {
            "m0q0_band_levels_db": {k: round(v, 3) for k, v in lv.items()},
            "m0q0_deltas_vs_hedz_db": {k: round(v, 3) for k, v in var_deltas.items()},
            "band_shape_rms_vs_hedz_db": round(float(np.sqrt((shape ** 2).mean())), 4),
            "c4_product_m0q0": round(c4_product(m0), 8),
            "c4_product_m0q0_db": round(20.0 * math.log10(max(c4_product(m0), 1e-30)), 3),
            "packed_roundtrip_pole_drift_max_hz": round(max_drift, 3),
            "pole_freqs": pole_rows,
            "stability": {
                "probe_points": stab["probe_points"],
                "nonfinite_coeff_rows": stab["nonfinite_coeff_rows"],
                "unstable_denominator_rows": stab["unstable_denominator_rows"],
                "max_pole_radius": round(stab["max_pole_radius"], 6),
            },
            "render_nonfinite": {"sweep": sweep_nf, "teleport": teleport_nf},
        }
        print(f"  {vkey}: low/body/bite/air d-vs-Hedz = "
              f"{[round(var_deltas[b],1) for b in ('low','body','bite','air')]}  "
              f"shapeRMS={report['variants'][vkey]['band_shape_rms_vs_hedz_db']}  "
              f"maxR={stab['max_pole_radius']:.4f}  unstable={stab['unstable_denominator_rows']}")

    # shape-invariance proof: B/C/D shape vs A
    a_shape = report["variants"]["A_original"]["band_shape_rms_vs_hedz_db"]
    report["band_balance_invariance"] = {
        "A_shape_rms_db": a_shape,
        "max_shape_rms_drift_from_A_db": round(
            max(abs(report["variants"][v]["band_shape_rms_vs_hedz_db"] - a_shape) for v in built), 4
        ),
        "interpretation": (
            "If gain-only edits preserved band balance, every variant's band-shape RMS "
            "equals A's (drift ~ packing quantization only). It does — proving b0/c4 is "
            "broadband and the Hedz band BALANCE cannot transfer without its poles/zeros."
        ),
    }
    report["packed_roundtrip_verdict"] = (
        f"max pole-frequency drift across all variants/corners = {pole_drift_global:.2f} Hz "
        f"(< ~5 Hz is inaudible). Poles are gain-independent, so this is purely the "
        f"Small Talk stages -> 240-byte packed quantization, identical across variants."
    )

    json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), indent=2)
    write_report_md(report)
    write_audition_html(report)
    print(f"\nWrote -> {os.path.relpath(OUT, ROOT)}  (pole drift {pole_drift_global:.2f} Hz)")


def write_report_md(r):
    L = []
    L.append("# Floor-transfer experiment — Hedz M0_Q0 floor onto Small Talk\n")
    L.append("Gain-only (kernel `c4` = biquad `b0`). **No Hedz pole frequency or coefficient "
             "is copied** — `c0,c1` (zero ratios) and `c2,c3` (poles) are byte-for-byte "
             "preserved from Small Talk. We move only the loudness floor / per-stage gain.\n")
    L.append(f"- Source: `bodies/small_talk.cart.json` (boost {r['boost']})")
    L.append(f"- Target floor: `dev/tmp/hedz_floor_profile/recipe.json` — Hedz uniform b0 "
             f"`{r['hedz_floor_b0']:.5f}`, band targets low {r['hedz_target_band_levels_db']['low']:+.1f} / "
             f"body {r['hedz_target_band_levels_db']['body']:+.1f} / bite {r['hedz_target_band_levels_db']['bite']:+.1f} / "
             f"air {r['hedz_target_band_levels_db']['air']:+.1f} dB")
    L.append(f"- Small Talk M0_Q0 deltas (current−target): "
             f"low {r['smalltalk_m0q0_deltas_current_minus_target']['low']:+.2f} · "
             f"body {r['smalltalk_m0q0_deltas_current_minus_target']['body']:+.2f} · "
             f"bite {r['smalltalk_m0q0_deltas_current_minus_target']['bite']:+.2f} · "
             f"air {r['smalltalk_m0q0_deltas_current_minus_target']['air']:+.2f} dB → "
             f"raises applied {r['band_raises_applied_db']}\n")

    L.append("## Variants\n")
    L.append("| variant | what | low Δ | body Δ | bite Δ | air Δ | band-shape RMS | c4·prod dB | max r | unstable | nonfinite |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    desc = {
        "A_original": "original Small Talk",
        "B_floor_b0": "uniform b0 = Hedz floor",
        "C_band_raise": "raise low/body/bite",
        "D_floor_band_aircap": "B + raises + air cap",
    }
    for vkey in ("A_original", "B_floor_b0", "C_band_raise", "D_floor_band_aircap"):
        v = r["variants"][vkey]
        d = v["m0q0_deltas_vs_hedz_db"]
        st = v["stability"]
        nf = v["render_nonfinite"]["sweep"] + v["render_nonfinite"]["teleport"] + st["nonfinite_coeff_rows"]
        L.append(f"| {vkey} | {desc[vkey]} | {d['low']:+.1f} | {d['body']:+.1f} | {d['bite']:+.1f} | "
                 f"{d['air']:+.1f} | {v['band_shape_rms_vs_hedz_db']:.3f} | {v['c4_product_m0q0_db']:+.1f} | "
                 f"{st['max_pole_radius']:.4f} | {st['unstable_denominator_rows']} | {nf} |")
    L.append("")

    inv = r["band_balance_invariance"]
    L.append("## The finding — floor/gain discipline is broadband; tone is not transferable this way\n")
    L.append(f"Band-shape RMS (the relative low↔body↔bite↔air balance, gain removed) is "
             f"**{inv['A_shape_rms_db']:.2f} dB for A and drifts at most "
             f"{inv['max_shape_rms_drift_from_A_db']:.3f} dB across B/C/D**. That near-zero drift "
             f"is the proof: editing per-row `b0/c4` while preserving poles + zero-ratios is a "
             f"pure **broadband** level move (the cascade is a series product, so ∏b0 is one "
             f"scalar on the whole magnitude). So:\n")
    L.append("- **What transfers:** the loudness *floor* — overall level, the per-stage gain "
             "envelope, and (through the runtime `tanh` containment) how hard the body drives "
             "into saturation. B sits Small Talk exactly on Hedz's `b0` floor.")
    L.append("- **What does NOT transfer:** Hedz's band *balance*. Small Talk's air sits "
             f"{r['smalltalk_m0q0_deltas_current_minus_target']['air']:+.1f} dB over the Hedz air "
             "floor; D's air-cap pulls air down **but pulls body/bite down with it** (broadband), "
             "so air-relative-to-body is unchanged. Taming air without darkening the body needs a "
             "pole/zero edit — which the brief correctly forbids (that would be copying tone).\n")
    L.append("This is the floor/ceiling split: **fit/borrow floors (gain) freely; ceilings (tone) "
             "live in the poles you keep Small-Talk-derived.**\n")

    L.append("## Packed round-trip\n")
    L.append(r["packed_roundtrip_verdict"] + "\n")
    L.append("Pole frequencies before/after the 240-byte round-trip (M0_Q0, Hz):\n")
    pr = r["variants"]["A_original"]["pole_freqs"]["M0_Q0"]
    L.append("| row | before | after |")
    L.append("|---:|---|---|")
    for i, (b, a) in enumerate(zip(pr["before_hz"], pr["after_hz"])):
        L.append(f"| {i} | {b} | {a} |")
    L.append("")

    L.append("## Audition\n")
    L.append("Open `audition.html` (audio first). Each variant has a slow Morph×Q **sweep** and "
             "three **teleport** stress renders. Listen for: B/C/D differ from A mainly in "
             "*loudness/saturation density* (the tanh driven harder), not in vowel/band character "
             "— the audible confirmation of the finding above.\n")
    open(os.path.join(OUT, "vocal_floor_report.md"), "w", encoding="utf-8").write("\n".join(L))


def write_audition_html(r):
    order = ["A_original", "B_floor_b0", "C_band_raise", "D_floor_band_aircap"]
    desc = {
        "A_original": "original Small Talk (baseline)",
        "B_floor_b0": "uniform b0 = Hedz floor (poles preserved)",
        "C_band_raise": "raise low/body/bite toward Hedz deltas",
        "D_floor_band_aircap": "B + band raises + air capped to Hedz air",
    }
    blocks = []
    for vkey in order:
        v = r["variants"][vkey]
        d = v["m0q0_deltas_vs_hedz_db"]
        meta = (f"Δ vs Hedz: low {d['low']:+.1f} body {d['body']:+.1f} bite {d['bite']:+.1f} "
                f"air {d['air']:+.1f} dB · max r {v['stability']['max_pole_radius']:.3f} · "
                f"unstable {v['stability']['unstable_denominator_rows']}")
        rows = "".join(
            f"<div class=row><b>{lbl}</b>"
            f"<audio controls preload=metadata src='{vkey}/{f}'></audio></div>"
            for lbl, f in [
                ("sweep (Morph×Q)", "sweep.wav"),
                ("teleport · noise", "teleport_noise.wav"),
                ("teleport · 150 Hz", "teleport_square_150hz.wav"),
                ("teleport · derivative", "teleport_derivative.wav"),
            ]
        )
        blocks.append(f"<section><h2>{vkey}</h2><p class=meta>{desc[vkey]}</p>"
                      f"<p class=meta>{meta}</p>{rows}</section>")
    inv = r["band_balance_invariance"]
    html = (
        "<!doctype html><meta charset=utf-8><title>Floor transfer — Small Talk</title>"
        "<style>body{background:#0a0d0c;color:#bec5be;font:14px/1.5 monospace;margin:24px;max-width:760px}"
        "h1{color:#5bef6f}h2{color:#31c6c9;margin-top:26px}.row{margin:5px 0;display:flex;gap:10px;align-items:center}"
        ".row b{display:inline-block;min-width:150px}.meta{color:#69836f}audio{height:30px}</style>"
        "<h1>Floor transfer — Hedz floor onto Small Talk</h1>"
        "<p class=meta>Gain-only (b0/c4); poles + zero-ratios preserved. Audio first. "
        f"Band-shape drift across B/C/D vs A = {inv['max_shape_rms_drift_from_A_db']:.3f} dB "
        "(≈0 → variants differ in loudness/saturation, not band balance).</p>"
        + "\n".join(blocks)
    )
    open(os.path.join(OUT, "audition.html"), "w", encoding="utf-8").write(html)


if __name__ == "__main__":
    main()
