"""Audio render: pink noise through drive chain + body cascade.

Produces base64-encoded 16-bit mono WAV for web playback.
Uses scipy.signal.sosfilt for C-speed biquad filtering.
"""
from __future__ import annotations

import base64
import io
import struct
import numpy as np
import scipy.signal

from pyruntime.body import Body
from pyruntime.drive import authoring_drive_chain
from pyruntime.encode import EncodedCoeffs

PLUGIN_SR = 44100.0

# Passthrough kernel coefficients (identity filter)
_PASS_C = (2.0, 1.0, 2.0, 1.0, 1.0)


def generate_pink_noise(n_samples: int, sr: float = PLUGIN_SR) -> np.ndarray:
    """Pink noise via spectral shaping (-3 dB/octave slope)."""
    white = np.random.randn(n_samples)
    fft = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n_samples, 1.0 / sr)
    freqs[0] = 1.0
    pink = np.fft.irfft(fft / np.sqrt(freqs), n_samples)
    peak = np.max(np.abs(pink))
    if peak > 0:
        pink *= 0.5 / peak
    return pink


def _is_passthrough(enc: EncodedCoeffs) -> bool:
    return (abs(enc.c0 - 2.0) < 1e-6 and abs(enc.c1 - 1.0) < 1e-6
            and abs(enc.c2 - 2.0) < 1e-6 and abs(enc.c3 - 1.0) < 1e-6
            and abs(enc.c4 - 1.0) < 1e-6)


def _enc_to_sos_row(enc: EncodedCoeffs) -> np.ndarray:
    """Convert one EncodedCoeffs to a scipy SOS row [b0, b1, b2, 1, a1, a2]."""
    a1 = enc.c2 - 2.0
    a2 = 1.0 - enc.c3
    b0 = enc.c4
    b1 = (enc.c0 - 2.0) * enc.c4
    b2 = (1.0 - enc.c1) * enc.c4
    return np.array([b0, b1, b2, 1.0, a1, a2], dtype=np.float64)


def apply_cascade(signal: np.ndarray, encoded_stages: list) -> np.ndarray:
    """Biquad cascade via scipy.signal.sosfilt (C-speed).

    Skips passthrough stages. Clamps output to ±10 post-cascade
    to guard against near-unstable poles.
    """
    active = [enc for enc in encoded_stages if not _is_passthrough(enc)]
    if not active:
        return signal.copy()

    sos = np.vstack([_enc_to_sos_row(enc) for enc in active])
    out = scipy.signal.sosfilt(sos, signal)
    np.nan_to_num(out, copy=False, nan=0.0, posinf=10.0, neginf=-10.0)
    np.clip(out, -10.0, 10.0, out=out)
    return out


def render_from_body(
    body: Body,
    morph: float,
    q: float,
    mackie_amount: float = 0.5,
    erode_amount: float = 0.0,
    corrode_amount: float = 0.0,
    duration: float = 2.0,
    sr: float = PLUGIN_SR,
) -> dict:
    """Render a Body object directly (no JSON round-trip)."""
    n_samples = int(sr * duration)
    signal = generate_pink_noise(n_samples, sr)
    signal = authoring_drive_chain(signal, mackie_amount, erode_amount, corrode_amount, sr)

    encoded_stages = body.corners.interpolate(morph, q)
    signal = apply_cascade(signal, encoded_stages)
    signal = np.clip(signal, -1.0, 1.0)

    peak = float(np.max(np.abs(signal)))
    peak_db = 20.0 * np.log10(max(peak, 1e-20))

    return {
        "audio_b64": signal_to_wav_b64(signal, sr),
        "sample_rate": int(sr),
        "samples": n_samples,
        "peak_db": round(peak_db, 1),
    }


def render_body(
    body_dict: dict | None,
    morph: float,
    q: float,
    mackie_amount: float = 0.5,
    erode_amount: float = 0.0,
    corrode_amount: float = 0.0,
    duration: float = 2.0,
    sr: float = PLUGIN_SR,
) -> dict:
    """Render from a body dict. Parses JSON, delegates to render_from_body."""
    n_samples = int(sr * duration)
    signal = generate_pink_noise(n_samples, sr)
    signal = authoring_drive_chain(signal, mackie_amount, erode_amount, corrode_amount, sr)

    if body_dict is not None and body_dict:
        body = Body.from_dict(body_dict)
        encoded_stages = body.corners.interpolate(morph, q)
        signal = apply_cascade(signal, encoded_stages)

    signal = np.clip(signal, -1.0, 1.0)
    peak = float(np.max(np.abs(signal)))
    peak_db = 20.0 * np.log10(max(peak, 1e-20))

    return {
        "audio_b64": signal_to_wav_b64(signal, sr),
        "sample_rate": int(sr),
        "samples": n_samples,
        "peak_db": round(peak_db, 1),
    }


def signal_to_wav_b64(signal: np.ndarray, sr: float = PLUGIN_SR) -> str:
    """Encode a float signal as base64 16-bit mono PCM WAV."""
    clamped = np.clip(signal, -1.0, 1.0)
    pcm = (clamped * 32767.0).astype(np.int16)

    buf = io.BytesIO()
    n_samples = len(pcm)
    data_size = n_samples * 2

    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, int(sr), int(sr) * 2, 2, 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm.tobytes())

    return base64.b64encode(buf.getvalue()).decode("ascii")


if __name__ == "__main__":
    import time
    t0 = time.perf_counter()
    result = render_body(None, 0.5, 0.5, 0.5, 0.0, 0.0, 0.5, 44100)
    t1 = time.perf_counter()
    print(f"Samples: {result['samples']}, Peak: {result['peak_db']:.1f} dB, Time: {(t1-t0)*1000:.0f} ms")
    assert result['samples'] == 22050
    assert len(result['audio_b64']) > 100
    print("OK")
