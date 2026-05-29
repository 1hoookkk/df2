#!/usr/bin/env python3
"""Teleport stress renderer: violent Morph/Q movement over a packed body.

This is the proof rig for the paradox: audio that sounds damaged while the
coefficient path stays deterministic and finite. It intentionally bypasses
host-parameter smoothing and drives the packed 4-corner surface directly.

Outputs:
  dev/tmp/teleport_stress/source.wav
  dev/tmp/teleport_stress/teleport_noise.wav
  dev/tmp/teleport_stress/teleport_square_150hz.wav
  dev/tmp/teleport_stress/teleport_derivative.wav
  dev/tmp/teleport_stress/teleport_stress.png
  dev/tmp/teleport_stress/audition.html
  dev/tmp/teleport_stress/report.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.packed_interp import (  # noqa: E402
    packed_bilinear,
    packed_probe,
    kernel_to_biquad,
    core_available,
    core_backend,
)

SR_DEFAULT = 44_100
AUTHORING_SR = 39_062.5
LABEL_TO_KEY = {
    "M0_Q0": "A",
    "M100_Q0": "B",
    "M0_Q100": "C",
    "M100_Q100": "D",
}
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
STAGES = 6
WORDS_PER_STAGE = 5
RAW_BYTES = len(CORNER_ORDER) * STAGES * WORDS_PER_STAGE * 2  # 240
RAW_SUFFIXES = (".body240", ".bin", ".bytes", ".raw")


def load_packed_body(path: Path) -> tuple[str, dict[str, list[tuple[int, ...]]]]:
    """Load corner words from either a raw 240-byte body or a compiled JSON.

    Both converge to the same A/B/C/D word bank: `packedWords` are the
    coefficient truth and the raw `.body240` file is the same words on disk, so
    the two render identically.
    """
    if path.suffix.lower() in RAW_SUFFIXES:
        return load_raw_body(path)
    return load_packed_cart(path)


def load_raw_body(path: Path) -> tuple[str, dict[str, list[tuple[int, ...]]]]:
    raw = path.read_bytes()
    if len(raw) != RAW_BYTES:
        raise SystemExit(f"{path}: raw body must be exactly {RAW_BYTES} bytes, got {len(raw)}")
    u16 = np.frombuffer(raw, dtype="<u2").reshape(len(CORNER_ORDER), STAGES, WORDS_PER_STAGE)
    out: dict[str, list[tuple[int, ...]]] = {}
    for ci, label in enumerate(CORNER_ORDER):
        out[LABEL_TO_KEY[label]] = [tuple(int(v) & 0xFFFF for v in row) for row in u16[ci]]
    return path.stem, out


def load_packed_cart(path: Path) -> tuple[str, dict[str, list[tuple[int, ...]]]]:
    cart = json.loads(path.read_text(encoding="utf-8"))
    sr = float(cart.get("authoring_sample_rate_hz", cart.get("sampleRate", AUTHORING_SR)))
    if abs(sr - AUTHORING_SR) > 1.0e-6:
        raise SystemExit(f"{path}: expected {AUTHORING_SR} Hz authoring rate, got {sr}")

    by_label: dict[str, Any] = {kf.get("label"): kf for kf in cart.get("keyframes", [])}
    missing = [label for label in CORNER_ORDER if label not in by_label]
    if missing:
        raise SystemExit(f"{path}: missing corner(s): {', '.join(missing)}")

    out: dict[str, list[tuple[int, ...]]] = {}
    for label in CORNER_ORDER:
        rows = by_label[label].get("packedWords")
        if not rows:
            raise SystemExit(f"{path}: {label} has no packedWords; teleport stress needs the 240-byte body")
        if len(rows) != 6 or any(len(row) != 5 for row in rows):
            raise SystemExit(f"{path}: {label}.packedWords must be 6 x 5")
        out[LABEL_TO_KEY[label]] = [tuple(int(v) & 0xFFFF for v in row) for row in rows]
    return str(cart.get("name") or path.stem), out


def source_signal(n: int, sr: int) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / sr
    saw55 = 2.0 * ((55.0 * t) % 1.0) - 1.0
    saw111 = 2.0 * ((111.3 * t) % 1.0) - 1.0
    tone = (
        0.26 * saw55
        + 0.18 * saw111
        + 0.12 * np.sin(2.0 * np.pi * 330.0 * t)
        + 0.08 * np.sin(2.0 * np.pi * 931.0 * t)
    )
    clicks = np.zeros(n, dtype=np.float64)
    step = max(1, sr // 11)
    clicks[::step] = 0.9
    click_env = np.exp(-np.arange(192) / 18.0)
    clicks = np.convolve(clicks, click_env, mode="same")
    rng = np.random.default_rng(0xDF2)
    noise = rng.standard_normal(n) * 0.015
    x = tone + clicks + noise
    return (0.45 * x / (np.max(np.abs(x)) + 1.0e-12)).astype(np.float64)


def drivers(mode: str, x: np.ndarray, sr: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(x)
    t = np.arange(n, dtype=np.float64) / sr
    if mode == "noise":
        rng = np.random.default_rng(seed)
        return rng.random(n), rng.random(n)
    if mode == "square_150hz":
        morph = (np.sin(2.0 * np.pi * 150.0 * t) >= 0.0).astype(np.float64)
        q = np.ones(n, dtype=np.float64)
        return morph, q
    if mode == "derivative":
        d = np.diff(x, prepend=x[0])
        scale = np.percentile(np.abs(d), 95) + 1.0e-12
        hot = np.tanh(d / scale)
        morph = 0.5 + 0.5 * hot
        q = 0.35 + 0.65 * np.minimum(1.0, np.abs(d) / (scale * 1.25))
        return morph, q
    raise ValueError(mode)


def static_probe(corners: dict[str, list[tuple[int, ...]]],
                 morph: np.ndarray, q: np.ndarray) -> dict[str, Any]:
    """Sample the morph/Q surface and return stability diagnostics.

    Delegates to trench-core's trench_packed_probe via packed_probe — no local
    kernel_to_biquad or pole_radius. Results are identical to what the runtime
    computes: same interpolation, same biquad conversion, same pole math.
    """
    idx = np.linspace(0, len(morph) - 1, min(1024, len(morph))).astype(int)
    max_abs_coeff = 0.0
    max_pole_radius = 0.0
    nonfinite_coeffs = 0
    unstable_rows = 0
    for i in idx:
        probe = packed_probe(corners, float(morph[i]), float(q[i]))
        for si, bq in enumerate(probe["biquad"]):
            if (probe["nonfinite_mask"] >> si) & 1:
                nonfinite_coeffs += 1
                continue
            max_abs_coeff = max(max_abs_coeff, max(abs(v) for v in bq))
        max_pole_radius = max(max_pole_radius, probe["max_pole_radius"])
        unstable_rows += bin(probe["unstable_mask"]).count("1")
    return {
        "probe_points": int(len(idx)),
        "nonfinite_coeff_rows": int(nonfinite_coeffs),
        "unstable_denominator_rows": int(unstable_rows),
        "max_abs_direct_coeff": max_abs_coeff,
        "max_pole_radius": max_pole_radius,
    }


def dc_block(samples: np.ndarray, sr: int) -> np.ndarray:
    r = 1.0 - (2.0 * np.pi * 18.0 / sr)
    y = np.empty_like(samples)
    xm1 = 0.0
    ym1 = 0.0
    for i, x in enumerate(samples):
        v = x - xm1 + r * ym1
        y[i] = v
        xm1 = x
        ym1 = v
    return y


def process_teleport(corners: dict[str, list[tuple[int, ...]]],
                     x: np.ndarray,
                     morph: np.ndarray,
                     q: np.ndarray,
                     sr: int,
                     containment_drive: float) -> tuple[np.ndarray, dict[str, Any]]:
    states = np.zeros((6, 2), dtype=np.float64)
    raw = np.zeros_like(x)
    nonfinite_events = 0
    peak_internal = 0.0
    started = time.perf_counter()

    for i, s in enumerate(x):
        rows = packed_bilinear(corners, float(morph[i]), float(q[i]))
        v = float(s)
        for si, row in enumerate(rows):
            b0, b1, b2, a1, a2 = kernel_to_biquad(row)
            y = b0 * v + states[si, 0]
            w1 = b1 * v - a1 * y + states[si, 1]
            w2 = b2 * v - a2 * y
            if not (math.isfinite(y) and math.isfinite(w1) and math.isfinite(w2)):
                y = 0.0
                w1 = 0.0
                w2 = 0.0
                nonfinite_events += 1
            states[si, 0] = w1
            states[si, 1] = w2
            v = y
        peak_internal = max(peak_internal, abs(v))
        raw[i] = v if math.isfinite(v) else 0.0

    elapsed = time.perf_counter() - started
    # Runtime-style final safety: DC block into hard musical containment.
    wet = dc_block(raw, sr)
    wet = np.tanh(wet * containment_drive)
    peak = float(np.max(np.abs(wet)) + 1.0e-12)
    if peak > 0.98:
        wet *= 0.98 / peak

    report = {
        "samples": int(len(x)),
        "seconds_render_cpu": elapsed,
        "nonfinite_state_events": int(nonfinite_events),
        "raw_peak_before_saturation": float(peak_internal),
        "containment_drive": float(containment_drive),
        "output_peak": float(np.max(np.abs(wet))),
        "output_rms": float(np.sqrt(np.mean(wet * wet))),
        "output_dc": float(np.mean(wet)),
    }
    return wet.astype(np.float32), report


def moving_rms(x: np.ndarray, window: int) -> np.ndarray:
    window = max(8, int(window))
    kernel = np.ones(window, dtype=np.float64) / window
    return np.sqrt(np.convolve(x.astype(np.float64) ** 2, kernel, mode="same"))


def write_plot(out: Path, sr: int, dry: np.ndarray,
               results: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]) -> None:
    fig, axes = plt.subplots(3, 3, figsize=(15, 9), facecolor="#080a0a")
    for row_i, (mode, (wet, morph, q)) in enumerate(results.items()):
        t = np.arange(len(wet)) / sr
        view = slice(0, min(len(wet), sr // 3))
        ax = axes[row_i, 0]
        ax.plot(t[view], dry[view], color="#4aa3ff", lw=0.7, alpha=0.55)
        ax.plot(t[view], wet[view], color="#f4f1ff", lw=0.8)
        ax.set_title(f"{mode}: audio", color="#eaeaea", fontsize=9)

        ax = axes[row_i, 1]
        ax.plot(t[view], morph[view], color="#f0c34a", lw=0.8, label="Morph")
        ax.plot(t[view], q[view], color="#ec5f67", lw=0.8, label="Q")
        ax.set_ylim(-0.05, 1.05)
        ax.set_title("coordinates", color="#eaeaea", fontsize=9)

        ax = axes[row_i, 2]
        env = np.abs(wet)
        rms = moving_rms(wet, sr // 250)
        ax.plot(t[view], env[view], color="#ff5f6d", lw=0.75, alpha=0.75, label="abs")
        ax.plot(t[view], -env[view], color="#ff5f6d", lw=0.75, alpha=0.75)
        ax.plot(t[view], rms[view], color="#f9d65c", lw=1.0, label="rms")
        ax.plot(t[view], -rms[view], color="#f9d65c", lw=1.0)
        ax.set_ylim(-1.05, 1.05)
        ax.set_title("amplitude envelope", color="#eaeaea", fontsize=9)

    for ax in axes.flat:
        ax.set_facecolor("#0b0f0e")
        ax.tick_params(colors="#8a8a8a", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#333")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def write_audition_html(out: Path, report: dict[str, Any]) -> None:
    modes = [
        ("teleport_noise.wav", "Noise Teleport", "random Morph/Q every sample"),
        ("teleport_square_150hz.wav", "150 Hz Strobe", "hard Morph square wave, Q pinned hot"),
        ("teleport_derivative.wav", "Derivative Rip", "input slope drives Morph/Q"),
    ]
    rows = []
    for wav, title, desc in modes:
        key = wav.removeprefix("teleport_").removesuffix(".wav")
        dyn = report["modes"][key]["dynamic"]
        stat = report["modes"][key]["static_probe"]
        rows.append(f"""
        <section class="row">
          <div>
            <h2>{title}</h2>
            <p>{desc}</p>
            <audio controls preload="metadata" src="{wav}"></audio>
          </div>
          <dl>
            <dt>nonfinite</dt><dd>{dyn["nonfinite_state_events"]}</dd>
            <dt>peak</dt><dd>{dyn["output_peak"]:.3f}</dd>
            <dt>rms</dt><dd>{dyn["output_rms"]:.3f}</dd>
            <dt>max pole r</dt><dd>{stat["max_pole_radius"]:.6f}</dd>
          </dl>
        </section>""")
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Teleport Stress Audition</title>
<style>
  body{{margin:0;background:#090b0b;color:#ece9df;font:14px/1.4 system-ui,Segoe UI,sans-serif}}
  main{{max-width:980px;margin:0 auto;padding:28px 20px 42px}}
  h1{{font-size:24px;margin:0 0 8px}}
  h2{{font-size:18px;margin:0 0 4px}}
  p{{margin:0 0 12px;color:#a9aaa3}}
  img{{display:block;width:100%;border:1px solid #2a2d2b;background:#111;margin:18px 0 24px}}
  .row{{display:grid;grid-template-columns:1fr 260px;gap:18px;align-items:center;border-top:1px solid #252927;padding:18px 0}}
  audio{{width:100%}}
  dl{{display:grid;grid-template-columns:1fr 1fr;gap:7px 12px;margin:0;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}}
  dt{{color:#888}}
  dd{{margin:0;text-align:right;color:#f6d76b}}
</style>
<main>
  <h1>Teleport Stress Audition</h1>
  <p>{report["doctrine"]}. These files are amplitude first: listen, then check the zero-failure counters.</p>
  <audio controls preload="metadata" src="source.wav"></audio>
  <img src="teleport_stress.png" alt="waveform and amplitude envelope stress plot">
  {''.join(rows)}
</main>
"""
    out.write_text(html, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", type=Path, default=ROOT / "bodies" / "neon_vane.cart.json",
                    help="compiled-v1 JSON with packedWords, or a raw 240-byte .body240 file")
    ap.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "teleport_stress")
    ap.add_argument("--seconds", type=float, default=1.25)
    ap.add_argument("--sr", type=int, default=SR_DEFAULT)
    ap.add_argument("--seed", type=int, default=0x513DF2)
    ap.add_argument("--containment-drive", type=float, default=4.0)
    ap.add_argument("--require-core", action="store_true",
                    help="fail unless packed math runs through the shipped trench-core (FFI)")
    args = ap.parse_args()

    if args.require_core and not core_available():
        print(
            f"teleport_stress error: trench-core FFI not available (backend={core_backend()}); "
            "build it with `cargo build -p trench-core`",
            file=sys.stderr,
        )
        return 1
    print(f"interp   -> {core_backend()}")

    name, corners = load_packed_body(args.body)
    n = int(round(args.seconds * args.sr))
    dry = source_signal(n, args.sr)
    args.out.mkdir(parents=True, exist_ok=True)
    wavfile.write(args.out / "source.wav", args.sr, dry.astype(np.float32))

    report: dict[str, Any] = {
        "body": name,
        "body_path": str(args.body),
        "sample_rate": args.sr,
        "seconds": args.seconds,
        "doctrine": "packedWords are authoritative; Morph/Q are direct address lines",
        "modes": {},
    }
    rendered: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for mode in ("noise", "square_150hz", "derivative"):
        morph, q = drivers(mode, dry, args.sr, args.seed)
        static = static_probe(corners, morph, q)
        wet, dynamic = process_teleport(corners, dry, morph, q, args.sr, args.containment_drive)
        stem = f"teleport_{mode}"
        wavfile.write(args.out / f"{stem}.wav", args.sr, wet)
        report["modes"][mode] = {"static_probe": static, "dynamic": dynamic}
        rendered[mode] = (wet, morph, q)

    write_plot(args.out / "teleport_stress.png", args.sr, dry, rendered)
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_audition_html(args.out / "audition.html", report)

    print(f"wrote {args.out}")
    for mode, info in report["modes"].items():
        dyn = info["dynamic"]
        stat = info["static_probe"]
        print(
            f"{mode}: nonfinite={dyn['nonfinite_state_events']} "
            f"peak={dyn['output_peak']:.3f} rms={dyn['output_rms']:.3f} "
            f"max_r={stat['max_pole_radius']:.6f} unstable_rows={stat['unstable_denominator_rows']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
