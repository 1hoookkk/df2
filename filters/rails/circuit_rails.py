#!/usr/bin/env python3
"""Circuit well FRFs -> pole/zero rails (FuzziFace archetype evidence).

Thin front-end over the shared dvtd fit core (see frf_rails_common / dvtd_rails).
Input:  data/circuit/*.json   (from tools/circuit_frf.py — provenance in its MANIFEST)
Output: out/circuit_rails/{circuit_rails.json, contact_sheet.png, plots/}
Run: python tools/circuit_rails.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frf_rails_common import run_well

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    run_well("circuit", ROOT / "data" / "circuit", ROOT / "out" / "circuit_rails")
