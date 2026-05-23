"""Frequency response computation — numpy vectorized.

Transcribed from runtime/src/freq_response.rs.
"""
import numpy as np
from pyruntime.encode import EncodedCoeffs
from pyruntime.constants import SR, FREQ_MIN, FREQ_MAX, NUM_RESPONSE_POINTS, TWO_PI


def freq_points(n: int = NUM_RESPONSE_POINTS) -> np.ndarray:
    """Log-spaced frequency points from 20 Hz to just under Nyquist."""
    return np.logspace(np.log10(FREQ_MIN), np.log10(FREQ_MAX), n)


def stage_response(enc: EncodedCoeffs, freqs: np.ndarray, sr: float = SR) -> np.ndarray:
    """Complex H(f) for one encoded stage.

    Kernel form: c0, c1, c2, c3, c4.
    Inverse to biquad: a1=c2-2, a2=1-c3, b0=c4, b1=(c0-2)*c4, b2=(1-c1)*c4.
    H(z) = (b0 + b1*z^-1 + b2*z^-2) / (1 + a1*z^-1 + a2*z^-2)
    """
    z_inv = np.exp(-1j * TWO_PI * freqs / sr)
    z_inv2 = z_inv * z_inv

    a1 = enc.c2 - 2.0
    a2 = 1.0 - enc.c3
    b0 = enc.c4
    b1 = (enc.c0 - 2.0) * enc.c4
    b2 = (1.0 - enc.c1) * enc.c4

    num = b0 + b1 * z_inv + b2 * z_inv2
    den = 1.0 + a1 * z_inv + a2 * z_inv2

    return num / den


def cascade_response(
    stages: list, freqs: np.ndarray, sr: float = SR
) -> np.ndarray:
    """Complex cascade response: product of all stage responses."""
    h = np.ones(len(freqs), dtype=complex)
    for enc in stages:
        h *= stage_response(enc, freqs, sr)
    return h


def cascade_response_db(
    stages: list, freqs: np.ndarray, sr: float = SR
) -> np.ndarray:
    """Cascade magnitude in dB."""
    h = cascade_response(stages, freqs, sr)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-20))
