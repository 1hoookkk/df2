#!/usr/bin/env python3
"""Build the Forge's audited, provenance-labelled global corner index.

The picker consumes only the generated manifest. Every promoted corner is:
  * reduced to one six-stage packed-authoritative posture,
  * probed through trench-core's exact packed owner,
  * rendered through the shipped FilterEngine,
  * positioned on the low-high x open-closed perceptual field,
  * deduplicated by packed words.

The generated output is disposable tooling data under dev/tmp. It is not a
publication step: study-only ROM and heritage inputs stay visibly labelled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402
from pyruntime import trench_ffi  # noqa: E402


SOURCE_ROOT = ROOT / "dev" / "tmp" / "arma_source_pack" / "corners_audio_only"
LOOSE_ROOT = ROOT / "dev" / "tmp"
DEFAULT_OUT = ROOT / "dev" / "tmp" / "corner_library"
CORNER_LABELS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
IDENTITY_WORDS = tuple(trench_ffi.encode(value) for value in (2.0, 1.0, 2.0, 1.0, 1.0))

CATEGORY_RULES = {
    "_authored": ("authored", "candidate-original", 0),
    "_design": ("design", "candidate-original", 1),
    "_physics": ("physics", "candidate-original", 2),
    "_voice": ("voice", "candidate-original", 3),
    "_heritage": ("heritage-study", "study-only", 5),
    "_rom": ("rom-study", "study-only", 6),
}
@dataclass(frozen=True)
class Candidate:
    source_path: Path
    source_keyframe: str
    name: str
    category: str
    provenance: str
    priority: int
    rows: tuple[tuple[int, ...], ...]


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "corner"


def rows_from_words(words: Iterable[int]) -> tuple[tuple[int, ...], ...]:
    flat = tuple(int(word) & 0xFFFF for word in words)
    if len(flat) != trench_ffi.NUM_STAGES * trench_ffi.NUM_COEFFS:
        raise ValueError(f"expected 30 packed words, got {len(flat)}")
    return tuple(
        flat[i : i + trench_ffi.NUM_COEFFS]
        for i in range(0, len(flat), trench_ffi.NUM_COEFFS)
    )


def words_from_keyframe(keyframe: dict[str, Any]) -> tuple[tuple[int, ...], ...]:
    # Gather every stage row first (heritage templates carry 12 = up to 6 active +
    # spare/off slots), THEN drop the "section off" marker. The E-mu off stage
    # decodes to (2,1,2,1,1); encoded literally it becomes an unstable garbage
    # biquad (pole radius 2.0) that sinks the whole corner. The real filter lives
    # in the non-pad stages — keep those, bypass the rest.
    packed = keyframe.get("packedWords") or []
    if packed:
        if len(packed) < trench_ffi.NUM_STAGES:
            raise ValueError(f"packedWords has {len(packed)} rows")
        rows = [tuple(int(word) & 0xFFFF for word in row) for row in packed]
    else:
        stages = keyframe.get("stages") or []
        if len(stages) < trench_ffi.NUM_STAGES:
            raise ValueError(f"stages has {len(stages)} rows")
        rows = []
        for stage in stages:
            try:
                rows.append(
                    tuple(
                        trench_ffi.encode(float(stage[key]))
                        for key in ("c0", "c1", "c2", "c3", "c4")
                    )
                )
            except KeyError as exc:
                raise ValueError(f"stage row missing {exc.args[0]}") from exc

    active = [row for row in rows if row != IDENTITY_WORDS]
    if not active:
        raise ValueError("all stages off (empty corner)")
    active = active[: trench_ffi.NUM_STAGES]
    # The body is a fixed 6-stage cascade: bypass any empty slots by repeating a
    # real stage (a known-stable section; a literal pass-through stage reads as a
    # marginal pole in the packed probe and would re-trip the gate).
    while len(active) < trench_ffi.NUM_STAGES:
        active.append(active[0])
    return tuple(active)


def classify(path: Path) -> tuple[str, str, int]:
    rel = path.relative_to(SOURCE_ROOT)
    return CATEGORY_RULES.get(rel.parts[0], ("other", "unclassified", 9))


def classify_loose(path: Path) -> tuple[str, str, int]:
    stem = path.stem.lower()
    if any(token in stem for token in ("vowel", "vox", "talking", "ah_ay_ee")):
        return "voice-local", "local-candidate", 4
    if any(token in stem for token in ("acid", "bass", "synth")):
        return "synth-local", "local-candidate", 4
    return "loose-local", "unclassified", 8


def json_candidates() -> tuple[list[Candidate], list[dict[str, Any]]]:
    out: list[Candidate] = []
    rejected: list[dict[str, Any]] = []
    for path in sorted(SOURCE_ROOT.rglob("*.corner.json")):
        category, provenance, priority = classify(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            frames = data.get("keyframes") or []
            if not frames:
                raise ValueError("no keyframes")
            per_file_seen: set[tuple[tuple[int, ...], ...]] = set()
            for index, frame in enumerate(frames):
                label = str(frame.get("label") or f"frame-{index + 1}")
                rows = words_from_keyframe(frame)
                if rows in per_file_seen:
                    continue
                per_file_seen.add(rows)
                out.append(
                    Candidate(
                        source_path=path,
                        source_keyframe=label,
                        name=f"{data.get('name') or path.stem} / {label}",
                        category=category,
                        provenance=provenance,
                        priority=priority,
                        rows=rows,
                    )
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            rejected.append(
                {
                    "sourcePath": relative(path),
                    "reason": "parse-error",
                    "detail": str(exc),
                }
            )
    return out, rejected


def loose_body_candidates() -> tuple[list[Candidate], list[dict[str, Any]]]:
    out: list[Candidate] = []
    rejected: list[dict[str, Any]] = []
    for path in sorted(LOOSE_ROOT.glob("*.body240")):
        category, provenance, priority = classify_loose(path)
        try:
            raw = path.read_bytes()
            if len(raw) != trench_ffi.BODY_BYTES:
                raise ValueError(f"expected 240 bytes, got {len(raw)}")
            words = struct.unpack("<120H", raw)
            seen: set[tuple[tuple[int, ...], ...]] = set()
            for index, label in enumerate(CORNER_LABELS):
                rows = rows_from_words(words[index * 30 : (index + 1) * 30])
                if rows in seen:
                    continue
                seen.add(rows)
                out.append(
                    Candidate(
                        source_path=path,
                        source_keyframe=label,
                        name=f"{path.stem} / {label}",
                        category=category,
                        provenance=provenance,
                        priority=priority,
                        rows=rows,
                    )
                )
        except (OSError, ValueError, struct.error) as exc:
            rejected.append(
                {
                    "sourcePath": relative(path),
                    "reason": "parse-error",
                    "detail": str(exc),
                }
            )
    return out, rejected


def body_from_rows(rows: tuple[tuple[int, ...], ...]) -> bytes:
    bank = {key: list(rows) for key in ("A", "B", "C", "D")}
    return trench_ffi.body_bytes_from_corner_words(bank)


def response_metrics(rows: list[tuple[float, ...]]) -> tuple[dict[str, Any], np.ndarray]:
    freqs = freq_points(512)
    db = cascade_response_db([EncodedCoeffs(*row) for row in rows], freqs)
    median = float(np.median(db))
    maximum = float(np.max(db))
    minimum = float(np.min(db))
    above = db[1:-1] >= median + 1.5
    peaks = np.flatnonzero(above & (db[1:-1] > db[:-2]) & (db[1:-1] >= db[2:])) + 1

    power = np.power(10.0, db / 10.0)
    logs = np.log(np.maximum(freqs, 20.0))
    lo, hi = math.log(20.0), math.log(39062.5 * 0.5)
    brightness = float(np.clip((np.sum(power * logs) / np.sum(power) - lo) / (hi - lo), 0.0, 1.0))
    prominence = maximum - median
    return (
        {
            "responseMinDb": round(minimum, 4),
            "responseMaxDb": round(maximum, 4),
            "responseMedianDb": round(median, 4),
            "responseSpanDb": round(maximum - minimum, 4),
            "resonanceProminenceDb": round(prominence, 4),
            "peakCount": int(len(peaks)),
            "brightness": round(brightness, 6),
        },
        db,
    )


def audition_signal() -> bytes:
    rng = np.random.default_rng(0xDF2)
    n = int(round(39062.5 * 0.6))
    t = np.arange(n, dtype=np.float64) / 39062.5
    saw = 2.0 * ((t * 91.0) % 1.0) - 1.0
    noise = rng.standard_normal(n)
    signal = (0.045 * saw + 0.025 * noise).astype("<f4")
    return signal.tobytes()


AUDITION_SIGNAL = audition_signal()


def compact_trace(db: np.ndarray, points: int = 36) -> list[float]:
    indices = np.linspace(0, len(db) - 1, points).round().astype(int)
    return [round(float(db[index]), 4) for index in indices]


def audit(candidate: Candidate) -> tuple[bool, dict[str, Any], bytes, list[float]]:
    body = body_from_rows(candidate.rows)
    probe = trench_ffi.packed_probe(body, 0.0, 0.0)
    decoded_rows = trench_ffi.packed_interpolate(body, 0.0, 0.0)
    response, db = response_metrics(decoded_rows)
    rendered = np.frombuffer(
        trench_ffi.engine_render(body, 0.0, 0.0, AUDITION_SIGNAL),
        dtype="<f4",
    )
    render_finite = bool(np.isfinite(rendered).all())
    render_peak = float(np.max(np.abs(rendered))) if render_finite else float("inf")
    render_rms = float(np.sqrt(np.mean(np.square(rendered)))) if render_finite else float("inf")
    checks = {
        "finite": probe["nonfinite_mask"] == 0 and render_finite,
        "stable": probe["unstable_mask"] == 0 and probe["max_pole_radius"] < 1.0,
        "alive": render_rms >= 1.0e-5,
        "saneLevel": render_peak <= 8.0 and render_rms <= 2.0,
        "multiPeak": response["peakCount"] >= 2,
    }
    report = {
        **response,
        "maxPoleRadius": round(float(probe["max_pole_radius"]), 8),
        "unstableMask": int(probe["unstable_mask"]),
        "nonfiniteMask": int(probe["nonfinite_mask"]),
        "renderPeak": round(render_peak, 8),
        "renderRms": round(render_rms, 8),
        "checks": checks,
    }
    return all(checks.values()), report, body, compact_trace(db)


def cartridge(name: str, rows: tuple[tuple[int, ...], ...]) -> dict[str, Any]:
    decoded = [[trench_ffi.decode(word) for word in row] for row in rows]
    packed = [list(row) for row in rows]
    stages = [
        {f"c{index}": value for index, value in enumerate(row)}
        for row in decoded
    ]
    return {
        "format": "compiled-v1",
        "name": name,
        "sampleRate": 39062.5,
        "stages": 6,
        "keyframes": [
            {
                "label": label,
                "boost": 1.0,
                "stages": stages,
                "packedWords": packed,
            }
            for label in CORNER_LABELS
        ],
    }


def generate(out_dir: Path) -> dict[str, Any]:
    if not trench_ffi.available() or not trench_ffi.engine_available():
        raise RuntimeError("build trench-core first: cargo build --release -p trench-core")

    candidates, rejected = json_candidates()
    loose, loose_rejected = loose_body_candidates()
    candidates.extend(loose)
    rejected.extend(loose_rejected)
    candidates.sort(key=lambda item: (item.priority, relative(item.source_path), item.source_keyframe))

    corners_dir = out_dir / "corners"
    corners_dir.mkdir(parents=True, exist_ok=True)
    for stale in corners_dir.rglob("*.corner.json"):
        stale.unlink()

    entries = []
    accepted_hashes: dict[str, str] = {}
    for candidate in candidates:
        packed_hash = hashlib.sha1(
            b"".join(struct.pack("<H", word) for row in candidate.rows for word in row)
        ).hexdigest()[:12]
        if packed_hash in accepted_hashes:
            rejected.append(
                {
                    "sourcePath": relative(candidate.source_path),
                    "sourceKeyframe": candidate.source_keyframe,
                    "reason": "duplicate",
                    "duplicateOf": accepted_hashes[packed_hash],
                }
            )
            continue
        ok, report, _body, trace = audit(candidate)
        if not ok:
            rejected.append(
                {
                    "sourcePath": relative(candidate.source_path),
                    "sourceKeyframe": candidate.source_keyframe,
                    "reason": "audit-failed",
                    "audit": report,
                }
            )
            continue

        ident = f"{slug(candidate.category)}--{slug(candidate.name)}--{packed_hash}"
        category_dir = corners_dir / slug(candidate.category)
        category_dir.mkdir(parents=True, exist_ok=True)
        target = category_dir / f"{ident}.corner.json"
        target.write_text(json.dumps(cartridge(candidate.name, candidate.rows), indent=2) + "\n", encoding="utf-8")
        entry = {
            "id": ident,
            "name": candidate.name,
            "category": candidate.category,
            "provenance": candidate.provenance,
            "sourcePath": relative(candidate.source_path),
            "sourceKeyframe": candidate.source_keyframe,
            "path": target.relative_to(out_dir).as_posix(),
            "brightness": report["brightness"],
            "openness": 0.5,
            "responseTraceDb": trace,
            "audit": report,
        }
        entries.append(entry)
        accepted_hashes[packed_hash] = ident

    # Peak prominence is the useful broad-vs-pinched discriminator, but the
    # absolute range varies widely across viable corners. Scale it from the
    # audited corpus so the picker uses the whole open-closed axis without
    # allowing a few extreme resonances to flatten every other posture.
    if entries:
        prominences = np.asarray(
            [entry["audit"]["resonanceProminenceDb"] for entry in entries],
            dtype=np.float64,
        )
        lo, hi = np.quantile(prominences, [0.05, 0.95])
        span = max(float(hi - lo), 1.0e-9)
        for entry in entries:
            closed = float(np.clip((entry["audit"]["resonanceProminenceDb"] - lo) / span, 0.0, 1.0))
            entry["openness"] = round(0.04 + 0.92 * (1.0 - closed), 6)
            entry["audit"]["openness"] = entry["openness"]

    counts = Counter(entry["category"] for entry in entries)
    rejects = Counter(item["reason"] for item in rejected)
    manifest = {
        "format": "df2-corner-library-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceRoot": relative(SOURCE_ROOT),
        "entryCount": len(entries),
        "categoryCounts": dict(sorted(counts.items())),
        "rejectCounts": dict(sorted(rejects.items())),
        "entries": entries,
        "rejected": rejected,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    manifest = generate(args.out.resolve())
    print(f"indexed {manifest['entryCount']} audited corners -> {args.out / 'index.json'}")
    for category, count in manifest["categoryCounts"].items():
        print(f"  {category}: {count}")
    print("rejected:")
    for reason, count in manifest["rejectCounts"].items():
        print(f"  {reason}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
