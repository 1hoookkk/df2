"""Consolidate preset library — 8 gold frames + 4 shipping presets, one flat dir."""
import json, subprocess, sys, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"
LIB = ROOT / "preset_library"
LIB.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

# ── 8 gold frame templates from ROM_GOLD ──────────────────────────────────
GOLD = {3: "millennium", 4: "meaty_gizmo", 10: "ooh_to_eee",
        13: "talking_hedz", 18: "razor_blades", 22: "deep_bouche",
        29: "lucifer_s_q", 30: "tooth_comb"}
ROM = Path(r"C:\Users\hooki\surface-forge\out\foundry\ROM_GOLD")

for num, name in GOLD.items():
    body = ROM / f"P2k_{num:03d}_{name}.body240"
    if not body.exists(): continue

    # Decode to geometry
    geo = LIB / f"{name}.geometry.json"
    subprocess.run(
        [sys.executable, "-m", "tools.filter_cli", "decode", str(body), str(geo)],
        capture_output=True, text=True, timeout=15, cwd=ROOT,
    )
    # Clean name
    d = json.loads(geo.read_text())
    d["name"] = name
    geo.write_text(json.dumps(d, indent=1))

    # Compile to body240
    packed = LIB / f"{name}.body240"
    subprocess.run(
        [str(COMPILER), str(geo), str(packed)],
        capture_output=True, text=True, timeout=15,
    )
    ok = "OK" if packed.exists() else "FAIL"
    print(f"  {name}: {ok}")

# ── 4 shipping presets from the build output ──────────────────────────────
SHIP = ROOT / "shipping_presets" / "bodies"
if SHIP.exists():
    for fp in SHIP.glob("*.body240"):
        if "compiled" in fp.name or "verify" in fp.name:
            continue
        dest = LIB / fp.name
        shutil.copy2(fp, dest)
        print(f"  {fp.stem}: copied body240")

    for fp in SHIP.glob("*.geometry.json"):
        if "compiled" in fp.name or "verify" in fp.name:
            continue
        dest = LIB / fp.name
        shutil.copy2(fp, dest)
        print(f"  {fp.stem}: copied geometry")

# ── Index ─────────────────────────────────────────────────────────────────
entries = {}
for geo in sorted(LIB.glob("*.geometry.json")):
    name = geo.stem
    body_path = LIB / f"{name}.body240"
    entries[name] = {
        "has_body": body_path.exists(),
        "geometry_size": geo.stat().st_size,
        "body_size": body_path.stat().st_size if body_path.exists() else 0,
    }

md = ["# Preset Library\n"]
for name, info in sorted(entries.items()):
    kind = "frame" if any(name == g for g in GOLD.values()) else "voice"
    md.append(f"- **{name}** ({kind}) — geometry + body240" if info["has_body"] else f"- **{name}** ({kind}) — geometry only")

(LIB / "index.md").write_text("\n".join(md) + "\n")

# Clean up shipping_presets
shutil.rmtree(ROOT / "shipping_presets", ignore_errors=True)

print(f"\nClean library: {LIB}")
print(f"  {len(entries)} presets ({len([e for e in entries.values() if e['has_body']])} with body240)")
