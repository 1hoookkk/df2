"""Harvest every real preset from dev/out into compiler-verified library."""
from __future__ import annotations
import hashlib, json, math, struct, subprocess, sys, csv, re, shutil
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"
LIB = Path(r"C:\Users\hooki\preset_library")
TMP = Path(r"C:\WINDOWS\TEMP\opencode\harvest_tmp")

SEARCH_DIRS = [
    ROOT / "dev",
    ROOT / "out",
    Path(r"C:\Users\hooki\df2") / "dev",
]

TMP.mkdir(parents=True, exist_ok=True)

# ── import filter_cli validation logic directly ─────────────────────────────
from tools.filter_cli import load as _validate, RUNTIME_SR

def validate_recipe(path: Path) -> dict | None:
    """Return parsed recipe dict if valid, None otherwise."""
    try:
        d = _validate(str(path))
        return d
    except (SystemExit, Exception):
        return None

# ── Step 1: find + validate all recipes ────────────────────────────────────
print("Step 1: Finding and validating geometry recipes...")
recipes = []  # list of (source_path, recipe_dict)
fail_log = []
for sdir in SEARCH_DIRS:
    if not sdir.exists():
        continue
    for fp in sorted(sdir.rglob("*.json")):
        if ".git" in fp.parts:
            continue
        d = validate_recipe(fp)
        if d is not None:
            recipes.append((fp, d))
        else:
            fail_log.append(fp)

print(f"  Valid recipes: {len(recipes)}")
print(f"  Failed validate: {len(fail_log)}")

# ── Step 2: compile each recipe ────────────────────────────────────────────
print("\nStep 2: Compiling through body-from-geometry.exe...")
compiled = []  # list of (source_path, recipe_dict, body_path, sha256, max_pole_r, pack_ok)
pack_failures = []
for src_path, recipe in recipes:
    stem = src_path.stem
    out_body = TMP / f"{stem}_{len(compiled)}.body240"
    try:
        r = subprocess.run(
            [str(COMPILER), str(src_path), str(out_body)],
            capture_output=True, text=True, timeout=30,
        )
        output = (r.stdout or r.stderr or "").strip()
        if r.returncode != 0 or not out_body.exists():
            pack_failures.append((str(src_path), output))
            continue
        body_bytes = out_body.read_bytes()
        if len(body_bytes) != 240:
            pack_failures.append((str(src_path), f"bad size {len(body_bytes)}"))
            continue
        h = hashlib.sha256(body_bytes).hexdigest()
        # Extract max pole radius from compiler output
        max_pr = 0.0
        for line in output.split("\n"):
            if "max pole radius" in line.lower():
                try:
                    max_pr = float(line.strip().split()[-1])
                except: pass
        compiled.append((src_path, recipe, out_body, h, max_pr, output))
    except subprocess.TimeoutExpired:
        pack_failures.append((str(src_path), "timeout"))
    except Exception as e:
        pack_failures.append((str(src_path), str(e)))

print(f"  Compiled OK: {len(compiled)}")
print(f"  Pack failures: {len(pack_failures)}")

# ── Step 3: dedup by sha256 ────────────────────────────────────────────────
print("\nStep 3: Deduping...")
by_hash: dict[str, list] = defaultdict(list)
for src_path, recipe, body_path, h, max_pr, output in compiled:
    by_hash[h].append((src_path, recipe, body_path, max_pr))

# Junk-name patterns to DROP (only if also no clean "name" field)
JUNK_NAMES = re.compile(
    r'^(cand_\d+|letter_word|EAR_az|'
    r'.*_probe$|.*_proof$|.*_audit$|.*_trial$|'
    r'[0-9a-f]{8,}|forge_all)', re.I
)

def is_junk(name: str) -> bool:
    return bool(JUNK_NAMES.match(name))

def clean_stem(name: str) -> str:
    """Strip hash suffixes: 'foo_bar_a1b2c3d4' -> 'foo_bar'"""
    name = re.sub(r'[_\.][0-9a-f]{8,}$', '', name)
    name = re.sub(r'[_\.][0-9a-f]{8,}$', '', name)  # double strip
    return name

deduped = []
dup_log = []
for h, entries in by_hash.items():
    # Score each entry: prefer clean human name, newest mtime
    scored = []
    for src_path, recipe, body_path, max_pr in entries:
        name = recipe.get("name", src_path.stem)
        stem = src_path.stem
        mtime = src_path.stat().st_mtime
        score = 0
        if not is_junk(name) and not is_junk(stem):
            score += 10  # clean name
        if name == stem:
            score += 5   # name matches stem (authored, not decoded)
        score += mtime / 1e12  # newer = slightly higher
        scored.append((score, src_path, recipe, body_path, max_pr))

    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    _, src_path, recipe, body_path, max_pr = best

    name = recipe.get("name", src_path.stem)
    name = clean_stem(name)

    # Final junk filter
    if is_junk(name):
        dup_log.append((h, name, "dropped junk", len(entries)))
        continue

    deduped.append({
        "sha256": h,
        "name": name,
        "recipe_path": str(src_path),
        "body_path": str(body_path),
        "max_pole_r": max_pr,
        "n_copies": len(entries),
        "all_paths": [str(e[0]) for e in entries],
    })
    if len(entries) > 1:
        dup_log.append((h, name, f"{len(entries)} copies", len(entries)))

print(f"  Deduped unique presets: {len(deduped)}")
print(f"  Duplicates merged: {len(dup_log)}")

# ── Step 4: find matching audio ────────────────────────────────────────────
print("\nStep 4: Finding matching audio...")
all_wavs = []
for sdir in SEARCH_DIRS:
    if not sdir.exists(): continue
    for fp in sdir.rglob("*.wav"):
        if ".git" in fp.parts: continue
        all_wavs.append(fp)
print(f"  Total WAV files found: {len(all_wavs)}")

# Build stem lookup
wav_by_stem = defaultdict(list)
for w in all_wavs:
    stem = w.stem.lower()
    stem = re.sub(r'[_\.][0-9a-f]{8,}$', '', stem)
    wav_by_stem[stem].append(w)

def find_matching_wav(name: str) -> Path | None:
    name_lower = name.lower()
    # Direct stem match
    if name_lower in wav_by_stem:
        return wav_by_stem[name_lower][0]  # take first
    # Try without hash suffixes
    clean = clean_stem(name_lower)
    if clean != name_lower and clean in wav_by_stem:
        return wav_by_stem[clean][0]
    return None

# ── Step 5: collect into preset_library ────────────────────────────────────
print("\nStep 5: Collecting into preset_library...")
LIB.mkdir(parents=True, exist_ok=True)
index_rows = []
for entry in deduped:
    name = entry["name"]
    sha = entry["sha256"]
    body_path = Path(entry["body_path"])
    
    # Copy recipe
    recipe_src = Path(entry["recipe_path"])
    out_dir = LIB / name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_recipe = out_dir / f"{name}.geometry.json"
    shutil.copy2(recipe_src, out_recipe)
    
    # Copy body (fresh-packed)
    out_body = out_dir / f"{name}.body240"
    shutil.copy2(body_path, out_body)
    
    # Find and copy audio
    wav_path = find_matching_wav(name)
    has_audio = False
    if wav_path:
        out_wav = out_dir / f"{name}.wav"
        shutil.copy2(wav_path, out_wav)
        has_audio = True
    
    index_rows.append({
        "name": name,
        "sha256": sha,
        "has_audio": "yes" if has_audio else "no",
        "validates": "true",
        "max_pole_radius": entry["max_pole_r"],
        "n_recipe_copies": entry["n_copies"],
        "source_paths": "|".join(entry["all_paths"]),
    })
    print(f"  {name}: packed sha={sha[:12]} audio={'yes' if has_audio else 'no'}")

# ── index.csv ──────────────────────────────────────────────────────────────
csv_path = LIB / "presets_index.csv"
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=[
        "name", "sha256", "has_audio", "validates",
        "max_pole_radius", "n_recipe_copies", "source_paths",
    ])
    w.writeheader()
    w.writerows(index_rows)
print(f"\nWrote {csv_path} ({len(index_rows)} presets)")

# ── index.md ───────────────────────────────────────────────────────────────
with_audio = sum(1 for r in index_rows if r["has_audio"] == "yes")
md_lines = [
    "# Preset Library Index",
    f"\n**Harvested presets:** {len(index_rows)}",
    f"**With audio:** {with_audio}",
    f"**Without audio:** {len(index_rows) - with_audio}",
    f"**Pack failures:** {len(pack_failures)}",
    f"\n## Preset list\n",
]
for r in sorted(index_rows, key=lambda x: x["name"].lower()):
    au = " 🔊" if r["has_audio"] == "yes" else ""
    md_lines.append(f"- **{r['name']}**{au} — max pole r={r['max_pole_radius']}, {r['n_recipe_copies']} source(s)")
md_lines.extend([
    f"\n## Pack failures ({len(pack_failures)})",
    "",
])
for p, msg in pack_failures[:50]:
    md_lines.append(f"- `{p}`: {msg[:120]}")
if len(pack_failures) > 50:
    md_lines.append(f"- ... and {len(pack_failures)-50} more")
md_lines.extend([
    f"\n## Validation failures ({len(fail_log)})",
    "Non-recipe JSON files (probe reports, metadata, fingerprints). Not listed individually.",
])
md_path = LIB / "presets_index.md"
with open(md_path, "w") as f:
    f.write("\n".join(md_lines) + "\n")
print(f"Wrote {md_path}")

# ── Step 6: orphan report ──────────────────────────────────────────────────
print("\nStep 6: Orphan body240 report...")
all_bodies = []
for sdir in SEARCH_DIRS:
    if not sdir.exists(): continue
    for fp in sdir.rglob("*.body240"):
        if ".git" in fp.parts: continue
        all_bodies.append(fp)

# Build set of packed body sha256s (deduped)
packed_shas = set(e["sha256"] for e in deduped)

orphans = []
for fp in all_bodies:
    body_bytes = fp.read_bytes()
    if len(body_bytes) != 240: continue
    h = hashlib.sha256(body_bytes).hexdigest()
    if h not in packed_shas:
        # Check if it has a recipe that maybe failed to pack
        orphans.append({"path": str(fp), "sha256": h})

orphan_csv = LIB / "orphan_bodies.csv"
with open(orphan_csv, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["path", "sha256"])
    for o in orphans:
        w.writerow([o["path"], o["sha256"]])
print(f"  Total orphan .body240 files: {len(orphans)}")
print(f"  Wrote {orphan_csv}")

# ── summary ────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"PRESET HARVEST COMPLETE")
print(f"  Valid recipes found:     {len(recipes)}")
print(f"  Compiled successfully:   {len(compiled)}")
print(f"  Pack failures:           {len(pack_failures)}")
print(f"  Unique presets (deduped):{len(deduped)}")
print(f"  With audio:              {with_audio}")
print(f"  Orphan bodies (no src):  {len(orphans)}")
print(f"  Library:                 {LIB}")
