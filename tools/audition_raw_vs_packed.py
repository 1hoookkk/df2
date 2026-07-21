#!/usr/bin/env python3
"""Raw-FIR versus packed-body audition for measured DVTD and HRTF targets.

This is an evidence tool, not a fitter.  It deliberately keeps the source
response and the packed projection separate:

    measured complex response / HRIR -> raw FIR -> audio
    existing .body240              -> trench-core runtime -> audio

The packed branch uses the current trench-core FFI for both decode/interpolate
and BODY SOLO audio.  It disables AGC, input drive, saturation, DC blocking,
spatial processing, and amount changes.  Neither branch is normalized per
render.  A second, common-gain preview is written only to make paired listening
practical; its gain is recorded in the report.

Default targets are the endpoint pairs behind the two failed source paths:

  DVTD: s1-01-bahn-tense-a -> s2-03-tiere-tense-i / locked Iron Mouth body
  HRTF: az210/el+00 -> az000/el+00 / locked Pinna Needle body

The input files remain external and read-only.  The output directory is a new
artifact bundle under dev/tmp and contains source/body/library hashes, response
plots, unnormalized proof WAVs, browser-safe listener WAVs, and an HTML player.

Usage:
    python tools/audition_raw_vs_packed.py
    python tools/audition_raw_vs_packed.py --manifest path/to/manifest.json
    python tools/audition_raw_vs_packed.py --out dev/tmp/my-new-audit
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import html
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve, resample_poly


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_SR = 39062.5
WAV_SR = int(round(ANALYSIS_SR))
LISTEN_SR = 48000
LISTEN_RESAMPLE_UP = 768
LISTEN_RESAMPLE_DOWN = 625
LISTEN_TARGET_PEAK = 0.8
LISTEN_MAX_BOOST_DB = 24.0
BODY_BYTES = 240
NUM_STAGES = 6
NUM_COEFFS = 5
NFFT = 65536
RESPONSE_POINTS = 1200
GRID_RES = 17
SOURCE_SECONDS = 3.0
TAIL_SECONDS = 0.75
CORNER_ORDER = (
    ("M0_Q0", 0.0, 0.0),
    ("M100_Q0", 1.0, 0.0),
    ("M0_Q100", 0.0, 1.0),
    ("M100_Q100", 1.0, 1.0),
)
DVTD_FIT_BAND = (100.0, 10000.0)
HRTF_FIT_BAND = (200.0, 16000.0)
PLOT_YLIM = (-80.0, 100.0)
PLOT_SHAPE_YLIM = (-50.0, 50.0)
PLOT_ERROR_YLIM = (-60.0, 60.0)


@dataclass(frozen=True)
class TargetSpec:
    target_id: str
    family: str
    pair_id: str
    source_path: Path
    body_path: Path
    morph: float
    q: float
    azimuth: float | None = None
    elevation: float | None = None
    receiver: int = 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_manifest() -> dict[str, Any]:
    """Return the four requested endpoint targets.

    These are references to read-only source/body artifacts already named in
    the current project evidence.  A caller on another checkout can provide a
    manifest with the same schema.
    """
    filters = Path(r"C:\Users\hooki\trench-filters")
    df2 = Path(r"C:\Users\hooki\df2")
    iron = df2 / "dev" / "tmp" / "exhausted_shipping_filters_locked" / "ship_iron_mouth" / "ship_iron_mouth.body240"
    pinna = df2 / "dev" / "tmp" / "exhausted_shipping_filters_locked" / "ship_pinna_needle" / "ship_pinna_needle.body240"
    return {
        "format": "trench-raw-fir-vs-packed-manifest-v1",
        "analysis_sample_rate_hz": ANALYSIS_SR,
        "wav_sample_rate_hz": WAV_SR,
        "targets": [
            {
                "id": "dvtd_iron_mouth_s1_a",
                "family": "dvtd",
                "pair": "dvtd_iron_mouth_endpoints",
                "source_path": str(filters / "data" / "vocal" / "dvtd" / "subject-1" / "s1-01-bahn-tense-a" / "s1-01-bahn-tense-a-vvtf-measured.txt"),
                "body_path": str(iron),
                "morph": 0.0,
                "q": 0.0,
            },
            {
                "id": "dvtd_iron_mouth_s2_i",
                "family": "dvtd",
                "pair": "dvtd_iron_mouth_endpoints",
                "source_path": str(filters / "data" / "vocal" / "dvtd" / "subject-2" / "s2-03-tiere-tense-i" / "s2-03-tiere-tense-i-vvtf-measured.txt"),
                "body_path": str(iron),
                "morph": 1.0,
                "q": 0.0,
            },
            {
                "id": "hrtf_pinna_needle_az210",
                "family": "hrtf",
                "pair": "hrtf_pinna_needle_endpoints",
                "source_path": str(filters / "data" / "hrtf" / "sonicom_P0001_FreeFieldComp_48kHz.sofa"),
                "body_path": str(pinna),
                "morph": 0.0,
                "q": 0.0,
                "azimuth": 210.0,
                "elevation": 0.0,
                "receiver": 0,
            },
            {
                "id": "hrtf_pinna_needle_az000",
                "family": "hrtf",
                "pair": "hrtf_pinna_needle_endpoints",
                "source_path": str(filters / "data" / "hrtf" / "sonicom_P0001_FreeFieldComp_48kHz.sofa"),
                "body_path": str(pinna),
                "morph": 1.0,
                "q": 0.0,
                "azimuth": 0.0,
                "elevation": 0.0,
                "receiver": 0,
            },
        ],
    }


def resolve_manifest(raw: dict[str, Any], manifest_path: Path | None) -> list[TargetSpec]:
    if raw.get("format") not in (None, "trench-raw-fir-vs-packed-manifest-v1"):
        raise ValueError(f"unsupported manifest format: {raw.get('format')!r}")
    base = manifest_path.parent if manifest_path else ROOT

    def path_value(value: str) -> Path:
        path = Path(os.path.expandvars(value))
        return path if path.is_absolute() else (base / path)

    targets: list[TargetSpec] = []
    for entry in raw.get("targets", []):
        if not isinstance(entry, dict):
            raise ValueError("each manifest target must be an object")
        family = str(entry.get("family", "")).lower()
        if family not in ("dvtd", "hrtf"):
            raise ValueError(f"target {entry.get('id')!r}: family must be dvtd or hrtf")
        try:
            spec = TargetSpec(
                target_id=str(entry["id"]),
                family=family,
                pair_id=str(entry.get("pair", entry["id"])),
                source_path=path_value(str(entry["source_path"])),
                body_path=path_value(str(entry["body_path"])),
                morph=float(entry["morph"]),
                q=float(entry["q"]),
                azimuth=float(entry["azimuth"]) if "azimuth" in entry else None,
                elevation=float(entry["elevation"]) if "elevation" in entry else None,
                receiver=int(entry.get("receiver", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid target entry: {entry!r}") from exc
        if not (0.0 <= spec.morph <= 1.0 and 0.0 <= spec.q <= 1.0):
            raise ValueError(f"target {spec.target_id}: morph/q must be in [0,1]")
        if spec.family == "hrtf" and (spec.azimuth is None or spec.elevation is None):
            raise ValueError(f"target {spec.target_id}: HRTF target needs azimuth/elevation")
        if not spec.source_path.is_file():
            raise FileNotFoundError(f"missing source file for {spec.target_id}: {spec.source_path}")
        if not spec.body_path.is_file():
            raise FileNotFoundError(f"missing body file for {spec.target_id}: {spec.body_path}")
        targets.append(spec)
    if len(targets) != 4:
        raise ValueError(f"expected exactly four targets (two DVTD and two HRTF), got {len(targets)}")
    if sum(t.family == "dvtd" for t in targets) != 2 or sum(t.family == "hrtf" for t in targets) != 2:
        raise ValueError("manifest must contain exactly two DVTD and two HRTF targets")
    return targets


class CoreRuntime:
    """Small FFI adapter; all packing/interpolation/audio remains in trench-core."""

    def __init__(self, library_path: Path):
        self.library_path = library_path.resolve()
        if not self.library_path.is_file():
            raise FileNotFoundError(f"missing trench-core library: {self.library_path}")
        self.lib = ctypes.CDLL(str(self.library_path))
        self._bind()

    def _bind(self) -> None:
        lib = self.lib
        lib.trench_packed_probe.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        lib.trench_packed_probe.restype = ctypes.c_int
        lib.trench_engine_create.restype = ctypes.c_void_p
        lib.trench_engine_destroy.argtypes = [ctypes.c_void_p]
        lib.trench_engine_prepare.argtypes = [ctypes.c_void_p, ctypes.c_double]
        lib.trench_engine_load_body_bytes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        lib.trench_engine_load_body_bytes.restype = ctypes.c_int
        lib.trench_engine_set_input_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_spatial_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_agc_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_dc_block_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_saturation_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_coeff_ramp_scale.argtypes = [ctypes.c_void_p, ctypes.c_float]
        lib.trench_engine_set_interstage_drive.argtypes = [ctypes.c_void_p, ctypes.c_float]
        lib.trench_engine_set_parameters.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
        ]
        lib.trench_engine_process_block.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int,
            ctypes.c_double,
            ctypes.c_double,
        ]

    def probe(self, body: bytes, morph: float, q: float) -> tuple[np.ndarray, float, int, int]:
        if len(body) != BODY_BYTES:
            raise ValueError(f"body must be {BODY_BYTES} bytes, got {len(body)}")
        rows = (ctypes.c_double * (NUM_STAGES * NUM_COEFFS))()
        max_radius = ctypes.c_double()
        unstable = ctypes.c_uint32()
        nonfinite = ctypes.c_uint32()
        body_buf = ctypes.create_string_buffer(body, len(body))
        rc = self.lib.trench_packed_probe(
            body_buf,
            len(body),
            ctypes.c_double(morph),
            ctypes.c_double(q),
            rows,
            ctypes.byref(max_radius),
            ctypes.byref(unstable),
            ctypes.byref(nonfinite),
        )
        if rc != 0:
            raise RuntimeError(f"trench_packed_probe failed (rc={rc})")
        return np.ctypeslib.as_array(rows).copy().reshape(NUM_STAGES, NUM_COEFFS), float(max_radius.value), int(unstable.value), int(nonfinite.value)

    def render(self, body: bytes, source: np.ndarray, morph: float, q: float) -> np.ndarray:
        """Render the static body through the linear BODY SOLO runtime path."""
        if len(body) != BODY_BYTES:
            raise ValueError(f"body must be {BODY_BYTES} bytes, got {len(body)}")
        source = np.asarray(source, dtype=np.float32)
        if source.ndim != 1 or not np.all(np.isfinite(source)):
            raise ValueError("source must be finite mono float32")
        # Let the runtime's coefficient ramp settle before the audible source.
        warmup = np.zeros(128, dtype=np.float32)
        signal = np.ascontiguousarray(np.concatenate((warmup, source)))
        eng = self.lib.trench_engine_create()
        if not eng:
            raise RuntimeError("trench_engine_create returned null")
        try:
            self.lib.trench_engine_prepare(eng, ctypes.c_double(ANALYSIS_SR))
            body_buf = ctypes.create_string_buffer(body, len(body))
            rc = self.lib.trench_engine_load_body_bytes(eng, body_buf, len(body))
            if rc != 0:
                raise RuntimeError(f"trench_engine_load_body_bytes failed (rc={rc})")
            # BODY SOLO: unity I/O and no product-path coloration.
            self.lib.trench_engine_set_input_mode(eng, 0)
            self.lib.trench_engine_set_spatial_mode(eng, 2)
            self.lib.trench_engine_set_agc_enabled(eng, 0)
            self.lib.trench_engine_set_dc_block_enabled(eng, 0)
            self.lib.trench_engine_set_saturation_enabled(eng, 0)
            self.lib.trench_engine_set_coeff_ramp_scale(eng, ctypes.c_float(0.0))
            self.lib.trench_engine_set_interstage_drive(eng, ctypes.c_float(0.0))
            self.lib.trench_engine_set_parameters(
                eng,
                ctypes.c_float(morph),
                ctypes.c_float(q),
                ctypes.c_float(0.0),
                ctypes.c_float(0.0),
                ctypes.c_float(1.0),
            )
            left = (ctypes.c_float * len(signal)).from_buffer(signal)
            right_signal = signal.copy()
            right = (ctypes.c_float * len(right_signal)).from_buffer(right_signal)
            self.lib.trench_engine_process_block(
                eng,
                left,
                right,
                ctypes.c_int(len(signal)),
                ctypes.c_double(morph),
                ctypes.c_double(q),
            )
            output = signal.copy()
            if not np.all(np.isfinite(output)):
                raise RuntimeError("packed runtime produced nonfinite audio")
            return output[128:].astype(np.float64)
        finally:
            self.lib.trench_engine_destroy(eng)


def response_db_from_rows_direct(rows: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    """Magnitude-only form, avoiding any phase algebra in the plot helper."""
    z = np.exp(-2j * np.pi * freqs / ANALYSIS_SR)
    z2 = z * z
    magnitude = np.ones_like(freqs, dtype=np.float64)
    for b0, b1, b2, a1, a2 in rows:
        numerator = b0 + b1 * z + b2 * z2
        denominator = 1.0 + a1 * z + a2 * z2
        magnitude *= np.abs(numerator) / np.maximum(np.abs(denominator), 1e-20)
    return 20.0 * np.log10(np.maximum(magnitude, 1e-20))


def complex_interp(freqs: np.ndarray, values: np.ndarray, query: np.ndarray) -> np.ndarray:
    return np.interp(query, freqs, values.real) + 1j * np.interp(query, freqs, values.imag)


def raw_response_from_fir(fir: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    fft_freqs = np.fft.rfftfreq(NFFT, d=1.0 / ANALYSIS_SR)
    fft_values = np.fft.rfft(fir, n=NFFT)
    return complex_interp(fft_freqs, fft_values, freqs)


def load_dvtd(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    table = np.loadtxt(path, skiprows=1)
    if table.ndim != 2 or table.shape[1] < 3:
        raise ValueError(f"DVTD table has unexpected shape: {table.shape}")
    freqs = table[:, 0].astype(np.float64)
    magnitude = table[:, 1].astype(np.float64)
    phase = table[:, 2].astype(np.float64)
    if not (np.all(np.isfinite(table)) and np.all(np.diff(freqs) > 0.0) and np.all(magnitude >= 0.0)):
        raise ValueError(f"DVTD table is not finite/ordered/nonnegative: {path}")
    source_h = magnitude * np.exp(1j * phase)
    fir_freqs = np.fft.rfftfreq(NFFT, d=1.0 / ANALYSIS_SR)
    if fir_freqs[-1] > freqs[-1] + 1e-6:
        raise ValueError(f"DVTD source ends at {freqs[-1]:.2f} Hz below runtime Nyquist")
    fir_h = complex_interp(freqs, source_h, fir_freqs)
    fir = np.fft.irfft(fir_h, n=NFFT).real
    metadata = {
        "loader": "dvtd_complex_frequency_table",
        "rows": int(len(table)),
        "source_frequency_hz": [float(freqs[0]), float(freqs[-1])],
        "source_magnitude_linear": [float(np.min(magnitude)), float(np.max(magnitude))],
        "source_phase_rad_range": [float(np.min(phase)), float(np.max(phase))],
        "raw_fir_length_samples": int(len(fir)),
        "raw_fir_duration_seconds": float(len(fir) / ANALYSIS_SR),
        "low_frequency_source_note": "DVTD source table retained as supplied; the dataset documents sub-100 Hz values as dummy/placeholder data.",
    }
    return fir.astype(np.float64), source_h, metadata


def load_hrtf(path: Path, azimuth: float, elevation: float, receiver: int) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    with h5py.File(path, "r") as handle:
        positions = np.asarray(handle["SourcePosition"][:], dtype=np.float64)
        matches = np.where(
            np.isclose(positions[:, 0], azimuth, atol=1e-6)
            & np.isclose(positions[:, 1], elevation, atol=1e-6)
        )[0]
        if len(matches) != 1:
            raise ValueError(f"HRTF direction ({azimuth},{elevation}) matched {len(matches)} SOFA rows")
        index = int(matches[0])
        ir = np.asarray(handle["Data.IR"][index, receiver, :], dtype=np.float64)
        input_sr = float(np.asarray(handle["Data.SamplingRate"][:]).reshape(-1)[0])
    if not np.all(np.isfinite(ir)):
        raise ValueError(f"HRTF HRIR is nonfinite: {path} row {index}")
    # 39062.5 / 48000 = 625 / 768 exactly.  Keep the measured waveform, only
    # resampling it to the packed-runtime clock for a like-for-like audition.
    fir = resample_poly(ir, 625, 768)
    raw_h = np.fft.rfft(fir, n=NFFT)
    metadata = {
        "loader": "sofa_simple_free_field_hrir",
        "sofa_row": index,
        "azimuth_deg": float(positions[index, 0]),
        "elevation_deg": float(positions[index, 1]),
        "receiver": int(receiver),
        "input_sample_rate_hz": input_sr,
        "raw_hrir_length_samples": int(len(ir)),
        "resampled_fir_length_samples": int(len(fir)),
        "raw_fir_duration_seconds": float(len(fir) / ANALYSIS_SR),
        "delay_policy": "raw HRIR retained, including measured onset delay; only sample-rate conversion was applied.",
    }
    return fir.astype(np.float64), raw_h, metadata


def make_glottal_source(length: int, seed: int = 17) -> np.ndarray:
    del seed
    t = np.arange(length, dtype=np.float64) / ANALYSIS_SR
    f0 = 112.0 * 2.0 ** (0.17 * np.sin(2.0 * np.pi * 0.19 * t))
    f0 *= 1.0 + 0.018 * np.sin(2.0 * np.pi * 5.2 * t)
    phase = np.cumsum(2.0 * np.pi * f0 / ANALYSIS_SR)
    source = np.zeros_like(t)
    for harmonic in range(1, 28):
        source += np.sin(harmonic * phase) / harmonic ** 1.22
    phrase = 0.78 + 0.22 * np.sin(2.0 * np.pi * 0.31 * t) ** 2
    source *= phrase
    source *= 0.025 / max(float(np.max(np.abs(source))), 1e-12)
    return source


def make_pink_source(length: int, seed: int = 20260720) -> np.ndarray:
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(length)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(length, d=1.0 / ANALYSIS_SR)
    scale = np.ones_like(freqs)
    scale[1:] = 1.0 / np.sqrt(np.maximum(freqs[1:], 1.0))
    source = np.fft.irfft(spectrum * scale, n=length).real
    source -= np.mean(source)
    source *= 0.08 / max(float(np.max(np.abs(source))), 1e-12)
    return source


def write_float_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = np.asarray(samples, dtype=np.float32)
    if not np.all(np.isfinite(values)):
        raise ValueError(f"refusing to write nonfinite WAV: {path}")
    # WAV headers store an integer rate.  The analysis/runtime clock remains
    # 39062.5 Hz in every JSON/plot claim; the file header is the nearest Hz.
    wavfile.write(str(path), WAV_SR, values)


def write_pcm16_wav(path: Path, samples: np.ndarray) -> None:
    """Write a browser-safe listener file without changing the proof arrays."""
    path.parent.mkdir(parents=True, exist_ok=True)
    values = np.asarray(samples, dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError(f"refusing to write nonfinite listener WAV: {path}")
    peak = float(np.max(np.abs(values))) if values.size else 0.0
    if peak > 1.0 + 1e-9:
        raise ValueError(f"listener WAV would clip: {path} peak={peak}")
    pcm = np.rint(np.clip(values, -1.0, 1.0) * 32767.0).astype(np.int16)
    wavfile.write(str(path), LISTEN_SR, pcm)


def listener_samples(samples: np.ndarray) -> np.ndarray:
    """Resample the runtime-clock render to a conventional browser rate."""
    return resample_poly(
        np.asarray(samples, dtype=np.float64),
        LISTEN_RESAMPLE_UP,
        LISTEN_RESAMPLE_DOWN,
    )


def curve_stats(raw_db: np.ndarray, packed_db: np.ndarray, freqs: np.ndarray, band: tuple[float, float]) -> dict[str, Any]:
    mask = (freqs >= band[0]) & (freqs <= band[1])
    raw_band = raw_db[mask]
    packed_band = packed_db[mask]
    raw_centered = raw_db - float(np.median(raw_band))
    packed_centered = packed_db - float(np.median(packed_band))
    residual = packed_db - raw_db
    return {
        "fit_band_hz": [float(band[0]), float(band[1])],
        "raw_median_db": float(np.median(raw_band)),
        "packed_median_db": float(np.median(packed_band)),
        "median_offset_db_packed_minus_raw": float(np.median(packed_band) - np.median(raw_band)),
        "raw_peak_db": float(np.max(raw_band)),
        "packed_peak_db": float(np.max(packed_band)),
        "raw_peak_hz": float(freqs[mask][int(np.argmax(raw_band))]),
        "packed_peak_hz": float(freqs[mask][int(np.argmax(packed_band))]),
        "raw_shape_crown_db": float(np.max(raw_centered[mask])),
        "packed_shape_crown_db": float(np.max(packed_centered[mask])),
        "shape_rms_db": float(np.sqrt(np.mean((packed_centered[mask] - raw_centered[mask]) ** 2))),
        "absolute_rms_db": float(np.sqrt(np.mean(residual[mask] ** 2))),
        "max_abs_error_db": float(np.max(np.abs(residual[mask]))),
    }


def body_response(runtime: CoreRuntime, body: bytes, freqs: np.ndarray, morph: float, q: float) -> tuple[np.ndarray, np.ndarray, float, int, int]:
    rows, max_radius, unstable, nonfinite = runtime.probe(body, morph, q)
    return response_db_from_rows_direct(rows, freqs), rows, max_radius, unstable, nonfinite


def sample_body_surface(runtime: CoreRuntime, body: bytes) -> dict[str, Any]:
    max_radius = 0.0
    unstable_cells = 0
    nonfinite_cells = 0
    for q in np.linspace(0.0, 1.0, GRID_RES):
        for morph in np.linspace(0.0, 1.0, GRID_RES):
            _, radius, unstable, nonfinite = runtime.probe(body, float(morph), float(q))
            max_radius = max(max_radius, radius)
            unstable_cells += int(unstable != 0)
            nonfinite_cells += int(nonfinite != 0)
    return {
        "grid": f"{GRID_RES}x{GRID_RES}",
        "sampled_max_pole_radius": float(max_radius),
        "sampled_unstable_cells": int(unstable_cells),
        "sampled_nonfinite_cells": int(nonfinite_cells),
        "claim_scope": "sampled Morph x Q grid, not continuum proof",
    }


def target_plot(result: dict[str, Any], path: Path) -> None:
    freqs = result["freqs"]
    raw_db = result["raw_db"]
    packed_db = result["packed_db"]
    corners = result["corner_db"]
    band = result["metrics"]["fit_band_hz"]
    raw_center = raw_db - result["metrics"]["raw_median_db"]
    packed_center = packed_db - result["metrics"]["packed_median_db"]
    residual = packed_db - raw_db
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 9.5), facecolor="#080b09")
    axes = axes.ravel()
    for ax in axes:
        ax.set_facecolor("#0d1210")
        ax.grid(True, which="both", color="#29362f", alpha=0.5, linewidth=0.55)
        ax.tick_params(colors="#b8c4bc", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#34443a")
    axes[0].semilogx(freqs, raw_db, color="#e8d39a", linestyle="--", linewidth=1.35, label="raw FIR")
    axes[0].semilogx(freqs, packed_db, color="#61d8ff", linewidth=1.35, label="packed runtime")
    axes[0].set_ylim(*PLOT_YLIM)
    axes[0].set_title("absolute magnitude — shared dB scale", color="#edf3ee")
    axes[0].legend(facecolor="#121b16", edgecolor="#34443a", labelcolor="#edf3ee", fontsize=8)
    axes[1].semilogx(freqs, raw_center, color="#e8d39a", linestyle="--", linewidth=1.35)
    axes[1].semilogx(freqs, packed_center, color="#61d8ff", linewidth=1.35)
    axes[1].set_ylim(*PLOT_SHAPE_YLIM)
    axes[1].set_title("median-centered shape", color="#edf3ee")
    axes[2].semilogx(freqs, residual, color="#ff8973", linewidth=1.25)
    axes[2].axhline(0.0, color="#a8b5ad", linewidth=0.7)
    axes[2].axvspan(band[0], band[1], color="#6fd8a4", alpha=0.08)
    axes[2].set_ylim(*PLOT_ERROR_YLIM)
    axes[2].set_title("packed − raw dB residual", color="#edf3ee")
    colors = {"M0_Q0": "#e8d39a", "M100_Q0": "#61d8ff", "M0_Q100": "#ff8973", "M100_Q100": "#ad9cff"}
    for label, curve in corners.items():
        axes[3].semilogx(freqs, curve, color=colors[label], linewidth=1.05, label=label)
    axes[3].set_ylim(*PLOT_YLIM)
    axes[3].set_title("all four packed corners — Q motion visible", color="#edf3ee")
    axes[3].legend(facecolor="#121b16", edgecolor="#34443a", labelcolor="#edf3ee", fontsize=7)
    for ax in axes:
        ax.set_xlim(30.0, ANALYSIS_SR / 2.0)
        ax.set_xlabel("Hz", color="#b8c4bc", fontsize=8)
        ax.set_ylabel("dB", color="#b8c4bc", fontsize=8)
    fig.suptitle(
        f"{result['target_id']} — {result['family']} · body endpoint ({result['morph']:.0%},{result['q']:.0%})",
        color="#edf3ee", fontsize=13,
    )
    fig.text(
        0.01,
        0.01,
        f"runtime {result['core_sha256'][:12]} · body {result['body_sha256'][:12]} · "
        f"shape RMS {result['metrics']['shape_rms_db']:.2f} dB · sampled max r {result['surface']['sampled_max_pole_radius']:.6f}",
        color="#718178",
        fontsize=7,
    )
    fig.tight_layout(rect=(0.0, 0.025, 1.0, 0.96))
    fig.savefig(path, dpi=115, facecolor=fig.get_facecolor())
    plt.close(fig)


def overview_plot(results: list[dict[str, Any]], path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), facecolor="#080b09")
    for ax, result in zip(axes.ravel(), results):
        ax.set_facecolor("#0d1210")
        ax.grid(True, which="both", color="#29362f", alpha=0.5, linewidth=0.55)
        ax.tick_params(colors="#b8c4bc", labelsize=8)
        ax.semilogx(result["freqs"], result["raw_db"], "--", color="#e8d39a", linewidth=1.15, label="raw FIR")
        ax.semilogx(result["freqs"], result["packed_db"], color="#61d8ff", linewidth=1.15, label="packed runtime")
        ax.set_xlim(30.0, ANALYSIS_SR / 2.0)
        ax.set_ylim(*PLOT_YLIM)
        ax.set_title(result["target_id"], color="#edf3ee", fontsize=10)
        ax.set_xlabel("Hz", color="#b8c4bc", fontsize=8)
        ax.set_ylabel("dB", color="#b8c4bc", fontsize=8)
    axes[0, 0].legend(facecolor="#121b16", edgecolor="#34443a", labelcolor="#edf3ee", fontsize=8)
    fig.suptitle("Raw FIR versus packed runtime — four-target audit / shared dB scale", color="#edf3ee", fontsize=14)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.96))
    fig.savefig(path, dpi=115, facecolor=fig.get_facecolor())
    plt.close(fig)


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def render_target(runtime: CoreRuntime, spec: TargetSpec, source: np.ndarray, out: Path, core_hash: str) -> dict[str, Any]:
    body = spec.body_path.read_bytes()
    if len(body) != BODY_BYTES:
        raise ValueError(f"{spec.body_path} is {len(body)} bytes, expected {BODY_BYTES}")
    if spec.family == "dvtd":
        fir, source_h, source_metadata = load_dvtd(spec.source_path)
        del source_h
        raw_metadata = source_metadata
        raw_response_factory = lambda freqs: raw_response_from_fir(fir, freqs)
    else:
        assert spec.azimuth is not None and spec.elevation is not None
        fir, source_h, source_metadata = load_hrtf(spec.source_path, spec.azimuth, spec.elevation, spec.receiver)
        del source_h
        raw_metadata = source_metadata
        raw_response_factory = lambda freqs: raw_response_from_fir(fir, freqs)

    freqs = np.geomspace(30.0, ANALYSIS_SR / 2.0 * 0.999, RESPONSE_POINTS)
    raw_h = raw_response_factory(freqs)
    raw_db = 20.0 * np.log10(np.maximum(np.abs(raw_h), 1e-20))
    packed_db, _, endpoint_radius, endpoint_unstable, endpoint_nonfinite = body_response(
        runtime, body, freqs, spec.morph, spec.q
    )
    corner_db: dict[str, np.ndarray] = {}
    corner_rows: dict[str, np.ndarray] = {}
    for label, morph, q in CORNER_ORDER:
        curve, rows, _, _, _ = body_response(runtime, body, freqs, morph, q)
        corner_db[label] = curve
        corner_rows[label] = rows

    fit_band = DVTD_FIT_BAND if spec.family == "dvtd" else HRTF_FIT_BAND
    metrics = curve_stats(raw_db, packed_db, freqs, fit_band)
    result: dict[str, Any] = {
        "target_id": spec.target_id,
        "family": spec.family,
        "pair_id": spec.pair_id,
        "source_path": str(spec.source_path),
        "body_path": str(spec.body_path),
        "source_sha256": sha256_file(spec.source_path),
        "body_sha256": sha256_file(spec.body_path),
        "core_sha256": core_hash,
        "morph": spec.morph,
        "q": spec.q,
        "azimuth_deg": spec.azimuth,
        "elevation_deg": spec.elevation,
        "receiver": spec.receiver,
        "freqs": freqs,
        "raw_db": raw_db,
        "packed_db": packed_db,
        "corner_db": corner_db,
        "corner_rows": corner_rows,
        "metrics": metrics,
        "source_metadata": raw_metadata,
        "endpoint_runtime": {
            "max_pole_radius": endpoint_radius,
            "unstable_mask": endpoint_unstable,
            "nonfinite_mask": endpoint_nonfinite,
        },
        "surface": sample_body_surface(runtime, body),
    }

    source_with_tail = np.concatenate((source, np.zeros(int(round(TAIL_SECONDS * ANALYSIS_SR)), dtype=np.float64)))
    raw_audio = fftconvolve(source_with_tail, fir, mode="full")[: len(source_with_tail)]
    packed_audio = runtime.render(body, source_with_tail, spec.morph, spec.q)
    if len(raw_audio) != len(packed_audio):
        raise RuntimeError(f"audio length mismatch for {spec.target_id}")
    if not (np.all(np.isfinite(raw_audio)) and np.all(np.isfinite(packed_audio))):
        raise RuntimeError(f"nonfinite raw/packed audio for {spec.target_id}")
    result["audio_stats"] = {
        "raw_peak": float(np.max(np.abs(raw_audio))),
        "packed_peak": float(np.max(np.abs(packed_audio))),
        "raw_rms": float(np.sqrt(np.mean(raw_audio * raw_audio))),
        "packed_rms": float(np.sqrt(np.mean(packed_audio * packed_audio))),
        "sample_count": int(len(raw_audio)),
        "analysis_sample_rate_hz": ANALYSIS_SR,
        "wav_sample_rate_hz": WAV_SR,
        "normalization": "none",
    }
    result["raw_audio"] = raw_audio
    result["packed_audio"] = packed_audio
    return result


def add_pair_metrics(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_pair.setdefault(result["pair_id"], []).append(result)
    pair_metrics: list[dict[str, Any]] = []
    for pair_id, members in by_pair.items():
        if len(members) != 2:
            raise ValueError(f"pair {pair_id!r} has {len(members)} members; expected two")
        members = sorted(members, key=lambda item: item["morph"])
        freqs = members[0]["freqs"]
        band = tuple(members[0]["metrics"]["fit_band_hz"])
        mask = (freqs >= band[0]) & (freqs <= band[1])
        raw_a = members[0]["raw_db"].copy()
        raw_b = members[1]["raw_db"].copy()
        packed_a = members[0]["packed_db"].copy()
        packed_b = members[1]["packed_db"].copy()
        raw_a -= float(np.median(raw_a[mask]))
        raw_b -= float(np.median(raw_b[mask]))
        packed_a -= float(np.median(packed_a[mask]))
        packed_b -= float(np.median(packed_b[mask]))
        raw_distance = float(np.sqrt(np.mean((raw_b[mask] - raw_a[mask]) ** 2)))
        packed_distance = float(np.sqrt(np.mean((packed_b[mask] - packed_a[mask]) ** 2)))
        retention = packed_distance / raw_distance if raw_distance > 1e-12 else math.nan

        q0_a = members[0]["corner_db"]["M0_Q0"].copy()
        q0_b = members[1]["corner_db"]["M100_Q0"].copy()
        q100_a = members[0]["corner_db"]["M0_Q100"].copy()
        q100_b = members[1]["corner_db"]["M100_Q100"].copy()
        for curve in (q0_a, q0_b, q100_a, q100_b):
            curve -= float(np.median(curve[mask]))
        # The midpoint is requested from the already generated body by using
        # the Q0 endpoint curves' average as a reference; this is a path-shape
        # diagnostic, not a claim about an unmeasured physical midpoint.
        pair_metrics.append({
            "pair_id": pair_id,
            "family": members[0]["family"],
            "targets": [members[0]["target_id"], members[1]["target_id"]],
            "raw_endpoint_shape_distance_rms_db": raw_distance,
            "packed_endpoint_shape_distance_rms_db": packed_distance,
            "packed_motion_retention_ratio": retention,
            "q0_to_q100_m0_shape_distance_rms_db": float(np.sqrt(np.mean((q100_a[mask] - q0_a[mask]) ** 2))),
            "q0_to_q100_m100_shape_distance_rms_db": float(np.sqrt(np.mean((q100_b[mask] - q0_b[mask]) ** 2))),
            "q0_endpoint_average_reference": "median-centered dB average of the two packed Q0 endpoint curves; not a measured interior target",
            "triage_rule": "heuristic only: low raw distance suggests source ambiguity; high endpoint shape RMS suggests projection loss; low motion retention suggests corner-motion loss",
        })
    return pair_metrics


def write_html(results: list[dict[str, Any]], pair_metrics: list[dict[str, Any]], out: Path) -> None:
    cards: list[str] = []
    diagnostics: list[str] = []
    for result in results:
        target_id = str(result["target_id"])
        target = html.escape(target_id, quote=True)
        family = html.escape(str(result["family"]), quote=True)
        gain_db = float(result["audio_stats"]["common_preview_gain_db"])
        raw_listener = html.escape(f"{target_id}.raw_fir.listen.wav", quote=True)
        packed_listener = html.escape(f"{target_id}.packed_body.listen.wav", quote=True)
        raw_absolute = html.escape(f"{target_id}.raw_fir.absolute.wav", quote=True)
        packed_absolute = html.escape(f"{target_id}.packed_body.absolute.wav", quote=True)
        preview_note = (
            f"same gain for raw and packed at this target: {gain_db:+.1f} dB · "
            f"PCM16 / {LISTEN_SR} Hz listener export"
        )
        cards.append(
            "<section class='listen-card'>"
            f"<div class='card-head'><div><h2>{target}</h2>"
            f"<p class='sub'>{family} · Morph={result['morph']:.0%} · Q={result['q']:.0%}</p></div>"
            f"<span class='gain'>{html.escape(preview_note)}</span></div>"
            "<div class='players'>"
            "<article class='audio-card raw'>"
            "<h3>A — RAW FIR</h3><p>Measured source rendered directly as a finite impulse response.</p>"
            f"<audio controls preload='metadata' src='{raw_listener}' aria-label='{target} raw FIR'></audio>"
            f"<a download href='{raw_listener}'>download listener WAV</a>"
            "</article>"
            "<article class='audio-card packed'>"
            "<h3>B — PACKED BODY</h3><p>Existing `.body240` through the BODY SOLO packed runtime.</p>"
            f"<audio controls preload='metadata' src='{packed_listener}' aria-label='{target} packed body'></audio>"
            f"<a download href='{packed_listener}'>download listener WAV</a>"
            "</article>"
            "</div>"
            f"<p class='stats'>shape RMS {result['metrics']['shape_rms_db']:.2f} dB · "
            f"absolute peaks raw {result['audio_stats']['raw_peak']:.4g}, packed {result['audio_stats']['packed_peak']:.4g}.</p>"
            "</section>"
        )
        diagnostics.append(
            "<details class='diagnostic'>"
            f"<summary>Open diagnostics for {target}</summary>"
            "<p><b>These are plots, not audio.</b> The dashed line is the raw measured FIR; "
            "the cyan line is the packed runtime. The residual is packed minus raw in dB. "
            "The four-corner panel is the same body at its four runtime corners, not four recordings.</p>"
            f"<img src='{target}.response.png' alt='{target} response diagnostics'>"
            "<p class='file-links'>"
            f"<a download href='{raw_absolute}'>unnormalized raw float32 proof WAV</a> · "
            f"<a download href='{packed_absolute}'>unnormalized packed float32 proof WAV</a>"
            "</p></details>"
        )
    pair_text = "".join(
        f"<li>{html.escape(p['pair_id'])}: raw endpoint distance {p['raw_endpoint_shape_distance_rms_db']:.2f} dB; "
        f"packed distance {p['packed_endpoint_shape_distance_rms_db']:.2f} dB; "
        f"motion retention {p['packed_motion_retention_ratio']:.3f}</li>"
        for p in pair_metrics
    )
    style = """
      :root { color-scheme: dark; }
      * { box-sizing: border-box; }
      html, body { margin: 0; padding: 0; min-width: 0; overflow-x: hidden; background: #080b09; color: #edf3ee; }
      body { font: 14px/1.45 system-ui, sans-serif; }
      main { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 64px; }
      h1 { margin: 0 0 8px; font-size: clamp(24px, 4vw, 36px); }
      h2, h3 { margin: 0; }
      h2 { font-size: 19px; }
      h3 { font-size: 15px; letter-spacing: .04em; }
      p { color: #b8c4bc; }
      .notice, .explain { border: 1px solid #34443a; border-radius: 10px; background: #101713; padding: 14px 16px; }
      .explain { margin: 16px 0 20px; }
      .explain p { margin: 5px 0; }
      .explain ul { margin: 8px 0 0 20px; padding: 0; color: #b8c4bc; }
      .listen-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 480px), 1fr)); gap: 16px; }
      .listen-card { min-width: 0; border: 1px solid #405348; border-radius: 12px; background: #0d1210; padding: 18px; }
      .card-head { display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; min-width: 0; }
      .sub, .stats { margin: 4px 0 0; font-size: 12px; }
      .gain { flex: 0 1 auto; border: 1px solid #586f5f; border-radius: 999px; padding: 4px 8px; color: #e8d39a; font-size: 11px; text-align: right; }
      .players { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
      .audio-card { min-width: 0; border-radius: 8px; padding: 12px; background: #121b16; }
      .audio-card.raw { border-left: 3px solid #e8d39a; }
      .audio-card.packed { border-left: 3px solid #61d8ff; }
      .audio-card p { min-height: 42px; margin: 6px 0; font-size: 12px; }
      audio { display: block; width: 100%; max-width: 100%; margin: 8px 0; }
      a { color: #61d8ff; }
      .diagnostic { margin-top: 18px; border-top: 1px solid #34443a; padding-top: 12px; }
      .diagnostic summary { cursor: pointer; color: #e8d39a; }
      .diagnostic img, .overview img { display: block; width: 100%; max-width: 100%; height: auto; margin-top: 12px; background: #0d1210; }
      .file-links { font-size: 12px; }
      .triage { margin-top: 28px; border-top: 1px solid #34443a; padding-top: 18px; }
      .triage ul { color: #b8c4bc; }
      .overview { margin-top: 18px; }
      @media (max-width: 640px) {
        main { width: calc(100% - 20px); padding-top: 14px; }
        .card-head { display: block; }
        .gain { display: inline-block; margin-top: 8px; text-align: left; }
        .players { grid-template-columns: 1fr; }
      }
    """
    document = "\n".join([
        "<!doctype html>",
        "<html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Raw FIR versus packed runtime — listen first</title>",
        f"<style>{style}</style></head><body><main>",
        "<h1>Listen first: raw FIR versus packed body</h1>",
        f"<div class='notice'><b>Press A, then B.</b> These listener files are PCM16 at {LISTEN_SR} Hz. "
        "A and B share one gain at each target so the difference is audible; the gain is not an independent normalization of either render. "
        "The unnormalized float32 files remain available inside each diagnostic panel for proof.</div>",
        "<div class='explain'><p><b>What the old pictures were:</b></p>"
        "<ul><li>absolute magnitude: measured FIR versus packed-runtime frequency response;</li>"
        "<li>median-centered shape: level removed so spectral shape can be compared;</li>"
        "<li>packed − raw residual: error in dB, not a waveform;</li>"
        "<li>all four packed corners: runtime endpoint/corner responses, not four audio tracks.</li></ul></div>",
        "<div class='listen-grid'>" + "".join(cards) + "</div>",
        "<section class='triage'><h2>Pair motion triage</h2><ul>" + pair_text + "</ul></section>",
        "<section class='overview'><details><summary>Open the four-target overview plot</summary><img src='overview.png' alt='four target response overview'></details></section>",
        "".join(diagnostics),
        "</main></body></html>",
    ])
    (out / "index.html").write_text(document, encoding="utf-8")


def write_report(results: list[dict[str, Any]], pair_metrics: list[dict[str, Any]], out: Path, core_path: Path, tool_hash: str) -> None:
    lines = [
        "# Raw FIR versus packed-body audition",
        "",
        "This bundle compares the supplied measured source against the existing packed body at the corresponding Q0 endpoint.",
        "The raw branch is a direct FIR reconstruction; the packed branch is the current `trench-core` BODY SOLO path.",
        "",
        "## Runtime and scope",
        "",
        f"- `OBSERVED`: trench-core library `{core_path}` SHA-256 `{sha256_file(core_path)}`.",
        f"- `OBSERVED`: audit tool SHA-256 `{tool_hash}`.",
        f"- `OBSERVED`: analysis clock `{ANALYSIS_SR} Hz`; unnormalized proof WAV header rate `{WAV_SR} Hz` (nearest integer header representation).",
        f"- `OBSERVED`: listener WAVs are PCM16 at `{LISTEN_SR} Hz`, resampled from the analysis clock with the fixed ratio `{LISTEN_RESAMPLE_UP}/{LISTEN_RESAMPLE_DOWN}`.",
        f"- `OBSERVED`: listener gain is one common gain for raw and packed at each target, capped at +{LISTEN_MAX_BOOST_DB:.0f} dB and targeting {LISTEN_TARGET_PEAK:.1f} peak; it is not per-render normalization.",
        "- `OBSERVED`: no AGC, input drive, saturation, DC blocking, spatial stage, amount taper, or per-render normalization in either runtime render.",
        "- `OBSERVED`: sampled stability grid is 17x17; this is sampled certification, not continuum proof.",
        "",
        "## Endpoint comparison",
        "",
        "| target | raw peak Hz | packed peak Hz | shape RMS | absolute RMS | raw crown | packed crown |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        m = r["metrics"]
        lines.append(
            f"| `{r['target_id']}` | {m['raw_peak_hz']:.0f} | {m['packed_peak_hz']:.0f} | "
            f"{m['shape_rms_db']:.2f} dB | {m['absolute_rms_db']:.2f} dB | "
            f"{m['raw_shape_crown_db']:.2f} dB | {m['packed_shape_crown_db']:.2f} dB |"
        )
    lines += ["", "## Pair/corner motion evidence", "", "| pair | raw endpoint distance | packed endpoint distance | packed motion retention | Q0→Q100 at M0 | Q0→Q100 at M100 |", "|---|---:|---:|---:|---:|---:|"]
    for p in pair_metrics:
        lines.append(
            f"| `{p['pair_id']}` | {p['raw_endpoint_shape_distance_rms_db']:.2f} dB | "
            f"{p['packed_endpoint_shape_distance_rms_db']:.2f} dB | {p['packed_motion_retention_ratio']:.3f} | "
            f"{p['q0_to_q100_m0_shape_distance_rms_db']:.2f} dB | {p['q0_to_q100_m100_shape_distance_rms_db']:.2f} dB |"
        )
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "- `OBSERVED`: the raw-FIR files are the material to audition first; the plots show the same raw and packed responses on fixed shared dB scales.",
        "- `INFERRED`: a large endpoint shape RMS with a preserved raw endpoint distance points at per-corner projection loss.",
        "- `INFERRED`: a low packed motion-retention ratio points at corner/lane motion loss, but no interior raw measurement was supplied here.",
        "- `UNKNOWN`: whether each raw FIR is musically distinctive is an operator listening verdict; this bundle does not replace that verdict with a score.",
        "- `UNKNOWN`: no direct claim about the best new six-lane fit is made by this audit; it diagnoses the existing source/projection/path boundary.",
        "",
        "## Files",
        "",
        "- `index.html`: listen-first A/B player; diagnostics are collapsed below the listener cards.",
        "- `overview.png`: four-target response comparison with shared dB scale.",
        "- `summary.json`: machine-readable hashes, metrics, audio peaks, and sampled stability.",
        "- `*.response.png`: per-target response, centered shape, residual, and all packed corners.",
        "- `*.raw_fir.absolute.wav` / `*.packed_body.absolute.wav`: unnormalized comparison files.",
        "- `*.raw_fir.preview.wav` / `*.packed_body.preview.wav`: float32 common-gain previews at the analysis-clock header rate.",
        f"- `*.raw_fir.listen.wav` / `*.packed_body.listen.wav`: browser-safe PCM16 listener files at {LISTEN_SR} Hz; raw and packed share the target gain.",
    ]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(manifest: dict[str, Any], targets: list[TargetSpec], out: Path, core_path: Path) -> None:
    out.mkdir(parents=True, exist_ok=False)
    core_hash = sha256_file(core_path)
    tool_hash = sha256_file(Path(__file__).resolve())
    source_length = int(round(SOURCE_SECONDS * ANALYSIS_SR))
    sources = {
        "dvtd": make_glottal_source(source_length),
        "hrtf": make_pink_source(source_length),
    }
    write_float_wav(out / "source.dvtd_glottal.wav", np.concatenate((sources["dvtd"], np.zeros(int(round(TAIL_SECONDS * ANALYSIS_SR))))))
    write_float_wav(out / "source.hrtf_pink.wav", np.concatenate((sources["hrtf"], np.zeros(int(round(TAIL_SECONDS * ANALYSIS_SR))))))

    runtime = CoreRuntime(core_path)
    pending: list[tuple[dict[str, Any], np.ndarray, np.ndarray]] = []
    results: list[dict[str, Any]] = []
    for spec in targets:
        print(f"auditioning {spec.target_id} ...", flush=True)
        result = render_target(runtime, spec, sources[spec.family], out, core_hash)
        safe_id = spec.target_id
        raw_audio = result.pop("raw_audio")
        packed_audio = result.pop("packed_audio")
        write_float_wav(out / f"{safe_id}.raw_fir.absolute.wav", raw_audio)
        write_float_wav(out / f"{safe_id}.packed_body.absolute.wav", packed_audio)
        pending.append((result, raw_audio, packed_audio))

    for result, raw_audio, packed_audio in pending:
        safe_id = result["target_id"]
        common_peak = max(result["audio_stats"]["raw_peak"], result["audio_stats"]["packed_peak"], 1e-12)
        common_gain = min(
            10.0 ** (LISTEN_MAX_BOOST_DB / 20.0),
            LISTEN_TARGET_PEAK / common_peak,
        )
        write_float_wav(out / f"{safe_id}.raw_fir.preview.wav", raw_audio * common_gain)
        write_float_wav(out / f"{safe_id}.packed_body.preview.wav", packed_audio * common_gain)
        write_pcm16_wav(out / f"{safe_id}.raw_fir.listen.wav", listener_samples(raw_audio * common_gain))
        write_pcm16_wav(out / f"{safe_id}.packed_body.listen.wav", listener_samples(packed_audio * common_gain))
        result["audio_stats"]["common_preview_gain_linear"] = float(common_gain)
        result["audio_stats"]["common_preview_gain_db"] = float(20.0 * math.log10(max(common_gain, 1e-12)))
        result["audio_stats"]["common_preview_scope"] = "raw and packed at this target"
        result["audio_stats"]["listener_sample_rate_hz"] = LISTEN_SR
        result["audio_stats"]["listener_encoding"] = "PCM16"
        result["audio_stats"]["listener_resample_ratio"] = f"{LISTEN_RESAMPLE_UP}/{LISTEN_RESAMPLE_DOWN}"
        target_plot(result, out / f"{safe_id}.response.png")
        results.append(result)

    pair_metrics = add_pair_metrics(results)
    overview_plot(results, out / "overview.png")
    summary = {
        "format": "trench-raw-fir-vs-packed-report-v2",
        "manifest": jsonable(manifest),
        "runtime": {
            "library_path": str(core_path.resolve()),
            "library_sha256": core_hash,
            "analysis_sample_rate_hz": ANALYSIS_SR,
            "wav_sample_rate_hz": WAV_SR,
            "listener_sample_rate_hz": LISTEN_SR,
            "listener_encoding": "PCM16",
            "listener_resample_ratio": f"{LISTEN_RESAMPLE_UP}/{LISTEN_RESAMPLE_DOWN}",
            "listener_gain_policy": "one common gain for raw and packed at each target; no per-render normalization",
            "listener_target_peak": LISTEN_TARGET_PEAK,
            "listener_max_boost_db": LISTEN_MAX_BOOST_DB,
            "body_solo": True,
            "normalization": "none",
            "sampled_stability_grid": f"{GRID_RES}x{GRID_RES}",
        },
        "tool_sha256": tool_hash,
        "targets": [
            {k: jsonable(v) for k, v in result.items() if k not in ("freqs", "raw_db", "packed_db", "corner_db", "corner_rows")}
            for result in results
        ],
        "pairs": jsonable(pair_metrics),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_html(results, pair_metrics, out)
    write_report(results, pair_metrics, out, core_path, tool_hash)
    print(f"wrote {out}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="JSON manifest; defaults to the four named endpoint pairings")
    parser.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "raw_fir_vs_packed_20260720_audition")
    parser.add_argument(
        "--core-dll",
        type=Path,
        default=ROOT / "dev" / "tmp" / "raw_fir_vs_packed_20260720" / "target" / "release" / "trench_core.dll",
        help="current trench-core shared library; use the isolated build target by default",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.out.exists():
        raise SystemExit(f"refusing to overwrite existing output directory: {args.out}")
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    else:
        manifest = default_manifest()
    targets = resolve_manifest(manifest, args.manifest.resolve() if args.manifest else None)
    build(manifest, targets, args.out, args.core_dll)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
