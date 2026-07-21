"""Rebuild audio extraction using EXACT GiantSteps ID from mp3 filename prefix.
Matches xlsx 'id' column directly to mp3 filename prefix. No fuzzy artist/title matching.
"""
import csv
import os
import re
import zipfile
from pathlib import Path

import openpyxl
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.convert_giantsteps import parse_key

ZIP_PATH = r"C:\Users\hooki\giantsteps_audio.zip"
XLSX_PATH = r"C:\Users\hooki\Downloads\GiantSteps+.xlsx"
AUDIO_OUT = Path(r"C:\Users\hooki\giantsteps_audio\wav_v2")
LABELS_OUT = Path(r"C:\Users\hooki\giantsteps_labels_v2.csv")

AUDIO_OUT.mkdir(parents=True, exist_ok=True)

# Load xlsx, index by GiantSteps ID
wb = openpyxl.load_workbook(XLSX_PATH)
ws = wb["GiantSteps+ Key Dataset"]

xlsx_by_id: dict[int, dict] = {}
for row in ws.iter_rows(min_row=2, values_only=True):
    gs_id = int(row[0])
    raw_key = str(row[7]).strip() if row[7] else ""
    label = parse_key(raw_key)
    xlsx_by_id[gs_id] = {
        "id": gs_id,
        "tonic": label[0] if label else None,
        "mode": label[1] if label else None,
        "artist": str(row[2] or "").strip(),
        "title": str(row[3] or "").strip(),
        "raw_key": raw_key,
    }

# Parse mp3 filenames — extract numeric GiantSteps ID from prefix
z = zipfile.ZipFile(ZIP_PATH)
mp3_pat = re.compile(r"^audio/(\d+)\s+.+\.mp3$")

mp3_by_id: dict[int, str] = {}
for name in z.namelist():
    if "__MACOSX" in name:
        continue
    m = mp3_pat.match(name)
    if not m:
        continue
    gs_id = int(m.group(1))
    mp3_by_id[gs_id] = name

print(f"xlsx rows: {len(xlsx_by_id)},  mp3s: {len(mp3_by_id)}")

# Match by exact numeric ID
matched = 0
missing_audio = 0
missing_label = 0
duplicate_label_map: dict[str, list[int]] = {}

with open(LABELS_OUT, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["filename", "tonic", "mode"])

    for gs_id, info in sorted(xlsx_by_id.items()):
        if info["tonic"] is None:
            continue  # no valid label

        if gs_id not in mp3_by_id:
            missing_audio += 1
            print(f"  MISSING AUDIO: {gs_id}  {info['artist']} - {info['title']}")
            continue

        filename = f"{gs_id:06d}.mp3"
        # Sanitize illegal chars in zip paths (asterisk etc)
        safe_name = re.sub(r'[*?<>:"|]', '_', filename)
        dst = AUDIO_OUT / safe_name

        if not dst.exists():
            with z.open(mp3_by_id[gs_id]) as src, open(dst, "wb") as d:
                d.write(src.read())

        writer.writerow([safe_name, info["tonic"], info["mode"]])

        # Track content duplicates
        content = safe_name  # use filename as proxy for now
        duplicate_label_map.setdefault(content, []).append(gs_id)
        matched += 1

print(f"matched: {matched}")
print(f"missing audio: {missing_audio}")
print(f"missing label: {missing_label}")
print(f"files extracted to: {AUDIO_OUT}")
print(f"labels: {LABELS_OUT}")

# Check for files with multiple IDs (impossible in this mapping, but good hygiene)
dupes = {k: v for k, v in duplicate_label_map.items() if len(v) > 1}
if dupes:
    print(f"WARNING: {len(dupes)} files with multiple IDs")
else:
    print("no duplicate IDs across files")
