"""Offline evidence gate for a stable track-key detector.

This is deliberately not runtime DSP.  It prepares a licensed, labeled subset
of the Freesound Loop Dataset and evaluates a small STFT/chroma key prototype
over half-, one-, and two-bar windows.  Runtime behavior should not be changed
until this benchmark supports it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import stft


SCHEMA_VERSION = 1
TARGET_SR = 22_050
NOTE_NAMES = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")
VALID_MODES = {"maj", "min"}
FSLD_DOI = "10.5281/zenodo.3967852"
FSLD_RECORD = "https://zenodo.org/records/3967852"

# Krumhansl-Kessler key profiles.  They are fixed before evaluation; no
# thresholds or profile weights are learned from the evaluation examples.
MAJOR_PROFILE = np.asarray(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
    dtype=np.float64,
)
MINOR_PROFILE = np.asarray(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    dtype=np.float64,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def normalized_label(tonic: str, mode: str) -> tuple[str, str] | None:
    tonic = tonic.strip().lower().replace("db", "c#").replace("eb", "d#")
    tonic = tonic.replace("gb", "f#").replace("ab", "g#").replace("bb", "a#")
    mode = mode.strip().lower()
    if tonic not in NOTE_NAMES or mode not in VALID_MODES:
        return None
    return tonic, mode


def parse_bpm(annotation: dict[str, Any], metadata: dict[str, Any]) -> float | None:
    values = [annotation.get("bpm"), (metadata.get("annotations") or {}).get("bpm")]
    for value in values:
        try:
            bpm = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(bpm) and 30.0 <= bpm <= 300.0:
            return bpm
    return None


def license_class(url: str) -> str | None:
    value = (url or "").lower()
    if "publicdomain/zero" in value:
        return "cc0"
    if "/licenses/by-nc/" in value:
        return "cc-by-nc"
    if "/licenses/by/" in value:
        return "cc-by"
    return None


def annotation_rows(root: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    rows: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    for path in sorted(root.glob("*/sound-*.json")):
        sound_id = path.stem.removeprefix("sound-")
        rows[sound_id].append((path, json.loads(path.read_text(encoding="utf-8"))))
    return rows


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "TRENCH-key-benchmark/1"})
    part = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    part.replace(path)


def prepare_fsld(args: argparse.Namespace) -> int:
    annotations_root = args.annotations.resolve()
    metadata_path = args.metadata.resolve()
    output_dir = args.output.resolve()
    audio_dir = output_dir / "audio"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    grouped = annotation_rows(annotations_root)
    samples: list[dict[str, Any]] = []
    rejected = Counter()

    for sound_id in sorted(grouped, key=lambda value: int(value)):
        source_rows = grouped[sound_id]
        labels: list[tuple[str, str]] = []
        genres: set[str] = set()
        instrumentations: list[dict[str, bool]] = []
        accepted_rows: list[tuple[Path, dict[str, Any]]] = []
        for path, annotation in source_rows:
            genres.update(str(item).lower() for item in (annotation.get("genres") or []))
            label = normalized_label(str(annotation.get("key", "")), str(annotation.get("mode", "")))
            if label is not None and not annotation.get("discard", False):
                labels.append(label)
                accepted_rows.append((path, annotation))
                instrumentations.append(annotation.get("instrumentation") or {})

        if args.genre.lower() not in genres:
            continue
        if not labels:
            rejected["missing_valid_key_or_mode"] += 1
            continue
        if len(set(labels)) != 1:
            rejected["annotator_disagreement"] += 1
            continue

        item = metadata.get(sound_id)
        if not isinstance(item, dict):
            rejected["missing_metadata"] += 1
            continue
        license_name = license_class(str(item.get("license", "")))
        if license_name is None:
            rejected["unsupported_license"] += 1
            continue
        preview_url = str(item.get("preview_url", "")).replace("http://", "https://", 1)
        if not preview_url:
            rejected["missing_preview"] += 1
            continue

        text_fields = [item.get("name"), item.get("description"), item.get("pack_name")]
        text_fields.extend(item.get("tags") or [])
        searchable = " ".join(str(value) for value in text_fields if value).lower()
        explicit_trap = "trap" in searchable
        if args.trap_only and not explicit_trap:
            continue

        representative = accepted_rows[0][1]
        bpm = parse_bpm(representative, item)
        if bpm is None:
            rejected["missing_valid_bpm"] += 1
            continue
        tonic, mode = labels[0]
        extension = Path(urllib.parse.urlparse(preview_url).path).suffix or ".mp3"
        audio_path = audio_dir / f"{sound_id}{extension}"
        if not audio_path.exists():
            print(f"download {sound_id}: {item.get('name', '')}", flush=True)
            try:
                download(preview_url, audio_path)
            except Exception as exc:  # keep acquisition failures visible and isolated
                rejected[f"download_failed:{type(exc).__name__}"] += 1
                continue

        split_byte = hashlib.sha256(f"fsld:{sound_id}".encode("ascii")).digest()[0]
        split = "calibration" if split_byte < 64 else "evaluation"
        samples.append(
            {
                "audio": str(Path("audio") / audio_path.name).replace("\\", "/"),
                "audio_sha256": sha256_file(audio_path),
                "bpm": bpm,
                "explicit_trap": explicit_trap,
                "freesound_url": f"https://freesound.org/s/{sound_id}/",
                "genres": sorted(genres),
                "ground_truth": {"mode": mode, "tonic": tonic},
                "instrumentation": instrumentations[0] if instrumentations else {},
                "label_sources": [
                    str(path.relative_to(annotations_root)).replace("\\", "/")
                    for path, _ in accepted_rows
                ],
                "license": {"class": license_name, "url": item.get("license")},
                "name": item.get("name", ""),
                "preview_url": preview_url,
                "sound_id": int(sound_id),
                "split": split,
                "username": item.get("username", ""),
            }
        )
        if args.limit and len(samples) >= args.limit:
            break

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset": {
            "annotations_sha256": sha256_file(args.annotations_zip.resolve())
            if args.annotations_zip
            else None,
            "doi": FSLD_DOI,
            "metadata_sha256": sha256_file(metadata_path),
            "name": "Freesound Loop Dataset",
            "record_url": FSLD_RECORD,
            "selection": {
                "genre": args.genre.lower(),
                "license_policy": "CC0, CC BY, or CC BY-NC; benchmark only, never shipped",
                "requires_expert_tonic_and_mode": True,
                "trap_only": bool(args.trap_only),
            },
        },
        "rejected": dict(sorted(rejected.items())),
        "samples": samples,
    }
    manifest_path = output_dir / "manifest.json"
    write_json(manifest_path, manifest)
    print(
        f"wrote {manifest_path}: {len(samples)} samples, "
        f"{sum(sample['explicit_trap'] for sample in samples)} explicitly tagged trap"
    )
    return 0 if samples else 1


def decode_audio(path: Path, sample_rate: int = TARGET_SR) -> np.ndarray:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar",
        str(sample_rate), "pipe:1",
    ]
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio = np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)
    if audio.size == 0 or not np.all(np.isfinite(audio)):
        raise ValueError(f"decoded audio is empty or nonfinite: {path}")
    return audio


def repeat_to_length(audio: np.ndarray, length: int) -> np.ndarray:
    if audio.size >= length:
        return audio[:length]
    repeats = math.ceil(length / audio.size)
    return np.tile(audio, repeats)[:length]


def chroma_vector(audio: np.ndarray, sample_rate: int = TARGET_SR) -> np.ndarray:
    if audio.size < 4096:
        audio = repeat_to_length(audio, 4096)
    audio = audio - float(np.mean(audio))
    frequencies, _, spectrum = stft(
        audio,
        fs=sample_rate,
        window="hann",
        nperseg=4096,
        noverlap=3584,
        boundary=None,
        padded=False,
    )
    magnitude = np.abs(spectrum)
    # A compact HPSS-like soft mask: sustained bins survive the temporal median;
    # broadband transients survive the frequency median and are de-emphasized.
    harmonic = median_filter(magnitude, size=(1, 17), mode="nearest")
    percussive = median_filter(magnitude, size=(17, 1), mode="nearest")
    magnitude *= harmonic / (harmonic + percussive + 1.0e-12)
    audible = (frequencies >= 40.0) & (frequencies <= 5000.0)
    frequencies = frequencies[audible]
    magnitude = magnitude[audible]
    midi = np.rint(69.0 + 12.0 * np.log2(frequencies / 440.0)).astype(np.int32)
    pitch_classes = np.mod(midi, 12)
    chroma = np.zeros((12, magnitude.shape[1]), dtype=np.float64)
    for pitch_class in range(12):
        chroma[pitch_class] = magnitude[pitch_classes == pitch_class].sum(axis=0)
    frame_norm = np.linalg.norm(chroma, axis=0, keepdims=True)
    chroma /= frame_norm + 1.0e-12
    vector = np.mean(chroma, axis=1)
    norm = float(np.linalg.norm(vector))
    if norm <= 1.0e-12:
        raise ValueError("no tonal chroma energy")
    return vector / norm


def score_chroma(chroma: np.ndarray) -> list[dict[str, Any]]:
    scores: list[dict[str, Any]] = []
    for mode, profile in (("maj", MAJOR_PROFILE), ("min", MINOR_PROFILE)):
        for tonic, name in enumerate(NOTE_NAMES):
            score = float(np.corrcoef(chroma, np.roll(profile, tonic))[0, 1])
            scores.append({"mode": mode, "score": score, "tonic": name})
    scores.sort(key=lambda row: (-row["score"], row["tonic"], row["mode"]))
    return scores


def classify_error(truth: tuple[str, str], predicted: tuple[str, str]) -> str:
    if truth == predicted:
        return "exact"
    true_tonic = NOTE_NAMES.index(truth[0])
    predicted_tonic = NOTE_NAMES.index(predicted[0])
    if truth[1] == "maj" and predicted == (NOTE_NAMES[(true_tonic + 9) % 12], "min"):
        return "relative_major_minor"
    if truth[1] == "min" and predicted == (NOTE_NAMES[(true_tonic + 3) % 12], "maj"):
        return "relative_major_minor"
    if true_tonic == predicted_tonic:
        return "mode_only"
    return "other"


def detect_window(audio: np.ndarray, bpm: float, bars: float) -> dict[str, Any]:
    seconds = bars * 4.0 * 60.0 / bpm
    window = repeat_to_length(audio, max(4096, int(round(seconds * TARGET_SR))))
    chroma = chroma_vector(window)
    scores = score_chroma(chroma)
    best, second = scores[:2]
    return {
        "bars": bars,
        "chroma": [round(float(value), 9) for value in chroma],
        "confidence_margin": round(best["score"] - second["score"], 9),
        "prediction": {"mode": best["mode"], "tonic": best["tonic"]},
        "score": round(best["score"], 9),
        "seconds": round(seconds, 6),
        "second": {
            "mode": second["mode"],
            "score": round(second["score"], 9),
            "tonic": second["tonic"],
        },
    }


def choose_threshold(rows: list[dict[str, Any]], target_precision: float) -> dict[str, Any]:
    calibration = [row for row in rows if row["split"] == "calibration" and row["bars"] == 2.0]
    if not calibration:
        return {"coverage": 0.0, "precision": None, "threshold": None}
    candidates = sorted({row["confidence_margin"] for row in calibration})
    best: tuple[float, float, float] | None = None
    for threshold in candidates:
        accepted = [row for row in calibration if row["confidence_margin"] >= threshold]
        if len(accepted) < 5:
            continue
        precision = sum(row["error"] == "exact" for row in accepted) / len(accepted)
        coverage = len(accepted) / len(calibration)
        if precision >= target_precision:
            candidate = (coverage, precision, threshold)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return {"coverage": 0.0, "precision": None, "threshold": None}
    return {"coverage": best[0], "precision": best[1], "threshold": best[2]}


def summarize(rows: list[dict[str, Any]], threshold: float | None) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for split in ("calibration", "evaluation"):
        for bars in (0.5, 1.0, 2.0):
            selected = [row for row in rows if row["split"] == split and row["bars"] == bars]
            if not selected:
                continue
            accepted = selected if threshold is None else [
                row for row in selected if row["confidence_margin"] >= threshold
            ]
            key = f"{split}:{bars:g}_bar"
            summaries[key] = {
                "accepted": len(accepted),
                "coverage": len(accepted) / len(selected),
                "exact_accuracy": (
                    sum(row["error"] == "exact" for row in accepted) / len(accepted)
                    if accepted else None
                ),
                "n": len(selected),
                "relative_major_minor": sum(
                    row["error"] == "relative_major_minor" for row in accepted
                ),
                "tonic_accuracy": (
                    sum(row["truth"]["tonic"] == row["prediction"]["tonic"] for row in accepted)
                    / len(accepted)
                    if accepted else None
                ),
            }
    return summaries


def group_summary(rows: list[dict[str, Any]], split: str, bars: float) -> dict[str, Any]:
    selected = [row for row in rows if row["split"] == split and row["bars"] == bars]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        groups["all"].append(row)
        if row["explicit_trap"]:
            groups["explicit_trap"].append(row)
        instrumentation = row["instrumentation"]
        tonal = any(instrumentation.get(name, False) for name in ("bass", "chords", "melody", "vocal"))
        if instrumentation.get("percussion", False) and not tonal:
            groups["percussion_only"].append(row)
        if tonal:
            groups["tonal"].append(row)
        if instrumentation.get("bass", False):
            groups["bass_present"].append(row)
    result: dict[str, Any] = {}
    for name, group in sorted(groups.items()):
        result[name] = {
            "exact_accuracy": sum(row["error"] == "exact" for row in group) / len(group),
            "n": len(group),
            "tonic_accuracy": sum(
                row["truth"]["tonic"] == row["prediction"]["tonic"] for row in group
            ) / len(group),
        }
    return result


def benchmark(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, sample in enumerate(manifest["samples"], 1):
        path = manifest_path.parent / sample["audio"]
        print(f"analyze {index}/{len(manifest['samples'])}: {sample['sound_id']}", flush=True)
        try:
            audio = decode_audio(path)
            predictions = [detect_window(audio, float(sample["bpm"]), bars) for bars in (0.5, 1.0, 2.0)]
        except Exception as exc:
            failures.append({"error": f"{type(exc).__name__}: {exc}", "sound_id": str(sample["sound_id"])})
            continue
        truth = (sample["ground_truth"]["tonic"], sample["ground_truth"]["mode"])
        for prediction in predictions:
            predicted = (prediction["prediction"]["tonic"], prediction["prediction"]["mode"])
            rows.append(
                {
                    **prediction,
                    "error": classify_error(truth, predicted),
                    "explicit_trap": sample["explicit_trap"],
                    "instrumentation": sample["instrumentation"],
                    "name": sample["name"],
                    "sound_id": sample["sound_id"],
                    "split": sample["split"],
                    "truth": sample["ground_truth"],
                }
            )

    gate = choose_threshold(rows, args.target_precision)
    threshold = gate["threshold"]
    evaluation_two_bar = [
        row for row in rows if row["split"] == "evaluation" and row["bars"] == 2.0
    ]
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for row in evaluation_two_bar:
        true_label = f"{row['truth']['tonic']}:{row['truth']['mode']}"
        predicted_label = f"{row['prediction']['tonic']}:{row['prediction']['mode']}"
        confusion[true_label][predicted_label] += 1

    report = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": {
            "description": "4096-point STFT, median harmonic mask, pitch-class fold, fixed Krumhansl-Kessler profiles",
            "frequency_range_hz": [40.0, 5000.0],
            "hop": 512,
            "sample_rate": TARGET_SR,
            "window": 4096,
        },
        "calibrated_abstention": {
            **gate,
            "target_precision": args.target_precision,
            "selection_rule": "maximum calibration coverage meeting target precision with at least five accepted examples",
        },
        "confusion_matrix_evaluation_2_bar": {
            truth: dict(sorted(predictions.items())) for truth, predictions in sorted(confusion.items())
        },
        "failures": failures,
        "groups_evaluation_2_bar_no_abstention": group_summary(rows, "evaluation", 2.0),
        "manifest": str(manifest_path),
        "results": rows,
        "summary": summarize(rows, threshold),
    }
    write_json(args.output.resolve(), report)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(f"wrote {args.output.resolve()}")
    return 0 if rows else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare-fsld", help="build and download an expert-labeled FSLD subset")
    prepare.add_argument("--annotations", required=True, type=Path)
    prepare.add_argument("--metadata", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--annotations-zip", type=Path)
    prepare.add_argument("--genre", default="hip hop")
    prepare.add_argument("--limit", type=int, default=0)
    prepare.add_argument("--trap-only", action="store_true")
    prepare.set_defaults(func=prepare_fsld)

    run = commands.add_parser("run", help="evaluate half-, one-, and two-bar key decisions")
    run.add_argument("manifest", type=Path)
    run.add_argument("output", type=Path)
    run.add_argument("--target-precision", type=float, default=0.80)
    run.set_defaults(func=benchmark)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "target_precision", 0.8) <= 0.0 or getattr(args, "target_precision", 0.8) > 1.0:
        raise SystemExit("--target-precision must be in (0, 1]")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
