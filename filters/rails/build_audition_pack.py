#!/usr/bin/env python3
"""Build the TRENCH audition pack — Part 1 of the 2026-07-03 audition sprint.

Candidates: ship_iron_mouth, ship_riot_plate (locked ship bodies) + fuzzi_face_01..08.
Every body is rendered through the SHIPPED engine path (trench_ffi.engine_render_slam:
Mackie SLAM input stage -> packed z-plane cascade -> AGC) on 5 materials x 5 sweep
programs (slow+fast Morph, slow+fast Q — the never-live axis — and the diagonal).
Beside every wav: packed-runtime response PNG + dense Morph x Q interior heatmap.
One folder + contact sheet + index.html player.

References df2's kernel in place (sys.path); no kernel code is copied here.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import sys
import wave
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DF2 = Path(r"C:\Users\hooki\df2")
if str(DF2) not in sys.path:
    sys.path.insert(0, str(DF2))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402
from src.utils.body240 import AUTHORING_SR  # noqa: E402

TAU = 2.0 * math.pi
BLOCK = 512
PLOT_FREQS = freq_points(900)
GRID_FREQS = freq_points(360)
GRID_N = 33
STAMP = date.today().isoformat()

LOCKED = DF2 / "dev" / "tmp" / "exhausted_shipping_filters_locked"
FUZZI = DF2 / "dev" / "tmp" / "fuzzi_face"
OUT = Path(r"C:\Users\hooki\trench-filters\out\audition_pack")

BODIES = [
    ("ship_iron_mouth", LOCKED / "ship_iron_mouth" / "ship_iron_mouth.body240",
     "vowel / DVTD rails — corridor PASS, copy-risk 15.4 dB clear (P2k_013)"),
    ("ship_riot_plate", LOCKED / "ship_riot_plate" / "ship_riot_plate.body240",
     "modal / three-layer forge — corridor PASS, copy-risk 15.0 dB clear (P2k_028)"),
] + [
    (f"fuzzi_face_{i:02d}", FUZZI / f"fuzzi_face_{i:02d}.body240",
     "fuzz batch, lineage UNKNOWN — corridor PASS, copy-risk 35-39 dB clear (P2k_015)")
    for i in range(1, 9)
]

# (name, seconds, slam_drive) — drives follow the locked-harness conventions
MATERIALS = [
    ("pink", 5.0, 0.50),
    ("drums", 4.0, 0.58),
    ("bass", 4.0, 0.55),
    ("vocal", 4.0, 0.52),
    ("fullmix", 4.0, 0.52),
]

FAST_HZ = 2.0  # fast sweep = 0->1->0 triangle each 0.5 s (wheel-flick territory)


# ---------------------------------------------------------------- materials
def pink_noise(seconds: float = 5.0, seed: int = 20260630) -> np.ndarray:
    n = int(seconds * AUTHORING_SR)
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / AUTHORING_SR)
    scale = np.ones_like(freqs)
    scale[1:] = 1.0 / np.sqrt(freqs[1:])
    y = np.fft.irfft(spec * scale, n)
    y -= float(np.mean(y))
    y *= 0.34 / max(float(np.max(np.abs(y))), 1e-12)
    return y.astype(np.float64)


def drum_source(seconds: float = 4.0) -> np.ndarray:
    n = int(seconds * AUTHORING_SR)
    audio = np.zeros(n, dtype=np.float64)
    beat = 0.5
    for k in range(int(seconds / beat) + 1):
        start = int(k * beat * AUTHORING_SR)
        length = min(n - start, int(0.18 * AUTHORING_SR))
        if length <= 0:
            continue
        env = np.exp(-np.linspace(0.0, 7.0, length))
        freq = 95.0 * np.exp(-np.linspace(0.0, 2.4, length)) + 38.0
        phase = np.cumsum(TAU * freq / AUTHORING_SR)
        audio[start:start + length] += 0.65 * np.sin(phase) * env
    for k in range(1, int(seconds / beat) + 1, 2):
        start = int(k * beat * AUTHORING_SR)
        length = min(n - start, int(0.13 * AUTHORING_SR))
        if length <= 0:
            continue
        idx = np.arange(length)
        env = np.exp(-idx / (0.035 * AUTHORING_SR))
        tone = np.sin(TAU * 1850.0 * idx / AUTHORING_SR) + 0.45 * np.sin(TAU * 2650.0 * idx / AUTHORING_SR)
        audio[start:start + length] += 0.34 * tone * env
    hat_len = int(0.045 * AUTHORING_SR)
    for k in range(int(seconds / 0.125)):
        start = int(k * 0.125 * AUTHORING_SR)
        length = min(n - start, hat_len)
        if length <= 0:
            continue
        idx = np.arange(length)
        env = np.exp(-idx / (0.012 * AUTHORING_SR))
        hat = np.sin(TAU * 7300.0 * idx / AUTHORING_SR) + 0.5 * np.sin(TAU * 10400.0 * idx / AUTHORING_SR)
        audio[start:start + length] += 0.055 * hat * env
    return np.clip(audio, -0.92, 0.92)


def program_source(seconds: float = 4.0) -> np.ndarray:
    n = int(seconds * AUTHORING_SR)
    t = np.arange(n) / AUTHORING_SR
    audio = np.zeros(n, dtype=np.float64)
    for idx, f0 in enumerate((82.41, 123.47, 164.81, 246.94)):
        phase = TAU * f0 * (1.0 + (idx - 1.5) * 0.004) * t
        saw = np.zeros(n, dtype=np.float64)
        for h in range(1, 35):
            saw += np.sin(phase * h) / h
        audio += saw / 4.0
    gate = 0.58 + 0.42 * (np.sin(TAU * 0.5 * t) > -0.2)
    audio *= gate
    audio *= 0.26 / max(float(np.max(np.abs(audio))), 1e-12)
    return audio


def bass_source(seconds: float = 4.0) -> np.ndarray:
    n = int(seconds * AUTHORING_SR)
    audio = np.zeros(n, dtype=np.float64)
    riff = [41.20, 41.20, 49.00, 41.20, 55.00, 41.20, 65.41, 49.00]  # E1 G1 A1 C2 figure
    note = seconds / len(riff)
    for k, f0 in enumerate(riff):
        start = int(k * note * AUTHORING_SR)
        length = min(n - start, int(note * 0.92 * AUTHORING_SR))
        if length <= 0:
            continue
        idx = np.arange(length)
        t = idx / AUTHORING_SR
        env = np.minimum(1.0, idx / (0.004 * AUTHORING_SR)) * np.exp(-t / (note * 0.55))
        sub = np.sin(TAU * f0 * t)
        saw = np.zeros(length, dtype=np.float64)
        for h in range(1, 21):
            saw += np.sin(TAU * f0 * h * t) / h
        audio[start:start + length] += (0.62 * sub + 0.38 * saw / 2.4) * env
    audio *= 0.50 / max(float(np.max(np.abs(audio))), 1e-12)
    return audio


def vocal_source(seconds: float = 4.0) -> np.ndarray:
    """Glottal-pulse phrase source: pitch contour + vibrato, -6 dB/oct-ish harmonic
    rolloff, phrase gating. Deliberately formant-free so the body supplies ALL of
    the vowel — the talkbox-carrier way to audition a vowel/formant filter."""
    n = int(seconds * AUTHORING_SR)
    t = np.arange(n) / AUTHORING_SR
    f0 = 116.0 * (2.0 ** (0.35 * np.sin(TAU * 0.22 * t)))  # slow contour ~93..145 Hz
    f0 *= 1.0 + 0.022 * np.sin(TAU * 5.4 * t)               # vibrato
    phase = np.cumsum(TAU * f0 / AUTHORING_SR)
    audio = np.zeros(n, dtype=np.float64)
    for h in range(1, 26):
        audio += np.sin(phase * h) / (h ** 1.25)
    phrase = np.zeros(n, dtype=np.float64)
    for (a, b) in ((0.05, 0.9), (1.05, 1.85), (2.1, 3.1), (3.3, 3.9)):
        i0, i1 = int(a * AUTHORING_SR), min(n, int(b * AUTHORING_SR))
        if i1 <= i0:
            continue
        length = i1 - i0
        idx = np.arange(length)
        att = np.minimum(1.0, idx / (0.03 * AUTHORING_SR))
        rel = np.minimum(1.0, (length - 1 - idx) / (0.08 * AUTHORING_SR))
        phrase[i0:i1] = np.maximum(phrase[i0:i1], att * rel)
    audio *= phrase
    audio *= 0.42 / max(float(np.max(np.abs(audio))), 1e-12)
    return audio


def fullmix_source(seconds: float = 4.0) -> np.ndarray:
    mix = 0.85 * drum_source(seconds) + 0.65 * bass_source(seconds) + 0.55 * program_source(seconds)
    mix *= 0.55 / max(float(np.max(np.abs(mix))), 1e-12)
    return mix


# ---------------------------------------------------------------- engine io
def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    y = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(round(AUTHORING_SR)))
        handle.writeframes((y * 32767.0).astype("<i2").tobytes())


def render_slam(body: bytes, source: np.ndarray, morph: list[float], q: list[float], slam: float) -> np.ndarray:
    out = trench_ffi.engine_render_slam(
        body,
        morph,
        q,
        source.astype("<f4").tobytes(),
        slam_drive=slam,
        agc_enabled=True,
        agc_drive=trench_ffi.MUSICAL_AGC_DRIVE,
    )
    return np.frombuffer(out, dtype="<f4").astype(np.float64)


def triangle(nb: int, seconds: float, rate_hz: float = FAST_HZ) -> list[float]:
    t = (np.arange(nb) + 0.5) * (seconds / nb)
    ph = (t * rate_hz) % 1.0
    return (1.0 - np.abs(2.0 * ph - 1.0)).tolist()


def programs(nb: int, seconds: float) -> list[tuple[str, list[float], list[float], str]]:
    up = np.linspace(0.0, 1.0, nb).tolist()
    tri = triangle(nb, seconds)
    hold_m = [0.5] * nb
    return [
        ("morph_slow_q0", up, [0.0] * nb, "Morph 0->1 over clip @ Q0"),
        ("morph_fast_q0", tri, [0.0] * nb, f"Morph 0->1->0 triangle {FAST_HZ:g} Hz @ Q0"),
        ("q_slow_m50", hold_m, up, "Q 0->1 over clip @ M50 — never-live axis"),
        ("q_fast_m50", hold_m, tri, f"Q 0->1->0 triangle {FAST_HZ:g} Hz @ M50 — THE novel test"),
        ("diagonal", up, up, "Morph & Q 0->1 together"),
    ]


# ---------------------------------------------------------------- analysis
def response_at(body: bytes, morph: float, q: float, freqs: np.ndarray) -> np.ndarray:
    rows = [EncodedCoeffs(*row) for row in trench_ffi.packed_interpolate(body, morph, q)]
    return cascade_response_db(rows, freqs, AUTHORING_SR)


def pole_radius_max(body: bytes, morph: float, q: float) -> float:
    rows = trench_ffi.packed_interpolate(body, morph, q)
    worst = 0.0
    for row in rows:
        c0, c1, c2, c3, c4 = row
        a1 = c2 - 2.0
        a2 = 1.0 - c3
        roots = np.roots([1.0, a1, a2])
        worst = max(worst, float(np.max(np.abs(roots))))
    return worst


def wrap_scan(body: bytes) -> dict:
    words = np.frombuffer(body, dtype="<u2").astype(np.int64).reshape(4, 30)
    edges = {"C0-C1_morph_q0": (0, 1), "C2-C3_morph_q100": (2, 3),
             "C0-C2_q_m0": (0, 2), "C1-C3_q_m100": (1, 3)}
    out = {}
    for name, (a, b) in edges.items():
        delta = np.abs(words[b] - words[a])
        out[name] = {"max_abs_dw": int(delta.max()), "n_over_32767": int(np.sum(delta > 32767))}
    out["any_wrap_risk"] = bool(any(v["n_over_32767"] for k, v in out.items() if isinstance(v, dict)))
    return out


def interior_grid(body: bytes) -> dict:
    ms = np.linspace(0.0, 1.0, GRID_N)
    qs = np.linspace(0.0, 1.0, GRID_N)
    peak = np.zeros((GRID_N, GRID_N))
    peak_hz = np.zeros((GRID_N, GRID_N))
    maxr = 0.0
    nonfinite = 0
    for j, q in enumerate(qs):
        for i, m in enumerate(ms):
            y = response_at(body, float(m), float(q), GRID_FREQS)
            if not np.all(np.isfinite(y)):
                nonfinite += 1
                y = np.nan_to_num(y, nan=-120.0, posinf=120.0, neginf=-120.0)
            peak[j, i] = float(np.max(y))
            peak_hz[j, i] = float(GRID_FREQS[int(np.argmax(y))])
            maxr = max(maxr, pole_radius_max(body, float(m), float(q)))
    return {"peak_db": peak, "peak_hz": peak_hz, "grid_max_pole_r": maxr,
            "nonfinite_cells": nonfinite}


# ---------------------------------------------------------------- figures
DARK = {"face": "#070908", "panel": "#0c100e", "grid": "#26352e", "tick": "#a8b5ad",
        "spine": "#2e3d35", "text": "#edf3ee"}
STATE_COLORS = {"LOW.Q0": "#e6d7a7", "HIGH.Q0": "#63d7ff", "LOW.Q100": "#ff8b6b",
                "HIGH.Q100": "#af9cff", "MID.Q50": "#96e6bf", "MID.Q100": "#ff5f7e"}
STATES = [("LOW.Q0", 0.0, 0.0), ("HIGH.Q0", 1.0, 0.0), ("LOW.Q100", 0.0, 1.0),
          ("HIGH.Q100", 1.0, 1.0), ("MID.Q50", 0.5, 0.5), ("MID.Q100", 0.5, 1.0)]


def style_ax(ax):
    ax.set_facecolor(DARK["panel"])
    ax.grid(True, which="both", color=DARK["grid"], alpha=0.36, linewidth=0.55)
    ax.tick_params(colors=DARK["tick"], labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(DARK["spine"])


def footer(fig, body_path: Path):
    fig.text(0.01, 0.005,
             f"{body_path} · packed runtime: trench_ffi.packed_interpolate -> cascade_response_db @ {AUTHORING_SR:.1f} Hz · {STAMP}",
             color="#6f7f75", fontsize=7)


def plot_response(name: str, body: bytes, body_path: Path, out_png: Path) -> dict:
    curves = {label: response_at(body, m, q, PLOT_FREQS) for label, m, q in STATES}
    fig, axes = plt.subplots(2, 2, figsize=(16.5, 10.5), facecolor=DARK["face"])
    axes = axes.flatten()
    for ax in axes:
        style_ax(ax)
    for label, _, _ in STATES:
        y = curves[label]
        axes[0].semilogx(PLOT_FREQS, np.clip(y, -72, 60), lw=1.45, color=STATE_COLORS[label], label=label)
        axes[1].semilogx(PLOT_FREQS, np.clip(y - float(np.max(y)), -72, 12), lw=1.45, color=STATE_COLORS[label])
    for ax in axes[:2]:
        ax.set_xlim(40, 18500)
    axes[0].set_ylim(-72, 60)
    axes[1].set_ylim(-72, 12)
    axes[0].set_title(f"{name} — absolute packed-runtime magnitude", color=DARK["text"], fontsize=11)
    axes[1].set_title("normalized shape", color=DARK["text"], fontsize=11)
    axes[0].legend(fontsize=8, facecolor="#101713", edgecolor="#314139", labelcolor=DARK["text"])
    morphs = np.linspace(0.0, 1.0, 180)
    for ax, q, sub in ((axes[2], 0.0, "Morph sweep at Q0"), (axes[3], 1.0, "Morph sweep at Q100")):
        img = np.array([response_at(body, float(m), q, GRID_FREQS) for m in morphs]).T
        lo = float(np.nanpercentile(img, 4.0))
        hi = float(np.nanpercentile(img, 99.3))
        ax.imshow(np.clip(img, lo, hi), aspect="auto", origin="lower", cmap="magma",
                  extent=[0.0, 1.0, 0.0, len(GRID_FREQS) - 1.0])
        ticks = [60, 200, 600, 2000, 6000, 15000]
        idxs = [float(np.argmin(np.abs(GRID_FREQS - f))) for f in ticks]
        ax.set_yticks(idxs)
        ax.set_yticklabels([f"{f/1000:g}k" if f >= 1000 else f"{f:g}" for f in ticks])
        ax.set_title(sub, color=DARK["text"], fontsize=11)
        ax.set_xlabel("Morph", color=DARK["tick"], fontsize=9)
        ax.grid(False)
    footer(fig, body_path)
    fig.tight_layout(rect=(0, 0.015, 1, 1))
    fig.savefig(out_png, dpi=110, facecolor=DARK["face"])
    plt.close(fig)
    return curves


def plot_interior(name: str, grid: dict, wrap: dict, body_path: Path, out_png: Path):
    fig, axes = plt.subplots(1, 2, figsize=(16.5, 7.0), facecolor=DARK["face"])
    for ax in axes:
        style_ax(ax)
        ax.grid(False)
    im0 = axes[0].imshow(grid["peak_db"], aspect="auto", origin="lower", cmap="magma",
                         extent=[0.0, 1.0, 0.0, 1.0])
    axes[0].set_title(f"{name} — interior peak gain (dB), {GRID_N}x{GRID_N} packed probe",
                      color=DARK["text"], fontsize=11)
    fig.colorbar(im0, ax=axes[0]).ax.tick_params(colors=DARK["tick"], labelsize=8)
    im1 = axes[1].imshow(np.log2(np.maximum(grid["peak_hz"], 30.0)), aspect="auto", origin="lower",
                         cmap="viridis", extent=[0.0, 1.0, 0.0, 1.0])
    axes[1].set_title("dominant-peak frequency (log2 Hz) — center motion", color=DARK["text"], fontsize=11)
    cb = fig.colorbar(im1, ax=axes[1])
    cb.ax.tick_params(colors=DARK["tick"], labelsize=8)
    for ax in axes:
        ax.set_xlabel("Morph", color=DARK["tick"], fontsize=9)
        ax.set_ylabel("Q", color=DARK["tick"], fontsize=9)
        # sweep paths auditioned in this pack
        ax.plot([0, 1], [0.0, 0.0], color="#63d7ff", lw=2.0, alpha=0.85)   # morph @ Q0
        ax.plot([0.5, 0.5], [0, 1], color="#ff5f7e", lw=2.0, alpha=0.85)   # Q @ M50
        ax.plot([0, 1], [0, 1], color="#96e6bf", lw=1.6, alpha=0.85, ls="--")  # diagonal
    wrap_line = " · ".join(f"{k} max|dW|={v['max_abs_dw']}" for k, v in wrap.items() if isinstance(v, dict))
    risk = "WRAP RISK EDGES PRESENT" if wrap["any_wrap_risk"] else "no |dW|>32767 edge"
    fig.text(0.01, 0.055, f"grid max |pole| = {grid['grid_max_pole_r']:.5f} · nonfinite cells = {grid['nonfinite_cells']} · {risk}",
             color="#e6d7a7", fontsize=9)
    fig.text(0.01, 0.03, wrap_line, color="#6f7f75", fontsize=7)
    footer(fig, body_path)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(out_png, dpi=110, facecolor=DARK["face"])
    plt.close(fig)


def plot_sweeps(name: str, renders: dict, body_path: Path, out_png: Path):
    """Spectrograms of the rendered audio for pink + drums across all 5 programs."""
    prog_names = [p[0] for p in programs(10, 4.0)]
    fig, axes = plt.subplots(2, 5, figsize=(22, 7.5), facecolor=DARK["face"])
    for r, mat in enumerate(("pink", "drums")):
        for c, prog in enumerate(prog_names):
            ax = axes[r][c]
            style_ax(ax)
            ax.grid(False)
            y = renders.get((mat, prog))
            if y is None or not y.size:
                continue
            ax.specgram(y, NFFT=1024, Fs=AUTHORING_SR, noverlap=768, cmap="magma",
                        vmin=-130, vmax=-20)
            ax.set_ylim(0, 16000)
            if r == 0:
                ax.set_title(prog, color=DARK["text"], fontsize=10)
            if c == 0:
                ax.set_ylabel(f"{mat}\nHz", color=DARK["tick"], fontsize=9)
    fig.suptitle(f"{name} — rendered SLAM+AGC sweeps (raw engine level)", color=DARK["text"], fontsize=13)
    footer(fig, body_path)
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.savefig(out_png, dpi=100, facecolor=DARK["face"])
    plt.close(fig)


# ---------------------------------------------------------------- pack build
def build():
    OUT.mkdir(parents=True, exist_ok=True)
    src_dir = OUT / "_sources"
    sources = {
        "pink": pink_noise(5.0, 20260630),
        "drums": drum_source(4.0),
        "bass": bass_source(4.0),
        "vocal": vocal_source(4.0),
        "fullmix": fullmix_source(4.0),
    }
    for mat, y in sources.items():
        write_wav(src_dir / f"source_{mat}.wav", y)

    manifest = {"date": STAMP, "engine": "trench_ffi.engine_render_slam (SLAM input stage + AGC)",
                "sr": AUTHORING_SR, "block": BLOCK, "fast_sweep_hz": FAST_HZ,
                "agc_drive": float(trench_ffi.MUSICAL_AGC_DRIVE), "bodies": []}
    sheet_rows = []

    for name, body_path, provenance in BODIES:
        body = body_path.read_bytes()
        assert len(body) == 240, f"{name}: {len(body)} bytes"
        bdir = OUT / name
        bdir.mkdir(parents=True, exist_ok=True)
        print(f"[{name}] response + interior ...", flush=True)
        curves = plot_response(name, body, body_path, bdir / "response.png")
        grid = interior_grid(body)
        wrap = wrap_scan(body)
        plot_interior(name, grid, wrap, body_path, bdir / "interior.png")

        rows = []
        spect_renders = {}
        for mat, seconds, slam in MATERIALS:
            src = sources[mat]
            nb = max(1, (len(src) + BLOCK - 1) // BLOCK)
            for prog, morph, qv, desc in programs(nb, seconds):
                y = render_slam(body, src, morph, qv, slam)
                peak = float(np.max(np.abs(y))) if y.size else 0.0
                rms = float(np.sqrt(np.mean(y * y))) if y.size else 0.0
                clip = int(np.sum(np.abs(y) >= 0.999))
                raw = bdir / f"{mat}_{prog}.wav"
                write_wav(raw, y)
                write_wav(bdir / f"{mat}_{prog}_norm.wav", y * (0.90 / peak) if peak > 1e-9 else y)
                if mat in ("pink", "drums"):
                    spect_renders[(mat, prog)] = y
                rows.append({"material": mat, "program": prog, "description": desc,
                             "slam_drive": slam, "file": raw.name,
                             "peak_abs": round(peak, 6), "rms": round(rms, 6),
                             "clip_count_float": clip,
                             "finite": bool(np.all(np.isfinite(y)))})
            print(f"[{name}] {mat} rendered", flush=True)
        plot_sweeps(name, spect_renders, body_path, bdir / "sweeps.png")

        report = {
            "body": str(body_path), "sha256": hashlib.sha256(body).hexdigest(),
            "provenance_note": provenance,
            "grid_max_pole_r": grid["grid_max_pole_r"],
            "nonfinite_grid_cells": grid["nonfinite_cells"],
            "wrap_scan": wrap,
            "renders": rows,
        }
        (bdir / "report.json").write_text(json.dumps(report, indent=2))
        manifest["bodies"].append({"name": name, "dir": name, **{k: report[k] for k in
                                   ("body", "sha256", "grid_max_pole_r", "nonfinite_grid_cells")},
                                   "any_wrap_risk": wrap["any_wrap_risk"]})
        sheet_rows.append({"name": name, "provenance": provenance, "curves": curves,
                           "grid": grid, "wrap": wrap,
                           "qfast": spect_renders.get(("drums", "q_fast_m50")),
                           "peak_worst": max(r["peak_abs"] for r in rows),
                           "clip_total": sum(r["clip_count_float"] for r in rows)})

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    contact_sheet(sheet_rows)
    write_index(manifest, sheet_rows)
    print("PACK COMPLETE:", OUT)


def contact_sheet(rows: list[dict]):
    n = len(rows)
    height = 3.0 * n + 2.2
    fig = plt.figure(figsize=(23, height), facecolor=DARK["face"])
    gs = fig.add_gridspec(n, 4, width_ratios=[3.2, 2.0, 2.6, 2.2], hspace=0.5, wspace=0.22,
                          left=0.035, right=0.985, top=1 - 1.5 / height, bottom=0.9 / height)
    for i, row in enumerate(rows):
        ax0 = fig.add_subplot(gs[i, 0])
        style_ax(ax0)
        for label, _, _ in STATES:
            ax0.semilogx(PLOT_FREQS, np.clip(row["curves"][label], -72, 60), lw=1.0,
                         color=STATE_COLORS[label], label=label if i == 0 else None)
        ax0.set_xlim(40, 18500)
        ax0.set_ylim(-72, 60)
        ax0.set_ylabel(row["name"], color=DARK["text"], fontsize=11, fontweight="bold")
        if i == 0:
            ax0.legend(fontsize=6, ncol=3, facecolor="#101713", edgecolor="#314139", labelcolor=DARK["text"])
        ax1 = fig.add_subplot(gs[i, 1])
        style_ax(ax1)
        ax1.grid(False)
        ax1.imshow(row["grid"]["peak_db"], aspect="auto", origin="lower", cmap="magma",
                   extent=[0, 1, 0, 1])
        ax1.plot([0.5, 0.5], [0, 1], color="#ff5f7e", lw=1.4, alpha=0.9)
        if i == 0:
            ax1.set_title("interior peak dB (MxQ)", color=DARK["text"], fontsize=9)
        ax2 = fig.add_subplot(gs[i, 2])
        style_ax(ax2)
        ax2.grid(False)
        if row["qfast"] is not None and row["qfast"].size:
            ax2.specgram(row["qfast"], NFFT=1024, Fs=AUTHORING_SR, noverlap=768,
                         cmap="magma", vmin=-130, vmax=-20)
            ax2.set_ylim(0, 16000)
        if i == 0:
            ax2.set_title("drums q_fast_m50 (THE novel test)", color=DARK["text"], fontsize=9)
        ax3 = fig.add_subplot(gs[i, 3])
        ax3.set_facecolor(DARK["panel"])
        ax3.set_xticks([])
        ax3.set_yticks([])
        for spine in ax3.spines.values():
            spine.set_color(DARK["spine"])
        wrap = row["wrap"]
        worst_edge = max(((k, v["max_abs_dw"]) for k, v in wrap.items() if isinstance(v, dict)),
                         key=lambda kv: kv[1])
        txt = (f"{row['provenance']}\n"
               f"grid max |pole| = {row['grid']['grid_max_pole_r']:.5f}\n"
               f"interior peak = {row['grid']['peak_db'].max():+.1f} dB\n"
               f"worst edge |dW| = {worst_edge[1]} ({worst_edge[0]})\n"
               f"wrap risk: {'YES' if wrap['any_wrap_risk'] else 'no'}\n"
               f"render peak (raw) = {row['peak_worst']:.3f} · clipped samples = {row['clip_total']}")
        ax3.text(0.04, 0.95, txt, color=DARK["text"], fontsize=8.2, va="top", family="monospace", wrap=True)
    fig.suptitle("TRENCH audition pack — 10 candidates through SLAM+AGC · corridor/copy-risk cited from PRIOR_ART_LEDGER (2026-07-03)",
                 color=DARK["text"], fontsize=14, y=1 - 0.45 / height)
    fig.text(0.01, 0.004,
             f"{OUT} · renders: trench_ffi.engine_render_slam @ {AUTHORING_SR:.1f} Hz · probes: packed_interpolate {GRID_N}x{GRID_N} · {STAMP}",
             color="#6f7f75", fontsize=8)
    fig.savefig(OUT / "contact_sheet.png", dpi=100, facecolor=DARK["face"])
    plt.close(fig)


def write_index(manifest: dict, rows: list[dict]):
    prog_names = [p[0] for p in programs(10, 4.0)]
    mats = [m[0] for m in MATERIALS]
    parts = [
        "<!doctype html><meta charset='utf-8'><title>TRENCH audition pack</title>",
        "<style>body{background:#070908;color:#edf3ee;font:14px/1.5 system-ui;margin:20px}"
        "h2{color:#96e6bf;margin-top:2em}img{max-width:100%;border:1px solid #2e3d35}"
        "table{border-collapse:collapse}td,th{padding:4px 8px;border:1px solid #26352e;font-size:12px}"
        "audio{width:190px;height:28px}a{color:#63d7ff}.note{color:#a8b5ad;font-size:12px}</style>",
        f"<h1>TRENCH audition pack — {STAMP}</h1>",
        "<p class='note'>All clips: shipped engine path (SLAM input stage &rarr; packed cascade &rarr; AGC), "
        "39062.5 Hz. Normalized clips for listening; raw wavs (exact engine level) linked in each body's report.json. "
        "q_fast_m50 is the never-live Q axis — THE novel test.</p>",
        "<p><a href='contact_sheet.png'>contact sheet</a> · sources: " +
        " · ".join(f"<a href='_sources/source_{m}.wav'>{m}</a>" for m in mats) + "</p>",
    ]
    for b in manifest["bodies"]:
        name = b["name"]
        parts.append(f"<h2>{html.escape(name)}</h2>")
        parts.append(f"<p class='note'>{html.escape(next(r['provenance'] for r in rows if r['name'] == name))} · "
                     f"grid max |pole| {b['grid_max_pole_r']:.5f} · wrap risk {'YES' if b['any_wrap_risk'] else 'no'}</p>")
        parts.append(f"<p><img src='{name}/response.png' width='980'><br>"
                     f"<img src='{name}/interior.png' width='980'><br>"
                     f"<img src='{name}/sweeps.png' width='980'></p>")
        parts.append("<table><tr><th></th>" + "".join(f"<th>{p}</th>" for p in prog_names) + "</tr>")
        for mat in mats:
            cells = "".join(
                f"<td><audio controls preload='none' src='{name}/{mat}_{p}_norm.wav'></audio></td>"
                for p in prog_names)
            parts.append(f"<tr><th>{mat}</th>{cells}</tr>")
        parts.append("</table>")
    (OUT / "index.html").write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    build()
