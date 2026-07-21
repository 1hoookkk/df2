"""Add ±50-cent detune CQT variants alongside existing base manifest rows.

Uses recorded chop_start_sample from base manifest — no re-generation.
Produces exactly 2 detune variants per base row (±50 cents).
Deterministic filenames, resume-safe.
"""

from __future__ import annotations

import argparse
import csv
import gc
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import librosa

TARGET_SR = 22_050
CHUNK_SECONDS = 6.0
CQT_BINS_PER_OCTAVE = 12
CQT_OCTAVES = 7
CQT_N_BINS = CQT_BINS_PER_OCTAVE * CQT_OCTAVES
CQT_HOP_LENGTH = 512
FMIN = librosa.note_to_hz("C2")
DETUNE_VALUES = [-50.0, 50.0]


def load_audio(path: Path) -> np.ndarray:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar",
        str(TARGET_SR), "pipe:1",
    ]
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)


def cqt_image(audio: np.ndarray) -> np.ndarray:
    return np.abs(
        librosa.cqt(audio, sr=TARGET_SR, hop_length=CQT_HOP_LENGTH,
                     n_bins=CQT_N_BINS, bins_per_octave=CQT_BINS_PER_OCTAVE, fmin=FMIN)
    ).astype(np.float32)


def process_one_source(
    audio_dir: str,
    output_dir: str,
    sf: str,
    file_idx: int,
    rows: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], int, int]:
    """(sf, new_rows, generated, skipped)"""
    out = Path(output_dir)
    audio_path = Path(audio_dir) / sf
    if not audio_path.exists():
        return sf, [], 0, 0

    # Check if ALL expected detune variants exist
    all_exist = True
    expected_detune: dict[str, dict[str, Any]] = {}
    for row in rows:
        base = row["npy"].replace(".npy", "")
        for dc in DETUNE_VALUES:
            direction = "n" if dc < 0 else "p"
            dt_npy = f"{base}_dt{int(abs(dc))}{direction}.npy"
            expected_detune[dt_npy] = row
            if not (out / dt_npy).exists():
                all_exist = False

    if all_exist:
        existing = [{**row, "npy": npy} for npy, row in expected_detune.items()]
        return sf, existing, 0, 0

    try:
        audio = load_audio(audio_path)
    except Exception:
        return sf, [], 0, 0

    if audio.size == 0:
        return sf, [], 0, 0

    chunk_len = int(CHUNK_SECONDS * TARGET_SR)
    new_rows: list[dict[str, Any]] = []
    generated = 0
    skipped = 0

    for row in rows:
        chop_i = int(row["chop_index"])
        shift = int(row["pitch_shift_semitones"])
        start_sample = int(row.get("chop_start_sample", 0))

        # Use recorded chop position
        start = min(start_sample, max(0, audio.size - chunk_len))
        loop = audio[start : start + chunk_len]
        if loop.size < chunk_len:
            loop = np.pad(loop, (0, chunk_len - loop.size))

        base = row["npy"].replace(".npy", "")

        for dc in DETUNE_VALUES:
            dt_npy = f"{base}_dt{int(abs(dc))}{'n' if dc < 0 else 'p'}.npy"
            if (out / dt_npy).exists():
                new_rows.append({**row, "npy": dt_npy})
                continue

            try:
                total_steps = float(shift) + dc / 100.0
                if total_steps == 0.0:
                    shifted = loop.copy()
                else:
                    shifted = librosa.effects.pitch_shift(y=loop, sr=TARGET_SR, n_steps=total_steps)

                cqt = cqt_image(shifted)
                np.save(out / dt_npy, cqt)
                new_rows.append({**row, "npy": dt_npy})
                generated += 1
            except MemoryError:
                skipped += 1
                continue

    gc.collect()
    return sf, new_rows, generated, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    audio_dir = str(args.audio_dir.resolve())
    output_dir = str(args.output_dir.resolve())

    rows_by_file: dict[str, list[dict[str, Any]]] = {}
    with args.manifest.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows_by_file.setdefault(row["source_file"], []).append(row)

    total = len(rows_by_file)
    print(f"{total} source files in manifest, {args.workers} workers")

    all_rows: list[dict[str, Any]] = []
    completed = 0
    total_generated = 0

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for file_idx, (sf, rows) in enumerate(sorted(rows_by_file.items()), 1):
            futures[pool.submit(process_one_source, audio_dir, output_dir, sf, file_idx, rows)] = sf

        for future in as_completed(futures):
            sf = futures[future]
            try:
                _, new_rows, generated, skipped = future.result()
                all_rows.extend(new_rows)
                completed += 1
                total_generated += generated
                tag = f"(+{generated} new)" if generated else "(already done)"
                if skipped:
                    tag += f" {skipped} skipped"
                print(f"  [{completed}/{total}] {sf}  {tag}", flush=True)
            except Exception as exc:
                completed += 1
                print(f"  [{completed}/{total}] FAIL {sf}: {exc}", flush=True)

    # Build combined manifest
    fieldnames = [
        "npy", "source_file", "source_sha256", "split", "chop_index",
        "chop_start_sample", "pitch_shift_semitones",
        "original_tonic", "original_mode",
        "shifted_tonic", "shifted_mode", "label_index", "cqt_shape",
    ]

    base_rows = []
    with args.manifest.open("r", encoding="utf-8", newline="") as f:
        base_rows = list(csv.DictReader(f))

    combined = base_rows + all_rows

    fd, tmp = tempfile.mkstemp(suffix=".csv", dir=str(output_dir), text=True)
    try:
        with open(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(combined)
        shutil.move(tmp, args.manifest.resolve())
    finally:
        Path(tmp).unlink(missing_ok=True)

    print(f"\ndone: {len(combined)} rows ({len(base_rows)} base + {len(all_rows)} detune), {total_generated} generated")
    print(f"manifest: {args.manifest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
