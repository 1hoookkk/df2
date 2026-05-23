#!/usr/bin/env python3
"""rom_corner_audit.py — audit the real skin-13 ROM corner words against the
derived-packed words, using the corrected c4 recombination.

Discovery (2026-05-19): the engine's word->coeff recombination is
    c0 = 4*d0 + d1   c1 = d1   c2 = 4*d2 + d3   c3 = d3   c4 = 4*d4
The df2 packed model used c4 = d4 (scale 1.0). The real scale is 4.0
(the constant FUN_1802c0150 writes to this+0x2a8). The derived-packed path
round-trips clean (encode/decode inverse) so it never exposed this; real
ROM words do.

Locates the 4 corner u16 banks in a full region dump, decodes them with the
corrected recombination, compares to the derived-packed words, and renders /
nulls the M50/Q50 midpoint vs the X3 wet.

Offline analysis only. No cartridge asset / format / topology / default-path
change. ROM words are reference-only.

Usage:
    python tools/rom_corner_audit.py dev/tmp/cheat_engine_dump/skin13_region_full.bin
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

from tools.coefficient_field_bakeoff import load_corner_coeffs, kernel_to_words
from tools.verified_packed_audit import (
    load_mono, render, find_lag, refine_lag, content_bounds,
    null_db, best_gain, CARTRIDGE, DRY, X3_MID,
)
from pyruntime.packed_interp import decode, lerp_u16

CORNERS = [("A", "M0_Q0"), ("B", "M100_Q0"), ("C", "M0_Q100"), ("D", "M100_Q100")]
OUT = ROOT / "dev" / "tmp" / "cheat_engine_dump"
DECODE_LUT = np.array([decode(w) for w in range(65536)], dtype=np.float64)


def words_to_kernel_c4x4(words: np.ndarray) -> np.ndarray:
    """Corrected recombination: c4 = 4*d4 (engine scale, verified from ROM)."""
    d = DECODE_LUT[words.astype(np.uint16)]
    out = np.empty(d.shape, dtype=np.float64)
    out[..., 0] = 4.0 * d[..., 0] + d[..., 1]
    out[..., 1] = d[..., 1]
    out[..., 2] = 4.0 * d[..., 2] + d[..., 3]
    out[..., 3] = d[..., 3]
    out[..., 4] = 4.0 * d[..., 4]
    return out


def locate_corner_a(u16: np.ndarray, grid_a: np.ndarray) -> tuple[int, float]:
    best = (0, 1e9)
    for wi in range(0, len(u16) - 30):
        k = words_to_kernel_c4x4(u16[wi:wi + 30].reshape(6, 5))
        s = float(np.max(np.abs(k - grid_a)))
        if s < best[1]:
            best = (wi, s)
    return best


def interp_rom(corner_words: dict[str, np.ndarray], morph: float, q: float) -> np.ndarray:
    """Morph-first u16 bilinear (= FUN_1802c3d40), then corrected decode."""
    out = np.empty((6, 5), dtype=np.uint16)
    for s in range(6):
        for w in range(5):
            ab = lerp_u16(int(corner_words["A"][s, w]), int(corner_words["B"][s, w]), morph)
            cd = lerp_u16(int(corner_words["C"][s, w]), int(corner_words["D"][s, w]), morph)
            out[s, w] = lerp_u16(ab, cd, q)
    return words_to_kernel_c4x4(out)


def clean_null(cand: np.ndarray, x3: np.ndarray) -> tuple[int, float]:
    cs, ce = content_bounds(x3)
    coarse = find_lag(x3, cand)
    lag, _ = refine_lag(x3, cand, cs, ce, coarse)
    r, c = x3[cs:ce], cand[cs - lag:ce - lag]
    m = min(len(r), len(c))
    r, c = r[:m], c[:m]
    return lag, null_db(r, c, best_gain(r, c))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", type=Path, help="full region dump (.bin)")
    ap.add_argument("--region-base", default="0x00AEE000")
    args = ap.parse_args()

    raw = args.dump.read_bytes()
    u16 = np.frombuffer(raw, dtype="<u2")
    base = int(args.region_base, 16)
    corner_coeffs, cartridge = load_corner_coeffs(CARTRIDGE)
    boost = float(cartridge["keyframes"][0].get("boost", 1.0))

    wi_a, score = locate_corner_a(u16, corner_coeffs["A"])
    byte_a = wi_a * 2
    print(f"corner A located at dump offset {byte_a:#06x} "
          f"(abs {hex(base + byte_a)}), max|Δ| = {score:.6f}")
    if score > 0.02:
        print("!! weak match — aborting")
        return 1

    # carve 4 corners (240 bytes contiguous) and verify each with corrected decode
    rom = {}
    print("\n# Corner verification (corrected c4=4*d4 decode):")
    lines = ["# Skin-13 ROM corner audit", "",
             f"Generated {datetime.now():%Y%m%d_%H%M%S}",
             f"Dump: `{args.dump}`  corner block at {hex(base + byte_a)}",
             "Recombination: c0=4d0+d1, c1=d1, c2=4d2+d3, c3=d3, **c4=4d4**", "",
             "## Corner verification vs P2K JSON grid", "",
             "| corner | max|Δ| decoded vs JSON |", "|---|---:|"]
    ok = True
    for i, (letter, label) in enumerate(CORNERS):
        words = u16[wi_a + i * 30: wi_a + (i + 1) * 30].reshape(6, 5).astype(np.uint16)
        rom[letter] = words
        k = words_to_kernel_c4x4(words)
        d = float(np.max(np.abs(k - corner_coeffs[letter])))
        ok &= d < 0.02
        print(f"  {label:10} max|Δ| = {d:.6f}  {'OK' if d < 0.02 else 'MISMATCH'}")
        lines.append(f"| {label} | {d:.6f} |")

    if not ok:
        print("\n!! a corner did not verify — stopping before the null test")
        return 1

    # save the carved 240-byte corner block
    carved = OUT / "skin13_corners_rom.bin"
    carved.write_bytes(raw[byte_a:byte_a + 240])
    print(f"\ncarved real ROM corner block -> {carved}")

    # ── ROM words vs derived-packed words ────────────────────────────────────
    derived = {k: kernel_to_words(v) for k, v in corner_coeffs.items()}
    lines += ["", "## ROM words vs derived-packed words", "",
              "| corner | words differing | max |Δ word| (LSB) |", "|---|---:|---:|"]
    for letter, label in CORNERS:
        dword = rom[letter].astype(np.int64) - derived[letter].astype(np.int64)
        lines.append(f"| {label} | {int(np.count_nonzero(dword))}/30 | "
                     f"{int(np.max(np.abs(dword)))} |")

    # ── M50/Q50 null vs X3 ───────────────────────────────────────────────────
    dry = load_mono(DRY)
    x3 = load_mono(X3_MID)
    rom_mid = interp_rom(rom, 0.5, 0.5)
    rom_lag, rom_null = clean_null(
        render(dry, rom_mid, "agc_boost", boost).astype(np.float64), x3)
    print(f"\nROM-word M50/Q50 clean null vs X3: {rom_null:+.2f} dB  (lag {rom_lag})")
    lines += ["", "## M50/Q50 clean-window null vs X3 wet", "",
              f"- ROM words + morph-first u16 lerp + corrected decode: "
              f"**{rom_null:+.2f} dB**",
              f"- prior derived-packed (c4=d4 roundtrip): -53.75 dB",
              f"- gate: -60 dB ({'PASS' if rom_null <= -60 else 'still short'})"]

    out_md = OUT / f"rom_corner_audit_{datetime.now():%Y%m%d_%H%M%S}.md"
    out_md.write_text("\n".join(lines) + "\n")
    print(f"wrote: {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
