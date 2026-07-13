#!/usr/bin/env python3
"""Modal well FRFs -> pole/zero rails (LucifersQ + Meaty Gizmo archetype evidence).

Thin front-end over the shared dvtd fit core (see frf_rails_common / dvtd_rails).
Input:  data/modal/*.json   (from tools/modal_frf.py — provenance in its MANIFEST)
Output: out/modal_rails/{modal_rails.json, contact_sheet.png, plots/}
Run: python tools/modal_rails.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frf_rails_common import run_well

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    run_well("modal", ROOT / "data" / "modal", ROOT / "out" / "modal_rails")
