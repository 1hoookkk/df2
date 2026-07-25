"""Build deployable 12-bin FFT-chroma vectors from labeled audio.

The frontend is deliberately small enough to reproduce in the JUCE plugin:
the first 131072 samples of a six-second 22.05 kHz window, one symmetric-Hann
FFT, 40-5000 Hz, nearest-MIDI pitch-class folding, and L2 normalization. There
is no HPSS, median filter, or frame loop.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

TARGET_SR = 22_050
CHUNK_SECONDS = 6.0
CHUNK_SAMPLES = int(TARGET_SR * CHUNK_SECONDS)
N_CHOPS = 4
FFT_SIZE = 131_072
MIN_HZ = 40.0
MAX_HZ = 5000.0
SEED = 42
NOTE_NAMES = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")

_WINDOW = 0.5 - 0.5 * np.cos(
    2.0 * np.pi * np.arange(FFT_SIZE, dtype=np.float64) / (FFT_SIZE - 1)
)
_FREQUENCIES = np.arange(FFT_SIZE // 2 + 1, dtype=np.float64) * TARGET_SR / FFT_SIZE
_AUDIBLE = (_FREQUENCIES >= MIN_HZ) & (_FREQUENCIES <= MAX_HZ)
_PITCH_CLASSES = np.mod(
    np.floor(69.0 + 12.0 * np.log2(_FREQUENCIES[_AUDIBLE] / 440.0) + 0.5).astype(np.int32),
    12,
)


def load_audio(path: Path) -> np.ndarray:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar",
        str(TARGET_SR), "pipe:1",
    ]
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio = np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)
    if audio.size == 0 or not np.all(np.isfinite(audio)):
        raise ValueError(f"decoded audio is empty or nonfinite: {path}")
    return audio


def chunk_indices(total: int, rng: np.random.Generator) -> list[int]:
    max_start = total - CHUNK_SAMPLES
    if max_start < 0:
        return [0] * N_CHOPS
    return sorted(int(rng.integers(0, max_start + 1)) for _ in range(N_CHOPS))


def fft_chroma_vector(audio: np.ndarray) -> np.ndarray:
    if audio.shape != (CHUNK_SAMPLES,):
        raise ValueError(f"expected exactly {CHUNK_SAMPLES} samples, got {audio.shape}")
    if not np.all(np.isfinite(audio)):
        raise ValueError("audio contains nonfinite samples")

    analysis = np.asarray(audio[:FFT_SIZE], dtype=np.float64)
    centred = analysis - float(np.mean(analysis))
    magnitude = np.abs(np.fft.rfft(centred * _WINDOW))[_AUDIBLE]
    vector = np.asarray(
        [magnitude[_PITCH_CLASSES == pitch_class].sum() for pitch_class in range(12)],
        dtype=np.float64,
    )
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 1.0e-12:
        raise ValueError("no finite tonal chroma energy")
    return np.asarray(vector / norm, dtype=np.float32)


def process_one_file(
    audio_dir: str, output_dir: str, source_file: str, tonic: str, mode: str, file_index: int,
) -> list[dict[str, Any]]:
    source_path = Path(audio_dir) / source_file
    output_path = Path(output_dir)
    stem = Path(source_file).stem
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    split = "train" if hashlib.sha256(source_file.encode()).digest()[0] < 204 else "val"
    audio = load_audio(source_path)
    rng = np.random.default_rng(SEED + file_index)
    starts = chunk_indices(audio.size, rng)
    rows: list[dict[str, Any]] = []

    for chop_index, start in enumerate(starts):
        name = f"{stem}_chop{chop_index}.npy"
        vector_path = output_path / name
        if vector_path.is_file():
            vector = np.load(vector_path).astype(np.float32, copy=False)
            if vector.shape != (12,) or not np.all(np.isfinite(vector)):
                raise ValueError(f"invalid resumable vector: {vector_path}")
        else:
            clip = audio[start : start + CHUNK_SAMPLES]
            if clip.size < CHUNK_SAMPLES:
                clip = np.pad(clip, (0, CHUNK_SAMPLES - clip.size))
            vector = fft_chroma_vector(clip)
            fd, temp_name = tempfile.mkstemp(suffix=".npy", dir=str(output_path))
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                np.save(temp_path, vector)
                temp_path.replace(vector_path)
            finally:
                temp_path.unlink(missing_ok=True)

        rows.append(
            {
                "npy": name,
                "source_file": source_file,
                "source_sha256": source_sha256,
                "split": split,
                "chop_index": chop_index,
                "chop_start_sample": int(start),
                "original_tonic": tonic,
                "original_mode": mode,
                "label_index": NOTE_NAMES.index(tonic) + (0 if mode == "maj" else 12),
                "feature_dim": int(vector.shape[0]),
            }
        )
    return rows


def atomic_write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "npy", "source_file", "source_sha256", "split", "chop_index",
        "chop_start_sample", "original_tonic", "original_mode", "label_index", "feature_dim",
    ]
    fd, temp_name = tempfile.mkstemp(suffix=".csv", dir=str(path.parent), text=True)
    try:
        with open(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda row: (row["source_file"].lower(), row["chop_index"])))
        shutil.move(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--labels-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")

    audio_dir = args.audio_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with args.labels_csv.open("r", encoding="utf-8", newline="") as handle:
        labels = {row["filename"]: (row["tonic"], row["mode"]) for row in csv.DictReader(handle)}

    paths = sorted(
        (path for path in audio_dir.iterdir() if path.is_file() and path.suffix.lower() in (".mp3", ".wav")),
        key=lambda path: path.name.lower(),
    )
    jobs = [(path.name, *labels[path.name], index) for index, path in enumerate(paths) if path.name in labels]
    print(f"{len(jobs)} files -> {len(jobs) * N_CHOPS} expected vectors")
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_one_file, str(audio_dir), str(output_dir), *job): job[0] for job in jobs
        }
        for completed, future in enumerate(as_completed(futures), 1):
            source_file = futures[future]
            try:
                result = future.result()
                rows.extend(result)
                print(f"  [{completed}/{len(jobs)}] {source_file} ({len(result)} vectors)", flush=True)
            except Exception as error:
                print(f"  [{completed}/{len(jobs)}] FAIL {source_file}: {error}", flush=True)

    manifest_path = output_dir / "manifest.csv"
    atomic_write_manifest(manifest_path, rows)
    vector_count = len(list(output_dir.glob("*.npy")))
    print(f"manifest: {len(rows)} rows, {vector_count} .npy files")
    print(f"manifest: {manifest_path}")
    if len(rows) != len(jobs) * N_CHOPS or vector_count != len(rows):
        raise SystemExit("dataset is incomplete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
