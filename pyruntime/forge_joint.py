"""forge_joint.py — joint coherent 4-corner Forge fitter.

Independent per-corner fitting is invalid for morph bodies (STATE.md "THE
LESSON — locked", 2026-05-20). A morphing body is one staged instrument
with four coordinated corners: stage *i* must be the same actor — same
physical resonator role — in every corner. When stages drift identity
across corners, the runtime's u16 bilinear lerp blends nonsense and the
midpoint nulls collapse (≈ −0.69 dB observed).

This module fits all four corners jointly, sharing one 6-stage layout.
Per-corner parameter variation is allowed within per-stage role bounds;
stage identity is anchored two ways:

  1. PER-CORNER SEEDING. Each corner is initialised from its own
     measured pole positions (when seeds are supplied) so the optimiser
     starts already in a coherent factorisation.
  2. PER-STAGE FREQUENCY BAND PENALTY. Each stage carries a
     ``RoleBounds.freq_hz`` range; per-corner-per-stage residual penalty
     pushes the dominant pole back into the band when it strays.

FLUID stages (e.g. F1, F2 in Talking Hedz) get a wide band that spans
the formant-migration range; RIGID stages get tight bands. Overlapping
FLUID bands are disambiguated by per-corner seeds, not bounds.

Coefficient domain matches ``forge_fit.py``: d-space [0, 1]^(6×5) with
kernel-form ``c0 = 4d0 + d1, c1 = d1, c2 = 4d2 + d3, c3 = d3, c4 = 4d4``.
Bounds on d guarantee post-encode survival.

Forge pipeline only. Never imports the Compiler.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from pyruntime.forge_fit import (
    NUM_STAGES, NUM_COEFFS, PASSTHRU_D,
    _seed_peak_picked, _seed_random, _stability_penalty,
    cascade_response, d_to_kernel, perceptual_weight,
)

_BOUNDS_PENALTY = 1.0e2
_STAB_PENALTY = 1.0e3


# ── role bounds ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StageBand:
    """Per-stage role anchor used by the joint fitter.

    ``freq_lo_hz`` / ``freq_hi_hz`` is the band the dominant pole must
    live in across all corners. For FLUID stages this spans the
    migration range; for RIGID stages it is tight. ``radius_lo`` and
    ``radius_hi`` softly bracket how resonant the stage can be —
    primarily a sanity guard.
    """
    freq_lo_hz: float
    freq_hi_hz: float
    radius_lo: float = 0.5
    radius_hi: float = 0.999


# ── derived pole quantities ────────────────────────────────────────────────

def stage_pole_params(kernel: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (pole_freq_hz_proxy, pole_radius, is_resonant) per stage.

    kernel shape (NUM_STAGES, 5). Frequency proxy is the polar angle
    derived from the biquad denominator; when |cos(theta)| > 1 the pole
    pair is real (non-resonant) and we mark it. SR is implicit — the
    caller multiplies by sr / (2π).
    """
    k = np.asarray(kernel, dtype=np.float64).reshape(-1, NUM_COEFFS)
    c2 = k[:, 2]
    c3 = k[:, 3]
    # biquad: a1 = c2 - 2, a2 = 1 - c3. r = sqrt(a2), 2r·cos(theta) = -a1.
    a2 = 1.0 - c3
    a2_safe = np.clip(a2, 1.0e-12, 1.0)
    r = np.sqrt(a2_safe)
    cos_theta = (2.0 - c2) / (2.0 * r + 1.0e-30)
    is_resonant = np.abs(cos_theta) <= 1.0
    theta = np.arccos(np.clip(cos_theta, -1.0, 1.0))  # safe; we mask later
    return theta, r, is_resonant


def _bounds_penalty(kernel: np.ndarray, sr: float,
                    bands: list[StageBand]) -> np.ndarray:
    """Per-stage penalty for pole frequency / radius outside its band.

    Returns shape (NUM_STAGES,). Quadratic-ish: zero inside the band,
    rises with octave distance outside. Only resonant stages incur a
    frequency penalty (real-pole stages are unconstrained).
    """
    theta, r, is_resonant = stage_pole_params(kernel)
    freq = theta * sr / (2.0 * np.pi)

    pen = np.zeros(NUM_STAGES, dtype=np.float64)
    for s, band in enumerate(bands):
        if is_resonant[s]:
            lo, hi = band.freq_lo_hz, band.freq_hi_hz
            if freq[s] < lo:
                pen[s] += np.log2(max(lo / max(freq[s], 1.0), 1.0))
            elif freq[s] > hi:
                pen[s] += np.log2(max(freq[s] / hi, 1.0))
        # radius (gentle): overshoot rare given d in [0,1], but bracket it
        if r[s] < band.radius_lo:
            pen[s] += (band.radius_lo - r[s]) * 2.0
        elif r[s] > band.radius_hi:
            pen[s] += (r[s] - band.radius_hi) * 2.0
    return pen


# ── seeding ────────────────────────────────────────────────────────────────

def _seed_from_pole_freqs(freqs_hz: np.ndarray, sr: float,
                          radius_init: float = 0.96) -> np.ndarray:
    """Build a (6, 5) d-space seed from explicit per-stage pole frequencies.

    Use when each corner has known initial pole positions (e.g. from
    decoding the ROM corner words during calibration). Order matters —
    stage *i* of the seed is stage *i* of the fit.
    """
    d = np.tile(PASSTHRU_D, (NUM_STAGES, 1)).astype(np.float64)
    for si, fp in enumerate(freqs_hz):
        fp = float(np.clip(fp, 20.0, sr * 0.49))
        r = float(np.clip(radius_init, 0.5, 0.999))
        theta = 2.0 * np.pi * fp / sr
        a2 = r * r
        a1 = -2.0 * r * np.cos(theta)
        # back to d-space: c3 = 1 - a2; c2 = 2 + a1; (c2 = 4 d2 + d3)
        d3 = 1.0 - a2
        d2 = (a1 + 2.0 - d3) / 4.0
        d[si] = [0.5, 0.25, np.clip(d2, 0.0, 1.0), np.clip(d3, 0.0, 1.0), 0.25]
    return np.clip(d, 0.0, 1.0)


# ── fit result ─────────────────────────────────────────────────────────────

@dataclass
class JointFit:
    d: dict[str, np.ndarray]              # letter -> (6, 5) d-space
    kernel: dict[str, np.ndarray]         # letter -> (6, 5) kernel
    response_null_db: dict[str, float]    # weighted complex response per corner
    bounds_residual: float                # final aggregated bounds penalty
    stable: dict[str, bool]
    restarts: int = 0
    best_restart: int = 0
    notes: list[str] = field(default_factory=list)


# ── the joint fitter ───────────────────────────────────────────────────────

def joint_fit_corners(
    targets: dict[str, np.ndarray],
    freqs: np.ndarray,
    z_inv: np.ndarray,
    sr: float,
    bands: list[StageBand] | None = None,
    seeds: dict[str, np.ndarray] | None = None,
    profile: str = "vocal",
    weight: np.ndarray | None = None,
    n_restarts: int = 8,
    seed: int = 0,
    max_nfev: int = 2500,
    verbose: bool = False,
) -> JointFit:
    """Fit 4 corners jointly with a shared 6-stage layout.

    Args:
        targets:   {letter -> complex response on `freqs`} for the 4 corners.
        freqs, z_inv: from ``forge_fit.fit_grid``.
        sr:        sample rate the targets were measured at.
        bands:     per-stage ``StageBand`` list (len NUM_STAGES). When
                   present, the residual includes a soft penalty pushing
                   each per-corner dominant pole into its stage band.
                   When None, the joint fit degenerates to per-corner
                   peak-pick fits sharing only stage ORDER (still better
                   than independent because all corners use the same
                   stability/seeding pattern, but no role anchor).
        seeds:     {letter -> (NUM_STAGES,) pole frequencies in Hz} initial
                   per-corner seeds. When provided, the first restart uses
                   these via ``_seed_from_pole_freqs``. When None, each
                   corner falls back to ``_seed_peak_picked`` on its own
                   target.
        profile:   perceptual weighting profile for ``perceptual_weight``
                   (used when ``weight`` is None).
        weight:    explicit per-frequency weight (same across corners).
        n_restarts: random restarts. ``n_restarts // 2`` start from seeds
                   (with jitter on later iterations); the rest are random.
        seed:      RNG seed.

    Returns a ``JointFit`` with per-corner d/kernel/null-db.
    """
    letters = list(targets.keys())
    n_corners = len(letters)
    target_arr = np.stack([np.asarray(targets[L], dtype=np.complex128) for L in letters])
    n_freqs = target_arr.shape[1]

    if weight is None:
        weight = perceptual_weight(freqs, profile)
    weight = np.asarray(weight, dtype=np.float64)

    use_bands = bands is not None
    if use_bands and len(bands) != NUM_STAGES:
        raise ValueError(f"bands must have {NUM_STAGES} entries, got {len(bands)}")

    rng = np.random.default_rng(seed)
    n_vars_per_corner = NUM_STAGES * NUM_COEFFS

    def unpack(x: np.ndarray) -> np.ndarray:
        return x.reshape(n_corners, NUM_STAGES, NUM_COEFFS)

    def residual(xflat: np.ndarray) -> np.ndarray:
        d = unpack(xflat)
        parts: list[np.ndarray] = []
        for ci in range(n_corners):
            kernel = d_to_kernel(d[ci])
            h = cascade_response(kernel, z_inv)
            r = weight * (h - target_arr[ci])
            parts.append(r.real)
            parts.append(r.imag)
            parts.append(_STAB_PENALTY * _stability_penalty(kernel))
            if use_bands:
                parts.append(_BOUNDS_PENALTY * _bounds_penalty(kernel, sr, bands))
        return np.concatenate(parts)

    # seed table per restart
    def make_seed(ri: int) -> np.ndarray:
        out = np.empty((n_corners, NUM_STAGES, NUM_COEFFS), dtype=np.float64)
        for ci, L in enumerate(letters):
            if seeds is not None and L in seeds and ri < n_restarts // 2:
                jitter = 0.0 if ri == 0 else 0.08 * (ri / max(n_restarts // 2 - 1, 1))
                freqs_hz = np.asarray(seeds[L], dtype=np.float64)
                if jitter:
                    freqs_hz = freqs_hz * (2.0 ** rng.normal(0.0, jitter, freqs_hz.shape))
                out[ci] = _seed_from_pole_freqs(freqs_hz, sr)
            elif ri < (n_restarts // 2 if seeds is None else 3 * n_restarts // 4):
                jitter = 0.0 if ri == 0 else 0.15
                out[ci] = _seed_peak_picked(target_arr[ci], freqs, sr, rng, jitter=jitter)
            else:
                out[ci] = _seed_random(rng)
        return out.reshape(-1)

    lo = np.zeros(n_corners * n_vars_per_corner)
    hi = np.ones(n_corners * n_vars_per_corner)

    best: JointFit | None = None
    best_cost: float = np.inf

    import time
    for ri in range(n_restarts):
        x0 = np.clip(make_seed(ri), lo + 1e-6, hi - 1e-6)
        if verbose:
            print(f"    restart {ri + 1}/{n_restarts}: solving "
                  f"({n_corners * n_vars_per_corner} vars, max_nfev={max_nfev})...",
                  flush=True)
            t0 = time.perf_counter()
        try:
            sol = least_squares(
                residual, x0, bounds=(lo, hi), method="trf",
                x_scale="jac", ftol=1e-10, xtol=1e-10, gtol=1e-10,
                max_nfev=max_nfev,
            )
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"    restart {ri + 1} FAILED: {e}", flush=True)
            continue
        if verbose:
            dt = time.perf_counter() - t0
            print(f"    restart {ri + 1}: nfev={sol.nfev} cost={sol.cost:.4g} "
                  f"({dt:.1f}s)", flush=True)

        d = np.clip(unpack(sol.x), 0.0, 1.0)
        per_corner_null: dict[str, float] = {}
        per_corner_kernel: dict[str, np.ndarray] = {}
        per_corner_d: dict[str, np.ndarray] = {}
        per_corner_stable: dict[str, bool] = {}
        bounds_total = 0.0
        for ci, L in enumerate(letters):
            kernel = d_to_kernel(d[ci])
            h = cascade_response(kernel, z_inv)
            res = weight * (h - target_arr[ci])
            num = float(np.sqrt(np.mean(np.abs(res) ** 2)))
            den = float(np.sqrt(np.mean(np.abs(target_arr[ci]) ** 2))) + 1e-30
            null_db = 20.0 * np.log10(num / den + 1e-30)
            per_corner_null[L] = null_db
            per_corner_kernel[L] = kernel
            per_corner_d[L] = d[ci]
            per_corner_stable[L] = bool(np.all(_stability_penalty(kernel) < 1e-9))
            if use_bands:
                bounds_total += float(np.sum(_bounds_penalty(kernel, sr, bands)))

        cost = sum(per_corner_null.values()) + bounds_total
        if cost < best_cost:
            best_cost = cost
            best = JointFit(
                d=per_corner_d, kernel=per_corner_kernel,
                response_null_db=per_corner_null,
                bounds_residual=bounds_total,
                stable=per_corner_stable,
                restarts=n_restarts, best_restart=ri,
            )
        if best is not None and max(best.response_null_db.values()) < -120.0:
            break

    if best is None:
        raise RuntimeError("joint_fit_corners: every restart failed")
    if not all(best.stable.values()):
        best.notes.append("WARNING: at least one corner is not pole-stable")
    return best
