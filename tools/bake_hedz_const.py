"""Deprecated guard for the retired Talking Hedz float fixture.

Talking Hedz authority is now the packed P2K ROM bank:

    ref/presets/P2k_013_talking_hedz.bin

To refresh it from the installed EmulatorX.dll, run:

    python tools/extract_emulatorx_rom_filters.py

This guard remains so old handoffs fail loudly instead of recreating the
Q-collapsed MorphDesigner-derived Rust fixture and `hedz_golden.rs`.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
