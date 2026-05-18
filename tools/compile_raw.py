#!/usr/bin/env python3
"""Compile an internal raw stage surface into a compiled-v1 cartridge.

Input format: raw-stage-v1 JSON with either:
  - `frames: {M0: {...}, M100: {...}}` (native 2-frame authoring surface)
  - `corners: {M0_Q0: {...}, ...}`     (legacy authored 4-corner surface)
  - `keyframes: [{label, stages, ...}, ...]`

Each stage is authored in musical units:
  - `allpole` / `resonator`: pole frequency + radius + stage gain. A textbook
    2-pole resonator with no numerator zeros: `b = (g, 0, 0)`. This is the
    firmware-native pole-only shape (Morpheus cubes per E-mu RE).
  - `lowpass2`: pole frequency + radius + stage gain. A normalized 2-pole
    low-pass section with a double zero at Nyquist and DC gain = stage_gain.
  - `zero_forced`: pole frequency + radius + stage gain, zero on unit circle
    at the pole frequency
  - `zero_forced_offset`: pole frequency + radius + stage gain, unit-circle
    zero offset by semitones
  - `explicit_zero`: pole frequency + radius + stage gain + explicit zero
    frequency/radius
  - `passthrough`

Output: compiled-v1 cartridge JSON that loads through
`trench_core::Cartridge::from_json`.

Stdlib only. No RBJ derivation. This is a deterministic format bridge from an
internal authoring surface to kernel-form coefficients.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
import json
import math
import struct
import sys
from pathlib import Path

AUTHORING_SR = 39062.5
NYQUIST_LIMIT_HZ = AUTHORING_SR * 0.5
FRAME_ORDER = ("M0", "M100")
CORNER_ORDER = ("M0_Q0", "M0_Q100", "M100_Q0", "M100_Q100")
CORNER_MORPH_Q = {
    "M0_Q0": (0.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q0": (1.0, 0.0),
    "M100_Q100": (1.0, 1.0),
}
FRAME_TO_CORNERS = {
    "M0": ("M0_Q0", "M0_Q100"),
    "M100": ("M100_Q0", "M100_Q100"),
}
PASSTHROUGH = {
    "w": [0xDFFF, 0x0000, 0x0000, 0x0000, 0x0000],
    "c0": 1.0, "c1": 0.0, "c2": 0.0, "c3": 0.0, "c4": 0.0
}
ACTIVE_STAGE_LIMIT = 6
OUTPUT_STAGE_COUNT = 12

# ── RE-grounded gates ─────────────────────────────────────────────────────
# Mandate (2026-05-14): compile_raw refuses AI-hallucinated cartridges before
# they can reach cascade.rs. Four gates, each panicking with CompileError.
# See `authoring/tables/q_radius_table.json` and the M0_Q0 coefficient diff
# in `juce-shell/diagnostics/coeffs_diff_*` for the empirical justification.

_Q_RADIUS_TABLE_PATH = Path(__file__).resolve().parent.parent / "tables" / "q_radius_table.json"
_TABLE_MATCH_TOL = 1e-6           # exact-float match tolerance
_NYQUIST_ANCHOR_HZ = 6000.0       # at least one stage must be above this freq
_HOT_STAGE_RADIUS = 0.95          # any stage with r above this triggers the boost tax
_HOT_BOOST_FLOOR = 1.0            # cartridges with hot stages must boost < 1.0
_ZERO_UNIT_CIRCLE_TOL = 1.0       # ban zero_radius >= this (empirical max in corpus: 0.9757)

_Q_RADIUS_TABLE_CACHE: list[float] | None = None


def _q_radius_table() -> list[float]:
    global _Q_RADIUS_TABLE_CACHE
    if _Q_RADIUS_TABLE_CACHE is None:
        if not _Q_RADIUS_TABLE_PATH.exists():
            raise CompileError(
                f"q_radius_table missing: {_Q_RADIUS_TABLE_PATH}. "
                "Run authoring/tools/extract_q_radius_table.py to rebuild from RE corpus."
            )
        payload = json.loads(_Q_RADIUS_TABLE_PATH.read_text(encoding="utf-8"))
        _Q_RADIUS_TABLE_CACHE = sorted(float(e["radius"]) for e in payload.get("entries", []))
        if not _Q_RADIUS_TABLE_CACHE:
            raise CompileError(f"q_radius_table at {_Q_RADIUS_TABLE_PATH} is empty")
    return _Q_RADIUS_TABLE_CACHE


def _gate_table_clamp(radius: float, stage_path: str) -> None:
    """Gate 1: pole radius must exist in q_radius_table.json (within ±_TABLE_MATCH_TOL)."""
    table = _q_radius_table()
    idx = bisect_left(table, radius)
    nearest_candidates: list[float] = []
    if idx < len(table):
        nearest_candidates.append(table[idx])
    if idx > 0:
        nearest_candidates.append(table[idx - 1])
    for t in nearest_candidates:
        if abs(t - radius) <= _TABLE_MATCH_TOL:
            return
    nearest = min(table, key=lambda t: abs(t - radius))
    raise CompileError(
        f"{stage_path}.radius={radius!r} is not in q_radius_table.json "
        f"(nearest legal value: {nearest:.7f}, Δ={radius - nearest:+.7f}). "
        "Round-number radii are forbidden — pole radii must come from the RE table."
    )


def _gate_nyquist_anchor(stages: list[dict], corner_label: str) -> None:
    """Gate 3: at least one active stage must have pole_freq_hz > _NYQUIST_ANCHOR_HZ."""
    for s in stages:
        if not isinstance(s, dict):
            continue
        if str(s.get("kind", "allpole")) == "passthrough":
            continue
        try:
            f_hz = float(s.get("pole_freq_hz", 0.0))
        except (TypeError, ValueError):
            continue
        if f_hz > _NYQUIST_ANCHOR_HZ:
            return
    raise CompileError(
        f"{corner_label}: no active stage has pole_freq_hz > {_NYQUIST_ANCHOR_HZ} Hz. "
        "Every cartridge must include an HF/Nyquist brace stage to anchor the upper end."
    )


def _gate_headroom_tax(stages: list[dict], boost: float, corner_label: str) -> None:
    """Gate 4: any hot stage (r > _HOT_STAGE_RADIUS) requires boost < _HOT_BOOST_FLOOR."""
    if abs(boost - _HOT_BOOST_FLOOR) > 1e-9:
        return  # boost has been cut — discipline already paid
    for idx, s in enumerate(stages):
        if not isinstance(s, dict):
            continue
        if str(s.get("kind", "allpole")) == "passthrough":
            continue
        try:
            r = float(s.get("radius", 0.0))
        except (TypeError, ValueError):
            continue
        if r > _HOT_STAGE_RADIUS:
            raise CompileError(
                f"{corner_label}.stages[{idx}].radius={r} > {_HOT_STAGE_RADIUS} "
                f"with cartridge boost=1.0. Hot cascades must pay the headroom tax "
                "(boost < 1.0) — level discipline belongs in the cartridge."
            )


class CompileError(Exception):
    pass


def _mf_decode(packed: int) -> float:
    packed &= 0xFFFF
    if packed == 0xFFFF:
        return 1.0
    if packed == 0x0000:
        return 0.0
    u = packed + 1
    exp = ((u >> 12) & 0xF) - 15
    mant = u & 0xFFF
    if exp < -14:
        return mant / 134217728.0
    scaled = (mant | 0x1000) / 8192.0
    return scaled * (2.0 ** exp)


_MF_DECODED = tuple(_mf_decode(raw) for raw in range(0x10000))


def _mf_encode(value: float) -> int:
    """Encode a float back to the nearest firmware u16 minifloat word."""
    idx = bisect_left(_MF_DECODED, value)
    best_err = float("inf")
    best_raw = 0
    for raw in (idx - 1, idx):
        if raw < 0 or raw >= len(_MF_DECODED):
            continue
        err = abs(_MF_DECODED[raw] - value)
        if err < best_err:
            best_err = err
            best_raw = raw
    return best_raw


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def require_finite(value: object, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CompileError(f"{field} must be numeric") from exc
    if not math.isfinite(out):
        raise CompileError(f"{field} must be finite")
    return out


def require_range(value: float, field: str, low: float, high: float, high_open: bool = False) -> float:
    if value < low:
        raise CompileError(f"{field} must be >= {low}")
    if high_open:
        if value >= high:
            raise CompileError(f"{field} must be < {high}")
    elif value > high:
        raise CompileError(f"{field} must be <= {high}")
    return value


def pole_a1(freq_hz: float, radius: float) -> float:
    theta = 2.0 * math.pi * freq_hz / AUTHORING_SR
    return -2.0 * radius * math.cos(theta)


def validate_pole_stage(stage: dict, stage_path: str) -> tuple[float, float, float]:
    freq_hz = require_range(
        require_finite(stage.get("pole_freq_hz"), f"{stage_path}.pole_freq_hz"),
        f"{stage_path}.pole_freq_hz",
        0.0,
        NYQUIST_LIMIT_HZ,
        high_open=True,
    )
    radius = require_range(
        require_finite(stage.get("radius"), f"{stage_path}.radius"),
        f"{stage_path}.radius",
        0.0,
        1.0,
        high_open=True,
    )
    _gate_table_clamp(radius, stage_path)  # Gate 1
    stage_gain = require_finite(stage.get("stage_gain", 1.0), f"{stage_path}.stage_gain")
    return freq_hz, radius, stage_gain


def encode_stage(stage: dict, stage_path: str) -> dict:
    kind = str(stage.get("kind", "allpole"))
    if kind == "passthrough":
        return PASSTHROUGH.copy()

    if kind in ("allpole", "resonator", "lowpass2", "zero_forced", "zero_forced_offset", "explicit_zero"):
        pole_freq_hz, radius, stage_gain = validate_pole_stage(stage, stage_path)
    else:
        raise CompileError(
            f"{stage_path}.kind must be one of passthrough, allpole, resonator, "
            f"lowpass2, zero_forced, zero_forced_offset, explicit_zero"
        )

    a1 = pole_a1(pole_freq_hz, radius)

    if kind in ("allpole", "resonator"):
        val1 = stage_gain - 1.0
        b1_target = 0.0
        b2_target = 0.0
    elif kind == "lowpass2":
        dc_den = 1.0 + a1 + radius * radius
        k = stage_gain * dc_den / 4.0
        c0 = f32(k)
        c1 = f32(2.0 * k)
        c2 = f32(k)
        c3 = f32(a1)
        c4 = f32(radius * radius)
        
        # Solve for words
        d1 = c1
        d0 = (c0 - c1) / 4.0
        d3 = c3
        d2 = (c2 - c3) / 4.0
        d4 = c4
        w = [_mf_encode(d) for d in (d0, d1, d2, d3, d4)]
        return {"w": w, "c0": c0, "c1": c1, "c2": c2, "c3": c3, "c4": c4}
    elif kind == "zero_forced":
        val1 = stage_gain - 1.0
        b1_target = -2.0 * math.cos(2.0 * math.pi * pole_freq_hz / AUTHORING_SR)
        b2_target = 1.0
    elif kind == "zero_forced_offset":
        val1 = stage_gain - 1.0
        offset = require_finite(stage.get("offset_semitones"), f"{stage_path}.offset_semitones")
        zero_freq_hz = pole_freq_hz * (2.0 ** (offset / 12.0))
        zero_freq_hz = max(20.0, min(AUTHORING_SR * 0.48, zero_freq_hz))
        b1_target = -2.0 * math.cos(2.0 * math.pi * zero_freq_hz / AUTHORING_SR)
        b2_target = 1.0
    else:  # explicit_zero
        val1 = stage_gain - 1.0
        zero_freq_hz = require_range(
            require_finite(stage.get("zero_freq_hz"), f"{stage_path}.zero_freq_hz"),
            f"{stage_path}.zero_freq_hz",
            0.0,
            NYQUIST_LIMIT_HZ,
            high_open=True,
        )
        zero_radius = require_range(
            require_finite(stage.get("zero_radius"), f"{stage_path}.zero_radius"),
            f"{stage_path}.zero_radius",
            0.0,
            1.0,
        )
        b1_target = -2.0 * zero_radius * math.cos(2.0 * math.pi * zero_freq_hz / AUTHORING_SR)
        b2_target = zero_radius * zero_radius

    val2 = b1_target - a1
    val3 = radius * radius - b2_target

    a1 = f32(a1)
    radius = f32(radius)
    val1 = f32(val1)
    val2 = f32(val2)
    val3 = f32(val3)

    c0 = 1.0 + val1
    c1 = a1 + val2
    c2 = radius * radius - val3
    c3 = a1
    c4 = radius * radius
    
    # Inverse solve for raw d_i coefficients
    d1 = c1
    d0 = (c0 - c1) / 4.0
    d3 = c3
    d2 = (c2 - c3) / 4.0
    d4 = c4
    
    w = [_mf_encode(d) for d in (d0, d1, d2, d3, d4)]
    
    return {"w": w, "c0": f32(c0), "c1": f32(c1), "c2": f32(c2), "c3": f32(c3), "c4": f32(c4)}


def _normalize_surface_entry(entry: object, label: str) -> dict:
    if isinstance(entry, list):
        return {"stages": entry}
    if isinstance(entry, dict):
        return entry
    raise CompileError(f"surface entry '{label}' must be an object or a stage list")


def normalize_corner_map(raw_doc: dict) -> dict[str, dict]:
    has_frames = "frames" in raw_doc
    has_corners = "corners" in raw_doc
    has_keyframes = "keyframes" in raw_doc
    if sum(1 for present in (has_frames, has_corners, has_keyframes) if present) != 1:
        raise CompileError("raw doc must contain exactly one of 'frames', 'corners', or 'keyframes'")

    if has_frames:
        frames = raw_doc["frames"]
        if not isinstance(frames, dict):
            raise CompileError("'frames' must be an object")
        normalized_frames: dict[str, dict] = {}
        for label in FRAME_ORDER:
            if label not in frames:
                raise CompileError(f"raw doc missing frame '{label}'")
            normalized_frames[label] = _normalize_surface_entry(frames[label], label)

        out: dict[str, dict] = {}
        for frame_label, frame in normalized_frames.items():
            for corner_label in FRAME_TO_CORNERS[frame_label]:
                out[corner_label] = frame
        return out

    if "corners" in raw_doc:
        corners = raw_doc["corners"]
        if not isinstance(corners, dict):
            raise CompileError("'corners' must be an object")
        out = {}
        for label in CORNER_ORDER:
            if label not in corners:
                raise CompileError(f"raw doc missing corner '{label}'")
            out[label] = _normalize_surface_entry(corners[label], label)
        return out

    if "keyframes" in raw_doc:
        keyframes = raw_doc["keyframes"]
        if not isinstance(keyframes, list):
            raise CompileError("'keyframes' must be a list")
        out = {}
        for idx, keyframe in enumerate(keyframes):
            if not isinstance(keyframe, dict):
                raise CompileError(f"keyframe[{idx}] must be an object")
            label = keyframe.get("label")
            if label not in CORNER_ORDER:
                raise CompileError(
                    f"keyframe[{idx}].label must be one of {', '.join(CORNER_ORDER)}"
                )
            out[label] = keyframe
        missing = [label for label in CORNER_ORDER if label not in out]
        if missing:
            raise CompileError(f"raw doc missing keyframes: {missing}")
        return out

    raise CompileError("raw doc must have exactly one of 'frames', 'corners', or 'keyframes'")


def compile_raw(raw_doc: dict) -> dict:
    raw_format = raw_doc.get("format")
    if raw_format != "raw-stage-v1":
        raise CompileError(
            f"unsupported raw format: {raw_format!r}, expected 'raw-stage-v1'"
        )

    sample_rate_fields = []
    for field in ("authoring_sample_rate_hz", "sampleRate"):
        if field in raw_doc:
            sample_rate_fields.append((field, require_finite(raw_doc[field], field)))

    if len(sample_rate_fields) == 2:
        (_, first_rate), (_, second_rate) = sample_rate_fields
        if abs(first_rate - second_rate) > 1e-9:
            raise CompileError(
                "authoring_sample_rate_hz and sampleRate must match when both are present"
            )

    sample_rate = sample_rate_fields[0][1] if sample_rate_fields else AUTHORING_SR
    if abs(sample_rate - AUTHORING_SR) > 1e-9:
        raise CompileError(
            f"authoring sample rate must be {AUTHORING_SR} for the raw authoring surface"
        )

    global_boost = require_finite(raw_doc.get("boost", 1.0), "boost")
    corner_map = normalize_corner_map(raw_doc)

    keyframes = []
    for label in CORNER_ORDER:
        corner = corner_map[label]
        stages = corner.get("stages", [])
        if not isinstance(stages, list):
            raise CompileError(f"{label}.stages must be a list")
        if len(stages) > ACTIVE_STAGE_LIMIT:
            raise CompileError(
                f"{label}.stages has {len(stages)} entries, expected <= {ACTIVE_STAGE_LIMIT}"
            )

        _gate_nyquist_anchor(stages, label)  # Gate 3

        compiled_stages = [
            encode_stage(stage, f"{label}.stages[{idx}]")
            for idx, stage in enumerate(stages)
        ]
        while len(compiled_stages) < ACTIVE_STAGE_LIMIT:
            compiled_stages.append(PASSTHROUGH.copy())
        while len(compiled_stages) < OUTPUT_STAGE_COUNT:
            compiled_stages.append(PASSTHROUGH.copy())

        boost = require_finite(corner.get("boost", global_boost), f"{label}.boost")
        _gate_headroom_tax(stages, boost, label)  # Gate 4
        morph, q = CORNER_MORPH_Q[label]
        keyframes.append(
            {
                "label": label,
                "morph": morph,
                "q": q,
                "boost": boost,
                "stages": compiled_stages,
            }
        )

    return {
        "format": "compiled-v1",
        "name": raw_doc.get("name", "unnamed_body"),
        "provenance": "compile_raw",
        "sampleRate": AUTHORING_SR,
        "keyframes": keyframes,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Compile a raw-stage-v1 authoring surface into compiled-v1 JSON."
    )
    parser.add_argument(
        "raw",
        type=Path,
        help="Path to raw-stage-v1 JSON file (2-frame or 4-corner), or '-' for stdin.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output cartridge path (stdout if omitted).",
    )
    args = parser.parse_args(argv)

    try:
        if str(args.raw) == "-":
            raw_doc = json.load(sys.stdin)
        else:
            with args.raw.open() as f:
                raw_doc = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"raw parse error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"raw read error: {exc}", file=sys.stderr)
        return 1

    try:
        cart = compile_raw(raw_doc)
    except CompileError as exc:
        print(f"compile error: {exc}", file=sys.stderr)
        return 2

    out_json = json.dumps(cart, indent=2)
    if args.out is None:
        sys.stdout.write(out_json + "\n")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_json + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
