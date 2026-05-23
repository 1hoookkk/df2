#!/usr/bin/env python3
"""locate_corners_in_dump.py — find the 4 corner u16 banks inside a raw
memory-region dump by decoding every 2-byte-aligned offset and matching the
decoded kernel coefficients against the known Talking Hedz corner grids.

Also locates the decoded-float coefficient buffer(s) (the +0x540 region) by
matching the M0_Q0 float32 grid, so the true object base can be recovered.

Offline analysis only. No cartridge asset / format / topology change.

Usage:
    python tools/locate_corners_in_dump.py dev/tmp/cheat_engine_dump/skin13_region_full.bin
    python tools/locate_corners_in_dump.py <dump> --region-base 0x00AEE000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.coefficient_field_bakeoff import load_corner_coeffs, words_to_kernel

CARTRIDGE = ROOT / "ref" / "p2k_skins" / "00_talking_hedz.json"
CORNERS = ["A", "B", "C", "D"]
LABELS = {"A": "M0_Q0", "B": "M100_Q0", "C": "M0_Q100", "D": "M100_Q100"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", type=Path)
    ap.add_argument("--region-base", default="0x00AEE000",
                    help="absolute address the dump starts at (for offset math)")
    ap.add_argument("--cartridge", type=Path, default=CARTRIDGE)
    args = ap.parse_args()

    base = int(args.region_base, 16)
    raw = args.dump.read_bytes()
    print(f"dump: {args.dump}  ({len(raw)} bytes, region base {hex(base)})")

    corner_coeffs, _ = load_corner_coeffs(args.cartridge)  # dict -> [6,5] kernel
    u16 = np.frombuffer(raw, dtype="<u2")
    f32 = np.frombuffer(raw, dtype="<f4")

    # ── locate corner A by decoding 30 u16 at every even byte offset ─────────
    expectA = corner_coeffs["A"]  # [6,5]
    n_words = len(u16)
    best = []  # (score, word_index)
    for wi in range(0, n_words - 30):
        words = u16[wi:wi + 30].reshape(6, 5)
        kern = words_to_kernel(words)
        score = float(np.max(np.abs(kern - expectA)))
        best.append((score, wi))
    best.sort()
    print("\n# Best corner-A matches (decode 30 u16 -> kernel vs M0_Q0 grid):")
    for score, wi in best[:5]:
        print(f"  byte offset {wi*2:#08x}  abs addr {hex(base + wi*2)}  "
              f"max|Δ| = {score:.6f}")

    score_a, wi_a = best[0]
    if score_a > 0.05:
        print(f"\n!! no clean corner-A match (best max|Δ|={score_a:.4f}). "
              "Layout/region may be wrong.")
    byte_a = wi_a * 2

    # ── verify B/C/D follow at +60 bytes each ───────────────────────────────
    print(f"\n# Assuming corner A at byte {byte_a:#08x} "
          f"(abs {hex(base + byte_a)}):")
    all_ok = True
    for i, c in enumerate(CORNERS):
        wi = wi_a + i * 30
        words = u16[wi:wi + 30].reshape(6, 5)
        kern = words_to_kernel(words)
        d = float(np.max(np.abs(kern - corner_coeffs[c])))
        ok = d < 0.05
        all_ok &= ok
        print(f"  {c} ({LABELS[c]}): abs {hex(base + wi*2)}  "
              f"max|Δ| vs grid = {d:.6f}  {'OK' if ok else 'MISMATCH'}")

    if all_ok:
        obj_2c0 = base + byte_a
        print(f"\n=> all 4 corners matched. Corner block (object+0x2C0) "
              f"starts at {hex(obj_2c0)}.")
        print(f"=> object base = {hex(obj_2c0 - 0x2C0)}")
        print(f"=> dump 240 bytes from {hex(obj_2c0)} for skin13_corners.bin,")
        print(f"   or carve it from this region dump directly:")
        out = args.dump.parent / "skin13_corners_carved.bin"
        out.write_bytes(raw[byte_a:byte_a + 240])
        print(f"   carved -> {out}")
    else:
        print("\n!! corners not contiguous at +60 — re-check layout.")

    # ── cross-check: locate the M0_Q0 float coefficient grid ────────────────
    expA_flat = corner_coeffs["A"].reshape(-1)  # 30 floats
    fbest = []
    for fi in range(0, len(f32) - 30):
        seg = f32[fi:fi + 30]
        if not np.all(np.isfinite(seg)):
            continue
        fbest.append((float(np.max(np.abs(seg - expA_flat))), fi))
    fbest.sort()
    print("\n# Best decoded-float coefficient-buffer matches (M0_Q0 grid):")
    for score, fi in fbest[:5]:
        print(f"  byte offset {fi*4:#08x}  abs addr {hex(base + fi*4)}  "
              f"max|Δ| = {score:.6f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
