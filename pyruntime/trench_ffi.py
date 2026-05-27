"""ctypes binding to the shipped trench-core packed math — the single owner.

Loads `trench_core.dll` / `.so` / `.dylib` and calls `trench_packed_decode` and
`trench_packed_interpolate` so Python tools judge the EXACT decode + morph-first
bilinear interpolation the plugin ships, instead of re-implementing it. This is
the un-haunting move: one module owns "what a body is and how it morphs," and
Python is glue that asks the Rust core "decode this, interpolate this."

Falls back gracefully: if the library isn't built, `available()` is False and
callers keep their pure-Python reference path.
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NUM_STAGES = 6
NUM_COEFFS = 5
BODY_BYTES = 4 * NUM_STAGES * NUM_COEFFS * 2  # 240
_OUT_LEN = NUM_STAGES * NUM_COEFFS            # 30

_lib = None
_lib_path: Path | None = None
_load_attempted = False


def _candidate_paths():
    if sys.platform == "win32":
        names = ["trench_core.dll"]
    elif sys.platform == "darwin":
        names = ["libtrench_core.dylib"]
    else:
        names = ["libtrench_core.so"]
    # Prefer release (what ships) over debug.
    for profile in ("release", "debug"):
        for name in names:
            yield ROOT / "target" / profile / name


def _load():
    global _lib, _lib_path, _load_attempted
    if _load_attempted:
        return _lib
    _load_attempted = True
    for path in _candidate_paths():
        if not path.exists():
            continue
        try:
            lib = ctypes.CDLL(str(path))
            # AttributeError here means a stale build missing these symbols —
            # skip it and try the next candidate rather than crashing.
            lib.trench_packed_decode.argtypes = [ctypes.c_uint16]
            lib.trench_packed_decode.restype = ctypes.c_double
            lib.trench_packed_interpolate.argtypes = [
                ctypes.c_char_p,                 # bytes (explicit len, NULs ok)
                ctypes.c_size_t,                 # len
                ctypes.c_double,                 # morph
                ctypes.c_double,                 # q
                ctypes.POINTER(ctypes.c_double), # out[30]
            ]
            lib.trench_packed_interpolate.restype = ctypes.c_int
            lib.trench_packed_probe.argtypes = [
                ctypes.c_char_p,                   # bytes
                ctypes.c_size_t,                   # len
                ctypes.c_double,                   # morph
                ctypes.c_double,                   # q
                ctypes.POINTER(ctypes.c_double),   # out_biquad[30]
                ctypes.POINTER(ctypes.c_double),   # out_max_pole_radius
                ctypes.POINTER(ctypes.c_uint32),   # out_unstable_mask
                ctypes.POINTER(ctypes.c_uint32),   # out_nonfinite_mask
            ]
            lib.trench_packed_probe.restype = ctypes.c_int
            _lib = lib
            _lib_path = path
            return _lib
        except (OSError, AttributeError):
            continue
    return None


def available() -> bool:
    return _load() is not None


def lib_path() -> Path | None:
    _load()
    return _lib_path


def decode(word: int) -> float:
    """Decode one packed u16 minifloat word via the shipped core."""
    lib = _load()
    if lib is None:
        raise RuntimeError("trench_core library not available")
    return float(lib.trench_packed_decode(ctypes.c_uint16(int(word) & 0xFFFF)))


def packed_interpolate(body_bytes: bytes, morph: float, q: float) -> list[tuple[float, ...]]:
    """Interpolate a 240-byte body at (morph, q); returns 6 kernel-form rows.

    Identical to the runtime `PackedCorners::interpolate` (morph-first lerp,
    then minifloat decode). Each row is (c0, c1, c2, c3, c4).
    """
    lib = _load()
    if lib is None:
        raise RuntimeError("trench_core library not available")
    if len(body_bytes) != BODY_BYTES:
        raise ValueError(f"body must be {BODY_BYTES} bytes, got {len(body_bytes)}")
    out = (ctypes.c_double * _OUT_LEN)()
    rc = lib.trench_packed_interpolate(
        bytes(body_bytes), len(body_bytes), float(morph), float(q), out
    )
    if rc != 0:
        raise RuntimeError(f"trench_packed_interpolate failed (rc={rc})")
    flat = list(out)
    return [
        tuple(flat[si * NUM_COEFFS:(si + 1) * NUM_COEFFS])
        for si in range(NUM_STAGES)
    ]


# Corner key order matches PackedCorners::from_rom_bytes (M0_Q0, M100_Q0, M0_Q100, M100_Q100).
_ABCD = ("A", "B", "C", "D")


def body_bytes_from_corner_words(corner_words: dict[str, list[tuple[int, ...]]]) -> bytes:
    """Serialize an A/B/C/D word bank to the canonical 240-byte body layout."""
    flat = bytearray()
    for key in _ABCD:
        rows = corner_words[key]
        for row in rows:
            for w in row:
                flat += (int(w) & 0xFFFF).to_bytes(2, "little")
    if len(flat) != BODY_BYTES:
        raise ValueError(f"word bank serialized to {len(flat)} bytes; expected {BODY_BYTES}")
    return bytes(flat)


def packed_bilinear(corner_words: dict[str, list[tuple[int, ...]]],
                    morph: float, q: float) -> list[tuple[float, ...]]:
    """A/B/C/D word bank → kernel rows, via the shipped core (drop-in)."""
    return packed_interpolate(body_bytes_from_corner_words(corner_words), morph, q)


def packed_probe(body_bytes: bytes, morph: float, q: float) -> dict:
    """Interpolate body at (morph, q), convert to biquad, return stability diagnostics.

    Single FFI call — no parallel Python kernel_to_biquad or pole_radius needed.

    Returns dict:
      biquad: list of 6 (b0,b1,b2,a1,a2) tuples, stage-major
      max_pole_radius: float
      unstable_mask: int  — bit i set if stage i has pole radius ≥ 1.0
      nonfinite_mask: int — bit i set if any coeff of stage i is nonfinite
    """
    lib = _load()
    if lib is None:
        raise RuntimeError("trench_core library not available")
    if len(body_bytes) != BODY_BYTES:
        raise ValueError(f"body must be {BODY_BYTES} bytes, got {len(body_bytes)}")
    out_bq = (ctypes.c_double * _OUT_LEN)()
    out_r = ctypes.c_double()
    out_unstable = ctypes.c_uint32()
    out_nonfinite = ctypes.c_uint32()
    rc = lib.trench_packed_probe(
        bytes(body_bytes), len(body_bytes), float(morph), float(q),
        out_bq,
        ctypes.byref(out_r),
        ctypes.byref(out_unstable),
        ctypes.byref(out_nonfinite),
    )
    if rc != 0:
        raise RuntimeError(f"trench_packed_probe failed (rc={rc})")
    flat = list(out_bq)
    return {
        "biquad": [
            tuple(flat[si * NUM_COEFFS:(si + 1) * NUM_COEFFS])
            for si in range(NUM_STAGES)
        ],
        "max_pole_radius": float(out_r.value),
        "unstable_mask": int(out_unstable.value),
        "nonfinite_mask": int(out_nonfinite.value),
    }
