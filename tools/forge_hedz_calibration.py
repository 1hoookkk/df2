#!/usr/bin/env python3
"""forge_hedz_calibration.py — remake Talking Hedz the Clean Room way.

Calibration fixture for the Forge fitter (pyruntime/forge_fit.py). Proves
the fitter before it is trusted on original bodies:

  1. Decode the skin-13 ROM corner words to their 4 complex cascade
     responses. These are REFERENCE-ONLY behavioural measurements — the
     envelope/phase the corners produce. The Forge never sees the ROM
     coefficients or words as a fit target; only the response curve.
  2. Fit each corner with forge_fit.fit_corner — a Bark/ERB-weighted,
     phase-aware least-squares fit that authors fresh d-space coefficients.
  3. Encode the authored corners to u16 words (the from_corner_data path),
     interpolate morph-first at M50/Q50, render, and null against the X3
     wet `hedzm50q50.wav`.

Gate: <= -60 dB. Baselines for context: ROM words give -95.41 dB
(bit-accurate); JSON-6dp derived-packed gives -53.75 dB.

The gate is measured POST-ENCODE — authored corners are quantised by
encode -> u16 -> decode, so a perfect pre-quantisation fit can still drift.

Offline analysis only. No cartridge asset / format / cascade topology /
default interpolation path is changed. ROM words are reference-only and
are never written into any shipped artifact.

Usage:
    python tools/forge_hedz_calibration.py [--restarts N] [--profile P]
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

from pyruntime.forge_fit import (  # noqa: E402
    cascade_response, fit_corner, fit_grid, perceptual_weight,
)
from tools.coefficient_field_bakeoff import kernel_to_words  # noqa: E402
from tools.rom_corner_audit import (  # noqa: E402
    CORNERS, clean_null, interp_rom, words_to_kernel_c4x4,
)
from tools.verified_packed_audit import (  # noqa: E402
    DRY, X3_MID, load_mono, null_db, render,
)

ROM_BIN = ROOT / "dev" / "tmp" / "cheat_engine_dump" / "skin13_corners_rom.bin"
OUT_ROOT = ROOT / "dev" / "tmp" / "forge_hedz_calibration"
SR = 44100.0
BOOST = 1.0  # ref/p2k_skins/00_talking_hedz.json — every keyframe boost = 1.0


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
    ap.add_argument("--restarts", type=int, default=16,
                    help="fit restarts per corner (default 16)")
    ap.add_argument("--profile", default="vocal",
                    help="perceptual weighting profile (default vocal)")
    args = ap.parse_args()

    if not ROM_BIN.exists():
        print(f"!! {ROM_BIN} not found — run tools/rom_corner_audit.py first.")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    freqs, z_inv = fit_grid(SR, n=2048)
    weight = perceptual_weight(freqs, args.profile)

    # ── 1. reference measurement: ROM corner complex responses ───────────────
    rom_words = load_rom_corners(ROM_BIN)
    rom_kernels = {k: words_to_kernel_c4x4(v) for k, v in rom_words.items()}
    targets = {k: cascade_response(rom_kernels[k], z_inv) for k in rom_kernels}

    print(f"Forge calibration — Talking Hedz remake  ({ts})")
    print(f"  profile={args.profile}  restarts={args.restarts}  "
          f"grid={len(freqs)} pts\n")

    # ── 2. fit 4 corners ─────────────────────────────────────────────────────
    authored_kernels: dict[str, np.ndarray] = {}
    authored_words: dict[str, np.ndarray] = {}
    fit_rows = []
    print("  corner       fit(weighted)  fit(flat)   words!=ROM  maxLSB  stable")
    for ci, (letter, label) in enumerate(CORNERS):
        fit = fit_corner(targets[letter], freqs, z_inv, SR,
                         profile=args.profile, n_restarts=args.restarts,
                         seed=1000 + ci)
        authored_kernels[letter] = fit.kernel
        words = kernel_to_words(fit.kernel)
        authored_words[letter] = words

        # flat (unweighted) response match, for an honest second number
        h = cascade_response(fit.kernel, z_inv)
        flat_num = float(np.sqrt(np.mean(np.abs(h - targets[letter]) ** 2)))
        flat_den = float(np.sqrt(np.mean(np.abs(targets[letter]) ** 2))) + 1e-30
        flat_db = 20.0 * np.log10(flat_num / flat_den + 1e-30)

        dword = words.astype(np.int64) - rom_words[letter].astype(np.int64)
        n_diff = int(np.count_nonzero(dword))
        max_lsb = int(np.max(np.abs(dword)))
        fit_rows.append({
            "letter": letter, "label": label,
            "weighted_db": fit.response_null_db, "flat_db": flat_db,
            "words_diff": n_diff, "max_lsb": max_lsb,
            "stable": fit.stable, "best_restart": fit.best_restart,
        })
        print(f"  {label:11}  {fit.response_null_db:+8.2f} dB  "
              f"{flat_db:+8.2f} dB  {n_diff:6d}/30  {max_lsb:6d}  "
              f"{'yes' if fit.stable else 'NO '}")

    # ── 3. per-corner post-encode cost (authored vs ROM, df2-internal) ───────
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

    # baseline: real ROM words through the same path
    rom_mid = interp_rom(rom_words, 0.5, 0.5)
    rom_lag, rom_null = clean_null(
        render(dry, rom_mid, "agc_boost", BOOST).astype(np.float64), x3)

    passed = auth_null <= -60.0
    print(f"\n  M50/Q50 null vs X3 wet:")
    print(f"    authored corners (Forge fit) : {auth_null:+.2f} dB  "
          f"(lag {auth_lag})  [{'PASS' if passed else 'FAIL'} <= -60]")
    print(f"    ROM words (baseline)         : {rom_null:+.2f} dB  "
          f"(lag {rom_lag})")

    # ── 5. report ────────────────────────────────────────────────────────────
    L = ["# Forge calibration — Talking Hedz remake", "",
         f"Generated {ts} by `tools/forge_hedz_calibration.py`", "",
         "Remakes Talking Hedz the Clean Room way: the Forge fitter "
         "(`pyruntime/forge_fit.py`) measures the 4 ROM corner complex "
         "responses (reference-only) and authors fresh 6-biquad corners that "
         "match them. The authored corners are encoded to u16, interpolated "
         "morph-first at M50/Q50, rendered, and nulled against the X3 wet.", "",
         f"- profile: `{args.profile}`   restarts/corner: {args.restarts}   "
         f"fit grid: {len(freqs)} log-spaced points",
         f"- gate: **-60 dB**   baselines: ROM words -95.41 dB, "
         f"JSON-6dp derived-packed -53.75 dB", "",
         "## Per-corner fit", "",
         "`fit(weighted)` is the Bark/ERB-weighted complex response match; "
         "`fit(flat)` is the same match unweighted. `words!=ROM` counts how "
         "many of the 30 authored u16 words differ from the ROM words — the "
         "Clean Room check (the fit is independent; it is not a word copy).", "",
         "| corner | fit weighted | fit flat | words != ROM | max LSB | stable |",
         "|---|---:|---:|---:|---:|:--:|"]
    for r in fit_rows:
        L.append(f"| {r['label']} | {r['weighted_db']:+.2f} dB | "
                 f"{r['flat_db']:+.2f} dB | {r['words_diff']}/30 | "
                 f"{r['max_lsb']} | {'yes' if r['stable'] else 'NO'} |")
    L += ["", "## Per-corner post-encode cost (authored vs ROM render)", "",
          "df2-internal null: authored corner render vs ROM corner render, "
          "both at the corner, same dry. Isolates the encode->u16->decode "
          "quantisation cost of the authored coefficients (no X3 wet — no "
          "corner wets exist on disk).", "",
          "| corner | authored vs ROM null |", "|---|---:|"]
    for r in corner_rows:
        L.append(f"| {r['label']} | {r['corner_null_db']:+.2f} dB |")
    L += ["", "## M50/Q50 null vs X3 wet `hedzm50q50.wav`", "",
          "Post-encode: authored corners -> u16 -> morph-first bilinear "
          "interpolate(0.5, 0.5) -> render -> lag-aligned clean-window null.", "",
          "| path | lag | clean null | gate -60 dB |", "|---|---:|---:|:--:|",
          f"| **authored corners (Forge fit)** | {auth_lag} | "
          f"**{auth_null:+.2f} dB** | {'PASS' if passed else 'FAIL'} |",
          f"| ROM words (baseline) | {rom_lag} | {rom_null:+.2f} dB | — |", "",
          "## Verdict", ""]
    if passed:
        L += [f"**PASS.** The Forge authored 4 original corners from response "
              f"measurements alone; encoded and interpolated, they null "
              f"{auth_null:+.2f} dB against the E-mu hardware wet — inside the "
              "-60 dB gate. The fitter is calibrated. Next: throw this fixture "
              "away and author original bodies."]
    else:
        L += [f"**FAIL.** Authored M50/Q50 nulls {auth_null:+.2f} dB, short of "
              "the -60 dB gate. Diagnose with the per-corner fit and "
              "post-encode tables above: a corner with a weak `fit weighted` "
              "number or a large `max LSB` is the limiter. Raise `--restarts` "
              "or revisit the fit parameterisation before trusting the Forge "
              "on originals."]
    L.append("")

    report = out_dir / "CALIBRATION_REPORT.md"
    report.write_text("\n".join(L) + "\n")
    np.savez(out_dir / "authored_corners.npz",
             **{f"kernel_{k}": v for k, v in authored_kernels.items()},
             **{f"words_{k}": v for k, v in authored_words.items()})
    print(f"\nwrote: {report}")
    print(f"       {out_dir / 'authored_corners.npz'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
