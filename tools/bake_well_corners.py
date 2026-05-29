#!/usr/bin/env python3
"""bake_well_corners.py — compress the DESIGN and PHYSICS faucets into the Forge
wells. Each designed weapon and physics body is baked as a single-corner
compiled-v1 file (<name>.corner.json) that the Forge loads straight into a well —
no WAV, no fit. They land under corners_audio_only/_design and _physics so each
shows up as its own group in every well's dropdown, beside the fit (WAV) sources.

One shape (a corner), three faucets (fit / design / physics), four wells.
"""
import importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def L(n, r):
    s = importlib.util.spec_from_file_location(n, ROOT / r)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
pc = L("physical_corners", ".claude/skills/physical-corners/physical_corners.py")
w  = L("weapons", "tools/weapons.py")

BASE = ROOT / "dev/tmp/arma_source_pack/corners_audio_only"
LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]


def write_corner(folder, name, corner6):
    d = BASE / folder
    d.mkdir(parents=True, exist_ok=True)
    stages = [{"c0": s[0], "c1": s[1], "c2": s[2], "c3": s[3], "c4": s[4]} for s in corner6]
    kfs = [{"label": lab, "boost": 1.5, "stages": stages} for lab in LABELS]
    cart = {"format": "compiled-v1", "name": name, "sampleRate": pc.SR, "stages": 6, "keyframes": kfs}
    (d / f"{name}.corner.json").write_text(json.dumps(cart, indent=1))


def main():
    n = 0
    # DESIGN — the weapons palette (low_body, high_bite, speaker_knockerz, ...)
    for name, (specs, peak) in w.WEAPONS.items():
        write_corner("_design", name, w.corner(specs, peak, 1.0, 1.0)); n += 1
    # PHYSICS — vowels, pipes, bells
    for v in ["a", "e", "i", "o", "u", "ae"]:
        write_corner("_physics", f"vowel_{v}", pc.vowel_corner(v)); n += 1
    for cm in [11, 18, 30]:
        write_corner("_physics", f"tube_{cm}cm", pc.build_corner(pc.tube_modes(float(cm)))); n += 1
    for f0 in [180, 300]:
        write_corner("_physics", f"bell_{int(f0)}", pc.build_corner(pc.modal_modes("bell", float(f0)))); n += 1
    # ROM — verbatim reference banks, split into per-corner pickables (_rom group)
    rom_banks = {"talking_hedz": ROOT / "dev/bake/00_talking_hedz_compiled.json"}
    for bank, path in rom_banks.items():
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for kf in data.get("keyframes", []):
            corner6 = [[s["c0"], s["c1"], s["c2"], s["c3"], s["c4"]] for s in kf["stages"]]
            write_corner("_rom", f"{bank}_{kf['label']}", corner6); n += 1
    print(f"baked {n} corner files into {BASE}  (_design / _physics / _rom)")


if __name__ == "__main__":
    main()
