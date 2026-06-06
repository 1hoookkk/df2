#!/usr/bin/env python3
"""target_browser - generate whole Morph/Q filter bodies from a musical archetype.

The end-to-end path (producer-first, no coefficients, no source WAVs):

  1. python -m tools.target_browser --template razor_shell --seed 1001 --count 32
        -> generates whole 4-corner bodies, throws out the broken ones,
           writes audition.html, and drops survivors into bodies/generated/.
  2. Listen in the audition page: four corners, midpoint, Morph/Q/diagonal sweeps.
  3. Mark KEEP / MAYBE / REJECT and write notes while listening.
  4. Promote the ones that hit:
        python -m tools.target_browser --keep <run_dir> cand_03 --notes "why"

A body = 4 corners (M0_Q0, M100_Q0, M0_Q100, M100_Q100). Morph = identity /
movement / geometry. Q = sharpness / contrast / depth. Stages are packing only.

  python -m tools.target_browser --list      # the archetypes
"""
from __future__ import annotations

import argparse
import html
import json
import math
import random
import shutil
import struct
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HERE = str(Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", _HERE, str(ROOT))]
sys.path.insert(0, str(ROOT))

import numpy as np

from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from pyruntime.packed_interp import coeffs_to_words

TEMPLATES = ROOT / "tools" / "target_templates.json"
GEN_DIR = ROOT / "bodies" / "generated"          # the Factory's PRESET folder
RUN_ROOT = ROOT / "dev" / "tmp" / "target_browser"  # full records for --keep
KEEP_DIR = ROOT / "dev" / "tmp" / "keepers"

AUTH_SR = 39062.5
RENDER_SR = 44100
SWEEP_BLOCK = 512
FREQS = np.logspace(math.log10(20.0), math.log10(16000.0), 512)
FIT_FREQS = np.logspace(math.log10(40.0), math.log10(16000.0), 192)
LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
BAND_LO_HI = (120.0, 8000.0)
CLIPS = [
    ("m0_q0.wav", "M0_Q0", "Home", 0.0, 0.0),
    ("m100_q0.wav", "M100_Q0", "Morph", 1.0, 0.0),
    ("m0_q100.wav", "M0_Q100", "Tension", 0.0, 1.0),
    ("m100_q100.wav", "M100_Q100", "Morph + Tension", 1.0, 1.0),
    ("midpoint.wav", "Midpoint", "Middle", 0.5, 0.5),
]

GATE_WORDS = {
    "stable": "unstable (would blow up)",
    "finite": "broke (non-finite)",
    "low_rolloff": "low end too boomy (pedestal)",
    "peak": "too hot / clips",
    "morph_motion": "barely moves on Morph",
    "morph_chaos": "Morph thrashes (not musical)",
    "q_center_shift": "Q relocates instead of sharpening",
    "packed_residual": "off-target after packing",
    "terrain": "too flat / not enough mountain character",
}


# ── feature sampling + axis rules ────────────────────────────────────────────

def _loguniform(rng, lo, hi):
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def sample_features(spec, rng):
    return [{"kind": f["kind"], "freq": _loguniform(rng, *f["freq_hz"]),
             "gain": rng.uniform(*f["gain_db"]), "bw": rng.uniform(*f["bw_oct"])}
            for f in spec["features"]]


def sample_morph_params(rule, n, rng):
    if rule["type"] == "glide":
        return {"factors": [rng.uniform(*rule["factor"]) for _ in range(n)]}
    return {"factor": rng.uniform(*rule["factor"])}


def sample_q_params(rule, rng):
    t = rule["type"]
    if t == "sharpen":
        return {"bw_scale": rng.uniform(*rule["bw_scale"]), "gain_boost": rng.uniform(*rule["gain_boost_db"])}
    if t == "deepen":
        return {"bw_scale": rng.uniform(*rule["bw_scale"]), "notch_extra": rng.uniform(*rule["notch_extra_db"])}
    return {"bw_scale": rng.uniform(*rule["bw_scale"]),
            "peak_boost": rng.uniform(*rule["peak_boost_db"]), "dip_boost": rng.uniform(*rule["dip_boost_db"])}


def apply_morph(feats, rule, p):
    t = rule["type"]
    out = [dict(f) for f in feats]
    if t == "shift":
        for f in out:
            if f["kind"] == "peak":
                f["freq"] *= p["factor"]
    elif t == "glide":
        for f, fac in zip(out, p["factors"]):
            f["freq"] *= fac
    elif t == "anchored":
        for f in out:
            if f["freq"] > rule["anchor_hz"]:
                f["freq"] *= p["factor"]
    elif t == "translate_comb":
        for f in out:
            if f["kind"] == "notch":
                f["freq"] *= p["factor"]
    return out


def apply_q(feats, rule, p):
    t = rule["type"]
    out = [dict(f) for f in feats]
    for f in out:
        f["bw"] *= p["bw_scale"]
        if t == "sharpen" and f["kind"] == "peak":
            f["gain"] += p["gain_boost"]
        elif t == "deepen" and f["kind"] == "notch":
            f["gain"] += p["notch_extra"]
        elif t == "contrast":
            f["gain"] += p["peak_boost"] if f["kind"] == "peak" else p["dip_boost"]
    return out


def feats_to_curve(feats, floor_db, freqs):
    db = np.full(len(freqs), float(floor_db))
    for f in feats:
        shape = np.exp(-((np.log2(freqs / f["freq"]) / max(f["bw"], 0.05)) ** 2))
        db = db + f["gain"] * shape if f["kind"] == "peak" else db - f["gain"] * shape
    return db


def prov_string(spec, base):
    peaks = [round(f["freq"]) for f in base if f["kind"] == "peak"]
    notches = [round(f["freq"]) for f in base if f["kind"] == "notch"]
    s = spec["label"]
    if peaks:
        s += " · peaks " + "/".join(str(p) for p in peaks) + " Hz"
    if notches:
        s += " · notch " + "/".join(str(n) for n in notches) + " Hz"
    return s


def sample_corner_features(spec, rng):
    """Sample four endpoint programs directly when an archetype supplies them.

    Normal templates derive corners from one base target. `corner_features`
    templates instead describe each packed endpoint as its own target terrain,
    closer to the P2K study bodies where the four corners are distinct actor
    programs rather than simple offsets from one curve.
    """
    corner_specs = spec["corner_features"]
    out = {}
    for lab in LABELS:
        feats = corner_specs.get(lab)
        if feats is None:
            raise KeyError(f"{spec['name']} missing corner_features.{lab}")
        out[lab] = sample_features({"features": feats}, rng)
    return out


# ── producer audition audio ──────────────────────────────────────────────────

def audition_source(seconds=1.0):
    n = int(RENDER_SR * seconds)
    t = np.arange(n) / RENDER_SR
    env = np.minimum(1.0, 18.0 * t) * np.exp(-t / (seconds * 0.9))
    f0 = 55.0 + 72.0 * np.exp(-t / 0.035)
    phase = 2.0 * np.pi * np.cumsum(f0) / RENDER_SR
    bass = np.sin(phase) * np.exp(-t / 0.45)
    saw = 2.0 * ((110.0 * t) % 1.0) - 1.0
    bite = 0.35 * saw * np.exp(-t / 0.9)
    click = np.zeros(n)
    c = max(1, int(RENDER_SR * 0.004))
    click[:c] = np.linspace(1.0, 0.0, c)
    x = (0.72 * bass + 0.28 * bite + 0.12 * click) * env
    peak = float(np.max(np.abs(x)))
    return (x / peak * 0.75 if peak > 1e-9 else x).astype(np.float32)


def _safe_wet(raw):
    wet = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    if wet.size == 0:
        return wet
    wet = wet - float(np.mean(wet))
    peak = float(np.max(np.abs(wet)))
    return wet / peak * 0.88 if peak > 1e-9 else wet


def write_wav(path, signal):
    pcm = (np.clip(signal, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RENDER_SR)
        w.writeframes(pcm.tobytes())


def render_held(body, m, q, source):
    raw = trench_ffi.engine_render(
        body, float(m), float(q), source.astype(np.float32).tobytes(), RENDER_SR
    )
    return _safe_wet(raw)


def render_sweep(body, mode, source):
    nblocks = max(1, (len(source) + SWEEP_BLOCK - 1) // SWEEP_BLOCK)
    ramp = np.linspace(0.0, 1.0, nblocks)
    zeros = np.zeros(nblocks)
    half = np.full(nblocks, 0.5)
    if mode == "morph":
        morph, q = ramp, zeros
    elif mode == "q":
        morph, q = half, ramp
    else:
        morph, q = ramp, ramp
    raw = trench_ffi.engine_render_automated(
        body, morph, q, source.astype(np.float32).tobytes(), RENDER_SR, block=SWEEP_BLOCK
    )
    return _safe_wet(raw)


def render_candidate_audio(cdir, body):
    source = audition_source()
    for fname, _code, _label, m, q in CLIPS:
        write_wav(cdir / fname, render_held(body, m, q, source))
    write_wav(cdir / "morph_sweep.wav", render_sweep(body, "morph", source))
    write_wav(cdir / "q_sweep.wav", render_sweep(body, "q", source))
    write_wav(cdir / "diagonal_sweep.wav", render_sweep(body, "diagonal", source))


# ── body assembly + shipped response ─────────────────────────────────────────

def body_bytes(corner_words) -> bytes:
    flat = []
    for label in LABELS:
        for w in corner_words[KEY[label]]:
            flat.extend(int(x) & 0xFFFF for x in w)
    return struct.pack("<" + "H" * 120, *flat)


def _mq(label):
    return {"M0_Q0": (0.0, 0.0), "M100_Q0": (1.0, 0.0),
            "M0_Q100": (0.0, 1.0), "M100_Q100": (1.0, 1.0)}[label]


def shipped_response(body, m, q):
    rows = trench_ffi.packed_interpolate(body, m, q)
    return cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, AUTH_SR)


def centroid(db):
    w = 10.0 ** (db / 20.0)
    return float(np.sum(FREQS * w) / max(np.sum(w), 1e-12))


def derive_boost(body, level_db):
    peak = float(shipped_response(body, 0.0, 0.0).max())
    return float(min(max(10.0 ** ((level_db - peak) / 20.0), 0.02), 32.0))


def grid_stability(body, n=12):
    g = np.linspace(0.0, 1.0, n)
    maxr, unstable, nonfinite = 0.0, 0, 0
    for m in g:
        for q in g:
            p = trench_ffi.packed_probe(body, float(m), float(q))
            maxr = max(maxr, p["max_pole_radius"])
            unstable += bin(p["unstable_mask"]).count("1")
            nonfinite += bin(p["nonfinite_mask"]).count("1")
    return maxr, unstable, nonfinite


def band_mean(db, lo, hi):
    m = (FREQS >= lo) & (FREQS < hi)
    return float(np.mean(db[m])) if np.any(m) else float("nan")


def shape_rms(a, b):
    lo, hi = BAND_LO_HI
    m = (FREQS >= lo) & (FREQS <= hi)
    r = a[m] - b[m]
    r = r - r.mean()
    return float(np.sqrt((r * r).mean()))


def terrain_metrics(responses):
    """Measure visible response character for shortlist ranking.

    Higher values mean stronger mountains/valleys and more obvious spectral tilt.
    These are selection/readout metrics, not hard runtime safety gates.
    """
    terrain = 0.0
    mountain = 0.0
    tilt = 0.0
    for db in responses:
        mid = db[(FREQS >= 120.0) & (FREQS <= 12000.0)]
        if mid.size:
            p95 = float(np.percentile(mid, 95))
            p05 = float(np.percentile(mid, 5))
            terrain = max(terrain, p95 - p05)
            mountain = max(mountain, float(np.max(mid) - np.median(mid)))
        low = band_mean(db, 80.0, 350.0)
        high = band_mean(db, 2500.0, 10000.0)
        if math.isfinite(low) and math.isfinite(high):
            tilt = max(tilt, abs(high - low))
    score = 0.55 * terrain + 0.30 * mountain + 0.15 * tilt
    return {
        "terrain_db": round(terrain, 1),
        "mountain_db": round(mountain, 1),
        "tilt_db": round(tilt, 1),
        "character_score": round(score, 1),
    }


def evaluate_gates(body, corner_feats, spec, boost):
    g = spec["gates"]
    maxr, unstable, nonfinite = grid_stability(body)
    r_home = shipped_response(body, 0.0, 0.0)
    r_tens = shipped_response(body, 0.0, 1.0)
    r_away = shipped_response(body, 1.0, 0.0)
    r_tight_away = shipped_response(body, 1.0, 1.0)
    terrain = terrain_metrics([r_home, r_away, r_tens, r_tight_away])
    peak = float(r_home.max()) + 20.0 * math.log10(boost)
    low = band_mean(r_home, 20.0, 120.0)
    cs = [centroid(shipped_response(body, float(m), 0.0)) for m in np.linspace(0, 1, 16)]
    net = abs(cs[-1] - cs[0])
    path = sum(abs(cs[i + 1] - cs[i]) for i in range(len(cs) - 1))
    chaos = (path / max(net, 1.0)) - 1.0
    q_shift = abs(centroid(r_tens) - centroid(r_home))
    resid = max(shape_rms(shipped_response(body, *_mq(lab)),
                          feats_to_curve(corner_feats[lab], spec["floor_db"], FREQS)) for lab in LABELS)

    checks = {
        "stable": maxr < 1.0 and unstable == 0,
        "finite": nonfinite == 0,
        "low_rolloff": (float(r_home.max()) - low) >= g["low_rolloff_min_db"],
        "peak": peak <= g["peak_max_db"],
        "morph_motion": net >= g["morph_motion_min_hz"],
        "morph_chaos": chaos <= g["morph_chaos_max"],
        "q_center_shift": q_shift <= g["q_center_shift_max_hz"],
        "packed_residual": resid <= g["packed_residual_max_db"],
        "terrain": terrain["character_score"] >= g.get("character_score_min", 0.0),
    }
    # HARD cull = brokenness only (guardrail, not boss). Off-target / Q-drift / chaos
    # are advisory readouts — the ear judges those, not a reject gate.
    hard = ("stable", "finite", "low_rolloff", "peak", "morph_motion")
    advisory = ("terrain", "morph_chaos", "q_center_shift", "packed_residual")
    return {
        "pass": all(checks[k] for k in hard),
        "checks": checks,
        "hard_failed": [k for k in hard if not checks[k]],
        "advisory_failed": [k for k in advisory if not checks[k]],
        "summary": {"moves_on_morph_hz": round(net, 0), "q_relocate_hz": round(q_shift, 0),
                    "max_pole_radius": round(maxr, 4), "packed_drift_db": round(resid, 1),
                    "peak_db": round(peak, 1), "boost": round(boost, 3), **terrain},
    }


def build_cart(name, corner_words, boost, template, seed):
    mq = {"M0_Q0": (0.0, 0.0), "M100_Q0": (1.0, 0.0), "M0_Q100": (0.0, 1.0), "M100_Q100": (1.0, 1.0)}
    kf = [{"label": lab, "morph": mq[lab][0], "q": mq[lab][1], "boost": boost,
           "packedWords": [list(int(x) & 0xFFFF for x in w) for w in corner_words[KEY[lab]]]}
          for lab in LABELS]
    return {"format": "compiled-v1", "name": name,
            "provenance": f"target-browser:{template} seed={seed}",
            "sampleRate": AUTH_SR, "authoring_sample_rate_hz": AUTH_SR,
            "stages": 6, "cornerOrder": LABELS, "boost": boost, "keyframes": kf}


# ── generate + publish into the Factory's PRESET list ─────────────────────────

def generate(spec, seed, count):
    run = RUN_ROOT / f"{spec['name']}_s{seed}"
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)
    morph_rule, q_rule = spec.get("morph_axis_rule"), spec.get("q_axis_rule")
    cands = []
    for i in range(count):
        rng = random.Random(seed * 1_000_003 + i)
        if "corner_features" in spec:
            corner_feats = sample_corner_features(spec, rng)
            base = corner_feats["M0_Q0"]
        else:
            base = sample_features(spec, rng)
            mp = sample_morph_params(morph_rule, len(base), rng)
            qp = sample_q_params(q_rule, rng)
            morphed = apply_morph(base, morph_rule, mp)
            corner_feats = {"M0_Q0": base, "M100_Q0": morphed,
                            "M0_Q100": apply_q(base, q_rule, qp),
                            "M100_Q100": apply_q(morphed, q_rule, qp)}
        corner_words = {}
        for lab in LABELS:
            curve = feats_to_curve(corner_feats[lab], spec["floor_db"], FIT_FREQS)
            rows = trench_ffi.fit_corner_from_magnitude(list(zip(FIT_FREQS.tolist(), curve.tolist())), AUTH_SR)
            corner_words[KEY[lab]] = [coeffs_to_words(*r) for r in rows]
        body = body_bytes(corner_words)
        boost = derive_boost(body, spec["level_guidance_db"])
        gate = evaluate_gates(body, corner_feats, spec, boost)
        name = f"cand_{i + 1:02d}"
        cdir = run / name
        cdir.mkdir()
        (cdir / f"{name}.body240").write_bytes(body)
        (cdir / f"{name}.cart.json").write_text(
            json.dumps(build_cart(name, corner_words, boost, spec["name"], seed), indent=2), encoding="utf-8")
        (cdir / "report.json").write_text(json.dumps({
            "candidate": name, "template": spec["name"], "seed": seed, "index": i,
            "label": spec["label"], "provenance": prov_string(spec, base), "gate": gate}, indent=2), encoding="utf-8")
        if gate["pass"]:
            render_candidate_audio(cdir, body)
        cands.append({
            "name": name,
            "body": body,
            "gate": gate,
            "prov": prov_string(spec, base),
            "dir": cdir,
        })
    return run, cands


def publish(spec, seed, survivors):
    """Drop survivor bodies into bodies/generated/ as 240-byte PRESET files."""
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    stem0 = f"gen_{spec['name']}_s{seed}_"
    for old in GEN_DIR.glob(f"{stem0}*.bin"):  # clear this archetype+seed's old run
        old.unlink()
    published = []
    for c in survivors:
        preset = f"{stem0}{c['name'].split('_')[-1]}"  # gen_<name>_s<seed>_NN
        (GEN_DIR / f"{preset}.bin").write_bytes(c["body"])
        published.append(preset)
    return published


def clip_players(candidate_name):
    cells = []
    for fname, code, label, _m, _q in CLIPS:
        cells.append(
            f'<label>{html.escape(code)}<span>{html.escape(label)}</span>'
            f'<audio controls preload="none" src="{candidate_name}/{fname}"></audio></label>'
        )
    for fname, label in [
        ("morph_sweep.wav", "Morph sweep"),
        ("q_sweep.wav", "Q sweep"),
        ("diagonal_sweep.wav", "Diagonal sweep"),
    ]:
        cells.append(
            f'<label>{html.escape(label)}<span>motion</span>'
            f'<audio controls preload="none" src="{candidate_name}/{fname}"></audio></label>'
        )
    return "\n".join(cells)


def write_audition_page(run, spec, seed, count, survivors, culled, published):
    rows = []
    rel_run = run.as_posix()
    for c in survivors:
        warnings = [GATE_WORDS[k] for k in c["gate"]["advisory_failed"]]
        warn = " · ".join(warnings) if warnings else "clean enough for ears"
        command = f"python -m tools.target_browser --keep {rel_run} {c['name']} --notes \"\""
        rows.append(f"""
<section class="candidate" data-name="{html.escape(c['name'])}">
  <header>
    <div>
      <h2>{html.escape(c['name'])}</h2>
      <p class="desc">{html.escape(c['prov'])}</p>
      <p class="warn">{html.escape(warn)}</p>
    </div>
    <div class="vote">
      <button data-vote="KEEP">KEEP</button>
      <button data-vote="MAYBE">MAYBE</button>
      <button data-vote="REJECT">REJECT</button>
    </div>
  </header>
  <div class="clips">
    {clip_players(c['name'])}
  </div>
  <textarea placeholder="producer notes"></textarea>
  <code>{html.escape(command)}</code>
</section>""")
    published_list = ", ".join(published) if published else "none"
    html_doc = f"""<!doctype html>
<meta charset="utf-8">
<title>Target Browser Audition</title>
<style>
body{{margin:0;background:#080a0a;color:#eee9dc;font:14px/1.4 system-ui,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 18px 56px}}
h1{{font-size:26px;margin:0 0 6px}}
h2{{font-size:19px;margin:0 0 4px;color:#9fe7c6}}
.meta,.desc,.warn{{color:#a4aaa2;margin:0 0 5px}}
.candidate{{border:1px solid #20342d;background:#0d1110;border-radius:8px;padding:14px;margin:16px 0}}
header{{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}}
.vote{{display:flex;gap:8px;flex-wrap:wrap}}
button{{background:#151a18;color:#eee9dc;border:1px solid #405247;border-radius:5px;padding:7px 10px;cursor:pointer}}
button.active[data-vote=KEEP]{{background:#17422c;border-color:#6ee7a8}}
button.active[data-vote=MAYBE]{{background:#433716;border-color:#e5c75f}}
button.active[data-vote=REJECT]{{background:#421d1d;border-color:#ff6d6d}}
.clips{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;margin-top:12px}}
label{{display:block;color:#f1d76a;font:12px ui-monospace,Consolas,monospace}}
label span{{color:#79827b;margin-left:8px}}
audio{{display:block;width:100%;margin-top:4px}}
textarea{{box-sizing:border-box;width:100%;min-height:54px;margin:12px 0 8px;background:#070908;color:#eee9dc;border:1px solid #28332d;border-radius:5px;padding:8px}}
code{{display:block;white-space:pre-wrap;color:#81d4ff;background:#070908;border:1px solid #18221d;border-radius:5px;padding:8px}}
@media(max-width:860px){{header{{display:block}}.vote{{margin-top:10px}}.clips{{grid-template-columns:1fr}}}}
</style>
<main>
  <h1>Target Browser Audition</h1>
  <p class="meta">{html.escape(spec['label'])} · template={html.escape(spec['name'])} · seed={seed} · survivors={len(survivors)}/{count} · broken culled={len(culled)}</p>
  <p class="meta">Listen first. Buttons and notes stay in this browser. Keep commands are shown per body.</p>
  <p class="meta">Factory presets written: {html.escape(published_list)}</p>
  {''.join(rows) if rows else '<p class="meta">No survivors. Try another seed.</p>'}
</main>
<script>
const runKey = "target-browser:{html.escape(spec['name'])}:s{seed}";
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
    (run / "audition.html").write_text(html_doc, encoding="utf-8")


def do_keep(run_dir: Path, names, notes):
    KEEP_DIR.mkdir(parents=True, exist_ok=True)
    if not run_dir.exists():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 1
    for name in names:
        name = name if name.startswith("cand_") else f"cand_{int(name):02d}"
        cdir = run_dir / name
        report = json.loads((cdir / "report.json").read_text(encoding="utf-8"))
        stem = f"{report['template']}_s{report['seed']}_{name}"
        shutil.copy(cdir / f"{name}.body240", KEEP_DIR / f"{stem}.body240")
        shutil.copy(cdir / f"{name}.cart.json", KEEP_DIR / f"{stem}.cart.json")
        (KEEP_DIR / f"{stem}.keep.json").write_text(json.dumps({
            "kept_utc": datetime.now(timezone.utc).isoformat(),
            "template": report["template"], "seed": report["seed"], "index": report["index"],
            "provenance": report.get("provenance", ""),
            "reproduce": f"python -m tools.target_browser --template {report['template']} --seed {report['seed']} --count {report['index'] + 1}",
            "gate": report["gate"], "notes": notes}, indent=2), encoding="utf-8")
        print(f"  kept {stem}")
    print(f"\nkept -> {KEEP_DIR}")
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template_name", nargs="?", help="archetype name (see --list)")
    ap.add_argument("--template", dest="template_flag", help="archetype name (see --list)")
    ap.add_argument("--list", action="store_true", help="list the musical archetypes")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=16, help="candidates to generate (8-32)")
    ap.add_argument("--keep", nargs="+", metavar=("RUN_DIR", "CAND"),
                    help="save keepers: --keep <run_dir> cand_03 07 ...")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    lib = json.loads(TEMPLATES.read_text(encoding="utf-8"))
    specs = {t["name"]: t for t in lib["templates"]}

    if args.list:
        print("\nArchetypes:\n")
        for t in lib["templates"]:
            print(f"  {t['name']:<28} \"{t['label']}\" — {t['listening_goal']}")
        return 0

    if args.keep:
        return do_keep(Path(args.keep[0]), args.keep[1:], args.notes)

    template = args.template_flag or args.template_name
    if not template or template not in specs:
        print("pick an archetype (or --list):", ", ".join(specs), file=sys.stderr)
        return 1
    if not trench_ffi.available() or not trench_ffi.engine_available():
        print("trench-core not built. Run: cargo build --release -p trench-core", file=sys.stderr)
        return 1

    spec = specs[template]
    count = max(4, min(48, args.count))
    print(f"GENERATE '{spec['label']}' ({spec['name']})  seed={args.seed}  count={count}")
    run, cands = generate(spec, args.seed, count)
    survivors = [c for c in cands if c["gate"]["pass"]]
    culled = [c for c in cands if not c["gate"]["pass"]]
    published = publish(spec, args.seed, survivors)
    write_audition_page(run, spec, args.seed, count, survivors, culled, published)

    for c in survivors:
        adv = " · ".join(GATE_WORDS[k] for k in c["gate"]["advisory_failed"])
        print(f"  {c['name']}  {c['prov']}" + (f"   [heads-up: {adv}]" if adv else ""))
    print(f"\n{len(survivors)}/{count} survived ({len(culled)} broken culled). "
          f"Dropped into the Factory's PRESET list as:")
    print(f"  bodies/generated/gen_{spec['name']}_s{args.seed}_NN.bin")
    print(f"\naudition -> {run / 'audition.html'}")
    print("\nNEXT (end to end):")
    print("  1. Open / RESTART the Filter Factory (it reads the PRESET list at launch).")
    print(f"  2. PRESET dropdown -> pick a 'gen_{spec['name']}_..' body (loads whole, SAW armed).")
    print("  3. PLAY, drag the puck (Morph/Q), watch the green scope. Audition by ear.")
    print(f"  4. Keep winners:  python -m tools.target_browser --keep {run.as_posix()} <NN> ..")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
