#!/usr/bin/env python3
"""DVTD measured VVTF -> phase-aware pole/zero rails (all 44, raw + plots).

Dresden Vocal Tract Dataset (Birkholz et al., figshare). Each model dir holds a
`*-vvtf-measured.txt` complex volume-velocity transfer function:
    freq_Hz  magnitude  phase_rad
Because PHASE is present, a complex rational fit recovers BOTH poles AND zeros --
including the antiformant zeros (and non-minimum-phase zeros, |z|>1) that a
magnitude-only LPC/peak-pick throws away. That is the data P2K never had.

Method (approach A): map measured f -> theta = 2*pi*f/sr_target onto the z unit
circle, fit B(z)/A(z) by regularized scipy Sanathanan-Koerner iteration
(phase-aware complex least squares with denominator reweighting). Roots ->
z-plane rails. Phase-aware throughout -- there is NO magnitude-only fallback
(that path cannot recover zeros and is invalid for this goal).

Constraints honoured:
  * measured trustworthy band = 100..10000 Hz (DVTD sets <100 Hz to dummy values).
  * sr_target = 39062.5 (TRENCH runtime). A 48k research rail is also emitted
    (json only) but is NOT called runtime-native.
  * bulk linear delay is estimated from unwrapped phase and removed before
    fitting so the rational model does not waste roots chasing measurement delay;
    removed_delay_seconds is stored.
  * unstable poles (r>=1) hard-flagged, non-min-phase zeros (|z|>1) flagged -- never clamped.
  * SK failures are marked FAIL / POOR_FIT and the plot is kept. No silent cleanup.

This is the RAW DATA pass: poles/zeros + provenance + fit-quality plots, then
STOP. No 6-lane projection, no authoring, no packing. Analysis material.

Two authoring-time annotations are carried, not applied:
  * type3_warp_candidate: a zero above the Type-3 split-code trigger (normalized
    freq 8788/48000, => ~7152 Hz at sr 39062.5) would warp if later compiled as a
    Type-3 cut lane (probe: df2/dev/tmp/type3_compression/probe.py).
  * i16-wrap risk is PAIRWISE (needs two morph endpoints) -> deferred to pairing;
    each feature's Hz is recorded so it is computable then.

Run: python tools/dvtd_rails.py
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import scipy.linalg as sla
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
DVTD = ROOT / "data" / "vocal" / "dvtd"
OUT = ROOT / "out" / "dvtd_rails"

SR_TARGET = 39062.5            # TRENCH runtime
SR_RESEARCH = 48000.0         # research rail only (NOT runtime-native)
FIT_LO, FIT_HI = 100.0, 10000.0
FORMANT_HI = 5000.0           # primary (authorable) band upper edge (gate/report band)
WEIGHT_TAPER_LO = 6000.0      # HF down-weight starts here (keeps F4/F5 at full weight)
DELAY_BAND = (150.0, 2500.0)  # clean sub-band for bulk-delay slope (avoids HF unwrap failures)
DELAY_MAX_S = 3.0e-3          # physical bound; reject larger estimates (noise-phase unwrap)
N_GRID = 600
N_POLES, N_ZEROS = 18, 14      # generous: raw rails; authoring picks the strong few later
SK_ITERS = 5
FLOOR_DB = -25.0              # error floor: match notch PRESENCE, not razor null depth
MAG_FLOOR_LIN = 10.0 ** (-20.0 / 20.0)   # relative-weight floor (-20 dB): 1/|H| weighting w/o infinite null gain
POOR_FORMANT_RMS_DB = 6.0     # OK/POOR gate on floored formant-band RMS; > this = HF-ripple/notch-depth residual, inspect plot
UNSTABLE_ARTIFACT_R = 1.30    # pole radius above this => fit artifact, not measured margin
BASELINE_MAX_R = 0.990        # baseline Q cap (bw floor ~100Hz@39k), calibrated to Talking Hedz Q0 corners;
                              # rigid printed tracts fit at the unit circle -> damp to a musical frame, leave Q headroom
T3_TRIGGER_FRAC = 8788.0 / 48000.0   # normalized freq of the Type-3 split-code trigger (probe-pinned)
SOURCE_CITE = ("Dresden Vocal Tract Dataset (DVTD), Birkholz et al., "
               "'Printable 3D vocal tract shapes from MRI data...', figshare s/5b81026892f7b39b429e")
OBJECTIVE_NOTE = ("phase-aware complex SK; data NOT smoothed; pure-delay (IR-onset) removal only; "
                  f"HF down-weight 1.0<= {WEIGHT_TAPER_LO:.0f}Hz -> 0.4 @ {FIT_HI:.0f}Hz; "
                  f"residual = floored log-mag (floor {FLOOR_DB:.0f}dB) on raw fit; "
                  f"poles Q-capped to baseline r<={BASELINE_MAX_R} (Hedz-Q0 frame), measured radius kept")
# SK fallback configs: (n_poles, n_zeros, lam_rel)
CONFIGS = [(18, 14, 1e-6), (18, 14, 1e-3), (16, 12, 1e-3), (14, 10, 1e-2)]


# --------------------------------------------------------------------------- IO
def find_models() -> list[dict]:
    out = []
    for subj_dir in sorted(DVTD.glob("subject-*")):
        for model_dir in sorted(p for p in subj_dir.iterdir() if p.is_dir()):
            f = next(model_dir.glob("*-vvtf-measured.txt"), None)
            if f is None:
                continue
            m = re.match(r"s(\d+)-(\d+)-(.+?)-(.+)$", model_dir.name)
            subj, idx, word, phon = m.groups() if m else ("?", "?", "?", model_dir.name)
            out.append({"id": model_dir.name, "subject": int(subj) if subj.isdigit() else subj,
                        "model_index": idx, "word": word, "phoneme": phon, "path": f})
    return out


def load_frf(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = np.genfromtxt(path, skip_header=1)
    f = data[:, 0].astype(np.float64)
    H = data[:, 1].astype(np.float64) * np.exp(1j * data[:, 2].astype(np.float64))
    return f, H


def band_weight(grid: np.ndarray) -> np.ndarray:
    """Full weight through F4/F5, cosine taper to 0.4 above WEIGHT_TAPER_LO."""
    w = np.ones_like(grid)
    hi = grid > WEIGHT_TAPER_LO
    x = (grid[hi] - WEIGHT_TAPER_LO) / (FIT_HI - WEIGHT_TAPER_LO)
    w[hi] = 0.4 + 0.6 * 0.5 * (1.0 + np.cos(np.pi * x))
    return w


def floored_db(H: np.ndarray) -> np.ndarray:
    return np.maximum(20.0 * np.log10(np.abs(H) + 1e-12), FLOOR_DB)


def bw_q(r: float, hz: float, sr: float) -> tuple[float, float]:
    bw = -math.log(min(max(r, 1e-9), 0.999999)) * sr / math.pi
    return bw, (hz / bw if bw > 0 else 0.0)


def baseline_cap(poles, b_raw, a_full, omega, sr):
    """Damp RESONANT pole radii to BASELINE_MAX_R (musical frame); leave structural
    real / near-DC poles (hz<=60) untouched. Robust median-dB gain renorm (a single
    point near a DC pole mis-scales). Mutates each pole with r_measured / r /
    bandwidth_hz / q / capped / unstable. Returns (Hbase, b_base, a_base).

    Shared by every well's extractor (dvtd, hrtf, ...) -- single source of the cap."""
    b_raw = np.asarray(b_raw, dtype=float)
    pz = []
    for p in poles:
        cap = (p["r"] > BASELINE_MAX_R) and (p["hz"] > 60.0)
        r_new = BASELINE_MAX_R if cap else p["r"]
        pz.append(r_new * np.exp(1j * p["angle_rad"]))
        p["r_measured"] = p["r"]
        p["r"] = r_new
        bw, q = bw_q(r_new, p["hz"], sr)
        p["bandwidth_hz"], p["q"], p["capped"] = round(bw, 1), round(q, 2), bool(cap)
        p["unstable"] = p["r_measured"] >= 1.0
    a_base = np.real(np.poly(np.array(pz))) if pz else np.array([1.0])
    raw_db = 20 * np.log10(np.abs(eval_tf(b_raw, a_full, omega)) + 1e-12)
    b0_db = 20 * np.log10(np.abs(eval_tf(b_raw, a_base, omega)) + 1e-12)
    b_base = b_raw * (10.0 ** ((np.median(raw_db) - np.median(b0_db)) / 20.0))
    return eval_tf(b_base, a_base, omega), b_base, a_base


def prep_for_sr(f: np.ndarray, H: np.ndarray, sr: float):
    """Restrict to band, remove only PURE propagation delay (IR onset), resample onto log grid.

    The bulk delay is estimated from the impulse-response onset (irfft of the full
    one-sided spectrum), NOT from the unwrapped-phase slope -- the phase slope is
    dominated by the formants' own group delay, and removing it over-flattens the
    phase and reflects every zero outside the unit circle. For DVTD the IR onset is
    ~0 (the measured VVTF is already near-minimum-phase), so this is ~a no-op.
    """
    n_full = 2 * (len(H) - 1)
    ir = np.fft.irfft(H, n=n_full)
    fs_native = (f[1] - f[0]) * n_full
    onset = int(np.argmax(np.abs(ir)))                # samples @ fs_native
    delay_s = onset / fs_native if abs(onset / fs_native) <= DELAY_MAX_S else 0.0
    band = (f >= FIT_LO) & (f <= FIT_HI)
    fb, Hb = f[band], H[band]
    omega_n = 2 * math.pi * fb / sr
    Hcomp = Hb * np.exp(1j * omega_n * (delay_s * sr))  # remove pure propagation delay only
    grid = np.logspace(math.log10(FIT_LO), math.log10(FIT_HI), N_GRID)
    re = np.interp(grid, fb, Hcomp.real)
    im = np.interp(grid, fb, Hcomp.imag)
    return grid, re + 1j * im, delay_s


# ---------------------------------------------------------------- SK rational fit
def sk_once(omega: np.ndarray, H: np.ndarray, N: int, M: int, iters: int, lam_rel: float,
            wfit: np.ndarray | None = None):
    zinv = np.exp(-1j * omega)
    Zb = np.vander(zinv, M + 1, increasing=True)
    Za = np.vander(zinv, N + 1, increasing=True)
    wf = np.ones_like(omega) if wfit is None else wfit
    a_prev = np.zeros(N)
    b = np.zeros(M + 1); a = np.zeros(N)
    for t in range(iters):
        wsk = np.ones_like(omega) if t == 0 else 1.0 / np.maximum(np.abs(Za[:, 0] + Za[:, 1:] @ a_prev), 1e-9)
        w = wsk * wf
        Phi = np.hstack([Zb, -H[:, None] * Za[:, 1:]]) * w[:, None]
        y = H * w
        A_real = np.vstack([Phi.real, Phi.imag])
        y_real = np.concatenate([y.real, y.imag])
        ncols = A_real.shape[1]
        lam = lam_rel * (np.sum(A_real ** 2) / ncols)
        if lam > 0:
            A_real = np.vstack([A_real, math.sqrt(lam) * np.eye(ncols)])
            y_real = np.concatenate([y_real, np.zeros(ncols)])
        x = sla.lstsq(A_real, y_real, lapack_driver="gelsd")[0]
        b, a = x[:M + 1], x[M + 1:]
        a_prev = a
    return b, np.concatenate([[1.0], a])


def eval_tf(b, a_full, omega):
    zinv = np.exp(-1j * omega)
    return np.polyval(b[::-1], zinv) / np.polyval(a_full[::-1], zinv)


def roots_features(coeffs_high_first, sr):
    if len(coeffs_high_first) < 2 or np.allclose(coeffs_high_first, 0):
        return []
    feats = []
    for z in np.roots(coeffs_high_first):
        ang = float(np.angle(z))
        feats.append({"r": float(abs(z)), "angle_rad": ang, "hz": abs(ang) / (2 * math.pi) * sr})
    feats.sort(key=lambda d: d["hz"])
    return feats


# --------------------------------------------------------------------- per model
def fit_model(mdl, frf, sr):
    f, H = frf
    grid, Hg, removed_delay_s = prep_for_sr(f, H, sr)
    omega = 2 * math.pi * grid / sr
    t3_hz = T3_TRIGGER_FRAC * sr
    wfit = band_weight(grid)                   # HF taper only; relative 1/|H| weighting chased nulls -> rejected
    fbmask = grid <= FORMANT_HI               # formant (authorable) band

    best = None
    for (N, M, lam) in CONFIGS:
        try:
            b, a_full = sk_once(omega, Hg, N, M, SK_ITERS, lam, wfit=wfit)
            Hfit = eval_tf(b, a_full, omega)
            if not np.all(np.isfinite(Hfit)):
                continue
            mag_err = floored_db(Hfit) - floored_db(Hg)   # floored: match notch presence, not razor depth
            ph_err = np.angle(Hfit / (Hg + 1e-18))
            magrms = float(np.sqrt(np.mean(mag_err ** 2)))
            magrms_fb = float(np.sqrt(np.mean(mag_err[fbmask] ** 2)))
            poles = roots_features(a_full, sr)
            maxr = max((p["r"] for p in poles), default=0.0)
            score = magrms_fb + (50.0 if maxr > UNSTABLE_ARTIFACT_R else 0.0)
            cand = dict(b=b, a_full=a_full, Hfit=Hfit, mag_err=mag_err, ph_err=ph_err,
                        magrms=magrms, magrms_fb=magrms_fb, maxr=maxr, N=N, M=M, lam=lam,
                        phrms=float(np.sqrt(np.mean((ph_err[fbmask]) ** 2))))
            if best is None or score < best["score"]:
                cand["score"] = score; best = cand
            if magrms_fb <= POOR_FORMANT_RMS_DB and maxr <= UNSTABLE_ARTIFACT_R:
                break
        except Exception:  # keep going; failure recorded below
            continue

    if best is None:
        status = "FAIL"
        rec = {"fit_status": status, "poles": [], "zeros": [], "coeffs": {"b": [], "a": []},
               "residual": {"mag_rms_formant_db": None, "mag_rms_full_db": None, "phase_rms_formant_rad": None}}
        rec["_plotdata"] = {"grid": grid, "Hg": Hg, "Hfit": np.full_like(Hg, np.nan),
                            "Hbase": np.full_like(Hg, np.nan)}
        flags = {"unstable_poles": 0, "poles_capped": 0, "nonmin_phase_zeros": 0, "type3_warp_zeros": 0}
    else:
        status = "OK" if (best["magrms_fb"] <= POOR_FORMANT_RMS_DB and best["maxr"] <= UNSTABLE_ARTIFACT_R) else "POOR_FIT"
        poles = roots_features(best["a_full"], sr)
        zeros = roots_features(best["b"][::-1], sr)
        # baseline Q cap (shared): damp RESONANT poles to the musical frame; structural poles kept.
        Hbase, b_base, a_base = baseline_cap(poles, best["b"], best["a_full"], omega, sr)
        wlo = np.array([2 * math.pi * FIT_LO / sr])
        for z in zeros:
            z["nonmin_phase"] = z["r"] > 1.0
            z["type3_warp_candidate"] = z["hz"] > t3_hz
        flags = {"unstable_poles": int(sum(p["unstable"] for p in poles)),
                 "poles_capped": int(sum(p["capped"] for p in poles)),
                 "nonmin_phase_zeros": int(sum(z["nonmin_phase"] for z in zeros)),
                 "type3_warp_zeros": int(sum(z["type3_warp_candidate"] for z in zeros))}
        rec = {"fit_status": status, "poles": poles, "zeros": zeros,
               "residual": {"mag_rms_formant_db": best["magrms_fb"], "mag_rms_full_db": best["magrms"],
                            "mag_max_db": float(np.max(np.abs(best["mag_err"]))),
                            "phase_rms_formant_rad": best["phrms"]},
               "baseline_max_r": BASELINE_MAX_R,
               "order_used": {"poles": best["N"], "zeros": best["M"], "lam_rel": best["lam"]},
               "coeffs_baseline": {"b": [float(x) for x in b_base], "a": [float(x) for x in a_base]},
               "coeffs_measured": {"b": [float(x) for x in best["b"]], "a": [float(x) for x in best["a_full"]]},
               "dc_gain_db": float(20 * np.log10(abs(eval_tf(best["b"], best["a_full"], wlo)[0]) + 1e-12))}
        rec["_plotdata"] = {"grid": grid, "Hg": Hg, "Hfit": best["Hfit"], "Hbase": Hbase}

    rec.update({
        "id": mdl["id"], "subject": mdl["subject"], "model_index": mdl["model_index"],
        "word": mdl["word"], "phoneme": mdl["phoneme"], "source": SOURCE_CITE,
        "source_path": str(mdl["path"]), "sr_target": sr, "fit_band_hz": [FIT_LO, FIT_HI],
        "formant_band_hz": [FIT_LO, FORMANT_HI], "objective": OBJECTIVE_NOTE,
        "order_requested": {"poles": N_POLES, "zeros": N_ZEROS},
        "removed_delay_seconds": removed_delay_s, "type3_trigger_hz": t3_hz, "flags": flags,
    })
    return rec


# --------------------------------------------------------------------- plotting
def plot_model(rec, out_dir: Path):
    pd = rec.pop("_plotdata")
    grid, Hg, Hfit, Hbase = pd["grid"], pd["Hg"], pd["Hfit"], pd["Hbase"]
    status = rec["fit_status"]
    color_title = "#ee493c" if status != "OK" else "#cdd"
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.4), facecolor="#0b0f0e")
    (axm, axp), (axr, axz) = axes
    res = rec["residual"]
    rfb, rfull = res["mag_rms_formant_db"], res["mag_rms_full_db"]
    fb_s = "n/a" if rfb is None else f"{rfb:.2f}"
    full_s = "n/a" if rfull is None else f"{rfull:.2f}"
    # magnitude (shade authorable formant band)
    axm.semilogx(grid, 20 * np.log10(np.abs(Hg) + 1e-12), color="#5bef6f", lw=1.6, label="measured (rigid tract)")
    axm.semilogx(grid, 20 * np.log10(np.abs(Hfit) + 1e-12), color="#7a5a2a", lw=1.0, ls="--", label="raw fit (max-Q)")
    axm.semilogx(grid, 20 * np.log10(np.abs(Hbase) + 1e-12), color="#ffb13e", lw=1.6,
                 label=f"baseline rail (r<={BASELINE_MAX_R})")
    axm.axvspan(FIT_LO, FORMANT_HI, color="#142019", zorder=0)
    capped = rec["flags"].get("poles_capped", 0)
    axm.set_title(f"{rec['id']}  [{status}]  fit RMS {fb_s} dB (full {full_s}) · {capped} poles Q-capped",
                  color=color_title, fontsize=9)
    axm.set_ylabel("dB", color="#889"); axm.legend(fontsize=7, facecolor="#11161400", labelcolor="#cdd")
    # phase (delay-removed)
    axp.semilogx(grid, np.angle(Hg), color="#5bef6f", lw=1.3, label="measured (delay-removed)")
    axp.semilogx(grid, np.angle(Hfit), color="#ffb13e", lw=1.0, label="fit")
    axp.set_title(f"phase  |  removed delay {rec['removed_delay_seconds']*1e3:.3f} ms", color="#cdd", fontsize=9)
    axp.set_ylabel("rad", color="#889"); axp.legend(fontsize=7, facecolor="#11161400", labelcolor="#cdd")
    # residual
    if np.all(np.isfinite(Hfit)):
        axr.semilogx(grid, floored_db(Hfit) - floored_db(Hg), color="#2fc8cc", lw=1.1,
                     label=f"floored mag err dB (floor {FLOOR_DB:.0f})")
        axr.semilogx(grid, np.angle(Hfit / (Hg + 1e-18)), color="#f1d76a", lw=0.9, label="phase err rad")
    axr.axhline(0, color="#26302b", lw=0.8)
    axr.set_title("residual (fit - measured, floored)", color="#cdd", fontsize=9)
    axr.set_xlabel("Hz", color="#889"); axr.legend(fontsize=7, facecolor="#11161400", labelcolor="#cdd")
    # z-plane
    th = np.linspace(0, 2 * math.pi, 240)
    axz.plot(np.cos(th), np.sin(th), color="#26302b", lw=1.0)
    for p in rec["poles"]:
        z = p["r"] * np.exp(1j * p["angle_rad"])
        axz.plot(z.real, z.imag, "x", color="#ee493c" if p.get("unstable") else "#9b8cff", ms=7)
    for zz in rec["zeros"]:
        z = zz["r"] * np.exp(1j * zz["angle_rad"])
        axz.plot(z.real, z.imag, "o", mfc="none",
                 color="#f1d76a" if zz.get("nonmin_phase") else "#2fc8cc", ms=6)
    axz.set_title(f"z-plane | nmp {rec['flags']['nonmin_phase_zeros']} | unstable {rec['flags']['unstable_poles']}"
                  f" | t3warp {rec['flags']['type3_warp_zeros']}", color="#cdd", fontsize=9)
    axz.set_aspect("equal"); axz.set_xlim(-1.4, 1.4); axz.set_ylim(-1.4, 1.4); axz.set_xlabel("Re", color="#889")
    for ax in (axm, axp, axr, axz):
        ax.set_facecolor("#0b0f0e"); ax.tick_params(colors="#889", labelsize=7); ax.grid(True, alpha=0.12)
        for s in ax.spines.values():
            s.set_color("#26302b")
    fig.tight_layout()
    fig.savefig(out_dir / f"{rec['id']}.png", dpi=110, facecolor="#0b0f0e")
    plt.close(fig)


def contact_sheet(recs, plotdatas, out_path: Path):
    n = len(recs); cols = 6; rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(2.2 * cols, 1.7 * rows), facecolor="#080a0a")
    for ax, rec, pd in zip(axes.ravel(), recs, plotdatas):
        grid, Hg, Hbase = pd["grid"], pd["Hg"], pd["Hbase"]
        ax.semilogx(grid, 20 * np.log10(np.abs(Hg) + 1e-12), color="#5bef6f", lw=0.9)
        if np.all(np.isfinite(Hbase)):
            ax.semilogx(grid, 20 * np.log10(np.abs(Hbase) + 1e-12), color="#ffb13e", lw=0.8)
        bad = rec["fit_status"] != "OK"
        ax.set_title(f"{rec['phoneme']} s{rec['subject']}" + (f" [{rec['fit_status']}]" if bad else ""),
                     color="#ee493c" if bad else "#cfe9df", fontsize=6)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("#0b0f0e")
        for s in ax.spines.values():
            s.set_color("#283632")
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    fig.tight_layout(pad=0.3)
    fig.savefig(out_path, dpi=130, facecolor="#080a0a")
    plt.close(fig)


# --------------------------------------------------------- authoring candidates
def authoring_candidates(recs: list[dict]) -> dict:
    """ADVISORY ONLY. Suggests feature-rich rails and high-contrast pairs for the
    SEPARATE authoring step. Bakes no body, assigns no corner / lane / Morph / Q."""
    cands = []
    for r in recs:
        if r["fit_status"] == "FAIL":
            continue
        forms = sorted(p["hz"] for p in r["poles"] if p["r"] > 0.90 and 200 <= p["hz"] <= 4500)
        notches = sorted(z["hz"] for z in r["zeros"] if 0.80 <= z["r"] <= 1.08 and 200 <= z["hz"] <= 8000)
        cands.append({
            "id": r["id"], "phoneme": r["phoneme"], "subject": r["subject"],
            "fit_status": r["fit_status"], "fb_rms_db": r["residual"]["mag_rms_formant_db"],
            "formants_hz": [round(x) for x in forms[:5]],
            "antiformants_hz": [round(x) for x in notches[:6]],
            "nonmin_phase_zeros": r["flags"]["nonmin_phase_zeros"],
            "richness": round(len(forms) + 0.5 * len(notches), 1),
        })
    ranked = sorted(cands, key=lambda c: (c["fit_status"] != "OK", -c["richness"]))
    ok = [c for c in cands if c["fit_status"] == "OK" and len(c["formants_hz"]) >= 2]
    pairs = []
    for i in range(len(ok)):
        for j in range(i + 1, len(ok)):
            a, b = ok[i], ok[j]
            n = min(len(a["formants_hz"]), len(b["formants_hz"]), 3)
            if n < 2:
                continue
            dist = math.sqrt(sum(math.log2(a["formants_hz"][k] / b["formants_hz"][k]) ** 2 for k in range(n)))
            pairs.append((dist, a["id"], b["id"]))
    pairs.sort(reverse=True)
    return {
        "note": ("ADVISORY ONLY -- suggestions for the SEPARATE authoring step. "
                 "No body emitted, no corner (M0/M100/Q0/Q100) assignment, no 6-lane projection, "
                 "no Morph/Q axis decision. Rank/pairs are hints; the operator chooses."),
        "rails_by_richness": ranked,
        "suggested_pairs_by_formant_contrast": [
            {"a": p[1], "b": p[2], "formant_log2_dist": round(p[0], 2)} for p in pairs[:12]
        ],
    }


# ------------------------------------------------------------------------- run
def run_pass(models, frfs, sr, out_dir: Path, make_plots: bool, label: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    plots = out_dir / "plots"
    if make_plots:
        plots.mkdir(exist_ok=True)
    recs, plotdatas = [], []
    print(f"\n=== pass {label}  sr_target={sr}  t3warp>{T3_TRIGGER_FRAC*sr:.0f}Hz ===")
    for mdl in models:
        rec = fit_model(mdl, frfs[mdl["id"]], sr)
        plotdatas.append(rec["_plotdata"])
        if make_plots:
            plot_model(rec, plots)      # pops _plotdata
        else:
            rec.pop("_plotdata", None)
        recs.append(rec)
        r = rec["residual"]
        mr = " n/a" if r["mag_rms_formant_db"] is None else f"{r['mag_rms_formant_db']:5.2f}"
        fl = " n/a" if r["mag_rms_full_db"] is None else f"{r['mag_rms_full_db']:5.2f}"
        print(f"  {rec['id']:<26} [{rec['fit_status']:<8}] fbRMS {mr} (full {fl}) dB  "
              f"nmp {rec['flags']['nonmin_phase_zeros']}  unst {rec['flags']['unstable_poles']}  "
              f"t3 {rec['flags']['type3_warp_zeros']}  delay {rec['removed_delay_seconds']*1e3:+.2f}ms")
    if make_plots:
        contact_sheet(recs, plotdatas, out_dir / "contact_sheet.png")
        (out_dir / "authoring_candidates.json").write_text(
            json.dumps(authoring_candidates(recs), indent=2), encoding="utf-8")
    (out_dir / f"dvtd_rails_{label}.json").write_text(json.dumps(recs, indent=2), encoding="utf-8")

    if make_plots:
        _fb = [r["residual"]["mag_rms_formant_db"] for r in recs
               if r["residual"]["mag_rms_formant_db"] is not None]
        fbvals = np.asarray(_fb, dtype=float) if _fb else np.array([np.nan])
        lines = [
            f"# DVTD pole/zero rails ({label}) — phase-aware SK complex fit",
            "",
            f"- models: {len(recs)} (2 subjects x 22), kept separate; sr_target={sr}",
            f"- fit band {FIT_LO:.0f}-{FIT_HI:.0f} Hz; authorable formant band {FIT_LO:.0f}-{FORMANT_HI:.0f} Hz",
            f"- objective: {OBJECTIVE_NOTE}",
            f"- order requested {N_POLES}p/{N_ZEROS}z, SK {SK_ITERS} iters, scipy gelsd + Tikhonov",
            f"- fit_status (gated on formant band): OK {sum(r['fit_status']=='OK' for r in recs)}, "
            f"POOR_FIT {sum(r['fit_status']=='POOR_FIT' for r in recs)}, FAIL {sum(r['fit_status']=='FAIL' for r in recs)}",
            f"- formant-band mag RMS: median {np.nanmedian(fbvals):.2f} dB, max {np.nanmax(fbvals):.2f}",
            f"- non-min-phase zeros total: {sum(r['flags']['nonmin_phase_zeros'] for r in recs)} (measured antiformant info)",
            f"- unstable poles total (flagged, kept): {sum(r['flags']['unstable_poles'] for r in recs)}",
            f"- Type-3 warp-candidate zeros (>{T3_TRIGGER_FRAC*sr:.0f} Hz): "
            f"{sum(r['flags']['type3_warp_zeros'] for r in recs)}",
            "",
            "| id | status | fbRMS dB | fullRMS | nmp | unst | t3 | delay ms |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for r in recs:
            rr = r["residual"]
            mm = "n/a" if rr["mag_rms_formant_db"] is None else f"{rr['mag_rms_formant_db']:.2f}"
            ff = "n/a" if rr["mag_rms_full_db"] is None else f"{rr['mag_rms_full_db']:.2f}"
            lines.append(f"| {r['id']} | {r['fit_status']} | {mm} | {ff} | {r['flags']['nonmin_phase_zeros']} | "
                         f"{r['flags']['unstable_poles']} | {r['flags']['type3_warp_zeros']} | "
                         f"{r['removed_delay_seconds']*1e3:+.2f} |")
        (out_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return recs


def main() -> int:
    models = find_models()
    print(f"found {len(models)} measured VVTF models")
    frfs = {m["id"]: load_frf(m["path"]) for m in models}
    run_pass(models, frfs, SR_TARGET, OUT, make_plots=True, label="trench_runtime")
    run_pass(models, frfs, SR_RESEARCH, OUT / "research_48k", make_plots=False, label="research_48k")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
