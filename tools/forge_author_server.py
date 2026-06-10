"""Law Author Studio backend: serves forge-web/ AND bakes a complete, trench_core-
audited session folder. Browser can send either 6 lane blocks for the Studio
path or a browser-packed 240-byte hex body plus explicit hand-authored corners.
Python audits through trench_core and writes the end-to-end artifacts.
Run:  python tools/forge_author_server.py
then open http://localhost:8130/studio.html

Emits dev/tmp/forge_visual_author/<session>/:
  target.json  fitted_lanes.json  law_source.json  body.body240
  cartridge.json  audit.json  response.png  workbench.html
"""
import sys, json, math, io, datetime
from types import SimpleNamespace
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
ROOT = Path(r"C:\Users\hooki\df2"); sys.path.insert(0, str(ROOT))
WEB = ROOT / "forge-web"
OUTROOT = ROOT / "dev/tmp/forge_visual_author"
V1_AUDITION = ROOT / "dev/tmp/forge_v1_lineup/audition"
BANK_DIR = ROOT / "desk/bank/v1"
BANK_MD = BANK_DIR / "BANK.md"
KILLS_MD = ROOT / "desk/KILLS.md"
SEEDS_JSON = WEB / "data/designer_seeds.json"
AUDITION_DIR = Path.home() / "Documents" / "TRENCH"
PLUGIN_BODIES_DIR = AUDITION_DIR / "bodies"
AUDITION_JSON = AUDITION_DIR / "authoring_slot.json"
AUDITION_BODY = AUDITION_DIR / "authoring_slot.body240"
SR = 39062.5; TAU = 2 * math.pi
clamp = lambda v, a, b: max(a, min(b, v))

from pyruntime import trench_ffi as t  # encode + packed_probe (shipped truth)
from src.utils.packed_runtime import evaluate_body, gate_failures
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np

fitter = None

# Forward compile is now owned ONCE by trench-core (compiler.rs), called via
# t.compile_body. No local stage_biquad/biquad_to_words mirror — that duplication
# (and its stale 0.9999 radius clamp) is retired; the DLL is the single source.
CORNER_KEYS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]

def corner_params(lanes, ci):
    useB = ci in (1, 3); sharp = ci in (2, 3); out = []
    for L in lanes:
        z = (L["zB"] if useB else L["zA"])
        out.append([1.0 if L.get("on", True) else 0.0,
                    L["pfB"] if useB else L["pf"],
                    L["prHi"] if sharp else L["pr"],
                    L.get("gain", 1.0),
                    1.0 if (z.get("on", True) and z["depth"] > 0.02) else 0.0,
                    z["hz"], z["depth"]])
    return out

def words_from_body(body):
    words = {}; off = 0
    for key in CORNER_KEYS:
        rows = []
        for _ in range(6):
            row = []
            for _ in range(5):
                row.append(body[off] | (body[off + 1] << 8)); off += 2
            rows.append(row)
        words[key] = rows
    return words

def pack(lanes):
    # Single owner: marshal the 168-f64 param vector and let trench-core compile it.
    p168 = []
    for ci in range(len(CORNER_KEYS)):
        for row in corner_params(lanes, ci):
            p168 += [float(x) for x in row]
    body = t.compile_body(p168)
    return bytes(body), words_from_body(body)

def body_words_from_payload(payload):
    if payload.get("hex"):
        body = bytes.fromhex(payload["hex"])
        if len(body) != 240:
            raise ValueError(f"expected 240-byte body, got {len(body)}")
        return body, words_from_body(body)
    return pack(payload["lanes"])

def mag_db(words, m, q, freqs):
    """packed-runtime magnitude via trench_core decode (the truth)."""
    pr = t.packed_probe(words_to_body(words), m, q); out = []
    for f in freqs:
        s = 0.0
        for (b0, b1, b2, a1, a2) in pr["biquad"]:
            w = TAU * f / SR; c, sn, c2, s2 = math.cos(w), math.sin(w), math.cos(2 * w), math.sin(2 * w)
            nr, ni = b0 + b1 * c + b2 * c2, -(b1 * sn + b2 * s2); dr, di = 1 + a1 * c + a2 * c2, -(a1 * sn + a2 * s2)
            s += 20 * math.log10(max(1e-12, math.hypot(nr, ni) / max(1e-12, math.hypot(dr, di))))
        out.append(s)
    return out

def words_to_body(words):
    b = bytearray()
    for key in CORNER_KEYS:
        for row in words[key]:
            for x in row: b += int(x & 0xffff).to_bytes(2, "little")
    return bytes(b)

def audit(body):
    rep = {"grid": 17, "stable": True, "max_pole_radius": 0.0, "unstable_cells": 0, "cells": 0}
    import numpy as np
    axis = np.linspace(0, 1, 17)
    for m in axis:
        for q in axis:
            p = t.packed_probe(body, float(m), float(q)); rep["cells"] += 1
            rep["max_pole_radius"] = max(rep["max_pole_radius"], p["max_pole_radius"])
            if p["unstable_mask"] or p["nonfinite_mask"]:
                rep["unstable_cells"] += 1; rep["stable"] = False
    rep["verdict"] = "PASS" if rep["stable"] and rep["max_pole_radius"] < 1.0 else "FAIL"
    return rep

def _load_score_context():
    ref_path = ROOT / "dev/tmp/production_authoring/extreme_qd_v1_final/reference_aggregate.json"
    reference = json.loads(ref_path.read_text(encoding="utf-8")) if ref_path.exists() else {
        "median_endpoint_span_db": 83.74825127919539,
        "median_morph_contrast_db": 24.806333597309525,
        "median_secondary_contrast_db": 17.138242518332483,
    }
    gates = SimpleNamespace(
        maximum_pole_radius=0.99990,
        minimum_ceiling_radius=0.9980,
        minimum_center_span_db=74.0,
        minimum_endpoint_span_db=88.0,
        maximum_span_db=285.0,
        minimum_morph_contrast_db=24.0,
        minimum_secondary_contrast_db=17.0,
        minimum_center_peaks=3,
        minimum_center_valleys=3,
        minimum_zero_motion_octaves=0.35,
        reference_endpoint_span_ratio=1.00,
        reference_morph_contrast_ratio=0.95,
        reference_secondary_contrast_ratio=0.95,
    )
    return gates, reference

SCORE_GATES, SCORE_REFERENCE = _load_score_context()

def score_body(body, grid_steps=9):
    metrics = evaluate_body(body, int(grid_steps))
    failures = gate_failures(metrics, SCORE_GATES, SCORE_REFERENCE)
    gates = {
        "stable": not any(reason == "packed surface is unstable or non-finite" for reason in failures),
        "radius": not any(reason in ("pole ceiling exceeded", "never reaches hot pole corridor") for reason in failures),
        "span": not any(reason in ("center terrain is too tame", "endpoint terrain is below ROM-calibrated floor", "endpoint terrain is pathological") for reason in failures),
        "morph": "Morph contrast is too weak" not in failures,
        "q": "Secondary contrast is too weak" not in failures,
        "peaks": "not enough center mountains" not in failures,
        "valleys": "not enough center canyons" not in failures,
        "zeros": "zeros do not travel enough" not in failures,
    }
    keys = (
        "objective", "max_pole_radius", "center_span_db", "endpoint_span_db_mean",
        "morph_contrast_rms_db", "secondary_contrast_rms_db",
        "center_response_peaks", "center_response_valleys",
        "median_zero_motion_octaves", "ceiling_occupancy_fraction",
        "grid_unstable_rows", "grid_nonfinite_rows", "interior_unstable_rows",
        "interior_nonfinite_rows",
    )
    return {
        "ok": True,
        "verdict": "PASS" if not failures else "FAIL",
        "failures": failures,
        "gates": gates,
        "metrics": {key: metrics.get(key) for key in keys},
        "reference": SCORE_REFERENCE,
        "grid_steps": int(grid_steps),
    }

def render_png(body, path):
    import numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    freqs = np.geomspace(40, 18000, 240)
    fig, ax = plt.subplots(figsize=(9, 4.2), facecolor="#0a0c0b")
    words = None
    for m, q, c, lbl in [(0, 0, "#5ba35a", "A·broad"), (1, 0, "#e09a2e", "B·broad"),
                         (0, 1, "#9fe7d0", "A·sharp"), (1, 1, "#e8533a", "B·sharp")]:
        pr = t.packed_probe(body, m, q)
        ys = []
        for f in freqs:
            s = 0.0
            for (b0, b1, b2, a1, a2) in pr["biquad"]:
                w = TAU * f / SR; cc, sn, c2, s2 = math.cos(w), math.sin(w), math.cos(2 * w), math.sin(2 * w)
                nr, ni = b0 + b1 * cc + b2 * c2, -(b1 * sn + b2 * s2); dr, di = 1 + a1 * cc + a2 * c2, -(a1 * sn + a2 * s2)
                s += 20 * math.log10(max(1e-12, math.hypot(nr, ni) / max(1e-12, math.hypot(dr, di))))
            ys.append(s)
        ax.semilogx(freqs, ys, lw=1.4, color=c, label=lbl)
    ax.set_xlim(40, 18000); ax.grid(alpha=.2); ax.legend(fontsize=8)
    ax.set_title("packed-runtime response (linear filter — no AGC/drive)", color="#cfe9df")
    ax.set_xlabel("Hz", color="#9aa"); ax.tick_params(colors="#8a968f", labelsize=7)
    fig.tight_layout(); fig.savefig(str(path), dpi=110, facecolor="#0a0c0b"); plt.close(fig)

def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if isinstance(data, str):
        tmp.write_text(data, encoding="utf-8")
    else:
        tmp.write_bytes(data)
    tmp.replace(path)

def publish_audition_slot(cart, body):
    AUDITION_DIR.mkdir(parents=True, exist_ok=True)
    if AUDITION_JSON.exists():
        write_atomic(AUDITION_JSON.with_suffix(".prev.json"), AUDITION_JSON.read_text(encoding="utf-8"))
    write_atomic(AUDITION_JSON, json.dumps(cart, indent=2) + "\n")
    write_atomic(AUDITION_BODY, body)
    return {
        "json": str(AUDITION_JSON),
        "body240": str(AUDITION_BODY),
        "json_bytes": AUDITION_JSON.stat().st_size,
        "body240_bytes": AUDITION_BODY.stat().st_size,
    }

def bake(payload):
    name = (payload.get("name") or "untitled").strip() or "untitled"
    slug = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_").lower() or "untitled"
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    sess = OUTROOT / f"{slug}_{stamp}"; sess.mkdir(parents=True, exist_ok=True)
    lanes = payload.get("lanes")
    corners = payload.get("corners")
    body, words = body_words_from_payload(payload)
    assert len(body) == 240, len(body)
    rep = audit(body)
    scored = score_body(body, 17)
    # artifacts
    (sess / "target.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if lanes is not None:
        (sess / "fitted_lanes.json").write_text(json.dumps(lanes, indent=2), encoding="utf-8")
        law = {"name": name, "format": "law-source-v1", "foundation_hz": payload.get("foundation"),
               "lanes": [{"role": L.get("role"), "pole_home": L["pf"], "pole_away": L["pfB"],
                          "radius_lo": L["pr"], "radius_hi": L["prHi"],
                          "zero_home": L["zA"], "zero_away": L["zB"], "gain": L.get("gain", 1.0)} for L in lanes]}
    else:
        (sess / "hand_corners.json").write_text(json.dumps(corners, indent=2), encoding="utf-8")
        law = {"name": name, "format": "df2-hand-pz-frame-v1", "cornerOrder": CORNER_KEYS,
               "source": "explicit browser-packed pole-zero frame", "corners": corners}
    (sess / "law_source.json").write_text(json.dumps(law, indent=2), encoding="utf-8")
    (sess / "body.body240").write_bytes(body)
    cart = {"format": "compiled-v1", "name": name, "sampleRate": SR, "stages": 6,
            "cornerOrder": CORNER_KEYS,
            "keyframes": [{"label": k, "boost": 1.0, "packedWords": words[k]} for k in CORNER_KEYS],
            "lawAudit": rep, "score": scored}
    (sess / "cartridge.json").write_text(json.dumps(cart, indent=2), encoding="utf-8")
    audition = publish_audition_slot(cart, body)
    (sess / "audit.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    (sess / "score.json").write_text(json.dumps(scored, indent=2), encoding="utf-8")
    render_png(body, sess / "response.png")
    (sess / "workbench.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>{name}</title>"
        f"<body style='background:#0a0c0b;color:#cfe9df;font-family:monospace;padding:20px'>"
        f"<h2>{name}</h2><p>verdict <b>{rep['verdict']}</b> · max r {rep['max_pole_radius']:.6f} · "
        f"unstable cells {rep['unstable_cells']}/{rep['cells']}</p>"
        f"<img src='response.png' style='max-width:900px;border:1px solid #222'>"
        f"<pre>{json.dumps(law, indent=2)}</pre></body>", encoding="utf-8")
    return {"ok": True, "session": sess.name,
            "verdict": rep["verdict"], "score": scored,
            "maxr": rep["max_pole_radius"],
            "unstable_cells": rep["unstable_cells"], "cells": rep["cells"],
            "dir": str(sess), "audition": audition, "hex": body.hex()}

def _slugify(name):
    return "".join(ch if ch.isalnum() else "_" for ch in name).strip("_").lower() or "untitled"

def _flat_typed_cards(cards):
    """6 designer cards {type,fcA,fcB,qLo,qHi,gain,on} -> the flat 42-f64 vector
    compile_body_typed expects (same order packTyped writes into the WASM)."""
    if len(cards) != 6:
        raise ValueError(f"expected 6 typed cards, got {len(cards)}")
    flat = []
    for c in cards:
        flat += [float(c["type"]), float(c["fcA"]), float(c["fcB"]),
                 float(c["qLo"]), float(c["qHi"]), float(c["gain"]),
                 1.0 if c.get("on", True) else 0.0]
    return flat

def keep(payload):
    """The KEEP button: typed cards -> DLL compile -> null vs browser WASM bytes ->
    17x17 packed audit -> bank artifacts (body240+cart+png+BANK.md row) ->
    plugin override dir + live audition slot. FAIL audits do not enter the bank."""
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("name it before keeping — the bank has no anonymous rows")
    slug = _slugify(name)
    cards = payload["cards"]
    body = t.compile_body_typed(_flat_typed_cards(cards))
    if payload.get("hex"):
        if bytes.fromhex(payload["hex"]) != body:
            raise RuntimeError("NULL FAILED: browser WASM bytes != DLL compile_body_typed — encoder drift, nothing banked")
    rep = audit(body)
    if rep["verdict"] != "PASS":
        return {"ok": False, "banked": False, "verdict": rep["verdict"],
                "error": f"17x17 audit FAIL ({rep['unstable_cells']}/{rep['cells']} unstable cells, max r {rep['max_pole_radius']:.6f}) — not banked",
                "audit": rep}
    words = words_from_body(body)
    cart = {"format": "compiled-v1", "name": name, "sampleRate": SR, "stages": 6,
            "cornerOrder": CORNER_KEYS,
            "keyframes": [{"label": k, "boost": 1.0, "packedWords": words[k]} for k in CORNER_KEYS],
            "typedCards": cards, "lawAudit": rep}
    cart_text = json.dumps(cart, indent=2) + "\n"
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    if (BANK_DIR / f"{slug}.body240").exists():
        raise ValueError(f"'{slug}' is already in the bank — pick another name")
    (BANK_DIR / f"{slug}.body240").write_bytes(body)
    (BANK_DIR / f"{slug}.cart.json").write_text(cart_text, encoding="utf-8")
    render_png(body, BANK_DIR / f"{slug}.png")
    row_n = len(list(BANK_DIR.glob("*.body240")))
    date = datetime.date.today().isoformat()
    words_txt = (payload.get("words") or "").strip().replace("|", "/") or "—"
    source = (payload.get("source") or "designer").replace("|", "/")
    row = f"| {row_n} | {slug} | {source} | {words_txt} | {date} | PASS maxr {rep['max_pole_radius']:.4f} |"
    lines = BANK_MD.read_text(encoding="utf-8").splitlines()
    last_tbl = max(i for i, ln in enumerate(lines) if ln.lstrip().startswith("|"))
    lines.insert(last_tbl + 1, row)
    write_atomic(BANK_MD, "\n".join(lines) + "\n")
    PLUGIN_BODIES_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(PLUGIN_BODIES_DIR / f"{slug}.cart.json", cart_text)
    audition = publish_audition_slot(cart, body)
    return {"ok": True, "banked": True, "verdict": "PASS", "slug": slug,
            "maxr": rep["max_pole_radius"], "bank": str(BANK_DIR / f"{slug}.body240"),
            "audition": audition}

def kill(payload):
    """The KILL button: one row of Tyson's words into the rejection ledger."""
    label = ((payload.get("label") or "unnamed design").strip() or "unnamed design").replace("|", "/")
    words_txt = (payload.get("words") or "").strip().replace("|", "/")
    if not words_txt:
        raise ValueError("a kill needs the why — one word is enough")
    with KILLS_MD.open("a", encoding="utf-8") as f:
        f.write(f"| {label} | {words_txt} | {datetime.date.today().isoformat()} |\n")
    return {"ok": True, "label": label}

def seeds_payload():
    """Seed list for the designer: authored seeds + every banked body that carries
    its typed source (so keeps become reloadable starting points)."""
    out = []
    if SEEDS_JSON.exists():
        out += json.loads(SEEDS_JSON.read_text(encoding="utf-8")).get("seeds", [])
    if BANK_DIR.exists():
        for p in sorted(BANK_DIR.glob("*.cart.json")):
            try:
                cart = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if cart.get("typedCards"):
                out.append({"name": f"bank · {cart.get('name', p.stem)}",
                            "hint": "kept body (typed source)", "cards": cart["typedCards"]})
    return {"ok": True, "seeds": out}

def score_payload(payload):
    body = body_words_from_payload(payload)[0]
    if len(body) != 240:
        raise ValueError(f"expected 240-byte body, got {len(body)}")
    return score_body(body, int(payload.get("grid", 9)))

def fit_audio(payload):
    """Fit the in/out slice of audio the browser selected -> a 6-section source
    (3+ foundation rails + LPC source poles). Shares the CLI fitter (one owner)."""
    global fitter
    if fitter is None:
        import fit_sources_lpc as fitter        # one owner for LPC/LSP fitting (CLI + /fit share it)
    samples = np.asarray(payload.get("samples", []), dtype=np.float64)
    sr = float(payload.get("sr", 44100.0))
    if samples.size < 256:
        raise ValueError(f"audio slice too short ({samples.size} samples) — widen the selection")
    samples = samples / (np.max(np.abs(samples)) or 1.0)
    src = fitter.fit(samples, sr,
                     name=(payload.get("name") or "fit").strip() or "fit",
                     group="fit · " + payload.get("qsource", "lpc"),
                     found=payload.get("found"),
                     preemph=float(payload.get("preemph", 0.97)),
                     crank=float(payload.get("crank", 0.0)),
                     qsource=payload.get("qsource", "lpc"))
    return {"ok": True,
            "source": {k: src[k] for k in ("name", "group", "sections")},
            "waste": src["waste"], "lsf_stable": src["lsf_stable"],
            "anchor": src["anchor"], "poles": src["poles"]}


def _foundation_stages(name):
    """The CHOOSEABLE foundation palette — your ear picks the bottom (not computed)."""
    from src.architectures.trajectory_program import StageTrajectory as ST
    table = {
        "none":      [],
        "sub_shelf": [ST(kind="lowshelf", pole_start_hz=120, pole_end_hz=120, gain_start_db=6, gain_end_db=6)],
        "low_hump":  [ST(kind="peaking", pole_start_hz=180, pole_end_hz=180, section_q=1.3, gain_start_db=9, gain_end_db=9)],
        "808":       [ST(kind="peaking", pole_start_hz=55,  pole_end_hz=55,  section_q=2.2, gain_start_db=11, gain_end_db=11)],
        "tube":      [ST(kind="peaking", pole_start_hz=110, pole_end_hz=110, section_q=1.6, gain_start_db=8, gain_end_db=8)],
    }
    return table.get(name, table["low_hump"])


def fit_body(payload):
    """samples + sr + foundation -> ARMA character (poles+ZEROS/cavities, via arma_weapons) under a
    CHOSEN foundation -> packed 240-byte body hex. The whole build is Python (the proven path);
    the browser only sends audio + the foundation choice and gets bytes back."""
    import tempfile, wave
    import arma_weapons
    from src.architectures.trajectory_program import StageTrajectory as ST, ProgramGenome
    from src.utils.body240 import words_from_kernels, raw_from_words
    ZE = SR * 0.49
    sc = lambda v: (float(v[0]), float(v[-1])) if isinstance(v, (list, tuple)) else (float(v), float(v))
    samples = np.asarray(payload.get("samples", []), dtype=np.float64)
    sr = float(payload.get("sr", 44100.0))
    if samples.size < 512:
        raise ValueError(f"audio too short ({samples.size} samples)")
    samples = samples / (np.max(np.abs(samples)) or 1.0)
    _tmpdir = ROOT / "dev" / "tmp" / "_fit"; _tmpdir.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(_tmpdir)); fd.close()
    with wave.open(fd.name, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(sr))
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    try:
        weapon = arma_weapons.build_weapon(Path(fd.name))      # ARMA: poles + mined zeros (the cavities)
    finally:
        try: Path(fd.name).unlink()
        except Exception: pass
    if not weapon:
        raise ValueError("fit found no resonances (give it a sustained vowel or a Dirac IR)")
    found = _foundation_stages(payload.get("foundation", "low_hump"))
    csecs = sorted(weapon["sections"], key=lambda s: sc(s["pole_hz_home"])[0], reverse=True)[:6 - len(found)]
    char = []
    for s in csecs:
        ph0, _ = sc(s["pole_hz_home"]); ph1, _ = sc(s["pole_hz_away"])
        zh0, zh1 = sc(s["zero_hz"]); zr0, _ = sc(s["zero_r"])
        char.append(ST(kind="actor", pole_start_hz=clamp(ph0, 30, ZE), pole_end_hz=clamp(ph1, 30, ZE),
            zero_start_hz=clamp(zh0, 30, ZE), zero_end_hz=clamp(zh1, 30, ZE),
            pole_radius_q0=min(float(s["pole_r_q0"]), 0.9985), pole_radius_q100=min(float(s["pole_r_q1"]), 0.9985),
            zero_radius_q0=min(zr0, 0.999), zero_radius_q100=min(zr0, 0.999)))
    stages = list(found) + char
    while len(stages) < 6:
        stages.append(ST(kind="actor", pole_start_hz=9000, pole_end_hz=9000, zero_start_hz=ZE, zero_end_hz=ZE,
                         pole_radius_q0=0.6, pole_radius_q100=0.6, zero_radius_q0=0.5, zero_radius_q100=0.5))
    body = raw_from_words(words_from_kernels(ProgramGenome(family="fitbody", seed=1, stages=tuple(stages[:6])).corner_kernels()))
    m = evaluate_body(body, 5)
    return {"ok": True, "hex": body.hex(), "stable": bool(m["max_pole_radius"] < 1.0),
            "foundation": payload.get("foundation", "low_hump"), "character_sections": len(char),
            "max_radius": round(float(m["max_pole_radius"]), 5)}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=str(WEB), **k)
    def log_message(self, *a): pass
    def serve_file(self, target):
        data = target.read_bytes()
        ctype = (
            "text/html" if target.suffix == ".html" else
            "image/png" if target.suffix == ".png" else
            "audio/wav" if target.suffix == ".wav" else
            "application/json" if target.suffix == ".json" else
            "application/octet-stream"
        )
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/sessions/"):
            rel = path.removeprefix("/sessions/").strip("/")
            target = (OUTROOT / rel).resolve()
            if not str(target).startswith(str(OUTROOT.resolve())) or not target.is_file():
                self.send_error(404); return
            self.serve_file(target)
            return
        if path == "/seeds":
            try:
                res, code = seeds_payload(), 200
            except Exception as e:
                res, code = {"ok": False, "error": str(e)}, 500
            data = json.dumps(res).encode("utf-8")
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            return
        if path == "/audition/v1":
            self.send_response(302); self.send_header("Location", "/audition/v1/audition.html"); self.end_headers()
            return
        if path.startswith("/audition/v1/"):
            rel = path.removeprefix("/audition/v1/").strip("/") or "audition.html"
            target = (V1_AUDITION / rel).resolve()
            if not str(target).startswith(str(V1_AUDITION.resolve())) or not target.is_file():
                self.send_error(404); return
            self.serve_file(target)
            return
        super().do_GET()
    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/bake", "/score", "/fit", "/fitbody", "/keep", "/kill"):
            self.send_error(404); return
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            res = {"/bake": bake, "/score": score_payload, "/fit": fit_audio,
                   "/fitbody": fit_body, "/keep": keep, "/kill": kill}[path](payload); code = 200
        except Exception as e:
            import traceback; traceback.print_exc()
            res = {"ok": False, "error": str(e)}; code = 500
        data = json.dumps(res).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store"); super().end_headers()

if __name__ == "__main__":
    if not t.available(): print("WARNING: trench_core not loadable — bake/audit will fail")
    OUTROOT.mkdir(parents=True, exist_ok=True)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8130
    print(f"Law Author Studio: http://localhost:{port}/studio.html   (bake -> {OUTROOT})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
