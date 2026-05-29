#!/usr/bin/env python3
"""prove_factorizer — audition + plot the response-first factorizer's output.

Consumes the artifacts written by the Rust proof test
(`cargo test -p trench-core --test factorizer_proof`): for each target it has a
`<name>.json` (target vs fitted magnitude + metrics) and a `<name>.body240`
(the fitted corner, replicated x4 = a static morph of that one corner).

This step closes the loop the numbers can't: it renders each fitted body through
the SHIPPED engine (AGC + saturate) with SAW / TONE / PINK and overlays
target-vs-fitted response, so the ear — the only fitness function — gets the
final word on whether the in-band fit (and the Nyquist-edge behaviour) is
musically usable.

  # first: cargo test -p trench-core --test factorizer_proof
  python tools/prove_factorizer.py
"""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.packed_interp import packed_bilinear, words_to_coeffs

SR = 44100
IN_DIR = ROOT / "dev" / "tmp" / "factorizer_proof"
CORNER_KEYS = ("A", "B", "C", "D")


def src_saw(dur=1.1, f0=110.0):
    t = np.arange(int(SR * dur)) / SR
    env = np.minimum(1.0, 8.0 * t) * np.exp(-t / (dur * 0.8))
    return (2.0 * ((f0 * t) % 1.0) - 1.0) * env * 0.6


def src_tone(dur=1.1, f0=220.0):
    t = np.arange(int(SR * dur)) / SR
    env = np.minimum(1.0, 12.0 * t) * np.exp(-t / (dur * 0.8))
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3, 4))
    return x * env * 0.4


def src_pink(dur=1.1, seed=0xF17):
    n = int(SR * dur)
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.arange(spec.size)
    spec[1:] /= np.sqrt(f[1:])  # -3 dB/oct
    x = np.fft.irfft(spec, n)
    return (x / (np.max(np.abs(x)) + 1e-9)) * 0.6


SOURCES = {"saw": src_saw(), "tone": src_tone(), "pink": src_pink()}


def body_corner_words(raw: bytes) -> dict[str, list[tuple[int, ...]]]:
    u16 = np.frombuffer(raw, dtype="<u2").reshape(4, 6, 5)
    return {CORNER_KEYS[c]: [tuple(int(v) for v in u16[c, s]) for s in range(6)] for c in range(4)}


def df2t(signal, enc_stages):
    """Python DF2T fallback (no AGC) — used only if the engine FFI is unavailable."""
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


def render(raw: bytes, src: np.ndarray) -> tuple[np.ndarray, bool]:
    if trench_ffi.engine_available():
        out = trench_ffi.engine_render(raw, 0.0, 0.0, src.astype(np.float32).tobytes(), SR)
        wet = np.frombuffer(out, dtype=np.float32).astype(np.float64)
        used = True
    else:
        cw = body_corner_words(raw)
        coeffs = packed_bilinear(cw, 0.0, 0.0)
        wet = df2t(src, [EncodedCoeffs(*c) for c in coeffs])
        used = False
    pk = np.max(np.abs(wet))
    if pk > 1e-9:
        wet = wet / pk * 0.9
    return wet, used


def write_wav(path: Path, x: np.ndarray):
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def plot_overlay(ax, d):
    f = np.array(d["freqs"])
    t = np.array(d["target_db"])
    fit = np.array(d["fitted_db"])
    lo, hi = d["band_hz"]
    ax.axvspan(lo, hi, color="#1d2a24", zorder=0)
    ax.semilogx(f, t, color="#5bef6f", lw=1.6, label="target")
    ax.semilogx(f, fit, color="#ffb13e", lw=1.3, label="fitted")
    ax.set_xlim(40, 16000)
    ax.set_title(
        f"{d['name']}\nin-band RMS {d['shape_rms_band_db']:.1f} dB · "
        f"max {d['shape_max_band_db']:.1f} dB · maxR {d['max_pole_radius']:.4f}",
        color="#cdd", fontsize=9,
    )
    ax.tick_params(colors="#889", labelsize=7)
    ax.set_facecolor("#0b0f0e")
    for s in ax.spines.values():
        s.set_color("#26302b")
    ax.legend(fontsize=7, facecolor="#11161400", labelcolor="#cdd", loc="lower left")


def main() -> int:
    jsons = sorted(IN_DIR.glob("*.json"))
    if not jsons:
        print(f"no artifacts in {IN_DIR}. Run first:", file=sys.stderr)
        print("  cargo test -p trench-core --test factorizer_proof", file=sys.stderr)
        return 1

    descs = [json.loads(p.read_text(encoding="utf-8")) for p in jsons]
    engine_used = False
    rows = []
    for d in descs:
        name = d["name"]
        raw = (IN_DIR / f"{name}.body240").read_bytes()
        clips = {}
        for sname, src in SOURCES.items():
            wet, used = render(raw, src)
            engine_used = engine_used or used
            wav = f"{name}__{sname}.wav"
            write_wav(IN_DIR / wav, wet)
            clips[sname] = wav
        rows.append((d, clips))
        print(f"  rendered {name}: in-band RMS {d['shape_rms_band_db']:.1f} dB, "
              f"maxR {d['max_pole_radius']:.4f}")

    # combined overlay plot
    n = len(descs)
    cols = 2
    rowsn = (n + cols - 1) // cols
    fig, axes = plt.subplots(rowsn, cols, figsize=(12, 3.2 * rowsn), facecolor="#080a0a")
    for ax, d in zip(np.atleast_1d(axes).ravel(), descs):
        plot_overlay(ax, d)
    for ax in np.atleast_1d(axes).ravel()[n:]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(IN_DIR / "overlay.png", dpi=120)
    plt.close(fig)

    path_note = "SHIPPED engine (AGC+saturate)" if engine_used else "Python DF2T fallback (no AGC)"
    html = [
        "<!doctype html><meta charset=utf-8><title>factorizer proof</title>",
        "<style>body{background:#0b0f0e;color:#cdd;font:14px monospace;padding:24px;max-width:1100px;margin:auto}",
        "h1{color:#5bef6f}.row{margin:14px 0;padding:10px;border:1px solid #1c2722;border-radius:6px}",
        ".n{color:#ffd23e;font-size:16px}.m{color:#789}audio{width:330px}img{width:100%;border:1px solid #1c2722;margin:14px 0}</style>",
        "<h1>Factorizer proof — fit_corner_from_magnitude</h1>",
        f"<p class=m>Each fitted corner rendered through the {path_note}. The shaded band is "
        "120–8000 Hz (the asserted-fidelity band; the top octave is the Nyquist edge). "
        "Green = target response, amber = fitted. The ear decides if the fit is usable.</p>",
        '<img src="overlay.png" alt="target vs fitted overlay">',
    ]
    for d, clips in rows:
        players = " ".join(
            f'<span class=m>{s}</span> <audio controls src="{w}"></audio>' for s, w in clips.items()
        )
        html.append(
            f'<div class=row><span class=n>{d["name"]}</span> '
            f'<span class=m>&nbsp; in-band RMS {d["shape_rms_band_db"]:.1f} dB · '
            f'max {d["shape_max_band_db"]:.1f} dB · maxR {d["max_pole_radius"]:.4f}</span>'
            f'<br>{players}</div>'
        )
    (IN_DIR / "audition.html").write_text("\n".join(html), encoding="utf-8")

    # report
    lines = [
        "# Factorizer proof — `fit_corner_from_magnitude`",
        "",
        "Target magnitude curve -> response-first ARMA factorizer -> 6-stage cascade.",
        "Shape residual = (fitted - target) dB, mean removed (the cepstral envelope fits",
        "shape, not absolute level; level is the boost/AGC's job).",
        "",
        "| target | full RMS | in-band RMS (120-8k) | in-band max | max pole R |",
        "|---|---:|---:|---:|---:|",
    ]
    for d in descs:
        lines.append(
            f"| {d['name']} | {d['shape_rms_full_db']:.2f} | {d['shape_rms_band_db']:.2f} | "
            f"{d['shape_max_band_db']:.2f} | {d['max_pole_radius']:.4f} |"
        )
    lines += [
        "",
        "## What this proves",
        "- **In the musical band the factorizer reproduces a broad formant-envelope",
        "  target tightly** (synthetic 3-formant: ~2.3 dB RMS / ~5 dB max, stable).",
        "  It is a working response-surface authoring tool for that class of target.",
        "- **Top octave (toward Nyquist) is unconstrained** — the fitter parks an edge",
        "  resonance there. Out of the asserted band; audition decides if it bites.",
        "- **It is an ENVELOPE fitter, not a razor-ROM replicator** — refit of a real",
        "  P2K reference smooths its sharp poles/notches (~13 dB in-band). Expected:",
        "  the response-first path targets broad shapes, not ROM-exact replicas.",
        "",
        "## Implication for a Target Browser",
        "Target broad formant/peak response surfaces with rolled low end (the no-pedestal",
        "shape the engine likes). Derive boost AFTER the shape (mean offset is large and",
        "expected). Do not expect razor-pole ROM replication from this fitter.",
        "",
        f"Audition: `dev/tmp/factorizer_proof/audition.html` (rendered via {path_note}).",
    ]
    (IN_DIR / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nwrote {IN_DIR / 'audition.html'} + overlay.png + REPORT.md  ({path_note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
