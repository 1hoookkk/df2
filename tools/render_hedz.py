#!/usr/bin/env python3
"""render_hedz.py — render a calibration_re filter JSON at one M/Q corner.

Replicates the Rust FilterEngine pipeline:
  cascade (DF2T, 6 stages) -> AGC -> boost -> DC blocker (~20 Hz)

The calibration JSON (e.g. Talking_Hedz.json from trenchwork_clean) carries
pole_freq_hz + radius + val1/val2/val3 per stage. a1 is reconstructed at the
file's authoring sample_rate (39062.5 Hz), then the SOS cascade runs at the
capture SR (44100 Hz) — matching what EmulatorX3 VST does.

Usage:
    python tools/render_hedz.py dry.wav --calib Talking_Hedz.json --corner M0_Q0 -o cand.wav
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import lfilter, sosfilt

SAMPLE_RATE_CAPTURE = 44100.0
BLOCK_SIZE = 32

# In-repo validated 4-corner Talking Hedz cartridge (= P2k_013).
DEFAULT_CALIB = Path(__file__).resolve().parent.parent / "ref" / "p2k_skins" / "00_talking_hedz.json"

AGC_TABLE = np.array(
    [1.0001, 1.0001, 0.996, 0.990, 0.920, 0.500, 0.200, 0.160,
     0.120, 0.120, 0.120, 0.120, 0.120, 0.120, 0.120, 0.120],
    dtype=np.float32,
)


# Runtime M/Q corner -> P2K JSON corner key.
# re-proven-facts.md (CLOSED): "P2K M0_Q100 = runtime M100_Q0 and vice versa".
# The anti-diagonal corners are swapped; the diagonal corners are identical.
RUNTIME_TO_P2K = {
    "M0_Q0":     "M0_Q0",
    "M0_Q100":   "M100_Q0",
    "M100_Q0":   "M0_Q100",
    "M100_Q100": "M100_Q100",
}


def load_calib(path: Path) -> tuple[dict, float, float]:
    """Load a calibration/cartridge JSON -> (corner_map, authoring_sr, boost).

    Supports two layouts:
      - {"corners": {"M0_Q0": {"stages": [...]}, ...}}    (Talking_Hedz / P2k_013)
      - {"keyframes": [{"label": "M0_Q0", "stages": [...], "boost": ...}, ...]}
        (compiled cartridge, e.g. ref/p2k_skins/00_talking_hedz.json)
    corner_map keys are the JSON corner labels; values carry a "stages" list.
    """
    calib = json.loads(path.read_text())
    sr = float(calib.get("sample_rate", calib.get("sampleRate", 39062.5)))
    if "keyframes" in calib:
        cmap = {kf["label"]: kf for kf in calib["keyframes"]}
        boost = float(calib["keyframes"][0].get("boost", calib.get("boost", 4.0)))
    else:
        cmap = calib["corners"]
        boost = float(calib.get("boost", 4.0))
    return cmap, sr, boost


def build_sos_from_calib(stages: list[dict], authoring_sr: float) -> np.ndarray:
    """P2K / calibration_re stage list -> scipy SOS matrix.

    a1: used directly if the stage carries it (P2k_013.json, extracted at the
        44100 Hz ROM table — re-proven-facts.md). Otherwise reconstructed from
        pole_freq_hz as a1 = -2*r*cos(2pi*f / authoring_sr) (Talking_Hedz.json).
    a2 = r * r
    b0 = 1 + val1,  b1 = a1 + val2,  b2 = a2 - val3   (P2K encode formula)
    """
    rows = []
    for st in stages:
        r = float(st["radius"] if "radius" in st else st["r"])
        if "a1" in st:
            a1 = float(st["a1"])
        else:
            f = float(st["pole_freq_hz"])
            a1 = -2.0 * r * math.cos(2.0 * math.pi * f / authoring_sr)
        a2 = r * r
        b0 = 1.0 + float(st["val1"])
        b1 = a1 + float(st["val2"])
        b2 = a2 - float(st["val3"])
        rows.append([b0, b1, b2, 1.0, a1, a2])
    return np.asarray(rows, dtype=np.float64)


def apply_agc(samples: np.ndarray) -> np.ndarray:
    samples = samples.astype(np.float32)
    out = np.empty_like(samples)
    gain = np.float32(1.0)
    for i, s in enumerate(samples):
        idx = int(np.uint32(np.float32(gain * abs(s)))) & 0xF
        new_gain = np.float32(gain * AGC_TABLE[idx])
        gain = new_gain if new_gain < np.float32(1.0) else np.float32(1.0)
        out[i] = np.float32(s * gain)
    return out


def apply_boost_ramped(samples: np.ndarray, boost: float) -> np.ndarray:
    samples = samples.astype(np.float32)
    out = samples.copy()
    n = len(samples)
    if n == 0:
        return out
    delta = np.float32((boost - 1.0) / BLOCK_SIZE)
    gain = np.float32(1.0)
    for i in range(min(BLOCK_SIZE, n)):
        gain += delta
        out[i] = np.float32(samples[i] * gain)
    if n > BLOCK_SIZE:
        out[BLOCK_SIZE:] = (samples[BLOCK_SIZE:] * np.float32(boost)).astype(np.float32)
    return out


def apply_dc_blocker(samples: np.ndarray, sr: float = SAMPLE_RATE_CAPTURE) -> np.ndarray:
    r = np.float32(1.0 - (2.0 * np.pi * 20.0 / sr))
    samples = samples.astype(np.float32)
    out = lfilter([1.0, -1.0], [1.0, -float(r)], samples).astype(np.float32)
    out[~np.isfinite(out)] = 0.0
    return out


def load_wav_left(path: Path) -> tuple[int, np.ndarray]:
    sr, data = wavfile.read(str(path))
    if data.dtype.kind in ("i", "u"):
        info = np.iinfo(data.dtype)
        data = data.astype(np.float32) / max(abs(info.min), abs(info.max))
    else:
        data = data.astype(np.float32)
    if data.ndim == 2:
        data = data[:, 0]
    return sr, data


def render(dry: np.ndarray, sos: np.ndarray, boost: float,
           offset: int = 0, native_sr: float = None,
           dc_block: bool = True) -> np.ndarray:
    """native_sr: if set, resample dry to that SR, run cascade, resample back.

    dc_block: apply df2's ~20 Hz DC blocker. Set False to null against an
    E-mu wet capture — the heritage render has no DC blocker, and applying
    one here collapses the null (cascade-only nulls -69 dB at M0_Q0; the
    DC blocker drags that to -3 dB)."""
    from scipy.signal import resample_poly
    from math import gcd

    x = dry[offset:].astype(np.float64)

    if native_sr and native_sr != SAMPLE_RATE_CAPTURE:
        # Hardware-SRC experiment only. Emulator X3 VST parity should normally
        # run the 44.1 kHz host stream directly with decoded coefficients.
        # 44100 / 39062.5 = 88200 / 78125 → gcd=25 → 3528/3125
        up = int(round(SAMPLE_RATE_CAPTURE))
        down = int(round(native_sr * 2)) // 2  # handle .5
        # exact: 44100/39062.5 = 88200/78125
        g = gcd(88200, 78125)  # = 25
        up_r, down_r = 88200 // g, 78125 // g  # 3528, 3125
        x_native = resample_poly(x, down_r, up_r)   # 44100→39062.5
        cascaded_native = sosfilt(sos, x_native)
        cascaded = resample_poly(cascaded_native, up_r, down_r).astype(np.float32)  # 39062.5→44100
    else:
        cascaded = sosfilt(sos, x).astype(np.float32)

    agc_out = apply_agc(cascaded)
    boosted = apply_boost_ramped(agc_out, boost)
    return apply_dc_blocker(boosted) if dc_block else boosted


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("dry", type=Path)
    p.add_argument("--calib", type=Path, default=DEFAULT_CALIB,
                   help="P2K / calibration JSON. Defaults to the in-repo "
                        "ref/p2k_skins/00_talking_hedz.json cartridge.")
    p.add_argument("--corner", required=True,
                   choices=["M0_Q0", "M0_Q100", "M100_Q0", "M100_Q100"],
                   help="M/Q corner. By default interpreted as a RUNTIME corner "
                        "(matches the wet capture labels) and swapped to the P2K "
                        "JSON key. Pass --p2k-corner to use the JSON key as-is.")
    p.add_argument("--p2k-corner", action="store_true",
                   help="Treat --corner as the raw P2K JSON key (no runtime swap).")
    p.add_argument("--no-dc-block", action="store_true",
                   help="Skip the ~20 Hz DC blocker. Use this when nulling against "
                        "an E-mu wet capture — the heritage render has none.")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--native", action="store_true",
                   help="Slow hardware-SRC experiment: resample dry to authoring "
                        "SR, cascade there, resample back. Do not use for normal "
                        "Emulator X3 VST parity.")
    p.add_argument("-o", "--output", type=Path, default=None)
    args = p.parse_args(argv)

    cmap, authoring_sr, boost = load_calib(args.calib)
    p2k_corner = args.corner if args.p2k_corner else RUNTIME_TO_P2K[args.corner]
    if p2k_corner != args.corner:
        print(f"corner: runtime {args.corner} -> P2K {p2k_corner}", file=sys.stderr)
    stages = cmap[p2k_corner]["stages"]
    sos = build_sos_from_calib(stages, authoring_sr)

    sr, dry = load_wav_left(args.dry)
    native_sr = authoring_sr if args.native else None
    if args.native:
        print("warning: --native is a slow hardware-SRC experiment, not the normal "
              "44.1 kHz Emulator X3 VST parity path.", file=sys.stderr)
    out = render(dry, sos, boost, args.offset, native_sr=native_sr,
                 dc_block=not args.no_dc_block)

    dest = args.output or args.dry.parent / f"{args.dry.stem}_{args.corner}.wav"
    wavfile.write(str(dest), sr, out)
    rms = 20 * np.log10(np.sqrt(np.mean(out.astype(np.float64) ** 2)) + 1e-30)
    print(f"wrote {len(out)} samples → {dest}  ({rms:.1f} dBFS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
