#!/usr/bin/env python3
"""df2_actor_extract — source WAV -> six-lane actor skeleton -> real DF2 body240.

Provenance tags (per lane):
  MEASURED        pole derived directly from LPC on the source audio
  INFERRED        derived from measurement (shifted variant, cranked Q, valley zero)
  INVENTED        no measurement supports it; added by the fill-hierarchy rule
  IDENTITY        pass-through pad; not a real feature

Zero treatment (per lane):
  LOCAL_TEAR          zero placed below the pole -> bite/edge at the resonance
  REMOTE_COUNTERWEIGHT  zero far from the pole   -> carve/hollow elsewhere
  EDGE_ZERO           zero near Nyquist          -> high-freq cap
  NEUTRAL             no zero                    -> pure resonator

LPC is ALL-POLE: every zero is INFERRED or INVENTED — never MEASURED.

Usage:
    python tools/df2_actor_extract.py                    # self-test (synthetic)
    python tools/df2_actor_extract.py --wav my.wav
    python tools/df2_actor_extract.py --wav a.wav --wav e.wav  # two = morph endpoints
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.linalg import toeplitz
from scipy.signal import butter, sosfilt

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402
from pyruntime.packed_interp import packed_bilinear, words_to_coeffs  # noqa: E402
from tools.author_lanes import body_to_packed_v1, lane_words  # noqa: E402

AUTHORING_SR = 39062.5
LPC_ORDER = 12
FREQS = freq_points()


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic source
# ─────────────────────────────────────────────────────────────────────────────

# Formant frequency / narrowband-Q pairs per config.  Q = fc/bw  (high Q = sharp LPC peak)
_SYNTH_FORMANTS = {
    "A": [(650,  18.0), (1200, 14.0), (2500, 12.0), (3800, 10.0), (5500,  9.0)],
    "B": [(280,  20.0), (2100, 13.0), (3200, 11.0), (4600, 10.0), (6500,  8.0)],
}


def synth_source(config: str = "A", dur: float = 2.0) -> tuple[np.ndarray, float]:
    """Narrow-Q resonator cascade on white noise -> formant-rich signal with sharp LPC peaks.

    Using white noise instead of a harmonic series avoids harmonic coloring that
    can confuse LPC.  High-Q filters (Q>8) produce spectral peaks narrow enough for
    LPC to lock onto at order 12.  Returns (signal, sr).
    """
    from scipy.signal import lfilter, iirpeak
    sr = 44100.0
    n = int(sr * dur)
    rng = np.random.default_rng(42)
    noise = rng.standard_normal(n).astype(np.float64)
    # Steady envelope — skip attack so the sustain window finder lands in the flat region
    env = np.ones(n)
    attack = int(sr * 0.05)
    env[:attack] = np.linspace(0.0, 1.0, attack)
    noise *= env
    # Cascade through narrow resonators in series (each carves the spectrum)
    y = noise.copy()
    for fc, Q in _SYNTH_FORMANTS[config]:
        w0 = fc / (sr / 2.0)
        b, a = iirpeak(w0, Q)
        y = lfilter(b, a, y)
    y /= np.max(np.abs(y)) + 1e-9
    y *= 0.7
    return y.astype(np.float64), sr


# ─────────────────────────────────────────────────────────────────────────────
# WAV loader
# ─────────────────────────────────────────────────────────────────────────────


def load_wav(path: Path) -> tuple[np.ndarray, float]:
    with wave.open(str(path)) as wf:
        sr = float(wf.getframerate())
        n_ch = wf.getnchannels()
        n_fr = wf.getnframes()
        raw = wf.readframes(n_fr)
        sw = wf.getsampwidth()
    if sw == 2:
        sig = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif sw == 4:
        sig = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {sw}")
    if n_ch > 1:
        sig = sig[::n_ch]  # take left channel
    return sig, sr


# ─────────────────────────────────────────────────────────────────────────────
# Sustain window
# ─────────────────────────────────────────────────────────────────────────────


def find_sustain_window(signal: np.ndarray, sr: float,
                        win_samples: int = 2048) -> tuple[int, int]:
    """Return (start, end) of the highest-energy, longest-stable region."""
    hop = win_samples // 4
    n = len(signal)
    rms_vals = []
    starts = []
    pos = 0
    while pos + win_samples <= n:
        chunk = signal[pos: pos + win_samples]
        rms_vals.append(float(np.sqrt(np.mean(chunk ** 2))))
        starts.append(pos)
        pos += hop
    if not rms_vals:
        return 0, min(win_samples, n)
    rms_arr = np.array(rms_vals)
    threshold = 0.55 * np.max(rms_arr)
    best_idx = int(np.argmax(rms_arr))
    # Walk back to find start of the high-energy plateau
    idx = best_idx
    while idx > 0 and rms_arr[idx - 1] >= threshold:
        idx -= 1
    # Skip one more frame to avoid the leading transient / attack
    idx = min(idx + 1, len(starts) - 1)
    start = starts[idx]
    end = min(start + win_samples, n)
    return start, end


# ─────────────────────────────────────────────────────────────────────────────
# LPC pole extraction
# ─────────────────────────────────────────────────────────────────────────────


def _lpc_yule_walker(frame: np.ndarray, order: int) -> np.ndarray:
    """LPC coefficients via Yule-Walker / autocorrelation method.

    Returns [1, a1, ..., a_order] matching scipy.signal.lpc convention.
    Uses scipy.linalg.toeplitz + numpy.linalg.solve (always available).
    """
    n = len(frame)
    # Biased autocorrelation
    r = np.array([np.dot(frame[:n - k], frame[k:]) / n for k in range(order + 1)])
    if abs(r[0]) < 1e-12:
        a = np.zeros(order + 1)
        a[0] = 1.0
        return a
    R = toeplitz(r[:order])
    try:
        a_tail = np.linalg.solve(R, -r[1:order + 1])
    except np.linalg.LinAlgError:
        a_tail = np.zeros(order)
    return np.concatenate([[1.0], a_tail])


def extract_lpc_poles(frame: np.ndarray, sr: float,
                      order: int = LPC_ORDER) -> list[tuple[float, float]]:
    """LPC -> complex poles (freq_hz, radius) in upper half-plane, physically-Hz.

    LPC is all-pole: these are MEASURED resonances only. No zeros are returned.
    """
    frame = frame - np.mean(frame)
    peak = np.max(np.abs(frame))
    if peak < 1e-9:
        return []
    frame = frame / peak
    # Windowing before LPC
    frame = frame * np.hanning(len(frame))
    try:
        a = _lpc_yule_walker(frame, order)
    except Exception:
        return []
    roots = np.roots(a)
    poles: list[tuple[float, float]] = []
    nyq = sr / 2.0
    for r in roots:
        radius = abs(r)
        angle = abs(np.angle(r))
        freq_hz = angle * sr / (2.0 * np.pi)
        # Upper half-plane, audible range, below AUTHORING Nyquist, stable and resonant
        auth_nyq = AUTHORING_SR / 2.0
        if (np.imag(r) > 1e-6 and 40 < freq_hz < min(nyq * 0.95, auth_nyq * 0.95)
                and 0.45 < radius < 0.9998):
            poles.append((freq_hz, float(radius)))
    poles.sort(key=lambda p: p[0])
    return poles


# ─────────────────────────────────────────────────────────────────────────────
# Spectral envelope + valleys
# ─────────────────────────────────────────────────────────────────────────────


def spectral_envelope(frame: np.ndarray, sr: float, n_fft: int = 4096
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Return (freqs, smoothed_log_magnitude) for the frame."""
    win = np.hanning(len(frame))
    padded = np.zeros(n_fft)
    w = min(len(frame), n_fft)
    padded[:w] = frame[:w] * win[:w]
    spec = np.fft.rfft(padded)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    mag_db = 20.0 * np.log10(np.maximum(np.abs(spec), 1e-12))
    # Smooth with a Gaussian kernel on a log-frequency scale
    from scipy.ndimage import gaussian_filter1d
    smoothed = gaussian_filter1d(mag_db, sigma=12)
    return freqs, smoothed


def detect_valleys(freqs: np.ndarray, smoothed: np.ndarray,
                   min_prominence_db: float = 3.0) -> list[float]:
    """Local minima in the smoothed spectrum with prominence >= min_prominence_db.

    Uses scipy.signal.find_peaks on the inverted curve — finds dips regardless of
    global level, so it works on spectra that rise monotonically (like a resonator
    cascade) as well as flat ones.

    Returns list of valley-center frequencies (MEASURED_VALLEY candidates).
    """
    from scipy.signal import find_peaks
    audible = (freqs > 80) & (freqs < freqs[-1] * 0.9)
    inv = -smoothed  # flip: dips become peaks
    idx_all, props = find_peaks(inv[audible], prominence=min_prominence_db, distance=8)
    audible_freqs = freqs[audible]
    valleys = [float(audible_freqs[i]) for i in idx_all]
    # Sort by prominence descending so callers get the deepest valleys first
    order = np.argsort(-props["prominences"])
    return [valleys[i] for i in order]


# ─────────────────────────────────────────────────────────────────────────────
# Zero treatment assignment
# ─────────────────────────────────────────────────────────────────────────────


def _assign_zero(role: str, pole_hz: float, pole_r: float,
                 valley_hz: float | None = None) -> tuple[str, float | None, float, str]:
    """Return (treatment, zero_hz, zero_r, zero_provenance).

    Zero placement rules (both strategies applied together):
      LOCAL_TEAR  — zero in the valley BELOW the pole if one is detected there;
                    otherwise 0.80x the pole frequency (just below the peak).
                    radius = 0.97 so the notch is deep enough to read on a curve.
      REMOTE_COUNTERWEIGHT — zero at a valley that is far from the pole (> 1 oct away),
                    or a fallback remote position. radius = 0.92.
      EDGE_ZERO   — near-Nyquist cap. radius = 0.9995.
      NEUTRAL     — no zero.
    """
    if role == "IDENTITY":
        return "NEUTRAL", pole_hz, pole_r, "N/A"
    if role == "AIR":
        nyq = AUTHORING_SR / 2.0
        return "EDGE_ZERO", nyq * 0.92, 0.9995, "INVENTED"
    if role == "HOLLOW":
        # Target a valley that is > 1 octave away from the pole
        if valley_hz and abs(np.log2(valley_hz / pole_hz)) > 1.0:
            z_hz = valley_hz
            prov = "INFERRED"
        else:
            z_hz = pole_hz * 0.30 if pole_hz > 500 else pole_hz * 3.5
            prov = "INVENTED"
        z_hz = float(max(80.0, min(z_hz, AUTHORING_SR / 2.0 * 0.88)))
        return "REMOTE_COUNTERWEIGHT", z_hz, 0.92, prov
    if role in ("BODY", "PRESENCE") and pole_r > 0.88:
        # Valley-targeted LOCAL_TEAR: prefer a spectral dip just below the pole.
        if valley_hz and 0.4 * pole_hz < valley_hz < pole_hz:
            z_hz = valley_hz          # measured dip — INFERRED from spectrum
            prov = "INFERRED"
        else:
            z_hz = pole_hz * 0.80     # fallback: 0.80x pole freq, just below peak
            prov = "INFERRED"
        # radius 0.97: close enough to the unit circle that the notch is visible
        return "LOCAL_TEAR", float(z_hz), 0.97, prov
    return "NEUTRAL", None, 0.0, "N/A"


# ─────────────────────────────────────────────────────────────────────────────
# Six-lane fill hierarchy
# ─────────────────────────────────────────────────────────────────────────────

_IDENTITY_LANE_FREQ = 500.0
_IDENTITY_LANE_R = 0.50


def fill_six_lanes(measured_poles: list[tuple[float, float]],
                   valleys: list[float],
                   source_label: str) -> list[dict[str, Any]]:
    """Hierarchical six-lane fill.

    Rule order:
      1. Keep measured poles (MEASURED)
      2. Add foundation if no sub-200 Hz pole (INVENTED)
      3. Add hollow from valley if headroom remains (INFERRED)
      4. Add air/cap if no pole above 12 kHz (INVENTED)
      5. Add pressure/fuse if still short (INVENTED)
      6. Identity-pad to 6 (IDENTITY)

    Few features is fine — build a clean body around them.
    """
    lanes: list[dict[str, Any]] = []

    def _nearest_valley_below(pole_hz: float) -> float | None:
        """Return the deepest valley between 0.4x and 1.0x the pole frequency."""
        candidates = [v for v in valleys if 0.4 * pole_hz < v < pole_hz]
        return candidates[0] if candidates else None  # already sorted by prominence

    # ── Step 1: measured poles ────────────────────────────────────────────────
    for freq, radius in measured_poles:
        if len(lanes) >= 6:
            break
        if freq > 8000:
            role = "AIR"
        elif freq > 3000:
            role = "PRESENCE"
        elif freq > 200:
            role = "BODY"
        else:
            role = "FOUNDATION"
        nearest_v = _nearest_valley_below(freq)
        treat, z_hz, z_r, z_prov = _assign_zero(role, freq, radius, valley_hz=nearest_v)
        lane: dict[str, Any] = {
            "role": role,
            "pole_hz": float(freq),
            "pole_r": float(radius),
            "zero_treatment": treat,
            "zero_hz": z_hz,
            "zero_r": float(z_r),
            "gain": 0.50,
            "provenance": "MEASURED",
            "zero_provenance": z_prov,
        }
        lanes.append(lane)

    # ── Step 2: foundation (sub-200 Hz) ──────────────────────────────────────
    has_foundation = any(l["pole_hz"] < 200 for l in lanes)
    if not has_foundation and len(lanes) < 6:
        treat, z_hz, z_r, z_prov = _assign_zero("FOUNDATION", 110.0, 0.93)
        lanes.append({
            "role": "FOUNDATION",
            "pole_hz": 110.0,
            "pole_r": 0.93,
            "zero_treatment": treat,
            "zero_hz": z_hz,
            "zero_r": float(z_r),
            "gain": 0.50,
            "provenance": "INVENTED",
            "zero_provenance": z_prov,
        })

    # ── Step 3: hollow from valley candidate ──────────────────────────────────
    if valleys and len(lanes) < 6:
        v_hz = valleys[0]  # use the lowest valley
        treat, z_hz, z_r, z_prov = _assign_zero("HOLLOW", v_hz, 0.78, valley_hz=v_hz)
        lanes.append({
            "role": "HOLLOW",
            "pole_hz": float(v_hz),
            "pole_r": 0.78,
            "zero_treatment": treat,
            "zero_hz": z_hz,
            "zero_r": float(z_r),
            "gain": 0.48,
            "provenance": "INFERRED",
            "zero_provenance": z_prov,
        })

    # ── Step 4: air / Nyquist cap ─────────────────────────────────────────────
    has_air = any(l["pole_hz"] > 12000 for l in lanes)
    if not has_air and len(lanes) < 6:
        treat, z_hz, z_r, z_prov = _assign_zero("AIR", 16500.0, 0.92)
        lanes.append({
            "role": "AIR",
            "pole_hz": 16500.0,
            "pole_r": 0.92,
            "zero_treatment": treat,
            "zero_hz": z_hz,
            "zero_r": float(z_r),
            "gain": 0.44,
            "provenance": "INVENTED",
            "zero_provenance": z_prov,
        })

    # ── Step 5: pressure / fuse ───────────────────────────────────────────────
    if len(lanes) < 6:
        treat, z_hz, z_r, z_prov = _assign_zero("PRESSURE", 6800.0, 0.88)
        lanes.append({
            "role": "PRESSURE",
            "pole_hz": 6800.0,
            "pole_r": 0.88,
            "zero_treatment": treat,
            "zero_hz": z_hz,
            "zero_r": float(z_r),
            "gain": 0.46,
            "provenance": "INVENTED",
            "zero_provenance": z_prov,
        })

    # ── Step 6: identity pad ──────────────────────────────────────────────────
    while len(lanes) < 6:
        r = _IDENTITY_LANE_R
        hz = _IDENTITY_LANE_FREQ
        lanes.append({
            "role": "IDENTITY",
            "pole_hz": hz,
            "pole_r": r,
            "zero_treatment": "NEUTRAL",
            "zero_hz": hz,   # matched -> H(z) = gain ≈ 1
            "zero_r": r,
            "gain": 1.0,
            "provenance": "IDENTITY",
            "zero_provenance": "N/A",
        })

    # Sort lanes by pole_hz for a coherent low->high order
    lanes.sort(key=lambda l: l["pole_hz"])

    # Stamp lane indices
    for i, l in enumerate(lanes):
        l["lane"] = i

    return lanes[:6]


# ─────────────────────────────────────────────────────────────────────────────
# Morph variant and Q-crank
# ─────────────────────────────────────────────────────────────────────────────


def make_morph_variant(lanes: list[dict], semitones: float = 1.5) -> list[dict]:
    """Shift all pole frequencies by +semitones. Provenance = INFERRED."""
    factor = 2.0 ** (semitones / 12.0)
    variant = []
    for l in lanes:
        v = dict(l)
        if v["provenance"] == "IDENTITY":
            variant.append(v)
            continue
        v["pole_hz"] = l["pole_hz"] * factor
        if v["zero_hz"] is not None and v["zero_treatment"] != "EDGE_ZERO":
            v["zero_hz"] = l["zero_hz"] * factor
        if v["provenance"] == "MEASURED":
            v["provenance"] = "INFERRED"  # freq-shifted copy is derived
        variant.append(v)
    return variant


def crank_secondary(lanes: list[dict], crank: float = 0.60) -> list[dict]:
    """Q-crank: push pole_r toward 0.999, freq LOCKED. Zeros derived -> INFERRED."""
    cranked = []
    for l in lanes:
        v = dict(l)
        if v["provenance"] != "IDENTITY":
            r0 = l["pole_r"]
            v["pole_r"] = r0 + (0.999 - r0) * crank
        cranked.append(v)
    return cranked


def align_lane_pairs(a: list[dict], b: list[dict]) -> tuple[list[dict], list[dict]]:
    """Match two pole lists by nearest frequency so lane i maps to lane i.

    Both lists must have the same length (already filled to 6 lanes).
    Match greedily: pair lowest-freq of A to nearest-freq in B.
    """
    used = [False] * len(b)
    out_a, out_b = [], []
    for la in sorted(a, key=lambda l: l["pole_hz"]):
        best_j, best_d = -1, float("inf")
        for j, lb in enumerate(b):
            if not used[j]:
                d = abs(la["pole_hz"] - lb["pole_hz"])
                if d < best_d:
                    best_d, best_j = d, j
        if best_j >= 0:
            out_a.append(la)
            out_b.append(b[best_j])
            used[best_j] = True
    # Renumber lane indices
    for i, (la, lb) in enumerate(zip(out_a, out_b)):
        la["lane"] = i
        lb["lane"] = i
    return out_a, out_b


# ─────────────────────────────────────────────────────────────────────────────
# Build the four corners
# ─────────────────────────────────────────────────────────────────────────────


def build_corners(m0_lanes: list[dict], m1_lanes: list[dict]) -> dict[str, list[dict]]:
    """Return the four corners as lane-list dicts."""
    m0_s1 = crank_secondary(m0_lanes)
    m1_s1 = crank_secondary(m1_lanes)
    return {
        "M0_S0": m0_lanes,
        "M1_S0": m1_lanes,
        "M0_S1": m0_s1,
        "M1_S1": m1_s1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Plots
# ─────────────────────────────────────────────────────────────────────────────

_DARK = "#0b0f0e"
_GREEN = "#39ff14"


def _dark_ax(ax):
    ax.set_facecolor(_DARK)
    ax.tick_params(colors="#888")
    ax.spines[:].set_color("#333")


def plot_window(out_dir: Path, signal: np.ndarray, sr: float,
                start: int, end: int) -> None:
    t = np.arange(len(signal)) / sr
    fig, ax = plt.subplots(figsize=(12, 3))
    fig.patch.set_facecolor(_DARK)
    _dark_ax(ax)
    ax.plot(t, signal, color="#2ec4ff", lw=0.6, alpha=0.8)
    ax.axvspan(start / sr, end / sr, color="#39ff14", alpha=0.18, label="sustain window")
    ax.set_xlabel("time (s)", color="#aaa")
    ax.set_ylabel("amplitude", color="#aaa")
    ax.set_title("waveform + sustain window", color="#eaeaea", fontsize=11)
    ax.legend(labelcolor="#ddd", facecolor=_DARK, edgecolor="#333", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_dir / "window.png", dpi=110)
    plt.close(fig)


def plot_spectrum(out_dir: Path, freqs_raw: np.ndarray, mag_db_raw: np.ndarray,
                 smoothed: np.ndarray, measured_poles: list[tuple[float, float]],
                 valleys: list[float]) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor(_DARK)
    _dark_ax(ax)
    band = freqs_raw > 40
    ax.semilogx(freqs_raw[band], mag_db_raw[band], color="#444", lw=0.6, alpha=0.8, label="raw FFT")
    ax.semilogx(freqs_raw[band], smoothed[band], color="#2ec4ff", lw=1.8, label="smoothed envelope")
    for f, r in measured_poles:
        ax.axvline(f, color="#ffd23e", lw=1.0, alpha=0.7, ls="--")
        ax.text(f, np.max(smoothed[band]) + 1, f"{f:.0f}", color="#ffd23e",
                fontsize=6, ha="center", va="bottom", rotation=60)
    for v in valleys:
        ax.axvline(v, color="#ff6b6b", lw=0.8, alpha=0.5, ls=":")
    # Legend proxy
    from matplotlib.lines import Line2D
    handles, labels = ax.get_legend_handles_labels()
    handles += [Line2D([0], [0], color="#ffd23e", lw=1, ls="--"),
                Line2D([0], [0], color="#ff6b6b", lw=1, ls=":")]
    labels += ["measured poles", "valley candidates"]
    ax.legend(handles, labels, labelcolor="#ddd", facecolor=_DARK, edgecolor="#333", fontsize=8)
    ax.set_xlabel("frequency Hz (log)", color="#aaa")
    ax.set_ylabel("dB", color="#aaa")
    ax.set_title("raw spectrum + smoothed envelope + candidates", color="#eaeaea", fontsize=11)
    ax.set_xlim(60, freqs_raw[-1])
    fig.tight_layout()
    fig.savefig(out_dir / "raw_vs_smooth_envelope.png", dpi=110)
    plt.close(fig)
    # peak/valley candidates — same axes, dedicated file
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    fig2.patch.set_facecolor(_DARK)
    _dark_ax(ax2)
    ax2.semilogx(freqs_raw[band], smoothed[band], color="#2ec4ff", lw=1.8)
    for f, r in measured_poles:
        ax2.axvline(f, color="#ffd23e", lw=1.2, alpha=0.85, ls="--",
                    label=f"pole {f:.0f} Hz r={r:.3f}")
    for v in valleys:
        ax2.axvline(v, color="#ff6b6b", lw=0.9, alpha=0.65, ls=":",
                    label=f"valley {v:.0f} Hz")
    ax2.set_xlabel("frequency Hz (log)", color="#aaa")
    ax2.set_ylabel("dB", color="#aaa")
    ax2.set_title("measured poles + valley candidates", color="#eaeaea", fontsize=11)
    ax2.set_xlim(60, freqs_raw[-1])
    ax2.legend(labelcolor="#ddd", facecolor=_DARK, edgecolor="#333", fontsize=7, loc="upper right",
               ncol=2)
    fig2.tight_layout()
    fig2.savefig(out_dir / "peak_valley_candidates.png", dpi=110)
    plt.close(fig2)


def plot_pz_map(out_dir: Path, lanes: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(7, 7))
    fig.patch.set_facecolor(_DARK)
    _dark_ax(ax)
    # Unit circle
    theta = np.linspace(0, 2 * np.pi, 400)
    ax.plot(np.cos(theta), np.sin(theta), color="#333", lw=1.0)
    ax.axhline(0, color="#222", lw=0.5)
    ax.axvline(0, color="#222", lw=0.5)
    prov_colors = {"MEASURED": "#ffd23e", "INFERRED": "#2ec4ff",
                   "INVENTED": "#ff6b6b", "IDENTITY": "#555"}
    for l in lanes:
        hz, r = l["pole_hz"], l["pole_r"]
        theta_p = 2 * np.pi * hz / AUTHORING_SR
        px, py = r * np.cos(theta_p), r * np.sin(theta_p)
        col = prov_colors.get(l["provenance"], "#aaa")
        # Pole (x marker)
        ax.plot([px, px], [py, py], marker="x", ms=10, color=col, mew=2.0)
        ax.plot([px], [-py], marker="x", ms=10, color=col, mew=2.0)
        # Zero (o marker)
        z_hz = l.get("zero_hz")
        z_r = l.get("zero_r", 0.0)
        if z_hz is not None and l["zero_treatment"] != "NEUTRAL":
            theta_z = 2 * np.pi * z_hz / AUTHORING_SR
            zx, zy = z_r * np.cos(theta_z), z_r * np.sin(theta_z)
            ax.plot([zx], [zy], marker="o", ms=8, color=col, mfc="none", mew=1.5)
            ax.plot([zx], [-zy], marker="o", ms=8, color=col, mfc="none", mew=1.5)
    # Legend
    from matplotlib.lines import Line2D
    legend_handles = [Line2D([0], [0], marker="x", color=c, ls="none", ms=9, mew=2,
                             label=f"{k} pole")
                      for k, c in prov_colors.items()]
    ax.legend(handles=legend_handles, labelcolor="#ddd", facecolor=_DARK,
              edgecolor="#333", fontsize=8, loc="upper left")
    ax.set_aspect("equal")
    ax.set_title("six-actor pole/zero map (authoring SR)", color="#eaeaea", fontsize=11)
    ax.set_xlabel("Re(z)", color="#aaa")
    ax.set_ylabel("Im(z)", color="#aaa")
    fig.tight_layout()
    fig.savefig(out_dir / "six_actor_pz_map.png", dpi=110)
    plt.close(fig)


def _lanes_to_corner_words(lanes: list[dict]) -> list[tuple[int, ...]]:
    return [lane_words(l) for l in lanes]


def _response_from_lanes(lanes: list[dict]) -> np.ndarray:
    words = _lanes_to_corner_words(lanes)
    enc = [EncodedCoeffs(*words_to_coeffs(w)) for w in words]
    return cascade_response_db(enc, FREQS)


def plot_six_actor_response(out_dir: Path, corners: dict[str, list[dict]],
                            source_name: str, measured_poles: list[tuple[float, float]]) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor(_DARK)
    _dark_ax(ax)
    styles = {"M0_S0": ("#2ec4ff", 1.4), "M1_S0": ("#ffd23e", 1.4),
              "M0_S1": ("#ff6b6b", 1.4), "M1_S1": ("#9b8cff", 1.4)}
    for cname, (col, lw) in styles.items():
        y = _response_from_lanes(corners[cname])
        y -= float(np.nanmax(y))
        ax.semilogx(FREQS, np.clip(y, -54, 3), color=col, lw=lw, alpha=0.85, label=cname)
    # Middle at (0.5, 0.5) — average of corner responses as proxy (no FFI needed)
    ys = [_response_from_lanes(corners[k]) for k in ("M0_S0", "M1_S0", "M0_S1", "M1_S1")]
    y_mid = sum(ys) / 4.0
    y_mid -= float(np.nanmax(y_mid))
    ax.semilogx(FREQS, np.clip(y_mid, -54, 3), color=_GREEN, lw=2.4, label="MIDDLE (avg)")
    # Measured pole markers
    for f, r in measured_poles:
        ax.axvline(f, color="#ffd23e", lw=0.8, alpha=0.35, ls="--")
    ax.set_xlim(60, 20000)
    ax.set_ylim(-54, 5)
    ax.grid(True, which="both", alpha=0.12)
    ax.set_xlabel("frequency Hz (log)", color="#aaa")
    ax.set_ylabel("dB", color="#aaa")
    ax.set_title(f"{source_name} — six-actor response (four corners + middle)",
                 color="#eaeaea", fontsize=11)
    ax.legend(labelcolor="#ddd", facecolor=_DARK, edgecolor="#333", fontsize=9, loc="upper right")
    fig.tight_layout()
    fig.savefig(out_dir / "six_actor_response.png", dpi=110)
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Compile and render end-to-end
# ─────────────────────────────────────────────────────────────────────────────

_CORNER_ALIAS = {"M0_S0": "M0_Q0", "M1_S0": "M100_Q0",
                 "M0_S1": "M0_Q100", "M1_S1": "M100_Q100"}


def compile_and_render(corners: dict[str, list[dict]],
                       out_dir: Path, source_name: str,
                       measured_poles: list[tuple[float, float]]) -> Path:
    """Compile body240 via author_lanes -> author_body, render via shipped engine."""
    # Build packed-body-v1 doc
    doc = body_to_packed_v1(source_name, corners)
    body_v1_path = out_dir / f"{source_name}.bodyv1.json"
    body_v1_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    cart_path = out_dir / f"{source_name}.cart.json"
    raw_path = out_dir / f"{source_name}.body240"

    result = subprocess.run(
        [sys.executable, "-m", "tools.author_body", str(body_v1_path),
         "-o", str(cart_path), "--raw-out", str(raw_path),
         "--name", source_name],
        cwd=str(ROOT), capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  author_body stderr: {result.stderr.strip()}", file=sys.stderr)
        raise RuntimeError(f"author_body failed for {source_name}")
    print(f"  compiled  -> {raw_path} ({raw_path.stat().st_size} bytes)")

    cart = json.loads(cart_path.read_text())

    # Build body_bytes from cart (same as render_audition.py::body_bytes_from_cart)
    import struct
    flat = []
    for kf in cart["keyframes"]:
        for w in kf["packedWords"]:
            flat.extend(int(x) & 0xFFFF for x in w)
    bb = struct.pack("<" + "H" * 120, *flat)

    # Build corner words dict for pure-Python response (no FFI for response)
    cw = {k: [tuple(w) for w in kf["packedWords"]]
          for k, kf in zip(("A", "B", "C", "D"), cart["keyframes"])}

    # 808 synth source (from render_audition.py)
    sr_render = 44100
    n = int(sr_render * 0.7)
    t = np.arange(n) / sr_render
    f = 50.0 + 60.0 * np.exp(-t / 0.03)
    phase = 2.0 * np.pi * np.cumsum(f) / sr_render
    body = np.sin(phase) * np.exp(-t / 0.28)
    click = np.zeros(n)
    c = int(sr_render * 0.004)
    click[:c] = np.linspace(1.0, 0.0, c)
    src_808 = (body + 0.25 * click).astype(np.float32)

    gap = np.zeros(int(sr_render * 0.12), dtype=np.float64)
    use_engine = trench_ffi.engine_available()
    positions = [("M0_S0", 0.0, 0.0), ("M1_S0", 1.0, 0.0),
                 ("M0_S1", 0.0, 1.0), ("M1_S1", 1.0, 1.0), ("MIDDLE", 0.5, 0.5)]
    segs: list[np.ndarray] = []

    for label, m, q in positions:
        if use_engine:
            raw = trench_ffi.engine_render(bb, m, q, src_808.tobytes(), sr_render)
            wet = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
        else:
            # Python cascade fallback (no AGC)
            from pyruntime.packed_interp import _packed_bilinear_reference
            coeffs = _packed_bilinear_reference(cw, m, q)
            from tools.render_audition import df2t
            wet = df2t(src_808.astype(np.float64), [EncodedCoeffs(*c) for c in coeffs])
        pk = np.max(np.abs(wet))
        if pk > 1e-9:
            wet = wet / pk * 0.9
        segs.extend([wet, gap])

    audio = np.concatenate(segs)
    engine_note = "shipped engine (AGC+saturate)" if use_engine else "Python cascade (no AGC)"
    print(f"  engine    = {engine_note}")

    # Write wav
    import wave as wv
    audio_path = out_dir / f"{source_name}_corners.wav"
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wv.open(str(audio_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr_render)
        w.writeframes(pcm.tobytes())
    print(f"  audio     -> {audio_path}")

    # Response curve PNG (from corner words, via pure-Python cascade)
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor(_DARK)
    _dark_ax(ax)
    corner_colors = {"M0_S0": "#2ec4ff", "M1_S0": "#ffd23e",
                     "M0_S1": "#ff6b6b", "M1_S1": "#9b8cff"}
    for corner_name, (m, q) in [("M0_S0", (0.0, 0.0)), ("M1_S0", (1.0, 0.0)),
                                  ("M0_S1", (0.0, 1.0)), ("M1_S1", (1.0, 1.0))]:
        from pyruntime.packed_interp import _packed_bilinear_reference
        coeffs = _packed_bilinear_reference(cw, m, q)
        enc = [EncodedCoeffs(*c) for c in coeffs]
        y = cascade_response_db(enc, FREQS)
        y -= float(np.nanmax(y))
        ax.semilogx(FREQS, np.clip(y, -54, 3), color=corner_colors[corner_name],
                    lw=1.5, label=corner_name)
    # Middle
    coeffs_mid = _packed_bilinear_reference(cw, 0.5, 0.5)
    enc_mid = [EncodedCoeffs(*c) for c in coeffs_mid]
    y_mid = cascade_response_db(enc_mid, FREQS)
    y_mid -= float(np.nanmax(y_mid))
    ax.semilogx(FREQS, np.clip(y_mid, -54, 3), color=_GREEN, lw=2.4, label="MIDDLE")
    # Measured pole markers
    for f, r in measured_poles:
        ax.axvline(f, color="#ffd23e", lw=0.9, alpha=0.4, ls="--")
    ax.set_xlim(60, 20000)
    ax.set_ylim(-54, 5)
    ax.grid(True, which="both", alpha=0.12)
    ax.set_xlabel("frequency Hz (log)", color="#aaa")
    ax.set_ylabel("dB (normalized)", color="#aaa")
    ax.set_title(f"{source_name} — VERIFIED: packed body response (dashes = measured poles)",
                 color="#eaeaea", fontsize=11)
    ax.legend(labelcolor="#ddd", facecolor=_DARK, edgecolor="#333", fontsize=9, loc="upper right")
    fig.tight_layout()
    resp_png = out_dir / "response_verify.png"
    fig.savefig(resp_png, dpi=110)
    plt.close(fig)
    print(f"  response  -> {resp_png}")

    return raw_path


# ─────────────────────────────────────────────────────────────────────────────
# Provenance tally
# ─────────────────────────────────────────────────────────────────────────────


def print_tally(source_name: str, m0_lanes: list[dict]) -> None:
    from collections import Counter
    tally = Counter(l["provenance"] for l in m0_lanes)
    z_tally = Counter(l["zero_provenance"] for l in m0_lanes)
    print(f"\n  provenance tally [{source_name}] (M0 skeleton):")
    for k in ("MEASURED", "INFERRED", "INVENTED", "IDENTITY"):
        print(f"    pole {k:12s}: {tally.get(k, 0)}")
    print(f"  zero provenances: {dict(z_tally)}")


# ─────────────────────────────────────────────────────────────────────────────
# Per-source processing
# ─────────────────────────────────────────────────────────────────────────────


def process_source(wav_paths: list[Path | None], out_root: Path) -> None:
    """Full pipeline for one or two WAVs (or None for synthetic)."""

    # ── Load / synthesize ──────────────────────────────────────────────────────
    if not wav_paths or wav_paths[0] is None:
        print("\n[synthetic source]")
        sig_a, sr_a = synth_source("A")
        sig_b, sr_b = synth_source("B")
        source_name = "synthetic"
        two_sources = True
    elif len(wav_paths) == 1:
        print(f"\n[WAV source] {wav_paths[0].name}")
        sig_a, sr_a = load_wav(wav_paths[0])
        sig_b, sr_b = None, None
        source_name = wav_paths[0].stem
        two_sources = False
    else:
        print(f"\n[WAV pair] {wav_paths[0].name} + {wav_paths[1].name}")
        sig_a, sr_a = load_wav(wav_paths[0])
        sig_b, sr_b = load_wav(wav_paths[1])
        source_name = wav_paths[0].stem + "_" + wav_paths[1].stem
        two_sources = True

    out_dir = out_root / source_name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  output    -> {out_dir}")

    # ── Sustain window ─────────────────────────────────────────────────────────
    win_a_start, win_a_end = find_sustain_window(sig_a, sr_a)
    frame_a = sig_a[win_a_start:win_a_end]
    print(f"  sustain   = {win_a_start/sr_a:.3f}s – {win_a_end/sr_a:.3f}s "
          f"({len(frame_a)} samples at {sr_a:.0f} Hz)")

    # ── Spectral analysis ──────────────────────────────────────────────────────
    freqs_raw, smoothed = spectral_envelope(frame_a, sr_a)
    n_fft = 4096
    win = np.hanning(len(frame_a))
    padded = np.zeros(n_fft)
    w = min(len(frame_a), n_fft)
    padded[:w] = frame_a[:w] * win[:w]
    spec = np.fft.rfft(padded)
    mag_db_raw = 20.0 * np.log10(np.maximum(np.abs(spec), 1e-12))

    # ── LPC poles ──────────────────────────────────────────────────────────────
    poles_a = extract_lpc_poles(frame_a, sr_a, order=LPC_ORDER)
    print(f"  LPC poles = {len(poles_a)} (MEASURED): "
          + ", ".join(f"{f:.0f}Hz r={r:.3f}" for f, r in poles_a))

    valleys = detect_valleys(freqs_raw, smoothed)
    print(f"  valleys   = {len(valleys)} (MEASURED_VALLEY): "
          + ", ".join(f"{v:.0f}Hz" for v in valleys[:4]))

    # ── Six-lane fill ──────────────────────────────────────────────────────────
    m0_lanes = fill_six_lanes(poles_a, valleys, source_name)

    if two_sources and sig_b is not None:
        win_b_start, win_b_end = find_sustain_window(sig_b, sr_b)
        frame_b = sig_b[win_b_start:win_b_end]
        poles_b = extract_lpc_poles(frame_b, sr_b, order=LPC_ORDER)
        print(f"  LPC poles (M1) = {len(poles_b)} (MEASURED): "
              + ", ".join(f"{f:.0f}Hz r={r:.3f}" for f, r in poles_b))
        freqs_raw_b, smoothed_b = spectral_envelope(frame_b, sr_b)
        valleys_b = detect_valleys(freqs_raw_b, smoothed_b)
        m1_lanes = fill_six_lanes(poles_b, valleys_b, source_name + "_B")
        # Align pairs so lane i always corresponds to lane i at runtime
        m0_lanes, m1_lanes = align_lane_pairs(m0_lanes, m1_lanes)
    else:
        # Single source -> morph variant by frequency shift
        m1_lanes = make_morph_variant(m0_lanes, semitones=1.5)
        print("  M1 variant = +1.5 semitone shift (INFERRED)")

    # ── Plots ──────────────────────────────────────────────────────────────────
    plot_window(out_dir, sig_a, sr_a, win_a_start, win_a_end)
    plot_spectrum(out_dir, freqs_raw, mag_db_raw, smoothed, poles_a, valleys)
    plot_pz_map(out_dir, m0_lanes)

    corners = build_corners(m0_lanes, m1_lanes)
    plot_six_actor_response(out_dir, corners, source_name, poles_a)
    print(f"  plots     -> {out_dir}/*.png")

    # ── Skeleton JSON ──────────────────────────────────────────────────────────
    skeleton = {
        "source": source_name,
        "authoring_sr": AUTHORING_SR,
        "notes": "pole provenance: MEASURED = LPC on source; zeros are always INFERRED or INVENTED (LPC is all-pole)",
        "m0_lanes": m0_lanes,
        "m1_lanes": m1_lanes,
    }
    sk_path = out_dir / f"{source_name}.skeleton.json"
    sk_path.write_text(json.dumps(skeleton, indent=2), encoding="utf-8")
    print(f"  skeleton  -> {sk_path}")

    # ── Compile & render (end-to-end verification) ────────────────────────────
    compile_and_render(corners, out_dir, source_name, poles_a)

    # ── Tally ──────────────────────────────────────────────────────────────────
    print_tally(source_name, m0_lanes)

    print(f"\n  DONE. Open {out_dir / 'response_verify.png'} to verify poles sit on resonances.")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wav", type=Path, action="append", dest="wavs", metavar="PATH",
                    help="source WAV (use twice for morph pair; omit for synthetic self-test)")
    ap.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "actor_extract",
                    help="output root directory (default: dev/tmp/actor_extract)")
    args = ap.parse_args(argv)

    out_root = args.out
    out_root.mkdir(parents=True, exist_ok=True)

    wav_paths = args.wavs or [None]
    process_source(wav_paths, out_root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
