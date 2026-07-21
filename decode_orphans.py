"""Decode orphan body240 files with clean names into geometry recipes and add to library."""
from __future__ import annotations
import csv, hashlib, json, math, re, struct, subprocess, sys, shutil
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent
LIB = Path(r"C:\Users\hooki\preset_library")
TMP = Path(r"C:\WINDOWS\TEMP\opencode\decode_tmp")
TMP.mkdir(parents=True, exist_ok=True)
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"

from tools.filter_cli import load as _validate

# ── junk name patterns ─────────────────────────────────────────────────────
JUNK = re.compile(
    r'^(cand_\d+|letter_word|EAR_az|'
    r'.*_probe$|.*_proof$|.*_audit$|.*_trial$|'
    r'^[0-9a-f]{8,}|forge_all|report|manifest|summary|'
    r'recovery_faceshot_|\.fingerprint|\.rustc_info)', re.I
)

def is_junk(name: str) -> bool:
    return bool(JUNK.match(name))

def clean_stem(name: str) -> str:
    name = re.sub(r'[_\.][0-9a-f]{8,}$', '', name)
    name = re.sub(r'[_\.][0-9a-f]{8,}$', '', name)
    return name

# ── Load existing library shas to skip duplicates ─────────────────────────
existing_shas = set()
lib_csv = LIB / "presets_index.csv"
if lib_csv.exists():
    with open(lib_csv) as f:
        for row in csv.DictReader(f):
            existing_shas.add(row["sha256"])

print(f"Existing library presets: {len(existing_shas)}")

# ── Load orphan list ──────────────────────────────────────────────────────
orphans = []
orphan_csv = LIB / "orphan_bodies.csv"
with open(orphan_csv) as f:
    for row in csv.DictReader(f):
        orphans.append(row)

print(f"Total orphans: {len(orphans)}")

# ── Dedup orphans by sha256, filter junk names ────────────────────────────
by_sha: dict[str, list] = defaultdict(list)
for o in orphans:
    by_sha[o["sha256"]].append(o["path"])

clean_orphans = []  # (sha256, name, [paths])
for sha, paths in by_sha.items():
    if sha in existing_shas:
        continue  # already in library (from recipe)
    # Pick the best name from the paths
    names = []
    for p in paths:
        stem = Path(p).stem
        names.append(stem)
    # Use the cleanest name
    clean_names = [n for n in names if not is_junk(n)]
    if not clean_names:
        continue  # skip junk-only orphans
    best_name = min(clean_names, key=lambda n: len(n))  # shortest clean name
    best_name = clean_stem(best_name)
    if not best_name or is_junk(best_name):
        continue
    clean_orphans.append((sha, best_name, paths))

print(f"Clean unique orphans to decode: {len(clean_orphans)}")
print(f"  (skipped {len(by_sha) - len(clean_orphans)} junk/duplicate)")

# ── Decode each orphan → validate → pack → collect ────────────────────────
decoded_ok = 0
decode_fail = 0
pack_fail = 0
validate_fail = 0

for sha, name, paths in clean_orphans:
    src_path = Path(paths[0])  # use first source
    out_dir = LIB / name
    if out_dir.exists():
        # Check if this body240 already exists in the library
        existing_body = out_dir / f"{name}.body240"
        if existing_body.exists() and hashlib.sha256(existing_body.read_bytes()).hexdigest() == sha:
            print(f"  {name}: already in library, skip")
            continue

    # Decode body240 → geometry recipe
    geo_path = TMP / f"{name}.geometry.json"
    try:
        r = subprocess.run(
            [sys.executable, "-m", "tools.filter_cli", "decode", str(src_path), str(geo_path)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0 or not geo_path.exists():
            print(f"  {name}: decode failed — {r.stderr.strip()[:80]}")
            decode_fail += 1
            continue
    except Exception as e:
        print(f"  {name}: decode error — {e}")
        decode_fail += 1
        continue

    # Validate the decoded recipe
    try:
        d = _validate(str(geo_path))
    except (SystemExit, Exception):
        print(f"  {name}: decoded recipe failed validation")
        validate_fail += 1
        continue

    # Pack through compiler (verification)
    packed = TMP / f"{name}.body240"
    try:
        r = subprocess.run(
            [str(COMPILER), str(geo_path), str(packed)],
            capture_output=True, text=True, timeout=30,
        )
        output = (r.stdout or r.stderr or "").strip()
        if r.returncode != 0 or not packed.exists():
            print(f"  {name}: pack failed — {output[:80]}")
            pack_fail += 1
            continue
        packed_sha = hashlib.sha256(packed.read_bytes()).hexdigest()
        if packed_sha != sha:
            print(f"  {name}: roundtrip MISMATCH (decoded {sha[:12]} → packed {packed_sha[:12]})")
            # Still collect it — the decoded recipe is editable even if not bit-identical
    except Exception as e:
        print(f"  {name}: pack error — {e}")
        pack_fail += 1
        continue

    # Extract max pole radius from compiler output
    max_pr = 0.0
    for line in output.split("\n"):
        if "max pole radius" in line.lower():
            try: max_pr = float(line.strip().split()[-1])
            except: pass

    # Collect into library
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(geo_path, out_dir / f"{name}.geometry.json")
    shutil.copy2(packed, out_dir / f"{name}.body240")

    # Check for matching audio
    wav_found = None
    for p in paths:
        parent = Path(p).parent
        for wav in parent.glob(f"{Path(p).stem}.*"):
            if wav.suffix.lower() == ".wav":
                wav_found = wav
                break
    has_audio = False
    if wav_found:
        shutil.copy2(wav_found, out_dir / f"{name}.wav")
        has_audio = True

    # Append to index CSV
    roundtrip = "yes" if packed_sha == sha else "mismatch"
    with open(lib_csv, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([name, sha, "yes" if has_audio else "no", roundtrip,
                    max_pr, 1, "|".join(paths)])

    decoded_ok += 1
    print(f"  {name}: decoded + packed ✓  audio={'yes' if has_audio else 'no'} roundtrip={roundtrip}")

print(f"\n{'='*60}")
print(f"ORPHAN DECODE COMPLETE")
print(f"  Decoded + packed: {decoded_ok}")
print(f"  Decode failures: {decode_fail}")
print(f"  Validate failures: {validate_fail}")
print(f"  Pack failures: {pack_fail}")
print(f"  Total in library now: {decoded_ok + 153}")
