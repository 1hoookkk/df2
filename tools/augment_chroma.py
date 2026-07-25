"""Build a compact key-classification matrix from base chroma vectors.

Training rows receive all 12 semitone rotations and clean/±40-cent variants.
Validation rows remain natural and unaugmented so the headline validation score
measures held-out audio rather than synthetic feature transforms.

The output is one contiguous float32 matrix plus a provenance manifest.  This
avoids tens of thousands of tiny .npy files and millions of file opens during
training.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np

NOTE_NAMES = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")
FEATURE_DIM = 12
# Do not use exactly ±50 cents here. In linear feature interpolation, +50 cents
# at class k is bit-identical to -50 cents at class k+1, creating contradictory
# labels for the same vector. ±40 cents stays near the boundary without crossing
# that ambiguity.
DETUNE_CENTS = (-40, 0, 40)


def detune_vector(vec: np.ndarray, cents: int) -> np.ndarray:
    """Approximate a fractional pitch-class rotation and restore unit norm."""
    if cents == 0:
        return np.asarray(vec, dtype=np.float32).copy()
    if abs(cents) >= 100:
        raise ValueError("detune must be strictly within one semitone")

    fraction = abs(cents) / 100.0
    direction = 1 if cents > 0 else -1
    result = (1.0 - fraction) * vec + fraction * np.roll(vec, direction)
    norm = float(np.linalg.norm(result))
    if not np.isfinite(norm) or norm <= 1.0e-12:
        raise ValueError("detune produced an empty or nonfinite vector")
    return np.asarray(result / norm, dtype=np.float32)


def shift_key_index(tonic: str, mode: str, semitones: int) -> int:
    if tonic not in NOTE_NAMES or mode not in ("maj", "min"):
        raise ValueError(f"invalid key label: {tonic}:{mode}")
    return (NOTE_NAMES.index(tonic) + semitones) % 12 + (0 if mode == "maj" else 12)


def variants_for_split(split: str, augment_validation: bool) -> Iterable[tuple[int, int]]:
    if split == "train" or augment_validation:
        return ((shift, cents) for shift in range(12) for cents in DETUNE_CENTS)
    if split == "val":
        return ((0, 0),)
    raise ValueError(f"unsupported split: {split!r}")


def atomic_save_npy(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".npy", dir=str(path.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        np.save(temp_path, array)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "feature_index", "source_file", "source_sha256", "split", "chop_index",
        "chop_start_sample", "original_tonic", "original_mode",
        "pitch_shift_semitones", "detune_cents", "label_index", "feature_dim",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".csv", dir=str(path.parent), text=True)
    try:
        with open(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        shutil.move(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def build_dataset(
    base_manifest: Path,
    npy_dir: Path,
    augment_validation: bool = False,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    with base_manifest.open("r", encoding="utf-8", newline="") as handle:
        base_rows = list(csv.DictReader(handle))
    if not base_rows:
        raise ValueError("base manifest is empty")

    source_chops: set[tuple[str, str]] = set()
    features: list[np.ndarray] = []
    output_rows: list[dict[str, Any]] = []

    for row in base_rows:
        source_file = row.get("source_file", "")
        source_hash = row.get("source_sha256", "")
        split = row.get("split", "")
        chop_index = row.get("chop_index", "")
        if not source_file or not source_hash:
            raise ValueError(f"missing source provenance: {row}")
        key = (source_file, chop_index)
        if key in source_chops:
            raise ValueError(f"duplicate source/chop row: {source_file} chop {chop_index}")
        source_chops.add(key)

        vector_path = npy_dir / row["npy"]
        if not vector_path.is_file():
            raise FileNotFoundError(vector_path)
        vector = np.load(vector_path).astype(np.float32, copy=False)
        if vector.shape != (FEATURE_DIM,):
            raise ValueError(f"expected ({FEATURE_DIM},), got {vector.shape}: {vector_path}")
        if not np.all(np.isfinite(vector)):
            raise ValueError(f"nonfinite base vector: {vector_path}")
        norm = float(np.linalg.norm(vector))
        if abs(norm - 1.0) > 1.0e-4:
            raise ValueError(f"base vector is not unit-normalized ({norm}): {vector_path}")

        tonic = row["original_tonic"]
        mode = row["original_mode"]
        for shift, cents in variants_for_split(split, augment_validation):
            rotated = np.roll(vector, shift)
            feature = detune_vector(rotated, cents)
            feature_index = len(features)
            features.append(feature)
            output_rows.append(
                {
                    "feature_index": feature_index,
                    "source_file": source_file,
                    "source_sha256": source_hash,
                    "split": split,
                    "chop_index": int(chop_index),
                    "chop_start_sample": int(row["chop_start_sample"]),
                    "original_tonic": tonic,
                    "original_mode": mode,
                    "pitch_shift_semitones": shift,
                    "detune_cents": cents,
                    "label_index": shift_key_index(tonic, mode, shift),
                    "feature_dim": FEATURE_DIM,
                }
            )

    matrix = np.stack(features).astype(np.float32, copy=False)
    if not np.all(np.isfinite(matrix)):
        raise ValueError("augmented feature matrix contains nonfinite values")
    return matrix, output_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path, help="Base-vector manifest")
    parser.add_argument("--npy-dir", required=True, type=Path, help="Directory containing base vectors")
    parser.add_argument("--output-features", type=Path, help="Output .npy matrix")
    parser.add_argument("--output-manifest", type=Path, help="Output provenance CSV")
    parser.add_argument(
        "--augment-validation",
        action="store_true",
        help="Also synthesize validation rotations (not recommended for headline metrics)",
    )
    args = parser.parse_args()

    npy_dir = args.npy_dir.resolve()
    output_features = (args.output_features or (npy_dir / "key_features.npy")).resolve()
    output_manifest = (args.output_manifest or (npy_dir / "key_manifest.csv")).resolve()
    matrix, rows = build_dataset(args.manifest.resolve(), npy_dir, args.augment_validation)

    atomic_save_npy(output_features, matrix)
    atomic_write_manifest(output_manifest, rows)

    split_counts: dict[str, int] = {}
    for row in rows:
        split_counts[row["split"]] = split_counts.get(row["split"], 0) + 1
    print(f"features: {matrix.shape}, {matrix.nbytes} bytes")
    print(f"splits: {split_counts}")
    print(f"features: {output_features}")
    print(f"manifest: {output_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
