#!/usr/bin/env python3
"""Generate three original four-corner vocal-terrain capture fixtures.

Each body is a six-row pole-zero program. Every zero is attached to the pole in
its own correspondence lane: it is derived from that lane's pole position and
moves with it. The generated WAV files are offline capture feedstock for
``tools/capture_to_cartridge.py``.

Axes:
    MORPH      the named vocal journey
    SECONDARY  human throat -> synthetic sheen transformation

Rows:
    BODY / F1 / F2 / F3 / CANYON / SHEEN
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
OUT = ROOT / "dev" / "tmp" / "synthetic_voice_terrain_capture_pack"
SR = 44_100
SECONDS = 12.0
IR_SECONDS = 0.45
TARGET_PEAK_DB = -6.0
LANE_NAMES = ("BODY", "F1", "F2", "F3", "CANYON", "SHEEN")
LANE_COLORS = ("#f78166", "#58a6ff", "#3fb950", "#bc8cff", "#e3b341", "#ff7b9c")


VOWELS = {
    "uw": {"label": "/u/ boot", "freqs": (300.0, 870.0, 2240.0), "bws": (55.0, 75.0, 140.0)},
    "iy": {"label": "/i/ beet", "freqs": (270.0, 2290.0, 3010.0), "bws": (55.0, 90.0, 120.0)},
    "aa": {"label": "/a/ father", "freqs": (730.0, 1090.0, 2440.0), "bws": (80.0, 90.0, 160.0)},
    "ao": {"label": "/o/ bought", "freqs": (570.0, 840.0, 2410.0), "bws": (70.0, 80.0, 160.0)},
    "ae": {"label": "/ae/ bat", "freqs": (660.0, 1720.0, 2410.0), "bws": (70.0, 105.0, 150.0)},
    "bender": {
        "label": "synthetic ear bend",
        "freqs": (420.0, 2650.0, 4620.0),
        "bws": (52.0, 95.0, 180.0),
    },
}


PRESETS = (
    {
        "slug": "ouui_sheen",
        "name": "OUUI Sheen",
        "morph": "/u/ rounded-back -> /i/ bright-front",
        "secondary": "human throat -> chrome top-end sheen",
        "from": "uw",
        "to": "iy",
        "strength": 0.72,
        "sheen_hz": (6100.0, 9300.0),
        "sheen_offset_st": (-4.0, -7.5),
    },
    {
        "slug": "ah_ear_bender",
        "name": "AH Ear Bender",
        "morph": "/a/ human throat -> synthetic stretched ear bend",
        "secondary": "open throat -> hollow glass pressure",
        "from": "aa",
        "to": "bender",
        "strength": 1.0,
        "sheen_hz": (5400.0, 10_400.0),
        "sheen_offset_st": (-5.0, -10.0),
    },
    {
        "slug": "ao_ae_halo",
        "name": "AO AE Halo",
        "morph": "/o/ round mouth -> /ae/ open-front halo",
        "secondary": "soft body -> breath-lit halo",
        "from": "ao",
        "to": "ae",
        "strength": 0.52,
        "sheen_hz": (6900.0, 8800.0),
        "sheen_offset_st": (-3.0, -6.0),
    },
)

CORNERS = (
    ("M0_Q0", 0.0, 0.0),
    ("M100_Q0", 1.0, 0.0),
    ("M0_Q100", 0.0, 1.0),
    ("M100_Q100", 1.0, 1.0),
)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def semitones(freq_hz: float, offset_st: float) -> float:
    return freq_hz * (2.0 ** (offset_st / 12.0))


def voice_state(spec: dict, morph: float) -> tuple[np.ndarray, np.ndarray]:
    start = VOWELS[str(spec["from"])]
    end = VOWELS[str(spec["to"])]
    freqs = np.array(start["freqs"]) + (np.array(end["freqs"]) - np.array(start["freqs"])) * morph
    bws = np.array(start["bws"]) + (np.array(end["bws"]) - np.array(start["bws"])) * morph
    return freqs, bws


def paired_actor(
    name: str,
    pole_hz: float,
    pole_bw_hz: float,
    zero_offset_st: float,
    zero_bw_hz: float,
) -> dict[str, float | str]:
    """One correspondence row whose zero follows its own pole."""
    return {
        "name": name,
        "kind": "pole_zero_pair",
        "pole_hz": float(pole_hz),
        "pole_bw_hz": float(pole_bw_hz),
        "zero_offset_st": float(zero_offset_st),
        "zero_hz": float(semitones(pole_hz, zero_offset_st)),
        "zero_bw_hz": float(zero_bw_hz),
    }


def lane_parameters(spec: dict, morph: float, secondary: float) -> list[dict[str, float | str]]:
    """Build six attached pole-zero rows for one point on a vocal surface."""
    freqs, bws = voice_state(spec, morph)
    f1, f2, f3 = freqs
    bw1, bw2, bw3 = bws
    strength = float(spec["strength"])
    pressure = secondary * strength
    width_scale = lerp(1.18, 0.52, pressure)
    canyon_zero_hz = float(np.sqrt(f1 * f2))
    canyon_offset = lerp(1.2, 4.8, pressure)
    canyon_pole_hz = semitones(canyon_zero_hz, -canyon_offset)
    sheen_hz = lerp(float(spec["sheen_hz"][0]), float(spec["sheen_hz"][1]), secondary)
    sheen_offset = lerp(float(spec["sheen_offset_st"][0]), float(spec["sheen_offset_st"][1]), secondary)

    return [
        paired_actor(
            "BODY",
            pole_hz=lerp(185.0, 245.0, pressure),
            pole_bw_hz=lerp(250.0, 165.0, pressure),
            zero_offset_st=lerp(18.0, 24.0, pressure),
            zero_bw_hz=lerp(1450.0, 980.0, pressure),
        ),
        paired_actor(
            "F1",
            pole_hz=float(f1),
            pole_bw_hz=float(bw1 * width_scale),
            zero_offset_st=lerp(-0.7, -2.5, pressure),
            zero_bw_hz=float(bw1 * lerp(3.4, 2.0, pressure)),
        ),
        paired_actor(
            "F2",
            pole_hz=float(f2),
            pole_bw_hz=float(bw2 * width_scale),
            zero_offset_st=lerp(-1.0, -3.4, pressure),
            zero_bw_hz=float(bw2 * lerp(3.0, 1.8, pressure)),
        ),
        paired_actor(
            "F3",
            pole_hz=float(f3),
            pole_bw_hz=float(bw3 * width_scale),
            zero_offset_st=lerp(-0.8, 2.8, pressure),
            zero_bw_hz=float(bw3 * lerp(2.6, 1.7, pressure)),
        ),
        paired_actor(
            "CANYON",
            pole_hz=canyon_pole_hz,
            pole_bw_hz=lerp(720.0, 460.0, pressure),
            zero_offset_st=canyon_offset,
            zero_bw_hz=lerp(470.0, 95.0, pressure),
        ),
        paired_actor(
            "SHEEN",
            pole_hz=sheen_hz,
            pole_bw_hz=lerp(1850.0, 620.0, pressure),
            zero_offset_st=sheen_offset,
            zero_bw_hz=lerp(2700.0, 1100.0, pressure),
        ),
    ]


def actor_sos(actor: dict[str, float | str]) -> np.ndarray:
    pole_hz = float(actor["pole_hz"])
    zero_hz = float(actor["zero_hz"])
    pole_radius = float(np.exp(-np.pi * float(actor["pole_bw_hz"]) / SR))
    zero_radius = float(np.exp(-np.pi * float(actor["zero_bw_hz"]) / SR))
    pole_angle = 2.0 * np.pi * pole_hz / SR
    zero_angle = 2.0 * np.pi * zero_hz / SR
    b = np.array((1.0, -2.0 * zero_radius * np.cos(zero_angle), zero_radius * zero_radius))
    a = np.array((1.0, -2.0 * pole_radius * np.cos(pole_angle), pole_radius * pole_radius))
    # DC-normalize each row. The surface shape comes from pole-zero geometry,
    # not from unrelated per-corner gain changes.
    b *= float(np.sum(a) / np.sum(b))
    return np.concatenate((b, a)).astype(np.float64)


def terrain_sos(spec: dict, morph: float, secondary: float, scalar: float = 1.0) -> np.ndarray:
    sos = np.vstack([actor_sos(actor) for actor in lane_parameters(spec, morph, secondary)])
    sos[0, :3] *= scalar
    return sos


def response_db(sos: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    omega = 2.0 * np.pi * freqs / SR
    _, h = sosfreqz(sos, worN=omega)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-14))


def common_scalar(spec: dict) -> float:
    freqs = np.logspace(np.log10(30.0), np.log10(18_000.0), 4096)
    peak_db = -300.0
    for _, morph, secondary in CORNERS:
        peak_db = max(peak_db, float(np.max(response_db(terrain_sos(spec, morph, secondary), freqs))))
    return 10.0 ** ((TARGET_PEAK_DB - peak_db) / 20.0)


def dry_excitation() -> np.ndarray:
    rng = np.random.default_rng(0x4F555549)
    n = int(SECONDS * SR)
    x = rng.standard_normal(n)
    edge = int(0.025 * SR)
    ramp = np.linspace(0.0, 1.0, edge)
    x[:edge] *= ramp
    x[-edge:] *= ramp[::-1]
    x *= 0.16 / max(float(np.max(np.abs(x))), 1e-30)
    return x.astype(np.float32)


def glottal_source(seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    f0 = 106.0 + 5.0 * np.sin(2.0 * np.pi * 0.42 * t)
    phase = 2.0 * np.pi * np.cumsum(f0) / SR
    x = np.zeros(n, dtype=np.float64)
    for harmonic in range(1, 38):
        x += np.sin(harmonic * phase) / (harmonic ** 1.38)
    rng = np.random.default_rng(0x534845454E)
    x += 0.016 * rng.standard_normal(n)
    return x * (0.24 / max(float(np.max(np.abs(x))), 1e-30))


def write_wav(path: Path, data: np.ndarray) -> None:
    wavfile.write(str(path), SR, np.asarray(data, dtype=np.float32))


def style_axis(ax: plt.Axes, ylim: tuple[float, float]) -> None:
    ax.set_facecolor("#0d1117")
    ax.set_xlim(70.0, 16_000.0)
    ax.set_ylim(*ylim)
    ax.grid(True, which="both", color="#1c2128", lw=0.42)
    ax.tick_params(colors="#8b949e", labelsize=7)
    ax.set_xlabel("Hz", color="#8b949e")
    ax.set_ylabel("dB", color="#8b949e")
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")


def plot_corners(spec: dict, out: Path) -> None:
    freqs = np.logspace(np.log10(70.0), np.log10(16_000.0), 1200)
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.2), facecolor="#0d1117")
    for ax, (corner, morph, secondary) in zip(axes.ravel(), CORNERS):
        style_axis(ax, (-58.0, 42.0))
        lanes = lane_parameters(spec, morph, secondary)
        for lane, color in zip(lanes, LANE_COLORS):
            lane_db = response_db(actor_sos(lane)[None, :], freqs)
            ax.semilogx(freqs, lane_db, color=color, lw=1.0, alpha=0.78,
                        label=str(lane["name"]))
            ax.axvline(float(lane["pole_hz"]), color=color, lw=0.65, alpha=0.42)
            ax.axvline(float(lane["zero_hz"]), color=color, lw=0.65, alpha=0.42, ls=":")
        composite = response_db(terrain_sos(spec, morph, secondary), freqs)
        ax.semilogx(freqs, composite, color="#ffffff", lw=2.5, label="COMPOSITE", zorder=10)
        ax.fill_between(freqs, -58.0, composite, color="#9aef5a", alpha=0.045)
        ax.set_title(f"{corner}   M={morph:.0f}  Q={secondary:.0f}", loc="left",
                     color="#f0f6fc", fontsize=11)
    axes[0, 0].legend(loc="upper right", fontsize=7.2, framealpha=0.2, ncol=2,
                      facecolor="#0d1117", labelcolor="#c9d1d9")
    fig.suptitle(
        f"{spec['name']}: six attached pole-zero rows\n"
        f"MORPH {spec['morph']}   |   Q {spec['secondary']}\n"
        "solid vertical = pole   dotted vertical = its attached zero",
        color="#f0f6fc", fontsize=13, fontweight="bold",
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.89))
    fig.savefig(out / "corner_lanes.png", dpi=145, facecolor="#0d1117")
    plt.close(fig)


def plot_surface(spec: dict, out: Path) -> None:
    freqs = np.logspace(np.log10(70.0), np.log10(16_000.0), 620)
    grid = np.linspace(0.0, 1.0, 5)
    fig, axes = plt.subplots(5, 5, figsize=(12.8, 11.0), facecolor="#0d1117")
    for row, secondary in enumerate(grid[::-1]):
        for col, morph in enumerate(grid):
            ax = axes[row, col]
            ax.set_facecolor("#0d1117")
            db = response_db(terrain_sos(spec, float(morph), float(secondary)), freqs)
            ax.semilogx(freqs, db, color="#9aef5a", lw=1.25)
            ax.fill_between(freqs, -58.0, db, color="#9aef5a", alpha=0.055)
            ax.set_xlim(70.0, 16_000.0)
            ax.set_ylim(-58.0, 42.0)
            ax.grid(True, which="both", color="#1c2128", lw=0.26)
            ax.set_xticks([])
            ax.set_yticks([])
            if row == 4:
                ax.set_xlabel(f"M {morph:.2f}", color="#8b949e", fontsize=7)
            if col == 0:
                ax.set_ylabel(f"Q {secondary:.2f}", color="#8b949e", fontsize=7)
            for spine in ax.spines.values():
                spine.set_edgecolor("#30363d")
    fig.suptitle(
        f"{spec['name']} source-capture surface: Morph journey across, Q transformation upward",
        color="#f0f6fc", fontsize=13, fontweight="bold",
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.965))
    fig.savefig(out / "surface_5x5.png", dpi=145, facecolor="#0d1117")
    plt.close(fig)


def write_audition(spec: dict, scalar: float, out: Path) -> None:
    source = glottal_source(7.5)
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
    audio = np.zeros(n, dtype=np.float64)
    zi = sosfilt_zi(terrain_sos(spec, 0.0, 0.0, scalar)) * 0.0
    for lo in range(0, n, block):
        hi = min(lo + block, n)
        sos = terrain_sos(spec, float(control[lo, 0]), float(control[lo, 1]), scalar)
        audio[lo:hi], zi = sosfilt(sos, source[lo:hi], zi=zi)
    audio = np.nan_to_num(audio)
    audio *= 0.82 / max(float(np.max(np.abs(audio))), 1e-30)
    write_wav(out / "audition_surface_walk.wav", audio)


def capture_command(spec: dict, out: Path) -> str:
    prefix = out.relative_to(ROOT).as_posix()
    return (
        f'python tools/capture_to_cartridge.py --name "{spec["name"]}" '
        f"--dry {prefix}/dry_broadband.wav "
        f"--wet-m0-q0 {prefix}/wet_m0_q0.wav "
        f"--wet-m100-q0 {prefix}/wet_m100_q0.wav "
        f"--wet-m0-q100 {prefix}/wet_m0_q100.wav "
        f"--wet-m100-q100 {prefix}/wet_m100_q100.wav"
    )


def write_fixture(spec: dict, dry: np.ndarray) -> dict:
    out = OUT / str(spec["slug"])
    out.mkdir(parents=True, exist_ok=True)
    write_wav(out / "dry_broadband.wav", dry)
    scalar = common_scalar(spec)
    impulse = np.zeros(int(IR_SECONDS * SR), dtype=np.float64)
    impulse[0] = 1.0
    corners = {}
    for label, morph, secondary in CORNERS:
        sos = terrain_sos(spec, morph, secondary, scalar)
        wet = sosfilt(sos, dry.astype(np.float64))
        ir = sosfilt(sos, impulse)
        write_wav(out / f"wet_{label.lower()}.wav", wet)
        write_wav(out / f"ir_{label.lower()}.wav", ir)
        actors = lane_parameters(spec, morph, secondary)
        corners[label] = {
            "morph": morph,
            "secondary": secondary,
            "wet": f"wet_{label.lower()}.wav",
            "impulse_response": f"ir_{label.lower()}.wav",
            "actors": actors,
            "sos": sos.tolist(),
            "wet_peak": float(np.max(np.abs(wet))),
        }
        print(
            f"{spec['slug']:<14} {label:<9} peak={float(np.max(np.abs(wet))):.5f} "
            f"F2={float(actors[2]['pole_hz']):.0f}->{float(actors[2]['zero_hz']):.0f}Hz "
            f"SHEEN={float(actors[5]['pole_hz']):.0f}->{float(actors[5]['zero_hz']):.0f}Hz"
        )
    plot_corners(spec, out)
    plot_surface(spec, out)
    write_audition(spec, scalar, out)
    command = capture_command(spec, out)
    manifest = {
        "format": "synthetic-voice-terrain-capture-fixture-v1",
        "name": spec["name"],
        "claim": (
            "Original six-row DF-II vocal terrain using adult-male vowel anchors. "
            "Every zero is attached to and derived from the pole in its own row."
        ),
        "sample_rate_hz": SR,
        "lane_order": list(LANE_NAMES),
        "axes": {"morph": spec["morph"], "secondary": spec["secondary"]},
        "global_scalar": scalar,
        "corners": corners,
        "capture_to_cartridge_command": command,
        "capture_fit_warning": (
            "The current generic capture fitter is envelope feedstock only. "
            "Do not assume it preserves these row couplings until row priors are wired through."
        ),
        "sources": ["tables/vowel_formants.json"],
    }
    (out / "ground_truth.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "README.md").write_text(
        f"# {spec['name']}\n\n"
        f"- `MORPH`: {spec['morph']}\n"
        f"- `Q`: {spec['secondary']}\n"
        "- Rows: `BODY / F1 / F2 / F3 / CANYON / SHEEN`\n"
        "- Every row is a coupled pole-zero pair. Zeros follow their row poles.\n\n"
        "## Experimental envelope fit\n\n"
        "The current generic capture fitter does not yet preserve row couplings. "
        "Use this only as envelope-fit feedstock until row priors are wired through.\n\n"
        "```powershell\n"
        f"{command}\n"
        "```\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    dry = dry_excitation()
    manifests = [write_fixture(spec, dry) for spec in PRESETS]
    (OUT / "pack_manifest.json").write_text(
        json.dumps(
            {
                "format": "synthetic-voice-terrain-capture-pack-v1",
                "presets": [
                    {
                        "name": manifest["name"],
                        "directory": str(PRESETS[index]["slug"]),
                        "axes": manifest["axes"],
                    }
                    for index, manifest in enumerate(manifests)
                ],
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    (OUT / "README.md").write_text(
        "# Synthetic voice terrain capture pack\n\n"
        "Three original four-corner source-capture fixtures. Every row is a coupled "
        "pole-zero pair; each zero follows the pole in its own row.\n\n"
        "- `ouui_sheen`: `/u/ -> /i/`, human throat -> chrome top-end sheen\n"
        "- `ah_ear_bender`: `/a/ -> synthetic ear bend`, open throat -> hollow glass pressure\n"
        "- `ao_ae_halo`: `/o/ -> /ae/`, soft body -> breath-lit halo\n\n"
        "These are deterministic source programs and WAV captures, not packed-runtime "
        "proof. The current generic capture fitter still needs row priors before it can "
        "be expected to preserve the attached-zero grammar.\n",
        encoding="utf-8",
    )
    print(f"wrote voice terrain capture pack: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
