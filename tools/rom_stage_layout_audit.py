#!/usr/bin/env python3
"""rom_stage_layout_audit.py — read-only inspection of E-mu's actual
stage layout across the 4 ROM corners of skin 13 (Talking Hedz).

Question being answered: does stage index i mean the same thing
(same frequency band / role) in every corner, or are the indices
scrambled across corners?

No fitting, no authoring, no modelling assumption. Decode the captured
240-byte ROM block, convert each stage's kernel coefficients to a pole
(frequency, Q, peak gain), and print one table per corner plus a
cross-corner side-by-side view at every stage index.

Offline analysis only. ROM data is reference-only.

Usage:
    python tools/rom_stage_layout_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.rom_corner_audit import CORNERS, words_to_kernel_c4x4  # noqa: E402

ROM_BIN = ROOT / "dev" / "tmp" / "cheat_engine_dump" / "skin13_corners_rom.bin"
SR = 44100.0  # the ROM dump was captured at 44100 Hz (Cheat Engine, X3 VST)


def stage_pole(kernel_row: np.ndarray) -> tuple[float, float, float, float, float]:
    """Kernel-form (c0..c4) -> (pole_freq_Hz, pole_radius, Q, peak_db, dc_db).

    pole_freq_Hz is NaN for a real-pole-pair stage (no resonance peak).
    Q follows the standard digital-biquad Q = -theta / (2 ln r). For real
    poles Q is reported as NaN.
    peak_db is the maximum magnitude of the stage response across 20 Hz
    .. SR/2 in dB. dc_db is the response at DC, for context.
    """
    c0, c1, c2, c3, c4 = (float(x) for x in kernel_row)
    a1 = c2 - 2.0
    a2 = 1.0 - c3

    # pole: z^2 + a1 z + a2 = 0 -> z = (-a1 +/- sqrt(a1^2 - 4 a2)) / 2
    disc = a1 * a1 - 4.0 * a2
    if disc < 0:
        # complex-conjugate pole pair
        r = float(np.sqrt(max(a2, 0.0)))
        cos_theta = -a1 / (2.0 * r) if r > 0 else 0.0
        cos_theta = float(np.clip(cos_theta, -1.0, 1.0))
        theta = float(np.arccos(cos_theta))
        f_hz = theta * SR / (2.0 * np.pi)
        ln_r = np.log(max(r, 1e-12))
        q = float(-theta / (2.0 * ln_r)) if ln_r < 0 else float("nan")
    else:
        # real pole pair: no resonance peak
        r = float(max(abs((-a1 + np.sqrt(disc)) / 2.0),
                      abs((-a1 - np.sqrt(disc)) / 2.0)))
        f_hz = float("nan")
        q = float("nan")

    # magnitude sweep for peak/DC dB
    freqs = np.logspace(np.log10(20.0), np.log10(SR * 0.499), 4096)
    z_inv = np.exp(-1j * 2.0 * np.pi * freqs / SR)
    z_inv2 = z_inv * z_inv
    b0 = c4
    b1 = (c0 - 2.0) * c4
    b2 = (1.0 - c1) * c4
    num = b0 + b1 * z_inv + b2 * z_inv2
    den = 1.0 + a1 * z_inv + a2 * z_inv2
    mag = np.abs(num / den)
    peak_db = float(20.0 * np.log10(max(mag.max(), 1e-12)))
    # DC: z^-1 = 1
    dc_h = (b0 + b1 + b2) / (1.0 + a1 + a2)
    dc_db = float(20.0 * np.log10(max(abs(dc_h), 1e-12)))
    return f_hz, r, q, peak_db, dc_db


def fmt_hz(hz: float) -> str:
    if not np.isfinite(hz):
        return "  --real--"
    if hz < 1000:
        return f"{hz:8.1f} Hz"
    return f"{hz/1000:8.3f} kHz"


def fmt_q(q: float) -> str:
    if not np.isfinite(q):
        return "    -- "
    return f"{q:7.2f}"


def main() -> int:
    if not ROM_BIN.exists():
        print(f"!! {ROM_BIN} not found")
        return 1
    raw = ROM_BIN.read_bytes()
    assert len(raw) == 240, len(raw)
    u16 = np.frombuffer(raw, dtype="<u2")
    corners = {
        letter: u16[i * 30:(i + 1) * 30].reshape(6, 5).astype(np.uint16)
        for i, (letter, _) in enumerate(CORNERS)
    }
    kernels = {k: words_to_kernel_c4x4(v) for k, v in corners.items()}

    # per-stage analysis per corner
    table: dict[str, list[tuple]] = {}
    for letter, label in CORNERS:
        table[letter] = []
        for s in range(6):
            f, r, q, peak, dc = stage_pole(kernels[letter][s])
            table[letter].append((s, f, r, q, peak, dc))

    # ── per-corner: index order (as stored in ROM, what morph pairs together) ──
    print("=" * 78)
    print("STAGE LAYOUT — INDEX ORDER (this is the order the morph pairs across)")
    print("=" * 78)
    for letter, label in CORNERS:
        print(f"\n{label}  (corner {letter})")
        print("  stage |  pole f       | radius r |   Q     | peak dB | DC dB")
        print("  ------+---------------+----------+---------+---------+--------")
        for s, f, r, q, peak, dc in table[letter]:
            print(f"    {s}   | {fmt_hz(f)}  |  {r:6.4f}  | {fmt_q(q)} | "
                  f"{peak:+6.1f}  | {dc:+6.1f}")

    # ── cross-corner: for each stage index, show all 4 corners side by side ──
    print()
    print("=" * 78)
    print("CROSS-CORNER VIEW — stage index i across the 4 corners")
    print("=" * 78)
    print("  If E-mu used the same actor at each index, the columns track.")
    print("  If they're scrambled, the columns jump unrelatedly.\n")
    print(f"  {'stage':<5} | {'M0_Q0':^14} | {'M100_Q0':^14} | "
          f"{'M0_Q100':^14} | {'M100_Q100':^14}")
    print("  ------+----------------+----------------+----------------+-----------------")
    for s in range(6):
        cells = []
        for letter, _label in CORNERS:
            _, f, _, q, _, _ = table[letter][s]
            cells.append(f"{fmt_hz(f):>9} Q{fmt_q(q).strip():>3}")
        print(f"    {s}   | {cells[0]:<14} | {cells[1]:<14} | "
              f"{cells[2]:<14} | {cells[3]:<14}")

    # ── if we sorted each corner by pole frequency, what would the order be? ──
    print()
    print("=" * 78)
    print("FREQUENCY-SORTED VIEW — each corner sorted ascending by pole f")
    print("=" * 78)
    print("  Compare against the index-order view above. If they match, the ROM")
    print("  stage indices were already in frequency order. If they differ, E-mu")
    print("  did NOT assign stages by frequency band.\n")
    print(f"  {'rank':<5} | {'M0_Q0':^14} | {'M100_Q0':^14} | "
          f"{'M0_Q100':^14} | {'M100_Q100':^14}")
    print("  ------+----------------+----------------+----------------+-----------------")
    sorted_idx: dict[str, list[int]] = {}
    for letter, _ in CORNERS:
        rows = table[letter]
        # NaN (real-pole) sorts last
        order = sorted(range(6), key=lambda i: (not np.isfinite(rows[i][1]),
                                                 rows[i][1] if np.isfinite(rows[i][1])
                                                            else 0.0))
        sorted_idx[letter] = order
    for rank in range(6):
        cells = []
        idx_cells = []
        for letter, _ in CORNERS:
            si = sorted_idx[letter][rank]
            _, f, _, q, _, _ = table[letter][si]
            cells.append(f"{fmt_hz(f):>9} Q{fmt_q(q).strip():>3}")
            idx_cells.append(si)
        print(f"    {rank}   | {cells[0]:<14} | {cells[1]:<14} | "
              f"{cells[2]:<14} | {cells[3]:<14}    "
              f"(from indices {idx_cells})")

    # ── permutation diagnostic: which ROM stage index lands at each freq rank? ──
    print()
    print("=" * 78)
    print("PERMUTATION DIAGNOSTIC")
    print("=" * 78)
    print("  For each corner, the ROM stage index at each frequency rank.")
    print("  If all 4 rows are [0,1,2,3,4,5], E-mu used frequency-sorted indexing.")
    print("  If they differ, the morph pairs different-frequency stages together.\n")
    for letter, label in CORNERS:
        print(f"    {label:<10}  index order: {sorted_idx[letter]}")
    all_same = all(sorted_idx[letter] == sorted_idx["A"]
                   for letter, _ in CORNERS)
    identity = list(range(6))
    a_is_identity = sorted_idx["A"] == identity
    print()
    if all_same and a_is_identity:
        print("  -> All 4 corners share the SAME stage-to-frequency mapping AND")
        print("     E-mu stored them in ascending frequency order.")
        print("     The morph pairs frequency-aligned stages. \"Banded slots\" is")
        print("     compatible with the data.")
    elif all_same and not a_is_identity:
        print(f"  -> All 4 corners share the SAME stage-to-frequency mapping,")
        print(f"     but E-mu did NOT use ascending frequency order ({sorted_idx['A']}).")
        print(f"     The morph still pairs the same actors; banded slots is")
        print(f"     compatible if we permute the bands accordingly.")
    else:
        print("  -> Corners DISAGREE on which stage index sits at each frequency rank.")
        print("     The morph pairs stages whose frequencies do NOT line up.")
        print("     \"Same actor per index\" is NOT how E-mu authored this.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
