#!/usr/bin/env python3
"""Overlay bare packed |H(z)| against measured driven-chain spectrum.

Cheap diagnostic for one body at one Morph/Secondary point. The measured curve
is a describing function: deterministic pink noise is rendered through the
shipped engine, then Welch PSD(output) / Welch PSD(input) is plotted against
the bare packed cascade from trench_core.dll `packed_probe`.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import struct
import sys
import wave
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402

SR = 39_062.5
FREQ_MIN_HZ = 20.0
FREQ_MAX_HZ = SR * 0.5
EPS = 1.0e-24


def slugify(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "body"


def load_body(path: Path) -> tuple[str, bytes]:
    raw = path.read_bytes()
    if len(raw) == trench_ffi.BODY_BYTES:
        return path.stem, raw

    doc = json.loads(raw.decode("utf-8"))
    if doc.get("format") != "compiled-v1":
        raise ValueError(f"{path}: expected raw 240-byte body or compiled-v1 JSON")
    keyframes = doc.get("keyframes")
    if not isinstance(keyframes, list):
        raise ValueError(f"{path}: compiled-v1 JSON missing keyframes")
    by_label = {str(kf.get("label", "")): kf for kf in keyframes if isinstance(kf, dict)}
    ordered = [by_label[label] for label in ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")]
    words: list[int] = []
    for frame in ordered:
        rows = frame.get("packedWords")
        if not isinstance(rows, list) or len(rows) != trench_ffi.NUM_STAGES:
            raise ValueError(f"{path}: each keyframe needs six packedWords rows")
        for row in rows:
            if not isinstance(row, list) or len(row) != trench_ffi.NUM_COEFFS:
                raise ValueError(f"{path}: each packedWords row needs five words")
            words.extend(int(word) & 0xFFFF for word in row)
    body = struct.pack("<" + "H" * len(words), *words)
    if len(body) != trench_ffi.BODY_BYTES:
        raise ValueError(f"{path}: serialized JSON body is {len(body)} bytes")
    return str(doc.get("name") or path.stem), body


def pink_noise(seconds: float, sr: float, rms: float, seed: int) -> np.ndarray:
    n = max(8192, int(round(seconds * sr)))
    rng = np.random.default_rng(int(seed))
    white = rng.standard_normal(n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    spectrum /= np.sqrt(np.maximum(freqs, 1.0))
    x = np.fft.irfft(spectrum, n)
    x -= float(np.mean(x))
    current_rms = float(np.sqrt(np.mean(x * x)))
    if current_rms > 0.0:
        x *= float(rms) / current_rms
    return x.astype("<f4")


def cascade_db(biquads: list[tuple[float, float, float, float, float]], freqs: np.ndarray, sr: float) -> np.ndarray:
    z1 = np.exp(-1j * 2.0 * np.pi * freqs / sr)
    z2 = z1 * z1
    h = np.ones_like(freqs, dtype=np.complex128)
    for b0, b1, b2, a1, a2 in biquads:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), EPS))


def render_engine(
    body: bytes,
    morph: float,
    secondary: float,
    dry: np.ndarray,
    agc_enabled: bool,
    agc_drive: float,
    slam_drive: float,
    dc_block_enabled: bool,
    saturation_enabled: bool,
) -> np.ndarray:
    if slam_drive > 0.0:
        raw = trench_ffi.engine_render_slam(
            body,
            [float(morph)],
            [float(secondary)],
            dry.astype("<f4").tobytes(),
            slam_drive=float(slam_drive),
            sr=SR,
            agc_enabled=agc_enabled,
            agc_drive=float(agc_drive),
            dc_block_enabled=dc_block_enabled,
            saturation_enabled=saturation_enabled,
        )
    else:
        raw = trench_ffi.engine_render(
            body,
            float(morph),
            float(secondary),
            dry.astype("<f4").tobytes(),
            sr=SR,
            input_mode=0,
            spatial_mode=2,
            agc_enabled=agc_enabled,
            agc_drive=float(agc_drive),
            dc_block_enabled=dc_block_enabled,
            saturation_enabled=saturation_enabled,
        )
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


def measured_response_db(
    dry: np.ndarray,
    wet: np.ndarray,
    sr: float,
    discard_seconds: float,
    nperseg: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    start = min(len(dry) - 2, max(0, int(round(discard_seconds * sr))))
    dry_seg = np.asarray(dry[start:], dtype=np.float64)
    wet_seg = np.asarray(wet[start:], dtype=np.float64)
    n = min(len(dry_seg), len(wet_seg))
    dry_seg = dry_seg[:n]
    wet_seg = wet_seg[:n]
    nperseg = max(256, min(int(nperseg), n))
    freqs, pxx = welch(dry_seg, fs=sr, nperseg=nperseg, noverlap=nperseg // 2, detrend="constant", scaling="density")
    _, pyy = welch(wet_seg, fs=sr, nperseg=nperseg, noverlap=nperseg // 2, detrend="constant", scaling="density")
    response = 10.0 * np.log10(np.maximum(pyy, EPS) / np.maximum(pxx, EPS))
    return freqs, response, pxx, pyy


def write_wav16(path: Path, samples: np.ndarray, sr: float) -> None:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(round(sr)))
        handle.writeframes(pcm.tobytes())


def band_mask(freqs: np.ndarray) -> np.ndarray:
    return (freqs >= 80.0) & (freqs <= 12_000.0)


def write_csv(path: Path, rows: list[dict[str, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def plot_overlay(
    out_png: Path,
    title: str,
    freqs: np.ndarray,
    bare: np.ndarray,
    driven: np.ndarray,
    driven_aligned: np.ndarray,
    residual: np.ndarray,
    metrics: dict[str, float | str | bool],
) -> None:
    fig, (ax, res_ax) = plt.subplots(
        2,
        1,
        figsize=(11.2, 7.4),
        dpi=155,
        sharex=True,
        gridspec_kw={"height_ratios": [3.0, 1.15]},
    )
    fig.patch.set_facecolor("#f7f3ea")
    for axis in (ax, res_ax):
        axis.set_facecolor("#fffaf0")
        axis.grid(True, which="both", lw=0.38, alpha=0.28)
        axis.set_xlim(FREQ_MIN_HZ, FREQ_MAX_HZ)

    ax.semilogx(freqs, bare, color="#171717", lw=1.65, label="bare packed cascade |H(z)|")
    ax.semilogx(freqs, driven, color="#bf3a31", lw=1.05, alpha=0.55, label="driven measured PSD ratio")
    ax.semilogx(freqs, driven_aligned, color="#2464a8", lw=1.35, label="driven measured, median-aligned")
    ax.axhline(0.0, color="#777777", lw=0.7, alpha=0.55)
    ax.set_ylabel("dB")
    ax.set_title(title, fontsize=13, loc="left")
    ax.legend(loc="best", fontsize=8, frameon=True)
    text = (
        f"feature RMS {metrics['feature_rms_db']:.2f} dB\n"
        f"feature max {metrics['feature_max_abs_db']:.2f} dB\n"
        f"raw median offset {metrics['raw_median_offset_db']:+.2f} dB"
    )
    ax.text(
        0.012,
        0.035,
        text,
        transform=ax.transAxes,
        fontsize=8,
        va="bottom",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "#fffaf0", "edgecolor": "#d0c7b8", "alpha": 0.9},
    )

    res_ax.semilogx(freqs, residual, color="#6f4dbf", lw=1.1)
    res_ax.axhline(0.0, color="#333333", lw=0.7, alpha=0.5)
    res_ax.axhline(3.0, color="#c17f24", lw=0.55, alpha=0.45)
    res_ax.axhline(-3.0, color="#c17f24", lw=0.55, alpha=0.45)
    res_ax.set_ylabel("aligned\nresidual dB")
    res_ax.set_xlabel("Hz")
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("body", type=Path, help="raw 240-byte .body240/.bin or compiled-v1 JSON")
    parser.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "driven_chain_overlay")
    parser.add_argument("--morph", type=float, default=0.5)
    parser.add_argument("--secondary", "--q", dest="secondary", type=float, default=0.5)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--discard", type=float, default=1.0, help="seconds discarded before Welch PSD")
    parser.add_argument("--rms", type=float, default=0.18, help="pink-noise RMS before engine render")
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--nperseg", type=int, default=8192)
    parser.add_argument("--agc-drive", type=float, default=4.0)
    parser.add_argument("--agc-off", action="store_true")
    parser.add_argument("--slam-drive", type=float, default=0.0)
    parser.add_argument("--dc-block-on", action="store_true", help="authoring default is off")
    parser.add_argument("--saturation-on", action="store_true", help="authoring default is off")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not trench_ffi.available():
        raise RuntimeError("packed trench_core FFI unavailable; build target/release/trench_core.dll")
    if not trench_ffi.engine_available():
        raise RuntimeError("engine FFI unavailable; rebuild target/release/trench_core.dll")

    body_path = args.body.resolve()
    name, body = load_body(body_path)
    setting_slug = (
        f"m{int(round(float(args.morph) * 100)):03d}_"
        f"s{int(round(float(args.secondary) * 100)):03d}_"
        f"rms{int(round(float(args.rms) * 10000)):05d}_"
        f"{'agc_off' if args.agc_off else 'agc' + str(float(args.agc_drive)).replace('.', '_')}_"
        f"slam{int(round(max(0.0, min(1.0, float(args.slam_drive))) * 100)):03d}_"
        f"{'dc_on' if args.dc_block_on else 'dc_off'}_"
        f"{'sat_on' if args.saturation_on else 'sat_off'}_"
        f"n{int(args.nperseg)}"
    )
    out_dir = args.out / slugify(body_path.stem) / setting_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    dry = pink_noise(float(args.seconds), SR, float(args.rms), int(args.seed))
    wet = render_engine(
        body,
        float(args.morph),
        float(args.secondary),
        dry,
        agc_enabled=not bool(args.agc_off),
        agc_drive=float(args.agc_drive),
        slam_drive=max(0.0, min(1.0, float(args.slam_drive))),
        dc_block_enabled=bool(args.dc_block_on),
        saturation_enabled=bool(args.saturation_on),
    )

    freqs, driven_db, pxx, pyy = measured_response_db(dry, wet, SR, float(args.discard), int(args.nperseg))
    valid = (freqs >= FREQ_MIN_HZ) & (freqs <= FREQ_MAX_HZ)
    freqs = freqs[valid]
    driven_db = driven_db[valid]

    probe = trench_ffi.packed_probe(body, float(args.morph), float(args.secondary))
    bare_db = cascade_db([tuple(map(float, bq)) for bq in probe["biquad"]], freqs, SR)

    compare = band_mask(freqs)
    raw_offset = float(np.median(driven_db[compare] - bare_db[compare]))
    driven_aligned = driven_db - raw_offset
    residual = driven_aligned - bare_db
    feature_rms = float(np.sqrt(np.mean(residual[compare] * residual[compare])))
    feature_max = float(np.max(np.abs(residual[compare])))

    dry_rms = float(np.sqrt(np.mean(np.asarray(dry, dtype=np.float64) ** 2)))
    wet_rms = float(np.sqrt(np.mean(np.asarray(wet, dtype=np.float64) ** 2)))
    metrics: dict[str, float | str | bool] = {
        "body": str(body_path),
        "name": name,
        "morph": float(args.morph),
        "secondary": float(args.secondary),
        "sample_rate_hz": SR,
        "seconds": float(args.seconds),
        "discard_seconds": float(args.discard),
        "pink_rms": dry_rms,
        "wet_rms": wet_rms,
        "agc_enabled": not bool(args.agc_off),
        "agc_drive": float(args.agc_drive),
        "slam_drive": max(0.0, min(1.0, float(args.slam_drive))),
        "dc_block_enabled": bool(args.dc_block_on),
        "saturation_enabled": bool(args.saturation_on),
        "max_pole_radius": float(probe["max_pole_radius"]),
        "unstable_mask": int(probe["unstable_mask"]),
        "nonfinite_mask": int(probe["nonfinite_mask"]),
        "raw_median_offset_db": raw_offset,
        "feature_rms_db": feature_rms,
        "feature_max_abs_db": feature_max,
        "engine_path": str(trench_ffi.lib_path()),
        "interpretation": (
            "Measured curve is a pink-noise describing function for this level and control point, "
            "not an LTI transfer function. Authoring default is cascade plus AGC only: "
            "input slam off, spatial off, DC block off, final saturation off."
        ),
    }

    rows = [
        {
            "freq_hz": float(freq),
            "bare_db": float(bare),
            "driven_db": float(driven),
            "driven_aligned_db": float(aligned),
            "aligned_residual_db": float(diff),
        }
        for freq, bare, driven, aligned, diff in zip(freqs, bare_db, driven_db, driven_aligned, residual)
    ]

    title = (
        f"{name}: bare cascade vs driven pink-noise response "
        f"(M={float(args.morph):.2f}, Secondary={float(args.secondary):.2f})"
    )
    plot_overlay(out_dir / "bare_vs_driven_overlay.png", title, freqs, bare_db, driven_db, driven_aligned, residual, metrics)
    write_csv(out_dir / "bare_vs_driven_overlay.csv", rows)
    (out_dir / "report.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    write_wav16(out_dir / "dry_pink.wav", dry, SR)
    write_wav16(out_dir / "wet_driven.wav", wet, SR)
    (out_dir / "README.md").write_text(
        "\n".join(
            [
                f"# {name} Driven-Chain Overlay",
                "",
                "OBSERVED: bare curve is `packed_probe` cascade magnitude for the same body and control point.",
                "OBSERVED: measured curve is Welch PSD(output) / Welch PSD(input) after shipped engine render on deterministic pink noise.",
                "OBSERVED: authoring default is AGC only after the cascade; Mackie SLAM, QSound, DC block, and final saturation are off.",
                "INFERRED: aligned residual shows whether feature shapes survive AGC at this operating level.",
                "UNKNOWN: this does not predict transient material; it is a stationary pink-noise describing function.",
                "",
                "## Files",
                "",
                "- `bare_vs_driven_overlay.png`",
                "- `bare_vs_driven_overlay.csv`",
                "- `dry_pink.wav`",
                "- `wet_driven.wav`",
                "- `report.json`",
                "",
                "## Metrics",
                "",
                f"- Feature RMS residual: `{feature_rms:.3f} dB` over 80-12000 Hz.",
                f"- Feature max absolute residual: `{feature_max:.3f} dB` over 80-12000 Hz.",
                f"- Raw median offset: `{raw_offset:+.3f} dB`.",
                f"- Max pole radius at point: `{float(probe['max_pole_radius']):.8f}`.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"wrote {out_dir}")
    print(f"feature_rms_db={feature_rms:.3f}")
    print(f"feature_max_abs_db={feature_max:.3f}")
    print(f"raw_median_offset_db={raw_offset:+.3f}")


if __name__ == "__main__":
    main()
