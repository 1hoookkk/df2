"""Train a compact 24-way key classifier and export RTNeural JSON.

Input is the contiguous 12-bin chroma matrix and provenance manifest produced
by augment_chroma.py. Training uses synthetic rotations; validation remains
natural held-out audio. The command validates provenance/leakage, checkpoints
every epoch, exports the best model, and verifies NumPy/RTNeural-JSON parity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

SEED = 42
DEFAULT_EPOCHS = 50
DEFAULT_BATCH_SIZE = 1024
LEARNING_RATE = 1.0e-3
WEIGHT_DECAY = 1.0e-5
HIDDEN1 = 128
HIDDEN2 = 64
N_CLASSES = 24
FEATURE_DIM = 12

NOTE_NAMES = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")


def label_name(index: int) -> str:
    tonic = NOTE_NAMES[index % 12]
    mode = "maj" if index < 12 else "min"
    return f"{tonic}:{mode}"


def relative_label_index(index: int) -> int:
    """Return relative minor for major, or relative major for minor."""
    tonic = index % 12
    if index < 12:
        return 12 + ((tonic + 9) % 12)
    return (tonic + 3) % 12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class KeyDataset:
    def __init__(self, features: np.ndarray, rows: list[dict[str, Any]], split: str):
        self.samples = [row for row in rows if row["split"] == split]
        indices = np.asarray([int(row["feature_index"]) for row in self.samples], dtype=np.int64)
        self.features = np.ascontiguousarray(features[indices], dtype=np.float32)
        self.labels = np.asarray([int(row["label_index"]) for row in self.samples], dtype=np.int64)

    def __len__(self) -> int:
        return len(self.samples)


class KeyMLP(nn.Module):
    def __init__(self, input_dim: int = FEATURE_DIM):
        super().__init__()
        self.fc1 = nn.Linear(input_dim, HIDDEN1)
        self.fc2 = nn.Linear(HIDDEN1, HIDDEN2)
        self.fc3 = nn.Linear(HIDDEN2, N_CLASSES)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        return self.fc3(x)


def read_and_validate_dataset(features_path: Path, manifest_path: Path) -> tuple[np.ndarray, list[dict[str, Any]]]:
    features = np.load(features_path).astype(np.float32, copy=False)
    if features.ndim != 2 or features.shape[1] != FEATURE_DIM:
        raise ValueError(f"expected feature matrix (N, {FEATURE_DIM}), got {features.shape}")
    if not np.all(np.isfinite(features)):
        raise ValueError("feature matrix contains nonfinite values")

    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != features.shape[0]:
        raise ValueError(f"manifest rows ({len(rows)}) != feature rows ({features.shape[0]})")

    indices: set[int] = set()
    for row in rows:
        feature_index = int(row["feature_index"])
        if feature_index < 0 or feature_index >= len(rows) or feature_index in indices:
            raise ValueError(f"invalid or duplicate feature_index: {feature_index}")
        indices.add(feature_index)
        if row.get("split") not in ("train", "val"):
            raise ValueError(f"invalid split: {row.get('split')!r}")
        if not row.get("source_file") or not row.get("source_sha256"):
            raise ValueError("every row must have source_file and source_sha256")
        label = int(row["label_index"])
        if label < 0 or label >= N_CLASSES:
            raise ValueError(f"invalid label_index: {label}")
        if int(row.get("feature_dim", FEATURE_DIM)) != FEATURE_DIM:
            raise ValueError(f"invalid feature_dim: {row.get('feature_dim')}")

    if indices != set(range(len(rows))):
        raise ValueError("feature_index values must cover every feature row exactly once")

    norms = np.linalg.norm(features, axis=1)
    if not np.allclose(norms, 1.0, atol=1.0e-4):
        raise ValueError(f"feature rows are not unit-normalized: [{norms.min()}, {norms.max()}]")
    return features, rows


def check_no_leakage(train_set: KeyDataset, val_set: KeyDataset) -> None:
    if not train_set.samples or not val_set.samples:
        raise ValueError("train and validation splits must both be nonempty")

    train_sources = {row["source_file"] for row in train_set.samples}
    val_sources = {row["source_file"] for row in val_set.samples}
    source_overlap = train_sources & val_sources
    if source_overlap:
        raise ValueError(f"source leakage: {len(source_overlap)} filenames cross splits")

    train_hashes = {row["source_sha256"] for row in train_set.samples}
    val_hashes = {row["source_sha256"] for row in val_set.samples}
    hash_overlap = train_hashes & val_hashes
    if hash_overlap:
        raise ValueError(f"content leakage: {len(hash_overlap)} hashes cross splits")

    synthetic_val = [
        row for row in val_set.samples
        if int(row.get("pitch_shift_semitones", 0)) != 0 or int(row.get("detune_cents", 0)) != 0
    ]
    if synthetic_val:
        raise ValueError(f"headline validation contains {len(synthetic_val)} synthetic rows")


def class_counts(dataset: KeyDataset) -> Counter[int]:
    return Counter(int(row["label_index"]) for row in dataset.samples)


def train_epoch(
    model: nn.Module,
    features: torch.Tensor,
    labels: torch.Tensor,
    class_weights: torch.Tensor,
    optimizer: torch.optim.Optimizer,
    batch_size: int,
) -> float:
    model.train()
    permutation = torch.randperm(features.shape[0], device=features.device)
    loss_sum = 0.0
    sample_count = 0
    for start in range(0, features.shape[0], batch_size):
        indices = permutation[start : start + batch_size]
        batch_features = features[indices]
        batch_labels = labels[indices]
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(model(batch_features), batch_labels, weight=class_weights)
        loss.backward()
        optimizer.step()
        count = int(indices.numel())
        loss_sum += float(loss.item()) * count
        sample_count += count
    return loss_sum / sample_count


@torch.no_grad()
def evaluate(model: nn.Module, features: torch.Tensor, labels: torch.Tensor) -> dict[str, Any]:
    model.eval()
    correct = 0
    tonic_correct = 0
    mode_correct = 0
    exact_or_relative = 0
    total = 0
    per_class_correct = Counter()
    per_class_total = Counter()

    predictions = model(features).argmax(dim=1)
    for truth, prediction in zip(labels.cpu().tolist(), predictions.cpu().tolist()):
        per_class_total[truth] += 1
        if truth == prediction:
            correct += 1
            per_class_correct[truth] += 1
        if truth % 12 == prediction % 12:
            tonic_correct += 1
        if (truth < 12) == (prediction < 12):
            mode_correct += 1
        if prediction in (truth, relative_label_index(truth)):
            exact_or_relative += 1
        total += 1

    per_class = {
        label_name(index): per_class_correct[index] / count
        for index, count in sorted(per_class_total.items())
    }
    macro_accuracy = sum(per_class.values()) / len(per_class) if per_class else 0.0
    return {
        "accuracy": correct / total if total else 0.0,
        "tonic_accuracy": tonic_correct / total if total else 0.0,
        "mode_accuracy": mode_correct / total if total else 0.0,
        "exact_or_relative_accuracy": exact_or_relative / total if total else 0.0,
        "macro_accuracy_present_classes": macro_accuracy,
        "n": total,
        "per_class": per_class,
    }


def export_rtneural(model: KeyMLP, input_dim: int, output_path: Path) -> None:
    layers: list[dict[str, Any]] = []
    specs = [
        (model.fc1, "relu", HIDDEN1),
        (model.fc2, "relu", HIDDEN2),
        (model.fc3, "softmax", N_CLASSES),
    ]
    for index, (layer, activation, out_size) in enumerate(specs):
        in_size = input_dim if index == 0 else specs[index - 1][2]
        weights = layer.weight.detach().cpu().numpy()
        bias = layer.bias.detach().cpu().numpy()
        if weights.shape != (out_size, in_size):
            raise ValueError(f"unexpected dense weight shape: {weights.shape}")
        layers.append(
            {
                "type": "dense",
                "activation": activation,
                "shape": [None, out_size],
                "weights": [weights.T.tolist(), bias.tolist()],
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    model_dict = {"in_shape": [None, input_dim], "layers": layers}
    output_path.write_text(json.dumps(model_dict, indent=2), encoding="utf-8")


def rtneural_json_forward(features: np.ndarray, model_path: Path) -> np.ndarray:
    model = json.loads(model_path.read_text(encoding="utf-8"))
    values = np.asarray(features, dtype=np.float64)
    for layer in model["layers"]:
        kernel = np.asarray(layer["weights"][0], dtype=np.float64)
        bias = np.asarray(layer["weights"][1], dtype=np.float64)
        values = values @ kernel + bias
        activation = layer.get("activation", "")
        if activation == "relu":
            values = np.maximum(values, 0.0)
        elif activation == "softmax":
            shifted = values - values.max(axis=1, keepdims=True)
            exp_values = np.exp(shifted)
            values = exp_values / exp_values.sum(axis=1, keepdims=True)
        elif activation:
            raise ValueError(f"unsupported activation in exported model: {activation}")
    return values


@torch.no_grad()
def verify_export_parity(model: KeyMLP, features: np.ndarray, output_path: Path) -> float:
    sample = np.asarray(features[: min(256, len(features))], dtype=np.float32)
    model = model.to("cpu").eval()
    torch_probabilities = torch.softmax(model(torch.from_numpy(sample)), dim=1).numpy()
    json_probabilities = rtneural_json_forward(sample, output_path)
    max_error = float(np.max(np.abs(torch_probabilities - json_probabilities)))
    if max_error > 1.0e-5:
        raise ValueError(f"RTNeural JSON parity failed: max abs error {max_error}")
    return max_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()

    if args.epochs <= 0:
        raise SystemExit("--epochs must be positive")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")

    torch.manual_seed(SEED)
    np.random.seed(SEED)
    features_path = args.features.resolve()
    manifest_path = args.manifest.resolve()
    output_path = args.output.resolve()
    report_path = (args.report or output_path.with_suffix(".metrics.json")).resolve()
    checkpoint_dir = (args.checkpoint_dir or output_path.parent / "checkpoints").resolve()
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    features, rows = read_and_validate_dataset(features_path, manifest_path)
    train_set = KeyDataset(features, rows, "train")
    val_set = KeyDataset(features, rows, "val")
    check_no_leakage(train_set, val_set)

    device = torch.device(args.device)
    print(f"device: {device}")
    print(f"train: {len(train_set)}, val: {len(val_set)}, input_dim: {features.shape[1]}")
    print(
        f"sources: train={len({row['source_file'] for row in train_set.samples})}, "
        f"val={len({row['source_file'] for row in val_set.samples})}; no leakage"
    )

    train_counts = class_counts(train_set)
    val_counts = class_counts(val_set)
    print("validation class distribution:")
    for index in range(N_CLASSES):
        print(f"  {label_name(index):>6s}: {val_counts.get(index, 0):3d}")

    missing_train_classes = [index for index in range(N_CLASSES) if train_counts[index] == 0]
    if missing_train_classes:
        raise ValueError(f"training split is missing classes: {missing_train_classes}")
    class_weights = torch.tensor(
        [len(train_set) / (N_CLASSES * train_counts[index]) for index in range(N_CLASSES)],
        dtype=torch.float32,
        device=device,
    )
    train_features = torch.from_numpy(train_set.features).to(device)
    train_labels = torch.from_numpy(train_set.labels).to(device)
    val_features = torch.from_numpy(val_set.features).to(device)
    val_labels = torch.from_numpy(val_set.labels).to(device)

    model = KeyMLP(features.shape[1]).to(device)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    print(f"params: {parameter_count}")
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)

    best_accuracy = -1.0
    best_epoch = 0
    best_checkpoint: Path | None = None
    history: list[dict[str, Any]] = []

    for epoch in range(1, args.epochs + 1):
        train_loss = train_epoch(
            model, train_features, train_labels, class_weights, optimizer, args.batch_size
        )
        val_metrics = evaluate(model, val_features, val_labels)
        epoch_record = {"epoch": epoch, "train_loss": train_loss, "validation": val_metrics}
        history.append(epoch_record)
        checkpoint_path = checkpoint_dir / f"epoch{epoch:03d}.pt"
        torch.save(
            {
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "validation": val_metrics,
            },
            checkpoint_path,
        )

        if val_metrics["accuracy"] > best_accuracy:
            best_accuracy = float(val_metrics["accuracy"])
            best_epoch = epoch
            best_checkpoint = checkpoint_path

        print(
            f"epoch {epoch:3d} loss={train_loss:.4f} "
            f"val={val_metrics['accuracy']:.3f} "
            f"macro={val_metrics['macro_accuracy_present_classes']:.3f} "
            f"tonic={val_metrics['tonic_accuracy']:.3f} "
            f"mode={val_metrics['mode_accuracy']:.3f}",
            flush=True,
        )

    if best_checkpoint is None:
        raise RuntimeError("training produced no checkpoint")
    checkpoint = torch.load(best_checkpoint, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    final_metrics = evaluate(model, val_features, val_labels)

    export_rtneural(model, features.shape[1], output_path)
    parity_error = verify_export_parity(model, features, output_path)
    report = {
        "schema_version": 1,
        "best_epoch": best_epoch,
        "checkpoint": str(best_checkpoint),
        "dataset": {
            "features": str(features_path),
            "features_sha256": sha256_file(features_path),
            "manifest": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "train_rows": len(train_set),
            "validation_rows": len(val_set),
            "train_sources": len({row["source_file"] for row in train_set.samples}),
            "validation_sources": len({row["source_file"] for row in val_set.samples}),
            "validation_policy": "natural held-out base chroma only",
        },
        "feature_contract": {
            "dimension": FEATURE_DIM,
            "ordering": list(NOTE_NAMES),
            "normalization": "L2 unit norm",
        },
        "labels": [label_name(index) for index in range(N_CLASSES)],
        "model": {
            "architecture": [features.shape[1], HIDDEN1, HIDDEN2, N_CLASSES],
            "parameters": parameter_count,
            "rtneural_json": str(output_path),
            "rtneural_json_sha256": sha256_file(output_path),
            "numpy_export_parity_max_abs_error": parity_error,
        },
        "validation": final_metrics,
        "history": history,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"best epoch: {best_epoch}, val accuracy: {final_metrics['accuracy']:.4f}")
    print(f"RTNeural JSON parity max abs error: {parity_error:.3e}")
    print(f"model: {output_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
