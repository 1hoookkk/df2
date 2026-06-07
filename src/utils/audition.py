"""Engine-rendered production auditions for exported body240 artifacts."""
from __future__ import annotations

from pathlib import Path
import wave

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db, freq_points

AUTHORING_SR = 39_062.5


def reese(secs: float = 3.0, f0: float = 82.4, seed: int = 3) -> bytes:
    count = int(secs * AUTHORING_SR)
    time = np.arange(count) / AUTHORING_SR
    rng = np.random.default_rng(seed)
    audio = np.zeros(count)
    for index in range(7):
        detune, phase = 1.0 + (index - 3) * 0.007, rng.random() * 2.0 * np.pi
        for harmonic in range(1, 30):
            audio += np.sin(2.0 * np.pi * f0 * detune * harmonic * time + phase) / harmonic
    audio *= 0.2 / np.max(np.abs(audio))
    return audio.astype("<f4").tobytes()


def _write_wav(path: Path, audio: bytes) -> None:
    samples = np.clip(np.frombuffer(audio, dtype="<f4"), -1.0, 1.0)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(AUTHORING_SR))
        handle.writeframes((samples * 32767).astype("<i2").tobytes())


def _response(body: bytes, morph: float, secondary: float, freqs: np.ndarray) -> np.ndarray:
    rows = [EncodedCoeffs(*row) for row in trench_ffi.packed_interpolate(body, morph, secondary)]
    return cascade_response_db(rows, freqs)


def _curve_png(body: bytes, name: str, out_dir: Path) -> None:
    freqs = freq_points(512)
    fig, axis = plt.subplots(figsize=(11, 6))
    for morph, secondary, label in ((0.0, 0.0, "home Q0"), (0.5, 0.0, "MIDDLE Q0"),
                                    (1.0, 0.0, "away Q0"), (0.5, 1.0, "MIDDLE Q100")):
        axis.semilogx(freqs, _response(body, morph, secondary, freqs), label=label)
    axis.set(xlim=(80, 19000), ylim=(-60, 40), xlabel="Hz", ylabel="dB", title=name)
    axis.grid(True, which="both", alpha=0.2)
    axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / f"{name}_curve.png", dpi=120)
    plt.close(fig)


SOURCES = {"reese": reese}


def audition(body: bytes, name: str, out_dir: Path, *, source_name: str, drive: float) -> None:
    if source_name not in SOURCES:
        raise ValueError(f"unsupported production audition source: {source_name}")
    source = (np.frombuffer(SOURCES[source_name](), dtype="<f4") * float(drive)).astype("<f4").tobytes()
    blocks = max(1, (len(source) // 4) // 512)
    linear = list(np.linspace(0.0, 1.0, blocks))

    def render(morph, secondary) -> bytes:
        audio = np.frombuffer(trench_ffi.engine_render_automated(body, morph, secondary, source), dtype="<f4").astype(np.float64)
        peak = np.max(np.abs(audio))
        return ((audio * (0.9 / peak)) if peak > 1e-9 else audio).astype("<f4").tobytes()

    _write_wav(out_dir / f"{name}_glide_casualQ.wav", render(linear, [0.0] * blocks))
    _write_wav(out_dir / f"{name}_escalation_midM.wav", render([0.5] * blocks, linear))
    _write_wav(out_dir / f"{name}_diagonal.wav", render(linear, linear))
    _curve_png(body, name, out_dir)
