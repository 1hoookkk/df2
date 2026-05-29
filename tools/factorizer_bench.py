#!/usr/bin/env python3
"""factorizer_bench — the scoreboard for tuning the response-first factorizer.

The anti-slop rule made runnable: nothing changes the fitter unless a NUMBER moves
on a FROZEN battery AND the ear signs off. This is the number.

One command: for each target in `tools/factorizer_battery.json` it
  builds the (frozen, deterministically-sampled) target curve
  -> fits it through the SHIPPED Rust factorizer (trench_ffi)
  -> packs to a 240-byte body and measures the SHIPPED (packed-decoded) response
  -> in-band shape residual (mean removed) + max pole radius (stability)
  -> renders SAW/TONE/PINK through the shipped engine for the ear,
then prints a scoreboard with the DELTA vs the previous run (so you can see
instantly whether a fitter change helped or hurt), writes audition.html +
overlay.png, and appends to history.

  python tools/factorizer_bench.py
  python tools/factorizer_bench.py --reset-baseline   # forget the previous run

Headline = mean in-band RMS over the 'primary' (broad-shape) targets. Drive it
down. 'boundary' targets (tilt, ref-derived) are tracked but never scored.
"""
from __future__ import annotations

import argparse
import json
import math
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
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from pyruntime.packed_interp import coeffs_to_words, words_to_coeffs

BATTERY = ROOT / "tools" / "factorizer_battery.json"
OUT = ROOT / "dev" / "tmp" / "factorizer_bench"
RENDER_SR = 44100


# ── frozen target curves ─────────────────────────────────────────────────────

def build_target(spec: dict, freqs: np.ndarray) -> np.ndarray:
    if spec.get("ref_bin"):
        raw = (ROOT / spec["ref_bin"]).read_bytes()
        u16 = np.frombuffer(raw, dtype="<u2").reshape(4, 6, 5)
        enc = [EncodedCoeffs(*words_to_coeffs(tuple(int(v) for v in u16[0, s]))) for s in range(6)]
        return cascade_response_db(enc, freqs, spec.get("sr", 39062.5))
    db = np.full_like(freqs, float(spec.get("floor_db", 0.0)))
    for fc, g, w in spec.get("bumps", []):
        db += g * np.exp(-((np.log2(freqs / fc) / w) ** 2))
    for fc, d, w in spec.get("dips", []):
        db -= d * np.exp(-((np.log2(freqs / fc) / w) ** 2))
    if spec.get("tilt"):
        corner, slope = spec["tilt"]
        db = np.where(freqs <= corner, db, db + slope * np.log2(np.maximum(freqs, corner) / corner))
    return db


def body_bytes(rows) -> bytes:
    """4 identical corners (static morph of the one fitted corner) -> 240 bytes."""
    words = [coeffs_to_words(*r) for r in rows]
    flat = []
    for _ in range(4):
        for w in words:
            flat.extend(int(x) & 0xFFFF for x in w)
    return struct.pack("<" + "H" * 120, *flat)


# ── sources for the ear ──────────────────────────────────────────────────────

def _env(n, dur):
    t = np.arange(n) / RENDER_SR
    return np.minimum(1.0, 8.0 * t) * np.exp(-t / (dur * 0.85))


def src_saw(dur=1.1, f0=110.0):
    n = int(RENDER_SR * dur); t = np.arange(n) / RENDER_SR
    return (2.0 * ((f0 * t) % 1.0) - 1.0) * _env(n, dur) * 0.6


def src_tone(dur=1.1, f0=220.0):
    n = int(RENDER_SR * dur); t = np.arange(n) / RENDER_SR
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3, 4))
    return x * _env(n, dur) * 0.4


def src_pink(dur=1.1, seed=0xF17):
    n = int(RENDER_SR * dur)
    spec = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    f = np.arange(spec.size); spec[1:] /= np.sqrt(f[1:])
    x = np.fft.irfft(spec, n)
    return (x / (np.max(np.abs(x)) + 1e-9)) * 0.6


SOURCES = {"saw": src_saw(), "tone": src_tone(), "pink": src_pink()}


def render(body: bytes, src: np.ndarray):
    out = trench_ffi.engine_render(body, 0.0, 0.0, src.astype(np.float32).tobytes(), RENDER_SR)
    wet = np.frombuffer(out, dtype=np.float32).astype(np.float64)
    pk = np.max(np.abs(wet))
    return wet / pk * 0.9 if pk > 1e-9 else wet


def write_wav(path: Path, x: np.ndarray):
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RENDER_SR)
        w.writeframes(pcm.tobytes())


def shape_stats(target, fitted, freqs, lo, hi):
    m = (freqs >= lo) & (freqs <= hi)
    r = fitted[m] - target[m]
    r = r - r.mean()
    return float(np.sqrt((r * r).mean())), float(np.abs(r).max())


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-baseline", action="store_true",
                    help="discard the previous run's scoreboard before comparing")
    args = ap.parse_args()

    if not trench_ffi.available():
        print("trench-core not built. Run: cargo build --release -p trench-core", file=sys.stderr)
        return 1

    bat = json.loads(BATTERY.read_text(encoding="utf-8"))
    sr = float(bat["sample_rate_hz"])
    band_lo, band_hi = bat["band_hz"]
    fit_freqs = np.logspace(math.log10(bat["sample_lo_hz"]), math.log10(bat["sample_hi_hz"]),
                            bat["sample_points"])
    eval_freqs = np.logspace(math.log10(bat["sample_lo_hz"]), math.log10(bat["sample_hi_hz"]), 256)

    OUT.mkdir(parents=True, exist_ok=True)
    prev = {}
    sb_path = OUT / "scoreboard.json"
    if sb_path.exists() and not args.reset_baseline:
        prev = {r["name"]: r for r in json.loads(sb_path.read_text())["targets"]}

    results = []
    for spec in bat["targets"]:
        name = spec["name"]
        tgt_fit = build_target(spec, fit_freqs)
        rows = trench_ffi.fit_corner_from_magnitude(list(zip(fit_freqs.tolist(), tgt_fit.tolist())), sr)
        body = body_bytes(rows)
        # SHIPPED (packed-decoded) response — what you actually hear
        shipped = trench_ffi.packed_interpolate(body, 0.0, 0.0)
        fitted = cascade_response_db([EncodedCoeffs(*c) for c in shipped], eval_freqs, sr)
        tgt_eval = build_target(spec, eval_freqs)
        rms, mx = shape_stats(tgt_eval, fitted, eval_freqs, band_lo, band_hi)
        probe = trench_ffi.packed_probe(body, 0.0, 0.0)
        maxr = probe["max_pole_radius"]

        clips = {}
        for sname, src in SOURCES.items():
            wav = f"{name}__{sname}.wav"
            write_wav(OUT / wav, render(body, src))
            clips[sname] = wav

        results.append({
            "name": name, "kind": spec.get("kind", "primary"),
            "in_band_rms_db": round(rms, 3), "in_band_max_db": round(mx, 3),
            "max_pole_radius": round(maxr, 5), "stable": maxr < 1.0,
            "freqs": eval_freqs.tolist(), "target_db": tgt_eval.tolist(),
            "fitted_db": fitted.tolist(), "clips": clips,
        })

    primary = [r for r in results if r["kind"] == "primary"]
    headline = float(np.mean([r["in_band_rms_db"] for r in primary]))
    prev_headline = None
    if prev:
        pv = [prev[r["name"]]["in_band_rms_db"] for r in primary if r["name"] in prev]
        if pv:
            prev_headline = float(np.mean(pv))

    # ── console scoreboard ──
    def delta(name, val):
        if name in prev:
            d = val - prev[name]["in_band_rms_db"]
            return f"{d:+.2f}" + ("  better" if d < -0.05 else "  worse" if d > 0.05 else "  =")
        return "   (new)"

    print(f"\n{'target':<20} {'kind':<9} {'RMS(dB)':>8} {'d vs prev':>14} {'max(dB)':>8} {'poleR':>8}")
    print("-" * 74)
    for r in results:
        print(f"{r['name']:<20} {r['kind']:<9} {r['in_band_rms_db']:>8.2f} {delta(r['name'], r['in_band_rms_db']):>14} "
              f"{r['in_band_max_db']:>8.2f} {r['max_pole_radius']:>8.4f}"
              + ("" if r["stable"] else "  UNSTABLE!"))
    hd = f"{headline:.3f} dB"
    if prev_headline is not None:
        d = headline - prev_headline
        hd += f"   (prev {prev_headline:.3f}, {d:+.3f} {'BETTER' if d < -0.01 else 'WORSE' if d > 0.01 else 'flat'})"
    print("-" * 74)
    print(f"HEADLINE  mean in-band RMS over {len(primary)} primary targets:  {hd}")

    # ── artifacts ──
    n = len(results); cols = 2; rowsn = (n + cols - 1) // cols
    fig, axes = plt.subplots(rowsn, cols, figsize=(12, 3.0 * rowsn), facecolor="#080a0a")
    for ax, r in zip(np.atleast_1d(axes).ravel(), results):
        f = np.array(r["freqs"])
        ax.axvspan(band_lo, band_hi, color="#1d2a24", zorder=0)
        ax.semilogx(f, r["target_db"], color="#5bef6f", lw=1.6, label="target")
        ax.semilogx(f, r["fitted_db"], color="#ffb13e", lw=1.3, label="shipped fit")
        ax.set_xlim(40, 16000)
        ax.set_title(f"{r['name']} [{r['kind']}]  RMS {r['in_band_rms_db']:.1f}dB  R {r['max_pole_radius']:.4f}",
                     color="#cdd", fontsize=9)
        ax.tick_params(colors="#889", labelsize=7); ax.set_facecolor("#0b0f0e")
        for s in ax.spines.values():
            s.set_color("#26302b")
        ax.legend(fontsize=7, labelcolor="#cdd", loc="lower left")
    for ax in np.atleast_1d(axes).ravel()[n:]:
        ax.axis("off")
    fig.tight_layout(); fig.savefig(OUT / "overlay.png", dpi=120); plt.close(fig)

    html = [
        "<!doctype html><meta charset=utf-8><title>factorizer bench</title>",
        "<style>body{background:#0b0f0e;color:#cdd;font:14px monospace;padding:24px;max-width:1100px;margin:auto}",
        "h1{color:#5bef6f}.row{margin:12px 0;padding:10px;border:1px solid #1c2722;border-radius:6px}",
        ".n{color:#ffd23e;font-size:15px}.m{color:#789}.b{color:#789}audio{width:300px}img{width:100%;border:1px solid #1c2722;margin:12px 0}</style>",
        "<h1>Factorizer bench</h1>",
        f"<p class=m>HEADLINE mean in-band RMS (primary targets): <b style='color:#5bef6f'>{headline:.2f} dB</b>. "
        "Shaded = 120-8000 Hz. Green = frozen target, amber = shipped (packed) fit. "
        "Drive the headline down; the ear gates each clip.</p>",
        '<img src="overlay.png">',
    ]
    for r in results:
        players = " ".join(f'<span class=m>{s}</span> <audio controls src="{w}"></audio>'
                           for s, w in r["clips"].items())
        html.append(
            f'<div class=row><span class=n>{r["name"]}</span> <span class=b>[{r["kind"]}]</span>'
            f'<span class=m>&nbsp; RMS {r["in_band_rms_db"]:.1f} dB · max {r["in_band_max_db"]:.1f} dB · '
            f'poleR {r["max_pole_radius"]:.4f}{"" if r["stable"] else " UNSTABLE"}</span><br>{players}</div>'
        )
    (OUT / "audition.html").write_text("\n".join(html), encoding="utf-8")

    # scoreboard.json (latest) + history
    stamp = datetime.now(timezone.utc).isoformat()
    slim = [{k: r[k] for k in ("name", "kind", "in_band_rms_db", "in_band_max_db", "max_pole_radius", "stable")}
            for r in results]
    sb_path.write_text(json.dumps({"generated_utc": stamp, "headline_rms_db": round(headline, 3),
                                   "targets": slim}, indent=2), encoding="utf-8")
    with (OUT / "history.jsonl").open("a", encoding="utf-8") as h:
        h.write(json.dumps({"utc": stamp, "headline_rms_db": round(headline, 3),
                            "per_target": {r["name"]: r["in_band_rms_db"] for r in results}}) + "\n")

    print(f"\nwrote {OUT}\\audition.html  +  overlay.png  +  scoreboard.json  (history appended)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
