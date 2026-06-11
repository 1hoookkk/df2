#!/usr/bin/env python3
"""audition_one — run an 808 through ONE raw .body240 via the SHIPPED engine
(AGC + saturate) and build a one-clip audition page. Same engine path, source,
and 5 positions as tools.render_audition; just for a single raw body file.

  python -m tools.audition_one path/to/body.body240
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scipy.signal import lfilter

from pyruntime import trench_ffi
from tools.render_audition import SR, POSITIONS, synth_808, write_wav


def pink_noise(dur=1.2, seed=7):
    """Steady pink noise (-3 dB/oct) — flat energy per octave, excites the whole
    filter shape. Paul Kellet's refined IIR colouring of white noise."""
    n = int(SR * dur)
    white = np.random.default_rng(seed).standard_normal(n)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1.0, -2.494956002, 2.017265875, -0.522189400]
    pink = lfilter(b, a, white)
    pk = np.max(np.abs(pink))
    return (pink / pk * 0.9).astype(np.float64) if pk > 1e-9 else pink


def render_raw_body(body: bytes, src):
    """Five FROZEN snapshots butted together (corners + middle). Static per clip."""
    if not trench_ffi.engine_available():
        raise RuntimeError("shipped engine not available — refusing AGC-less fallback for judging")
    gap = np.zeros(int(SR * 0.14))
    segs = []
    for _, m, q in POSITIONS:
        raw = trench_ffi.engine_render(body, m, q, src.astype(np.float32).tobytes(), SR)
        wet = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
        pk = np.max(np.abs(wet))
        if pk > 1e-9:
            wet = wet / pk * 0.9
        segs.append(wet)
        segs.append(gap)
    return np.concatenate(segs)


def render_sweep(body: bytes, src, q=1.0):
    """CONTINUOUS morph glide 0->1->0 at fixed Q on one engine instance — the
    interpolation interior actually moving (the 'magic in the middle')."""
    if not trench_ffi.engine_available():
        raise RuntimeError("shipped engine not available — refusing AGC-less fallback for judging")
    block = 512
    nb = max(2, (len(src) + block - 1) // block)
    half = nb // 2
    morph = np.concatenate([np.linspace(0, 1, half, endpoint=False),
                            np.linspace(1, 0, nb - half)])
    qarr = np.full(nb, float(q))
    raw = trench_ffi.engine_render_automated(
        body, morph.tolist(), qarr.tolist(), src.astype(np.float32).tobytes(), sr=SR)
    wet = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    pk = np.max(np.abs(wet))
    return wet / pk * 0.9 if pk > 1e-9 else wet


SOURCES = {"pink": pink_noise, "808": synth_808}


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m tools.audition_one path/to/body.body240 [pink|808]", file=sys.stderr)
        return 2
    bpath = Path(args[0])
    srckey = args[1] if len(args) > 1 and args[1] in SOURCES else "pink"
    body = bpath.read_bytes()
    if len(body) != 240:
        print(f"!! expected 240 bytes, got {len(body)}", file=sys.stderr)
        return 2

    name = bpath.stem
    out = ROOT / "dev" / "tmp" / "audition"
    out.mkdir(parents=True, exist_ok=True)
    snap = render_raw_body(body, SOURCES[srckey]())
    sweep = render_sweep(body, pink_noise(5.0), q=1.0)
    write_wav(out / f"{name}.wav", snap)
    write_wav(out / f"{name}_sweep.wav", sweep)

    html = [
        "<!doctype html><meta charset=utf-8><title>TRENCH audition</title>",
        "<style>body{background:#0b0f0e;color:#cdd;font:14px monospace;padding:24px}",
        "h1{color:#5bef6f}.row{margin:10px 0;padding:8px;border:1px solid #1c2722;border-radius:5px}",
        ".n{color:#ffd23e}.m{color:#789}audio{width:520px;vertical-align:middle}</style>",
        f"<h1>TRENCH audition — {name}</h1>",
        "<p class=m>Rendered via SHIPPED engine (AGC+saturate).</p>",
        f'<div class=row><span class=n>{name} · snapshots</span> '
        f'<span class=m>{srckey}, FROZEN at HOME · MORPH · TENSION · MORPH+TENSION · MIDDLE</span>'
        f'<br><audio controls src="{name}.wav"></audio></div>',
        f'<div class=row><span class=n>{name} · morph sweep</span> '
        f'<span class=m>pink, Q=100, morph GLIDING 0&rarr;1&rarr;0 (the interpolation interior, moving)</span>'
        f'<br><audio controls autoplay src="{name}_sweep.wav"></audio></div>',
    ]
    (out / "audition.html").write_text("\n".join(html))
    print(f"rendered {name}.wav (snapshots) + {name}_sweep.wav (moving morph), src={srckey}")
    print(f"open: {out / 'audition.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
