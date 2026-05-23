#!/usr/bin/env python3
"""rom_words_compare.py — compare a Cheat Engine ROM-word dump against the
derived-packed corner words, and re-null the M50/Q50 midpoint vs the X3 wet.

Input: a raw 240-byte dump of CPhantomRTFilter object+0x2C0 — 4 corners
(A=M0_Q0, B=M100_Q0, C=M0_Q100, D=M100_Q100), each 30 u16 little-endian,
stage-major (6 stages x 5 words). See dev/tmp/cheat_engine_dump/CHECKLIST.md.

Offline analysis only. Does not modify cartridge assets, cartridge format,
cascade topology, or the default interpolation path. The dumped words are
treated as reference-only; nothing is promoted into ref/ or a cartridge.

Usage:
    python tools/rom_words_compare.py <dump.bin>
    python tools/rom_words_compare.py <dump.bin> --x3 path.wav --dry path.wav
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.coefficient_field_bakeoff import (
    load_corner_coeffs, kernel_to_words, packed_oracle, words_to_kernel,
)
from tools.verified_packed_audit import (
    load_mono, render, find_lag, refine_lag, content_bounds,
    null_db, best_gain, CARTRIDGE, DRY, X3_MID, SR,
)

CORNERS = [("A", "M0_Q0"), ("B", "M100_Q0"), ("C", "M0_Q100"), ("D", "M100_Q100")]
OUT_ROOT = ROOT / "dev" / "tmp" / "cheat_engine_dump"


def parse_dump(path: Path) -> dict[str, np.ndarray]:
    """240-byte raw dump -> {A,B,C,D: uint16[6,5]}."""
    raw = path.read_bytes()
    if len(raw) < 240:
        raise SystemExit(f"dump is {len(raw)} bytes; need >= 240")
    if len(raw) > 240:
        print(f"note: dump is {len(raw)} bytes; using first 240")
    words = np.frombuffer(raw[:240], dtype="<u2").reshape(4, 6, 5)
    return {letter: words[i].astype(np.uint16) for i, (letter, _) in enumerate(CORNERS)}


def clean_null(cand_render: np.ndarray, x3: np.ndarray) -> tuple[int, float]:
    """Lag-align (verified convention: x3[n] <-> cand[n-lag]) and null over
    the X3 content region. Returns (lag, clean_null_db)."""
    cs, ce = content_bounds(x3)
    coarse = find_lag(x3, cand_render)
    lag, _ = refine_lag(x3, cand_render, cs, ce, coarse)
    r = x3[cs:ce]
    c = cand_render[cs - lag:ce - lag]
    m = min(len(r), len(c))
    r, c = r[:m], c[:m]
    return lag, null_db(r, c, best_gain(r, c))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", type=Path, help="raw 240-byte object+0x2C0 dump")
    ap.add_argument("--x3", type=Path, default=X3_MID)
    ap.add_argument("--dry", type=Path, default=DRY)
    ap.add_argument("--cartridge", type=Path, default=CARTRIDGE)
    args = ap.parse_args()

    rom = parse_dump(args.dump)
    corner_coeffs, cartridge = load_corner_coeffs(args.cartridge)
    boost = float(cartridge["keyframes"][0].get("boost", 1.0))
    derived = {k: kernel_to_words(v) for k, v in corner_coeffs.items()}

    lines = ["# ROM-word vs derived-packed comparison", "",
             f"Generated: {datetime.now():%Y%m%d_%H%M%S}",
             f"Dump: `{args.dump}` ({args.dump.stat().st_size} bytes)", ""]

    # ── per-corner word + coefficient deltas ─────────────────────────────────
    lines += ["## Corner word deltas (ROM - derived-packed)", "",
              "| corner | words differing | max |Δ word| (LSB) | max |Δ c0..c4| |",
              "|---|---:|---:|---:|"]
    for letter, label in CORNERS:
        rw = rom[letter].astype(np.int64)
        dw = derived[letter].astype(np.int64)
        dword = rw - dw
        n_diff = int(np.count_nonzero(dword))
        max_lsb = int(np.max(np.abs(dword)))
        rk = words_to_kernel(rom[letter])
        dk = words_to_kernel(derived[letter])
        max_dc = float(np.max(np.abs(rk - dk)))
        lines.append(f"| {label} | {n_diff}/30 | {max_lsb} | {max_dc:.6f} |")
        print(f"{label:10} words differ {n_diff}/30  max LSB {max_lsb}  max Δc {max_dc:.6f}")

    # ── M50/Q50 render + null vs X3 ──────────────────────────────────────────
    dry = load_mono(args.dry)
    x3 = load_mono(args.x3)

    rom_mid = packed_oracle(rom, 0.5, 0.5)
    der_mid = packed_oracle(derived, 0.5, 0.5)
    rom_lag, rom_null = clean_null(
        render(dry, rom_mid, "agc_boost", boost).astype(np.float64), x3)
    der_lag, der_null = clean_null(
        render(dry, der_mid, "agc_boost", boost).astype(np.float64), x3)

    lines += ["", "## M50/Q50 clean-window null vs X3 wet", "",
              "| midpoint corners | lag | clean null | gate -60 dB |",
              "|---|---:|---:|---|",
              f"| derived-packed | {der_lag} | {der_null:+.2f} dB | "
              f"{'PASS' if der_null <= -60 else 'fail'} |",
              f"| ROM dump | {rom_lag} | {rom_null:+.2f} dB | "
              f"{'PASS' if rom_null <= -60 else 'fail'} |", "",
              f"ROM words move the midpoint null by "
              f"**{rom_null - der_null:+.2f} dB** vs derived-packed."]
    print(f"\nderived-packed M50/Q50 clean null: {der_null:+.2f} dB")
    print(f"ROM-dump      M50/Q50 clean null: {rom_null:+.2f} dB")
    print(f"delta: {rom_null - der_null:+.2f} dB")

    out = OUT_ROOT / f"rom_words_compare_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"\nwrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
