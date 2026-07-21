"""Derive 8 gold-type templates from actual ROM_GOLD body240 files.
Then create compile-ready template recipes with frame/voice annotation."""
import json, shutil, subprocess, sys, math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

ROM = Path(r"C:\Users\hooki\surface-forge\out\foundry\ROM_GOLD")
OUT = ROOT / "preset_library" / "gold_templates"
OUT.mkdir(parents=True, exist_ok=True)
TMP = ROOT / "preset_library" / "gold_source"
TMP.mkdir(parents=True, exist_ok=True)

GOLD_NAMES = {
    3: "millennium", 4: "meaty_gizmo", 10: "ooh_to_eee",
    13: "talking_hedz", 18: "razor_blades", 22: "deep_bouche",
    29: "lucifer_s_q", 30: "tooth_comb",
}

def stage_role(stage):
    pr = stage.get("pole_r", 0)
    ph = stage.get("pole_hz", 0)
    zr = stage.get("zero_r", 0)
    if pr > 0.85:
        if ph >= 6000: return "air"
        if ph <= 500: return "body"
        return "voice"
    if zr > 0.95: return "notch"
    return "other"

# Decode each ROM_GOLD body to geometry
templates = []
for num, name in GOLD_NAMES.items():
    body_path = ROM / f"P2k_{num:03d}_{name}.body240"
    if not body_path.exists():
        print(f"  SKIP: {body_path}")
        continue
    
    # Decode via filter_cli
    geo_path = TMP / f"P2k_{num:03d}_{name}.geometry.json"
    r = subprocess.run(
        [sys.executable, "-m", "tools.filter_cli", "decode", str(body_path), str(geo_path)],
        capture_output=True, text=True, timeout=30, cwd=ROOT,
    )
    if not geo_path.exists():
        print(f"  FAIL decode: {name} — {r.stderr[:120]}")
        continue
    
    d = json.loads(geo_path.read_text())
    d["name"] = name  # clean name
    corners = d["corners"]
    
    # Classify stages
    stage_info = []
    for si in range(6):
        ref = corners[0][si]
        role = stage_role(ref)
        ph = ref.get("pole_hz", 0)
        pr = ref.get("pole_r", 0)
        zh = ref.get("zero_hz", 0)
        zr = ref.get("zero_r", 0)
        stage_info.append({
            "stage": si, "role": role,
            "pole_hz": ph, "pole_r": pr,
            "zero_hz": zh, "zero_r": zr,
        })
    
    frame = [s for s in stage_info if s["role"] in ("air", "body")]
    voice = [s for s in stage_info if s["role"] == "voice"]
    
    # Save the clean geometry as the template
    tpl_path = OUT / f"{name}.geometry.json"
    with open(tpl_path, "w") as f:
        json.dump(d, f, indent=1)
    
    templates.append({
        "name": name,
        "stage_info": stage_info,
        "frame_stages": [s["stage"] for s in frame],
        "voice_stages": [s["stage"] for s in voice],
        "frame_desc": ", ".join(f"S{s['stage']}({s['role']}@{s['pole_hz']:.0f}Hz)" for s in frame),
        "voice_desc": ", ".join(f"S{s['stage']}({s['pole_hz']:.0f}Hz)" for s in voice),
    })
    print(f"  {name}: frame=[{templates[-1]['frame_desc']}]  voice=[{templates[-1]['voice_desc']}]")

# Verify each template compiles
print("\nVerifying templates compile...")
for t in templates:
    tpl_path = OUT / f"{t['name']}.geometry.json"
    packed = OUT / f"{t['name']}.body240"
    r = subprocess.run(
        [str(ROOT / "target" / "release" / "body-from-geometry.exe"),
         str(tpl_path), str(packed)],
        capture_output=True, text=True, timeout=30,
    )
    status = "PASS" if r.returncode == 0 and packed.exists() else "FAIL"
    output = (r.stdout or r.stderr or "").strip()
    max_pr = "?"
    for line in output.split("\n"):
        if "max pole radius" in line.lower():
            try: max_pr = f"{float(line.strip().split()[-1]):.4f}"
            except: pass
    print(f"  {t['name']}: {status} max_pole_r={max_pr}")

# Write index
md = [
    "# P2K Gold-Type Templates",
    f"\n{len(templates)} templates from real ROM_GOLD body240 files.",
    "Decoded via filter_cli decode, compile-ready.",
    "",
    "| Template | Frame (keep) | Voice (swap) |",
    "|----------|-------------|--------------|",
]
for t in templates:
    md.append(f"| {t['name']} | {t['frame_desc']} | {t['voice_desc']} |")
md.extend([
    "",
    "## How to use",
    "",
    "1. Pick a template: `gold_templates/<name>.geometry.json`",
    "2. Edit the voice stages (S{}) with your measured formant data (pole_hz, pole_r, zero_hz, zero_r, scale)".format(
        ", ".join(str(s) for t_ in templates for s in t_["voice_stages"])),
    "3. Compile: `python -m tools.filter_cli pack gold_templates/<name>.geometry.json out.body240`",
    "4. The frame stages (air + body) stay fixed — they define the physical identity.",
    "",
    "## Stage details",
])
for t in templates:
    md.append(f"\n### {t['name']}")
    md.append(f"- **Frame (keep):** {t['frame_desc']}")
    md.append(f"- **Voice (swap):** {t['voice_desc']}")
    for s in t["stage_info"]:
        label = f"S{s['stage']}: {s['role']} pole={s['pole_r']}@{s['pole_hz']:.0f}Hz"
        if s['zero_r'] > 0.3:
            label += f" zero={s['zero_r']}@{s['zero_hz']:.0f}Hz"
        marker = " [FRAME]" if s['stage'] in t['frame_stages'] else " [VOICE]" if s['stage'] in t['voice_stages'] else ""
        md.append(f"  {label}{marker}")

(OUT / "index.md").write_text("\n".join(md) + "\n")
print(f"\nWrote {len(templates)} templates to {OUT}")
