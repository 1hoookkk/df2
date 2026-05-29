#!/usr/bin/env python3
"""render_audition — run an 808 through a set of bodies via the SHIPPED engine
(AGC + saturate) and build a one-page audition. Each clip plays the same 808 at
the four corners + the emergent middle, back to back, so you hear the body's
whole range in one listen. Flag the ones that hit; tell me in sound.

  python -m tools.render_audition
"""
from __future__ import annotations

import json
import struct
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.packed_interp import packed_bilinear, words_to_coeffs

SR = 44100
POSITIONS = [
    ("HOME", 0.0, 0.0),
    ("MORPH", 1.0, 0.0),
    ("TENSION", 0.0, 1.0),
    ("MORPH+TENSION", 1.0, 1.0),
    ("MIDDLE", 0.5, 0.5),
]


def synth_808(dur=0.7):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = 50.0 + 60.0 * np.exp(-t / 0.03)  # pitch drop 110 -> 50 Hz
    phase = 2.0 * np.pi * np.cumsum(f) / SR
    body = np.sin(phase) * np.exp(-t / 0.28)
    click = np.zeros(n)
    c = int(SR * 0.004)
    click[:c] = np.linspace(1.0, 0.0, c)
    return (body + 0.25 * click).astype(np.float64)


def body_bytes_from_cart(cart) -> bytes:
    flat = []
    for kf in cart["keyframes"]:
        for w in kf["packedWords"]:
            flat.extend(int(x) & 0xFFFF for x in w)
    return struct.pack("<" + "H" * 120, *flat)


def cart_corner_words(cart):
    return {
        k: [tuple(w) for w in cart["keyframes"][i]["packedWords"]]
        for i, k in enumerate(["A", "B", "C", "D"])
    }


def df2t(signal, enc_stages):
    y = signal.copy()
    for enc in enc_stages:
        c0, c1, c2, c3, c4 = enc
        b0, b1, b2 = c4, c4 * (c0 - 2.0), c4 * (1.0 - c1)
        a1, a2 = c2 - 2.0, 1.0 - c3
        s1 = s2 = 0.0
        out = np.empty_like(y)
        for i, x in enumerate(y):
            o = b0 * x + s1
            s1 = b1 * x - a1 * o + s2
            s2 = b2 * x - a2 * o
            out[i] = o
        y = out
    return y


def render_body(cart, src):
    bb = body_bytes_from_cart(cart)
    cw = cart_corner_words(cart)
    use_engine = trench_ffi.engine_available()
    segs = []
    gap = np.zeros(int(SR * 0.14))
    for _, m, q in POSITIONS:
        if use_engine:
            raw = trench_ffi.engine_render(bb, m, q, src.astype(np.float32).tobytes(), SR)
            wet = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
        else:
            coeffs = packed_bilinear(cw, m, q)
            wet = df2t(src, [EncodedCoeffs(*c) for c in coeffs])
        pk = np.max(np.abs(wet))
        if pk > 1e-9:
            wet = wet / pk * 0.9  # normalize per segment so quiet bodies are audible
        segs.append(wet)
        segs.append(gap)
    return np.concatenate(segs), use_engine


def write_wav(path, x):
    pcm = np.clip(x, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    out = ROOT / "dev" / "tmp" / "audition"
    out.mkdir(parents=True, exist_ok=True)
    src = synth_808()

    manifest = {}
    mf = ROOT / "bodies" / "crazy" / "manifest.json"
    if mf.exists():
        for e in json.loads(mf.read_text()):
            manifest[e["name"]] = e

    jobs = sorted((ROOT / "bodies" / "crazy").glob("crazy_*.cart.json"))
    mv = ROOT / "bodies" / "proofs" / "metallic_vowel_target.json"
    if mv.exists():
        jobs = [mv] + jobs

    rows = []
    engine_used = False
    for fp in jobs:
        cart = json.loads(fp.read_text())
        name = fp.stem.replace(".cart", "")
        clip, used = render_body(cart, src)
        engine_used = engine_used or used
        write_wav(out / f"{name}.wav", clip)
        m = manifest.get(name, {})
        meta = (
            f"crazy={m.get('crazy', '—')}  notches/peaks={m.get('peaks', '—')}  seed={m.get('seed', '—')}"
            if m
            else "hand-built target"
        )
        rows.append((name, meta))
        print(f"  rendered {name}  ({meta})")

    path_note = "SHIPPED engine (AGC+saturate)" if engine_used else "Python cascade fallback (no AGC)"
    html = [
        "<!doctype html><meta charset=utf-8><title>TRENCH audition</title>",
        "<style>body{background:#0b0f0e;color:#cdd;font:14px monospace;padding:24px}",
        "h1{color:#5bef6f}.row{margin:10px 0;padding:8px;border:1px solid #1c2722;border-radius:5px}",
        ".n{color:#ffd23e}.m{color:#789}audio{width:520px;vertical-align:middle}</style>",
        f"<h1>TRENCH audition — 808 through each body</h1>",
        f"<p class=m>Each clip = the 808 at HOME · MORPH · TENSION · MORPH+TENSION · MIDDLE, back to back. "
        f"Rendered via {path_note}. Flag the ones that hit.</p>",
    ]
    for name, meta in rows:
        html.append(
            f'<div class=row><span class=n>{name}</span> '
            f'<span class=m>{meta}</span><br><audio controls src="{name}.wav"></audio></div>'
        )
    (out / "audition.html").write_text("\n".join(html))
    print(f"\n{len(rows)} clips via {path_note}")
    print(f"open: {out / 'audition.html'}")


if __name__ == "__main__":
    main()
