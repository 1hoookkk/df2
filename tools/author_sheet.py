"""AUTHOR SHEET — Tyson's pen. A body is a JSON sheet of 6 lanes; this
compiles it and shows the verdict in the same sheets the ROM study uses.

The sheet IS the METHOD.md model: 6 lanes x (LOW pose + HIGH pose), each pose
a pole [Hz, r] and a zero [Hz, r]. Gain is bookkept automatically (each lane
normalized flat off-resonance, the serial-cascade survival law). Corners are
derived. Provenance is required per lane — no source, no body.

Usage:
  python tools/author_sheet.py sheets/VOWL_aa_to_iy.json [--wav] [--no-live]
Outputs (dev/tmp/author_sheet/<name>*):
  <name>.body240              the real 240-byte artifact
  <name>.png                  morph heatmap + LO/HI/Q curves + gate verdict
  <name>_per_stage.png        per-lane verdict sheet (same format as ROM study)
  <name>_overlay.png          lanes + cascade at corners/center (same format)
  <name>_morphsweep.wav       (--wav) pink-noise Morph 0->100 sweep, real engine
  <name>_qsweep.wav           (--wav) Q 0->100 sweep at M50, real engine

THE EAR PATH (default on): every compile also writes the compiled-v1
cartridge to Documents/TRENCH/authoring_slot.json. A diagnostics TRENCH with
the "@ Audition (live)" body selected hot-reloads it — edit the sheet, run
this, and the change is under your fingers on real material within a second.

Sheet format (sheets/TEMPLATE.json is the annotated starter):
  { "name": "...",
    "lanes": [
      { "what":   "human label for the lane",
        "source": "table/measured citation — REQUIRED, empty = refused",
        "low":  { "pole": [hz, r], "zero": [hz, r] },
        "high": { "pole": [hz, r], "zero": [hz, r] },
        "q_tighten": 0.02,          // Q100 pole-radius add (0 / 0.02 / 0.06)
        "q_zero_tighten": 0.0 },    // optional: Q100 zero-radius add
      { "parked": true }            // a flat lane (pole==zero), pays no tax
    ] }
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import morph_designer as md
from tools import plot_stages as ps

import numpy as np

OUT = md.ROOT / "dev" / "tmp" / "author_sheet"


def lane_from_row(row: dict) -> md.Lane:
    if row.get("parked"):
        (p, z, t, label) = md.PARKED
        return md.Lane(p, p, z, z, t, "parked flat lane (pole==zero, identity)")
    lo, hi = row["low"], row["high"]
    return md.Lane(
        tuple(lo["pole"]), tuple(hi["pole"]),
        tuple(lo["zero"]), tuple(hi["zero"]),
        float(row.get("q_tighten", 0.0)),
        str(row.get("source", "")),
        float(row.get("q_zero_tighten", 0.0)),
    )


def words_dict(body: bytes) -> dict:
    w = np.frombuffer(body, dtype="<u2").reshape(4, 6, 5)
    return {k: [tuple(int(x) for x in w[c, s]) for s in range(6)]
            for c, k in enumerate("ABCD")}


def write_audition_slot(name: str, body: bytes, provenance: str) -> Path | None:
    """compiled-v1 cartridge -> Documents/TRENCH/authoring_slot.json.
    The diagnostics plugin's '@ Audition (live)' body hot-reloads this file."""
    slot = Path.home() / "Documents" / "TRENCH" / "authoring_slot.json"
    if not slot.parent.is_dir():
        return None
    w = np.frombuffer(body, dtype="<u2").reshape(4, 6, 5)
    from src.utils.body240 import CORNER_ORDER
    keyframes = []
    for ci, label in enumerate(CORNER_ORDER):
        m, q = md.CORNER_POINTS[label]
        keyframes.append({
            "label": label, "morph": float(m), "q": float(q), "boost": 1.0,
            "packedWords": [[int(x) for x in w[ci, s]] for s in range(6)],
        })
    cart = {"format": "compiled-v1", "name": name, "provenance": provenance,
            "sampleRate": md.SR, "authoring_sample_rate_hz": md.SR,
            "stages": 6, "cornerOrder": list(CORNER_ORDER), "keyframes": keyframes}
    slot.write_text(json.dumps(cart, indent=1), encoding="utf-8")
    return slot


def write_sweep_wavs(name: str, body: bytes) -> list[Path]:
    """Continuous Morph and Q sweeps on pink noise through the REAL engine
    (audition voicing law: slam 0.15; the sweep IS the audition, not snapshots)."""
    import wave
    from pyruntime import trench_ffi
    seconds, block = 6.0, 512
    n = int(md.SR * seconds)
    rng = np.random.default_rng(2026)
    white = rng.standard_normal(n)
    x = np.empty(n); prev = 0.0                        # one-pole lowpassed white ~ pink-ish drive
    for i in range(n):
        prev = 0.55 * white[i] + 0.45 * prev
        x[i] = prev
    x = (0.25 * x / max(1e-9, np.max(np.abs(x)))).astype("<f4")
    nb = max(1, (n + block - 1) // block)
    out = []
    for tag, morph, q in (
        ("morphsweep", np.linspace(0.0, 1.0, nb).tolist(), [0.5] * nb),
        ("qsweep", [0.5] * nb, np.linspace(0.0, 1.0, nb).tolist()),
    ):
        y = np.frombuffer(
            trench_ffi.engine_render_slam(body, morph, q, x.tobytes(),
                                          slam_drive=0.15, agc_drive=1.0,
                                          sr=md.SR, block=block),
            dtype="<f4")
        y = y / max(1e-9, np.max(np.abs(y))) * 0.85
        p = OUT / f"{name}_{tag}.wav"
        with wave.open(str(p), "wb") as h:
            h.setnchannels(1); h.setsampwidth(2); h.setframerate(int(md.SR))
            h.writeframes((y * 32767.0).astype("<i2").tobytes())
        out.append(p)
    return out


def write_audition_page(name: str, body: bytes, wavs: list[Path]) -> Path:
    """One self-contained HTML: the response curve ANIMATES in sync with the
    sweep audio. Plot is the hero; audio underneath. No server, no deps."""
    import base64
    n_frames, stride = 120, 3
    freqs = md.FREQS[::stride]
    frames = {}
    for mode, mq in (("morph", lambda t: (t, 0.5)), ("q", lambda t: (0.5, t))):
        rows = []
        for i in range(n_frames):
            m, q = mq(i / (n_frames - 1))
            rows.append([round(float(v), 1) for v in md.resp(body, m, q)[::stride]])
        frames[mode] = rows
    wav_b64 = {}
    for p in wavs:
        tag = "morph" if "morphsweep" in p.name else "q"
        wav_b64[tag] = base64.b64encode(p.read_bytes()).decode()
    payload = json.dumps({"name": name, "freqs": [round(float(f), 1) for f in freqs],
                          "frames": frames})
    html = f"""<!doctype html><meta charset="utf-8"><title>{name} — audition</title>
<style>
 body{{background:#0a0c0b;color:#cfe9df;font:13px/1.5 system-ui;margin:0;padding:18px}}
 canvas{{width:100%;height:520px;display:block;background:#0d100e;border:1px solid #1d2320}}
 .bar{{display:flex;gap:10px;align-items:center;margin:12px 0}}
 button{{background:#15201b;color:#cfe9df;border:1px solid #2c3a33;padding:8px 22px;
   font:600 13px system-ui;cursor:pointer;letter-spacing:.08em}}
 button.on{{background:#274238;border-color:#4a7a66}}
 h1{{font:600 15px system-ui;letter-spacing:.14em;margin:0 0 10px}}
</style>
<h1>{name}</h1>
<canvas id="c" width="1560" height="1040"></canvas>
<div class="bar">
 <button id="bm" class="on">MORPH 0&rarr;100</button>
 <button id="bq">Q 0&rarr;100</button>
 <span id="pos"></span>
</div>
<audio id="am" src="data:audio/wav;base64,{wav_b64.get('morph','')}"></audio>
<audio id="aq" src="data:audio/wav;base64,{wav_b64.get('q','')}"></audio>
<script>
const D={payload};
const cv=document.getElementById('c'),g=cv.getContext('2d');
const F=D.freqs,N=F.length,lo=Math.log10(F[0]),hi=Math.log10(F[N-1]);
const X=F.map(f=>(Math.log10(f)-lo)/(hi-lo)*cv.width);
const yOf=db=>cv.height*(1-(db+45)/90);
let mode='morph';
const au={{morph:document.getElementById('am'),q:document.getElementById('aq')}};
function grid(){{g.fillStyle='#0d100e';g.fillRect(0,0,cv.width,cv.height);
 g.strokeStyle='#1a211d';g.lineWidth=1;g.beginPath();
 for(const f of [100,1000,10000]){{const x=(Math.log10(f)-lo)/(hi-lo)*cv.width;g.moveTo(x,0);g.lineTo(x,cv.height);}}
 for(let db=-40;db<=40;db+=10){{g.moveTo(0,yOf(db));g.lineTo(cv.width,yOf(db));}}
 g.stroke();
 g.strokeStyle='#2a332e';g.beginPath();g.moveTo(0,yOf(0));g.lineTo(cv.width,yOf(0));g.stroke();
 g.fillStyle='#5a6a61';g.font='20px system-ui';
 g.fillText('100',(Math.log10(100)-lo)/(hi-lo)*cv.width+4,cv.height-8);
 g.fillText('1k',(Math.log10(1000)-lo)/(hi-lo)*cv.width+4,cv.height-8);
 g.fillText('10k',(Math.log10(10000)-lo)/(hi-lo)*cv.width+4,cv.height-8);
 g.fillText('+20',6,yOf(20)-4);g.fillText('-20',6,yOf(-20)-4);}}
function curve(row,color,w){{g.strokeStyle=color;g.lineWidth=w;g.beginPath();
 for(let i=0;i<N;i++){{const y=yOf(Math.max(-45,Math.min(45,row[i])));
  i?g.lineTo(X[i],y):g.moveTo(X[i],y);}} g.stroke();}}
function draw(t){{const rows=D.frames[mode];grid();
 curve(rows[0],'#3a4a42',2);curve(rows[rows.length-1],'#3a4a42',2);
 const idx=Math.min(rows.length-1,Math.round(t*(rows.length-1)));
 curve(rows[idx],'#bfeee0',5);
 document.getElementById('pos').textContent=(mode==='morph'?'MORPH ':'Q ')+Math.round(t*100);}}
function tick(){{const a=au[mode];
 draw(a.duration?a.currentTime/a.duration:0);requestAnimationFrame(tick);}}
function setMode(m){{au[mode].pause();mode=m;
 document.getElementById('bm').className=m==='morph'?'on':'';
 document.getElementById('bq').className=m==='q'?'on':'';
 const a=au[m];a.currentTime=0;a.play();}}
document.getElementById('bm').onclick=()=>setMode('morph');
document.getElementById('bq').onclick=()=>setMode('q');
cv.onclick=()=>{{const a=au[mode];a.paused?a.play():a.pause();}};
draw(0);tick();
</script>"""
    p = OUT / f"{name}_audition.html"
    p.write_text(html, encoding="utf-8")
    return p


def main(sheet_path: str, live: bool = True, wav: bool = False) -> None:
    sheet = json.loads(Path(sheet_path).read_text(encoding="utf-8"))
    name = sheet["name"]
    rows = sheet["lanes"]
    if not (1 <= len(rows) <= 6):
        raise SystemExit(f"REFUSED: {len(rows)} lanes (need 1..6)")
    lanes = [lane_from_row(r) for r in rows]

    body = md.compile_lanes(name, lanes)          # provenance gate lives here
    OUT.mkdir(parents=True, exist_ok=True)
    body_path = OUT / f"{name}.body240"
    body_path.write_bytes(body)

    # gate metrics + heatmap (morph_designer's render, redirected here)
    md.OUT = OUT
    md._render_body(name, body)

    # the ROM-study verdict sheets on OUR body — same eyes for theirs and ours
    ps.OUT_DIR = str(OUT)
    cw = words_dict(body)
    per_stage = OUT / f"{name}_per_stage.png"
    overlay = OUT / f"{name}_overlay.png"
    ps.sheet_per_stage(name, cw, str(per_stage))
    ps.sheet_overlay(name, cw, str(overlay))
    print(body_path)
    print(OUT / f"{name}.png")
    print(per_stage)
    print(overlay)

    if live:
        slot = write_audition_slot(name, body, f"author_sheet {Path(sheet_path).name}")
        if slot is not None:
            print(f"{slot}  <- '@ Audition (live)' body hears this NOW")
    if wav:
        wavs = write_sweep_wavs(name, body)
        for p in wavs:
            print(p)
        print(write_audition_page(name, body, wavs), " <- PLOT + SOUND together")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) != 1:
        raise SystemExit(__doc__)
    main(args[0], live="--no-live" not in flags, wav="--wav" in flags)
