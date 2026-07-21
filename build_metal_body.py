"""Build a metal-body filter from the metallic_modes table.
Uses the actual corner_words toolchain — bp(), corner_words(), raw_from_words()."""
import json, subprocess, sys, math, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# The actual df2 tools
sys.path.insert(0, str(Path(r"C:\Users\hooki\df2")))
from tools.corner_words import bp, pas, edge, corner_words, build_toml
from src.utils.body240 import raw_from_words

COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"
OUT = ROOT / "preset_library" / "metal_bodies"
OUT.mkdir(parents=True, exist_ok=True)

# ── Metal mode data from metallic_modes.json ──────────────────────────────
# free_bar at 220 Hz:  partials = [220, 606, 1189, 1965, 2935]
# clamped_bar at 220 Hz: partials = [220, 1379, 3861, 7566]
# bell at 300 Hz prime: partials = [150, 300, 360, 450, 600, 750, 801, 900, 1200]
# free_plate at 300 Hz: partials = [300, 519, 699, 795, 1050, 1179, 1443]
# gong at 200 Hz: partials = [200, 304, 400, 482, 556, 666, 812, 1020]

# Build: free_bar (morph: strike -> ring, Q = damping)
# Stages:
#   S0: air/presence (fixed high from talking_hedz style)
#   S1-S4: 4 partials of the bar
#   S5: body resonance

templates = []

for name, partials_hz, fund_hz in [
    ("free_bar_440", [440, 1213, 2378, 3931], 440),
    ("clamped_bar_220", [220, 1379, 3861, 7566], 220),
    ("bell_300", [300, 600, 750, 1000], 300),
    ("free_plate_300", [300, 519, 699, 795], 300),
    ("gong_200", [200, 400, 556, 666], 200),
]:
    # Build 4 corners: morph changes the strike (brightness), Q tightens radii
    corners = {}
    for mi, (m_label, morph) in enumerate([("M0_Q0", 0.0), ("M100_Q0", 1.0)]):
        for qi, (q_label, q) in enumerate([("M0_Q0", 0.0), ("M0_Q100", 1.0)]):
            label = f"M{int(morph*100)}_Q{int(q*100)}"
            
            # Scale partials with morph (brighter strike)
            scale = 1.0 + 0.3 * morph
            scaled = [f * scale for f in partials_hz]
            
            # Radius: Q tightens it
            r = 0.95 + 0.045 * q  # 0.95 -> 0.995
            
            stages = []
            # S0: air/presence (fixed high)
            stages.append(bp(8500 + 2000 * morph, min(0.99, r + 0.01)))
            # S1-S4: the partials
            for f in scaled[:4]:
                stages.append(bp(f, r))
            # S5: body resonance
            stages.append(bp(max(fund_hz * 0.5, 80), r))
            
            corners[label] = stages
    
    # Pack words
    words = {}
    for label, stages in corners.items():
        words[label] = corner_words(stages)
    
    body_bytes = raw_from_words(words)
    sha = hashlib.sha256(body_bytes).hexdigest()
    
    # Also write geometry.json for compiler
    # (raw_from_words produces body240 directly, but we can also write geometry)
    
    (OUT / f"{name}.body240").write_bytes(body_bytes)
    templates.append({"name": name, "sha": sha, "partials": scaled, "fundamental": fund_hz})
    print(f"{name}: built ✓ sha={sha[:12]}  partials={[round(f) for f in scaled]}")

# Verify through compiler by round-tripping via filter_cli decode
print("\nVerifying through compiler...")
for t in templates:
    # Decode body240 → geometry → re-compile
    body_path = OUT / f"{t['name']}.body240"
    geo_path = OUT / f"{t['name']}.geometry.json"
    r1 = subprocess.run(
        [sys.executable, "-m", "tools.filter_cli", "decode", str(body_path), str(geo_path)],
        capture_output=True, text=True, timeout=15, cwd=ROOT,
    )
    if not geo_path.exists():
        print(f"  {t['name']}: decode FAIL — {r1.stderr[:100]}")
        continue
    packed2 = OUT / f"{t['name']}.verify.body240"
    r2 = subprocess.run(
        [str(COMPILER), str(geo_path), str(packed2)],
        capture_output=True, text=True, timeout=15,
    )
    output = (r2.stdout or r2.stderr or "").strip()
    if r2.returncode == 0 and packed2.exists():
        max_pr = "?"
        for line in output.split("\n"):
            if "max pole radius" in line.lower():
                try: max_pr = f"{float(line.strip().split()[-1]):.4f}"
                except: pass
        print(f"  {t['name']}: PASS max_r={max_pr}")
    else:
        print(f"  {t['name']}: FAIL — {output[:120]}")

print(f"\nWrote {len(templates)} metal bodies to {OUT}")
