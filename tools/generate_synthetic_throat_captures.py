#!/usr/bin/env python3
"""Generate a deterministic four-corner MOUNTAINS + throat capture fixture.

The fixture separates two ideas:

1. An idealized adult-male oral-vowel ghost based on Peterson-Barney formant
   anchors and Klatt-style bandwidths.
2. A six-lane DF-II terrain body built around those real formant locations.

The terrain is not a literal anatomical throat. It is an authored musical
filter starter with a lawful body foundation, three formant mountains, an
explicit canyon, and an air counterweight.

Axes:
    MORPH      /u/ rounded-back -> /i/ bright-front articulation
    SECONDARY  relaxed -> pressured throat terrain

Outputs:
    dev/tmp/synthetic_mountains_throat_captures/
      dry_broadband.wav
      wet_*.wav
      ir_*.wav
      audition_surface_walk.wav
      throat_overlay_contact_sheet.png
      throat_lane_contact_sheet.png
      throat_surface_5x5.png
      ground_truth.json
      README.md
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile
from scipy.signal import sosfilt, sosfilt_zi, sosfreqz


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dev" / "tmp" / "synthetic_mountains_throat_captures"
SR = 44_100
SECONDS = 12.0
IR_SECONDS = 0.45
TARGET_PEAK_DB = -6.0
LANE_NAMES = ("BODY", "F1", "F2", "F3", "CANYON", "AIR")
LANE_COLORS = ("#f78166", "#58a6ff", "#3fb950", "#bc8cff", "#e3b341", "#ff7b9c")

# Peterson-Barney adult-male vowel postures for the moving low formants, with
# Klatt-style fixed high resonators for the oral-vowel ghost.
VOWELS = {
    "u": {
        "label": "/u/ boot",
        "freq_hz": np.array((300.0, 870.0, 2240.0, 3300.0, 3850.0)),
        "bw_hz": np.array((55.0, 75.0, 140.0, 250.0, 200.0)),
    },
    "i": {
        "label": "/i/ beet",
        "freq_hz": np.array((270.0, 2290.0, 3010.0, 3300.0, 3850.0)),
        "bw_hz": np.array((55.0, 90.0, 120.0, 250.0, 200.0)),
    },
}

CORNERS = (
    ("M0_Q0", "u_relaxed", 0.0, 0.0),
    ("M100_Q0", "i_relaxed", 1.0, 0.0),
    ("M0_Q100", "u_pressured", 0.0, 1.0),
    ("M100_Q100", "i_pressured", 1.0, 1.0),
)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_array(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    return a + (b - a) * t


def normalize_sos(b: np.ndarray, a: np.ndarray) -> np.ndarray:
    return np.concatenate((b / a[0], a / a[0])).astype(np.float64)


def peaking_sos(freq_hz: float, q: float, gain_db: float) -> np.ndarray:
    """RBJ peaking biquad: one local pole-zero mountain or canyon."""
    w0 = 2.0 * np.pi * freq_hz / SR
    alpha = np.sin(w0) / (2.0 * q)
    amp = 10.0 ** (gain_db / 40.0)
    b = np.array((1.0 + alpha * amp, -2.0 * np.cos(w0), 1.0 - alpha * amp))
    a = np.array((1.0 + alpha / amp, -2.0 * np.cos(w0), 1.0 - alpha / amp))
    return normalize_sos(b, a)


def shelf_sos(freq_hz: float, gain_db: float, high: bool) -> np.ndarray:
    """RBJ shelf biquad: broad body or remote air counterweight."""
    w0 = 2.0 * np.pi * freq_hz / SR
    amp = 10.0 ** (gain_db / 40.0)
    alpha = np.sin(w0) * np.sqrt(2.0) / 2.0
    beta = 2.0 * np.sqrt(amp) * alpha
    cos_w0 = np.cos(w0)
    if high:
        b = amp * np.array((
            (amp + 1.0) + (amp - 1.0) * cos_w0 + beta,
            -2.0 * ((amp - 1.0) + (amp + 1.0) * cos_w0),
            (amp + 1.0) + (amp - 1.0) * cos_w0 - beta,
        ))
        a = np.array((
            (amp + 1.0) - (amp - 1.0) * cos_w0 + beta,
            2.0 * ((amp - 1.0) - (amp + 1.0) * cos_w0),
            (amp + 1.0) - (amp - 1.0) * cos_w0 - beta,
        ))
    else:
        b = amp * np.array((
            (amp + 1.0) - (amp - 1.0) * cos_w0 + beta,
            2.0 * ((amp - 1.0) - (amp + 1.0) * cos_w0),
            (amp + 1.0) - (amp - 1.0) * cos_w0 - beta,
        ))
        a = np.array((
            (amp + 1.0) + (amp - 1.0) * cos_w0 + beta,
            -2.0 * ((amp - 1.0) + (amp + 1.0) * cos_w0),
            (amp + 1.0) + (amp - 1.0) * cos_w0 - beta,
        ))
    return normalize_sos(b, a)


def oral_formant_sos(freq_hz: float, bw_hz: float) -> np.ndarray:
    """DC-normalized all-pole Klatt-style oral formant section."""
    radius = float(np.exp(-np.pi * bw_hz / SR))
    theta = 2.0 * np.pi * freq_hz / SR
    a1 = -2.0 * radius * np.cos(theta)
    a2 = radius * radius
    dc_gain = 1.0 + a1 + a2
    return np.array((dc_gain, 0.0, 0.0, 1.0, a1, a2), dtype=np.float64)


def formant_parameters(morph: float) -> tuple[np.ndarray, np.ndarray]:
    u = VOWELS["u"]
    i = VOWELS["i"]
    return (
        lerp_array(u["freq_hz"], i["freq_hz"], morph),
        lerp_array(u["bw_hz"], i["bw_hz"], morph),
    )


def oral_ghost_sos(morph: float) -> np.ndarray:
    """Ideal oral-vowel shape used only as the gray acoustic reference."""
    freqs, bws = formant_parameters(morph)
    return np.vstack([oral_formant_sos(freq, bw) for freq, bw in zip(freqs, bws)])


def lane_parameters(morph: float, secondary: float) -> list[dict[str, float | str]]:
    """Return six corresponding terrain actors for one endpoint."""
    freqs, bws = formant_parameters(morph)
    f1, f2, f3 = freqs[:3]
    bw1, bw2, bw3 = bws[:3]
    bandwidth_scale = lerp(1.12, 0.62, secondary)
    return [
        {
            "name": "BODY",
            "kind": "low_shelf",
            "freq_hz": lerp(360.0, 470.0, secondary),
            "gain_db": lerp(4.5, 8.0, secondary),
        },
        {
            "name": "F1",
            "kind": "peak",
            "freq_hz": float(f1),
            "q": float(f1 / (bw1 * bandwidth_scale)),
            "gain_db": lerp(9.0, 14.0, secondary),
        },
        {
            "name": "F2",
            "kind": "peak",
            "freq_hz": float(f2),
            "q": float(f2 / (bw2 * bandwidth_scale)),
            "gain_db": lerp(11.0, 17.0, secondary),
        },
        {
            "name": "F3",
            "kind": "peak",
            "freq_hz": float(f3),
            "q": float(f3 / (bw3 * bandwidth_scale)),
            "gain_db": lerp(7.5, 11.5, secondary),
        },
        {
            "name": "CANYON",
            "kind": "peak",
            "freq_hz": float(np.sqrt(f1 * f2)),
            "q": lerp(1.05, 2.35, secondary),
            "gain_db": lerp(-4.0, -15.0, secondary),
        },
        {
            "name": "AIR",
            "kind": "high_shelf",
            "freq_hz": lerp(6500.0, 5100.0, secondary),
            "gain_db": lerp(1.5, 5.5, secondary),
        },
    ]


def actor_sos(actor: dict[str, float | str]) -> np.ndarray:
    kind = actor["kind"]
    if kind == "peak":
        return peaking_sos(
            float(actor["freq_hz"]),
            float(actor["q"]),
            float(actor["gain_db"]),
        )
    if kind == "low_shelf":
        return shelf_sos(float(actor["freq_hz"]), float(actor["gain_db"]), high=False)
    if kind == "high_shelf":
        return shelf_sos(float(actor["freq_hz"]), float(actor["gain_db"]), high=True)
    raise ValueError(f"unknown actor kind: {kind}")


def throat_terrain_sos(morph: float, secondary: float, scalar: float = 1.0) -> np.ndarray:
    sos = np.vstack([actor_sos(actor) for actor in lane_parameters(morph, secondary)])
    sos[0, :3] *= scalar
    return sos


def foundation_sos(morph: float, secondary: float, scalar: float = 1.0) -> np.ndarray:
    lanes = lane_parameters(morph, secondary)
    sos = np.vstack((actor_sos(lanes[0]), actor_sos(lanes[5])))
    sos[0, :3] *= scalar
    return sos


def response(sos: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    omega = 2.0 * np.pi * freqs / SR
    _, h = sosfreqz(sos, worN=omega)
    return h


def response_db(sos: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(np.abs(response(sos, freqs)), 1e-14))


def common_scalar() -> float:
    """Apply one global gain to every endpoint so relative levels survive."""
    freqs = np.logspace(np.log10(30.0), np.log10(18_000.0), 4096)
    peak = 0.0
    for _, _, morph, secondary in CORNERS:
        peak = max(
            peak,
            float(np.max(np.abs(response(throat_terrain_sos(morph, secondary), freqs)))),
        )
    return (10.0 ** (TARGET_PEAK_DB / 20.0)) / max(peak, 1e-30)


def broadband_excitation() -> np.ndarray:
    """Deterministic white excitation with soft edges for empirical TF capture."""
    rng = np.random.default_rng(0x5448524F4154)
    n = int(SECONDS * SR)
    x = rng.standard_normal(n)
    edge = int(0.025 * SR)
    ramp = np.linspace(0.0, 1.0, edge)
    x[:edge] *= ramp
    x[-edge:] *= ramp[::-1]
    x *= 0.16 / max(float(np.max(np.abs(x))), 1e-30)
    return x.astype(np.float32)


def glottal_source(seconds: float) -> np.ndarray:
    """Harmonic-rich listening excitation, separate from the broadband dry."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    f0 = 108.0 + 4.0 * np.sin(2.0 * np.pi * 0.45 * t)
    phase = 2.0 * np.pi * np.cumsum(f0) / SR
    x = np.zeros(n, dtype=np.float64)
    for harmonic in range(1, 34):
        x += np.sin(harmonic * phase) / (harmonic ** 1.45)
    rng = np.random.default_rng(0x564F494345)
    x += 0.018 * rng.standard_normal(n)
    x *= 0.24 / max(float(np.max(np.abs(x))), 1e-30)
    return x


def write_wav(path: Path, data: np.ndarray) -> None:
    wavfile.write(str(path), SR, np.asarray(data, dtype=np.float32))


def align_peak(db: np.ndarray, target_db: np.ndarray) -> np.ndarray:
    """Align a shape-only ghost to the compared terrain for readable overlays."""
    return db + float(np.max(target_db) - np.max(db))


def style_axis(ax: plt.Axes, ylim: tuple[float, float] = (-42.0, 18.0)) -> None:
    ax.set_facecolor("#0d1117")
    ax.set_xlim(70.0, 15_000.0)
    ax.set_ylim(*ylim)
    ax.grid(True, which="both", color="#1c2128", lw=0.45)
    ax.tick_params(colors="#8b949e", labelsize=7)
    ax.set_xlabel("Hz", color="#8b949e")
    ax.set_ylabel("dB", color="#8b949e")
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")


def plot_overlay_contact_sheet(scalar: float) -> None:
    freqs = np.logspace(np.log10(70.0), np.log10(15_000.0), 1200)
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.2), facecolor="#0d1117")
    for ax, (corner, suffix, morph, secondary) in zip(axes.ravel(), CORNERS):
        style_axis(ax)
        terrain_db = response_db(throat_terrain_sos(morph, secondary, scalar), freqs)
        foundation_db = response_db(foundation_sos(morph, secondary, scalar), freqs)
        oral_db = align_peak(response_db(oral_ghost_sos(morph), freqs), terrain_db)
        lanes = lane_parameters(morph, secondary)
        ax.semilogx(freqs, oral_db, color="#8b949e", lw=1.2, ls="--",
                    label="oral formant ghost")
        ax.semilogx(freqs, foundation_db, color="#e3b341", lw=1.8,
                    label="body + air foundation")
        ax.semilogx(freqs, terrain_db, color="#9aef5a", lw=2.4,
                    label="six-lane throat terrain")
        ax.fill_between(freqs, -42.0, terrain_db, color="#9aef5a", alpha=0.055)
        for lane, color in zip(lanes[1:5], LANE_COLORS[1:5]):
            ax.axvline(float(lane["freq_hz"]), color=color, lw=0.7, alpha=0.55)
            ax.text(float(lane["freq_hz"]), 16.0, str(lane["name"]), color=color,
                    fontsize=7, ha="center", va="top")
        ax.set_title(f"{corner}  {suffix.replace('_', ' ')}", loc="left",
                     color="#f0f6fc", fontsize=11)
    axes[0, 0].legend(loc="lower right", fontsize=7.5, framealpha=0.2,
                      facecolor="#0d1117", labelcolor="#c9d1d9")
    fig.suptitle(
        "MOUNTAINS + throat: real formant anchors carved into a six-lane terrain\n"
        "gray = oral ghost (shape-aligned)   amber = foundation   green = full terrain",
        color="#f0f6fc", fontsize=14, fontweight="bold",
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.925))
    fig.savefig(OUT / "throat_overlay_contact_sheet.png", dpi=145, facecolor="#0d1117")
    plt.close(fig)


def plot_lane_contact_sheet(scalar: float) -> None:
    freqs = np.logspace(np.log10(70.0), np.log10(15_000.0), 1200)
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.2), facecolor="#0d1117")
    for ax, (corner, suffix, morph, secondary) in zip(axes.ravel(), CORNERS):
        style_axis(ax, ylim=(-18.0, 25.0))
        lanes = lane_parameters(morph, secondary)
        for actor, color in zip(lanes, LANE_COLORS):
            actor_db = response_db(actor_sos(actor), freqs)
            ax.semilogx(freqs, actor_db, color=color, lw=1.2, alpha=0.9,
                        label=str(actor["name"]))
        terrain_db = response_db(throat_terrain_sos(morph, secondary), freqs)
        ax.semilogx(freqs, terrain_db, color="#ffffff", lw=2.4,
                    label="COMPOSITE", zorder=10)
        ax.set_title(f"{corner}  {suffix.replace('_', ' ')}", loc="left",
                     color="#f0f6fc", fontsize=11)
    axes[0, 0].legend(loc="upper right", fontsize=7.3, framealpha=0.2, ncol=2,
                      facecolor="#0d1117", labelcolor="#c9d1d9")
    fig.suptitle(
        "Six correspondence lanes: BODY / F1 / F2 / F3 / CANYON / AIR",
        color="#f0f6fc", fontsize=14, fontweight="bold",
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.945))
    fig.savefig(OUT / "throat_lane_contact_sheet.png", dpi=145, facecolor="#0d1117")
    plt.close(fig)


def plot_surface(scalar: float) -> None:
    freqs = np.logspace(np.log10(70.0), np.log10(15_000.0), 620)
    grid = np.linspace(0.0, 1.0, 5)
    fig, axes = plt.subplots(5, 5, figsize=(12.8, 11.0), facecolor="#0d1117")
    for row, secondary in enumerate(grid[::-1]):
        for col, morph in enumerate(grid):
            ax = axes[row, col]
            ax.set_facecolor("#0d1117")
            db = response_db(throat_terrain_sos(float(morph), float(secondary), scalar), freqs)
            ax.semilogx(freqs, db, color="#9aef5a", lw=1.25)
            ax.fill_between(freqs, -42.0, db, color="#9aef5a", alpha=0.06)
            ax.set_xlim(70.0, 15_000.0)
            ax.set_ylim(-42.0, 18.0)
            ax.grid(True, which="both", color="#1c2128", lw=0.28)
            ax.set_xticks([])
            ax.set_yticks([])
            if row == 4:
                ax.set_xlabel(f"M {morph:.2f}", color="#8b949e", fontsize=7)
            if col == 0:
                ax.set_ylabel(f"S {secondary:.2f}", color="#8b949e", fontsize=7)
            for spine in ax.spines.values():
                spine.set_edgecolor("#30363d")
    fig.suptitle(
        "MOUNTAINS + throat surface: Morph /u/ -> /i/, Secondary relaxed -> pressured",
        color="#f0f6fc", fontsize=13, fontweight="bold",
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.965))
    fig.savefig(OUT / "throat_surface_5x5.png", dpi=145, facecolor="#0d1117")
    plt.close(fig)


def write_audition_walk(scalar: float) -> None:
    seconds = 7.5
    source = glottal_source(seconds)
    n = len(source)
    checkpoints = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))
    control = np.zeros((n, 2), dtype=np.float64)
    segment = n // (len(checkpoints) - 1)
    for index, (start, end) in enumerate(zip(checkpoints, checkpoints[1:])):
        lo = index * segment
        hi = n if index == len(checkpoints) - 2 else (index + 1) * segment
        control[lo:hi, 0] = np.linspace(start[0], end[0], hi - lo)
        control[lo:hi, 1] = np.linspace(start[1], end[1], hi - lo)
    block = 128
    out = np.zeros(n, dtype=np.float64)
    zi = sosfilt_zi(throat_terrain_sos(0.0, 0.0, scalar)) * 0.0
    for lo in range(0, n, block):
        hi = min(lo + block, n)
        sos = throat_terrain_sos(float(control[lo, 0]), float(control[lo, 1]), scalar)
        out[lo:hi], zi = sosfilt(sos, source[lo:hi], zi=zi)
    out = np.nan_to_num(out)
    out *= 0.82 / max(float(np.max(np.abs(out))), 1e-30)
    write_wav(OUT / "audition_surface_walk.wav", out)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scalar = common_scalar()
    dry = broadband_excitation()
    write_wav(OUT / "dry_broadband.wav", dry)

    impulse = np.zeros(int(IR_SECONDS * SR), dtype=np.float64)
    impulse[0] = 1.0
    manifest_corners = {}
    for key, suffix, morph, secondary in CORNERS:
        sos = throat_terrain_sos(morph, secondary, scalar)
        wet = sosfilt(sos, dry.astype(np.float64))
        ir = sosfilt(sos, impulse)
        wet_path = OUT / f"wet_{key.lower()}_{suffix}.wav"
        ir_path = OUT / f"ir_{key.lower()}_{suffix}.wav"
        write_wav(wet_path, wet)
        write_wav(ir_path, ir)
        actors = lane_parameters(morph, secondary)
        manifest_corners[key] = {
            "label": suffix,
            "morph": morph,
            "secondary": secondary,
            "wet": wet_path.name,
            "impulse_response": ir_path.name,
            "actors": actors,
            "sos": sos.tolist(),
            "wet_peak": float(np.max(np.abs(wet))),
            "wet_rms": float(np.sqrt(np.mean(wet * wet))),
        }
        print(
            f"{key:9} {suffix:11} wet peak={float(np.max(np.abs(wet))):.5f} "
            f"canyon={float(actors[4]['freq_hz']):.0f}Hz/{float(actors[4]['gain_db']):+.1f}dB"
        )

    plot_overlay_contact_sheet(scalar)
    plot_lane_contact_sheet(scalar)
    plot_surface(scalar)
    write_audition_walk(scalar)

    command = (
        "python tools/capture_to_cartridge.py "
        "--name \"Synthetic Mountains Throat\" "
        "--dry dev/tmp/synthetic_mountains_throat_captures/dry_broadband.wav "
        "--wet-m0-q0 dev/tmp/synthetic_mountains_throat_captures/wet_m0_q0_u_relaxed.wav "
        "--wet-m100-q0 dev/tmp/synthetic_mountains_throat_captures/wet_m100_q0_i_relaxed.wav "
        "--wet-m0-q100 dev/tmp/synthetic_mountains_throat_captures/wet_m0_q100_u_pressured.wav "
        "--wet-m100-q100 dev/tmp/synthetic_mountains_throat_captures/wet_m100_q100_i_pressured.wav"
    )
    manifest = {
        "format": "synthetic-mountains-throat-capture-fixture-v1",
        "claim": (
            "Adult-male oral-vowel formant anchors wrapped in an original six-lane "
            "DF-II musical terrain. This is not literal anatomy."
        ),
        "sample_rate_hz": SR,
        "dry": "dry_broadband.wav",
        "axes": {
            "morph": "/u/ rounded-back -> /i/ bright-front articulation",
            "secondary": (
                "relaxed -> pressured terrain: mountains sharpen, canyon deepens, "
                "body warms, air counterweight rises"
            ),
        },
        "lane_order": list(LANE_NAMES),
        "global_scalar": scalar,
        "global_peak_target_db": TARGET_PEAK_DB,
        "corners": manifest_corners,
        "capture_to_cartridge_command": command,
        "sources": [
            "tables/vowel_formants.json",
            "tables/klatt_1980_bandwidths.json",
        ],
    }
    (OUT / "ground_truth.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / "README.md").write_text(
        "# Synthetic MOUNTAINS + throat capture fixture\n\n"
        "This fixture uses Peterson-Barney adult-male oral-vowel formant anchors "
        "inside an original six-lane DF-II musical terrain. It is an authoring "
        "starter, not literal anatomical proof.\n\n"
        "## Axes\n\n"
        "- `MORPH`: `/u/` rounded-back -> `/i/` bright-front articulation\n"
        "- `SECONDARY`: relaxed -> pressured terrain. It sharpens the three "
        "mountains, deepens the canyon, warms the body foundation, and raises "
        "the air counterweight together.\n\n"
        "## Six correspondence lanes\n\n"
        "`BODY / F1 / F2 / F3 / CANYON / AIR`\n\n"
        "## Fit the four captures\n\n"
        "```powershell\n"
        f"{command}\n"
        "```\n",
        encoding="utf-8",
    )
    print(f"wrote capture fixture: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
