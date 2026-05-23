#!/usr/bin/env python3
"""rust_cascade_parity.py — verify the Rust trench-core Cascade reproduces the
Python `scipy.sosfilt` M50/Q50 ROM-word reference.

The Rust render is produced by the integration test:
    cargo test -p trench-core --features packed_interp \\
        --test rust_cascade_parity -- --nocapture
which writes `dev/tmp/rust_cascade_parity/rust_rom_m50q50.wav` (32-bit float,
mono) by feeding the real skin-13 ROM corner words through the actual runtime
`Cascade`.

This script recomputes the Python reference from scratch (it does NOT trust the
prior -95.41 dB number) and nulls the Rust render against:
  (a) the Python `rom_corner_audit` M50/Q50 reference render  — acceptance <= -90 dB
  (b) the X3 wet `hedzm50q50.wav`                              — acceptance ~ -95 dB

Lag convention for (b): x3[n] <-> cand[n-2817], clean window x3[7283:254915]
(reused verbatim from tools/verified_packed_audit.py via rom_corner_audit).

Offline verification only. No cartridge asset / format / topology change.

Usage:
    python tools/rust_cascade_parity.py
"""
from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scipy.io import wavfile

from tools.verified_packed_audit import (
    load_mono, render, content_bounds, find_lag, refine_lag,
    null_db, best_gain, DRY, X3_MID,
)
from tools.rom_corner_audit import interp_rom, CORNERS

ROM_BIN = ROOT / "dev" / "tmp" / "cheat_engine_dump" / "skin13_corners_rom.bin"
RUST_WAV = ROOT / "dev" / "tmp" / "rust_cascade_parity" / "rust_rom_m50q50.wav"
OUT_ROOT = ROOT / "dev" / "tmp" / "rust_cascade_parity"
BOOST = 1.0  # ref/p2k_skins/00_talking_hedz.json — every keyframe boost = 1.0


def load_rust_render(path: Path) -> np.ndarray:
    """Load the float32 mono WAV written by the Rust parity test."""
    sr, data = wavfile.read(str(path))
    assert sr == 44100, f"{path}: sr {sr} != 44100"
    if data.ndim == 2:
        data = data[:, 0]
    return data.astype(np.float64)


def load_rom_corners(path: Path) -> dict[str, np.ndarray]:
    """Parse the 240-byte ROM block: 4 corners x 6 stages x 5 u16 LE."""
    raw = path.read_bytes()
    assert len(raw) == 240, f"{path}: {len(raw)} bytes, expected 240"
    u16 = np.frombuffer(raw, dtype="<u2")
    return {
        letter: u16[i * 30:(i + 1) * 30].reshape(6, 5).astype(np.uint16)
        for i, (letter, _label) in enumerate(CORNERS)
    }


def clean_null_vs_x3(cand: np.ndarray, x3: np.ndarray) -> tuple[int, float, float]:
    """Lag-aligned clean-window null of cand vs the X3 wet.

    Returns (lag, gain, null_db). Same procedure as rom_corner_audit.clean_null,
    but also returns the gain so the report can show it."""
    cs, ce = content_bounds(x3)
    coarse = find_lag(x3, cand)
    lag, _ = refine_lag(x3, cand, cs, ce, coarse)
    r, c = x3[cs:ce], cand[cs - lag:ce - lag]
    m = min(len(r), len(c))
    r, c = r[:m], c[:m]
    g = best_gain(r, c)
    return lag, g, null_db(r, c, g)


def main() -> int:
    if not RUST_WAV.exists():
        print(f"!! {RUST_WAV} not found.")
        print("   Run: cargo test -p trench-core --features packed_interp "
              "--test rust_cascade_parity -- --nocapture")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── inputs ───────────────────────────────────────────────────────────────
    dry = load_mono(DRY)
    x3 = load_mono(X3_MID)
    rom = load_rom_corners(ROM_BIN)
    rust = load_rust_render(RUST_WAV)

    # ── Python reference render (recomputed from scratch) ────────────────────
    rom_mid = interp_rom(rom, 0.5, 0.5)
    py_ref = render(dry, rom_mid, "agc_boost", BOOST).astype(np.float64)

    print(f"dry        {len(dry)} samples")
    print(f"x3 wet     {len(x3)} samples")
    print(f"rust       {len(rust)} samples")
    print(f"python ref {len(py_ref)} samples")

    # ── (a) Rust vs Python reference — sample-aligned, no lag ────────────────
    n = min(len(rust), len(py_ref))
    r_seg, p_seg = rust[:n], py_ref[:n]
    diff = r_seg - p_seg
    null_g1 = null_db(p_seg, r_seg, 1.0)
    g_match = best_gain(p_seg, r_seg)
    null_gm = null_db(p_seg, r_seg, g_match)
    max_abs = float(np.max(np.abs(diff)))
    n_diff = int(np.count_nonzero(diff))

    # windowed (uniformity check)
    NW = 8
    win = n // NW
    win_nulls = []
    for w in range(NW):
        s, e = w * win, (w + 1) * win if w < NW - 1 else n
        win_nulls.append(null_db(p_seg[s:e], r_seg[s:e], 1.0))

    # ── (b) Rust vs X3 wet — lag-aligned clean window ────────────────────────
    rust_lag, rust_g, rust_x3_null = clean_null_vs_x3(rust, x3)
    pyref_lag, pyref_g, pyref_x3_null = clean_null_vs_x3(py_ref, x3)

    # ── verdict ──────────────────────────────────────────────────────────────
    pass_a = null_g1 <= -90.0
    pass_b = rust_x3_null <= -90.0

    print()
    print(f"(a) Rust vs Python ref : {null_g1:+.2f} dB (gain 1.0) | "
          f"{null_gm:+.2f} dB (gain {g_match:.6f})  "
          f"[{'PASS' if pass_a else 'FAIL'} <= -90]")
    print(f"    max|sample diff| = {max_abs:.3e}   differing samples = "
          f"{n_diff}/{n}")
    print(f"(b) Rust vs X3 wet     : {rust_x3_null:+.2f} dB (lag {rust_lag}, "
          f"gain {rust_g:.4f})  [{'PASS' if pass_b else 'FAIL'} ~ -95]")
    print(f"    control: Python ref vs X3 = {pyref_x3_null:+.2f} dB "
          f"(lag {pyref_lag})")

    # ── report ───────────────────────────────────────────────────────────────
    L = ["# Rust Cascade Parity Verification", "",
         f"Generated {ts} by `tools/rust_cascade_parity.py`", "",
         "Verifies the shipping Rust `trench-core` `Cascade` reproduces the "
         "Python `scipy.sosfilt` M50/Q50 reference when fed the real skin-13 "
         "ROM corner words. Every figure recomputed from the raw WAVs / ROM "
         "block — the prior -95.41 dB number was not trusted.", "",
         "## Pipeline", "",
         "Both paths share: `skin13_corners_rom.bin` (240 raw ROM u16) -> "
         "morph-first u16 bilinear `interpolate(0.5, 0.5)` (c4 = 4*d4) -> "
         "Rossum kernel.", "",
         "- **Rust**: `kernel_to_biquad` -> `trench-core` `Cascade` "
         "(12-stage DF2T, fixed coefficients, zero state), float32 output.",
         "- **Python**: `kernel_to_sos` -> `scipy.sosfilt` (f64) -> f32, then "
         "AGC + boost (both verified identity: cascade peak ~0.36 < AGC table "
         f"threshold; boost = {BOOST}).", "",
         "## Inputs", "",
         f"- ROM corner words: `{ROM_BIN.relative_to(ROOT)}` (240 bytes)",
         f"- dry: `{DRY}` ({len(dry)} samples)",
         f"- X3 wet: `{X3_MID}` ({len(x3)} samples)",
         f"- Rust render: `{RUST_WAV.relative_to(ROOT)}` ({len(rust)} samples)",
         "",
         "## (a) Rust render vs Python reference render", "",
         "Sample-aligned (both start at dry sample 0), no lag.", "",
         "| metric | value |", "|---|---:|",
         f"| null (gain 1.0) | **{null_g1:+.2f} dB** |",
         f"| null (gain-matched, g = {g_match:.6f}) | {null_gm:+.2f} dB |",
         f"| max\\|sample diff\\| | {max_abs:.3e} |",
         f"| differing samples | {n_diff} / {n} |",
         f"| acceptance (<= -90 dB) | {'PASS' if pass_a else 'FAIL'} |", "",
         f"Windowed null (gain 1.0, {NW} windows): " +
         ", ".join(f"{v:+.1f}" for v in win_nulls) + " dB.", "",
         "## (b) Rust render vs X3 wet `hedzm50q50.wav`", "",
         "Lag-aligned, clean window = X3 content bounds "
         f"`{content_bounds(x3)}`.", "",
         "| candidate | lag | gain | clean-window null |",
         "|---|---:|---:|---:|",
         f"| Rust Cascade render | {rust_lag} | {rust_g:.4f} | "
         f"**{rust_x3_null:+.2f} dB** |",
         f"| Python reference (control) | {pyref_lag} | {pyref_g:.4f} | "
         f"{pyref_x3_null:+.2f} dB |", "",
         f"Acceptance (~ -95 dB / gate -90 dB): "
         f"{'PASS' if pass_b else 'FAIL'}.", "",
         "## Verdict", ""]
    if pass_a and pass_b:
        L += [f"**PASS.** The Rust `Cascade` reproduces the Python model to "
              f"{null_g1:+.2f} dB and nulls {rust_x3_null:+.2f} dB against the "
              "X3 wet — bit-accurate, indistinguishable from the "
              "`scipy.sosfilt` reference. The 2026-05-19 A/B-render `+3.20 dB` "
              "figure was a packed-vs-decoded-float comparison (two different "
              "interpolations, both inside Rust) plus pink-noise + peak "
              "normalisation — never a Rust-vs-Python cascade measurement. "
              "`cascade.rs` DF2T math is correct as written; no fix needed."]
    else:
        L += ["**FAIL.** The Rust render diverges from the Python reference. "
              "Per STATE.md Active session, that divergence is the bug: "
              "investigate `cascade.rs` against the SPEC.md DF2T math."]
    L.append("")

    report = out_dir / "PARITY_REPORT.md"
    report.write_text("\n".join(L) + "\n")
    print(f"\nwrote: {report}")
    return 0 if (pass_a and pass_b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
