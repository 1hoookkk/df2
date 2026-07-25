"""Acoustic-physics models for named objects. Real textbook formulas, no fudging.

Used to compute the freq slots for physically-modelled intent presets. Each named
object declares its physical dimensions; the resonance frequencies fall out of the
standard acoustics formulas (Helmholtz, pipe modes, cavity modes, plate modes).
This file is the SOURCE OF TRUTH for the physics; the resulting freq lists are
baked into tables/family_intents.json by tools/build_physical_intents.py.

References:
- Helmholtz fundamental + Rayleigh end correction: standard, e.g.
  Kinsler & Frey, *Fundamentals of Acoustics* §10.5.
- Rectangular cavity (room) modes: Kinsler & Frey §11.4.
- Open/closed pipe harmonic series: undergrad-acoustics textbook.
- Free circular plate transverse modes: Leissa, *Vibration of Plates* — λ² values.
"""
from __future__ import annotations
import math

C_AIR = 343.0  # m/s, dry air @ 20 °C


# ── Helmholtz resonators (bottles, jugs, jars) ────────────────────────────────

def helmholtz(V_litres: float, neck_diameter_cm: float, neck_length_cm: float) -> float:
    """Helmholtz fundamental, Hz. Includes Rayleigh end correction (open-end flange)."""
    V = V_litres * 1e-3                                    # m^3
    r = (neck_diameter_cm * 0.5) * 1e-2                    # m
    A = math.pi * r * r                                    # m^2
    L = neck_length_cm * 1e-2                              # m
    L_eff = L + 1.7 * r                                    # Rayleigh correction
    return (C_AIR / (2.0 * math.pi)) * math.sqrt(A / (V * L_eff))


def closed_pipe_modes(length_cm: float, n: int = 4) -> list[float]:
    """Pipe closed at one end (the bottle body, above the Helmholtz): odd quarter-wave
    harmonics  f_k = (2k-1) c / (4L), k = 1..n."""
    L = length_cm * 1e-2
    return [(2 * k - 1) * C_AIR / (4 * L) for k in range(1, n + 1)]


def open_pipe_modes(length_cm: float, n: int = 4) -> list[float]:
    """Pipe open at both ends: full harmonic series  f_k = k c / (2L)."""
    L = length_cm * 1e-2
    return [k * C_AIR / (2 * L) for k in range(1, n + 1)]


# ── rectangular cavity room modes (bathtub-class enclosures) ──────────────────

def rectangular_room_modes(L_cm: float, W_cm: float, H_cm: float, n_terms: int = 3) -> list[float]:
    """Axial / tangential / oblique modes of a rectangular cavity (closed walls).
    f_lmn = (c/2) sqrt((l/L)^2 + (m/W)^2 + (n/H)^2)."""
    L, W, H = L_cm * 1e-2, W_cm * 1e-2, H_cm * 1e-2
    modes = []
    for l in range(n_terms + 1):
        for m in range(n_terms + 1):
            for n in range(n_terms + 1):
                if l + m + n == 0:
                    continue
                f = (C_AIR / 2.0) * math.sqrt((l / L) ** 2 + (m / W) ** 2 + (n / H) ** 2)
                modes.append(f)
    return sorted(modes)


# ── circular plate (Chladni / struck disc) ────────────────────────────────────
# Leissa free-edge plate λ² coefficients for the lowest non-trivial transverse modes.
_PLATE_LAMBDA_SQ = [5.253, 9.084, 12.23, 20.52, 21.59, 33.05]


def free_plate_modes(radius_cm: float, thickness_mm: float = 0.5,
                     E_pa: float = 2.0e11, rho_kgm3: float = 7800.0, nu: float = 0.3,
                     n: int = 4) -> list[float]:
    """Transverse vibration modes of a thin, free-edge circular plate (steel default).
    f_k = λ_k² sqrt(D/(ρ h)) / (2 π r²),  D = E h³ / (12 (1-ν²))."""
    h = thickness_mm * 1e-3
    r = radius_cm * 1e-2
    D = E_pa * h ** 3 / (12.0 * (1 - nu ** 2))
    coeff = math.sqrt(D / (rho_kgm3 * h)) / (2.0 * math.pi * r * r)
    return [lam * coeff for lam in _PLATE_LAMBDA_SQ[:n]]


# ── cylindrical-shell modes (tin can, lightly struck) ─────────────────────────
# Donnell-Mushtari short cylinder approximation: dominant flexural modes scale by
# (m^2 + (n π R / L)^2)/(m^2+n^2). For a small tin can the first few audible modes
# fall between the radial bending and axial bending bands.
def tin_can_modes(radius_cm: float, length_cm: float, thickness_mm: float = 0.25,
                  E_pa: float = 2.0e11, rho_kgm3: float = 7850.0,
                  modes: list[tuple[int, int]] | None = None) -> list[float]:
    """Approximate ring-shell modes (m circumferential, n axial). Defaults to the
    handful that empirically dominate the audible spectrum of a small steel can."""
    if modes is None:
        modes = [(2, 1), (3, 1), (4, 1), (2, 2)]
    h = thickness_mm * 1e-3
    R = radius_cm * 1e-2
    L = length_cm * 1e-2
    c_l = math.sqrt(E_pa / (rho_kgm3 * (1 - 0.3 ** 2)))   # longitudinal plate wave speed
    out = []
    for m, n in modes:
        # Donnell approximation for thin cylindrical shell
        Omega2 = ((1 - 0.3 ** 2) * (n * math.pi * R / L) ** 4 +
                  ((h / R) ** 2 / 12.0) * (m ** 2 + (n * math.pi * R / L) ** 2) ** 4)
        denom = (m ** 2 + (n * math.pi * R / L) ** 2) ** 2
        Omega2 /= max(denom, 1e-9)
        f = (c_l / (2.0 * math.pi * R)) * math.sqrt(max(Omega2, 0.0))
        out.append(f)
    return sorted(out)


# ── helpers ───────────────────────────────────────────────────────────────────

def geom_mean(*vals: float) -> float:
    if not vals:
        return 0.0
    p = 1.0
    for v in vals:
        p *= v
    return p ** (1.0 / len(vals))
