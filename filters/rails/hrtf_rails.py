#!/usr/bin/env python3
"""HRTF (SONICOM) measured response -> phase-aware pole/zero rails.

Second source well (after DVTD vocal). HRTFs carry strong measured PINNA NOTCHES
= real non-minimum-phase zeros, plus the ear-canal/concha peaks -> material for the
bright / multi-resonant (DJ-Alkaline-class) ship filter. The morph/Q sharpness is
added later by Q-pressure; the well supplies the frequency STRUCTURE.

Reuses the proven DVTD fit math verbatim (imported from dvtd_rails -- the SK kernel
is NOT duplicated). HRTF-specific front-end:
  HRIR -> zero-padded rfft -> complex FRF
  remove pure arrival delay via IR onset (ITD/propagation) -- here it is REAL and
  non-zero (unlike DVTD ~0); the IR-onset method removes only pure delay, not the
  resonance group delay, so zeros stay physically placed.
  fit a representative spatial grid of directions (one ear) -> rails + flags + plots.

Extraction only: raw poles/zeros + baseline-Q cap + plots. No body, no corners.

Run: python tools/hrtf_rails.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import h5py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dvtd_rails as D   # SK kernel + helpers (single source of the fit math)

ROOT = Path(__file__).resolve().parent.parent
SOFA = ROOT / "data" / "hrtf" / "sonicom_P0001_FreeFieldComp_48kHz.sofa"
OUT = ROOT / "out" / "hrtf_rails"
PLOTS = OUT / "plots"

SR_TARGET = D.SR_TARGET            # 39062.5 (TRENCH runtime)
FIT_LO, FIT_HI = 200.0, 16000.0   # HRTF meaningful band (ear-canal peak .. pinna notches)
TAPER_LO = 14000.0
N_GRID = 600
PAD = 2048                        # zero-pad HRIR for fine FRF resolution
EAR = 0                           # left ear
# representative spatial grid (nearest measured direction is chosen)
AZIMUTHS = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]
ELEVATIONS = [-30, 0, 30, 60]
SOURCE = "SONICOM P0001 FreeFieldComp 48kHz (HRTF well)"


def band_weight(grid):
    w = np.ones_like(grid)
    hi = grid > TAPER_LO
    x = (grid[hi] - TAPER_LO) / (FIT_HI - TAPER_LO)
    w[hi] = 0.4 + 0.6 * 0.5 * (1.0 + np.cos(np.pi * x))
    return w


def load_sofa(path):
    with h5py.File(path, "r") as f:
        return (np.array(f["Data.IR"], float), float(np.array(f["Data.SamplingRate"]).ravel()[0]),
                np.array(f["SourcePosition"], float))


def nearest(pos, az, el):
    d = ((pos[:, 0] - az + 180) % 360 - 180) ** 2 + (pos[:, 1] - el) ** 2
    return int(np.argmin(d))


def prep_hrir(hrir, sr_native):
    """HRIR -> delay-removed complex FRF on the log fit-grid (mapped to SR_TARGET)."""
    H = np.fft.rfft(hrir, n=PAD)
    fbins = np.fft.rfftfreq(PAD, 1.0 / sr_native)
    onset = int(np.argmax(np.abs(hrir)))               # pure arrival delay (samples @ sr_native)
    delay_s = onset / sr_native
    band = (fbins >= FIT_LO) & (fbins <= FIT_HI)
    fb, Hb = fbins[band], H[band]
    Hb = Hb * np.exp(1j * 2 * math.pi * fb * delay_s)  # remove pure delay (linear-phase advance)
    grid = np.logspace(math.log10(FIT_LO), math.log10(FIT_HI), N_GRID)
    re = np.interp(grid, fb, Hb.real); im = np.interp(grid, fb, Hb.imag)
    return grid, re + 1j * im, delay_s


def fit_one(grid, Hg):
    """SK fallback + baseline-Q cap. Mirrors dvtd_rails.fit_model orchestration on a prepared FRF."""
    omega = 2 * math.pi * grid / SR_TARGET
    wfit = band_weight(grid)
    fbmask = grid <= FIT_HI
    best = None
    for (N, M, lam) in D.CONFIGS:
        try:
            b, a_full = D.sk_once(omega, Hg, N, M, D.SK_ITERS, lam, wfit=wfit)
            Hfit = D.eval_tf(b, a_full, omega)
            if not np.all(np.isfinite(Hfit)):
                continue
            mag_err = D.floored_db(Hfit) - D.floored_db(Hg)
            rms = float(np.sqrt(np.mean(mag_err ** 2)))
            maxr = max((p["r"] for p in D.roots_features(a_full, SR_TARGET)), default=0.0)
            score = rms + (50.0 if maxr > D.UNSTABLE_ARTIFACT_R else 0.0)
            if best is None or score < best["score"]:
                best = dict(b=b, a=a_full, Hfit=Hfit, rms=rms, maxr=maxr, score=score)
            if rms <= 6.0 and maxr <= D.UNSTABLE_ARTIFACT_R:
                break
        except Exception:
            continue
    if best is None:
        return None
    poles = D.roots_features(best["a"], SR_TARGET)
    zeros = D.roots_features(best["b"][::-1], SR_TARGET)
    # baseline-Q cap: shared with DVTD (caps resonant poles only, robust renorm)
    Hbase, b_base, a_base = D.baseline_cap(poles, best["b"], best["a"], omega, SR_TARGET)
    t3 = D.T3_TRIGGER_FRAC * SR_TARGET
    for z in zeros:
        z["nonmin_phase"] = z["r"] > 1.0          # pinna notches often non-min-phase
        z["type3_warp_candidate"] = z["hz"] > t3
    return dict(poles=poles, zeros=zeros, rms=best["rms"], Hfit=best["Hfit"], Hbase=Hbase,
                coeffs_baseline=dict(b=[float(x) for x in b_base], a=[float(x) for x in a_base]),
                coeffs_measured=dict(b=[float(x) for x in best["b"]], a=[float(x) for x in best["a"]]))


def plot_one(rec, grid, Hg, out):
    status = rec["fit_status"]
    fig, ((axm, axp), (axr, axz)) = plt.subplots(2, 2, figsize=(11, 7.4), facecolor="#0b0f0e")
    Hb, Hf = rec["_Hbase"], rec["_Hfit"]
    axm.semilogx(grid, 20 * np.log10(np.abs(Hg) + 1e-12), color="#5bef6f", lw=1.5, label="measured HRTF")
    axm.semilogx(grid, 20 * np.log10(np.abs(Hf) + 1e-12), color="#7a5a2a", lw=0.9, ls="--", label="raw fit")
    axm.semilogx(grid, 20 * np.log10(np.abs(Hb) + 1e-12), color="#ffb13e", lw=1.5, label="baseline rail")
    axm.set_title(f"{rec['id']}  [{status}]  RMS {rec['rms']:.2f} dB  nmp(notch) {rec['flags']['nonmin_phase_zeros']}",
                  color="#ee493c" if status != "OK" else "#cdd", fontsize=9)
    axm.set_ylabel("dB", color="#889"); axm.legend(fontsize=7, facecolor="#11161400", labelcolor="#cdd")
    axp.semilogx(grid, np.angle(Hg), color="#5bef6f", lw=1.2, label="measured")
    axp.semilogx(grid, np.angle(Hf), color="#ffb13e", lw=0.9, label="fit")
    axp.set_title(f"phase | ITD removed {rec['removed_delay_ms']:.2f} ms", color="#cdd", fontsize=9)
    axp.legend(fontsize=7, facecolor="#11161400", labelcolor="#cdd")
    axr.semilogx(grid, D.floored_db(Hf) - D.floored_db(Hg), color="#2fc8cc", lw=1.0)
    axr.axhline(0, color="#26302b"); axr.set_title("residual (floored)", color="#cdd", fontsize=9)
    axr.set_xlabel("Hz", color="#889")
    th = np.linspace(0, 2 * math.pi, 240); axz.plot(np.cos(th), np.sin(th), color="#26302b", lw=1.0)
    for p in rec["poles"]:
        z = p["r"] * np.exp(1j * p["angle_rad"]); axz.plot(z.real, z.imag, "x",
            color="#ee493c" if p.get("unstable") else "#9b8cff", ms=7)
    for zz in rec["zeros"]:
        z = zz["r"] * np.exp(1j * zz["angle_rad"]); axz.plot(z.real, z.imag, "o", mfc="none",
            color="#f1d76a" if zz["nonmin_phase"] else "#2fc8cc", ms=6)
    axz.set_aspect("equal"); axz.set_xlim(-1.4, 1.4); axz.set_ylim(-1.4, 1.4)
    axz.set_title(f"z-plane | notch-zeros {rec['flags']['nonmin_phase_zeros']}", color="#cdd", fontsize=9)
    for ax in (axm, axp, axr, axz):
        ax.set_facecolor("#0b0f0e"); ax.tick_params(colors="#889", labelsize=7); ax.grid(True, alpha=0.12)
        for sp in ax.spines.values():
            sp.set_color("#26302b")
    fig.tight_layout(); fig.savefig(out, dpi=110, facecolor="#0b0f0e"); plt.close(fig)


def main():
    PLOTS.mkdir(parents=True, exist_ok=True)
    ir, sr, pos = load_sofa(SOFA)
    print(f"SOFA {ir.shape} @ {sr}  -> grid {len(AZIMUTHS)}x{len(ELEVATIONS)} dirs, ear {EAR}")
    recs, plotpacks = [], []
    for el in ELEVATIONS:
        for az in AZIMUTHS:
            idx = nearest(pos, az, el)
            aaz, ael = pos[idx, 0], pos[idx, 1]
            grid, Hg, delay_s = prep_hrir(ir[idx, EAR, :], sr)
            r = fit_one(grid, Hg)
            rid = f"az{int(round(aaz)):03d}_el{int(round(ael)):+03d}"
            if r is None:
                rec = dict(id=rid, fit_status="FAIL", poles=[], zeros=[], rms=None,
                           flags=dict(unstable_poles=0, nonmin_phase_zeros=0, type3_warp_zeros=0, poles_capped=0))
                recs.append(rec); continue
            r["fit_status"] = "OK" if r["rms"] <= 6.0 else "POOR_FIT"
            r["flags"] = dict(unstable_poles=sum(p["unstable"] for p in r["poles"]),
                              poles_capped=sum(p["capped"] for p in r["poles"]),
                              nonmin_phase_zeros=sum(z["nonmin_phase"] for z in r["zeros"]),
                              type3_warp_zeros=sum(z["type3_warp_candidate"] for z in r["zeros"]))
            rec = dict(id=rid, azimuth=float(aaz), elevation=float(ael), ear="left",
                       source=SOURCE, sr_target=SR_TARGET, fit_band_hz=[FIT_LO, FIT_HI],
                       removed_delay_ms=delay_s * 1e3, baseline_max_r=D.BASELINE_MAX_R,
                       rms=r["rms"], fit_status=r["fit_status"], flags=r["flags"],
                       poles=r["poles"], zeros=r["zeros"],
                       coeffs_baseline=r["coeffs_baseline"], coeffs_measured=r["coeffs_measured"],
                       _Hbase=r["Hbase"], _Hfit=r["Hfit"])
            plot_one(rec, grid, Hg, PLOTS / f"{rid}.png")
            plotpacks.append((rid, grid, Hg, r["Hbase"], r["fit_status"]))
            for k in ("_Hbase", "_Hfit"):
                rec.pop(k, None)
            recs.append(rec)
            print(f"  {rid}  [{rec['fit_status']:<8}] RMS {r['rms']:5.2f}  notch-zeros {rec['flags']['nonmin_phase_zeros']}"
                  f"  delay {delay_s*1e3:.2f}ms")
    # contact sheet
    n = len(plotpacks); cols = 6; rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(2.2 * cols, 1.7 * rows), facecolor="#080a0a")
    for ax, (rid, grid, Hg, Hb, st) in zip(np.atleast_1d(axes).ravel(), plotpacks):
        ax.semilogx(grid, 20 * np.log10(np.abs(Hg) + 1e-12), color="#5bef6f", lw=0.9)
        ax.semilogx(grid, 20 * np.log10(np.abs(Hb) + 1e-12), color="#ffb13e", lw=0.8)
        ax.set_title(rid, color="#ee493c" if st != "OK" else "#cfe9df", fontsize=6)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("#0b0f0e")
        for s in ax.spines.values():
            s.set_color("#283632")
    for ax in np.atleast_1d(axes).ravel()[n:]:
        ax.axis("off")
    fig.tight_layout(pad=0.3); fig.savefig(OUT / "contact_sheet.png", dpi=130, facecolor="#080a0a"); plt.close(fig)
    (OUT / "hrtf_rails.json").write_text(json.dumps(recs, indent=2), encoding="utf-8")
    ok = sum(r["fit_status"] == "OK" for r in recs)
    nmp = sum(r["flags"]["nonmin_phase_zeros"] for r in recs)
    print(f"\n{len(recs)} dirs: {ok} OK; {nmp} notch (non-min-phase) zeros total")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
