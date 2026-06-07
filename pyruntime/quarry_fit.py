"""Bounded packed-domain fitting for standalone quarry source envelopes.

Standalone recordings provide spectral identity clues, not uniquely observable
physical filters. Fit their smoothed envelopes inside the cartridge's native
minifloat-decode box so the emitted six-row posture survives packing without a
post-hoc root repair changing the contour.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.signal import resample_poly

from pyruntime import forge_fit, trench_ffi
from pyruntime.desk_compile import min_phase_target
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from pyruntime.packed_interp import coeffs_to_words, words_to_coeffs


DEFAULT_RUNTIME_SR = 39_062.5
DEFAULT_GRID_POINTS = 256
DEFAULT_RESTARTS = 2
DEFAULT_MAX_NFEV = 500
DEFAULT_SHAPE_BAND = (120.0, 7_500.0)
DEFAULT_ENVELOPE_FREQS = np.logspace(math.log10(40.0), math.log10(7_800.0), 192)
DEFAULT_COMPLEX_POLE_RADIUS_BAND = (0.990, 0.998)


@dataclass(frozen=True)
class QuarryFit:
    kernel_rows: list[tuple[float, ...]]
    packed_rows: list[tuple[float, ...]]
    packed_words: list[tuple[int, ...]]
    body_bytes: bytes
    response_null_db: float
    packed_max_pole_radius: float
    packed_unstable_mask: int
    packed_nonfinite_mask: int
    complex_pole_radius_band: tuple[float, float]
    cranked_complex_rows: int


def smooth_audio_envelope(
    samples: np.ndarray,
    sr_in: float,
    *,
    freqs_hz: np.ndarray = DEFAULT_ENVELOPE_FREQS,
    analysis_sr: int = 16_000,
    lifter: int = 64,
) -> tuple[np.ndarray, np.ndarray]:
    """Derive a low-quefrency spectral envelope from a conditioned mono slice."""
    values = np.asarray(samples, dtype=np.float64).flatten()
    if values.size < 64:
        raise ValueError("audio envelope needs at least 64 samples")
    sr_int = int(round(sr_in))
    if sr_int != analysis_sr:
        divisor = math.gcd(sr_int, analysis_sr)
        values = resample_poly(values, analysis_sr // divisor, sr_int // divisor)
    nfft = 1
    while nfft < max(4096, len(values)):
        nfft *= 2
    nfft = min(nfft, 16_384)
    windowed = np.zeros(nfft, dtype=np.float64)
    count = min(len(values), nfft)
    windowed[:count] = values[:count] * np.hanning(count)
    logmag = np.log(np.abs(np.fft.rfft(windowed)) + 1e-9)
    mirrored = np.concatenate((logmag, logmag[-2:0:-1]))
    cepstrum = np.fft.ifft(mirrored).real
    kept = np.zeros_like(cepstrum)
    keep = min(int(lifter), len(cepstrum) // 2 - 1)
    kept[:keep] = cepstrum[:keep]
    kept[-keep + 1:] = cepstrum[-keep + 1:]
    smooth = np.fft.fft(kept).real[: len(logmag)]
    fft_freqs = np.fft.rfftfreq(nfft, 1.0 / analysis_sr)
    envelope_db = 20.0 / math.log(10.0) * smooth
    freqs_hz = np.asarray(freqs_hz, dtype=np.float64)
    sampled = np.interp(freqs_hz, fft_freqs, envelope_db)
    sampled -= float(np.max(sampled))
    return freqs_hz, sampled


def shape_residual_db(
    target_db: np.ndarray,
    fitted_db: np.ndarray,
    freqs_hz: np.ndarray,
    band: tuple[float, float] = DEFAULT_SHAPE_BAND,
) -> float:
    """Gain-independent RMS contour error inside the requested frequency band."""
    freqs_hz = np.asarray(freqs_hz, dtype=np.float64)
    target_db = np.asarray(target_db, dtype=np.float64)
    fitted_db = np.asarray(fitted_db, dtype=np.float64)
    mask = (freqs_hz >= band[0]) & (freqs_hz <= band[1])
    residual = fitted_db[mask] - target_db[mask]
    residual -= float(np.mean(residual))
    return float(np.sqrt(np.mean(residual * residual)))


def packed_response_db(
    fit: QuarryFit,
    freqs_hz: np.ndarray,
    runtime_sr: float = DEFAULT_RUNTIME_SR,
) -> np.ndarray:
    return cascade_response_db(
        [EncodedCoeffs(*row) for row in fit.packed_rows],
        np.asarray(freqs_hz, dtype=np.float64),
        runtime_sr,
    )


def crank_complex_pole_radii(
    kernel_rows: list[tuple[float, ...]],
    radius_band: tuple[float, float] = DEFAULT_COMPLEX_POLE_RADIUS_BAND,
) -> tuple[list[tuple[float, ...]], int]:
    """Clamp resonant complex-pair pole radii while preserving center frequency.

    Real-pole support rows remain untouched. They supply broad tilt/foundation
    behavior; forcing them into the razor band creates accidental whistles.
    """
    radius_lo, radius_hi = (float(value) for value in radius_band)
    if not 0.0 < radius_lo <= radius_hi < 1.0:
        raise ValueError("complex pole radius band must satisfy 0 < lo <= hi < 1")
    projected = []
    changed = 0
    for row in kernel_rows:
        c0, c1, c2, c3, c4 = (float(value) for value in row)
        a1, a2 = c2 - 2.0, 1.0 - c3
        if a2 > 0.0 and a1 * a1 < 4.0 * a2:
            radius = math.sqrt(a2)
            target_radius = float(np.clip(radius, radius_lo, radius_hi))
            if abs(target_radius - radius) > 1.0e-12:
                cos_theta = float(np.clip(-a1 / (2.0 * radius), -1.0, 1.0))
                a1 = -2.0 * target_radius * cos_theta
                a2 = target_radius * target_radius
                c2, c3 = a1 + 2.0, 1.0 - a2
                changed += 1
        projected.append((c0, c1, c2, c3, c4))
    return projected, changed


def fit_envelope(
    source_freqs_hz: np.ndarray,
    source_db: np.ndarray,
    *,
    runtime_sr: float = DEFAULT_RUNTIME_SR,
    grid_points: int = DEFAULT_GRID_POINTS,
    n_restarts: int = DEFAULT_RESTARTS,
    max_nfev: int = DEFAULT_MAX_NFEV,
    seed: int = 0,
    complex_pole_radius_band: tuple[float, float] = DEFAULT_COMPLEX_POLE_RADIUS_BAND,
) -> QuarryFit:
    """Fit a smoothed magnitude envelope into one stable packed six-row posture."""
    source_freqs_hz = np.asarray(source_freqs_hz, dtype=np.float64)
    source_db = np.asarray(source_db, dtype=np.float64)
    if source_freqs_hz.ndim != 1 or source_db.shape != source_freqs_hz.shape:
        raise ValueError("source frequency and magnitude arrays must be matching 1-D arrays")
    if source_freqs_hz.size < 2 or not np.all(np.diff(source_freqs_hz) > 0.0):
        raise ValueError("source frequency grid must contain at least two increasing points")
    if not np.all(np.isfinite(source_db)):
        raise ValueError("source magnitude envelope contains non-finite values")

    fit_freqs, z_inv = forge_fit.fit_grid(runtime_sr, n=grid_points)
    target = min_phase_target(source_freqs_hz, source_db, fit_freqs, sr=runtime_sr)
    solved = forge_fit.fit_corner(
        target,
        fit_freqs,
        z_inv,
        runtime_sr,
        profile="flat",
        n_restarts=n_restarts,
        seed=seed,
        max_nfev=max_nfev,
        tol=1e-8,
    )
    solved_rows = [tuple(float(value) for value in row) for row in solved.kernel]
    kernel_rows, cranked_rows = crank_complex_pole_radii(
        solved_rows,
        complex_pole_radius_band,
    )
    response_null_db = forge_fit._response_null_db(
        np.asarray(kernel_rows, dtype=np.float64),
        z_inv,
        target,
        forge_fit.perceptual_weight(fit_freqs, "flat"),
    )
    packed_words = [tuple(int(value) for value in coeffs_to_words(*row)) for row in kernel_rows]
    packed_rows = [tuple(float(value) for value in words_to_coeffs(row)) for row in packed_words]
    body_bytes = trench_ffi.body_bytes_from_corner_words(
        {letter: packed_words for letter in "ABCD"}
    )
    probe = trench_ffi.packed_probe(body_bytes, 0.0, 0.0)
    unstable = int(probe["unstable_mask"])
    nonfinite = int(probe["nonfinite_mask"])
    if unstable or nonfinite:
        raise RuntimeError(
            "bounded quarry fit failed packed stability gate: "
            f"unstable_mask={unstable:#x} nonfinite_mask={nonfinite:#x}"
        )
    return QuarryFit(
        kernel_rows=kernel_rows,
        packed_rows=packed_rows,
        packed_words=packed_words,
        body_bytes=body_bytes,
        response_null_db=float(response_null_db),
        packed_max_pole_radius=float(probe["max_pole_radius"]),
        packed_unstable_mask=unstable,
        packed_nonfinite_mask=nonfinite,
        complex_pole_radius_band=complex_pole_radius_band,
        cranked_complex_rows=cranked_rows,
    )
