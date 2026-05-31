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
MUSICAL_AGC_DRIVE = 4.0

_lib = None
_lib_path: Path | None = None
_load_attempted = False
_engine_ok = False  # the stateful FilterEngine symbols (audition) bound OK
_agc_ok = False     # the read-only trench_agc_table symbol bound OK
_fit_ok = False     # the trench_fit_corner_from_magnitude symbol bound OK


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
            lib.trench_packed_encode.argtypes = [ctypes.c_double]
            lib.trench_packed_encode.restype = ctypes.c_uint16
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
            _bind_engine(lib)  # optional: stateful audition path (separate, non-fatal)
            _bind_agc(lib)     # optional: read-only AGC curve accessor (non-fatal)
            _bind_fit(lib)     # optional: response-curve factorizer (non-fatal)
            return _lib
        except (OSError, AttributeError):
            continue
    return None


def _bind_engine(lib) -> None:
    """Bind the stateful FilterEngine symbols used for audition (process_block).

    Kept separate from the packed-math bindings so that a DLL missing these
    (older build) still delegates the codec/interp/probe math — audition just
    becomes unavailable instead of dropping the whole library."""
    global _engine_ok
    try:
        lib.trench_engine_create.restype = ctypes.c_void_p
        lib.trench_engine_destroy.argtypes = [ctypes.c_void_p]
        lib.trench_engine_prepare.argtypes = [ctypes.c_void_p, ctypes.c_double]
        lib.trench_engine_load_body_bytes.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.trench_engine_load_body_bytes.restype = ctypes.c_int
        lib.trench_engine_load_cartridge.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.trench_engine_load_cartridge.restype = ctypes.c_int
        lib.trench_engine_set_input_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_spatial_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_agc_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.trench_engine_set_agc_drive.argtypes = [ctypes.c_void_p, ctypes.c_float]
        try:
            lib.trench_engine_set_parameters.argtypes = [
                ctypes.c_void_p, ctypes.c_float, ctypes.c_float,
                ctypes.c_float, ctypes.c_float,  # slam_drive (0..1), five_d
            ]
            _set_params_ok = True
        except AttributeError:
            _set_params_ok = False
        lib.trench_engine_process_block.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),  # left  (in place)
            ctypes.POINTER(ctypes.c_float),  # right (in place)
            ctypes.c_int,                    # num samples
            ctypes.c_double,                 # morph
            ctypes.c_double,                 # q
        ]
        _engine_ok = True
    except AttributeError:
        _engine_ok = False


def _bind_agc(lib) -> None:
    """Bind the read-only AGC-table accessor. Kept separate (non-fatal) so a DLL
    missing it (older build) still delegates the packed math; `agc_table()` then
    falls back to its in-module mirror."""
    global _agc_ok
    try:
        lib.trench_agc_table.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
        lib.trench_agc_table.restype = ctypes.c_int
        _agc_ok = True
    except AttributeError:
        _agc_ok = False


def _bind_fit(lib) -> None:
    """Bind the response-curve factorizer. Non-fatal: a DLL missing it (older
    build) still delegates the packed math; `fit_corner_from_magnitude()` raises."""
    global _fit_ok
    try:
        lib.trench_fit_corner_from_magnitude.argtypes = [
            ctypes.POINTER(ctypes.c_double),  # freqs[n]
            ctypes.POINTER(ctypes.c_double),  # dbs[n]
            ctypes.c_size_t,                  # n
            ctypes.c_double,                  # runtime_sr
            ctypes.POINTER(ctypes.c_double),  # out[30] kernel coeffs
        ]
        lib.trench_fit_corner_from_magnitude.restype = ctypes.c_int
        _fit_ok = True
    except AttributeError:
        _fit_ok = False


# The canonical AGC / global-compression curve lives in exactly ONE place:
# `trench-core/src/dsp/mod.rs::BASE_AGC_TABLE`. `agc_table()` reads it via FFI and
# RAISES if the core isn't built — there is deliberately NO in-Python mirror, so
# a stale copy can never silently stand in for the engine's real curve.
_AGC_TABLE_LEN = 16  # trench-core BASE_AGC_TABLE is [f32; 16] — a length, not the data


def agc_table() -> tuple[float, ...]:
    """The canonical 16-entry AGC / global-compression curve, read from the
    shipped trench-core (single source of truth = `BASE_AGC_TABLE` in
    `trench-core/src/dsp/mod.rs`).

    Raises RuntimeError if the library isn't built/loadable or is a stale build
    missing `trench_agc_table`. No fallback by design — build it with
    `cargo build --release -p trench-core`.
    """
    lib = _load()
    if lib is None:
        raise RuntimeError(
            "trench_core library not available; cannot read the canonical AGC table. "
            "Build it: cargo build --release -p trench-core"
        )
    if not _agc_ok:
        raise RuntimeError(
            "trench_core is loaded but missing trench_agc_table (stale build); "
            "rebuild: cargo build --release -p trench-core"
        )
    buf = (ctypes.c_float * _AGC_TABLE_LEN)()
    wrote = lib.trench_agc_table(buf, ctypes.c_size_t(_AGC_TABLE_LEN))
    if wrote <= 0:
        raise RuntimeError(f"trench_agc_table failed (rc={wrote})")
    return tuple(float(buf[i]) for i in range(int(wrote)))


def fit_corner_from_magnitude(curve, runtime_sr: float = 39062.5) -> list[tuple[float, ...]]:
    """Factorize a target magnitude curve into one fitted corner via the shipped
    Rust factorizer (`arma::fit_corner_from_magnitude`).

    `curve` is a sorted iterable of (freq_hz, db) points. Returns 6 kernel-form
    rows (c0..c4). Raises RuntimeError if the core isn't built/loadable or the
    fitter returns None (degenerate target). The fit is dumb on purpose — the
    taste lives in the curve, not here.
    """
    lib = _load()
    if lib is None or not _fit_ok:
        raise RuntimeError(
            "trench_core factorizer unavailable; build: cargo build --release -p trench-core"
        )
    pts = [(float(f), float(d)) for f, d in curve]
    n = len(pts)
    if n < 2:
        raise ValueError("curve needs at least 2 points")
    fs = (ctypes.c_double * n)(*[f for f, _ in pts])
    ds = (ctypes.c_double * n)(*[d for _, d in pts])
    out = (ctypes.c_double * (NUM_STAGES * NUM_COEFFS))()
    rc = lib.trench_fit_corner_from_magnitude(
        fs, ds, ctypes.c_size_t(n), ctypes.c_double(float(runtime_sr)), out
    )
    if rc != 0:
        raise RuntimeError(f"trench_fit_corner_from_magnitude failed (rc={rc})")
    flat = list(out)
    return [tuple(flat[si * NUM_COEFFS:(si + 1) * NUM_COEFFS]) for si in range(NUM_STAGES)]


def available() -> bool:
    return _load() is not None


def engine_available() -> bool:
    """True when the stateful FilterEngine (audition / process_block) is bound."""
    _load()
    return _engine_ok


def engine_render(body_bytes: bytes, morph: float, q: float, in_f32_bytes: bytes,
                  sr: float = 39062.5, input_mode: int = 0, spatial_mode: int = 2,
                  agc_enabled: bool = True, agc_drive: float = MUSICAL_AGC_DRIVE) -> bytes:
    """Render mono input through the SHIPPED FilterEngine at a held (morph, q).

    `in_f32_bytes` is little-endian float32 mono PCM; returns the processed
    left channel as little-endian float32 bytes. This is the player's exact
    DSP — load a 240-byte body, prepare at `sr`, process_block — so the desk
    auditions what the instrument plays, not a Python approximation.

    Defaults: input_mode 0 (None — no input drive) and spatial_mode 2 (Off),
    so you hear the body itself, transparent-player style.
    """
    lib = _load()
    if lib is None or not _engine_ok:
        raise RuntimeError("trench_core engine FFI not available")
    if len(body_bytes) != BODY_BYTES:
        raise ValueError(f"body must be {BODY_BYTES} bytes, got {len(body_bytes)}")
    n = len(in_f32_bytes) // 4
    eng = lib.trench_engine_create()
    if not eng:
        raise RuntimeError("trench_engine_create returned null")
    try:
        lib.trench_engine_prepare(eng, ctypes.c_double(float(sr)))
        rc = lib.trench_engine_load_body_bytes(eng, bytes(body_bytes), len(body_bytes))
        if rc != 0:
            raise RuntimeError(f"load_body_bytes failed (rc={rc})")
        lib.trench_engine_set_input_mode(eng, ctypes.c_int(int(input_mode)))
        lib.trench_engine_set_spatial_mode(eng, ctypes.c_int(int(spatial_mode)))
        lib.trench_engine_set_agc_enabled(eng, ctypes.c_int(1 if agc_enabled else 0))
        lib.trench_engine_set_agc_drive(eng, ctypes.c_float(max(1.0, float(agc_drive))))
        left = (ctypes.c_float * n).from_buffer_copy(in_f32_bytes)
        right = (ctypes.c_float * n).from_buffer_copy(in_f32_bytes)
        lib.trench_engine_process_block(eng, left, right, ctypes.c_int(n),
                                        ctypes.c_double(float(morph)), ctypes.c_double(float(q)))
        return bytes(left)
    finally:
        lib.trench_engine_destroy(eng)


def engine_render_automated(body_bytes: bytes, morph_per_block, q_per_block,
                            in_f32_bytes: bytes, sr: float = 39062.5,
                            input_mode: int = 0, spatial_mode: int = 2,
                            block: int = 512, agc_enabled: bool = True,
                            agc_drive: float = MUSICAL_AGC_DRIVE) -> bytes:
    """Render mono input through the shipped engine while AUTOMATING (morph, q).

    Holds ONE engine instance and steps `(morph, q)` per `block` samples via
    repeated `process_block`, so filter state is continuous (no clicks/resets) —
    the genuine shipped path for slow Morph/Q/diagonal sweeps. `morph_per_block`
    and `q_per_block` are sequences (one value per block; last value is held if
    short). Returns processed left channel as little-endian float32 bytes.
    """
    lib = _load()
    if lib is None or not _engine_ok:
        raise RuntimeError("trench_core engine FFI not available")
    if len(body_bytes) != BODY_BYTES:
        raise ValueError(f"body must be {BODY_BYTES} bytes, got {len(body_bytes)}")
    total = len(in_f32_bytes) // 4
    nb = max(1, (total + block - 1) // block)
    mlen, qlen = len(morph_per_block), len(q_per_block)
    eng = lib.trench_engine_create()
    if not eng:
        raise RuntimeError("trench_engine_create returned null")
    try:
        lib.trench_engine_prepare(eng, ctypes.c_double(float(sr)))
        rc = lib.trench_engine_load_body_bytes(eng, bytes(body_bytes), len(body_bytes))
        if rc != 0:
            raise RuntimeError(f"load_body_bytes failed (rc={rc})")
        lib.trench_engine_set_input_mode(eng, ctypes.c_int(int(input_mode)))
        lib.trench_engine_set_spatial_mode(eng, ctypes.c_int(int(spatial_mode)))
        lib.trench_engine_set_agc_enabled(eng, ctypes.c_int(1 if agc_enabled else 0))
        lib.trench_engine_set_agc_drive(eng, ctypes.c_float(max(1.0, float(agc_drive))))
        out = bytearray()
        for bi in range(nb):
            s = bi * block * 4
            chunk = in_f32_bytes[s:s + block * 4]
            cn = len(chunk) // 4
            if cn == 0:
                break
            m = float(morph_per_block[min(bi, mlen - 1)])
            q = float(q_per_block[min(bi, qlen - 1)])
            left = (ctypes.c_float * cn).from_buffer_copy(chunk)
            right = (ctypes.c_float * cn).from_buffer_copy(chunk)
            lib.trench_engine_process_block(eng, left, right, ctypes.c_int(cn),
                                            ctypes.c_double(m), ctypes.c_double(q))
            out += bytes(left)
        return bytes(out)
    finally:
        lib.trench_engine_destroy(eng)


def engine_render_slam(body_bytes: bytes, morph_per_block, q_per_block,
                       in_f32_bytes: bytes, slam_drive: float = 0.5,
                       five_d: float = 0.0, sr: float = 39062.5,
                       block: int = 512, agc_enabled: bool = True,
                       agc_drive: float = MUSICAL_AGC_DRIVE) -> bytes:
    """Render through the shipped engine with the MACKIE DESK SLAM input stage
    engaged (input_mode=1): a PRE-cascade saturator (0..1 -> up to 36 dB desk
    drive) feeding the filter, then the AGC post-cascade. This is the full driven
    path E-mu-style (drive INTO the filter), not just AGC-on-output. `slam_drive`
    in [0,1]. Filter state is continuous across blocks (no clicks)."""
    lib = _load()
    if lib is None or not _engine_ok:
        raise RuntimeError("trench_core engine FFI not available")
    if not getattr(lib.trench_engine_set_parameters, "argtypes", None):
        raise RuntimeError("trench_engine_set_parameters not bound (rebuild trench-core FFI)")
    if len(body_bytes) != BODY_BYTES:
        raise ValueError(f"body must be {BODY_BYTES} bytes, got {len(body_bytes)}")
    total = len(in_f32_bytes) // 4
    nb = max(1, (total + block - 1) // block)
    mlen, qlen = len(morph_per_block), len(q_per_block)
    sd = max(0.0, min(1.0, float(slam_drive)))
    eng = lib.trench_engine_create()
    if not eng:
        raise RuntimeError("trench_engine_create returned null")
    try:
        lib.trench_engine_prepare(eng, ctypes.c_double(float(sr)))
        rc = lib.trench_engine_load_body_bytes(eng, bytes(body_bytes), len(body_bytes))
        if rc != 0:
            raise RuntimeError(f"load_body_bytes failed (rc={rc})")
        lib.trench_engine_set_input_mode(eng, ctypes.c_int(1))  # MackieDeskSlam
        lib.trench_engine_set_agc_enabled(eng, ctypes.c_int(1 if agc_enabled else 0))
        lib.trench_engine_set_agc_drive(eng, ctypes.c_float(max(1.0, float(agc_drive))))
        out = bytearray()
        for bi in range(nb):
            s = bi * block * 4
            chunk = in_f32_bytes[s:s + block * 4]
            cn = len(chunk) // 4
            if cn == 0:
                break
            m = float(morph_per_block[min(bi, mlen - 1)])
            q = float(q_per_block[min(bi, qlen - 1)])
            # set_slam_drive (+ five_d); morph/q still applied per-block below
            lib.trench_engine_set_parameters(eng, ctypes.c_float(m), ctypes.c_float(q),
                                             ctypes.c_float(sd), ctypes.c_float(float(five_d)))
            left = (ctypes.c_float * cn).from_buffer_copy(chunk)
            right = (ctypes.c_float * cn).from_buffer_copy(chunk)
            lib.trench_engine_process_block(eng, left, right, ctypes.c_int(cn),
                                            ctypes.c_double(m), ctypes.c_double(q))
            out += bytes(left)
        return bytes(out)
    finally:
        lib.trench_engine_destroy(eng)


def engine_render_controls_stereo(cartridge_json: str, morph: float, q: float,
                                  in_f32_bytes: bytes, slam_drive: float = 0.0,
                                  qsound_enabled: bool = False, space: float = 0.75,
                                  agc_enabled: bool = True,
                                  agc_drive: float = MUSICAL_AGC_DRIVE,
                                  sr: float = 39062.5, block: int = 512) -> tuple[bytes, bytes]:
    """Render a held Talking-Hedz-style control state through the shipped engine.

    This narrow helper exists for audible calibration: it loads the full JSON
    cartridge, preserves stereo output for QSound, and exposes the real engine's
    Mackie input slam, QSound, and AGC switches without recreating DSP in Python.
    """
    lib = _load()
    if lib is None or not _engine_ok:
        raise RuntimeError("trench_core engine FFI not available")
    payload = cartridge_json.encode("utf-8")
    total = len(in_f32_bytes) // 4
    eng = lib.trench_engine_create()
    if not eng:
        raise RuntimeError("trench_engine_create returned null")
    try:
        lib.trench_engine_prepare(eng, ctypes.c_double(float(sr)))
        rc = lib.trench_engine_load_cartridge(eng, ctypes.c_char_p(payload))
        if rc != 0:
            raise RuntimeError(f"load_cartridge failed (rc={rc})")
        sd = max(0.0, min(1.0, float(slam_drive)))
        sp = max(0.0, min(1.0, float(space)))
        lib.trench_engine_set_input_mode(eng, ctypes.c_int(1 if sd > 0.0 else 0))
        lib.trench_engine_set_spatial_mode(eng, ctypes.c_int(0 if qsound_enabled else 2))
        lib.trench_engine_set_agc_enabled(eng, ctypes.c_int(1 if agc_enabled else 0))
        lib.trench_engine_set_agc_drive(eng, ctypes.c_float(max(1.0, float(agc_drive))))
        out_l = bytearray()
        out_r = bytearray()
        for start in range(0, total, block):
            chunk = in_f32_bytes[start * 4:(start + block) * 4]
            n = len(chunk) // 4
            if n == 0:
                break
            lib.trench_engine_set_parameters(
                eng, ctypes.c_float(float(morph)), ctypes.c_float(float(q)),
                ctypes.c_float(sd), ctypes.c_float(sp),
            )
            left = (ctypes.c_float * n).from_buffer_copy(chunk)
            right = (ctypes.c_float * n).from_buffer_copy(chunk)
            lib.trench_engine_process_block(
                eng, left, right, ctypes.c_int(n),
                ctypes.c_double(float(morph)), ctypes.c_double(float(q)),
            )
            out_l += bytes(left)
            out_r += bytes(right)
        return bytes(out_l), bytes(out_r)
    finally:
        lib.trench_engine_destroy(eng)


def lib_path() -> Path | None:
    _load()
    return _lib_path


def decode(word: int) -> float:
    """Decode one packed u16 minifloat word via the shipped core."""
    lib = _load()
    if lib is None:
        raise RuntimeError("trench_core library not available")
    return float(lib.trench_packed_decode(ctypes.c_uint16(int(word) & 0xFFFF)))


def encode(value: float) -> int:
    """Encode one f64 to the nearest packed u16 word via the shipped core.

    The inverse of `decode`. Owning this in Rust is what lets a Python-authored
    body (coeffs -> words) pack to the exact words the plugin would.
    """
    lib = _load()
    if lib is None:
        raise RuntimeError("trench_core library not available")
    return int(lib.trench_packed_encode(ctypes.c_double(float(value)))) & 0xFFFF


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
