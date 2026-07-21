"""Build filename:label mapping, extract audio, generate final labels CSV."""
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
AUDIO_OUT = r"C:\Users\hooki\giantsteps_audio\wav"
LABELS_OUT = r"C:\Users\hooki\giantsteps_labels_mapped.csv"

os.makedirs(AUDIO_OUT, exist_ok=True)

# Load xlsx with key parsing
wb = openpyxl.load_workbook(XLSX_PATH)
ws = wb["GiantSteps+ Key Dataset"]

xlsx_rows = []
for row in ws.iter_rows(min_row=2, values_only=True):
    raw_key = str(row[7]).strip() if row[7] else ""
    label = parse_key(raw_key)
    if label is None:
        continue
    xlsx_rows.append({
        "id": row[0],
        "artist": str(row[2] or "").strip().lower(),
        "title": str(row[3] or "").strip().lower(),
        "mix": str(row[4] or "").strip().lower(),
        "tonic": label[0],
        "mode": label[1],
    })

# Parse mp3 filenames
z = zipfile.ZipFile(ZIP_PATH)
mp3s = [n for n in z.namelist() if n.endswith(".mp3") and "__MACOSX" not in n]

fn_pat = re.compile(r"^audio/(\d+)\s+(.+?)\s*-\s*(.+)\.mp3$")

audio_parsed = []
for name in mp3s:
    m = fn_pat.match(name)
    if not m:
        continue
    artist = m.group(2).strip().lower()
    title_part = m.group(3).strip().lower()
    mix = ""
    mix_m = re.search(r"\((.+?)\)$", title_part)
    if mix_m:
        mix = mix_m.group(1).strip().lower()
        title = title_part[: mix_m.start()].strip().rstrip("-").strip()
    else:
        title = title_part
    audio_parsed.append({"zip_path": name, "artist": artist, "title": title, "mix": mix})

# Match
mapped = []
unmatched = []
for x in xlsx_rows:
    x_aw = set(x["artist"].split())
    x_tw = set(x["title"].split())
    found = None
    for p in audio_parsed:
        if x_aw & set(p["artist"].split()) and x_tw & set(p["title"].split()):
            found = p
            break
    if found:
        mapped.append({**x, "zip_path": found["zip_path"]})
    else:
        unmatched.append(x)

print(f"mapped: {len(mapped)},  unmatched: {len(unmatched)}")

# Extract matched files and write labels
with open(LABELS_OUT, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["filename", "tonic", "mode"])
    for i, row in enumerate(mapped):
        safe_name = f"{row['id']:06d}.mp3"
        dst = os.path.join(AUDIO_OUT, safe_name)
        if not os.path.exists(dst):
            with z.open(row["zip_path"]) as src, open(dst, "wb") as d:
                d.write(src.read())
        writer.writerow([safe_name, row["tonic"], row["mode"]])
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(mapped)}", flush=True)

print(f"done: {len(mapped)} files extracted to {AUDIO_OUT}")
print(f"labels: {LABELS_OUT}")
