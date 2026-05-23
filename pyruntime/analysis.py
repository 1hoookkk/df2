"""Body analysis — motion, crossings, cancellations, profile.

Judges body quality like a Z-plane sound designer: morph trajectory
distance, spectral zero crossings, pole-zero proximity, composite profile.
"""
from __future__ import annotations

import math

import numpy as np

from pyruntime.body import Body
from pyruntime.constants import SR
from pyruntime.corner import CornerName, CornerState
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.stage_params import StageParams


def morph_trajectory_distance(body: Body) -> dict:
    """RMS spectral distance between M0 and M100 corners.

    Measures at both Q=0 and Q=1.  Higher = more morph motion.
    Zero = static filter (morph knob does nothing).

    Returns {"q0_rms_db": float, "q1_rms_db": float, "mean_rms_db": float}.
    """
    freqs = freq_points()
    sr = SR

    # M0_Q0 vs M100_Q0
    enc_m0_q0 = body.corners.interpolate(0.0, 0.0)
    enc_m100_q0 = body.corners.interpolate(1.0, 0.0)
    db_m0_q0 = cascade_response_db(enc_m0_q0, freqs, sr)
    db_m100_q0 = cascade_response_db(enc_m100_q0, freqs, sr)
    q0_rms = _rms_distance(db_m0_q0, db_m100_q0)

    # M0_Q1 vs M100_Q1
    enc_m0_q1 = body.corners.interpolate(0.0, 1.0)
    enc_m100_q1 = body.corners.interpolate(1.0, 1.0)
    db_m0_q1 = cascade_response_db(enc_m0_q1, freqs, sr)
    db_m100_q1 = cascade_response_db(enc_m100_q1, freqs, sr)
    q1_rms = _rms_distance(db_m0_q1, db_m100_q1)

    mean_rms = (q0_rms + q1_rms) / 2.0

    return {
        "q0_rms_db": float(q0_rms),
        "q1_rms_db": float(q1_rms),
        "mean_rms_db": float(mean_rms),
    }


def zero_crossing_count(encoded_stages: list, freqs: np.ndarray, sr: float) -> int:
    """Count where cascade magnitude response crosses 0 dB.

    More crossings = more complex spectral shape.
    """
    if not encoded_stages:
        return 0
    db = cascade_response_db(encoded_stages, freqs, sr)
    if len(db) < 2:
        return 0
    # Sign changes in the dB array (positive = above 0 dB, negative = below)
    signs = np.sign(db)
    # A crossing occurs where consecutive signs differ (and neither is zero)
    diffs = np.diff(signs)
    return int(np.count_nonzero(diffs))


def pole_zero_proximity(stage: StageParams) -> float:
    """Angular distance between pole and zero for a single stage.

    Close to 0 = cancellation.  Large = reinforcement.
    Passthrough stages (r < 0.01) return pi (not meaningful).
    """
    if stage.r < 0.01:
        return math.pi

    r = stage.r
    a1 = stage.a1

    # Pole angle: acos(-a1 / (2*r))
    pole_arg = -a1 / (2.0 * r)
    pole_arg = max(-1.0, min(1.0, pole_arg))
    pole_angle = math.acos(pole_arg)

    # Zero coefficients: b1 = a1 + val2, b2 = r^2 - val3
    b1 = a1 + stage.val2
    b2 = r * r - stage.val3

    if b2 <= 0.0:
        # Zero radius is zero or imaginary — no meaningful angle
        return math.pi

    zero_r = math.sqrt(b2)
    zero_arg = -b1 / (2.0 * zero_r)
    zero_arg = max(-1.0, min(1.0, zero_arg))
    zero_angle = math.acos(zero_arg)

    return abs(pole_angle - zero_angle)


def body_profile(body: Body) -> dict:
    """Composite analysis combining all metrics.

    Returns a dict with morph distance, per-corner crossing counts,
    stage proximity scores, active stage count, and spectral tilt.
    """
    freqs = freq_points()
    sr = SR

    # Morph trajectory
    morph_dist = morph_trajectory_distance(body)

    # Encoded corners for crossing counts
    enc_m0_q0 = body.corners.interpolate(0.0, 0.0)
    enc_m0_q100 = body.corners.interpolate(0.0, 1.0)
    enc_m100_q0 = body.corners.interpolate(1.0, 0.0)
    enc_m100_q100 = body.corners.interpolate(1.0, 1.0)

    crossings = {
        "m0_q0": zero_crossing_count(enc_m0_q0, freqs, sr),
        "m0_q100": zero_crossing_count(enc_m0_q100, freqs, sr),
        "m100_q0": zero_crossing_count(enc_m100_q0, freqs, sr),
        "m100_q100": zero_crossing_count(enc_m100_q100, freqs, sr),
    }

    # Stage proximity from raw StageParams at corner A (M0_Q0)
    corner_a = body.corners.corner(CornerName.A)
    raw_stages = corner_a.stages

    stage_prox = [pole_zero_proximity(s) for s in raw_stages]

    active = sum(1 for s in raw_stages if s.r > 0.01)

    # Spectral tilt at M0_Q0
    db_a = cascade_response_db(enc_m0_q0, freqs, sr)
    if len(db_a) >= 2:
        tilt = float(db_a[-1] - db_a[0])
    else:
        tilt = 0.0

    audit = midpoint_audit(body)

    return {
        "morph_distance": morph_dist,
        "crossings": crossings,
        "stage_proximity": stage_prox,
        "active_stages": active,
        "spectral_tilt_db": tilt,
        "midpoint_audit": audit,
    }


def midpoint_audit(body: Body, peak_limit_db: float = 35.0) -> dict:
    """Audit the morph trajectory for resonance spikes.

    The midpoint collapse: if stages are scrambled between corners,
    interpolating coefficients at 25%/50%/75% morph can cause poles
    to tear across the unit circle, producing catastrophic gain stacking.

    Tests morph at 0.0, 0.25, 0.5, 0.75, 1.0 for both Q=0 and Q=1.
    Returns pass/fail with peak dB at each test point.

    peak_limit_db: maximum allowed cascade peak (default 35 dB).
    """
    freqs = freq_points()
    sr = SR
    test_morphs = [0.0, 0.25, 0.5, 0.75, 1.0]
    test_qs = [0.0, 1.0]

    worst_peak = -999.0
    worst_point = (0.0, 0.0)
    points = []

    for m in test_morphs:
        for q in test_qs:
            enc = body.corners.interpolate(m, q)
            db = cascade_response_db(enc, freqs, sr)
            peak = float(np.max(db))
            points.append({"morph": m, "q": q, "peak_db": round(peak, 1)})
            if peak > worst_peak:
                worst_peak = peak
                worst_point = (m, q)

    passed = worst_peak <= peak_limit_db

    return {
        "passed": passed,
        "worst_peak_db": round(worst_peak, 1),
        "worst_point": {"morph": worst_point[0], "q": worst_point[1]},
        "peak_limit_db": peak_limit_db,
        "points": points,
    }


def _rms_distance(a: np.ndarray, b: np.ndarray) -> float:
    """RMS of element-wise difference between two dB arrays."""
    diff = a - b
    return float(np.sqrt(np.mean(diff * diff)))
