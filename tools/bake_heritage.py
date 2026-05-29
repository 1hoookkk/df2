#!/usr/bin/env python3
"""bake_heritage.py — compile the E-mu MorphDesigner heritage XML presets
(ref/heritage/*.xml) into per-corner .corner.json for the Forge wells.

Each preset is a designed 2-frame morph (M0 <-> M100) — a KIN pair with a real
musical middle. Uses the backward-looking Compiler (pyruntime/designer_compile);
the baked corners are raw data for the wells, not a textbook to derive from.

Caveat: heritage coeffs are firmware-44.1k-domain; played at the 39062.5 author
rate they sit ~2 semitones low. Fine for prospecting; recompile if it matters.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pyruntime.designer_compile import parse_xml, compile_designer  # noqa: E402

HERITAGE = ROOT / "ref" / "heritage"
OUT = ROOT / "dev/tmp/arma_source_pack/corners_audio_only/_heritage"
SR = 39062.5
LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]


def slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


def to6(corner_state):
    return [[e.c0, e.c1, e.c2, e.c3, e.c4] for e in corner_state.encode()]


def write_corner(folder: Path, name, corner6):
    folder.mkdir(parents=True, exist_ok=True)
    stages = [{"c0": s[0], "c1": s[1], "c2": s[2], "c3": s[3], "c4": s[4]} for s in corner6]
    kfs = [{"label": lab, "boost": 1.5, "stages": stages} for lab in LABELS]
    cart = {"format": "compiled-v1", "name": name, "sampleRate": SR, "stages": 6, "keyframes": kfs}
    (folder / f"{name}.corner.json").write_text(json.dumps(cart, indent=1))


def main():
    import shutil
    if OUT.exists():
        shutil.rmtree(OUT)  # clear old flat files so the menu tree is clean
    xmls = sorted(HERITAGE.glob("*.xml"))
    n, skipped = 0, []
    for xml in xmls:
        try:
            arr = compile_designer(parse_xml(str(xml)))
            folder = OUT / xml.stem  # one readable folder per preset -> a submenu
            write_corner(folder, "M0", to6(arr._corners[0])); n += 1
            write_corner(folder, "M100", to6(arr._corners[2])); n += 1
        except Exception as e:
            skipped.append((xml.name, str(e)))
    print(f"baked {n} heritage corners from {len(xmls)} presets -> {OUT}")
    for nm, e in skipped:
        print(f"  skipped {nm}: {e}")


if __name__ == "__main__":
    main()
