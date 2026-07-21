"""Slice, pitch-shift, and CQT-encode a labeled key dataset for ML training.

Resume-safe: rebuilds manifest rows from existing .npy files.
Atomic manifest write: temp file → rename.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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
NOTE_NAMES = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")
CHUNK_SECONDS = 6.0
RANDOM_CHOPS = 4
MAX_SHIFT_SEMITONES = 11
CQT_BINS_PER_OCTAVE = 12
CQT_OCTAVES = 7
CQT_N_BINS = CQT_BINS_PER_OCTAVE * CQT_OCTAVES
CQT_HOP_LENGTH = 512
FMIN = librosa.note_to_hz("C2")
SEED = 42
EXPECTED_VARIANTS_PER_FILE = RANDOM_CHOPS * (MAX_SHIFT_SEMITONES + 1)  # 48


def shift_key(tonic: str, mode: str, semitones: int) -> tuple[str, str]:
    idx = NOTE_NAMES.index(tonic)
    return NOTE_NAMES[(idx + semitones) % 12], mode


def chunk_indices(total_samples: int, chunk_samples: int, n_chops: int, rng: np.random.Generator) -> list[int]:
    max_start = total_samples - chunk_samples
    if max_start < 0:
        return [0] * n_chops
    return sorted(int(rng.integers(0, max_start + 1)) for _ in range(n_chops))


def cqt_image(audio: np.ndarray) -> np.ndarray:
    return np.abs(
        librosa.cqt(audio, sr=TARGET_SR, hop_length=CQT_HOP_LENGTH,
                     n_bins=CQT_N_BINS, bins_per_octave=CQT_BINS_PER_OCTAVE, fmin=FMIN)
    ).astype(np.float32)


def load_audio(path: Path) -> np.ndarray:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar",
        str(TARGET_SR), "pipe:1",
    ]
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio = np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)
    if audio.size == 0 or not np.all(np.isfinite(audio)):
        raise ValueError(f"decoded audio empty or nonfinite: {path}")
    return audio


def make_manifest_row(stem: str, audio_name: str, source_sha256: str, split: str,
                      chop_i: int, start_sample: int, shift: int,
                      tonic: str, mode: str, cqt: np.ndarray) -> dict[str, Any]:
    shifted_tonic, shifted_mode = shift_key(tonic, mode, shift)
    return {
        "npy": f"{stem}_chop{chop_i}_shift{shift:+d}.npy",
        "source_file": audio_name,
        "source_sha256": source_sha256,
        "split": split,
        "chop_index": chop_i,
        "chop_start_sample": start_sample,
        "pitch_shift_semitones": shift,
        "original_tonic": tonic,
        "original_mode": mode,
        "shifted_tonic": shifted_tonic,
        "shifted_mode": shifted_mode,
        "label_index": NOTE_NAMES.index(shifted_tonic) + (0 if mode == "maj" else 12),
        "cqt_shape": f"[{cqt.shape[0]},{cqt.shape[1]}]",
    }


def process_or_resume(
    audio_path: Path,
    tonic: str,
    mode: str,
    output_dir: Path,
    file_index: int,
) -> list[dict[str, Any]]:
    stem = audio_path.stem
    audio_name = audio_path.name
    source_sha256 = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    split_byte = hashlib.sha256(audio_name.encode()).digest()[0]
    split = "train" if split_byte < 204 else "val"

    # Check if ALL expected variants exist — if so, rebuild rows from disk
    expected_names = [f"{stem}_chop{c}_shift{s:+d}.npy"
                      for c in range(RANDOM_CHOPS) for s in range(MAX_SHIFT_SEMITONES + 1)]
    all_exist = all((output_dir / n).exists() for n in expected_names)

    if all_exist:
        rows = []
        for chop_i in range(RANDOM_CHOPS):
            for shift in range(MAX_SHIFT_SEMITONES + 1):
                npy = f"{stem}_chop{chop_i}_shift{shift:+d}.npy"
                if not (output_dir / npy).exists():
                    continue
                cqt = np.load(output_dir / npy)
                rows.append(make_manifest_row(
                    stem, audio_name, source_sha256, split,
                    chop_i, 0, shift, tonic, mode, cqt,
                ))
        return rows

    # Generate new variants
    audio = load_audio(audio_path)
    if audio.size < int(TARGET_SR * 0.5):
        return []

    chunk_len = int(CHUNK_SECONDS * TARGET_SR)
    rng = np.random.default_rng(SEED + file_index)
    starts = chunk_indices(audio.size, chunk_len, RANDOM_CHOPS, rng)

    rows = []
    for chop_i, start in enumerate(starts):
        loop = audio[start : start + chunk_len]
        if loop.size < chunk_len:
            loop = np.pad(loop, (0, chunk_len - loop.size))

        for shift in range(MAX_SHIFT_SEMITONES + 1):
            if shift == 0:
                shifted = loop.copy()
            else:
                shifted = librosa.effects.pitch_shift(y=loop, sr=TARGET_SR, n_steps=float(shift))
            cqt_arr = cqt_image(shifted)

            row = make_manifest_row(
                stem, audio_name, source_sha256, split,
                chop_i, int(start), shift, tonic, mode, cqt_arr,
            )
            np.save(output_dir / row["npy"], cqt_arr)
            rows.append(row)

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--labels-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    audio_dir = args.audio_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    label_map: dict[str, tuple[str, str]] = {}
    with args.labels_csv.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            tonic = str(row.get("tonic", "")).strip().lower()
            mode = str(row.get("mode", "")).strip().lower()
            if tonic in NOTE_NAMES and mode in ("maj", "min"):
                label_map[row["filename"]] = (tonic, mode)

    jobs: list[tuple[Path, str, str, int]] = []
    for ext in (".mp3", ".MP3", ".wav", ".WAV"):
        for path in sorted(audio_dir.glob(f"*{ext}")):
            if path.name in label_map:
                tonic, mode = label_map[path.name]
                jobs.append((path, tonic, mode, len(jobs)))

    total = len(jobs)
    expected_total = total * EXPECTED_VARIANTS_PER_FILE
    print(f"{total} files → {expected_total} expected CQT arrays", flush=True)

    manifest_rows: list[dict[str, Any]] = []
    completed = 0
    generated = 0

    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = {}
        for path, tonic, mode, idx in jobs:
            futures[pool.submit(process_or_resume, path, tonic, mode, output_dir, idx)] = path

        for future in as_completed(futures):
            path = futures[future]
            try:
                rows = future.result()
                manifest_rows.extend(rows)
                completed += 1
                if rows:
                    generated += len(rows)
                    tag = f"({len(rows)} variants)"
                    missing = EXPECTED_VARIANTS_PER_FILE - len(rows)
                    if missing:
                        tag += f" WARNING: {missing} missing"
                else:
                    tag = "(skipped)"
                print(f"  [{completed}/{total}] {path.name}  {tag}", flush=True)
            except Exception as exc:
                completed += 1
                print(f"  [{completed}/{total}] FAIL {path.name}: {exc}", flush=True)

    # Atomic write
    fieldnames = [
        "npy", "source_file", "source_sha256", "split", "chop_index",
        "chop_start_sample", "pitch_shift_semitones",
        "original_tonic", "original_mode",
        "shifted_tonic", "shifted_mode", "label_index", "cqt_shape",
    ]
    manifest_path = output_dir / "manifest.csv"
    fd, tmp = tempfile.mkstemp(suffix=".csv", dir=str(output_dir), text=True)
    try:
        with open(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(manifest_rows)
        shutil.move(tmp, manifest_path)
    finally:
        Path(tmp).unlink(missing_ok=True)

    npy_count = len(list(output_dir.glob("*.npy")))
    print(f"\nmanifest: {len(manifest_rows)} rows,  .npy files: {npy_count}")
    if len(manifest_rows) != expected_total:
        print(f"WARNING: expected {expected_total} rows, got {len(manifest_rows)}")
    if len(manifest_rows) != npy_count:
        print(f"WARNING: manifest rows ({len(manifest_rows)}) ≠ .npy files ({npy_count})")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
