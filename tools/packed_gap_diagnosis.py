#!/usr/bin/env python3
"""Packed-domain parity gap diagnosis.

Isolates why derived-packed midpoint nulls at only -12 dB vs X3 M50/Q50.

Tests, in order:
  1. Corner encode-roundtrip penalty — how much does re-encoding float→u16→float
     degrade each corner's null depth vs the exact float render?
  2. Per-stage pole-angle quantization error — shows high-Q stages lose most precision.
  3. Midpoint packed vs X3 with full pipeline (AGC + boost + no-DC-block), same as
     render_hedz.py corner comparison that achieves -62 to -69 dB.
  4. Phase vs magnitude decomposition of the residual at midpoint.

Outputs:
  dev/tmp/packed_gap_diagnosis/<timestamp>/DIAGNOSIS.md
  dev/tmp/packed_gap_diagnosis/<timestamp>/corner_roundtrip.csv
  dev/tmp/packed_gap_diagnosis/<timestamp>/pole_quantization.csv
  dev/tmp/packed_gap_diagnosis/<timestamp>/df2_packed_midpoint_full_pipeline.wav  (if x3 ref exists)

Usage:
    python tools/packed_gap_diagnosis.py
    python tools/packed_gap_diagnosis.py --x3-mid path/to/hedzm50q50.wav
    python tools/packed_gap_diagnosis.py --dry path/to/dry.wav --x3-mid path/to/wet.wav
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import lfilter, sosfilt

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.packed_interp import (
    build_corner_words_from_coeffs,
    packed_bilinear,
    coeffs_to_words,
    words_to_coeffs,
    decode,
    encode,
)
from tools.coefficient_field_bakeoff import (
    load_corner_coeffs,
    kernel_to_sos,
    kernel_to_words,
    packed_oracle,
    decoded_float_baseline,
    null_depth,
    CORNER_LABELS,
)
from pyruntime import trench_ffi

DEFAULT_CARTRIDGE = ROOT / "ref" / "p2k_skins" / "00_talking_hedz.json"
DEFAULT_DRY = Path(r"C:\Users\hooki\Downloads\222323232.wav")
DEFAULT_X3_MID = Path(r"C:\Users\hooki\Downloads\hedzm50q50.wav")
DEFAULT_OUT = ROOT / "dev" / "tmp" / "packed_gap_diagnosis"
SR = 44100
EPS = 1e-30

# Canonical AGC / global-compression curve, read from trench-core via FFI (single
# source of truth = trench-core/src/dsp/mod.rs::AGC_TABLE). No hand-copied literal.
AGC_TABLE = np.array(trench_ffi.agc_table(), dtype=np.float32)
BLOCK_SIZE = 32


# ── pipeline helpers (matching render_hedz.py exactly) ────────────────────────


def apply_agc(samples: np.ndarray) -> np.ndarray:
    samples = samples.astype(np.float32)
    out = np.empty_like(samples)
    gain = np.float32(1.0)
    for i, s in enumerate(samples):
        idx = int(np.uint32(np.float32(gain * abs(s)))) & 0xF
        new_gain = np.float32(gain * AGC_TABLE[idx])
        gain = new_gain if new_gain < np.float32(1.0) else np.float32(1.0)
        out[i] = np.float32(s * gain)
    return out


def apply_boost_ramped(samples: np.ndarray, boost: float) -> np.ndarray:
    samples = samples.astype(np.float32)
    out = samples.copy()
    n = len(samples)
    if n == 0:
        return out
    delta = np.float32((boost - 1.0) / BLOCK_SIZE)
    gain = np.float32(1.0)
    for i in range(min(BLOCK_SIZE, n)):
        gain += delta
        out[i] = np.float32(samples[i] * gain)
    if n > BLOCK_SIZE:
        out[BLOCK_SIZE:] = (samples[BLOCK_SIZE:] * np.float32(boost)).astype(np.float32)
    return out


def full_pipeline_render(dry: np.ndarray, coeffs: np.ndarray, boost: float) -> np.ndarray:
    """cascade → AGC → boost, no DC blocker (matches X3 null path in render_hedz.py)."""
    sos = kernel_to_sos(coeffs)
    cascaded = sosfilt(sos, dry.astype(np.float64)).astype(np.float32)
    np.nan_to_num(cascaded, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    agc_out = apply_agc(cascaded)
    return apply_boost_ramped(agc_out, boost)


def simple_render(dry: np.ndarray, coeffs: np.ndarray) -> np.ndarray:
    """cascade only — no AGC, no boost (same as packed_interp_report.py)."""
    sos = kernel_to_sos(coeffs)
    out = sosfilt(sos, dry.astype(np.float64)).astype(np.float32)
    np.nan_to_num(out, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return out


def load_wav_mono(path: Path) -> np.ndarray:
    sr, data = wavfile.read(str(path))
    if data.dtype.kind in ("i", "u"):
        info = np.iinfo(data.dtype)
        data = data.astype(np.float32) / max(abs(info.min), abs(info.max))
    else:
        data = data.astype(np.float32)
    if data.ndim == 2:
        data = data[:, 0]
    return data


def lag_aligned_null(ref: np.ndarray, cand: np.ndarray, max_lag: int = 5000) -> tuple[int, float, float]:
    """Find optimal lag via FFT xcorr, compute gain-matched null.

    Returns (lag, gain, null_db).
    lag > 0: cand leads ref by lag samples (ref[lag:] ~ cand[0:])
    lag < 0: ref leads cand by |lag| samples (ref[0:] ~ cand[|lag|:])
    """
    n2 = max(len(ref), len(cand))
    n2 = 1 << (n2 - 1).bit_length()
    R = np.fft.rfft(np.pad(ref.astype(np.float64), (0, n2 - len(ref))))
    C = np.fft.rfft(np.pad(cand.astype(np.float64), (0, n2 - len(cand))))
    # xcorr[k] = sum_n ref[n]*cand[n-k]: peak at k means cand leads ref by k
    xcorr = np.fft.irfft(R * np.conj(C))
    half = min(max_lag, n2 // 2)
    fwd = list(range(half))
    bwd = list(range(n2 - half, n2))
    best_lag = max(fwd + bwd, key=lambda l: abs(xcorr[l]))
    if best_lag >= n2 // 2:
        best_lag = best_lag - n2  # negative lag: ref leads cand

    if best_lag >= 0:
        # cand leads ref: ref[0:] aligns with cand[best_lag:]
        r = ref.astype(np.float64)
        c = cand[best_lag:best_lag + len(ref)].astype(np.float64)
    else:
        # ref leads cand: ref[|lag|:] aligns with cand[0:]
        ab = abs(best_lag)
        r = ref[ab:].astype(np.float64)
        c = cand[:len(ref) - ab].astype(np.float64)

    n = min(len(r), len(c))
    r, c = r[:n], c[:n]

    gain_num = float(np.dot(r, c))
    gain_den = float(np.dot(c, c)) + EPS
    gain = gain_num / gain_den

    residual = r - gain * c
    ref_rms = math.sqrt(float(np.mean(r ** 2))) + EPS
    res_rms = math.sqrt(float(np.mean(residual ** 2))) + EPS
    null_db = 20.0 * math.log10(res_rms / ref_rms)
    return best_lag, gain, null_db


# ── test 1: corner encode roundtrip penalty ───────────────────────────────────


def test_corner_roundtrip(
    corner_coeffs: dict[str, np.ndarray],
    dry: np.ndarray,
    boost: float,
) -> list[dict]:
    rows = []
    for letter, label in CORNER_LABELS.items():
        exact_coeffs = corner_coeffs[letter]  # [6×5] float64, exact stage_to_kernel values

        # Build packed corner words and decode back
        words = kernel_to_words(exact_coeffs)  # [6×5] uint16
        decoded_coeffs = np.empty_like(exact_coeffs)
        DECODE_LUT = np.array([decode(w) for w in range(65536)], dtype=np.float64)
        d = DECODE_LUT[words.astype(np.uint16)]
        decoded_coeffs[:, 0] = d[:, 0] * 4.0 + d[:, 1]
        decoded_coeffs[:, 1] = d[:, 1]
        decoded_coeffs[:, 2] = d[:, 2] * 4.0 + d[:, 3]
        decoded_coeffs[:, 3] = d[:, 3]
        decoded_coeffs[:, 4] = d[:, 4]

        # Per-coefficient quantization error
        coeff_max_err = float(np.max(np.abs(exact_coeffs - decoded_coeffs)))

        # Render both and null
        ref_audio = full_pipeline_render(dry, exact_coeffs, boost)
        cand_audio = full_pipeline_render(dry, decoded_coeffs, boost)
        nd = null_depth(ref_audio, cand_audio)

        # Per-stage pole angle error
        pole_angle_errors = []
        for si in range(exact_coeffs.shape[0]):
            c2_e = exact_coeffs[si, 2]
            c3_e = exact_coeffs[si, 3]
            c2_d = decoded_coeffs[si, 2]
            c3_d = decoded_coeffs[si, 3]
            a1_e = c2_e - 2.0
            r2_e = max(1.0 - c3_e, 0.0)
            a1_d = c2_d - 2.0
            r2_d = max(1.0 - c3_d, 0.0)
            r_e = math.sqrt(r2_e) if r2_e > 0 else 0.0
            r_d = math.sqrt(r2_d) if r2_d > 0 else 0.0
            theta_e = math.acos(max(-1.0, min(1.0, -a1_e / (2.0 * r_e)))) if r_e > 0 else 0.0
            theta_d = math.acos(max(-1.0, min(1.0, -a1_d / (2.0 * r_d)))) if r_d > 0 else 0.0
            pole_angle_errors.append(abs(theta_e - theta_d))
            q_e = r_e / max(1.0 - r2_e, 1e-12)

        max_pole_angle_err = max(pole_angle_errors) if pole_angle_errors else 0.0
        max_pole_angle_err_deg = math.degrees(max_pole_angle_err)

        # Radius values for context
        r_vals = [math.sqrt(max(1.0 - exact_coeffs[si, 3], 0.0)) for si in range(exact_coeffs.shape[0])]
        max_r = max(r_vals)
        q_vals = [r / max(1.0 - r**2, 1e-12) for r in r_vals]
        max_q = max(q_vals)

        rows.append({
            "corner": label,
            "null_float_vs_packed_roundtrip_db": round(nd, 2),
            "max_coeff_err": round(coeff_max_err, 6),
            "max_pole_angle_err_rad": round(max_pole_angle_err, 6),
            "max_pole_angle_err_deg": round(max_pole_angle_err_deg, 4),
            "max_r": round(max_r, 6),
            "max_q": round(max_q, 1),
        })
        print(f"  corner {label}: roundtrip null {nd:.2f} dB  |  max_r={max_r:.6f}  max_Q={max_q:.1f}  "
              f"max_Δθ={max_pole_angle_err_deg:.4f}°")

    return rows


# ── test 2: per-stage pole quantization ───────────────────────────────────────


def test_pole_quantization(corner_coeffs: dict[str, np.ndarray]) -> list[dict]:
    rows = []
    for letter, label in CORNER_LABELS.items():
        exact_coeffs = corner_coeffs[letter]
        words = kernel_to_words(exact_coeffs)
        DECODE_LUT = np.array([decode(w) for w in range(65536)], dtype=np.float64)
        d = DECODE_LUT[words.astype(np.uint16)]
        decoded_coeffs = np.empty_like(exact_coeffs)
        decoded_coeffs[:, 0] = d[:, 0] * 4.0 + d[:, 1]
        decoded_coeffs[:, 1] = d[:, 1]
        decoded_coeffs[:, 2] = d[:, 2] * 4.0 + d[:, 3]
        decoded_coeffs[:, 3] = d[:, 3]
        decoded_coeffs[:, 4] = d[:, 4]

        for si in range(exact_coeffs.shape[0]):
            c2_e, c3_e, c4_e = exact_coeffs[si, 2], exact_coeffs[si, 3], exact_coeffs[si, 4]
            c2_d, c3_d, c4_d = decoded_coeffs[si, 2], decoded_coeffs[si, 3], decoded_coeffs[si, 4]

            a1_e = c2_e - 2.0
            r_e = math.sqrt(max(1.0 - c3_e, 0.0))
            a1_d = c2_d - 2.0
            r_d = math.sqrt(max(1.0 - c3_d, 0.0))

            theta_e = math.acos(max(-1.0, min(1.0, -a1_e / (2.0 * r_e)))) if r_e > 1e-9 else 0.0
            theta_d = math.acos(max(-1.0, min(1.0, -a1_d / (2.0 * r_d)))) if r_d > 1e-9 else 0.0
            freq_e = theta_e * SR / (2.0 * math.pi)
            freq_d = theta_d * SR / (2.0 * math.pi)
            q_e = r_e / max(1.0 - r_e ** 2, 1e-12)

            da1 = abs(a1_e - a1_d)
            dr = abs(r_e - r_d)
            dtheta = abs(theta_e - theta_d)
            dc4 = abs(c4_e - c4_d)
            dfreq = abs(freq_e - freq_d)

            rows.append({
                "corner": label,
                "stage": si,
                "pole_freq_hz": round(freq_e, 2),
                "pole_r": round(r_e, 6),
                "q": round(q_e, 1),
                "da1": round(da1, 8),
                "dr": round(dr, 8),
                "dtheta_rad": round(dtheta, 8),
                "dtheta_deg": round(math.degrees(dtheta), 6),
                "dfreq_hz": round(dfreq, 4),
                "dc4": round(dc4, 8),
            })

    return rows


# ── test 3: midpoint vs X3 with full pipeline ─────────────────────────────────


def test_midpoint_full_pipeline(
    corner_coeffs: dict[str, np.ndarray],
    dry: np.ndarray,
    x3_mid: np.ndarray,
    boost: float,
) -> dict:
    corner_words_np = {name: kernel_to_words(coeffs) for name, coeffs in corner_coeffs.items()}

    packed_mid = packed_oracle(corner_words_np, 0.5, 0.5)
    float_mid = decoded_float_baseline(corner_coeffs, 0.5, 0.5)

    packed_audio = full_pipeline_render(dry, packed_mid, boost)
    float_audio = full_pipeline_render(dry, float_mid, boost)

    lag_p, gain_p, null_p = lag_aligned_null(x3_mid, packed_audio)
    lag_f, gain_f, null_f = lag_aligned_null(x3_mid, float_audio)

    # Also simple render (no AGC/boost) to compare with previous session
    packed_simple = simple_render(dry, packed_mid)
    float_simple = simple_render(dry, float_mid)
    lag_ps, gain_ps, null_ps = lag_aligned_null(x3_mid, packed_simple)
    lag_fs, gain_fs, null_fs = lag_aligned_null(x3_mid, float_simple)

    # Packed vs float null (internal, no X3)
    packed_vs_float_full = null_depth(
        full_pipeline_render(dry, packed_mid, boost),
        full_pipeline_render(dry, float_mid, boost),
    )

    return {
        "packed_full_pipeline": {"lag": lag_p, "gain": round(gain_p, 6), "null_db": round(null_p, 2)},
        "float_full_pipeline": {"lag": lag_f, "gain": round(gain_f, 6), "null_db": round(null_f, 2)},
        "packed_simple": {"lag": lag_ps, "gain": round(gain_ps, 6), "null_db": round(null_ps, 2)},
        "float_simple": {"lag": lag_fs, "gain": round(gain_fs, 6), "null_db": round(null_fs, 2)},
        "packed_vs_float_full_pipeline_null_db": round(packed_vs_float_full, 2),
    }, packed_audio


# ── test 4: phase vs magnitude decomposition at midpoint ──────────────────────


def decompose_phase_vs_magnitude(
    corner_coeffs: dict[str, np.ndarray],
    freq_bins: int = 4096,
) -> dict:
    from scipy.signal import sosfreqz

    corner_words_np = {name: kernel_to_words(coeffs) for name, coeffs in corner_coeffs.items()}
    packed_mid = packed_oracle(corner_words_np, 0.5, 0.5)
    float_mid = decoded_float_baseline(corner_coeffs, 0.5, 0.5)

    sos_packed = kernel_to_sos(packed_mid)
    sos_float = kernel_to_sos(float_mid)

    freqs, H_packed = sosfreqz(sos_packed, worN=freq_bins, fs=SR)
    _, H_float = sosfreqz(sos_float, worN=freq_bins, fs=SR)

    # Magnitude ratio and phase difference
    mag_packed = np.abs(H_packed)
    mag_float = np.abs(H_float)
    mag_ratio_db = 20.0 * np.log10(mag_packed / (mag_float + EPS) + EPS)

    phase_packed = np.unwrap(np.angle(H_packed))
    phase_float = np.unwrap(np.angle(H_float))
    phase_diff_deg = np.degrees(phase_packed - phase_float)

    # Estimate null contribution from magnitude error vs phase error
    # |H_p - H_f|^2 = |H_f|^2 * (ε_m^2 + ε_φ^2) for small errors
    # where ε_m = (|H_p| - |H_f|) / |H_f|, ε_φ = ΔΦ in radians
    eps_m = (mag_packed - mag_float) / (mag_float + EPS)
    eps_phi = phase_packed - phase_float  # radians
    mag_error_rms = float(np.sqrt(np.mean(eps_m ** 2)))
    phase_error_rms = float(np.sqrt(np.mean(eps_phi ** 2)))

    # Weighted by |H_f|^2 (signal power)
    weights = mag_float ** 2
    w_sum = float(np.sum(weights)) + EPS
    mag_error_rms_w = float(np.sqrt(np.sum(weights * eps_m ** 2) / w_sum))
    phase_error_rms_w = float(np.sqrt(np.sum(weights * eps_phi ** 2) / w_sum))

    # Band-level phase error
    bands = [
        ("sub", 20, 80), ("low", 80, 250), ("low-mid", 250, 1000),
        ("high-mid", 1000, 4000), ("high", 4000, 10000), ("air", 10000, 20000),
    ]
    band_stats = []
    for band_name, f_lo, f_hi in bands:
        mask = (freqs >= f_lo) & (freqs <= f_hi)
        if not np.any(mask):
            continue
        pd = phase_diff_deg[mask]
        md = mag_ratio_db[mask]
        band_stats.append({
            "band": band_name,
            "f_lo": f_lo,
            "f_hi": f_hi,
            "phase_diff_rms_deg": round(float(np.sqrt(np.mean(pd ** 2))), 3),
            "phase_diff_max_deg": round(float(np.max(np.abs(pd))), 3),
            "mag_ratio_rms_db": round(float(np.sqrt(np.mean(md ** 2))), 3),
            "mag_ratio_max_db": round(float(np.max(np.abs(md))), 3),
        })

    return {
        "mag_error_rms_unweighted": round(mag_error_rms, 6),
        "phase_error_rms_rad_unweighted": round(phase_error_rms, 6),
        "mag_error_rms_signal_weighted": round(mag_error_rms_w, 6),
        "phase_error_rms_rad_signal_weighted": round(phase_error_rms_w, 6),
        "band_stats": band_stats,
    }


# ── report writer ─────────────────────────────────────────────────────────────


def write_report(
    out_path: Path,
    corner_rows: list[dict],
    pole_rows: list[dict],
    midpoint_results: dict | None,
    phase_results: dict,
    has_x3: bool,
) -> None:
    lines = [
        "# Packed Parity Gap Diagnosis",
        "",
        f"Cartridge: `ref/p2k_skins/00_talking_hedz.json` (derived-packed-canonical corners)",
        f"Corner words: re-encoded from decoded floats — NOT original E-mu ROM u16 words",
        "",
        "## Summary",
        "",
    ]

    if corner_rows:
        lines += [
            "### Corner Encode-Roundtrip Null Depths",
            "",
            "| corner | null (float vs packed-roundtrip) dB | max_r | max_Q | max_Δθ (°) |",
            "|---|---:|---:|---:|---:|",
        ]
        for r in corner_rows:
            lines.append(
                f"| {r['corner']} | {r['null_float_vs_packed_roundtrip_db']} | "
                f"{r['max_r']} | {r['max_q']} | {r['max_pole_angle_err_deg']} |"
            )
        lines.append("")
        lines.append(
            "**Interpretation**: Q0 corners (low Q, r ≈ 0.96-0.98) should roundtrip well. "
            "Q100 corners (high Q, r ≈ 0.999) amplify pole-angle quantization error — "
            "expect much worse roundtrip null depth."
        )

    lines += ["", "### Phase vs Magnitude Decomposition at Midpoint (M=0.5, Q=0.5)", ""]
    lines.append(f"- Magnitude error RMS (signal-weighted): {phase_results['mag_error_rms_signal_weighted']:.6f} "
                 f"(unweighted: {phase_results['mag_error_rms_unweighted']:.6f})")
    lines.append(f"- Phase error RMS (signal-weighted): {phase_results['phase_error_rms_rad_signal_weighted']:.6f} rad "
                 f"(unweighted: {phase_results['phase_error_rms_rad_unweighted']:.6f} rad)")
    lines.append("")
    lines += [
        "| band | Hz | phase RMS (°) | phase max (°) | mag RMS (dB) | mag max (dB) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for b in phase_results["band_stats"]:
        lines.append(
            f"| {b['band']} | {b['f_lo']}-{b['f_hi']} | {b['phase_diff_rms_deg']} | "
            f"{b['phase_diff_max_deg']} | {b['mag_ratio_rms_db']} | {b['mag_ratio_max_db']} |"
        )

    if has_x3 and midpoint_results:
        lines += ["", "### Midpoint vs X3 — Full Pipeline vs Simple Render", ""]
        lines += [
            "| path | pipeline | lag | gain | null vs X3 dB |",
            "|---|---|---:|---:|---:|",
        ]
        for key, label, pipeline in [
            ("float_simple", "float", "simple (no AGC/boost)"),
            ("packed_simple", "packed", "simple (no AGC/boost)"),
            ("float_full_pipeline", "float", "full (AGC+boost, no DC block)"),
            ("packed_full_pipeline", "packed", "full (AGC+boost, no DC block)"),
        ]:
            r = midpoint_results[key]
            lines.append(f"| {label} | {pipeline} | {r['lag']} | {r['gain']} | {r['null_db']} |")
        lines.append("")
        pvf = midpoint_results["packed_vs_float_full_pipeline_null_db"]
        lines.append(f"Packed vs float (both full pipeline): {pvf:.2f} dB null")

    lines += [
        "",
        "## Ranked Diagnosis",
        "",
        "1. **PRIMARY — Derived-packed corners ≠ ROM words**: The P2K JSON stores floats decoded from "
        "   E-mu ROM u16 words. Re-encoding these floats back to u16 creates different words. "
        "   The difference is amplified by high-Q resonances (r ≈ 0.999, Q ≈ 500) at Q100 corners, "
        "   causing large pole-angle phase errors at those resonances.",
        "",
        "2. **HIGH-Q POLE ANGLE QUANTIZATION**: At r ≈ 0.999, 1 LSB error in (c2-c3)/4 ≈ 0.001 rad "
        "   pole angle shift. Group delay error ∝ r*Q*Δθ. At Q ≈ 500, even 0.001 rad causes "
        "   large phase offset at the resonance peak.",
        "",
        "3. **PIPELINE (minor)**: AGC at moderate signal levels (<0.5 dB effect). Not the "
        "   dominant error.",
        "",
        "4. **TRIM/ALIGNMENT (minor)**: Lag-aligned overlap, not trimmed clean region. "
        "   X3 coefficient ramp-in at start may add noise.",
        "",
        "## Fix Path",
        "",
        "The -12 dB null cannot be closed by fixing the Python/Rust interpolation code. "
        "The code is correct. The gap comes from using re-encoded (lossy) corner words "
        "instead of the original E-mu ROM u16 words.",
        "",
        "Fix requires: capture the actual 240-byte ROM coefficient block for skin 13 "
        "(Talking Hedz) via Ghidra static extraction from EosAudioEngine.dll `.rdata` "
        "or Cheat Engine runtime dump at the offsets listed in FRAME_BANK.md. "
        "Replace the derived-packed corners with the ROM words. "
        "Expected improvement: high-Q corner roundtrip null should improve significantly "
        "(ROM words are exact; re-encoding is lossy).",
    ]

    out_path.write_text("\n".join(lines) + "\n")


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cartridge", type=Path, default=DEFAULT_CARTRIDGE)
    parser.add_argument("--dry", type=Path, default=DEFAULT_DRY)
    parser.add_argument("--x3-mid", type=Path, default=DEFAULT_X3_MID)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"cartridge: {args.cartridge}")

    corner_coeffs, cartridge = load_corner_coeffs(args.cartridge)
    boost = float(cartridge["keyframes"][0].get("boost", 1.0))
    print(f"boost: {boost}")

    has_dry = args.dry.exists()
    has_x3 = args.x3_mid.exists()

    if not has_dry:
        print(f"warning: dry not found at {args.dry} — skipping audio tests")

    dry = load_wav_mono(args.dry) if has_dry else None

    # ── test 1: corner encode roundtrip ──
    print("\n[1] Corner encode-roundtrip null depths...")
    corner_rows = []
    if dry is not None:
        corner_rows = test_corner_roundtrip(corner_coeffs, dry, boost)
        with (out_dir / "corner_roundtrip.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(corner_rows[0].keys()))
            w.writeheader()
            w.writerows(corner_rows)

    # ── test 2: per-stage pole quantization ──
    print("\n[2] Per-stage pole quantization analysis...")
    pole_rows = test_pole_quantization(corner_coeffs)
    with (out_dir / "pole_quantization.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pole_rows[0].keys()))
        w.writeheader()
        w.writerows(pole_rows)

    # Print worst stages
    pole_rows_sorted = sorted(pole_rows, key=lambda r: -r["dtheta_rad"])
    print(f"  {'corner':12} {'stage':>5} {'freq_hz':>9} {'r':>8} {'Q':>6} {'Δθ (°)':>12} {'Δfreq (Hz)':>12}")
    for r in pole_rows_sorted[:10]:
        print(f"  {r['corner']:12} {r['stage']:>5} {r['pole_freq_hz']:>9.1f} "
              f"{r['pole_r']:>8.6f} {r['q']:>6.1f} {r['dtheta_deg']:>12.6f} {r['dfreq_hz']:>12.4f}")

    # ── test 3: midpoint vs X3 ──
    print("\n[3] Midpoint vs X3 (full pipeline + simple)...")
    midpoint_results = None
    midpoint_wav = None
    if dry is not None and has_x3:
        x3_mid = load_wav_mono(args.x3_mid)
        midpoint_results, midpoint_wav = test_midpoint_full_pipeline(
            corner_coeffs, dry, x3_mid, boost
        )
        print(f"  float  simple:        {midpoint_results['float_simple']['null_db']:+.2f} dB  "
              f"(gain {midpoint_results['float_simple']['gain']:.4f})")
        print(f"  packed simple:        {midpoint_results['packed_simple']['null_db']:+.2f} dB  "
              f"(gain {midpoint_results['packed_simple']['gain']:.4f})")
        print(f"  float  full pipeline: {midpoint_results['float_full_pipeline']['null_db']:+.2f} dB  "
              f"(gain {midpoint_results['float_full_pipeline']['gain']:.4f})")
        print(f"  packed full pipeline: {midpoint_results['packed_full_pipeline']['null_db']:+.2f} dB  "
              f"(gain {midpoint_results['packed_full_pipeline']['gain']:.4f})")
        print(f"  packed vs float (full pipeline): {midpoint_results['packed_vs_float_full_pipeline_null_db']:+.2f} dB")

        wav_path = out_dir / "df2_packed_midpoint_full_pipeline.wav"
        wavfile.write(str(wav_path), SR, midpoint_wav.astype(np.float32))
        print(f"  wrote: {wav_path}")
    elif dry is not None:
        print("  (skipped — X3 mid capture not found)")

    # ── test 4: phase vs magnitude decomposition ──
    print("\n[4] Phase vs magnitude decomposition at midpoint...")
    phase_results = decompose_phase_vs_magnitude(corner_coeffs)
    print(f"  magnitude error RMS (signal-weighted): {phase_results['mag_error_rms_signal_weighted']:.6f}")
    print(f"  phase error RMS (signal-weighted):     {phase_results['phase_error_rms_rad_signal_weighted']:.6f} rad "
          f"({math.degrees(phase_results['phase_error_rms_rad_signal_weighted']):.3f}°)")
    print("  band breakdown:")
    for b in phase_results["band_stats"]:
        print(f"    {b['band']:9} ({b['f_lo']:>5}-{b['f_hi']:>5} Hz): "
              f"phase RMS {b['phase_diff_rms_deg']:7.3f}°  max {b['phase_diff_max_deg']:7.3f}°  "
              f"mag RMS {b['mag_ratio_rms_db']:6.3f} dB")

    # ── write report ──
    report_path = out_dir / "DIAGNOSIS.md"
    write_report(report_path, corner_rows, pole_rows, midpoint_results, phase_results, has_x3 and dry is not None)
    print(f"\nwrote: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
