#!/usr/bin/env python3
"""corner-bench — the minimal visual authoring surface over the registered-lane CLI.

  python -m tools.corner_bench          # opens http://localhost:8757

A 2x2 corner grid. Drop onto each corner either:
  - a .tf.json measurement  (tf_ingest shape) -> fitted via trench-core fit-candidates
  - a .candidates.json set  -> that corner's candidates are used
BUILD then runs the SAME backend as the CLI: assign each corner's candidates to
lanes in listed order (serial cascade — listing order carries no meaning),
validate, emit, pack through tools/filter_cli (trench-core, the one compiler),
and plot. No new math, no new compiler, no silent repair: a continuity/law
refusal is shown verbatim, exactly as the CLI prints it.

Artifacts land in dev/tmp/corner_bench/<name>.*
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tools.register_lanes import CORNERS, DEFAULT_LIMITS, assign_candidate, dumps, \
    emit_geometry, new_document, validate

ROOT = Path(__file__).resolve().parent.parent
FITTER = ROOT / "target" / "release" / "fit-candidates.exe"
OUT_DIR = ROOT / "dev" / "tmp" / "corner_bench"
PORT = 8757

STATE = {c: None for c in CORNERS}  # corner -> {"label", "candidates":[...]}

# WAVs only from the measured-object library (controlled IR intake — the same
# boundary source_catalog draws); TF/candidate JSONs from dev/tmp. dev/tmp WAVs
# are generated renders/captures, never measured sources.
SOURCE_ROOTS = [(ROOT / "wav-source-library" / "measured_objects", ("*.wav",)),
                (ROOT / "dev" / "tmp", ("*.tf.json", "*.candidates.json"))]
KIND = {".wav": "wav", ".candidates.json": "candidates", ".tf.json": "tf"}


def list_sources():
    """Every loadable measured source, no folder browsing."""
    out = []
    for root, pats in SOURCE_ROOTS:
        if not root.exists():
            continue
        for pat in pats:
            kind = KIND[pat.lstrip("*")]
            for p in sorted(root.rglob(pat)):
                rel = p.relative_to(ROOT).as_posix()
                out.append({"path": rel, "name": p.name, "kind": kind,
                            "dir": p.parent.name})
    return out


def load_source(corner: str, rel_path: str, detilt: bool, mode: str = "poles_first"):
    """Load a listed source into a corner slot server-side (no drag needed)."""
    p = (ROOT / rel_path).resolve()
    if ROOT not in p.parents:
        raise RuntimeError("source must live inside the workstation")
    if p.suffix.lower() == ".wav":
        from tools.tf_ingest import ir_to_tf
        tf = ir_to_tf(p, detilt=detilt)
        content = json.dumps(tf)
        cands, fit = fit_tf(p.name, content, mode)
        return {"label": f"{p.name} ({'detilt, ' if detilt else ''}{mode} fit, "
                         f"rms {fit['residual_rms_db']:.1f} dB)",
                "candidates": cands,
                "tf": {"freqs_hz": tf["freqs_hz"], "mag_db": tf["mag_db"]}}
    return corner_payload(corner, p.name, p.read_text(encoding="utf-8"), mode)


import math

# the section-type grammar (filters/grammar/typed_vowl.py) with the SAME
# thresholds register_lanes validates: T1 co-located <=0.5 oct, T2/T3 rail
# separation >=0.5 oct.
LAW_TAG = {"local_peak_notch": "T1 peak/notch", "high_zero_cliff": "T2 cliff",
           "low_zero_sub_cut": "T3 sub-cut", "free": "free"}


def law_of(cand):
    """Classify one candidate against the typed grammar. Inspection only —
    the real enforcement is register_lanes.validate on the lane plan."""
    if cand["state"] == "identity":
        return None
    if "real_roots" in cand["pole"] or "real_roots" in cand["zero"]:
        return "free"
    ph, zh = cand["pole"]["hz"], cand["zero"]["hz"]
    if ph <= 0 or zh <= 0:
        return "free"
    sep = math.log2(zh / ph)
    if abs(sep) <= 0.5:
        return "local_peak_notch"
    if sep >= 0.5:
        return "high_zero_cliff"
    return "low_zero_sub_cut"


def corner_plot_b64(payload):
    """Per-corner verdict plot: the measured curve vs the fitted cascade that
    will actually enter geometry (conjugate stages only; real-pairs are named
    as skipped). Response math reused from tools.filter_cli (the sanctioned
    plotting path), nothing new."""
    import base64
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from tools.filter_cli import corner_db
    freqs = [20 * (10 ** (i / 199 * 3)) for i in range(200)]
    usable, skipped = [], 0
    for c in payload["candidates"]:
        if c["topology"]["pole"] == "real_pair" or c["topology"]["zero"] == "real_pair":
            skipped += 1
            continue
        usable.append({"pole_hz": c["pole"]["hz"], "pole_r": c["pole"]["r"],
                       "zero_hz": c["zero"]["hz"], "zero_r": c["zero"]["r"],
                       "scale": c["scale"]})
    fig, ax = plt.subplots(figsize=(5.2, 2.6), facecolor="#141712")
    ax.set_facecolor("#10130f")
    tf = payload.get("tf")
    if tf:
        ax.semilogx(tf["freqs_hz"], tf["mag_db"], lw=1.0, color="#7f8f85", label="measured")
    if usable:
        ax.semilogx(freqs, corner_db(usable, freqs), lw=1.8, color="#e6a13b",
                    label=f"fit ({len(usable)} lanes)" + (f" · {skipped} real-pair skipped" if skipped else ""))
    ax.grid(True, which="both", alpha=0.15, color="#3a4438")
    ax.tick_params(colors="#8a968f", labelsize=7)
    for s in ax.spines.values():
        s.set_color("#3a4438")
    ax.legend(fontsize=7, facecolor="#181b20", edgecolor="#2a2e35", labelcolor="#cfe9df")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor="#141712")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _fig_b64(fig):
    import base64
    import io
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor="#141712")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


LANE_COL = ["#8b8ff0", "#e6a13b", "#ee6a3c", "#56ed70", "#2fc8cc", "#e0d24a"]


def diag_lanes_b64(doc, geo):
    """2x2 corner sheet: each lane's own curve + the white cascade — the
    anatomy made visible per pose. Response math = filter_cli's (sanctioned)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from tools.filter_cli import corner_db, stage_response
    freqs = [20 * (10 ** (i / 199 * 3)) for i in range(200)]
    labels = [f"L{p['slot']} {LAW_TAG[p['law']]}" for p in doc["stage_plan"]]
    fig, axs = plt.subplots(2, 2, figsize=(11, 6.4), facecolor="#141712")
    for ci, corner in enumerate(CORNERS):
        ax = axs[ci // 2][ci % 2]
        ax.set_facecolor("#10130f")
        stages = geo["corners"][ci]
        for si, s in enumerate(stages):
            import math as m
            db = [20 * m.log10(max(v, 1e-9)) for v in stage_response(s, freqs)]
            ax.semilogx(freqs, db, lw=1.0, color=LANE_COL[si], alpha=0.85, label=labels[si])
        ax.semilogx(freqs, corner_db(stages, freqs), lw=2.2, color="#ffffff", label="cascade")
        ax.set_title(corner, color="#cfe9df", fontsize=10)
        ax.grid(True, which="both", alpha=0.15, color="#3a4438")
        ax.tick_params(colors="#8a968f", labelsize=7)
        for sp in ax.spines.values():
            sp.set_color("#3a4438")
        if ci == 0:
            ax.legend(fontsize=6.5, ncol=2, facecolor="#181b20", edgecolor="#2a2e35",
                      labelcolor="#cfe9df", loc="lower left")
    fig.suptitle("lanes per pose (colored) + cascade (white)", color="#cfe9df", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return _fig_b64(fig)


def diag_morph_b64(body_path):
    """Morph-sweep sheet from the REAL packed runtime (trench_packed_probe via
    the trench-core cdylib): cascade |H| at 9 morph steps, Q0 and Q100 panels,
    plus the sampled max pole radius. This is the animation the user ships."""
    import ctypes
    import math as m
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dll = ctypes.CDLL(str(ROOT / "target" / "release" / "trench_core.dll"))
    dll.trench_packed_probe.restype = ctypes.c_int32
    body = Path(body_path).read_bytes()
    buf = (ctypes.c_uint8 * 240).from_buffer_copy(body)
    freqs = [20 * (10 ** (i / 199 * 3)) for i in range(200)]
    sr = 39062.5

    def rows_at(morph, q):
        out = (ctypes.c_double * 30)()
        mr = ctypes.c_double()
        um = ctypes.c_uint32()
        nm = ctypes.c_uint32()
        rc = dll.trench_packed_probe(buf, 240, ctypes.c_double(morph), ctypes.c_double(q),
                                     out, ctypes.byref(mr), ctypes.byref(um), ctypes.byref(nm))
        if rc != 0:
            raise RuntimeError(f"trench_packed_probe rc {rc}")
        return [list(out[i * 5:(i + 1) * 5]) for i in range(6)], mr.value

    def cascade_db(rows):
        dbs = []
        for f in freqs:
            w = 2 * m.pi * f / sr
            z = complex(m.cos(-w), m.sin(-w))
            h = complex(1.0, 0.0)
            for b0, b1, b2, a1, a2 in rows:
                h *= (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
            dbs.append(20 * m.log10(max(abs(h), 1e-9)))
        return dbs

    fig, axs = plt.subplots(1, 2, figsize=(11, 3.6), facecolor="#141712")
    cmap = plt.get_cmap("plasma")
    max_r = 0.0
    for pi, q in enumerate((0.0, 1.0)):
        ax = axs[pi]
        ax.set_facecolor("#10130f")
        for k in range(9):
            morph = k / 8.0
            rows, mr = rows_at(morph, q)
            max_r = max(max_r, mr)
            ax.semilogx(freqs, cascade_db(rows), lw=1.2, color=cmap(0.15 + 0.7 * morph),
                        label=f"M{int(morph*100)}" if k in (0, 4, 8) else None)
        ax.set_title(f"morph sweep · Q{int(q*100)}", color="#cfe9df", fontsize=10)
        ax.grid(True, which="both", alpha=0.15, color="#3a4438")
        ax.tick_params(colors="#8a968f", labelsize=7)
        for sp in ax.spines.values():
            sp.set_color("#3a4438")
        ax.legend(fontsize=7, facecolor="#181b20", edgecolor="#2a2e35", labelcolor="#cfe9df")
    fig.suptitle(f"packed-runtime morph sweep (the real interpolation) · sampled max pole radius {max_r:.4f}",
                 color="#cfe9df", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return _fig_b64(fig)


# ── audition: real TRENCH audio through the engine FFI ──────────────────────

STEM_DIRS = [ROOT / "wav-source-library" / "audition_stems",
             ROOT / "wav-source-library" / "08_clean_instruments"]


def list_stems():
    stems = [{"id": "drums", "name": "drum loop (generated, dry)"}]
    for d in STEM_DIRS:
        if d.exists():
            for p in sorted(d.glob("*.wav")):
                stems.append({"id": p.relative_to(ROOT).as_posix(), "name": p.name})
    return stems


def gen_drum_loop(sr=44100, bars=2, bpm=100):
    """Deterministic dry drum loop: kick (sine drop) / snare (noise burst) /
    hats (short noise). A stem generator, not filter math."""
    import numpy as np
    rng = np.random.default_rng(4613)
    beat = 60.0 / bpm
    n = int(sr * beat * 4 * bars)
    x = np.zeros(n, dtype=np.float64)

    def kick(t0):
        i0 = int(t0 * sr)
        t = np.arange(int(0.25 * sr)) / sr
        f = 120.0 * np.exp(-t * 18) + 45.0
        seg = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 14)
        x[i0:i0 + len(seg)] += 0.9 * seg[:max(0, min(len(seg), n - i0))]

    def snare(t0):
        i0 = int(t0 * sr)
        t = np.arange(int(0.18 * sr)) / sr
        seg = (rng.standard_normal(len(t)) * 0.5 + np.sin(2 * np.pi * 190 * t) * 0.4) * np.exp(-t * 22)
        x[i0:i0 + len(seg)] += 0.6 * seg[:max(0, min(len(seg), n - i0))]

    def hat(t0):
        i0 = int(t0 * sr)
        t = np.arange(int(0.05 * sr)) / sr
        seg = rng.standard_normal(len(t)) * np.exp(-t * 70)
        x[i0:i0 + len(seg)] += 0.25 * seg[:max(0, min(len(seg), n - i0))]

    for bar in range(bars):
        base = bar * 4 * beat
        kick(base)
        kick(base + 2.5 * beat)
        snare(base + 1 * beat)
        snare(base + 3 * beat)
        for k in range(8):
            hat(base + k * beat / 2)
    peak = np.max(np.abs(x)) or 1.0
    return (x / peak * 0.7).astype(np.float32), sr


def load_stem(stem_id):
    if stem_id == "drums":
        return gen_drum_loop()
    import numpy as np
    from scipy.io import wavfile
    p = (ROOT / stem_id).resolve()
    if ROOT not in p.parents:
        raise RuntimeError("stem must live inside the workstation")
    sr, x = wavfile.read(p)
    x = x.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    peak = np.max(np.abs(x)) or 1.0
    x = x / peak * 0.7  # one declared headroom scaling of the DRY input, not a wet normalization
    return x[: sr * 12].astype(np.float32), sr


def render_audition(name, q, solo, stem_id):
    """The stem through the REAL engine (trench_engine_* FFI): morph triangle
    sweep 0->1->0 across the stem at fixed Q. solo = BODY SOLO (cascade-only:
    input None, spatial Off, AGC/saturation off, amount 1)."""
    import ctypes
    import numpy as np
    from scipy.io import wavfile
    body_path = OUT_DIR / f"{name}.body240"
    if not body_path.exists():
        raise RuntimeError(f"no built body '{name}' — hit BUILD first")
    stem, sr = load_stem(stem_id)
    dll = ctypes.CDLL(str(ROOT / "target" / "release" / "trench_core.dll"))
    dll.trench_engine_create.restype = ctypes.c_void_p
    dll.trench_engine_prepare.argtypes = [ctypes.c_void_p, ctypes.c_double]
    dll.trench_engine_destroy.argtypes = [ctypes.c_void_p]
    dll.trench_engine_load_body_bytes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    dll.trench_engine_load_body_bytes.restype = ctypes.c_int32
    for fn in ("trench_engine_set_input_mode", "trench_engine_set_spatial_mode",
               "trench_engine_set_agc_enabled", "trench_engine_set_saturation_enabled"):
        getattr(dll, fn).argtypes = [ctypes.c_void_p, ctypes.c_int32]
    dll.trench_engine_set_parameters.argtypes = [ctypes.c_void_p] + [ctypes.c_float] * 5
    eng = dll.trench_engine_create()
    try:
        dll.trench_engine_prepare(eng, ctypes.c_double(float(sr)))
        body = body_path.read_bytes()
        buf = (ctypes.c_uint8 * 240).from_buffer_copy(body)
        rc = dll.trench_engine_load_body_bytes(eng, buf, 240)
        if rc != 0:
            raise RuntimeError(f"load_body_bytes rc {rc}")
        if solo:
            dll.trench_engine_set_input_mode(eng, 0)
            dll.trench_engine_set_spatial_mode(eng, 2)
            dll.trench_engine_set_agc_enabled(eng, 0)
            dll.trench_engine_set_saturation_enabled(eng, 0)
            dll.trench_engine_set_parameters(eng, 0.0, 0.0, 0.0, 0.0, 1.0)
        dll.trench_engine_process_block.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),
            ctypes.c_int32, ctypes.c_double, ctypes.c_double]
        left = np.copy(stem)
        right = np.copy(stem)
        n = len(stem)
        block = 512
        for i0 in range(0, n, block):
            nb = min(block, n - i0)
            pos = i0 / max(1, n - 1)
            morph = 2 * pos if pos <= 0.5 else 2 * (1 - pos)  # triangle 0->1->0
            dll.trench_engine_process_block(
                eng,
                left[i0:].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                right[i0:].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                nb, ctypes.c_double(morph), ctypes.c_double(q))
    finally:
        dll.trench_engine_destroy(ctypes.c_void_p(eng))
    wet = np.stack([left, right], axis=1)
    peak = float(np.max(np.abs(wet)))
    clip = int(np.sum(np.abs(wet) >= 1.0))
    tag = f"Q{int(q*100)}" + ("_solo" if solo else "")
    out = OUT_DIR / f"{name}_audition_{tag}.wav"
    wavfile.write(out, sr, wet.astype(np.float32))  # raw engine output, no normalization
    dry = OUT_DIR / f"{name}_dry.wav"
    wavfile.write(dry, sr, stem)
    return {"wet": out.relative_to(ROOT).as_posix(), "dry": dry.relative_to(ROOT).as_posix(),
            "peak": peak, "clip_samples": clip}


FIT_FLAGS = {"free": [], "anatomy": ["--anatomy"], "formant": ["--formant"],
             "poles_first": ["--poles-first"]}


def fit_tf(name: str, content: str, mode: str = "poles_first"):
    """One TF JSON -> that corner's candidate list, via the owned fitter."""
    if not FITTER.exists():
        raise RuntimeError(f"fitter missing: build with cargo build --release -p trench-core --bin fit-candidates")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / name
        src.write_text(content, encoding="utf-8")
        out = Path(td) / "fit.json"
        cmd = [str(FITTER), str(src), str(out)] + FIT_FLAGS.get(mode, [])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stdout + r.stderr)
        fit = json.loads(out.read_text(encoding="utf-8"))
    cands = []
    for i, s in enumerate(fit["stages"]):
        cands.append({"id": f"drop-{i}", "topology": s["topology"], "state": s["state"],
                      "pole": s["pole"], "zero": s["zero"], "scale": s["scale"],
                      "packed_words": s["packed_words"],
                      "provenance": {"source": name, "source_sha256": "0" * 64,
                                     "method": "fit-candidates via corner_bench drop"}})
    return cands, fit["fit"]


def corner_payload(corner: str, name: str, content: str, mode: str = "poles_first"):
    """Classify a dropped file for one corner slot."""
    d = json.loads(content)
    if isinstance(d, dict) and "freqs_hz" in d and "mag_db" in d:
        cands, fit = fit_tf(name, content, mode)
        return {"label": f"{name} ({mode} fit, rms {fit['residual_rms_db']:.1f} dB)",
                "candidates": cands, "tf": {"freqs_hz": d["freqs_hz"], "mag_db": d["mag_db"]}}
    if isinstance(d, dict) and d.get("corner_order") == CORNERS:
        cands = d["corners"][corner]["candidates"]
        return {"label": f"{name} [{corner}] ({len(cands)} candidates)",
                "candidates": cands}
    raise RuntimeError(f"{name}: not a tf_ingest TF JSON or a candidate set")


def build(name: str, limits_off: bool):
    doc = new_document(name)
    doc["secondary_axis"]["note"] = "authored by corner drop in corner_bench (each corner = its dropped measurement)"
    if limits_off:
        for p in doc["stage_plan"]:
            p["limits"] = {k: None for k in DEFAULT_LIMITS}
    candset = {"name": f"corner_bench:{name}", "corners": {}}
    for corner in CORNERS:
        slot = STATE[corner]
        candset["corners"][corner] = {
            "source": {"catalog_record": None},
            "candidates": slot["candidates"] if slot else [],
        }
    log = []
    for corner in CORNERS:
        slot = STATE[corner]
        if slot is None:
            log.append(f"{corner}: empty -> identity lanes")
            continue
        # canonical geometry is conjugate-only: real-pair candidates are SKIPPED
        # and reported, never projected into hz/r (the stage-law refusal).
        usable = [c for c in slot["candidates"]
                  if c["topology"]["pole"] != "real_pair" and c["topology"]["zero"] != "real_pair"]
        skipped = len(slot["candidates"]) - len(usable)
        for i, cand in enumerate(usable[:6]):
            assign_candidate(doc, candset, cand["id"], f"lane{i}", corner)
        laws = ", ".join(LAW_TAG[law_of(c)] for c in usable[:6])
        log.append(f"{corner}: {slot['label']} -> {min(len(usable), 6)} lanes [{laws}]"
                   + (f" · {skipped} real-pair candidate(s) SKIPPED (conjugate-only geometry)" if skipped else ""))
    # run the corners through the grammar: where a lane's four assignments agree
    # on a typed law, DECLARE it in the stage plan — validate() then enforces it.
    for p in doc["stage_plan"]:
        lane_laws = {law_of(a) for a in
                     (doc["lanes"][p["lane_id"]]["assignments"][c] for c in CORNERS)}
        lane_laws.discard(None)  # identity corners don't vote
        if len(lane_laws) == 1 and (law := lane_laws.pop()) != "free":
            p["law"] = law
            p["role"] = LAW_TAG[law]
            p["pole_zero_relation"] = LAW_TAG[law] + " (classified from fitted corners)"
            log.append(f"lane {p['slot']}: law {LAW_TAG[law]} declared + enforced")
        elif len(lane_laws) > 1:
            log.append(f"lane {p['slot']}: MIXED laws across corners "
                       f"({', '.join(sorted(LAW_TAG[l] for l in lane_laws))}) -> free, not enforced")
    errs = validate(doc)
    if errs:
        return {"ok": False, "log": log, "errors": errs}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rl = OUT_DIR / f"{name}.registered_lanes.json"
    rl.write_text(dumps(doc), encoding="utf-8")
    geo = OUT_DIR / f"{name}.geometry.json"
    geo.write_text(dumps(emit_geometry(doc)), encoding="utf-8")
    body = OUT_DIR / f"{name}.body240"
    r = subprocess.run([sys.executable, "-m", "tools.filter_cli", "pack", str(geo), str(body)],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        return {"ok": False, "log": log, "errors": [r.stdout + r.stderr]}
    log.append((r.stdout or r.stderr).strip())
    png = OUT_DIR / f"{name}.png"
    p = subprocess.run([sys.executable, "-m", "tools.filter_cli", "plot", str(geo),
                        "--out", str(png)], capture_output=True, text=True, cwd=ROOT)
    import base64
    plot_b64 = base64.b64encode(png.read_bytes()).decode() if p.returncode == 0 and png.exists() else None
    diags = {}
    geo_data = json.loads(geo.read_text(encoding="utf-8"))
    for key, fn in (("lanes", lambda: diag_lanes_b64(doc, geo_data)),
                    ("morph", lambda: diag_morph_b64(body))):
        try:
            diags[key] = fn()
        except Exception as e:
            log.append(f"diagnostic '{key}' unavailable: {e}")
    return {"ok": True, "log": log, "errors": [],
            "body": str(body), "registered": str(rl), "plot": plot_b64,
            "diag_lanes": diags.get("lanes"), "diag_morph": diags.get("morph")}


def set_corner(corner, payload):
    # ids must be unique ACROSS corners: assign_candidate resolves by id over
    # the whole set, and the fitter emits per-corner drop-N ids that collide.
    for i, c in enumerate(payload["candidates"]):
        c["id"] = f"{corner}-drop-{i}"
    STATE[corner] = payload
    tags = {}
    for c in payload["candidates"]:
        t = LAW_TAG[law_of(c) or "free"]
        if c["topology"]["pole"] == "real_pair" or c["topology"]["zero"] == "real_pair":
            t = "real-pair (skip)"
        tags[t] = tags.get(t, 0) + 1
    summary = ", ".join(f"{k} x{v}" for k, v in sorted(tags.items()))
    return {"ok": True, "label": payload["label"], "summary": summary,
            "plot": corner_plot_b64(payload)}


PAGE = """<!doctype html><meta charset="utf-8"><title>corner stitch</title>
<style>
 body{background:#141712;color:#cfe9df;font:14px/1.5 Segoe UI,sans-serif;margin:24px;max-width:1100px}
 h1{font-size:18px;color:#e6d9a8} .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:14px 0}
 .cell{border:2px dashed #3a4438;border-radius:10px;min-height:120px;padding:12px;background:#191d17}
 .cell.over{border-color:#e6a13b;background:#20261c} .cell h2{margin:0 0 6px;font-size:13px;color:#8fb59f}
 .cell .got{color:#e6d9a8;font-size:12px;word-break:break-all}
 .cands{font-size:11px;color:#7f8f85;margin-top:6px}
 button{background:#2c4436;color:#dff2e6;border:1px solid #4a6a55;border-radius:6px;
        padding:8px 22px;font-size:15px;cursor:pointer} button:hover{background:#3a5a46}
 input[type=text]{background:#10130f;color:#cfe9df;border:1px solid #3a4438;border-radius:5px;padding:6px}
 #log{white-space:pre-wrap;background:#0e110d;border-radius:8px;padding:10px;font:12px Consolas,monospace;
      color:#9fc7b0;margin-top:12px} .err{color:#ee6a5c} img{max-width:100%;border-radius:8px;margin-top:12px}
 .hint{color:#6d7d72;font-size:12px} label{font-size:12px;color:#8fb59f}
</style>
<h1>CORNER STITCH — choose a table, choose a corner, inspect the plot</h1>
<div class="hint">Pick one source table for each of the four runtime corners. Each slot shows its own measured-versus-fit plot; BUILD only stitches the four selected corner candidate sets.</div>
<div style="display:flex;gap:14px;align-items:flex-start">
<div style="flex:0 0 340px">
 <input type="text" id="filter" placeholder="filter sources..." style="width:95%;margin-bottom:6px">
 <label><input type="checkbox" id="detilt"> legacy pre-detilt WAVs (A/B only)</label><br>
 <label>fit mode <select id="fitmode">
   <option value="poles_first" selected>acoustic profiler: macro peel + residual poles/zeros</option>
   <option value="formant">T4 formant: peak-weighted search, untethered zeros</option>
   <option value="anatomy">typed anatomy: T3 sub-cut + 4x T1 ridge + T2 cap</option>
   <option value="free">free ARMA (unconstrained)</option>
 </select></label>
 <div id="sources" style="max-height:420px;overflow-y:auto;border:1px solid #3a4438;border-radius:8px;
      background:#10130f;font-size:12px"></div>
</div>
<div style="flex:1">
<div class="grid">
 <div class="cell" id="M0_Q0"><h2>M0 · Q0 — pose at 0</h2><div class="btns"></div><div class="got">empty</div><div class="cands"></div><img class="cplot" style="display:none"></div>
 <div class="cell" id="M100_Q0"><h2>M100 · Q0 — pose at 100</h2><div class="btns"></div><div class="got">empty</div><div class="cands"></div><img class="cplot" style="display:none"></div>
 <div class="cell" id="M0_Q100"><h2>M0 · Q100</h2><div class="btns"></div><div class="got">empty</div><div class="cands"></div><img class="cplot" style="display:none"></div>
 <div class="cell" id="M100_Q100"><h2>M100 · Q100</h2><div class="btns"></div><div class="got">empty</div><div class="cands"></div><img class="cplot" style="display:none"></div>
</div>
</div>
</div>
name <input type="text" id="name" value="bench_body">
<label><input type="checkbox" id="limitsoff"> continuity limits off</label>
<button onclick="build()">BUILD</button>
<div class="hint" style="display:inline-block;margin-left:12px">four slots stay independent until BUILD</div>
<div id="log">four corner slots are empty</div>
<img id="plot" style="display:none">
<img id="diagmorph" style="display:none">
<img id="diaglanes" style="display:none">
<script>
let SOURCES = [], SELECTED = null;
const FILLED = {};
function markCorner(c, ok, label, summary, plot) {
  const el = document.getElementById(c);
  el.querySelector(".got").textContent = ok ? label : "REFUSED: " + label;
  el.querySelector(".cands").textContent = ok ? (summary || "") : "";
  el.style.borderColor = ok ? "#4a6a55" : "#a04438";
  el.style.borderStyle = "solid";
  const img = el.querySelector(".cplot");
  if (ok && plot) { img.src = "data:image/png;base64," + plot; img.style.display = "block"; }
  else if (!ok) img.style.display = "none";
  if (ok) FILLED[c] = true;
  renderButtons(c);
}
async function setCorner(c) {
  if (!SELECTED) { markCorner(c, false, "pick a source on the left first", "", null); FILLED[c] = false; return; }
  const el = document.getElementById(c);
  el.querySelector(".got").textContent = "loading " + SELECTED + " ...";
  const r = await fetch("/corner_path", {method:"POST", body: JSON.stringify({
    corner: c, path: SELECTED, detilt: document.getElementById("detilt").checked,
    mode: document.getElementById("fitmode").value})});
  const d = await r.json();
  markCorner(c, d.ok, d.ok ? d.label : d.error, d.summary, d.plot);
}
async function clearCorner(c) {
  await fetch("/clear", {method:"POST", body: JSON.stringify({corner: c})});
  const el = document.getElementById(c);
  el.querySelector(".got").textContent = "empty";
  el.querySelector(".cands").textContent = "";
  el.querySelector(".cplot").style.display = "none";
  el.style.borderColor = "#3a4438"; el.style.borderStyle = "dashed";
  FILLED[c] = false;
  renderButtons(c);
}
function renderButtons(c) {
  const b = document.getElementById(c).querySelector(".btns");
  b.innerHTML = "";
  const set = document.createElement("button");
  set.textContent = FILLED[c] ? "replace with selected" : "add selected";
  set.style.cssText = "font-size:11px;padding:3px 10px;margin-right:6px";
  set.onclick = (e) => { e.stopPropagation(); setCorner(c); };
  b.appendChild(set);
  if (FILLED[c]) {
    const clr = document.createElement("button");
    clr.textContent = "clear";
    clr.style.cssText = "font-size:11px;padding:3px 10px;background:#443028;border-color:#6a5344";
    clr.onclick = (e) => { e.stopPropagation(); clearCorner(c); };
    b.appendChild(clr);
  }
}
function renderSources() {
  const q = document.getElementById("filter").value.toLowerCase();
  const box = document.getElementById("sources");
  box.innerHTML = "";
  for (const s of SOURCES) {
    if (q && !(s.path.toLowerCase().includes(q))) continue;
    const d = document.createElement("div");
    d.textContent = (s.kind === "wav" ? "\\u266b " : s.kind === "candidates" ? "\\u25a6 " : "\\u223f ")
                    + s.dir + " / " + s.name;
    d.style.cssText = "padding:4px 8px;cursor:pointer;border-bottom:1px solid #1c211a";
    if (SELECTED === s.path) d.style.background = "#2c4436";
    d.onclick = () => { SELECTED = s.path; renderSources(); };
    box.appendChild(d);
  }
}
document.getElementById("filter").oninput = renderSources;
fetch("/sources").then(r => r.json()).then(d => { SOURCES = d; renderSources(); });
for (const c of ["M0_Q0","M100_Q0","M0_Q100","M100_Q100"]) {
  renderButtons(c);
  const el = document.getElementById(c);
  el.addEventListener("dragover", e => { e.preventDefault(); el.classList.add("over"); });
  el.addEventListener("dragleave", () => el.classList.remove("over"));
  el.addEventListener("drop", async e => {
    e.preventDefault(); el.classList.remove("over");
    const f = e.dataTransfer.files[0]; if (!f) return;
    const content = await f.text();
    const r = await fetch("/corner", {method:"POST",
      body: JSON.stringify({corner:c, name:f.name, content,
        mode: document.getElementById("fitmode").value})});
    const d = await r.json();
    markCorner(c, d.ok, d.ok ? d.label : d.error, d.summary, d.plot);
  });
}
async function build() {
  const log = document.getElementById("log");
  log.textContent = "building...";
  const r = await fetch("/build", {method:"POST", body: JSON.stringify({
    name: document.getElementById("name").value || "bench_body",
    limits_off: document.getElementById("limitsoff").checked})});
  const d = await r.json();
  let t = d.log.join("\\n");
  if (d.errors.length) t += "\\n\\nREFUSED:\\n" + d.errors.join("\\n");
  else t += "\\n\\nbody: " + d.body + "\\nregistered: " + d.registered;
  log.innerHTML = d.errors.length ? '<span class="err">'+t+'</span>' : t;
  for (const [id, key] of [["plot","plot"],["diagmorph","diag_morph"],["diaglanes","diag_lanes"]]) {
    const img = document.getElementById(id);
    if (d[key]) { img.src = "data:image/png;base64," + d[key]; img.style.display = "block"; }
    else img.style.display = "none";
  }
}
</script>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/sources":
            self.send_json(list_sources())
            return
        if self.path == "/stems":
            self.send_json(list_stems())
            return
        if self.path.startswith("/file?p="):
            from urllib.parse import unquote
            rel = unquote(self.path[len("/file?p="):])
            fp = (ROOT / rel).resolve()
            if ROOT not in fp.parents or not fp.exists() or fp.suffix.lower() != ".wav":
                self.send_response(404)
                self.end_headers()
                return
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            if self.path == "/corner_path":
                corner = req["corner"]
                payload = load_source(corner, req["path"], bool(req.get("detilt", False)),
                                      req.get("mode", "poles_first"))
                self.send_json(set_corner(corner, payload))
            elif self.path == "/corner":
                corner = req["corner"]
                payload = corner_payload(corner, req["name"], req["content"],
                                         req.get("mode", "poles_first"))
                self.send_json(set_corner(corner, payload))
            elif self.path == "/stems":
                self.send_json(list_stems())
            elif self.path == "/audition":
                self.send_json({"ok": True, **render_audition(
                    req["name"], float(req["q"]), bool(req.get("solo", True)),
                    req.get("stem", "drums"))})
            elif self.path == "/clear":
                STATE[req["corner"]] = None
                self.send_json({"ok": True})
            elif self.path == "/build":
                self.send_json(build(req["name"], req["limits_off"]))
            else:
                self.send_json({"ok": False, "error": "unknown endpoint"}, 404)
        except Exception as e:  # surface every refusal verbatim in the page
            self.send_json({"ok": False, "error": str(e), "log": [], "errors": [str(e)]})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"corner bench at {url}  (Ctrl+C to stop)")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
