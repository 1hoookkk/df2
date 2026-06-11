#!/usr/bin/env python3
"""Author a clean-room study body that articulates "trench work".

This is an audition candidate, not a promoted production body. The body is a
four-corner acoustic surface. A saved Morph/Q path visits the postures in
speech order:

    /tr/ onset -> /eh-n-ch/ -> /w-er/ -> /r-k/ tail

The packed body is useful by itself with a rich sustained source. The enhanced
demo also shapes the excitation with short noise bursts because a filter body
cannot generate consonant timing from silence.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi
from src.utils.body240 import compiled_payload, raw_from_words, render_png
from src.utils.packed_runtime import evaluate_body
from tools.corner_words import corner_words, notch

OUT = ROOT / "dev" / "tmp" / "trench_work_phrase_sharp"
SR = 39_062.5
BLOCK = 128
SECONDS = 2.4


def _posture(
    stages: list[tuple[float, float, float, float]],
) -> list[tuple[int, ...]]:
    """Build six registered pole mountains with explicit sharp zero canyons."""
    if len(stages) != 6:
        raise ValueError("each phrase posture must have exactly six terrain stages")
    return corner_words([
        notch(pole_hz, pole_radius, -0.05, zero_hz, zero_radius)
        for pole_hz, pole_radius, zero_hz, zero_radius in stages
    ])


def build_words() -> dict[str, list[tuple[int, ...]]]:
    """Original acoustic postures, ordered low-to-high for stage registration."""
    return {
        # Five mountain/canyon stages plus one broad tilt stage. The tilt row is
        # deliberately registered in slot 6 across all corners.
        "M0_Q0": _posture([
            (420, .974, 250, .985), (1250, .976, 800, .990),
            (1850, .978, 1550, .992), (2800, .976, 2300, .993),
            (4300, .973, 3600, .996), (820, .930, 12200, .860),
        ]),
        # "trench": /eh/ mountains plus a sharp upper /ch/ release corridor.
        "M100_Q0": _posture([
            (530, .985, 310, .992), (1840, .987, 1080, .995),
            (2480, .985, 2200, .993), (3400, .976, 3000, .994),
            (5000, .980, 4100, .997), (950, .935, 13400, .880),
        ]),
        # "work": rounded /w/ opening into the close F2/F3 /er/ signature.
        "M0_Q100": _posture([
            (350, .982, 240, .990), (900, .982, 650, .993),
            (1350, .987, 1120, .994), (1690, .988, 1510, .995),
            (2600, .976, 2150, .993), (650, .940, 9200, .920),
        ]),
        # Dark /r-k/ tail with a modest upper release.
        "M100_Q100": _posture([
            (430, .980, 270, .990), (1150, .982, 760, .993),
            (1580, .987, 1370, .995), (2200, .978, 1850, .994),
            (3300, .973, 2800, .994), (620, .942, 8000, .930),
        ]),
    }


PATH_POINTS = [
    # seconds, morph, q, label
    (0.00, 0.00, 0.00, "tr onset"),
    (0.20, 0.00, 0.00, "tr onset"),
    (0.36, 1.00, 0.00, "trench vowel"),
    (0.82, 1.00, 0.00, "trench vowel"),
    (1.03, 1.00, 0.00, "ch release"),
    (1.20, 0.00, 1.00, "w-er onset"),
    (1.68, 0.00, 1.00, "work vowel"),
    (2.08, 1.00, 1.00, "r-k tail"),
    (2.40, 1.00, 1.00, "r-k tail"),
]


def _automation(sample_count: int) -> tuple[list[float], list[float]]:
    block_count = max(1, math.ceil(sample_count / BLOCK))
    times = np.arange(block_count) * BLOCK / SR
    point_times = np.array([point[0] for point in PATH_POINTS])
    morph = np.interp(times, point_times, [point[1] for point in PATH_POINTS])
    secondary = np.interp(times, point_times, [point[2] for point in PATH_POINTS])
    return morph.tolist(), secondary.tolist()


def _burst(time: np.ndarray, center: float, width: float, level: float) -> np.ndarray:
    return level * np.exp(-0.5 * ((time - center) / width) ** 2)


def _source(*, consonant_bursts: bool) -> bytes:
    count = int(SECONDS * SR)
    time = np.arange(count) / SR
    rng = np.random.default_rng(7)
    f0 = 96.0 - 8.0 * (time / SECONDS)
    phase = 2.0 * np.pi * np.cumsum(f0) / SR
    # Glottal-source spectral tilt is not constant across an utterance. A
    # smaller exponent is brighter/pressed; a larger exponent is darker and
    # more relaxed. This affects only the audition excitation, never body bytes.
    tilt = np.interp(
        time,
        [0.00, 0.30, 0.82, 1.20, 1.72, 2.40],
        [0.82, 0.95, 1.08, 1.28, 1.36, 1.48],
    )
    voiced = sum(
        np.sin(harmonic * phase) / np.power(float(harmonic), tilt)
        for harmonic in range(1, 56)
    )
    voiced /= max(float(np.max(np.abs(voiced))), 1e-9)
    noise = rng.standard_normal(count)
    noise /= max(float(np.max(np.abs(noise))), 1e-9)

    # Two voiced syllables with a brief join. This envelope is only an audition
    # source; the portable artifact remains the packed four-corner body.
    envelope = (
        0.08
        + _burst(time, 0.52, 0.34, 0.82)
        + _burst(time, 1.62, 0.35, 0.86)
    )
    noise_level = np.full(count, 0.035)
    if consonant_bursts:
        noise_level += _burst(time, 0.12, 0.055, 0.30)  # /tr/
        noise_level += _burst(time, 0.97, 0.075, 0.42)  # /ch/
        noise_level += _burst(time, 2.11, 0.045, 0.26)  # /k/
    audio = 0.30 * voiced * envelope + noise * noise_level
    audio *= 0.72 / max(float(np.max(np.abs(audio))), 1e-9)
    return audio.astype("<f4").tobytes()


def _write_wav(path: Path, audio: bytes) -> None:
    samples = np.frombuffer(audio, dtype="<f4").astype(np.float64)
    peak = float(np.max(np.abs(samples)))
    if peak > 1e-9:
        samples *= 0.92 / peak
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(SR))
        handle.writeframes((np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes())


def _render(body: bytes, source: bytes) -> bytes:
    morph, secondary = _automation(len(source) // 4)
    return trench_ffi.engine_render_automated(
        body, morph, secondary, source, sr=SR, block=BLOCK,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    words = build_words()
    body = raw_from_words(words)
    metrics = evaluate_body(body, 17)
    if not (
        metrics["stable"]
        and metrics["finite"]
        and metrics["grid_unstable_rows"] == 0
        and metrics["grid_nonfinite_rows"] == 0
        and metrics["interior_unstable_rows"] == 0
        and metrics["interior_nonfinite_rows"] == 0
    ):
        raise RuntimeError(f"packed runtime audit failed: {metrics}")

    slug = "trench_work_phrase_sharp"
    body_path = OUT / f"{slug}.body240"
    cart_path = OUT / f"{slug}.cart.json"
    body_path.write_bytes(body)
    payload = compiled_payload("Trench Work Phrase Sharp", 1.0, words)
    payload["provenance"] = "clean-room sharp-zero phrase posture -> packed trench-core audit"
    payload["study_only"] = True
    cart_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    render_png(slug, words, OUT / f"{slug}.png")

    demos = {
        "body_only_sustained_source.wav": _render(body, _source(consonant_bursts=False)),
        "articulation_demo_with_excitation_bursts.wav": _render(body, _source(consonant_bursts=True)),
    }
    for name, audio in demos.items():
        _write_wav(OUT / name, audio)

    report = {
        "name": "Trench Work Phrase Sharp",
        "study_only": True,
        "portable_artifact": body_path.name,
        "body240_sha256": hashlib.sha256(body).hexdigest(),
        "body240_bytes": len(body),
        "engine": "shipped trench_core.dll",
        "path_points": [
            {"seconds": seconds, "morph": morph, "q": q, "label": label}
            for seconds, morph, q, label in PATH_POINTS
        ],
        "auditions": sorted(demos),
        "design_notes": {
            "body": "five registered sharp-zero mountain/canyon stages plus one broad corner-dependent spectral-tilt stage",
            "audition_excitation": "dynamic voiced-source harmonic tilt: bright pressed onset -> darker relaxed work tail",
        },
        "packed_runtime_audit": metrics,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(OUT),
        "body240_bytes": len(body),
        "sha256": report["body240_sha256"],
        "stable": metrics["stable"],
        "finite": metrics["finite"],
        "grid_points": metrics["grid_points"],
        "interior_grid_points": metrics["interior_grid_points"],
        "unstable_rows": metrics["grid_unstable_rows"] + metrics["interior_unstable_rows"],
        "nonfinite_rows": metrics["grid_nonfinite_rows"] + metrics["interior_nonfinite_rows"],
        "auditions": report["auditions"],
    }, indent=2))


if __name__ == "__main__":
    main()
