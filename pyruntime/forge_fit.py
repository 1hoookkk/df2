"""forge_fit.py — Bark/ERB-weighted phase-aware cascade fitter.

THE FORGE. Authors original 6-biquad bodies by fitting a target complex
cascade response. The fit is phase-aware: the acceptance gate is a
time-domain null, so a magnitude-only fit is insufficient — phase error
shows up as residual energy after sample-aligned subtraction.

Perceptual error weighting (Bark for mids, ERB-rate for lows) shapes
*where* the 6 biquads' limited resolution is spent. The emphasis profile
moves per body (vocal → Bark mids, sub → ERB lows, bright → high band).
The weighting modulates a complex-domain least-squares fit; it does not
turn the fit into a magnitude fit.

Coefficient domain: each stage is fitted as five minifloat-decode
components d0..d4 in [0, 1]. That is the cartridge's native authoring
domain — kernel coefficients recombine as

    c0 = 4*d0 + d1   c1 = d1   c2 = 4*d2 + d3   c3 = d3   c4 = 4*d4

(the verified E-mu recombination, see pyruntime/packed_interp.py). Box
bounds [0, 1] on d guarantee the authored corner survives the
encode -> u16 -> decode round trip without saturation, so a tight fit
post-encode stays tight.

Forge pipeline. This module must NEVER import heritage_coeffs.py or
designer_compile.py (the Compiler). It only fits measured responses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import find_peaks

NUM_STAGES = 6
NUM_COEFFS = 5
COMBINE_K = 4.0
_STAB_PENALTY = 1.0e3

# Near-passthrough stage in d-space (H(z) == 1): c4=1, c2=2, c3=0, c0=2, c1=1.
PASSTHRU_D = np.array([0.25, 1.0, 0.5, 0.0, 0.25], dtype=np.float64)


# ── perceptual band-rate scales ────────────────────────────────────────────

def hz_to_bark(f: np.ndarray) -> np.ndarray:
    """Traunmüller Bark band-rate. Critical-band resolution for mids."""
    f = np.asarray(f, dtype=np.float64)
    return 13.0 * np.arctan(0.00076 * f) + 3.5 * np.arctan((f / 7500.0) ** 2)


def hz_to_erb_rate(f: np.ndarray) -> np.ndarray:
    """Glasberg & Moore ERB-rate. Finer than Bark below ~500 Hz — the
    right scale when the body's character lives in the lows."""
    f = np.asarray(f, dtype=np.float64)
    return 21.4 * np.log10(0.00437 * f + 1.0)


# Per-body emphasis profiles: (band-rate scale, emphasis center Hz,
# emphasis width in octaves, emphasis gain dB). None = flat (band-rate
# equalised only). See BODIES.md for which body wants which.
PROFILES: dict[str, tuple | None] = {
    "flat":   None,
    "vocal":  ("bark", 1500.0, 2.2, 6.0),    # Small Talk / Talking Hedz
    "sub":    ("erb",   60.0,  1.6, 9.0),    # Speaker Knockerz
    "bright": ("bark", 8000.0, 1.8, 6.0),    # Aluminum Siding
    "broad":  ("bark", 1000.0, 4.0, 3.0),    # Cul-De-Sac
}


def perceptual_weight(freqs: np.ndarray, profile: str = "vocal") -> np.ndarray:
    """Per-frequency error weight W(f) for the fit residual.

    Two factors, multiplied:
      1. Band-rate equaliser — so a log-frequency grid contributes roughly
         equal weight per critical band (Bark or ERB), not per decade.
      2. A raised-cosine emphasis bump in log-frequency, centred per the
         body profile. `flat` skips the bump.

    Normalised to mean 1 and clipped to [0.1, 10] so least_squares stays
    well-conditioned.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    spec = PROFILES.get(profile, PROFILES["vocal"])

    if spec is None:
        w = np.ones_like(freqs)
    else:
        scale, _c, _w, _g = spec
        rate = hz_to_erb_rate(freqs) if scale == "erb" else hz_to_bark(freqs)
        # dRate/dlog(f): critical bands spanned per log-frequency cell.
        density = np.gradient(rate, np.log(freqs))
        w = np.sqrt(np.clip(density / np.mean(density), 1e-6, None))

    if spec is not None:
        _scale, center, width_oct, gain_db = spec
        oct_dist = np.log2(np.maximum(freqs, 1e-6) / center)
        bump = np.cos(np.clip(oct_dist / width_oct, -1.0, 1.0) * (np.pi / 2.0))
        bump = np.where(np.abs(oct_dist) <= width_oct, bump, 0.0)
        w = w * (10.0 ** (gain_db / 20.0 * bump))

    w = w / np.mean(w)
    return np.clip(w, 0.1, 10.0)


# ── coefficient domain ─────────────────────────────────────────────────────

def d_to_kernel(d: np.ndarray) -> np.ndarray:
    """d-space (NUM_STAGES, 5) in [0,1] -> kernel-form c0..c4."""
    d = np.asarray(d, dtype=np.float64).reshape(NUM_STAGES, NUM_COEFFS)
    k = np.empty_like(d)
    k[:, 0] = COMBINE_K * d[:, 0] + d[:, 1]
    k[:, 1] = d[:, 1]
    k[:, 2] = COMBINE_K * d[:, 2] + d[:, 3]
    k[:, 3] = d[:, 3]
    k[:, 4] = COMBINE_K * d[:, 4]
    return k


def kernel_to_d(k: np.ndarray) -> np.ndarray:
    """Inverse of d_to_kernel. Result is clipped into [0,1]."""
    k = np.asarray(k, dtype=np.float64).reshape(NUM_STAGES, NUM_COEFFS)
    d = np.empty_like(k)
    d[:, 1] = k[:, 1]
    d[:, 3] = k[:, 3]
    d[:, 0] = (k[:, 0] - k[:, 1]) / COMBINE_K
    d[:, 2] = (k[:, 2] - k[:, 3]) / COMBINE_K
    d[:, 4] = k[:, 4] / COMBINE_K
    return np.clip(d, 0.0, 1.0)


def cascade_response(kernel: np.ndarray, z_inv: np.ndarray) -> np.ndarray:
    """Complex cascade response: product of per-stage biquad responses.

    Kernel -> biquad: a1=c2-2, a2=1-c3, b0=c4, b1=(c0-2)c4, b2=(1-c1)c4.
    Matches pyruntime/freq_response.py exactly.
    """
    kernel = np.asarray(kernel, dtype=np.float64).reshape(NUM_STAGES, NUM_COEFFS)
    c0, c1, c2, c3, c4 = (kernel[:, i] for i in range(5))
    a1 = c2 - 2.0
    a2 = 1.0 - c3
    b0 = c4
    b1 = (c0 - 2.0) * c4
    b2 = (1.0 - c1) * c4

    z1 = z_inv[None, :]
    z2 = z1 * z1
    num = b0[:, None] + b1[:, None] * z1 + b2[:, None] * z2
    den = 1.0 + a1[:, None] * z1 + a2[:, None] * z2
    return np.prod(num / den, axis=0)


def _stability_penalty(kernel: np.ndarray) -> np.ndarray:
    """Per-stage penalty: 0 inside the z^2+a1 z+a2 stability triangle,
    positive (and large) outside it. a2<1 is held by the d bounds; this
    guards the two real-pole edges a2 > |a1| - 1."""
    a1 = kernel[:, 2] - 2.0
    a2 = 1.0 - kernel[:, 3]
    return (np.maximum(0.0, a1 - 1.0 - a2)
            + np.maximum(0.0, -a1 - 1.0 - a2))


# ── frequency grid ─────────────────────────────────────────────────────────

def fit_grid(sr: float, n: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Log-spaced fit frequencies and their z^-1 = exp(-j w) values."""
    freqs = np.logspace(np.log10(20.0), np.log10(sr * 0.499), n)
    z_inv = np.exp(-1j * 2.0 * np.pi * freqs / sr)
    return freqs, z_inv


# ── fit result ─────────────────────────────────────────────────────────────

@dataclass
class CornerFit:
    d: np.ndarray                 # (6,5) authored d-space coefficients
    kernel: np.ndarray            # (6,5) authored kernel c0..c4
    response_null_db: float       # weighted complex response match vs target
    restarts: int = 0
    best_restart: int = 0
    stable: bool = True
    notes: list[str] = field(default_factory=list)


# ── the fitter ─────────────────────────────────────────────────────────────

def _seed_peak_picked(target: np.ndarray, freqs: np.ndarray,
                      sr: float, rng: np.random.Generator,
                      jitter: float = 0.0) -> np.ndarray:
    """Initialise d-space from the target's magnitude peaks.

    The strongest resonances of |target| become pole frequencies; unused
    stages start as near-passthrough. This is the 'measure the envelope'
    half of the Clean Room rule — it reads the response curve, never the
    source coefficients.
    """
    mag = 20.0 * np.log10(np.maximum(np.abs(target), 1e-12))
    idx, _ = find_peaks(mag, prominence=1.0)
    if len(idx) == 0:
        idx = np.array([np.argmax(mag)])
    order = np.argsort(mag[idx])[::-1]
    peak_freqs = freqs[idx[order]][:NUM_STAGES]

    d = np.tile(PASSTHRU_D, (NUM_STAGES, 1)).astype(np.float64)
    for si, fp in enumerate(peak_freqs):
        if jitter:
            fp = fp * (2.0 ** (rng.normal(0.0, jitter)))
        fp = float(np.clip(fp, 20.0, sr * 0.49))
        r = float(np.clip(0.96 + rng.normal(0.0, 0.02 * (jitter > 0)), 0.5, 0.999))
        theta = 2.0 * np.pi * fp / sr
        a2 = r * r
        a1 = -2.0 * r * np.cos(theta)
        d3 = 1.0 - a2                       # c3
        d2 = (a1 + 2.0 - d3) / COMBINE_K    # (c2-c3)/4
        # mild on-circle-ish zero numerator; refine will shape it
        d[si] = [0.5, 0.25, np.clip(d2, 0.0, 1.0), np.clip(d3, 0.0, 1.0), 0.25]
    return np.clip(d, 0.0, 1.0)


def _seed_random(rng: np.random.Generator) -> np.ndarray:
    """A biased random d-space seed: sharp-ish poles, modest gain."""
    d = np.empty((NUM_STAGES, NUM_COEFFS))
    d[:, 0] = rng.uniform(0.30, 0.70, NUM_STAGES)
    d[:, 1] = rng.uniform(0.00, 0.60, NUM_STAGES)
    d[:, 2] = rng.uniform(0.20, 0.80, NUM_STAGES)
    d[:, 3] = rng.uniform(0.00, 0.35, NUM_STAGES)   # small c3 -> r near 1
    d[:, 4] = rng.uniform(0.05, 0.45, NUM_STAGES)
    return d


def _response_null_db(kernel: np.ndarray, z_inv: np.ndarray,
                      target: np.ndarray, weight: np.ndarray) -> float:
    """Weighted complex response match, in dB. Lower is better."""
    h = cascade_response(kernel, z_inv)
    res = weight * (h - target)
    ref = weight * target
    num = float(np.sqrt(np.mean(np.abs(res) ** 2)))
    den = float(np.sqrt(np.mean(np.abs(ref) ** 2))) + 1e-30
    return 20.0 * np.log10(num / den + 1e-30)


def fit_corner(target: np.ndarray, freqs: np.ndarray, z_inv: np.ndarray,
               sr: float, profile: str = "vocal",
               n_restarts: int = 16, seed: int = 0,
               weight: np.ndarray | None = None) -> CornerFit:
    """Fit one corner's complex response with a 6-biquad cascade.

    Phase-aware: the residual is the complex difference H_fit - H_target,
    perceptually weighted, with real and imaginary parts both minimised.

    Args:
        target:  complex target response on `freqs`.
        freqs, z_inv: from fit_grid().
        sr:      sample rate the response was measured at.
        profile: perceptual emphasis profile (see PROFILES). Used only
                 when `weight` is None.
        n_restarts: random/peak-picked restarts; best result is kept.
        seed:    RNG seed for reproducibility.
        weight:  optional explicit per-frequency weight. When a corner is
                 fitted against a *measured* wet transfer function, pass
                 perceptual_weight() pre-multiplied by a measurement-
                 reliability term (e.g. magnitude-squared coherence) so
                 the fit ignores frequencies the measurement cannot trust.

    Returns a CornerFit with authored d-space and kernel coefficients.
    """
    target = np.asarray(target, dtype=np.complex128)
    if weight is None:
        weight = perceptual_weight(freqs, profile)
    else:
        weight = np.asarray(weight, dtype=np.float64)
    rng = np.random.default_rng(seed)

    def residual(dflat: np.ndarray) -> np.ndarray:
        kernel = d_to_kernel(dflat)
        h = cascade_response(kernel, z_inv)
        r = weight * (h - target)
        pen = _STAB_PENALTY * _stability_penalty(kernel)
        return np.concatenate([r.real, r.imag, pen])

    lo = np.zeros(NUM_STAGES * NUM_COEFFS)
    hi = np.ones(NUM_STAGES * NUM_COEFFS)

    best: CornerFit | None = None
    for ri in range(n_restarts):
        if ri == 0:
            seed_d = _seed_peak_picked(target, freqs, sr, rng)
        elif ri <= n_restarts // 3:
            seed_d = _seed_peak_picked(target, freqs, sr, rng, jitter=0.15)
        else:
            seed_d = _seed_random(rng)
        x0 = np.clip(seed_d.reshape(-1), lo + 1e-6, hi - 1e-6)

        try:
            sol = least_squares(
                residual, x0, bounds=(lo, hi), method="trf",
                x_scale="jac", ftol=1e-10, xtol=1e-10, gtol=1e-10,
                max_nfev=1500,
            )
        except Exception:  # noqa: BLE001 — a bad restart must not kill the run
            continue

        d = np.clip(sol.x.reshape(NUM_STAGES, NUM_COEFFS), 0.0, 1.0)
        kernel = d_to_kernel(d)
        null_db = _response_null_db(kernel, z_inv, target, weight)
        if best is None or null_db < best.response_null_db:
            stable = bool(np.all(_stability_penalty(kernel) < 1e-9))
            best = CornerFit(d=d, kernel=kernel, response_null_db=null_db,
                             restarts=n_restarts, best_restart=ri,
                             stable=stable)
        if best is not None and best.response_null_db < -120.0:
            break  # already at machine precision — more restarts won't help

    if best is None:
        raise RuntimeError("fit_corner: every restart failed")
    if not best.stable:
        best.notes.append("WARNING: fitted cascade is not pole-stable")
    return best
