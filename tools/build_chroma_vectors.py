"""Compute time-pooled chroma vectors from audio. Fast: one CQT per chop, no pitch-shift.

Output: 12-dim L2-normalized chroma vectors + manifest.
Semitone rotation and detune augmentation happen in feature space (augment_chroma.py).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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
N_CHOPS = 4
CQT_BINS_PER_OCTAVE = 12
CQT_OCTAVES = 7
CQT_N_BINS = CQT_BINS_PER_OCTAVE * CQT_OCTAVES
CQT_HOP_LENGTH = 512
FMIN = librosa.note_to_hz("C2")
SEED = 42


def load_audio(path: Path) -> np.ndarray:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar",
        str(TARGET_SR), "pipe:1",
    ]
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)


def chunk_indices(total: int, chunk_len: int, rng: np.random.Generator) -> list[int]:
    max_start = total - chunk_len
    if max_start < 0:
        return [0] * N_CHOPS
    return sorted(int(rng.integers(0, max_start + 1)) for _ in range(N_CHOPS))


def chroma_vector(audio: np.ndarray) -> np.ndarray:
    """CQT → fold octaves → time-mean-pool → L2-normalize → 12-dim."""
    cqt = np.abs(
        librosa.cqt(audio, sr=TARGET_SR, hop_length=CQT_HOP_LENGTH,
                     n_bins=CQT_N_BINS, bins_per_octave=CQT_BINS_PER_OCTAVE, fmin=FMIN)
    ).astype(np.float32)
    # Fold 7 octaves to 12-bin chroma: (84, T) → (7, 12, T) → sum → (12, T)
    chroma = cqt.reshape(CQT_OCTAVES, CQT_BINS_PER_OCTAVE, -1).sum(axis=0)
    vec = np.mean(chroma, axis=1)
    norm = float(np.linalg.norm(vec))
    if norm > 1e-12:
        vec /= norm
    return vec.astype(np.float32)


def process_one_file(
    audio_dir: str, output_dir: str, sf: str, tonic: str, mode: str, file_index: int,
) -> list[dict[str, Any]]:
    out = Path(output_dir)
    stem = Path(sf).stem
    source_sha256 = hashlib.sha256((Path(audio_dir) / sf).read_bytes()).hexdigest()
    split_byte = hashlib.sha256(sf.encode()).digest()[0]
    split = "train" if split_byte < 204 else "val"

    # Check if all 4 chops exist. Decode once even on resume so the manifest can
    # reproduce the deterministic chop locations instead of inventing zeros.
    all_exist = all((out / f"{stem}_chop{c}.npy").exists() for c in range(N_CHOPS))
    if all_exist:
        audio = load_audio(Path(audio_dir) / sf)
        chunk_len = int(CHUNK_SECONDS * TARGET_SR)
        rng = np.random.default_rng(SEED + file_index)
        starts = chunk_indices(audio.size, chunk_len, rng)
        rows = []
        for c in range(N_CHOPS):
            vec = np.load(out / f"{stem}_chop{c}.npy")
            rows.append({
                "npy": f"{stem}_chop{c}.npy",
                "source_file": sf, "source_sha256": source_sha256,
                "split": split, "chop_index": c, "chop_start_sample": int(starts[c]),
                "original_tonic": tonic, "original_mode": mode,
                "label_index": NOTE_NAMES.index(tonic) + (0 if mode == "maj" else 12),
                "feature_dim": vec.shape[0],
            })
        return rows

    audio = load_audio(Path(audio_dir) / sf)
    if audio.size < int(TARGET_SR * 0.5):
        return []

    chunk_len = int(CHUNK_SECONDS * TARGET_SR)
    rng = np.random.default_rng(SEED + file_index)
    starts = chunk_indices(audio.size, chunk_len, rng)

    rows = []
    for c, start in enumerate(starts):
        loop = audio[start : start + chunk_len]
        if loop.size < chunk_len:
            loop = np.pad(loop, (0, chunk_len - loop.size))
        vec = chroma_vector(loop)
        npy_name = f"{stem}_chop{c}.npy"
        np.save(out / npy_name, vec)
        rows.append({
            "npy": npy_name, "source_file": sf, "source_sha256": source_sha256,
            "split": split, "chop_index": c, "chop_start_sample": int(start),
            "original_tonic": tonic, "original_mode": mode,
            "label_index": NOTE_NAMES.index(tonic) + (0 if mode == "maj" else 12),
            "feature_dim": int(vec.shape[0]),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--labels-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    audio_dir = str(args.audio_dir.resolve())
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    label_map: dict[str, tuple[str, str]] = {}
    with args.labels_csv.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            label_map[row["filename"]] = (row["tonic"], row["mode"])

    jobs = []
    audio_paths = sorted(
        (p for p in Path(audio_dir).iterdir() if p.is_file() and p.suffix.lower() in (".mp3", ".wav")),
        key=lambda p: p.name.lower(),
    )
    for p in audio_paths:
        if p.name in label_map:
            jobs.append((p.name, *label_map[p.name], len(jobs)))

    total = len(jobs)
    expected = total * N_CHOPS
    print(f"{total} files → {expected} expected vectors")

    manifest_rows: list[dict[str, Any]] = []
    completed = 0

    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = {}
        for sf, tonic, mode, idx in jobs:
            fut = pool.submit(process_one_file, audio_dir, str(output_dir), sf, tonic, mode, idx)
            futures[fut] = sf

        for future in as_completed(futures):
            sf = futures[future]
            try:
                rows = future.result()
                manifest_rows.extend(rows)
                completed += 1
                print(f"  [{completed}/{total}] {sf}  ({len(rows)} vectors)", flush=True)
            except Exception as exc:
                completed += 1
                print(f"  [{completed}/{total}] FAIL {sf}: {exc}", flush=True)

    fieldnames = [
        "npy", "source_file", "source_sha256", "split", "chop_index",
        "chop_start_sample", "original_tonic", "original_mode",
        "label_index", "feature_dim",
    ]
    manifest_path = output_dir / "manifest.csv"
    fd, tmp = tempfile.mkstemp(suffix=".csv", dir=str(output_dir), text=True)
    try:
        with open(fd, "w", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(manifest_rows)
        shutil.move(tmp, manifest_path)
    finally:
        Path(tmp).unlink(missing_ok=True)

    print(f"\nmanifest: {len(manifest_rows)} rows, {len(list(output_dir.glob('*.npy')))} .npy files")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
