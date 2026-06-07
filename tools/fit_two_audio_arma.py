#!/usr/bin/env python3
"""Fit two standalone recordings into one six-lane pole-zero Morph body.

Each recording is conditioned to a steady analysis slice, reduced to a
low-quefrency spectral envelope, then fitted inside the cartridge's native
packable coefficient box. Unlike LPC, the fitted model contains both
denominator poles and numerator zeros. The endpoint fits become M0 and M100;
Secondary is deliberately neutral because two recordings do not measure a
second performance axis.

Standalone audio does not identify a unique physical source filter or prove
lane continuity between recordings. By default this tool reports and applies a
minimum-cost endpoint lane mapping from fitted pole/zero geometry. Use
`--mapping` to override it after inspection or audition.

Example:
    python tools/fit_two_audio_arma.py --name "Aaa to Eee" \
        --m0 "dev/tmp/recordings/aaa - aa.wav" \
        --m100 "dev/tmp/voice/eee_isolated.wav"
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words, kernel_to_biquad  # noqa: E402
from pyruntime.quarry_fit import fit_envelope, smooth_audio_envelope  # noqa: E402
from tools.corner_words import build_toml_words  # noqa: E402

RUNTIME_SR = 39062.5
NUM_STAGES = 6
ANALYSIS_FFT = 4096


@dataclass(frozen=True)
class RootPair:
    freq_hz: float
    radius: float
    kind: str


@dataclass(frozen=True)
class LaneSummary:
    lane: int
    pole: RootPair
    zero: RootPair | None
    gain: float


def slugify(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower() or "untitled"


def load_mono(path: Path) -> tuple[float, np.ndarray]:
    sr, data = wavfile.read(str(path))
    arr = np.asarray(data)
    if arr.dtype.kind == "i":
        arr = arr.astype(np.float64) / max(float(np.iinfo(arr.dtype).max), 1.0)
    elif arr.dtype.kind == "u":
        info = np.iinfo(arr.dtype)
        midpoint = (float(info.max) + 1.0) * 0.5
        arr = (arr.astype(np.float64) - midpoint) / midpoint
    else:
        arr = arr.astype(np.float64)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    if arr.ndim != 1 or arr.size < 64:
        raise ValueError(f"{path}: expected at least 64 mono samples")
    return float(sr), arr


def steady_slice(samples: np.ndarray, sr: float) -> tuple[np.ndarray, dict]:
    """Select a loud steady region and window one ARMA FFT-length slice."""
    samples = np.asarray(samples, dtype=np.float64).flatten()
    frame = max(64, int(round(0.025 * sr)))
    hop = max(1, int(round(0.010 * sr)))
    starts = np.arange(0, max(1, len(samples) - frame + 1), hop, dtype=int)
    if starts.size == 0:
        starts = np.array([0], dtype=int)
    rms = np.array([
        float(np.sqrt(np.mean(samples[s:min(len(samples), s + frame)] ** 2) + 1e-30))
        for s in starts
    ])
    peak = max(float(np.max(rms)), 1e-30)
    keep = rms >= peak * (10.0 ** (-3.0 / 20.0))
    best_start = int(starts[int(np.argmax(rms))])
    best_end = min(len(samples), best_start + frame)
    run_start = None
    for index, active in enumerate(np.append(keep, False)):
        if active and run_start is None:
            run_start = index
        elif not active and run_start is not None:
            run_end = index - 1
            start = int(starts[run_start])
            end = min(len(samples), int(starts[run_end]) + frame)
            if end - start > best_end - best_start:
                best_start, best_end = start, end
            run_start = None

    target_len = max(64, int(math.ceil(ANALYSIS_FFT * sr / RUNTIME_SR)))
    region = samples[best_start:best_end]
    if region.size > target_len:
        offset = (region.size - target_len) // 2
        region = region[offset:offset + target_len]
        selected_start = best_start + offset
    else:
        selected_start = best_start
    region = region - float(np.mean(region))
    peak_abs = float(np.max(np.abs(region))) if region.size else 0.0
    if peak_abs <= 1e-12:
        raise ValueError("selected steady slice has no usable energy")
    region = (region / peak_abs) * np.hamming(region.size)
    return region.astype(np.float64), {
        "source_samples": int(len(samples)),
        "selected_start_sample": int(selected_start),
        "selected_samples": int(len(region)),
        "selected_start_ms": round(1000.0 * selected_start / sr, 3),
        "selected_duration_ms": round(1000.0 * len(region) / sr, 3),
    }


def _root_pair(b0: float, b1: float, b2: float, sr: float, numerator: bool) -> RootPair | None:
    if numerator and abs(b1) + abs(b2) < 1e-10:
        return None
    coeff = [b0, b1, b2] if numerator else [1.0, b1, b2]
    if abs(coeff[0]) < 1e-15:
        return None
    roots = np.roots(coeff)
    if roots.size == 0:
        return None
    root = max(roots, key=lambda value: (abs(float(np.imag(value))), abs(value)))
    angle = abs(float(np.angle(root)))
    return RootPair(
        freq_hz=angle * sr / (2.0 * math.pi),
        radius=float(abs(root)),
        kind="complex_pair" if abs(float(np.imag(root))) > 1e-7 else "real_pair",
    )


def summarize_rows(rows: list[tuple[float, ...]], sr: float = RUNTIME_SR) -> list[LaneSummary]:
    out = []
    for index, row in enumerate(rows):
        b0, b1, b2, a1, a2 = kernel_to_biquad(tuple(row))
        pole = _root_pair(1.0, a1, a2, sr, numerator=False)
        if pole is None:
            pole = RootPair(0.0, 0.0, "none")
        zero = _root_pair(b0, b1, b2, sr, numerator=True)
        out.append(LaneSummary(index + 1, pole, zero, float(b0)))
    return out


def _octave_distance(a: float, b: float) -> float:
    return abs(math.log2(max(a, 20.0) / max(b, 20.0)))


def lane_cost(a: LaneSummary, b: LaneSummary) -> float:
    cost = _octave_distance(a.pole.freq_hz, b.pole.freq_hz)
    cost += 0.25 * abs(a.pole.radius - b.pole.radius)
    if a.zero is not None and b.zero is not None:
        cost += 0.45 * _octave_distance(a.zero.freq_hz, b.zero.freq_hz)
        cost += 0.10 * abs(a.zero.radius - b.zero.radius)
    elif (a.zero is None) != (b.zero is None):
        cost += 0.75
    return cost


def infer_mapping(a: list[LaneSummary], b: list[LaneSummary]) -> tuple[list[int], float]:
    """Return zero-based B lane indices ordered by A lane, plus aggregate cost."""
    if len(a) != NUM_STAGES or len(b) != NUM_STAGES:
        raise ValueError(f"expected {NUM_STAGES} rows per endpoint")
    best_mapping = list(range(NUM_STAGES))
    best_cost = math.inf
    for mapping in itertools.permutations(range(NUM_STAGES)):
        cost = sum(lane_cost(a[index], b[mapping[index]]) for index in range(NUM_STAGES))
        if cost < best_cost:
            best_mapping = list(mapping)
            best_cost = cost
    return best_mapping, float(best_cost)


def parse_mapping(value: str | None, inferred: list[int]) -> tuple[list[int], str]:
    if value is None:
        return inferred, "inferred-minimum-cost"
    try:
        mapping = [int(item.strip()) - 1 for item in value.split(",")]
    except ValueError as exc:
        raise ValueError("--mapping must contain six comma-separated 1-based B lane numbers") from exc
    if sorted(mapping) != list(range(NUM_STAGES)):
        raise ValueError("--mapping must be a permutation of 1,2,3,4,5,6")
    return mapping, "explicit-user"


def fit_audio(path: Path) -> tuple[list[tuple[float, ...]], dict]:
    sr, samples = load_mono(path)
    conditioned, meta = steady_slice(samples, sr)
    freqs_hz, envelope_db = smooth_audio_envelope(conditioned, sr)
    fit = fit_envelope(
        freqs_hz,
        envelope_db,
        runtime_sr=RUNTIME_SR,
        seed=sum(str(path).encode("utf-8")),
    )
    return fit.packed_rows, {
        "path": str(path),
        "sample_rate_hz": sr,
        "fit_backend": "bounded-forge-native-d-space",
        "packed_max_pole_radius": fit.packed_max_pole_radius,
        "response_null_db": fit.response_null_db,
        "complex_pole_radius_band": list(fit.complex_pole_radius_band),
        "cranked_complex_rows": fit.cranked_complex_rows,
        **meta,
    }


def print_lanes(label: str, lanes: list[LaneSummary]) -> None:
    print(f"{label}:")
    for lane in lanes:
        zero = "none" if lane.zero is None else f"{lane.zero.freq_hz:7.0f}Hz r{lane.zero.radius:.4f}"
        print(
            f"  L{lane.lane}: pole {lane.pole.freq_hz:7.0f}Hz r{lane.pole.radius:.4f}  "
            f"zero {zero:>18}  gain {lane.gain:.5f}"
        )


def write_body(
    name: str,
    out_dir: Path,
    rows_a: list[tuple[float, ...]],
    rows_b: list[tuple[float, ...]],
    plan: dict,
) -> tuple[Path, Path, Path, Path]:
    words_a = [coeffs_to_words(*row) for row in rows_a]
    words_b = [coeffs_to_words(*row) for row in rows_b]
    bank = {"A": words_a, "B": words_b, "C": words_a, "D": words_b}
    body = trench_ffi.body_bytes_from_corner_words(bank)
    probes = [
        trench_ffi.packed_probe(body, morph / 16.0, secondary / 16.0)
        for secondary in range(17) for morph in range(17)
    ]
    plan["packed_probe"] = {
        "grid": "17x17",
        "points": len(probes),
        "max_pole_radius": max(float(probe["max_pole_radius"]) for probe in probes),
        "unstable_rows": sum(int(probe["unstable_mask"]).bit_count() for probe in probes),
        "nonfinite_rows": sum(int(probe["nonfinite_mask"]).bit_count() for probe in probes),
        "dll": str(trench_ffi.lib_path()),
    }
    if plan["packed_probe"]["unstable_rows"] or plan["packed_probe"]["nonfinite_rows"]:
        raise RuntimeError(f"packed-grid stability gate failed: {plan['packed_probe']}")

    slug = slugify(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    toml = out_dir / f"{slug}.packed.toml"
    plan_path = out_dir / f"{slug}.fit.json"
    raw = out_dir / f"{slug}.body240"
    cart = out_dir / f"{slug}.cart.json"
    png = out_dir / f"{slug}.png"
    corners = {
        "M0_Q0": words_a,
        "M100_Q0": words_b,
        "M0_Q100": words_a,
        "M100_Q100": words_b,
    }
    toml.write_text(build_toml_words(name, corners), encoding="utf-8")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    subprocess.run([
        sys.executable, str(ROOT / "tools" / "author_body.py"), str(toml),
        "--out", str(cart), "--raw-out", str(raw), "--png", str(png),
    ], check=True)
    return toml, plan_path, raw, cart


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--m0", type=Path, required=True, help="standalone WAV at Morph 0")
    ap.add_argument("--m100", type=Path, required=True, help="standalone WAV at Morph 100")
    ap.add_argument("--mapping", default=None,
                    help="optional six-number B-lane permutation for A lanes, e.g. 1,3,2,4,5,6")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "dev" / "tmp" / "two_audio_arma")
    args = ap.parse_args(argv)

    rows_a, source_a = fit_audio(args.m0)
    rows_b_raw, source_b = fit_audio(args.m100)
    lanes_a = summarize_rows(rows_a)
    lanes_b_raw = summarize_rows(rows_b_raw)
    inferred, inferred_cost = infer_mapping(lanes_a, lanes_b_raw)
    mapping, mapping_source = parse_mapping(args.mapping, inferred)
    rows_b = [rows_b_raw[index] for index in mapping]

    print_lanes("M0 fitted ARMA endpoint", lanes_a)
    print()
    print_lanes("M100 fitted ARMA endpoint before correspondence mapping", lanes_b_raw)
    print()
    print("B lane used for each A lane:", ", ".join(str(index + 1) for index in mapping))
    print(f"mapping source: {mapping_source}  inferred cost: {inferred_cost:.4f}")
    print("Secondary: neutral (C=A, D=B); two recordings do not measure a Secondary axis.")

    plan = {
        "format": "two-audio-arma-fit-v1",
        "name": args.name,
        "boundary": (
            "Each standalone WAV is reduced to a low-quefrency spectral envelope and "
            "fitted as a bounded six-lane minimum-phase ARMA posture in the cartridge's "
            "native packable coefficient box. Numerator zeros and denominator poles are "
            "model-derived from audio. They are not claimed as a uniquely observable "
            "physical source filter. Complex-pair pole radii are projected into the "
            "0.990..0.998 authoring band while real support rows are preserved. "
            "Endpoint lane correspondence is inferred unless "
            "--mapping is supplied. Secondary is neutral because it was not measured."
        ),
        "sources": {"m0": source_a, "m100": source_b},
        "mapping": {
            "source": mapping_source,
            "a_lane_to_b_lane_1_based": [index + 1 for index in mapping],
            "inferred_minimum_cost": inferred_cost,
        },
        "m0_lanes": [asdict(lane) for lane in lanes_a],
        "m100_lanes_before_mapping": [asdict(lane) for lane in lanes_b_raw],
        "secondary": "neutral-duplicated-endpoints",
    }
    toml, fit_json, raw, cart = write_body(args.name, args.out_dir, rows_a, rows_b, plan)
    print()
    print(f"wrote {toml}")
    print(f"wrote {fit_json}")
    print(f"wrote {raw} ({raw.stat().st_size} bytes)")
    print(f"wrote {cart}")
    probe = plan["packed_probe"]
    print(
        f"packed probe: {probe['grid']} maxR={probe['max_pole_radius']:.9f} "
        f"unstable={probe['unstable_rows']} nonfinite={probe['nonfinite_rows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
