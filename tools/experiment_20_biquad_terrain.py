#!/usr/bin/env python3
"""Offline 20-biquad terrain experiment.

Builds one original four-corner "OUUI -> synthetic ear bender" body with
20 lawful RBJ peaking sections, then asks the shipped trench-core factorizer
to compress the four corner magnitude curves into the runtime's six packed
rows. Writes plots, audio, metrics, and the packed .body240 comparison.

This does not change the plugin topology or publish a preset.
"""
from __future__ import annotations

import html
import json
import math
import struct
import sys
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import sosfilt, sosfreqz

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words  # noqa: E402

SR = 44100
AUTH_SR = 39062.5
AGC_DRIVE = 4.0
BLOCK = 512
FREQS = np.logspace(math.log10(35.0), math.log10(16000.0), 1024)
FIT_FREQS = np.logspace(math.log10(40.0), math.log10(16000.0), 256)
LABELS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
STATES = {
    "M0_Q0": (0.0, 0.0),
    "M100_Q0": (1.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q100": (1.0, 1.0),
    "MID": (0.5, 0.5),
}
OUT = ROOT / "dev" / "tmp" / "experiment_20_biquad_terrain" / "ouui_ear_bender"


@dataclass(frozen=True)
class Lane:
    name: str
    role: str
    f0: float
    f1: float
    gain0_db: float
    gain1_db: float
    q0: float
    q1: float
    tension_gain_db: float
    tension_q_scale: float
    tension_octaves: float = 0.0


# Twenty registered actors. Each is one stable pole pair with an attached zero
# pair from the RBJ peaking-EQ construction. Morph moves their identity; Q
# changes contrast and selectively relocates actors instead of only sharpening.
LANES = (
    Lane("chest", "body", 150, 210, 4.0, 3.0, 1.0, 1.2, 1.0, 0.90),
    Lane("F1", "throat", 320, 410, 8.0, 5.0, 2.8, 3.8, 3.0, 1.45),
    Lane("F2", "throat", 690, 980, 10.0, 7.0, 5.5, 7.5, 4.0, 1.65),
    Lane("F3", "throat", 1260, 1780, 8.0, 8.0, 7.0, 9.0, 4.0, 1.80),
    Lane("F4", "throat", 2460, 3280, 6.0, 7.0, 8.0, 11.0, 5.0, 1.90),
    Lane("F5", "throat", 3480, 4320, 4.0, 6.0, 9.0, 13.0, 6.0, 2.00),
    Lane("mouth_hollow", "canyon", 520, 760, -7.0, -10.0, 3.5, 5.0, -5.0, 1.60),
    Lane("tongue_hollow", "canyon", 930, 1340, -8.0, -12.0, 5.0, 7.0, -6.0, 1.80),
    Lane("palate_hollow", "canyon", 2020, 2260, -9.0, -11.0, 6.0, 8.0, -8.0, 2.00),
    Lane("presence_hollow", "canyon", 3020, 3640, -6.0, -10.0, 7.0, 10.0, -8.0, 2.10),
    Lane("air_hollow", "canyon", 5750, 5140, -7.0, -13.0, 9.0, 14.0, -10.0, 2.20),
    Lane("air_cap", "sheen", 5200, 6900, 4.0, 8.0, 7.0, 12.0, 5.0, 1.90),
    Lane("sheen_1", "sheen", 6500, 7600, 3.0, 7.0, 10.0, 15.0, 5.0, 2.20),
    Lane("sheen_2", "sheen", 7450, 9000, -3.0, -8.0, 11.0, 17.0, -7.0, 2.30),
    Lane("sheen_3", "sheen", 8550, 10300, 4.0, 9.0, 12.0, 19.0, 6.0, 2.40),
    Lane("sheen_4", "sheen", 10000, 12100, -4.0, -9.0, 13.0, 21.0, -7.0, 2.50),
    Lane("sheen_5", "sheen", 12100, 14900, 3.0, 8.0, 14.0, 24.0, 7.0, 2.60),
    Lane("cross_up", "crosser", 1520, 6100, 3.0, 11.0, 5.0, 13.0, 8.0, 2.20, 0.16),
    Lane("cross_down", "crosser", 5940, 1480, 2.0, 10.0, 6.0, 15.0, 8.0, 2.30, -0.18),
    Lane("counterweight", "counterweight", 9100, 2650, -4.0, -12.0, 8.0, 13.0, -8.0, 2.00, -0.12),
)


def lerp_log(a: float, b: float, t: float) -> float:
    return a * (b / a) ** t


def lane_state(lane: Lane, morph: float, q_axis: float) -> dict:
    freq = lerp_log(lane.f0, lane.f1, morph) * 2.0 ** (q_axis * lane.tension_octaves)
    gain = lane.gain0_db + (lane.gain1_db - lane.gain0_db) * morph
    gain += lane.tension_gain_db * q_axis
    q_value = lerp_log(lane.q0, lane.q1, morph) * lerp_log(1.0, lane.tension_q_scale, q_axis)
    return {
        "name": lane.name,
        "role": lane.role,
        "freq_hz": float(np.clip(freq, 35.0, 16000.0)),
        "gain_db": gain,
        "q": max(q_value, 0.35),
    }


def peaking_sos(freq_hz: float, q_value: float, gain_db: float) -> np.ndarray:
    """RBJ peaking EQ: stable attached pole/zero pairs on a flat baseline."""
    freq_hz = float(np.clip(freq_hz, 35.0, SR * 0.48))
    q_value = max(float(q_value), 0.35)
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq_hz / SR
    alpha = math.sin(w0) / (2.0 * q_value)
    b0, b1, b2 = 1.0 + alpha * a, -2.0 * math.cos(w0), 1.0 - alpha * a
    a0, a1, a2 = 1.0 + alpha / a, -2.0 * math.cos(w0), 1.0 - alpha / a
    return np.array([b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0])


def response_db(sos: np.ndarray, freqs: np.ndarray = FREQS) -> np.ndarray:
    _, h = sosfreqz(sos, worN=freqs, fs=SR)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-20))


def terrain_sos(morph: float, q_axis: float) -> tuple[np.ndarray, list[dict]]:
    actors = [lane_state(lane, morph, q_axis) for lane in LANES]
    sos = np.vstack([peaking_sos(a["freq_hz"], a["q"], a["gain_db"]) for a in actors])
    # Keep the experiment inside a musical headroom envelope without changing
    # its shape. One scalar is folded into the first numerator.
    peak = float(response_db(sos, FIT_FREQS).max())
    scalar = 10.0 ** ((11.0 - peak) / 20.0)
    sos[0, :3] *= scalar
    return sos, actors


def max_pole_radius(sos: np.ndarray) -> float:
    return max(float(np.max(np.abs(np.roots((1.0, row[4], row[5]))))) for row in sos)


def packed_body() -> tuple[bytes, dict[str, list[tuple[int, ...]]]]:
    corners: dict[str, list[tuple[int, ...]]] = {}
    for label in LABELS:
        sos, _ = terrain_sos(*STATES[label])
        db = response_db(sos, FIT_FREQS)
        rows = trench_ffi.fit_corner_from_magnitude(zip(FIT_FREQS.tolist(), db.tolist()), AUTH_SR)
        corners[label] = [coeffs_to_words(*row) for row in rows]
    flat: list[int] = []
    for label in LABELS:
        for row in corners[label]:
            flat.extend(int(word) & 0xFFFF for word in row)
    return struct.pack("<120H", *flat), corners


def packed_db(body: bytes, morph: float, q_axis: float) -> np.ndarray:
    rows = trench_ffi.packed_interpolate(body, morph, q_axis)
    return cascade_response_db([EncodedCoeffs(*row) for row in rows], FREQS, AUTH_SR)


def shape_rms(a: np.ndarray, b: np.ndarray, lo: float = 80.0, hi: float = 12000.0) -> float:
    mask = (FREQS >= lo) & (FREQS <= hi)
    residual = a[mask] - b[mask]
    residual -= residual.mean()
    return float(np.sqrt(np.mean(residual * residual)))


def level_offset_db(reference: np.ndarray, candidate: np.ndarray, lo: float = 80.0, hi: float = 12000.0) -> float:
    mask = (FREQS >= lo) & (FREQS <= hi)
    return float(np.mean(reference[mask] - candidate[mask]))


def packed_stability(body: bytes, n: int = 11) -> dict:
    max_radius = 0.0
    unstable_rows = 0
    nonfinite_rows = 0
    for morph in np.linspace(0.0, 1.0, n):
        for q_axis in np.linspace(0.0, 1.0, n):
            probe = trench_ffi.packed_probe(body, float(morph), float(q_axis))
            max_radius = max(max_radius, float(probe["max_pole_radius"]))
            unstable_rows += int(probe["unstable_mask"]).bit_count()
            nonfinite_rows += int(probe["nonfinite_mask"]).bit_count()
    return {
        "grid": f"{n}x{n}",
        "max_pole_radius": round(max_radius, 6),
        "unstable_rows": unstable_rows,
        "nonfinite_rows": nonfinite_rows,
        "stable": max_radius < 1.0 and unstable_rows == 0 and nonfinite_rows == 0,
    }


def source(seconds: float = 4.0) -> np.ndarray:
    rng = np.random.default_rng(20260601)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    saw = sum((2.0 * ((f * t) % 1.0) - 1.0) / (i + 1)
              for i, f in enumerate((55.0, 110.0, 165.0)))
    hiss = rng.normal(0.0, 0.18, n)
    env = np.minimum(1.0, 16.0 * t) * (0.78 + 0.22 * np.sin(2.0 * np.pi * 0.45 * t) ** 2)
    x = (0.45 * saw + hiss) * env
    return (x / max(float(np.max(np.abs(x))), 1e-9) * 0.62).astype(np.float32)


def saturate(x: np.ndarray) -> np.ndarray:
    knee = 0.9
    a = np.abs(x)
    return np.where(a <= knee, x, np.sign(x) * (knee + (1.0 - knee) * np.tanh((a - knee) / (1.0 - knee))))


def agc(samples: np.ndarray, drive: float = AGC_DRIVE) -> np.ndarray:
    """Mono version of trench-core's table AGC for the non-shipping 20-row path."""
    table = np.asarray(trench_ffi.agc_table(), dtype=np.float32)
    out = np.empty_like(samples, dtype=np.float32)
    gain = np.float32(1.0)
    drive32 = np.float32(max(1.0, drive))
    for i, sample in enumerate(np.asarray(samples, dtype=np.float32)):
        driven = np.float32(sample * drive32)
        idx = int(np.uint32(np.float32(gain * abs(driven)))) & 0xF
        gain = min(np.float32(gain * table[idx]), np.float32(1.0))
        out[i] = np.float32(driven * gain / drive32)
    return saturate(out).astype(np.float32)


def render_terrain(x: np.ndarray, mode: str) -> np.ndarray:
    nb = max(1, (len(x) + BLOCK - 1) // BLOCK)
    zi = np.zeros((len(LANES), 2), dtype=np.float64)
    out = np.zeros(len(x), dtype=np.float64)
    for bi in range(nb):
        start, end = bi * BLOCK, min(len(x), (bi + 1) * BLOCK)
        t = bi / max(nb - 1, 1)
        if mode == "morph":
            morph, q_axis = t, 0.0
        elif mode == "q":
            morph, q_axis = 0.5, t
        elif mode == "diagonal":
            morph, q_axis = t, t
        else:
            morph, q_axis = STATES[mode]
        sos, _ = terrain_sos(morph, q_axis)
        out[start:end], zi = sosfilt(sos, x[start:end], zi=zi)
    return agc(out)


def render_packed(body: bytes, x: np.ndarray, mode: str) -> np.ndarray:
    if mode in STATES:
        raw = trench_ffi.engine_render(body, *STATES[mode], x.tobytes(), SR, agc_drive=AGC_DRIVE)
    else:
        nb = max(1, (len(x) + BLOCK - 1) // BLOCK)
        ramp = np.linspace(0.0, 1.0, nb)
        if mode == "morph":
            morph, q_axis = ramp, np.zeros(nb)
        elif mode == "q":
            morph, q_axis = np.full(nb, 0.5), ramp
        else:
            morph, q_axis = ramp, ramp
        raw = trench_ffi.engine_render_automated(
            body, morph, q_axis, x.tobytes(), SR, block=BLOCK, agc_drive=AGC_DRIVE,
        )
    return np.frombuffer(raw, dtype=np.float32).copy()


def write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes(pcm.tobytes())


def level_match(reference: np.ndarray, candidate: np.ndarray) -> tuple[np.ndarray, float]:
    ref_rms = math.sqrt(float(np.mean(np.asarray(reference, dtype=np.float64) ** 2)))
    cand_rms = math.sqrt(float(np.mean(np.asarray(candidate, dtype=np.float64) ** 2)))
    gain = ref_rms / max(cand_rms, 1e-12)
    out = np.asarray(candidate, dtype=np.float64) * gain
    peak = float(np.max(np.abs(out)))
    if peak > 0.98:
        out *= 0.98 / peak
    return out.astype(np.float32), 20.0 * math.log10(max(gain, 1e-12))


def write_cart(body: bytes, corners: dict[str, list[tuple[int, ...]]]) -> None:
    keyframes = []
    for label in LABELS:
        morph, q_axis = STATES[label]
        keyframes.append({
            "label": label,
            "morph": morph,
            "q": q_axis,
            "boost": 1.0,
            "packedWords": [list(map(int, row)) for row in corners[label]],
        })
    payload = {
        "format": "compiled-v1",
        "name": "20 Biquad Terrain compressed to six",
        "provenance": "offline experiment only",
        "sampleRate": AUTH_SR,
        "authoring_sample_rate_hz": AUTH_SR,
        "stages": 6,
        "cornerOrder": list(LABELS),
        "boost": 1.0,
        "keyframes": keyframes,
    }
    (OUT / "compressed_6row.cart.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (OUT / "compressed_6row.body240").write_bytes(body)


def plot_corners(body: bytes) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13, 7), dpi=130, sharex=True, sharey=True)
    for ax, label in zip(axes.ravel(), LABELS):
        sos, _ = terrain_sos(*STATES[label])
        target = response_db(sos)
        packed = packed_db(body, *STATES[label])
        aligned = packed + level_offset_db(target, packed)
        ax.semilogx(FREQS, target, color="#6ee7a8", lw=1.8, label="20 rows")
        ax.semilogx(FREQS, packed, color="#89928e", lw=1.0, ls=":", label="packed 6 rows raw")
        ax.semilogx(FREQS, aligned, color="#ffbf4b", lw=1.3, label="packed 6 rows level-aligned")
        ax.fill_between(FREQS, target, aligned, color="#ff6b6b", alpha=0.14)
        ax.set_title(f"{label}  shape RMS {shape_rms(target, packed):.1f} dB")
        ax.grid(alpha=0.20, which="both")
        ax.set_xlim(35, 16000)
        ax.set_ylim(-48, 18)
    axes[0, 0].legend(loc="lower left")
    for ax in axes[:, 0]:
        ax.set_ylabel("dB")
    for ax in axes[-1, :]:
        ax.set_xlabel("Hz")
    fig.suptitle("OUUI -> synthetic ear bender: lawful 20-biquad terrain vs runtime 6-row compression")
    fig.tight_layout()
    fig.savefig(OUT / "corners_20_vs_6.png", facecolor="#f5f1e8")
    plt.close(fig)


def plot_midpoint(body: bytes) -> None:
    sos, _ = terrain_sos(0.5, 0.5)
    target = response_db(sos)
    packed = packed_db(body, 0.5, 0.5)
    aligned = packed + level_offset_db(target, packed)
    fig, ax = plt.subplots(figsize=(11, 4.4), dpi=130)
    ax.semilogx(FREQS, target, color="#6ee7a8", lw=2.0, label="20-row mathematical terrain")
    ax.semilogx(FREQS, packed, color="#89928e", lw=1.0, ls=":", label="packed 6-row midpoint raw")
    ax.semilogx(FREQS, aligned, color="#ffbf4b", lw=1.5, label="packed 6-row midpoint level-aligned")
    ax.fill_between(FREQS, target, aligned, color="#ff6b6b", alpha=0.16)
    ax.set(xlim=(35, 16000), ylim=(-48, 18), xlabel="Hz", ylabel="dB",
           title=f"Midpoint: six rows cannot retain every mountain and canyon (shape RMS {shape_rms(target, packed):.1f} dB)")
    ax.grid(alpha=0.20, which="both")
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(OUT / "midpoint_20_vs_6.png", facecolor="#f5f1e8")
    plt.close(fig)


def plot_actor_map() -> None:
    colors = {"body": "#4267ac", "throat": "#3a9d5d", "canyon": "#c3423f",
              "sheen": "#ca8a04", "crosser": "#8b5cf6", "counterweight": "#111827"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 7), dpi=130, sharey=True)
    for ax, q_axis, title in zip(axes, (0.0, 1.0), ("Q = 0: body and motion", "Q = 1: contrast, relocation, sheen")):
        for lane in LANES:
            a, b = lane_state(lane, 0.0, q_axis), lane_state(lane, 1.0, q_axis)
            color = colors[lane.role]
            ax.plot((0.0, 1.0), (a["freq_hz"], b["freq_hz"]), color=color, lw=1.6, alpha=0.85)
            ax.scatter((0.0, 1.0), (a["freq_hz"], b["freq_hz"]),
                       s=(18 + 2.2 * abs(a["gain_db"]), 18 + 2.2 * abs(b["gain_db"])),
                       color=color, alpha=0.90)
        ax.set_yscale("log")
        ax.set_xlim(-0.03, 1.03)
        ax.set_ylim(90, 16500)
        ax.set_xticks((0.0, 1.0), ("OUUI body", "synthetic edge"))
        ax.set_title(title)
        ax.grid(alpha=0.20, which="both")
    axes[0].set_ylabel("registered actor frequency (Hz, log)")
    fig.suptitle("Axis design: Morph changes posture; Q changes the rules without losing the body")
    fig.tight_layout()
    fig.savefig(OUT / "actor_map.png", facecolor="#f5f1e8")
    plt.close(fig)


def write_html(metrics: dict) -> None:
    clips = ("MID", "morph", "q", "diagonal")
    players = []
    for clip in clips:
        players.append(
            f"<section><h2>{html.escape(clip)}</h2>"
            f"<label>20 rows<audio controls src='audio/terrain20_{clip}.wav'></audio></label>"
            f"<label>packed 6 raw<audio controls src='audio/packed6_{clip}.wav'></audio></label>"
            f"<label>packed 6 matched<audio controls src='audio/packed6_matched_{clip}.wav'></audio></label>"
            "</section>"
        )
    doc = f"""<!doctype html>
<meta charset="utf-8">
<title>20 biquad terrain experiment</title>
<style>
body{{background:#0c0f0e;color:#e7e4da;font:15px/1.5 system-ui;margin:0}}
main{{max-width:1100px;margin:auto;padding:24px}}
h1,h2{{color:#9aef5a}} img{{width:100%;margin:8px 0 20px;background:#f5f1e8}}
section{{border:1px solid #33433c;border-radius:7px;padding:12px;margin:12px 0}}
label{{display:grid;grid-template-columns:150px 1fr;align-items:center;gap:10px;margin:7px 0}}
audio{{width:100%}} code{{color:#ffbf4b}}
</style>
<main>
<h1>20 biquads: OUUI throat to synthetic ear bender</h1>
<p>Offline experiment only. Green is the lawful 20-row terrain. Amber is the same four corners compressed through trench-core into the runtime's six packed rows.</p>
<p><code>AGC drive = {AGC_DRIVE:.1f}</code> on both audition paths. Packed six-row audio uses the shipped engine. The matched preview adds post-render gain only so structural loss can be judged without a loudness trick.</p>
<img src="actor_map.png">
<img src="corners_20_vs_6.png">
<img src="midpoint_20_vs_6.png">
{''.join(players)}
<pre>{html.escape(json.dumps(metrics, indent=2))}</pre>
</main>"""
    (OUT / "audition.html").write_text(doc, encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "audio").mkdir(exist_ok=True)

    body, corners = packed_body()
    write_cart(body, corners)

    state_metrics = {}
    for label, (morph, q_axis) in STATES.items():
        sos, actors = terrain_sos(morph, q_axis)
        terrain = response_db(sos)
        packed = packed_db(body, morph, q_axis)
        state_metrics[label] = {
            "terrain20_max_pole_radius": round(max_pole_radius(sos), 6),
            "terrain20_peak_db": round(float(terrain.max()), 3),
            "packed6_peak_db": round(float(packed.max()), 3),
            "packed6_level_offset_80_12000_db": round(level_offset_db(terrain, packed), 3),
            "shape_rms_80_12000_db": round(shape_rms(terrain, packed), 3),
            "terrain20_actor_count": len(actors),
        }

    stability = packed_stability(body)
    metrics = {
        "experiment": "20 lawful RBJ biquads versus packed runtime six-row factorization",
        "shipping_topology_changed": False,
        "agc_drive": AGC_DRIVE,
        "terrain20": {
            "sections": len(LANES),
            "construction": "registered RBJ peaking sections; every pole pair has an attached zero pair",
        },
        "packed6": {"bytes": len(body), "sections": 6, "surface_stability": stability},
        "states": state_metrics,
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (OUT / "terrain20_recipe.json").write_text(
        json.dumps({"name": "OUUI throat to synthetic ear bender", "lanes": [asdict(lane) for lane in LANES]}, indent=2),
        encoding="utf-8",
    )

    plot_actor_map()
    plot_corners(body)
    plot_midpoint(body)

    x = source()
    write_wav(OUT / "audio" / "dry.wav", x)
    matched_preview_gain = {}
    for mode in ("MID", "morph", "q", "diagonal"):
        terrain_audio = render_terrain(x, mode)
        packed_audio = render_packed(body, x, mode)
        matched_audio, matched_gain_db = level_match(terrain_audio, packed_audio)
        matched_preview_gain[mode] = round(matched_gain_db, 3)
        write_wav(OUT / "audio" / f"terrain20_{mode}.wav", terrain_audio)
        write_wav(OUT / "audio" / f"packed6_{mode}.wav", packed_audio)
        write_wav(OUT / "audio" / f"packed6_matched_{mode}.wav", matched_audio)
    metrics["packed6"]["matched_preview_post_gain_db"] = matched_preview_gain
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_html(metrics)

    print(f"wrote {OUT}")
    print(f"audition {OUT / 'audition.html'}")
    print(f"packed stability {stability}")
    for label, values in state_metrics.items():
        print(f"{label:10} shape RMS={values['shape_rms_80_12000_db']:5.2f} dB  "
              f"target peak={values['terrain20_peak_db']:+5.1f}  packed peak={values['packed6_peak_db']:+5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
