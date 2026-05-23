"""Pre-filter drive stages for the authoring chain.

These run during body audition so authors hear through the same
saturation the plugin applies.

Vectorized with numpy/scipy where possible. Per-sample loops
only for inherently sequential processors (corrode delta modulator).
"""

import math
import numpy as np
import scipy.signal

# ── Mackie 1202 ────────────────────────────────────────────────────

DC_BLOCK_HZ = 5.0
DIODE_KNEE = 0.70


def mackie_drive(samples: np.ndarray, drive: float = 0.5, sr: float = 44100.0) -> np.ndarray:
    """Mackie 1202 input stage: DC block + diode soft clip. Vectorized."""
    if drive < 1e-6:
        return samples.copy()

    # DC blocking via scipy 1-pole HPF
    wn = DC_BLOCK_HZ / (sr / 2)
    b, a = scipy.signal.butter(1, wn, btype='high')
    dc_clean = scipy.signal.lfilter(b, a, samples)

    # Pre-gain
    pre_gain = 1.0 + drive * drive * 7.0
    hot = dc_clean * pre_gain

    # Diode soft clip (vectorized)
    abs_hot = np.abs(hot)
    sign = np.sign(hot)
    headroom = 1.0 - DIODE_KNEE
    excess = abs_hot - DIODE_KNEE
    compressed = DIODE_KNEE + headroom * np.tanh(excess / headroom)
    clipped = np.where(abs_hot <= DIODE_KNEE, hot, sign * compressed)
    clipped = np.clip(clipped, -1.0, 1.0)

    # Makeup gain
    makeup = 1.0 / math.sqrt(pre_gain)
    return clipped * makeup


# ── Erode (adaptive quantizer) ────────────────────────────────────

MIN_STEP = 1.0 / 65536.0
MAX_STEP = 1.0 / 3.0


def erode(samples: np.ndarray, amount: float = 0.5, sr: float = 44100.0) -> np.ndarray:
    """Adaptive re-quantizer. Sequential (envelope follower has feedback)."""
    if amount < 1e-6:
        return samples.copy()

    out = np.empty_like(samples)
    attack_coeff = 1.0 - math.exp(-1.0 / (0.0001 * sr))
    release_coeff = 1.0 - math.exp(-1.0 / (0.004 * sr))
    envelope = 0.0

    for i in range(len(samples)):
        x = float(samples[i])
        level = abs(x)

        if level > envelope:
            envelope += attack_coeff * (level - envelope)
        else:
            envelope += release_coeff * (level - envelope)

        step = MIN_STEP + (MAX_STEP - MIN_STEP) * amount * max(envelope, 0.01)
        quantized = round(x / step) * step
        out[i] = x * (1.0 - amount) + quantized * amount

    return out


# ── Corrode (delta modulator) ─────────────────────────────────────

STEP_UP = 1.5
STEP_DOWN = 0.5
MIN_DELTA_STEP = 1e-6
MAX_DELTA_STEP = 0.5
SAME_SIGN_THRESH = 3


def corrode(samples: np.ndarray, amount: float = 0.5, sr: float = 44100.0) -> np.ndarray:
    """1-bit delta modulator. Inherently sequential (feedback loop)."""
    if amount < 1e-6:
        return samples.copy()

    out = np.empty_like(samples)
    charge_coeff = 1.0 - math.exp(-1.0 / (0.039 * sr))
    discharge_coeff = 1.0 - math.exp(-1.0 / (0.017 * sr))
    integrator_coeff = 1.0 - math.exp(-1.0 / (0.0044 * sr))

    reconstruction = 0.0
    step_size = 0.001
    same_sign_count = 0
    last_sign = 0

    for i in range(len(samples)):
        x = float(samples[i])
        delta = 1 if x >= reconstruction else -1

        if delta == last_sign:
            same_sign_count += 1
        else:
            same_sign_count = 1
        last_sign = delta

        target_step = step_size * (STEP_UP if same_sign_count >= SAME_SIGN_THRESH else STEP_DOWN)
        target_step = max(MIN_DELTA_STEP, min(MAX_DELTA_STEP, target_step))

        if target_step > step_size:
            step_size += charge_coeff * (target_step - step_size)
        else:
            step_size += discharge_coeff * (target_step - step_size)

        reconstruction += integrator_coeff * (delta * step_size - reconstruction)
        out[i] = x * (1.0 - amount) + reconstruction * amount

    return out


# ── Combined authoring chain ──────────────────────────────────────

def authoring_drive_chain(
    samples: np.ndarray,
    mackie_amount: float = 0.5,
    erode_amount: float = 0.0,
    corrode_amount: float = 0.0,
    sr: float = 44100.0,
) -> np.ndarray:
    """Full pre-filter drive chain for body audition.

    Default: mackie at 0.5, erode/corrode off.
    """
    out = samples
    if erode_amount > 1e-6:
        out = erode(out, erode_amount, sr)
    if corrode_amount > 1e-6:
        out = corrode(out, corrode_amount, sr)
    out = mackie_drive(out, mackie_amount, sr)
    return out
