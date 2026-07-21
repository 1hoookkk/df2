from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from tools.augment_chroma import build_dataset, detune_vector, shift_key_index
from tools.build_fft_chroma_vectors import CHUNK_SAMPLES, fft_chroma_vector
from tools.train_key_model import (
    KeyMLP,
    export_rtneural,
    relative_label_index,
    verify_export_parity,
)


class KeyModelPipelineTests(unittest.TestCase):
    def test_fft_chroma_frontend_finds_sine_pitch_class(self) -> None:
        sample_index = np.arange(CHUNK_SAMPLES, dtype=np.float64)
        for frequency, expected in ((261.625565, 0), (440.0, 9), (739.988845, 6)):
            audio = np.sin(2.0 * np.pi * frequency * sample_index / 22_050.0)
            vector = fft_chroma_vector(audio)
            self.assertEqual(int(np.argmax(vector)), expected)
            self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0, places=5)

    def test_relative_key_indices_wrap_and_change_mode(self) -> None:
        self.assertEqual(relative_label_index(0), 21)   # C major -> A minor
        self.assertEqual(relative_label_index(11), 20)  # B major -> G# minor
        self.assertEqual(relative_label_index(12), 3)   # C minor -> D# major
        self.assertEqual(relative_label_index(21), 0)   # A minor -> C major

    def test_detune_preserves_shape_finiteness_and_norm(self) -> None:
        vector = np.zeros(12, dtype=np.float32)
        vector[0] = 1.0
        for cents in (-40, 0, 40):
            result = detune_vector(vector, cents)
            self.assertEqual(result.shape, (12,))
            self.assertTrue(np.all(np.isfinite(result)))
            self.assertAlmostEqual(float(np.linalg.norm(result)), 1.0, places=6)

    def test_compact_dataset_augments_train_only_without_duplicate_clean_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            train = np.zeros(12, dtype=np.float32)
            train[0] = 1.0
            val = np.zeros(12, dtype=np.float32)
            val[9] = 1.0
            np.save(root / "train.npy", train)
            np.save(root / "val.npy", val)

            manifest = root / "manifest.csv"
            fieldnames = [
                "npy", "source_file", "source_sha256", "split", "chop_index",
                "chop_start_sample", "original_tonic", "original_mode",
                "label_index", "feature_dim",
            ]
            rows = [
                {
                    "npy": "train.npy", "source_file": "train.mp3", "source_sha256": "a" * 64,
                    "split": "train", "chop_index": 0, "chop_start_sample": 12,
                    "original_tonic": "c", "original_mode": "maj", "label_index": 0,
                    "feature_dim": 12,
                },
                {
                    "npy": "val.npy", "source_file": "val.mp3", "source_sha256": "b" * 64,
                    "split": "val", "chop_index": 0, "chop_start_sample": 34,
                    "original_tonic": "a", "original_mode": "min", "label_index": 21,
                    "feature_dim": 12,
                },
            ]
            with manifest.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            matrix, output_rows = build_dataset(manifest, root)
            self.assertEqual(matrix.shape, (37, 12))
            train_rows = [row for row in output_rows if row["split"] == "train"]
            val_rows = [row for row in output_rows if row["split"] == "val"]
            self.assertEqual(len(train_rows), 36)
            self.assertEqual(len(val_rows), 1)
            self.assertEqual(
                sum(row["pitch_shift_semitones"] == 0 and row["detune_cents"] == 0 for row in train_rows),
                1,
            )
            self.assertEqual(val_rows[0]["label_index"], shift_key_index("a", "min", 0))
            self.assertEqual(np.unique(matrix[:36], axis=0).shape[0], 36)

    def test_rtneural_json_matches_pytorch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            torch.manual_seed(123)
            model = KeyMLP()
            features = np.random.default_rng(123).normal(size=(32, 12)).astype(np.float32)
            output = Path(temp) / "model.json"
            export_rtneural(model, 12, output)
            self.assertLess(verify_export_parity(model, features, output), 1.0e-5)


if __name__ == "__main__":
    unittest.main()
