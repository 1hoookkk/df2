"""Harvest geometry recipes from all specified paths — compiled through THE compiler."""
from __future__ import annotations
import csv, hashlib, json, subprocess, sys, shutil
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"
LIB = Path(r"C:\Users\hooki\preset_library")
TMP = Path(r"C:\WINDOWS\TEMP\opencode\harvest_tmp2")
TMP.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))
from tools.filter_cli import load as _validate

SEARCH_PATHS = [
    ROOT / "filters",
    ROOT / "workstation",
    ROOT / "dev",
    ROOT / "fixtures",
    ROOT / "recipe-index",
    ROOT / "workstation" / "src",
    Path(r"C:\Users\hooki\df2"),
    Path(r"C:\Users\hooki\df2\dev\tmp"),
    Path(r"C:\Users\hooki\surface-forge"),
]

EXCLUDE_DIRS = {".git", "__pycache__", "target", "node_modules", ".fingerprint"}

print("Searching for geometry recipes...")
all_jsons = []
for sp in SEARCH_PATHS:
    if not sp.exists():
        print(f"  SKIP (not found): {sp}")
        continue
    for fp in sp.rglob("*.json"):
        if any(ex in fp.parts for ex in EXCLUDE_DIRS):
            continue
        all_jsons.append(fp)

print(f"Total JSON files: {len(all_jsons)}")

# Validate each
recipes = []  # (path, recipe_dict)
for fp in all_jsons:
    try:
        d = _validate(str(fp))
        recipes.append((fp, d))
    except (SystemExit, Exception):
        pass

print(f"Valid geometry recipes: {len(recipes)}")

# Filter to only "real measured data" — skip decodedFrom bodies
authored = []
decoded = []
for fp, d in recipes:
    if "decodedFrom" in d:
        decoded.append((fp, d))
    else:
        authored.append((fp, d))

print(f"  Authored (from measurements): {len(authored)}")
print(f"  Decoded from body240: {len(decoded)}")

# Compile each authored recipe
print("\nCompiling through body-from-geometry.exe...")
compiled = []  # (path, recipe, body_path, sha256, max_pr)
failures = []
for fp, d in authored:
    stem = fp.stem
    name = d.get("name", stem)
    out_body = TMP / f"{stem}.body240"
    try:
        r = subprocess.run(
            [str(COMPILER), str(fp), str(out_body)],
            capture_output=True, text=True, timeout=30,
        )
        output = (r.stdout or r.stderr or "").strip()
        if r.returncode != 0 or not out_body.exists():
            failures.append((str(fp), output[:120]))
            continue
        body_bytes = out_body.read_bytes()
        if len(body_bytes) != 240:
            failures.append((str(fp), f"bad size {len(body_bytes)}"))
            continue
        h = hashlib.sha256(body_bytes).hexdigest()
        max_pr = 0.0
        for line in output.split("\n"):
            if "max pole radius" in line.lower():
                try: max_pr = float(line.strip().split()[-1])
                except: pass
        compiled.append((fp, d, out_body, h, max_pr, output))
    except subprocess.TimeoutExpired:
        failures.append((str(fp), "timeout"))
    except Exception as e:
        failures.append((str(fp), str(e)))

print(f"  Compiled OK: {len(compiled)}")
print(f"  Failures: {len(failures)}")

# Dedup by sha256
print("\nDeduping...")
by_hash = defaultdict(list)
for fp, d, body_path, h, max_pr, output in compiled:
    by_hash[h].append((fp, d, max_pr))

deduped = []
dup_log = []
for h, entries in by_hash.items():
    # Pick best: authored name, newest mtime
    scored = []
    for fp, d, max_pr in entries:
        mtime = fp.stat().st_mtime
        score = mtime / 1e12
        if d.get("name", "") == fp.stem:
            score += 10  # name matches stem = clean
        scored.append((score, fp, d, max_pr))
    scored.sort(key=lambda x: -x[0])
    best_fp, best_d, best_pr = scored[0][1], scored[0][2], scored[0][3]
    
    name = best_d.get("name", best_fp.stem)
    # Clean hash suffixes
    import re
    name = re.sub(r'[_\.][0-9a-f]{8,}$', '', name)
    
    deduped.append({
        "sha256": h,
        "name": name,
        "recipe_path": str(best_fp),
        "max_pole_r": best_pr,
        "n_copies": len(entries),
        "all_paths": [str(e[0]) for e in entries],
    })
    if len(entries) > 1:
        dup_log.append((h, name, len(entries)))

print(f"  Unique presets: {len(deduped)}")
print(f"  Duplicates merged: {len(dup_log)}")

# Collect into library
print("\nCollecting...")
LIB.mkdir(parents=True, exist_ok=True)

# Find matching WAVs
all_wavs = []
for sp in SEARCH_PATHS:
    if not sp.exists(): continue
    for fp in sp.rglob("*.wav"):
        if any(ex in fp.parts for ex in EXCLUDE_DIRS): continue
        all_wavs.append(fp)
wav_by_stem = defaultdict(list)
for w in all_wavs:
    stem = w.stem.lower()
    wav_by_stem[stem].append(w)

def find_wav(name):
    nl = name.lower()
    if nl in wav_by_stem: return wav_by_stem[nl][0]
    return None

rows = []
for entry in deduped:
    name = entry["name"]
    sha = entry["sha256"]
    recipe_src = Path(entry["recipe_path"])
    out_dir = LIB / name
    out_dir.mkdir(parents=True, exist_ok=True)
    
    shutil.copy2(recipe_src, out_dir / f"{name}.geometry.json")
    # Re-pack fresh
    fresh_body = out_dir / f"{name}.body240"
    subprocess.run([str(COMPILER), str(recipe_src), str(fresh_body)],
                   capture_output=True, timeout=30)
    
    wav = find_wav(name)
    has_audio = "no"
    if wav:
        shutil.copy2(wav, out_dir / f"{name}.wav")
        has_audio = "yes"
    
    rows.append({
        "name": name,
        "sha256": sha,
        "has_audio": has_audio,
        "validates": "true",
        "max_pole_radius": entry["max_pole_r"],
        "n_recipe_copies": entry["n_copies"],
        "source_paths": "|".join(entry["all_paths"]),
    })
    print(f"  {name}: sha={sha[:12]} audio={has_audio}")

# Write index
csv_path = LIB / "presets_index.csv"
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=[
        "name", "sha256", "has_audio", "validates",
        "max_pole_radius", "n_recipe_copies", "source_paths",
    ])
    w.writeheader()
    for r in sorted(rows, key=lambda x: x["name"].lower()):
        w.writerow(r)

with_audio = sum(1 for r in rows if r["has_audio"] == "yes")
md = [
    "# Preset Library — Geometry Recipes from Measured Data",
    f"\n**Total:** {len(rows)}",
    f"**With audio:** {with_audio}",
    f"**Compile failures:** {len(failures)}",
    "\n## Presets\n",
]
for r in sorted(rows, key=lambda x: x["name"].lower()):
    au = " 🔊" if r["has_audio"] == "yes" else ""
    md.append(f"- **{r['name']}**{au} — max pole r={r['max_pole_radius']}")
md.extend(["\n## Failures\n"])
for p, msg in failures[:30]:
    md.append(f"- `{p}`: {msg[:100]}")
(md_path := LIB / "presets_index.md").write_text("\n".join(md) + "\n")

print(f"\n{'='*60}")
print(f"DONE — {len(rows)} recipes collected")
print(f"  Search paths searched: {len([p for p in SEARCH_PATHS if p.exists()])}")
print(f"  Authored recipes found: {len(authored)}")
print(f"  Decoded-from-body skipped: {len(decoded)}")
print(f"  Compile failures: {len(failures)}")
print(f"  Library: {LIB}")
