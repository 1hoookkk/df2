"""Build 8 template recipes from the gold-type P2K bodies.
Frame stages fixed, voice stages parameterized. Compile-ready."""
import json, shutil
from pathlib import Path

LIB = Path(r"C:\Users\hooki\preset_library")
TPL = LIB / "templates"
TPL.mkdir(parents=True, exist_ok=True)

# The 8 gold types and their arch_ names in the library
GOLD = [
    ("millennium", "arch_millennium"),
    ("meaty_gizmo", "arch_meaty_gizmo"),
    ("ooh_to_eee", "arch_ooh_to_eee"),
    ("talking_hedz", "arch_talking_hedz"),
    ("razor_blades", "arch_razor_blades"),
    ("deep_bouche", "arch_deep_bouche"),
    ("lucifer_s_q", "arch_lucifer_s_q"),
    ("tooth_comb", "arch_tooth_comb"),
]

templates = []
for gold_name, arch_name in GOLD:
    geo_path = LIB / arch_name / f"{arch_name}.geometry.json"
    if not geo_path.exists():
        print(f"SKIP: {arch_name} — geometry not found")
        continue
    
    d = json.loads(geo_path.read_text())
    corners = d["corners"]
    
    # Classify each stage's role from corner A (M0_Q0)
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
    
    stage_info = []
    for si in range(6):
        ref = corners[0][si]
        role = stage_role(ref)
        stage_info.append({"stage": si, "role": role, "hz": ref.get("pole_hz", 0)})
    
    # Determine fixed stages (frame) vs replaceable (voice)
    # Frame = air + body stages that define the physical identity
    # Voice = formant stages you swap with measured data
    # Notch/other = keep as-is (part of the frame structure)
    
    frame_stages = [s for s in stage_info if s["role"] in ("air", "body")]
    voice_stages = [s for s in stage_info if s["role"] == "voice"]
    
    # Build description
    frame_desc = ", ".join(f"S{s['stage']}({s['role']}@{s['hz']:.0f}Hz)" for s in frame_stages)
    voice_desc = ", ".join(f"S{s['stage']}({s['hz']:.0f}Hz)" for s in voice_stages)
    
    # Copy the raw geometry as the template
    # The voice stages are documented as replaceable but the template compiles as-is
    tpl_path = TPL / f"{gold_name}.geometry.json"
    shutil.copy2(geo_path, tpl_path)
    
    # Also create a simpler "frame-only" version where voice stages are marked
    frame_only = json.loads(geo_path.read_text())
    for si in [s["stage"] for s in voice_stages]:
        for ci in range(4):
            # Mark as replaceable by setting a comment field
            frame_only["corners"][ci][si]["_voice_slot"] = True
    
    tpl_frame = TPL / f"{gold_name}_frame.geometry.json"
    with open(tpl_frame, "w") as f:
        json.dump(frame_only, f, indent=1)
    
    templates.append({
        "name": gold_name,
        "file": f"{gold_name}.geometry.json",
        "frame": frame_desc,
        "voice": voice_desc,
        "n_frame": len(frame_stages),
        "n_voice": len(voice_stages),
        "stages": stage_info,
    })

# Write template index
md = [
    "# P2K Gold-Type Templates",
    "",
    "8 frame templates, compile-ready. Voice stages are replaceable with measured data.",
    "",
    "| Template | Frame (keep) | Voice (swap) |",
    "|----------|-------------|--------------|",
]
for t in templates:
    md.append(f"| {t['name']} | {t['frame']} | {t['voice']} |")
md.extend([
    "",
    "## How to use",
    "",
    "1. Pick a template: `templates/<name>.geometry.json`",
    "2. Fill the voice stages with your measured formant data (Klatt, DVTD, LPC, etc.)",
    "3. Compile: `python -m tools.filter_cli pack templates/<name>.geometry.json out.body240`",
    "",
    "The frame stages (air + body) stay fixed — they define the physical identity.",
    "The voice stages are the formant slots you replace to change the vowel/sound.",
    "",
    "## Frame details",
])
for t in templates:
    md.append(f"\n### {t['name']}")
    md.append(f"- **Frame:** {t['frame']}")
    md.append(f"- **Voice slots:** {t['voice']}")
    stages_str = " | ".join(f"S{s['stage']} {s['role']} @{s['hz']:.0f}Hz" for s in t['stages'])
    md.append(f"- **Full:** {stages_str}")

tpl_index = TPL / "index.md"
tpl_index.write_text("\n".join(md) + "\n")

print(f"Wrote {len(templates)} templates to {TPL}")
for t in templates:
    print(f"  {t['name']}: frame=[{t['frame']}]  voice=[{t['voice']}]")
