"""DRUMKIT MAKER - render a playable drum kit from ANY body via swipe gestures.

The insight (Tyson 2026-07-12): a fast MORPH swipe through resonant states
IS a percussive event. So every body is secretly a drum kit - excite it with
clicks/noise and flick the morph. This tool renders the kit offline through
the SHIPPED engine (trench_core.dll, block-automated morph = the real thing).

Usage:
  python tools/drumkit_maker.py --body dev/tmp/zapkit/ZAP.body240 --out dev/tmp/zapkit/kit
  python tools/drumkit_maker.py --body "TRENCH1...." --out kit      (clips paste straight in)
  python tools/drumkit_maker.py --scratch --out dev/tmp/zapkit      (vowel formant-scratch demo)
"""
from __future__ import annotations
import argparse
import math
import os
import struct
import sys
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from pyruntime import trench_ffi
from tools.body240_clip import decode_clip, encode_clip

SR = 48000
BLOCK = 64
VOWEL_BODY = os.path.join(os.path.dirname(__file__), "..",
                          "juce-shell", "assets", "bodies", "vowel.body240")

rng = np.random.default_rng(0xD12)


# --- exciters ----------------------------------------------------------------
def click(dur_s: float) -> np.ndarray:
    n = int(dur_s * SR)
    x = np.zeros(n, np.float32)
    x[0] = 0.9
    return x


def noise_burst(dur_s: float, tail_s: float, total_s: float) -> np.ndarray:
    n = int(total_s * SR)
    x = rng.standard_normal(n).astype(np.float32) * 0.5
    t = np.arange(n) / SR
    env = np.exp(-np.maximum(0.0, t - dur_s) / max(1e-4, tail_s))
    env[t > dur_s + 6 * tail_s] = 0.0
    return (x * env).astype(np.float32)


def saw(freq: float, dur_s: float) -> np.ndarray:
    t = np.arange(int(dur_s * SR)) / SR
    return (0.5 * (2.0 * ((t * freq) % 1.0) - 1.0)).astype(np.float32)


# --- gestures ----------------------------------------------------------------
def swipe(n_samples: int, m0: float, m1: float, t0: float, t1: float,
          curve: float = 1.0) -> np.ndarray:
    """Per-block morph track: hold m0, swipe m0->m1 during [t0,t1], hold m1."""
    nb = max(1, (n_samples + BLOCK - 1) // BLOCK)
    tb = (np.arange(nb) * BLOCK + BLOCK / 2) / SR
    u = np.clip((tb - t0) / max(1e-4, t1 - t0), 0.0, 1.0) ** curve
    return (m0 + (m1 - m0) * u).astype(np.float64)


def render(body: bytes, x: np.ndarray, morph_blocks, q: float) -> np.ndarray:
    nb = len(morph_blocks)
    out = trench_ffi.engine_render_automated(
        body, list(morph_blocks), [q] * nb, x.astype(np.float32).tobytes(),
        sr=float(SR), block=BLOCK)
    return np.frombuffer(out, np.float32).copy()


def finish(y: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(y))) or 1.0
    y = y * (10 ** (-1.0 / 20.0) / peak)          # peak-normalize to -1 dBFS
    keep = np.where(np.abs(y) > 10 ** (-60 / 20))[0]
    if len(keep):
        y = y[: min(len(y), keep[-1] + int(0.02 * SR))]
    n_fade = min(len(y), int(0.02 * SR))
    y[-n_fade:] *= np.linspace(1.0, 0.0, n_fade) ** 2
    return y


def write_wav(path: str, y: np.ndarray) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())


# --- the kit grammar ---------------------------------------------------------
# name: (exciter, morph swipe (m0, m1, t0, t1, curve), Q)
# Short NOISE BURSTS, never bare clicks: a dirac starves the resonators
# (~46 dB quieter ring, measured); a few ms of noise pumps every mode.
def kit_pieces() -> dict:
    return {
        "kick":     (noise_burst(0.006, 0.004, 0.6), (0.35, 0.02, 0.000, 0.040, 1.4), 1.00),
        "snare":    (noise_burst(0.020, 0.050, 0.4), (0.45, 0.22, 0.000, 0.055, 1.0), 0.75),
        "hat_shut": (noise_burst(0.008, 0.020, 0.15), (0.93, 0.93, 0.0, 0.01, 1.0), 0.65),
        "hat_open": (noise_burst(0.010, 0.090, 0.5),  (0.95, 0.90, 0.0, 0.30, 1.0), 0.85),
        "tom_lo":   (noise_burst(0.004, 0.003, 0.6), (0.30, 0.10, 0.000, 0.060, 1.2), 1.00),
        "tom_hi":   (noise_burst(0.004, 0.003, 0.6), (0.55, 0.32, 0.000, 0.060, 1.2), 1.00),
        "zap":      (noise_burst(0.003, 0.002, 0.7), (1.00, 0.00, 0.000, 0.070, 0.8), 1.00),
        "riser":    (noise_burst(0.300, 0.200, 0.8), (0.00, 1.00, 0.000, 0.650, 1.0), 0.95),
    }


def make_kit(body: bytes, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    lines = [f"TRENCH DRUM KIT - rendered through the shipped engine",
             f"body clip:", encode_clip(body), ""]
    for name, (x, sw, q) in kit_pieces().items():
        y = finish(render(body, x, swipe(len(x), *sw), q))
        write_wav(os.path.join(out_dir, f"{name}.wav"), y)
        lines.append(f"{name:9s} swipe {sw[0]:.2f}->{sw[1]:.2f} in {int((sw[3]-sw[2])*1000)}ms  Q={q}")
        print(f"  {name}: {len(y)/SR*1000:.0f} ms")
    with open(os.path.join(out_dir, "KIT.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"kit written to {out_dir}")


# --- the formant scratch demo -------------------------------------------------
def make_scratch(out_dir: str) -> None:
    body = open(VOWEL_BODY, "rb").read()
    x = saw(110.0, 2.6)
    nb = (len(x) + BLOCK - 1) // BLOCK
    tb = (np.arange(nb) * BLOCK + BLOCK / 2) / SR
    m = np.full(nb, 0.1)
    # scratch phrase: wub - ya - yaow - wubba-wubba - eh
    strokes = [(0.10, 0.35, 0.1, 0.9), (0.45, 0.62, 0.9, 0.1),
               (0.75, 0.95, 0.1, 1.0), (0.95, 1.10, 1.0, 0.3),
               (1.25, 1.33, 0.3, 0.9), (1.33, 1.41, 0.9, 0.2),
               (1.41, 1.49, 0.2, 0.9), (1.49, 1.57, 0.9, 0.2),
               (1.75, 2.10, 0.2, 0.75), (2.20, 2.50, 0.75, 0.45)]
    for (t0, t1, m0, m1) in strokes:
        sel = (tb >= t0) & (tb < t1)
        u = np.clip((tb[sel] - t0) / (t1 - t0), 0, 1)
        m[sel] = m0 + (m1 - m0) * u
        m[tb >= t1] = m1
    y = finish(render(body, x, m, 0.55))
    os.makedirs(out_dir, exist_ok=True)
    write_wav(os.path.join(out_dir, "vowel_scratch.wav"), y)
    print(f"vowel_scratch.wav written ({len(y)/SR:.2f}s)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", help="path to .body240 OR a TRENCH1 clip string")
    ap.add_argument("--out", default="dev/tmp/zapkit/kit")
    ap.add_argument("--scratch", action="store_true", help="render the vowel formant-scratch demo")
    a = ap.parse_args()
    if a.scratch:
        make_scratch(a.out)
    if a.body:
        body = decode_clip(a.body) if a.body.startswith("TRENCH1") \
            else open(a.body, "rb").read()
        make_kit(body, a.out)


if __name__ == "__main__":
    main()
