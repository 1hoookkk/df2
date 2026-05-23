#!/usr/bin/env python3
"""author_body.py — direct-authoring path for original df2 bodies.

Takes a TOML body spec (6 slots x 4 corners, universal vocabulary labels)
and emits a compiled-v1 cartridge JSON ready to load in the df2 player.

No fitter. No optimizer. No reference target. The author specifies
(freq, radius, val1) per slot per corner and the universal vocabulary
labels (Root/Body/Mouth/Scar/Edge/Rip) provide the role names.

Spec format (TOML):

    name = "Speaker Knockerz"
    boost = 4.0

    [vocabulary]
    slot_0 = { label = "Root",  desc = "sub anchor" }
    slot_1 = { label = "Body",  desc = "low mass" }
    slot_2 = { label = "Mouth", desc = "formant" }
    slot_3 = { label = "Scar",  desc = "anti-resonance" }
    slot_4 = { label = "Edge",  desc = "bite" }
    slot_5 = { label = "Rip",   desc = "shatter" }

    [[corner.M0_Q0.stages]]
    type = "resonator"      # or "resonator_with_zero" or "passthrough"
    freq_hz = 55.0
    radius  = 0.94
    val1    = 0.0
    # resonator_with_zero adds: zero_freq_hz, zero_radius

    # ... 5 more stages for M0_Q0
    # ... then [[corner.M100_Q0.stages]] etc for the other 3 corners

Usage:
    python tools/author_body.py bodies/<spec>.toml [-o bodies/<spec>.cart.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import tomli

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import math
import numpy as np

from pyruntime.body import Body  # noqa: E402
from pyruntime.corner import CornerArray, CornerName, CornerState  # noqa: E402
from pyruntime.stage_math import resonator, resonator_with_zero  # noqa: E402
from pyruntime.stage_params import StageParams  # noqa: E402
from pyruntime.constants import SR  # noqa: E402

CORNER_KEYS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
CORNER_NAME = {
    "M0_Q0":     CornerName.A,
    "M0_Q100":   CornerName.B,
    "M100_Q0":   CornerName.C,
    "M100_Q100": CornerName.D,
}
SLOTS = 6


def build_stage(stage_spec: dict, slot_idx: int) -> StageParams:
    """Convert one stage spec entry into StageParams via stage_math."""
    t = stage_spec.get("type", "resonator")
    if t == "passthrough":
        return StageParams.passthrough()
    freq = float(stage_spec["freq_hz"])
    radius = float(stage_spec["radius"])
    val1 = float(stage_spec.get("val1", 0.0))
    if t == "resonator":
        return resonator(freq, radius, val1)
    if t == "resonator_with_zero":
        zf = float(stage_spec["zero_freq_hz"])
        zr = float(stage_spec["zero_radius"])
        return resonator_with_zero(freq, radius, val1, zf, zr)
    raise ValueError(f"slot {slot_idx}: unknown stage type {t!r}")


def build_corner(corner_spec: dict, corner_label: str, boost: float) -> CornerState:
    """Build a CornerState from a corner's stage list."""
    stages_in = corner_spec.get("stages", [])
    if len(stages_in) != SLOTS:
        raise ValueError(
            f"corner {corner_label}: expected {SLOTS} stages, got {len(stages_in)}"
        )
    stages = [build_stage(s, i) for i, s in enumerate(stages_in)]
    return CornerState(stages=stages, boost=boost)


def peak_normalize_stages(stages_json: list[dict], sr: float = SR) -> list[dict]:
    """For each stage's [c0..c4] kernel, decode → biquad (b0,b1,b2,a1,a2),
    compute peak |H(e^jw)| across the audible band (20 Hz - sr/2.2), then
    scale c4 (= b0) by 1/peak so the stage's peak magnitude is unity.

    Fixes the recurring LF-gain blow-up where high-radius low-frequency
    resonators stack DC gain of (1-r)^-2 per stage. After normalization,
    every stage contributes <=0 dB at its peak and the cascade is well-
    behaved across the spectrum.
    """
    out = []
    freqs = np.logspace(np.log10(20.0), np.log10(sr/2.2), 1024)
    omegas = 2.0 * np.pi * freqs / sr
    cosw  = np.cos(omegas);   sinw  = np.sin(omegas)
    cos2w = np.cos(2*omegas); sin2w = np.sin(2*omegas)
    for s in stages_json:
        c0, c1, c2, c3, c4 = s["c0"], s["c1"], s["c2"], s["c3"], s["c4"]
        # decode (matches pyruntime/render.py and JS player)
        a1 = c2 - 2.0
        a2 = 1.0 - c3
        b0 = c4
        b1 = (c0 - 2.0) * c4
        b2 = (1.0 - c1) * c4
        # passthrough? (c0=2,c1=1,c2=2,c3=1,c4=1) → b0=1,b1=0,b2=0,a1=0,a2=0 → flat
        if abs(b0) < 1e-12:
            out.append(s); continue
        numRe = b0 + b1*cosw + b2*cos2w
        numIm = -b1*sinw - b2*sin2w
        denRe = 1.0 + a1*cosw + a2*cos2w
        denIm = -a1*sinw - a2*sin2w
        denMag2 = denRe*denRe + denIm*denIm
        denMag2 = np.maximum(denMag2, 1e-30)
        mag = np.sqrt((numRe*numRe + numIm*numIm) / denMag2)
        peak = float(np.max(mag))
        if peak < 1e-9 or not np.isfinite(peak):
            out.append(s); continue
        # scale c4 (=b0) by 1/peak — c0/c1 are RATIOS b1/b0 and b2/b0 so they
        # remain unchanged; the whole numerator scales together.
        out.append({
            "c0": c0, "c1": c1, "c2": c2, "c3": c3, "c4": c4 / peak,
        })
    return out


def author_body(spec_path: Path, out_path: Path | None = None) -> Path:
    """Compile a TOML spec into a compiled-v1 cartridge JSON."""
    with open(spec_path, "rb") as f:
        spec = tomli.load(f)

    name = spec.get("name", spec_path.stem)
    boost = float(spec.get("boost", 4.0))
    filter_type = spec.get("filter_type")

    corner_block = spec.get("corner", {})
    missing = [k for k in CORNER_KEYS if k not in corner_block]
    if missing:
        raise ValueError(f"spec missing corner(s): {missing}")

    states = {
        label: build_corner(corner_block[label], label, boost)
        for label in CORNER_KEYS
    }
    corners = CornerArray(
        a=states["M0_Q0"],
        b=states["M0_Q100"],
        c=states["M100_Q0"],
        d=states["M100_Q100"],
    )
    body = Body(
        name=name, corners=corners, boost=boost,
        filter_type=filter_type,
    )

    payload = json.loads(body.to_compiled_json(provenance="author_body"))
    payload["format"] = "compiled-v1"

    # ── peak-normalize each stage in each keyframe ──────────────────────
    for kf in payload.get("keyframes", []):
        kf["stages"] = peak_normalize_stages(kf["stages"], sr=SR)

    vocab = spec.get("vocabulary")
    if vocab:
        payload["vocabulary"] = vocab

    if out_path is None:
        out_path = spec_path.with_suffix(".cart.json")
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"authored: {name}")
    print(f"  spec : {spec_path}")
    print(f"  cart : {out_path}")
    print(f"  corners: {', '.join(CORNER_KEYS)}")
    print(f"  slots : {SLOTS} active + {12 - SLOTS} passthrough = 12 total")
    if vocab:
        print(f"  vocabulary:")
        for i in range(SLOTS):
            entry = vocab.get(f"slot_{i}", {})
            print(f"    slot {i}: {entry.get('label', '?'):8} — {entry.get('desc', '')}")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec", type=Path, help="path to TOML body spec")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output cartridge path (default: <spec>.cart.json)")
    args = ap.parse_args()
    if not args.spec.exists():
        print(f"!! spec not found: {args.spec}", file=sys.stderr)
        return 1
    author_body(args.spec, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
