#!/usr/bin/env python3
"""forge_hedz_joint_calibration.py — joint coherent 4-corner Talking Hedz fit.

The Clean Room calibration done right: ALL FOUR corners fitted together
with one shared 6-stage layout, anchored by per-stage role bands and
per-corner seed pole positions. Independent per-corner fitting was
falsified on 2026-05-20 (M50/Q50 nulled -0.69 dB even with each corner
fitting at -272 dB pre-encode).

Pipeline:
  1. Decode skin-13 ROM corner words to 4 complex cascade responses.
     REFERENCE-ONLY (envelope/phase the corners produce). No coefficients
     or words copied.
  2. Joint-fit all 4 corners simultaneously with forge_joint, anchored
     by per-stage StageBands (from the ROM stage-layout audit) and
     per-corner pole-frequency seeds (also from the ROM audit).
  3. Encode authored corners to u16, interpolate morph-first at M50/Q50,
     render, null against `hedzm50q50.wav`.

Gate: <= -60 dB. Baselines: ROM words -95.41 dB, JSON-6dp derived-packed
-53.75 dB. Failure modes:
  (a) stage anchors wrong  -> revise StageBands
  (b) joint constraints too loose  -> tighten _BOUNDS_PENALTY or add
                                      explicit coherence regularizer
  (c) optimizer found bad factorization  -> raise --restarts or revise seed
  (d) Hedz needs near-ROM-word precision  -> clean-room can't reach it

Offline analysis only. ROM words are reference-only.

Usage:
    python tools/forge_hedz_joint_calibration.py [--restarts N] [--profile P]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.forge_fit import cascade_response, fit_grid, perceptual_weight  # noqa: E402
from pyruntime.forge_joint import StageBand, joint_fit_corners  # noqa: E402
from tools.coefficient_field_bakeoff import kernel_to_words  # noqa: E402
from tools.rom_corner_audit import (  # noqa: E402
    CORNERS, clean_null, interp_rom, words_to_kernel_c4x4,
)
from tools.verified_packed_audit import (  # noqa: E402
    DRY, X3_MID, load_mono, null_db, render,
)

ROM_BIN = ROOT / "dev" / "tmp" / "cheat_engine_dump" / "skin13_corners_rom.bin"
OUT_ROOT = ROOT / "dev" / "tmp" / "forge_hedz_joint_calibration"
SR = 44100.0
BOOST = 1.0


# Talking Hedz role bands, derived from the ROM stage-layout audit. Stages 1
# and 5 are FLUID (F1/F2) — wide bands that
# span the formant migration; stages 0/2/3/4 are RIGID (stable across
# corners). Stage 1 and stage 5 bands overlap (both cover ~150-2300 Hz);
# disambiguation is by per-corner seed (below).
HEDZ_BANDS: list[StageBand] = [
    StageBand(freq_lo_hz=8500.0,  freq_hi_hz=12500.0, radius_lo=0.6, radius_hi=0.999),  # 0 PHASE_SCAR top edge
    StageBand(freq_lo_hz=150.0,   freq_hi_hz=1300.0,  radius_lo=0.6, radius_hi=0.999),  # 1 F1 FLUID
    StageBand(freq_lo_hz=1450.0,  freq_hi_hz=3000.0,  radius_lo=0.6, radius_hi=0.999),  # 2 low-upper
    StageBand(freq_lo_hz=2200.0,  freq_hi_hz=3400.0,  radius_lo=0.6, radius_hi=0.999),  # 3 upper
    StageBand(freq_lo_hz=4400.0,  freq_hi_hz=6000.0,  radius_lo=0.6, radius_hi=0.999),  # 4 high-air
    StageBand(freq_lo_hz=150.0,   freq_hi_hz=2300.0,  radius_lo=0.6, radius_hi=0.999),  # 5 F2 FLUID
]

# Per-corner pole-frequency seeds, in Hz, from the ROM stage-layout audit.
# Each row is [stage0, stage1, stage2, stage3, stage4, stage5].
HEDZ_SEEDS: dict[str, np.ndarray] = {
    "A": np.array([10500.0, 1006.0, 1770.0, 2650.0, 5200.0,  225.0]),  # M0_Q0
    "B": np.array([ 9500.0,  227.0, 2670.0, 3080.0, 5400.0, 2020.0]),  # M100_Q0
    "C": np.array([11500.0, 1076.0, 1700.0, 2500.0, 4910.0,  178.0]),  # M0_Q100
    "D": np.array([10100.0,  219.0, 2420.0, 2720.0, 4970.0, 1700.0]),  # M100_Q100
}


def load_rom_corners(path: Path) -> dict[str, np.ndarray]:
    """Parse the 240-byte ROM block: 4 corners x 6 stages x 5 u16 LE."""
    raw = path.read_bytes()
    assert len(raw) == 240, f"{path}: {len(raw)} bytes, expected 240"
    u16 = np.frombuffer(raw, dtype="<u2")
    return {
        letter: u16[i * 30:(i + 1) * 30].reshape(6, 5).astype(np.uint16)
        for i, (letter, _label) in enumerate(CORNERS)
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--restarts", type=int, default=12,
                    help="joint-fit restarts (default 12)")
    ap.add_argument("--profile", default="vocal",
                    help="perceptual weighting profile (default vocal)")
    ap.add_argument("--no-bands", action="store_true",
                    help="disable per-stage role bands (debug / ablation)")
    ap.add_argument("--no-seeds", action="store_true",
                    help="disable per-corner pole-frequency seeds (debug)")
    ap.add_argument("--grid", type=int, default=2048,
                    help="fit grid points (default 2048; try 512 for smoke)")
    ap.add_argument("--max-nfev", type=int, default=2500,
                    help="per-restart max function evals (default 2500)")
    ap.add_argument("--verbose", action="store_true",
                    help="print per-restart progress")
    args = ap.parse_args()

    if not ROM_BIN.exists():
        print(f"!! {ROM_BIN} not found — run tools/rom_corner_audit.py first.")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    freqs, z_inv = fit_grid(SR, n=args.grid)
    weight = perceptual_weight(freqs, args.profile)

    # ── 1. reference measurement: ROM corner complex responses ───────────────
    rom_words = load_rom_corners(ROM_BIN)
    rom_kernels = {k: words_to_kernel_c4x4(v) for k, v in rom_words.items()}
    targets = {k: cascade_response(rom_kernels[k], z_inv) for k in rom_kernels}

    bands = None if args.no_bands else HEDZ_BANDS
    seeds = None if args.no_seeds else HEDZ_SEEDS

    print(f"Forge JOINT calibration — Talking Hedz remake  ({ts})")
    print(f"  profile={args.profile}  restarts={args.restarts}  "
          f"grid={len(freqs)} pts")
    print(f"  bands={'on' if bands else 'OFF'}  "
          f"seeds={'on' if seeds else 'OFF'}\n")

    # ── 2. joint fit all 4 corners with one shared stage layout ──────────────
    fit = joint_fit_corners(
        targets=targets, freqs=freqs, z_inv=z_inv, sr=SR,
        bands=bands, seeds=seeds,
        profile=args.profile, weight=weight,
        n_restarts=args.restarts, seed=1234,
        max_nfev=args.max_nfev, verbose=args.verbose,
    )

    authored_kernels = fit.kernel
    authored_words: dict[str, np.ndarray] = {}
    print("  corner       fit(weighted)  fit(flat)   words!=ROM  maxLSB  stable")
    fit_rows = []
    for letter, label in CORNERS:
        kernel = authored_kernels[letter]
        words = kernel_to_words(kernel)
        authored_words[letter] = words
        h = cascade_response(kernel, z_inv)
        flat_num = float(np.sqrt(np.mean(np.abs(h - targets[letter]) ** 2)))
        flat_den = float(np.sqrt(np.mean(np.abs(targets[letter]) ** 2))) + 1e-30
        flat_db = 20.0 * np.log10(flat_num / flat_den + 1e-30)
        dword = words.astype(np.int64) - rom_words[letter].astype(np.int64)
        n_diff = int(np.count_nonzero(dword))
        max_lsb = int(np.max(np.abs(dword)))
        stable = fit.stable[letter]
        fit_rows.append({
            "letter": letter, "label": label,
            "weighted_db": fit.response_null_db[letter], "flat_db": flat_db,
            "words_diff": n_diff, "max_lsb": max_lsb, "stable": stable,
        })
        print(f"  {label:11}  {fit.response_null_db[letter]:+8.2f} dB  "
              f"{flat_db:+8.2f} dB  {n_diff:6d}/30  {max_lsb:6d}  "
              f"{'yes' if stable else 'NO '}")
    print(f"  bounds_residual: {fit.bounds_residual:.4g}  "
          f"best_restart: {fit.best_restart}/{fit.restarts}")
    if fit.notes:
        for n in fit.notes:
            print(f"  NOTE: {n}")

    # ── 3. per-corner post-encode cost (authored vs ROM render, df2-internal)
    dry = load_mono(DRY)
    x3 = load_mono(X3_MID)
    corner_rows = []
    for letter, label in CORNERS:
        a_auth = render(dry, authored_kernels[letter], "agc_boost", BOOST)
        a_rom = render(dry, rom_kernels[letter], "agc_boost", BOOST)
        n = min(len(a_auth), len(a_rom))
        cn = null_db(a_rom[:n].astype(np.float64),
                     a_auth[:n].astype(np.float64), 1.0)
        corner_rows.append({"label": label, "corner_null_db": cn})

    # ── 4. M50/Q50 — authored corners through the packed morph path ──────────
    auth_mid = interp_rom(authored_words, 0.5, 0.5)
    auth_lag, auth_null = clean_null(
        render(dry, auth_mid, "agc_boost", BOOST).astype(np.float64), x3)

    rom_mid = interp_rom(rom_words, 0.5, 0.5)
    rom_lag, rom_null = clean_null(
        render(dry, rom_mid, "agc_boost", BOOST).astype(np.float64), x3)

    passed = auth_null <= -60.0
    print(f"\n  M50/Q50 null vs X3 wet:")
    print(f"    authored corners (Forge JOINT fit) : {auth_null:+.2f} dB  "
          f"(lag {auth_lag})  [{'PASS' if passed else 'FAIL'} <= -60]")
    print(f"    ROM words (baseline)               : {rom_null:+.2f} dB  "
          f"(lag {rom_lag})")

    # ── 5. report ────────────────────────────────────────────────────────────
    L = ["# Forge JOINT calibration — Talking Hedz remake", "",
         f"Generated {ts} by `tools/forge_hedz_joint_calibration.py`", "",
         "Joint coherent 4-corner fit. One shared 6-stage layout; "
         "per-corner parameter variation within per-stage role bands; "
         "per-corner pole-frequency seeds from the ROM stage-layout audit. "
         "Independent per-corner fitting (the prior `forge_hedz_calibration.py` "
         "approach) was falsified.", "",
         f"- profile: `{args.profile}`   restarts: {args.restarts}   "
         f"fit grid: {len(freqs)} log-spaced points",
         f"- bands: {'enabled' if bands else 'DISABLED (ablation)'}   "
         f"seeds: {'enabled' if seeds else 'DISABLED (ablation)'}",
         f"- gate: **-60 dB**   baselines: ROM words -95.41 dB, "
         f"JSON-6dp derived-packed -53.75 dB",
         f"- bounds_residual: {fit.bounds_residual:.4g}   "
         f"best_restart: {fit.best_restart + 1}/{fit.restarts}", "",
         "## Per-corner fit", "",
         "| corner | fit weighted | fit flat | words != ROM | max LSB | stable |",
         "|---|---:|---:|---:|---:|:--:|"]
    for r in fit_rows:
        L.append(f"| {r['label']} | {r['weighted_db']:+.2f} dB | "
                 f"{r['flat_db']:+.2f} dB | {r['words_diff']}/30 | "
                 f"{r['max_lsb']} | {'yes' if r['stable'] else 'NO'} |")
    L += ["", "## Per-corner post-encode cost (authored vs ROM render)", "",
          "| corner | authored vs ROM null |", "|---|---:|"]
    for r in corner_rows:
        L.append(f"| {r['label']} | {r['corner_null_db']:+.2f} dB |")
    L += ["", "## M50/Q50 null vs X3 wet `hedzm50q50.wav`", "",
          "Post-encode: authored corners -> u16 -> morph-first bilinear "
          "interpolate(0.5, 0.5) -> render -> lag-aligned clean-window null.", "",
          "| path | lag | clean null | gate -60 dB |", "|---|---:|---:|:--:|",
          f"| **authored corners (Forge JOINT fit)** | {auth_lag} | "
          f"**{auth_null:+.2f} dB** | {'PASS' if passed else 'FAIL'} |",
          f"| ROM words (baseline) | {rom_lag} | {rom_null:+.2f} dB | — |", "",
          "## Verdict", ""]
    if passed:
        L += [f"**PASS.** Joint coherent 4-corner fit clears the -60 dB gate "
              f"at {auth_null:+.2f} dB. The Forge framework — joint staged "
              f"body fitting + packed-morph survival — is calibrated on "
              "Talking Hedz. Authoring original bodies (Small Talk, Speaker "
              "Knockerz, Aluminum Siding, Cul-De-Sac) is unblocked. Note this "
              "validates the AUTHORING path; it does NOT validate the IR/ARMA "
              "capture path (snapshot factory) — that is a separate test."]
    else:
        L += [f"**FAIL.** Authored M50/Q50 nulls {auth_null:+.2f} dB, short of "
              "the -60 dB gate. Failure-mode triage: "
              "(a) stage anchors wrong → revise `HEDZ_BANDS`; "
              "(b) joint constraints too loose → raise `_BOUNDS_PENALTY` or "
              "add a coherence regularizer to `forge_joint.py`; "
              "(c) optimizer found bad factorization → raise `--restarts` "
              "or revise seed jitter; (d) Hedz needs near-ROM-word "
              "precision → clean-room won't reach it; shelve Hedz and proceed "
              "to originals on intent gates. Diagnose by per-corner "
              "fit numbers above: weak `fit weighted` or large `max LSB` "
              "points at the limiting corner."]
    L.append("")

    report = out_dir / "JOINT_CALIBRATION_REPORT.md"
    report.write_text("\n".join(L) + "\n")
    np.savez(out_dir / "authored_corners.npz",
             **{f"kernel_{k}": v for k, v in authored_kernels.items()},
             **{f"words_{k}": v for k, v in authored_words.items()})
    print(f"\nwrote: {report}")
    print(f"       {out_dir / 'authored_corners.npz'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
