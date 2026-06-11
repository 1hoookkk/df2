#!/usr/bin/env python3
"""Verified Body Forge: clean-room Hz/radius actors -> legal .body240.

This is an end-to-end authoring proof, not a vendor reconstruction.

Pipeline:
  1. Start from original six-lane Hz/radius actor data.
  2. Convert each actor corner to standard biquad pole/zero kernel form.
  3. Pack through the repo's firmware-verified packed codec.
  4. Verify the actual 240-byte body through trench-core packed_probe.
  5. Emit .body240, compiled-v1 JSON, actor/audit metadata, plot, and WAVs.

The strategic pattern is MorphLP-inspired but clean-room: a macro pole
trajectory is paired with editable zero relationships. No vendor table values,
filter names, coefficient bytes, or preset data are used.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import sys
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words, kernel_to_biquad  # noqa: E402
from src.utils.body240 import (  # noqa: E402
    CORNER_ORDER,
    PACKED_KEYS,
    AUTHORING_SR,
    compiled_payload,
    raw_from_words,
)


TAU = 2.0 * math.pi
STAGES = 6
OUT_ROOT = ROOT / "dev" / "tmp" / "verified_body_forge"


@dataclass(frozen=True)
class ActorLane:
    lane: int
    role: str
    pole_home_hz: float
    pole_away_hz: float
    zero_home_hz: float
    zero_away_hz: float
    pole_radius_home: float
    pole_radius_away: float
    zero_radius_home: float
    zero_radius_away: float
    gain_home: float
    gain_away: float
    tight_pole_lift: float
    tight_zero_lift: float
    tight_gain_scale: float
    note: str


ACTORS: tuple[ActorLane, ...] = (
    ActorLane(
        0, "fundamental shelf / weight",
        82.0, 110.0, 205.0, 285.0,
        0.930, 0.942, 0.720, 0.760,
        0.40, 0.42, 0.010, 0.020, 0.94,
        "F0 shelf lane. Pole sits on the source fundamental; zero sets the shelf knee.",
    ),
    ActorLane(
        1, "canyon / low hollow",
        260.0, 380.0, 520.0, 295.0,
        0.965, 0.975, 0.90, 0.93,
        0.46, 0.48, 0.012, 0.035, 0.92,
        "Zero crosses toward the pole to make a visible low-mid hollow.",
    ),
    ActorLane(
        2, "mover / mouth",
        720.0, 1180.0, 980.0, 760.0,
        0.975, 0.986, 0.92, 0.95,
        0.42, 0.44, 0.012, 0.035, 0.92,
        "Primary vowel-ish mover. Away corner raises the pole while the zero counters.",
    ),
    ActorLane(
        3, "crosser / bite",
        1850.0, 1160.0, 1280.0, 2450.0,
        0.970, 0.984, 0.93, 0.96,
        0.39, 0.41, 0.012, 0.035, 0.92,
        "Bite lane moves against the mouth lane to create midpoint drama.",
    ),
    ActorLane(
        4, "ladder / tear",
        3250.0, 5450.0, 2400.0, 3900.0,
        0.962, 0.978, 0.90, 0.94,
        0.34, 0.36, 0.012, 0.035, 0.92,
        "Upper ladder lane adds a torn edge without requiring near-unit poles.",
    ),
    ActorLane(
        5, "cap / air",
        7600.0, 9800.0, 11800.0, 13200.0,
        0.940, 0.958, 0.84, 0.88,
        0.29, 0.31, 0.012, 0.035, 0.92,
        "Air cap is deliberately lower-gain; it gives motion without frying headroom.",
    ),
)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def kernel_from_pole_zero(
    pole_hz: float,
    pole_radius: float,
    zero_hz: float,
    zero_radius: float,
    gain: float,
    sr: float,
) -> tuple[float, float, float, float, float]:
    """Clean-room Hz/radius -> packed-kernel coordinates.

    Standard second-order pole/zero math:
      numerator roots:   zero_radius at +/- zero_hz
      denominator roots: pole_radius at +/- pole_hz

    Kernel slots are the verified packed-runtime slots:
      c0/c1 = zeros, c2/c3 = poles, c4 = gain.
    """
    pole_hz = clamp(pole_hz, 10.0, 0.47 * sr)
    zero_hz = clamp(zero_hz, 10.0, 0.47 * sr)
    pole_radius = clamp(pole_radius, 0.05, 0.9985)
    zero_radius = clamp(zero_radius, 0.05, 0.999)
    gain = clamp(gain, 1e-5, 3.95)

    wp = TAU * pole_hz / sr
    wz = TAU * zero_hz / sr
    c0 = 2.0 - 2.0 * zero_radius * math.cos(wz)
    c1 = 1.0 - zero_radius * zero_radius
    c2 = 2.0 - 2.0 * pole_radius * math.cos(wp)
    c3 = 1.0 - pole_radius * pole_radius
    c4 = gain
    return c0, c1, c2, c3, c4


def corner_state(actor: ActorLane, morph: float, secondary: float, sr: float) -> dict[str, Any]:
    pole_hz = lerp(actor.pole_home_hz, actor.pole_away_hz, morph)
    zero_hz = lerp(actor.zero_home_hz, actor.zero_away_hz, morph)
    pole_radius = lerp(actor.pole_radius_home, actor.pole_radius_away, morph)
    zero_radius = lerp(actor.zero_radius_home, actor.zero_radius_away, morph)
    gain = lerp(actor.gain_home, actor.gain_away, morph)

    pole_radius = clamp(pole_radius + actor.tight_pole_lift * secondary, 0.05, 0.9985)
    zero_radius = clamp(zero_radius + actor.tight_zero_lift * secondary, 0.05, 0.999)
    gain = gain * lerp(1.0, actor.tight_gain_scale, secondary)
    kernel = kernel_from_pole_zero(pole_hz, pole_radius, zero_hz, zero_radius, gain, sr)

    return {
        "lane": actor.lane,
        "role": actor.role,
        "pole_hz": round(pole_hz, 6),
        "pole_radius": round(pole_radius, 9),
        "zero_hz": round(zero_hz, 6),
        "zero_radius": round(zero_radius, 9),
        "gain": round(gain, 9),
        "kernel": [round(float(value), 12) for value in kernel],
    }


def build_cleanroom_body(sr: float) -> tuple[bytes, dict[str, list[tuple[int, ...]]], dict[str, Any]]:
    corner_map = {
        "M0_Q0": (0.0, 0.0),
        "M100_Q0": (1.0, 0.0),
        "M0_Q100": (0.0, 1.0),
        "M100_Q100": (1.0, 1.0),
    }
    kernels: dict[str, list[tuple[float, ...]]] = {}
    corner_meta: dict[str, list[dict[str, Any]]] = {}

    for label in CORNER_ORDER:
        morph, secondary = corner_map[label]
        states = [corner_state(actor, morph, secondary, sr) for actor in ACTORS]
        corner_meta[label] = states
        kernels[label] = [tuple(float(value) for value in state["kernel"]) for state in states]

    words = {
        label: [tuple(int(value) for value in coeffs_to_words(*row)) for row in rows]
        for label, rows in kernels.items()
    }
    body = raw_from_words(words)
    return body, words, {
        "corners": corner_meta,
        "actors": [asdict(actor) for actor in ACTORS],
    }


def body_bytes_for_ffi(words: dict[str, list[tuple[int, ...]]]) -> bytes:
    return trench_ffi.body_bytes_from_corner_words({
        PACKED_KEYS[label]: words[label] for label in CORNER_ORDER
    })


def response_at(body: bytes, morph: float, secondary: float, sr: float) -> np.ndarray:
    rows = trench_ffi.packed_interpolate(body, morph, secondary)
    return cascade_response_db([EncodedCoeffs(*row) for row in rows], freq_points(), sr)


def render_forge_plot(
    name: str,
    body: bytes,
    actor_doc: dict[str, Any],
    out: Path,
    sr: float,
    f0_hz: float,
) -> None:
    freqs = freq_points()
    plt.rcParams["figure.facecolor"] = "#070a09"
    plt.rcParams["axes.facecolor"] = "#090d0c"
    fig, axes = plt.subplots(1, 3, figsize=(17.2, 5.4), facecolor="#070a09")

    ymarks = [60, 150, 400, 1000, 2500, 6000]
    yidx = [int(np.argmin(np.abs(freqs - freq))) for freq in ymarks]
    for axis, secondary, title in ((axes[0], 0.0, "Secondary 0"), (axes[1], 1.0, "Secondary 1")):
        image = np.array([response_at(body, morph, secondary, sr)
                          for morph in np.linspace(0.0, 1.0, 240)]).T
        lo = float(np.nanpercentile(image, 4))
        hi = float(np.nanpercentile(image, 99.3))
        axis.imshow(
            np.clip(image, lo, max(hi, lo + 1.0)),
            aspect="auto",
            origin="lower",
            cmap="magma",
            extent=[0, 1, 0, len(freqs)],
            vmin=lo,
            vmax=max(hi, lo + 1.0),
        )
        axis.set_title(f"{title} packed Morph sweep", color="#e9efe9", fontsize=10)
        axis.set_xlabel("Morph", color="#a7b4ad", fontsize=8)
        axis.set_yticks(yidx)
        axis.set_yticklabels([str(freq) for freq in ymarks], color="#a7b4ad", fontsize=7)
        axis.tick_params(colors="#a7b4ad")
        for spine in axis.spines.values():
            spine.set_color("#25352e")

    colors = {
        "M0_Q0": "#35c6ff",
        "M100_Q0": "#ffd344",
        "M0_Q100": "#ff6363",
        "M100_Q100": "#9b8cff",
    }
    for label in CORNER_ORDER:
        morph = 1.0 if "M100" in label else 0.0
        secondary = 1.0 if "Q100" in label else 0.0
        curve = response_at(body, morph, secondary, sr)
        curve = np.clip(curve - float(np.max(curve)), -64.0, 6.0)
        axes[2].semilogx(freqs, curve, color=colors[label], lw=1.8, label=label)
    for harmonic in range(1, 13):
        hz = f0_hz * harmonic
        if 20.0 <= hz <= 20000.0:
            axes[2].axvline(
                hz,
                color="#6f8077",
                lw=1.1 if harmonic == 1 else 0.55,
                alpha=0.62 if harmonic == 1 else 0.30,
            )
    axes[2].text(
        f0_hz,
        -61.0,
        "F0",
        color="#a7b4ad",
        ha="center",
        va="bottom",
        fontsize=8,
        family="monospace",
    )

    axes[2].set_title("Four corners, normalized", color="#e9efe9", fontsize=10)
    axes[2].set_xlim(20.0, 20000.0)
    axes[2].set_ylim(-64.0, 6.0)
    axes[2].grid(True, which="both", color="#26342f", alpha=0.42, linewidth=0.55)
    axes[2].tick_params(colors="#a7b4ad", labelsize=7)
    axes[2].legend(facecolor="#101713", edgecolor="#27372f", labelcolor="#e9efe9", fontsize=8)
    for spine in axes[2].spines.values():
        spine.set_color("#25352e")

    midpoint = actor_doc["corners"]["M100_Q100"]
    pole_line = " ".join(str(int(round(stage["pole_hz"]))) for stage in midpoint)
    fig.text(
        0.5, 0.018,
        f"Clean-room actors -> packed .body240 -> trench-core audit. F0={f0_hz:g} Hz. Tight-away pole Hz: {pole_line}",
        color="#96a69d",
        ha="center",
        family="monospace",
        fontsize=8,
    )
    fig.suptitle(name, color="#e9efe9", fontsize=13)
    fig.tight_layout(rect=[0, 0.05, 1, 0.93])
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=125)
    plt.close(fig)


def roots_from_biquad(biquad: tuple[float, float, float, float, float], sr: float) -> dict[str, Any]:
    b0, b1, b2, a1, a2 = biquad

    def roots(poly: tuple[float, float, float]) -> list[dict[str, float]]:
        out = []
        for root in np.roots(poly):
            radius = float(abs(root))
            angle = abs(float(np.angle(root)))
            out.append({
                "real": round(float(np.real(root)), 9),
                "imag": round(float(np.imag(root)), 9),
                "radius": round(radius, 9),
                "hz": round(angle * sr / TAU, 6),
            })
        return out

    return {
        "zeros": roots((b0, b1, b2)),
        "poles": roots((1.0, a1, a2)),
    }


def audit_body(body: bytes, grid: int, sr: float) -> dict[str, Any]:
    worst = 0.0
    unstable = 0
    nonfinite = 0
    max_db = -math.inf
    min_db = math.inf
    points = []
    values = np.linspace(0.0, 1.0, grid)

    for morph in values:
        for secondary in values:
            probe = trench_ffi.packed_probe(body, float(morph), float(secondary))
            worst = max(worst, float(probe["max_pole_radius"]))
            unstable |= int(probe["unstable_mask"])
            nonfinite |= int(probe["nonfinite_mask"])
            curve = response_at(body, float(morph), float(secondary), sr)
            max_db = max(max_db, float(np.max(curve)))
            min_db = min(min_db, float(np.min(curve)))
            if morph in (0.0, 0.5, 1.0) and secondary in (0.0, 0.5, 1.0):
                points.append({
                    "morph": round(float(morph), 3),
                    "secondary": round(float(secondary), 3),
                    "max_pole_radius": round(float(probe["max_pole_radius"]), 9),
                    "unstable_mask": int(probe["unstable_mask"]),
                    "nonfinite_mask": int(probe["nonfinite_mask"]),
                })

    midpoint_probe = trench_ffi.packed_probe(body, 0.5, 0.5)
    return {
        "verified_runtime": str(trench_ffi.lib_path()),
        "grid": f"{grid}x{grid}",
        "body_bytes": len(body),
        "max_pole_radius": round(worst, 9),
        "unstable_mask": unstable,
        "nonfinite_mask": nonfinite,
        "response_min_db": round(min_db, 3),
        "response_max_db": round(max_db, 3),
        "response_span_db": round(max_db - min_db, 3),
        "midpoint_roots": [
            roots_from_biquad(tuple(float(v) for v in row), sr)
            for row in midpoint_probe["biquad"]
        ],
        "sample_points": points,
        "pass": unstable == 0 and nonfinite == 0 and worst < 1.0,
    }


def synth_source(sr: float, seconds: float, f0_hz: float) -> np.ndarray:
    n = int(sr * seconds)
    t = np.arange(n, dtype=np.float64) / sr
    sweep = np.sin(TAU * (95.0 * seconds / math.log(620.0 / 95.0)) *
                   (np.exp(t * math.log(620.0 / 95.0) / seconds) - 1.0))
    buzz = np.zeros_like(t)
    base = f0_hz
    for harmonic in range(1, 34):
        buzz += (1.0 / harmonic) * np.sin(TAU * base * harmonic * t)
    transient = np.sin(TAU * 1850.0 * t) * np.exp(-t * 6.0)
    source = 0.35 * sweep + 0.32 * buzz + 0.08 * transient
    ramp_n = min(n, int(sr * 0.025))
    envelope = np.ones(n, dtype=np.float64)
    envelope[:ramp_n] = np.linspace(0.0, 1.0, ramp_n)
    source *= envelope
    source = np.asarray(source, dtype=np.float64)
    source /= max(1e-9, float(np.max(np.abs(source))))
    return (source * 0.35).astype("<f4")


def write_wav(path: Path, audio: np.ndarray, sr: float) -> None:
    pcm = np.asarray(audio, dtype=np.float32)
    pcm = pcm / max(1.0, float(np.max(np.abs(pcm))))
    i16 = np.clip(pcm * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(round(sr)))
        wf.writeframes(i16.tobytes())


def render_auditions(body: bytes, out_dir: Path, sr: float, f0_hz: float) -> list[str]:
    if not trench_ffi.engine_available():
        return []
    src = synth_source(sr, 5.0, f0_hz)
    write_wav(out_dir / "dry_source.wav", src, sr)
    block = 512
    blocks = max(1, (len(src) + block - 1) // block)

    renders = []
    jobs = {
        "home.wav": ([0.0] * blocks, [0.0] * blocks),
        "away.wav": ([1.0] * blocks, [0.0] * blocks),
        "tight_home.wav": ([0.0] * blocks, [1.0] * blocks),
        "diagonal_walk.wav": (
            [i / max(1, blocks - 1) for i in range(blocks)],
            [i / max(1, blocks - 1) for i in range(blocks)],
        ),
        "morph_walk.wav": (
            [i / max(1, blocks - 1) for i in range(blocks)],
            [0.35] * blocks,
        ),
    }
    for filename, (morph, secondary) in jobs.items():
        out = trench_ffi.engine_render_automated(
            body,
            morph,
            secondary,
            src.tobytes(),
            sr=sr,
            agc_enabled=True,
            agc_drive=3.0,
            block=block,
        )
        audio = np.frombuffer(out, dtype="<f4").copy()
        write_wav(out_dir / filename, audio, sr)
        renders.append(filename)
    return ["dry_source.wav"] + renders


def write_index(out_dir: Path, name: str, report: dict[str, Any]) -> None:
    auditions = report["outputs"].get("auditions", [])
    audio_html = "\n".join(
        f"<div><a href=\"{html.escape(item)}\">{html.escape(item)}</a><br>"
        f"<audio controls src=\"{html.escape(item)}\"></audio></div>"
        for item in auditions
    )
    doc = f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(name)} - Verified Body Forge</title>
<style>
body {{ background:#070a09; color:#d7ded9; font:14px/1.45 system-ui, sans-serif; margin:28px; }}
a {{ color:#85d7ff; }}
.grid {{ display:grid; grid-template-columns: minmax(360px, 1fr) 360px; gap:24px; align-items:start; }}
img {{ width:100%; max-width:1200px; border:1px solid #24332c; }}
code, pre {{ color:#a7f0c1; background:#101713; padding:2px 4px; }}
.card {{ border:1px solid #24332c; padding:14px; background:#0d120f; }}
audio {{ width:100%; margin:4px 0 12px; }}
</style>
<h1>{html.escape(name)}</h1>
<p>Clean-room Hz/radius actor lanes baked to a verified 240-byte packed body.</p>
<div class="grid">
  <div><img src="{html.escape(report['outputs']['plot_png'])}" alt="response plot"></div>
  <div class="card">
    <p><b>Audit:</b> {'PASS' if report['audit']['pass'] else 'FAIL'}</p>
    <p><b>Max pole radius:</b> {report['audit']['max_pole_radius']}</p>
    <p><b>Runtime:</b><br><code>{html.escape(report['audit']['verified_runtime'])}</code></p>
    <p><a href="{html.escape(report['outputs']['body240'])}">.body240</a><br>
       <a href="{html.escape(report['outputs']['cart_json'])}">compiled-v1 JSON</a><br>
       <a href="{html.escape(report['outputs']['actors_json'])}">actor data</a><br>
       <a href="{html.escape(report['outputs']['audit_json'])}">audit JSON</a></p>
    {audio_html}
  </div>
</div>
"""
    (out_dir / "index.html").write_text(doc, encoding="utf-8")


def forge(args: argparse.Namespace) -> dict[str, Any]:
    if not trench_ffi.available():
        raise RuntimeError("trench-core is required. Build it with: cargo build --release -p trench-core")

    name = args.name
    out_dir = args.out / name
    out_dir.mkdir(parents=True, exist_ok=True)

    body, words, actor_doc = build_cleanroom_body(args.sr)
    ffi_body = body_bytes_for_ffi(words)
    if body != ffi_body:
        raise RuntimeError("body serializer mismatch between src.utils.body240 and trench_ffi")

    body_path = out_dir / f"{name}.body240"
    cart_path = out_dir / f"{name}.cart.json"
    actors_path = out_dir / "actors.json"
    audit_path = out_dir / "audit.json"
    plot_path = out_dir / "response.png"

    body_path.write_bytes(body)
    cart_path.write_text(
        json.dumps(compiled_payload(name, args.boost, words), indent=2) + "\n",
        encoding="utf-8",
    )
    actor_doc.update({
        "format": "verified-body-forge-cleanroom-v1",
        "name": name,
        "strategy": {
            "clean_room": True,
            "authoring_surface": "Hz/radius/gain actor lanes",
            "runtime_authority": ".body240 packed words plus trench-core packed_probe",
            "opportunity": "macro pole trajectory plus editable zero relations, then bake to six lanes",
            "vendor_boundary": "No vendor names, bytes, packed tables, coefficients, curves, or presets are used.",
        },
        "source_fundamental_hz": args.f0,
        "authoring_sample_rate_hz": args.sr,
        "corner_order": list(CORNER_ORDER),
        "packed_words": {
            label: [[int(value) for value in row] for row in rows]
            for label, rows in words.items()
        },
    })
    actors_path.write_text(json.dumps(actor_doc, indent=2) + "\n", encoding="utf-8")

    audit = audit_body(body, args.grid, args.sr)
    report = {
        "name": name,
        "body240_sha256": hashlib.sha256(body).hexdigest(),
        "audit": audit,
        "outputs": {
            "body240": body_path.name,
            "cart_json": cart_path.name,
            "actors_json": actors_path.name,
            "audit_json": audit_path.name,
            "plot_png": plot_path.name,
            "auditions": [],
            "index_html": "index.html",
        },
    }

    render_forge_plot(name, body, actor_doc, plot_path, args.sr, args.f0)
    if not args.no_audio:
        report["outputs"]["auditions"] = render_auditions(body, out_dir, args.sr, args.f0)

    audit_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_index(out_dir, name, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean-room actor lanes -> verified .body240 body")
    parser.add_argument("--name", default="cleanroom_macro_pole_forge")
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    parser.add_argument("--sr", type=float, default=AUTHORING_SR)
    parser.add_argument("--boost", type=float, default=1.0)
    parser.add_argument("--grid", type=int, default=9)
    parser.add_argument("--f0", type=float, default=82.0)
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()
    if args.grid < 3:
        raise SystemExit("--grid must be at least 3")

    report = forge(args)
    out_dir = args.out / args.name
    print(f"wrote {out_dir}")
    print(f"body240 sha256 {report['body240_sha256']}")
    print(f"packed audit pass {report['audit']['pass']} max_pole_radius={report['audit']['max_pole_radius']}")
    print(f"open {out_dir / 'index.html'}")


if __name__ == "__main__":
    main()
