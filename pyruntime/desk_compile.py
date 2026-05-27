"""desk_compile.py — backend for the Anatomy-First filter design desk.

NO invented DSP. The compile path is:

    drawn magnitude target (per corner)
      -> cepstral MIN-PHASE reconstruction (the standard bridge for a
         magnitude-only target; same approach arma.rs uses internally)
      -> the REAL repo solver  pyruntime.forge_fit.fit_corner()
      -> kernel coefficients   (the cartridge's native 6x5 domain)
      -> compiled-v1 cartridge (stages + packedWords) the plugin loads.

Validation uses the repo's real stability rule (pole radius < 1.0, finite
coefficients) over the packed Morph x Q surface. Write-live writes the exact
file the plugin watches and hot-reloads: ~/Documents/TRENCH/authoring_slot.json.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np

from pyruntime import forge_fit, packed_interp as pi

SR = 39062.5                       # authoring rate (discovered: trench-core)
N_FIT = 512                        # fit-grid resolution (snappy compile; plenty for a 6-biquad fit)
STAGES = 6
CORNERS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
LIVE_PATH = Path(os.path.expanduser("~")) / "Documents" / "TRENCH" / "authoring_slot.json"


# ── min-phase reconstruction from a drawn magnitude (the only new DSP; standard) ──
def min_phase_target(ctrl_hz, ctrl_db, fit_freqs, sr=SR, n_fft=8192):
    """Drawn (freq, dB) control points -> complex MIN-PHASE target on `fit_freqs`.

    A drawn curve is magnitude-only; the solver wants a complex target. Minimum
    phase is the canonical, causal reconstruction: phase = Hilbert transform of
    log-magnitude, computed here via the real cepstrum (window 0/1..n/2). This is
    the same magnitude->complex bridge the ARMA fitter builds internally."""
    ctrl_hz = np.asarray(ctrl_hz, float)
    ctrl_db = np.asarray(ctrl_db, float)
    half = n_fft // 2
    lin = np.arange(half + 1) * sr / n_fft
    lin[0] = lin[1] * 0.5
    db = np.interp(np.log2(lin), np.log2(ctrl_hz), ctrl_db,
                   left=ctrl_db[0], right=ctrl_db[-1])
    logmag = (db / 20.0) * math.log(10.0)                 # natural log |H|
    full = np.concatenate([logmag, logmag[-2:0:-1]])      # even-symmetric, len n_fft
    cep = np.fft.ifft(full).real
    win = np.zeros(n_fft)
    win[0] = 1.0
    win[1:half] = 2.0
    win[half] = 1.0
    hmin = np.exp(np.fft.fft(cep * win))[: half + 1]      # complex min-phase
    re = np.interp(np.log2(fit_freqs), np.log2(lin), hmin.real)
    im = np.interp(np.log2(fit_freqs), np.log2(lin), hmin.imag)
    return re + 1j * im


# ── kernel <-> stability helpers (repo math) ──
def pole_radius(c):                # c = kernel [c0..c4]; a2 = 1 - c3 = r^2
    return math.sqrt(max(0.0, 1.0 - c[3]))


def kernel_db_curve(kernel, z_inv):
    return 20.0 * np.log10(np.abs(forge_fit.cascade_response(np.asarray(kernel), z_inv)) + 1e-12)


# ── compile a 4-corner design through the REAL forge ──
def compile_design(design, profile="vocal", n_restarts=2, max_nfev=300, tol=1e-7):
    """design: {corners: {LABEL: {points:[{hz,db},...]}}, name, boost}.
    Returns {cartridge, corners:{LABEL:{target_db,solved_db,error_db,null_db,...}}}.

    The fit budget (n_restarts/max_nfev/tol) is the "forge_fit (light)" path:
    the SAME real solver, fewer iterations — a drawn curve converges in ~2
    restarts because the peak-picked seed already lands the resonances."""
    freqs, z_inv = forge_fit.fit_grid(SR, N_FIT)
    name = design.get("name", "desk_body")
    boost = float(design.get("boost", 1.0))
    keyframes, per = [], {}
    for label in CORNERS:
        pts = design["corners"][label]["points"]
        hz = [max(20.0, min(SR * 0.49, float(p["hz"]))) for p in pts]
        db = [float(p["db"]) for p in pts]
        order = np.argsort(hz)
        hz = np.asarray(hz)[order]; db = np.asarray(db)[order]
        target = min_phase_target(hz, db, freqs)
        fit = forge_fit.fit_corner(target, freqs, z_inv, SR, profile=profile,
                                   n_restarts=n_restarts, max_nfev=max_nfev, tol=tol)
        kernel = np.asarray(fit.kernel, float).reshape(STAGES, 5)
        words = [list(pi.coeffs_to_words(*row)) for row in kernel.tolist()]
        keyframes.append({
            "label": label, "boost": boost,
            "stages": [{"c0": r[0], "c1": r[1], "c2": r[2], "c3": r[3], "c4": r[4]} for r in kernel.tolist()],
            "packedWords": words,
        })
        target_db = 20.0 * np.log10(np.abs(target) + 1e-12)
        solved_db = kernel_db_curve(kernel, z_inv)
        per[label] = {
            "freqs": freqs.tolist(),
            "target_db": target_db.tolist(),
            "solved_db": solved_db.tolist(),
            "error_db": (solved_db - target_db).tolist(),
            "null_db": float(fit.response_null_db),
            "stable": bool(fit.stable),
            "max_radius": max(pole_radius(r) for r in kernel.tolist()),
        }
    cartridge = {
        "format": "compiled-v1", "name": name, "provenance": "desk: draw->minphase->forge_fit",
        "authoringModel": "response-surface-v1", "sampleRate": SR, "stages": STAGES,
        "cornerOrder": list(CORNERS), "keyframes": keyframes,
    }
    return {"cartridge": cartridge, "corners": per}


# ── validate against the repo's real stability rule + structure ──
def validate_cartridge(cart):
    issues, warnings = [], []
    kfs = {k["label"]: k for k in cart.get("keyframes", [])}
    for label in CORNERS:
        if label not in kfs:
            issues.append(f"missing corner {label}")
    if issues:
        return {"ok": False, "issues": issues, "warnings": warnings, "max_radius": None}

    # words per corner (authority); rebuild from stages if packedWords absent
    words = {}
    for label in CORNERS:
        kf = kfs[label]
        if kf.get("packedWords"):
            rows = kf["packedWords"]
        else:
            rows = [pi.coeffs_to_words(s["c0"], s["c1"], s["c2"], s["c3"], s["c4"]) for s in kf["stages"][:STAGES]]
        if len(rows) != STAGES or any(len(r) != 5 for r in rows):
            issues.append(f"{label}: packedWords must be 6x5")
        words[LABEL_TO_KEY[label]] = [tuple(int(x) & 0xFFFF for x in r) for r in rows]
    if issues:
        return {"ok": False, "issues": issues, "warnings": warnings, "max_radius": None}

    # stability over the packed Morph x Q surface, via the SINGLE owned call:
    # pi.packed_probe -> trench-core interpolate -> biquad -> pole_radius, the
    # exact shipped path. No parallel Python kernel_to_biquad/pole_radius here.
    max_r, nonfinite, unstable = 0.0, 0, 0
    for m in np.linspace(0, 1, 17):
        for q in np.linspace(0, 1, 17):
            pr = pi.packed_probe(words, float(m), float(q))
            max_r = max(max_r, pr["max_pole_radius"])
            nonfinite += bin(pr["nonfinite_mask"]).count("1")
            unstable += bin(pr["unstable_mask"]).count("1")
    if nonfinite:
        issues.append(f"{nonfinite} nonfinite coeff rows across the morph surface")
    if unstable:
        issues.append(f"{unstable} unstable rows (pole radius >= 1.0) across the morph surface")
    if max_r > 0.9995:
        warnings.append(f"max pole radius {max_r:.4f} — very hot, near the edge")
    return {"ok": not issues, "issues": issues, "warnings": warnings, "max_radius": round(max_r, 5)}


# ── live slot I/O (the exact file the plugin watches) ──
def write_live(cart):
    LIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIVE_PATH.write_text(json.dumps(cart, indent=2), encoding="utf-8")
    return str(LIVE_PATH)


def load_live():
    if not LIVE_PATH.exists():
        return None
    return json.loads(LIVE_PATH.read_text(encoding="utf-8"))


def live_as_design(npoints=14):
    """Read the live cartridge -> editable target points per corner (its response)."""
    cart = load_live()
    if cart is None:
        return None
    freqs, z_inv = forge_fit.fit_grid(SR, N_FIT)
    ctrl = np.logspace(np.log10(20.0), np.log10(20000.0), npoints)
    kfs = {k["label"]: k for k in cart.get("keyframes", [])}
    corners = {}
    for label in CORNERS:
        kf = kfs.get(label)
        if not kf:
            continue
        if kf.get("packedWords"):
            kernel = [list(pi.words_to_coeffs(tuple(r))) for r in kf["packedWords"]]
        else:
            kernel = [[s["c0"], s["c1"], s["c2"], s["c3"], s["c4"]] for s in kf["stages"][:STAGES]]
        db = kernel_db_curve(kernel, z_inv)
        cdb = np.interp(np.log2(ctrl), np.log2(freqs), db)
        corners[label] = {"points": [{"hz": float(f), "db": float(d)} for f, d in zip(ctrl, cdb)]}
    return {"name": cart.get("name", "live"), "corners": corners}


def health():
    return {
        "ok": True,
        "forge_fit": True,
        "core_backend": pi.core_backend(),
        "live_path": str(LIVE_PATH),
        "live_exists": LIVE_PATH.exists(),
        "sample_rate_hz": SR, "stages": STAGES,
    }
