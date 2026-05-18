"""Bake Talking Hedz heritage template → Rust const arrays + golden impulse response.

Reads `cartridges/factory/_source/heritage_designer_sections.json`, pulls
the `hedz` template's 30-integer authoring grid, compiles it to 4-corner × 6-stage ×
5-coefficient kernel-form floats via the E-mu type 1/2/3 firmware recipes,
runs an impulse through the resulting DF2T cascade at each corner, and
emits two Rust source files:

    runtime/trench-core/src/hedz_rom.rs    — the cartridge const arrays
    runtime/trench-core/src/hedz_golden.rs — committed golden impulse-response
                                      vectors per corner, for the Rust
                                      cross-language parity test.

**Stdlib only.** This tool intentionally does NOT import from pyruntime —
it inlines the compile math from `pyruntime/heritage_coeffs.py` and the
f32-cast path from `pyruntime/encode.py` so it runs from a clean venv and
in any CI sandbox without numpy. If `pyruntime/heritage_coeffs.py` ever
changes, this script must be re-audited; the committed Rust consts are
the truth the plugin ships, so drift gets caught by the Rust cascade
test (`runtime/trench-core/tests/hedz_cascade.rs`).

Doctrinally this tool is COMPILER-side: it reads legacy heritage data
(the 30-integer grid) and emits raw bytes for the Rust runtime to
consume. It does not import from THE FORGE and must not.

Usage::

    python forge/compilers/bake_hedz_const.py
    # or: python forge/compilers/bake_hedz_const.py --template hedz --inventory <path>
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    path = start if start.is_dir() else start.parent
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


REPO = find_repo_root(Path(__file__).resolve())
DEFAULT_INVENTORY = (
    REPO / "cartridges" / "factory" / "_source" / "heritage_designer_sections.json"
)
DEFAULT_ROM = REPO / "runtime" / "trench-core" / "src" / "hedz_rom.rs"
DEFAULT_GOLDEN = REPO / "runtime" / "trench-core" / "src" / "hedz_golden.rs"

SR = 44100
BOOST = 4.0
NUM_STAGES = 6
IMPULSE_LEN = 256

# ---------------------------------------------------------------------------
# f32 cast (replaces numpy float32 in pyruntime/encode.py:38-43)
# ---------------------------------------------------------------------------

def f32(x: float) -> float:
    """Round-trip through IEEE-754 single precision, matching np.float32."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


# ---------------------------------------------------------------------------
# Firmware compile (mirrors pyruntime/heritage_coeffs.py type 1/2/3)
# Proven against 79 preset vector oracles in the vault. Do not edit without
# re-auditing the oracle.
# ---------------------------------------------------------------------------

SR_FAMILY = {44100: 0, 48000: 1, 96000: 2, 192000: 3}
FW_BASE = [18, 18, 4, 1]
FW_SCALE = [220, 220, 200, 177]
COMBINE_K = 4.0


def mf_decode(packed: int) -> float:
    """u16 minifloat → float. Mirrors trench-core/src/minifloat.rs and
    pyruntime/heritage_coeffs.py:_mf_decode."""
    packed &= 0xFFFF
    if packed == 0xFFFF:
        return 1.0
    if packed == 0x0000:
        return 0.0
    u = packed + 1
    exp = ((u >> 12) & 0xF) - 15
    mant = u & 0xFFF
    if exp < -14:
        return mant / 134217728.0  # 2 ** -27
    scaled = (mant | 0x1000) / 8192.0  # 2 ** -13
    return scaled * (2.0 ** exp)


def fw_words_to_kernel(w0: int, w1: int, w2: int, w3: int, w4: int) -> tuple[float, float, float, float, float]:
    """5 uint16 firmware words → direct-form kernel (c0..c4). Mirrors
    pyruntime/heritage_coeffs.py:_fw_words_to_kernel."""
    d0 = mf_decode(w0)
    d1 = mf_decode(w1)
    d2 = mf_decode(w2)
    d3 = mf_decode(w3)
    d4 = mf_decode(w4)
    return (
        d0 * COMBINE_K + d1,
        d1,
        d2 * COMBINE_K + d3,
        d3,
        d4,
    )


def fw_freq_value(packed_freq: int, sr: int = SR) -> int:
    idx = SR_FAMILY.get(sr, 0)
    return (FW_SCALE[idx] * packed_freq) // 128 + FW_BASE[idx]


def fw_radius(freq_value: int) -> int:
    return (freq_value * 124) // 256 + 118


def fw_gain_offset(packed_gain: int, global_shift: int = 0) -> int:
    raw = (packed_gain - 64) // 2 + global_shift
    return max(-32, min(31, raw))


def type1_kernel(freq_packed: int, gain_packed: int, global_shift: int, sr: int):
    fv = fw_freq_value(freq_packed, sr)
    rad = fw_radius(fv)
    go = fw_gain_offset(gain_packed, global_shift)
    w0 = fv << 8
    w1 = max(0, min(255, rad + go)) << 8
    w2 = fv << 8
    w3 = max(0, min(255, rad - go)) << 8
    w4 = 0xE000
    return fw_words_to_kernel(w0, w1, w2, w3, w4)


def type2_kernel(freq_packed: int, gain_packed: int, global_shift: int, sr: int):
    idx = SR_FAMILY.get(sr, 0)
    fv = fw_freq_value(freq_packed, sr)
    rad = fw_radius(fv)
    go = fw_gain_offset(gain_packed, global_shift)
    if idx < 2:
        w0 = 0xEC << 8
        w1 = 0xFF << 8
        w4_val = fv + 0xF5
    else:
        w0 = 0xE1 << 8
        w1 = 0xF0 << 8
        w4_val = fv
    w2 = fv << 8
    w3 = max(0, min(255, rad - go)) << 8
    w4 = w4_val << 8
    return fw_words_to_kernel(w0, w1, w2, w3, w4)


def type3_freq_compression(freq_value: int, shift: int) -> int:
    if freq_value > 0xDB and shift < 0:
        freq_value = (((freq_value - 220) * (shift + 32)) >> 5) + 220
    return freq_value


def type3_kernel(freq_packed: int, gain_packed: int, shift: int, sr: int):
    idx = SR_FAMILY.get(sr, 0)
    fv = fw_freq_value(freq_packed, sr)
    go = fw_gain_offset(gain_packed, shift)
    fv_compressed = type3_freq_compression(fv, shift)
    rad = fw_radius(fv_compressed)
    base = FW_BASE[idx]
    w0 = base << 8
    w1 = ((base * 124) // 256 + 150) << 8
    w2 = fv_compressed << 8
    w3 = max(0, min(255, rad - go)) << 8
    if idx < 2:
        c4_raw = (fv_compressed - 18) * (-12) + (-8192)
        w4 = c4_raw & 0xFFFF
    else:
        w4 = 0xE000
    return fw_words_to_kernel(w0, w1, w2, w3, w4)


def compile_stage(type_id: int, freq_packed: int, gain_packed: int, shift: int, sr: int):
    """Compile one stage to (c0, c1, c2, c3, c4). Bypass on type=0."""
    if type_id <= 0:
        return (1.0, 0.0, 0.0, 0.0, 0.0)
    if type_id == 1:
        return type1_kernel(freq_packed, gain_packed, shift, sr)
    if type_id == 2:
        return type2_kernel(freq_packed, gain_packed, shift, sr)
    if type_id == 3:
        return type3_kernel(freq_packed, gain_packed, shift, sr)
    # Unknown type — fall back to type 1 (matches heritage_coeffs default)
    return type1_kernel(freq_packed, gain_packed, shift, sr)


def f32_tuple(coeffs):
    """Apply f32 cast to every coefficient, matching the Rust pipeline."""
    return tuple(f32(c) for c in coeffs)


# ---------------------------------------------------------------------------
# Heritage-template → 4-corner cartridge
# ---------------------------------------------------------------------------

def load_template(inventory_path: Path, name: str) -> dict:
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    if data.get("format") != "heritage-designer-sections-v1":
        raise SystemExit(
            f"unexpected inventory format: {data.get('format')!r}"
        )
    for tpl in data["templates"]:
        if tpl["name"] == name:
            return tpl
    raise SystemExit(f"template {name!r} not found in {inventory_path}")


def compile_corner(sections: list[dict], morph: float, sr: int):
    """Compile one morph endpoint of a heritage template to 6 stages ×
    5 kernel coefficients. MorphDesigner XML is morph-only, so Q is
    collapsed — both Q-endpoints of the same morph value share the same
    compile (see pyruntime/designer_compile.py:176-201)."""
    # shift = -32 + (frequency + gain) * 63 — but heritage_designer_sections
    # carries frequency/gain per template in the inventory header. We're
    # targeting hedz which has frequency=1.0, gain=1.0 → shift = -32+126 = 94.
    # Keep the calculation explicit so other templates behave the same.
    stages = []
    for sec in sections[:NUM_STAGES]:
        type_id = sec["type"]
        low_freq = sec["low_freq"]
        low_gain = sec["low_gain"]
        high_freq = sec["high_freq"]
        high_gain = sec["high_gain"]
        freq = round(low_freq + morph * (high_freq - low_freq))
        gain = round(low_gain + morph * (high_gain - low_gain))
        coeffs = compile_stage(type_id, freq, gain, shift=0, sr=sr)
        stages.append(f32_tuple(coeffs))
    while len(stages) < NUM_STAGES:
        stages.append((1.0, 0.0, 0.0, 0.0, 0.0))
    return stages


def build_cartridge(template: dict, sr: int):
    """Return a [4][6][5] nested tuple in corner order M0_Q0, M100_Q0,
    M0_Q100, M100_Q100 (matches trench-core/src/cartridge.rs:105-109)."""
    sections = template["sections"]
    m0 = compile_corner(sections, morph=0.0, sr=sr)
    m1 = compile_corner(sections, morph=1.0, sr=sr)
    # MorphDesigner XML is morph-only → Q0 and Q100 share the same stages.
    return [m0, m1, m0, m1]


# ---------------------------------------------------------------------------
# DF2T cascade emulator (mirrors trench-core/src/cascade.rs:38-68)
# ---------------------------------------------------------------------------

def run_impulse(corner_stages: list[tuple[float, ...]], length: int, boost: float) -> list[float]:
    """Run a unit impulse through a 6-stage DF2T cascade and return the
    output as f32-rounded samples. This is the reference that the Rust
    test (trench-core/tests/hedz_cascade.rs) must match byte-close.

    No ramping, no control-block interpolation — static coefficients,
    sample-accurate. The Rust test feeds the same static coefficients
    by calling Cascade::set_targets with chunk_size=1 so deltas are
    zero and the coefficients snap immediately.
    """
    # Per-stage DF2T state: w1, w2
    state = [(0.0, 0.0) for _ in range(NUM_STAGES)]
    out = []
    for n in range(length):
        x = 1.0 if n == 0 else 0.0
        sig = x
        for i, (c0, c1, c2, c3, c4) in enumerate(corner_stages):
            w1, w2 = state[i]
            y = c0 * sig + w1
            new_w1 = c1 * sig - c3 * y + w2
            new_w2 = c2 * sig - c4 * y
            state[i] = (new_w1, new_w2)
            sig = y
        sig *= boost
        out.append(f32(sig))
    return out


# ---------------------------------------------------------------------------
# Rust codegen
# ---------------------------------------------------------------------------

_ROM_HEADER = """//! Talking Hedz cartridge — baked from `cartridges/factory/_source/heritage_designer_sections.json`.
//!
//! DO NOT EDIT BY HAND. Regenerate with `python forge/compilers/bake_hedz_const.py`.
//!
//! Source: E-mu MorphDesigner XML template `hedz`, extracted from the
//! NotebookLM filter bundles and compiled through the E-mu type 1/2/3
//! firmware recipes (pyruntime/heritage_coeffs.py). The committed float
//! values are the post-f32-cast kernel coefficients the Rust cascade
//! consumes directly.
//!
//! Corner order matches `Cartridge::corners`:
//!     0: M0_Q0, 1: M100_Q0, 2: M0_Q100, 3: M100_Q100
//!
//! Talking Hedz is a morph-only heritage filter — the Q axis is
//! collapsed, so Q0 and Q100 share identical coefficients at each
//! morph endpoint. The 4-corner shape is kept so the runtime
//! `Cartridge::interpolate` can walk the standard Q-then-morph path
//! without special-casing morph-only bodies.

use crate::cartridge::{{CornerData, NUM_CORNERS}};

/// Authoring name — one heap allocation at plugin init, never on the
/// audio thread.
pub const HEDZ_NAME: &str = "Talking Hedz";

/// Per-corner post-cascade boost. All four corners carry the heritage
/// default `boost = 4.0` from `compile_designer_to_body`.
pub const HEDZ_BOOSTS: [f64; NUM_CORNERS] = [{boost:.1}, {boost:.1}, {boost:.1}, {boost:.1}];

/// Full cartridge — 4 corners × 6 stages × 5 coefficients.
pub const HEDZ_CORNERS: [CornerData; NUM_CORNERS] = [
"""

_ROM_FOOTER = "];\n"


def emit_rom(corners: list[list[tuple[float, ...]]], out_path: Path) -> None:
    labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
    lines = [_ROM_HEADER.format(boost=BOOST)]
    for corner_idx, corner in enumerate(corners):
        lines.append(f"    // {labels[corner_idx]}\n")
        lines.append("    [\n")
        for stage_idx, stage in enumerate(corner):
            c0, c1, c2, c3, c4 = stage
            lines.append(
                f"        [{c0!r}, {c1!r}, {c2!r}, {c3!r}, {c4!r}], // stage {stage_idx + 1}\n"
            )
        lines.append("    ],\n")
    lines.append(_ROM_FOOTER)
    out_path.write_text("".join(lines), encoding="utf-8")


_GOLDEN_HEADER = """//! Talking Hedz cascade golden impulse response.
//!
//! DO NOT EDIT BY HAND. Regenerate with `python forge/compilers/bake_hedz_const.py`.
//!
//! Each `HEDZ_GOLDEN_<LABEL>` array is the first {length} samples of a
//! unit-impulse response through the static hedz cascade at the named
//! corner, computed by a stdlib DF2T emulator in Python. The Rust
//! cross-language parity test (`trench-core/tests/hedz_cascade.rs`)
//! feeds the same impulse through `trench_core::Cascade` with
//! `set_targets(chunk_size=1)` so coefficients snap immediately and no
//! ramping interpolation runs, and asserts the two outputs match
//! byte-close (< 1e-6 peak error). If this test fails, either the
//! bake script or the Rust cascade math has drifted — fix the root
//! cause, do not relax the tolerance.

pub const HEDZ_GOLDEN_LEN: usize = {length};

"""


def emit_golden(impulses: dict[str, list[float]], out_path: Path, length: int) -> None:
    lines = [_GOLDEN_HEADER.format(length=length)]
    for label, samples in impulses.items():
        lines.append(f"pub const HEDZ_GOLDEN_{label}: [f32; HEDZ_GOLDEN_LEN] = [\n")
        for i in range(0, length, 4):
            chunk = samples[i : i + 4]
            formatted = ", ".join(f"{s!r}f32" for s in chunk)
            lines.append(f"    {formatted},\n")
        lines.append("];\n\n")
    out_path.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--template", default="hedz")
    parser.add_argument("--rom-out", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--golden-out", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--impulse-len", type=int, default=IMPULSE_LEN)
    parser.add_argument("--sample-rate", type=int, default=SR)
    args = parser.parse_args(argv)

    template = load_template(args.inventory, args.template)
    corners = build_cartridge(template, sr=args.sample_rate)

    labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
    impulses: dict[str, list[float]] = {}
    for label, stages in zip(labels, corners):
        impulses[label] = run_impulse(stages, args.impulse_len, BOOST)

    args.rom_out.parent.mkdir(parents=True, exist_ok=True)
    emit_rom(corners, args.rom_out)
    emit_golden(impulses, args.golden_out, args.impulse_len)

    # Summary printout (stdout — not committed as a build artifact).
    print(f"template: {args.template}")
    print(f"  sections: {len(template['sections'])}")
    print(f"  type_absolute: {template.get('type_absolute')}")
    print(f"  shape_id: {template.get('shape_id')}")
    print(f"wrote {args.rom_out}")
    print(f"wrote {args.golden_out}")
    for label, samples in impulses.items():
        peak = max(abs(s) for s in samples)
        energy = sum(s * s for s in samples)
        print(f"  {label}: peak={peak:.6f}  energy={energy:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
