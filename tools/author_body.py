#!/usr/bin/env python3
"""Compile and render a direct 240-byte df2 body.

This is the direct-authoring path. A body is not authored as named stages,
actors, or slots. A body is four complete corners, each stored as 6 x 5 packed
u16 coefficient words:

    4 corners x 6 rows x 5 words x 2 bytes = 240 bytes

Input can be either:

    1. a raw 240-byte little-endian block, in corner order:
       M0_Q0, M100_Q0, M0_Q100, M100_Q100

    2. a TOML/JSON packed-body-v1 document:

       format = "packed-body-v1"
       name = "My Body"
       boost = 1.0

       [corner.M0_Q0]
       words = [
         [0xDFFF, 0x0000, 0x0000, 0x0000, 0x0000],
         ...
       ]

The output is a compiled-v1 cartridge. The optional PNG render is a diagnostic
of the whole response and packed morph; rows/stages are readback coordinates
only, not the authoring language.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tomli

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402
from pyruntime.packed_interp import packed_bilinear, words_to_coeffs  # noqa: E402

CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
AUTHORING_SR = 39062.5
PACKED_KEYS = {
    "M0_Q0": "A",
    "M100_Q0": "B",
    "M0_Q100": "C",
    "M100_Q100": "D",
}
STAGES = 6
WORDS_PER_STAGE = 5
RAW_BYTES = len(CORNER_ORDER) * STAGES * WORDS_PER_STAGE * 2
FREQS = freq_points()


class BodyError(Exception):
    pass


def _load_doc(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    with path.open("rb") as f:
        return tomli.load(f)


def _parse_word(value: Any, where: str) -> int:
    if isinstance(value, str):
        value = int(value, 0)
    if not isinstance(value, int):
        raise BodyError(f"{where}: expected u16 word, got {value!r}")
    if value < 0 or value > 0xFFFF:
        raise BodyError(f"{where}: u16 word out of range: {value!r}")
    return value


def _validate_words(rows: Any, corner: str) -> list[tuple[int, ...]]:
    if not isinstance(rows, list) or len(rows) != STAGES:
        raise BodyError(f"{corner}: expected exactly {STAGES} rows")
    out: list[tuple[int, ...]] = []
    for row_i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != WORDS_PER_STAGE:
            raise BodyError(f"{corner}[{row_i}]: expected {WORDS_PER_STAGE} words")
        out.append(tuple(_parse_word(v, f"{corner}[{row_i}][{wi}]")
                         for wi, v in enumerate(row)))
    return out


def _parse_hex_bytes(hex_text: str) -> bytes:
    clean = "".join(ch for ch in hex_text if ch not in " \t\r\n,_")
    if len(clean) != RAW_BYTES * 2:
        raise BodyError(f"bytes_hex must contain {RAW_BYTES} bytes ({RAW_BYTES * 2} hex chars)")
    try:
        return bytes.fromhex(clean)
    except ValueError as exc:
        raise BodyError("bytes_hex contains non-hex characters") from exc


def words_from_raw(raw: bytes) -> dict[str, list[tuple[int, ...]]]:
    if len(raw) != RAW_BYTES:
        raise BodyError(f"raw body is {len(raw)} bytes; expected {RAW_BYTES}")
    u16 = np.frombuffer(raw, dtype="<u2").reshape(len(CORNER_ORDER), STAGES, WORDS_PER_STAGE)
    return {
        label: [tuple(int(v) for v in row) for row in u16[ci]]
        for ci, label in enumerate(CORNER_ORDER)
    }


def raw_from_words(words: dict[str, list[tuple[int, ...]]]) -> bytes:
    """Serialize the 4-corner word bank to the canonical 240-byte body.

    Corner-major (CORNER_ORDER), stage-major within a corner, 30 u16
    little-endian per corner. Exact inverse of `words_from_raw`; this is the
    layout `PackedCorners::from_rom_bytes` consumes on the Rust side.
    """
    flat = [
        word
        for label in CORNER_ORDER
        for row in words[label]
        for word in row
    ]
    arr = np.array(flat, dtype="<u2")
    expected = len(CORNER_ORDER) * STAGES * WORDS_PER_STAGE
    if arr.size != expected:
        raise BodyError(f"word bank has {arr.size} words; expected {expected}")
    return arr.tobytes()


def load_packed_words(path: Path) -> tuple[str, float, dict[str, list[tuple[int, ...]]]]:
    if path.suffix.lower() in (".bin", ".bytes", ".raw"):
        return path.stem, 1.0, words_from_raw(path.read_bytes())

    doc = _load_doc(path)
    if doc.get("format") != "packed-body-v1":
        raise BodyError(
            f"{path}: unsupported format {doc.get('format')!r}; expected packed-body-v1. "
            "Stage/slot authoring documents are intentionally rejected here."
        )
    name = str(doc.get("name") or path.stem)
    boost = float(doc.get("boost", 1.0))

    for field in ("authoring_sample_rate_hz", "sampleRate"):
        if field in doc and abs(float(doc[field]) - AUTHORING_SR) > 1e-9:
            raise BodyError(
                f"{field} must be {AUTHORING_SR}; df2 bodies are always authored at 39 kHz"
            )

    if "bytes_hex" in doc:
        return name, boost, words_from_raw(_parse_hex_bytes(str(doc["bytes_hex"])))

    corner_block = doc.get("corner")
    if not isinstance(corner_block, dict):
        raise BodyError("packed-body-v1 requires either bytes_hex or [corner.<name>].words")

    missing = [label for label in CORNER_ORDER if label not in corner_block]
    if missing:
        raise BodyError(f"missing corner(s): {', '.join(missing)}")

    words = {}
    for label in CORNER_ORDER:
        entry = corner_block[label]
        if not isinstance(entry, dict) or "words" not in entry:
            raise BodyError(f"corner.{label} requires words = [[...], ...]")
        words[label] = _validate_words(entry["words"], label)
    return name, boost, words


def _stage_dict_from_words(words: tuple[int, ...]) -> dict[str, float]:
    """Runtime fallback row from packed words.

    `packedWords` are the authority. The `stages` block is kept as a compiled-v1
    fallback for older/runtime code and therefore uses the direct DF2T biquad
    row expected by trench-core::Cascade: [b0, b1, b2, a1, a2].
    """
    c0, c1, c2, c3, c4 = words_to_coeffs(words)
    return {
        "c0": c4,
        "c1": (c0 - 2.0) * c4,
        "c2": (1.0 - c1) * c4,
        "c3": c2 - 2.0,
        "c4": 1.0 - c3,
    }


def compiled_payload(name: str, boost: float, words: dict[str, list[tuple[int, ...]]]) -> dict[str, Any]:
    keyframes = []
    for label in CORNER_ORDER:
        morph = 1.0 if "M100" in label else 0.0
        q = 1.0 if "Q100" in label else 0.0
        keyframes.append({
            "label": label,
            "morph": morph,
            "q": q,
            "boost": boost,
            "stages": [_stage_dict_from_words(row) for row in words[label]],
            "packedWords": [[int(v) for v in row] for row in words[label]],
        })
    return {
        "format": "compiled-v1",
        "name": name,
        "provenance": "direct-packed-240",
        "sampleRate": AUTHORING_SR,
        "authoring_sample_rate_hz": AUTHORING_SR,
        "stages": STAGES,
        "cornerOrder": list(CORNER_ORDER),
        "keyframes": keyframes,
    }


def _encoded_from_rows(rows: list[tuple[float, ...]]) -> list[EncodedCoeffs]:
    return [EncodedCoeffs(*row) for row in rows]


def _packed_keyed(words: dict[str, list[tuple[int, ...]]]) -> dict[str, list[tuple[int, ...]]]:
    return {PACKED_KEYS[label]: words[label] for label in CORNER_ORDER}


def _response_at(words: dict[str, list[tuple[int, ...]]], morph: float, q: float) -> np.ndarray:
    rows = packed_bilinear(_packed_keyed(words), morph, q)
    return cascade_response_db(_encoded_from_rows(rows), FREQS)


def _sweep(words: dict[str, list[tuple[int, ...]]], q: float, n: int = 220) -> np.ndarray:
    arr = np.array([_response_at(words, m, q) for m in np.linspace(0.0, 1.0, n)]).T
    lo = np.nanpercentile(arr, 5)
    hi = np.nanpercentile(arr, 99.5)
    if hi <= lo:
        hi = lo + 1.0
    return np.clip(arr, lo, hi), float(lo), float(hi)


def audit_motion(words: dict[str, list[tuple[int, ...]]]) -> list[str]:
    notes: list[str] = []
    band = (FREQS >= 250.0) & (FREQS <= 6000.0)
    band_idx = np.where(band)[0]
    for q in (0.0, 1.0):
        peaks = []
        levels = []
        for morph in np.linspace(0.0, 1.0, 9):
            y = _response_at(words, float(morph), q)
            local_i = int(np.argmax(y[band]))
            idx = int(band_idx[local_i])
            peaks.append(float(FREQS[idx]))
            levels.append(float(y[idx]))
        travel_oct = np.log2(max(peaks) / max(min(peaks), 1.0))
        level_span = max(levels) - min(levels)
        q_label = "Q0" if q == 0.0 else "Q100"
        notes.append(
            f"{q_label}: band peak {peaks[0]:.0f}->{peaks[-1]:.0f} Hz, "
            f"range {min(peaks):.0f}-{max(peaks):.0f} Hz, travel {travel_oct:.2f} oct, "
            f"level span {level_span:.1f} dB"
        )
        if travel_oct < 0.75:
            notes.append(f"WARNING {q_label}: weak motion through 250 Hz-6 kHz")
    return notes


def render_png(name: str, words: dict[str, list[tuple[int, ...]]], out: Path) -> None:
    plt.rcParams["figure.facecolor"] = "#070a09"
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.2))
    ymarks = [60, 150, 400, 1000, 2500, 6000]
    yidx = [int(np.argmin(np.abs(FREQS - f))) for f in ymarks]

    for a, q, title in ((ax[0], 0.0, "Q0"), (ax[1], 1.0, "Q100")):
        img, lo, hi = _sweep(words, q)
        a.imshow(img, aspect="auto", origin="lower", cmap="magma",
                 extent=[0, 1, 0, len(FREQS)], vmin=lo, vmax=hi)
        a.set_yticks(yidx)
        a.set_yticklabels([str(f) for f in ymarks], fontsize=7)
        a.set_title(f"{name} -- packed morph sweep ({title})", color="#eaeaea", fontsize=10)
        a.set_xlabel("morph", color="#aaa", fontsize=8)
        a.tick_params(colors="#888")

    colors = {
        "M0_Q0": "#2ec4ff",
        "M100_Q0": "#ffd23e",
        "M0_Q100": "#ff6b6b",
        "M100_Q100": "#9b8cff",
    }
    for label in CORNER_ORDER:
        enc = [EncodedCoeffs(*words_to_coeffs(row)) for row in words[label]]
        y = cascade_response_db(enc, FREQS)
        y = y - float(np.max(y))
        ax[2].semilogx(FREQS, np.clip(y, -60, 6), color=colors[label], lw=1.7, label=label)
    ax[2].set_xlim(20, 20000)
    ax[2].set_ylim(-60, 6)
    ax[2].grid(True, which="both", alpha=0.15)
    ax[2].set_facecolor("#0b0f0e")
    ax[2].set_title("four complete corners", color="#eaeaea", fontsize=10)
    ax[2].tick_params(colors="#888", labelsize=7)
    ax[2].legend(labelcolor="#ccc", fontsize=8, facecolor="#0b0f0e", edgecolor="#333")

    fig.suptitle(f"{name} -- direct 240-byte body", color="#eaeaea", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=115)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("body", type=Path, help="packed-body-v1 TOML/JSON or raw 240-byte body")
    ap.add_argument("-o", "--out", type=Path, default=None, help="output compiled-v1 JSON")
    ap.add_argument("--raw-out", type=Path, default=None,
                    help="also emit the raw 240-byte body (coefficient truth)")
    ap.add_argument("--png", type=Path, default=None, help="render morph sweep PNG")
    ap.add_argument("--name", default=None, help="override body name")
    args = ap.parse_args(argv)

    try:
        name, boost, words = load_packed_words(args.body)
        if args.name:
            name = args.name
        payload = compiled_payload(name, boost, words)
    except (BodyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"author_body error: {exc}", file=sys.stderr)
        return 1

    out = args.out or args.body.with_suffix(".cart.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"compiled -> {out}")
    print(f"body     -> {name}")
    print(f"source   -> direct 240-byte packed words")

    if args.raw_out:
        try:
            raw = raw_from_words(words)
        except BodyError as exc:
            print(f"author_body error: {exc}", file=sys.stderr)
            return 1
        assert len(raw) == RAW_BYTES, f"raw body must be {RAW_BYTES} bytes, got {len(raw)}"
        args.raw_out.parent.mkdir(parents=True, exist_ok=True)
        args.raw_out.write_bytes(raw)
        print(f"raw      -> {args.raw_out} ({len(raw)} bytes)")

    for line in audit_motion(words):
        print(line)

    if args.png:
        render_png(name, words, args.png)
        print(f"rendered -> {args.png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
