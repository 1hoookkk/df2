"""Parity null: TRENCH DSP pipeline vs canonical references.

Walks reference/canonical_audio/MANIFEST.json. Each entry carries a per-skin source
path (relative to the Trench root) and a source_type:

  - raw_p2k_skin  : datasets/p2k_skins/*.json (33 numbered + 2 vocal)
                    stage form {a1, r, val1, val2, val3, flag}
  - calibration_re: reference/calibration/*.json (6 ft=33-55 extractions)
                    stage form {pole_freq_hz, radius, val1, val2, val3, ...}
                    a1 is reconstructed: a1 = -2r*cos(2pi*f/sample_rate_authored)

Pipeline:
    source stage -> (b0, b1, b2, a1, a2) -> scipy.signal.sosfilt
                 -> per-sample AGC (16-entry table from agc.rs)
                 -> * boost
                 -> best-fit gain null vs reference WAV (lag=0)

Hard fail at rel_null > FAIL_THRESHOLD_DB.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import sosfilt

def find_repo_root(start: Path) -> Path:
    path = start if start.is_dir() else start.parent
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


ROOT = find_repo_root(Path(__file__).resolve())
DRY = Path(r"C:/Users/hooki/trenchwork_clean/ref/bypassed-pinknoise.wav")
REF_DIR = ROOT / "reference" / "canonical_audio"

CORNERS = ("M0_Q0", "M0_Q100", "M100_Q0", "M100_Q100")
# Null worse than this triggers a failure exit code.
FAIL_THRESHOLD_DB = -140.0

# AGC_TABLE ported from trenchwork_clean/trench-core/src/agc.rs
AGC_TABLE = np.array(
    [1.0001, 1.0001, 0.996, 0.990, 0.920, 0.500, 0.200, 0.160,
     0.120, 0.120, 0.120, 0.120, 0.120, 0.120, 0.120, 0.120],
    dtype=np.float64,
)


def db(x: float) -> float:
    x = float(x)
    return -300.0 if x <= 0.0 else 20.0 * np.log10(x)


def mono(d: np.ndarray) -> np.ndarray:
    return d[:, 0] if d.ndim > 1 else d


def stage_coefficients_raw(stage: dict) -> tuple[float, float, float, float, float]:
    """Raw p2k_skin stage → (b0, b1, b2, a1, a2)."""
    a1 = float(stage["a1"])
    r = min(float(stage["r"]), 0.999999)
    a2 = r * r
    if float(stage.get("flag", 1.0)) < 0.5:
        b0, b1, b2 = 1.0, 0.0, 0.0
    else:
        b0 = 1.0 + float(stage["val1"])
        b1 = a1 + float(stage["val2"])
        b2 = a2 - float(stage["val3"])
    return b0, b1, b2, a1, a2


def stage_coefficients_calibration(
    stage: dict, sample_rate_authored: float
) -> tuple[float, float, float, float, float]:
    """Calibration stage → (b0, b1, b2, a1, a2). Reconstructs a1 from
    pole_freq_hz + radius at the calibration's authoring sample rate."""
    r = min(float(stage["radius"]), 0.999999)
    f = float(stage["pole_freq_hz"])
    a1 = -2.0 * r * math.cos(2.0 * math.pi * f / float(sample_rate_authored))
    a2 = r * r
    val1 = float(stage.get("val1", 0.0))
    val2 = float(stage.get("val2", 0.0))
    val3 = float(stage.get("val3", 0.0))
    if val1 == 0.0 and val2 == 0.0 and val3 == 0.0:
        b0, b1, b2 = 1.0, 0.0, 0.0
    else:
        b0 = 1.0 + val1
        b1 = a1 + val2
        b2 = a2 - val3
    return b0, b1, b2, a1, a2


def build_sos(stages: list[dict], source_type: str, sample_rate_authored: float) -> np.ndarray:
    rows = []
    for st in stages:
        if source_type == "calibration_re":
            b0, b1, b2, a1, a2 = stage_coefficients_calibration(st, sample_rate_authored)
        else:
            b0, b1, b2, a1, a2 = stage_coefficients_raw(st)
        rows.append([b0, b1, b2, 1.0, a1, a2])
    return np.asarray(rows, dtype=np.float64)


def apply_agc(samples: np.ndarray) -> np.ndarray:
    """Per-sample post-cascade soft limiter (EmulatorX.dll AGC)."""
    out = np.empty_like(samples)
    gain = 1.0
    for i, s in enumerate(samples):
        idx = int(gain * abs(s)) & 0xF
        new_gain = gain * AGC_TABLE[idx]
        gain = new_gain if new_gain < 1.0 else 1.0
        out[i] = s * gain
    return out


def apply_dc_block(samples: np.ndarray, sample_rate: float = 44100.0) -> np.ndarray:
    """One-pole DC blocker matching trench-core engine.rs DcBlocker."""
    r = 1.0 - (2.0 * np.pi * 20.0 / sample_rate)
    out = np.empty_like(samples)
    x_prev = 0.0
    y_prev = 0.0
    for i, x in enumerate(samples):
        y = x - x_prev + r * y_prev
        x_prev = x
        y_prev = y if np.isfinite(y) else 0.0
        out[i] = y_prev
    return out


def best_fit_null(pred: np.ndarray, ref: np.ndarray, lag_search: int = 0):
    """Lag-aligned best-fit-gain null. Canonical references are rendered
    through the exact same pipeline as `pred`, so lag=0 is correct and we
    skip the search by default."""
    n = min(len(pred), len(ref))
    p = pred[:n].astype(np.float64, copy=False)
    r = ref[:n].astype(np.float64, copy=False)
    den = float(np.dot(p, p))
    if den <= 0.0:
        return (0, 0.0, 0.0, 0.0, 0.0)
    gain = float(np.dot(p, r) / den)
    res = r - gain * p
    rms = float(np.sqrt(float(np.dot(res, res)) / n))
    peak = float(np.max(np.abs(res)))
    ref_rms = float(np.sqrt(float(np.dot(r, r)) / n))
    return (0, gain, rms, peak, ref_rms)


def load_source(entry: dict) -> tuple[dict, str, float]:
    """Resolve a manifest entry's source file. Returns (body, source_type,
    sample_rate_authored)."""
    src = resolve_repo_path(entry["source"])
    body = json.loads(src.read_text())
    src_type = entry.get("source_type", "raw_p2k_skin")
    sr_auth = float(entry.get("sample_rate_authored", 39062.5))
    return body, src_type, sr_auth


def resolve_repo_path(rel: str) -> Path:
    path = ROOT / rel
    if path.exists():
        return path

    normalized = rel.replace("\\", "/")
    moved_prefixes = (
        ("docs/calibration/", "reference/calibration/"),
        ("cartridges/engine/", "cartridges/factory/"),
        ("trench-core/", "runtime/trench-core/"),
    )
    for old, new in moved_prefixes:
        if normalized.startswith(old):
            candidate = ROOT / new / normalized[len(old) :]
            if candidate.exists():
                return candidate
    return path


def main() -> int:
    manifest_path = REF_DIR / "MANIFEST.json"
    missing = [
        str(path)
        for path in (REF_DIR, manifest_path, DRY)
        if not path.exists()
    ]
    if missing:
        print("FAIL: parity inputs missing:")
        for path in missing:
            print(f"  {path}")
        return 2

    manifest = json.loads(manifest_path.read_text())
    dry = mono(sf.read(str(DRY))[0])

    print(f"dry input:  {DRY.name}  {len(dry)} samples")
    print(f"refs:       {REF_DIR}  ({len(manifest)} entries)")
    print(f"pipeline:   source stage -> SOS cascade -> AGC -> *boost -> gain null")
    print(f"fail at:    rel_null > {FAIL_THRESHOLD_DB:.0f} dB")
    print()
    print(f"{'name':28} {'src':4} {'boost':>6} {'worst_corner':>12} {'gain':>8} {'rel_null':>11}")

    failures: list[tuple[str, str, float]] = []
    covered = 0
    import gc
    for name in sorted(manifest):
        entry = manifest[name]
        body, src_type, sr_auth = load_source(entry)
        worst = (None, 0.0, 1.0)  # corner, rel_db, gain
        for label in CORNERS:
            wav = REF_DIR / f"{name}_{label}.wav"
            if not wav.exists():
                continue
            ref = mono(sf.read(str(wav))[0])
            corner = body["corners"].get(label)
            if corner is None:
                continue
            sos = build_sos(corner["stages"], src_type, sr_auth)
            boost = float(entry.get("boost", body.get("boost", 1.0)))
            cascaded = sosfilt(sos, dry)
            pred = apply_agc(cascaded) * boost
            _lag, gain, rms, _peak, ref_rms = best_fit_null(pred, ref)
            rel = db(rms) - db(ref_rms)
            covered += 1
            if worst[0] is None or rel > worst[1]:
                worst = (label, rel, gain)
            del ref, sos, cascaded, pred
        gc.collect()
        if worst[0] is None:
            print(f"{name:28} no refs")
            continue
        boost = float(entry.get("boost", 1.0))
        marker = " " if worst[1] <= FAIL_THRESHOLD_DB else "!"
        tag = "raw" if src_type == "raw_p2k_skin" else "cal"
        print(
            f"{marker}{name:27} {tag:>4} {boost:6.2f} {worst[0]:>12} "
            f"{worst[2]:8.4f} {worst[1]:+8.1f} dB"
        )
        if worst[1] > FAIL_THRESHOLD_DB:
            failures.append((name, worst[0], worst[1]))

    print()
    if covered == 0:
        print("FAIL: canonical parity covered zero reference corners")
        return 1
    if failures:
        print(f"FAIL: {len(failures)}/{len(manifest)} entries exceeded {FAIL_THRESHOLD_DB:.0f} dB")
        for name, corner, rel in failures:
            print(f"  {name}  worst corner {corner}  rel_null={rel:+.1f}dB")
        return 1
    print(f"OK: {len(manifest)}/{len(manifest)} entries null at <= {FAIL_THRESHOLD_DB:.0f} dB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
