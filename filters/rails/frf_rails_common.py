#!/usr/bin/env python3
"""Shared FRF->rails runner for the circuit and modal wells.

Front-ends (circuit_rails.py / modal_rails.py) only name the well; the fit math
is dvtd_rails' SK kernel verbatim (single source, same pattern as hrtf_rails.py):
sk_once over CONFIGS -> roots_features -> baseline_cap (BASELINE_MAX_R) -> flags,
RMS gate 6 dB, per-FRF plot + contact sheet + rails JSON.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import dvtd_rails as D   # SK kernel + helpers (single source of the fit math)

SR_TARGET = D.SR_TARGET
RMS_GATE = 6.0
TAPER_LO = 14000.0


def band_weight(grid, fit_hi):
    w = np.ones_like(grid)
    hi = grid > TAPER_LO
    x = (grid[hi] - TAPER_LO) / (fit_hi - TAPER_LO)
    w[hi] = 0.4 + 0.6 * 0.5 * (1.0 + np.cos(np.pi * x))
    return w


def fit_one(grid, Hg):
    omega = 2 * math.pi * grid / SR_TARGET
    wfit = band_weight(grid, grid[-1])
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
            if rms <= RMS_GATE and maxr <= D.UNSTABLE_ARTIFACT_R:
                break
        except Exception:
            continue
    if best is None:
        return None
    poles = D.roots_features(best["a"], SR_TARGET)
    zeros = D.roots_features(best["b"][::-1], SR_TARGET)
    Hbase, b_base, a_base = D.baseline_cap(poles, best["b"], best["a"], omega, SR_TARGET)
    t3 = D.T3_TRIGGER_FRAC * SR_TARGET
    for z in zeros:
        z["nonmin_phase"] = z["r"] > 1.0
        z["type3_warp_candidate"] = z["hz"] > t3
    return dict(poles=poles, zeros=zeros, rms=best["rms"], Hfit=best["Hfit"], Hbase=Hbase,
                coeffs_baseline=dict(b=[float(x) for x in b_base], a=[float(x) for x in a_base]),
                coeffs_measured=dict(b=[float(x) for x in best["b"]], a=[float(x) for x in best["a"]]))


def plot_one(rec, grid, Hg, Hf, Hb, out):
    status = rec["fit_status"]
    fig, ((axm, axp), (axr, axz)) = plt.subplots(2, 2, figsize=(11, 7.4), facecolor="#0b0f0e")
    axm.semilogx(grid, 20 * np.log10(np.abs(Hg) + 1e-12), color="#5bef6f", lw=1.5, label="well FRF")
    axm.semilogx(grid, 20 * np.log10(np.abs(Hf) + 1e-12), color="#7a5a2a", lw=0.9, ls="--", label="raw fit")
    axm.semilogx(grid, 20 * np.log10(np.abs(Hb) + 1e-12), color="#ffb13e", lw=1.5, label="baseline rail")
    axm.set_title(f"{rec['id']}  [{status}]  RMS {rec['rms']:.2f} dB",
                  color="#ee493c" if status != "OK" else "#cdd", fontsize=9)
    axm.set_ylabel("dB", color="#889"); axm.legend(fontsize=7, facecolor="#11161400", labelcolor="#cdd")
    axp.semilogx(grid, np.angle(Hg), color="#5bef6f", lw=1.2, label="well")
    axp.semilogx(grid, np.angle(Hf), color="#ffb13e", lw=0.9, label="fit")
    axp.set_title("phase", color="#cdd", fontsize=9)
    axp.legend(fontsize=7, facecolor="#11161400", labelcolor="#cdd")
    axr.semilogx(grid, D.floored_db(Hf) - D.floored_db(Hg), color="#2fc8cc", lw=1.0)
    axr.axhline(0, color="#26302b"); axr.set_title("residual (floored)", color="#cdd", fontsize=9)
    axr.set_xlabel("Hz", color="#889")
    th = np.linspace(0, 2 * math.pi, 240); axz.plot(np.cos(th), np.sin(th), color="#26302b", lw=1.0)
    for p in rec["poles"]:
        z = p["r"] * np.exp(1j * p["angle_rad"])
        axz.plot(z.real, z.imag, "x", color="#ee493c" if p.get("unstable") else "#9b8cff", ms=7)
    for zz in rec["zeros"]:
        z = zz["r"] * np.exp(1j * zz["angle_rad"])
        axz.plot(z.real, z.imag, "o", mfc="none", color="#f1d76a" if zz["nonmin_phase"] else "#2fc8cc", ms=6)
    axz.set_aspect("equal"); axz.set_xlim(-1.4, 1.4); axz.set_ylim(-1.4, 1.4)
    axz.set_title(f"z-plane | nmp zeros {rec['flags']['nonmin_phase_zeros']}", color="#cdd", fontsize=9)
    for ax in (axm, axp, axr, axz):
        ax.set_facecolor("#0b0f0e"); ax.tick_params(colors="#889", labelsize=7); ax.grid(True, alpha=0.12)
        for sp in ax.spines.values():
            sp.set_color("#26302b")
    fig.tight_layout(); fig.savefig(out, dpi=110, facecolor="#0b0f0e"); plt.close(fig)


def run_well(well: str, in_dir: Path, out_dir: Path):
    plots = out_dir / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in in_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"no FRFs in {in_dir} — run tools/{well}_frf.py first")
    recs, packs = [], []
    for fp in files:
        d = json.loads(fp.read_text(encoding="utf-8"))
        grid = np.array(d["freq_hz"])
        Hg = np.array(d["H_re"]) + 1j * np.array(d["H_im"])
        r = fit_one(grid, Hg)
        rid = d["id"]
        if r is None:
            recs.append(dict(id=rid, fit_status="FAIL", poles=[], zeros=[], rms=None,
                             flags=dict(unstable_poles=0, nonmin_phase_zeros=0,
                                        type3_warp_zeros=0, poles_capped=0)))
            print(f"  {rid}  [FAIL]")
            continue
        status = "OK" if r["rms"] <= RMS_GATE else "POOR_FIT"
        flags = dict(unstable_poles=sum(p["unstable"] for p in r["poles"]),
                     poles_capped=sum(p["capped"] for p in r["poles"]),
                     nonmin_phase_zeros=sum(z["nonmin_phase"] for z in r["zeros"]),
                     type3_warp_zeros=sum(z["type3_warp_candidate"] for z in r["zeros"]))
        rec = dict(id=rid, well=well, source=d["source"], model=d.get("model", d.get("family")),
                   settings=d.get("settings", {}), sr_target=SR_TARGET,
                   fit_band_hz=[float(grid[0]), float(grid[-1])],
                   baseline_max_r=D.BASELINE_MAX_R, rms=r["rms"], fit_status=status, flags=flags,
                   poles=r["poles"], zeros=r["zeros"],
                   coeffs_baseline=r["coeffs_baseline"], coeffs_measured=r["coeffs_measured"])
        plot_one(rec, grid, Hg, r["Hfit"], r["Hbase"], plots / f"{rid}.png")
        packs.append((rid, grid, Hg, r["Hbase"], status))
        recs.append(rec)
        print(f"  {rid}  [{status:<8}] RMS {r['rms']:5.2f}  poles_capped {flags['poles_capped']}"
              f"  nmp_zeros {flags['nonmin_phase_zeros']}")
    # contact sheet
    n = len(packs); cols = 6; rows = max(1, (n + cols - 1) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(2.2 * cols, 1.7 * rows), facecolor="#080a0a")
    for ax, (rid, grid, Hg, Hb, st) in zip(np.atleast_1d(axes).ravel(), packs):
        ax.semilogx(grid, 20 * np.log10(np.abs(Hg) + 1e-12), color="#5bef6f", lw=0.9)
        ax.semilogx(grid, 20 * np.log10(np.abs(Hb) + 1e-12), color="#ffb13e", lw=0.8)
        ax.set_title(rid, color="#ee493c" if st != "OK" else "#cfe9df", fontsize=5)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_facecolor("#0b0f0e")
        for s in ax.spines.values():
            s.set_color("#283632")
    for ax in np.atleast_1d(axes).ravel()[n:]:
        ax.axis("off")
    fig.tight_layout(pad=0.3)
    fig.savefig(out_dir / "contact_sheet.png", dpi=130, facecolor="#080a0a")
    plt.close(fig)
    (out_dir / f"{well}_rails.json").write_text(json.dumps(recs, indent=2), encoding="utf-8")
    ok = sum(r["fit_status"] == "OK" for r in recs)
    rmss = [r["rms"] for r in recs if r["rms"] is not None]
    print(f"\n{len(recs)} rails: {ok} OK / {len(recs) - ok} not; "
          f"RMS min {min(rmss):.2f} med {float(np.median(rmss)):.2f} max {max(rmss):.2f}")
    print(f"wrote {out_dir}")
    return recs
