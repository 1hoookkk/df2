#!/usr/bin/env python3
"""CV-WAV performance render — the Forge capture mechanism (DAW automation as audio).

MECHANISM
  In FL Studio, map the Morph (and Q) automation to a DC audio signal (CV) and
  bounce each as a standard .wav. This script parses the WAV amplitude directly
  into m(t) / q(t) and renders a source loop through the SHIPPED TRENCH engine
  (engine_render_slam: AGC + Mackie desk drive + optional QSound). The morph is
  the loop; this bakes the performed morph into the audio.

  + Immutable & undeniable: the audio file IS the automation log.
  + Sample-accurate, zero event jitter (CV is sampled at audio rate).
  - Requires a manual audio-render step in the DAW per performance.

CV CONVENTION
  Param value lives in [0,1]. Unipolar CV (0..1) maps 1:1. Bipolar CV (-1..1)
  is auto-detected (min < ~0) and mapped (x+1)/2. Force with --cv-range.
  CV and loop need not share sample-rate or length: each CV is resampled onto
  the loop's timeline, so alignment is automatic.

USAGE
  python tools/cv_perform_render.py --loop bass.wav --body bodies/x.cart.json \
      --morph-cv morph_cv.wav [--q-cv q_cv.wav | --q 0.9] \
      [--slam 0.45] [--five-d 0] [--block 256] --out baked.wav
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from src.utils.body240 import CORNER_ORDER, raw_from_words  # noqa: E402

RUNTIME_SR = 39062.5  # bodies are authored at this rate; render here for correct Hz


def load_body(path: Path) -> bytes:
    """Accept a raw .body240 or a compiled-v1 .cart.json and return 240 bytes."""
    if path.suffix == ".body240":
        return path.read_bytes()
    doc = json.loads(path.read_text(encoding="utf-8"))
    words = {kf["label"]: [tuple(int(x) for x in w) for w in kf["packedWords"]]
             for kf in doc["keyframes"]}
    missing = [c for c in CORNER_ORDER if c not in words]
    if missing:
        raise SystemExit(f"{path.name}: cart missing corners {missing}")
    return raw_from_words(words)


def read_mono(path: Path) -> tuple[np.ndarray, float]:
    sr, data = wavfile.read(str(path))
    data = np.asarray(data)
    if data.dtype.kind in "iu":  # int PCM -> [-1,1]
        data = data.astype(np.float64) / float(np.iinfo(data.dtype).max + 1)
    else:
        data = data.astype(np.float64)
    if data.ndim > 1:  # stereo -> mono mean
        data = data.mean(axis=1)
    return data, float(sr)


def cv_to_param(cv_samples: np.ndarray, n: int, cv_range: str) -> np.ndarray:
    """Resample a CV onto n loop-samples and map its amplitude to a [0,1] param."""
    src = cv_samples if len(cv_samples) else np.zeros(1)
    x = np.interp(np.linspace(0.0, 1.0, n), np.linspace(0.0, 1.0, len(src)), src)
    bipolar = (cv_range == "bipolar") or (cv_range == "auto" and float(x.min()) < -0.02)
    if bipolar:
        x = (x + 1.0) * 0.5
    return np.clip(x, 0.0, 1.0)


def per_block(param_samples: np.ndarray, n: int, block: int) -> list[float]:
    """One value per render block, sampled at the block centre (deterministic)."""
    nb = max(1, (n + block - 1) // block)
    idx = np.clip((np.arange(nb) * block + block // 2), 0, n - 1)
    return param_samples[idx].astype(float).tolist()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--loop", type=Path, required=True, help="source audio loop (.wav)")
    ap.add_argument("--body", type=Path, required=True, help=".body240 or compiled-v1 .cart.json")
    ap.add_argument("--morph-cv", type=Path, help="Morph CV .wav (DC automation render)")
    ap.add_argument("--q-cv", type=Path, help="Q CV .wav; omit to hold Q at --q")
    ap.add_argument("--q", type=float, default=0.0, help="constant Q when --q-cv absent")
    ap.add_argument("--morph", type=float, default=0.0, help="constant Morph when --morph-cv absent")
    ap.add_argument("--cv-range", choices=["auto", "unipolar", "bipolar"], default="auto")
    ap.add_argument("--slam", type=float, default=0.0, help="Mackie desk drive 0..1")
    ap.add_argument("--five-d", type=float, default=0.0, help="QSound width 0..1")
    ap.add_argument("--block", type=int, default=256, help="render block (smaller = finer morph)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if not trench_ffi.engine_available():
        raise SystemExit("trench-core engine FFI unavailable; build: cargo build --release -p trench-core")

    body = load_body(args.body)

    loop, sr_in = read_mono(args.loop)
    n = max(1, int(round(len(loop) * RUNTIME_SR / sr_in)))
    loop_rt = resample(loop, n).astype(np.float32) if sr_in != RUNTIME_SR else loop.astype(np.float32)
    n = len(loop_rt)

    if args.morph_cv:
        m_cv, _ = read_mono(args.morph_cv)
        m_samples = cv_to_param(m_cv, n, args.cv_range)
    else:
        m_samples = np.full(n, float(np.clip(args.morph, 0.0, 1.0)))
    if args.q_cv:
        q_cv, _ = read_mono(args.q_cv)
        q_samples = cv_to_param(q_cv, n, args.cv_range)
    else:
        q_samples = np.full(n, float(np.clip(args.q, 0.0, 1.0)))

    mpb = per_block(m_samples, n, args.block)
    qpb = per_block(q_samples, n, args.block)

    in_bytes = loop_rt.tobytes()
    try:
        out_bytes = trench_ffi.engine_render_slam(body, mpb, qpb, in_bytes,
                                                  slam_drive=float(args.slam), five_d=float(args.five_d),
                                                  sr=RUNTIME_SR, block=args.block)
        chain = f"SLAM {args.slam} + 5D {args.five_d} + AGC"
    except Exception as ex:  # noqa: BLE001 — slam binding optional on older DLLs
        print(f"slam path unavailable ({ex}); AGC-only", file=sys.stderr)
        out_bytes = trench_ffi.engine_render_automated(body, mpb, qpb, in_bytes, sr=RUNTIME_SR, block=args.block)
        chain = "AGC only"
    out_rt = np.frombuffer(out_bytes, dtype=np.float32).astype(np.float64)

    out = resample(out_rt, len(loop)) if sr_in != RUNTIME_SR else out_rt
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0.999:  # transparent peak-safety only; AGC already set the level
        out = out * (0.999 / peak)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(args.out), int(round(sr_in)), out.astype(np.float32))

    print(f"body={args.body.name}  chain={chain}  block={args.block}")
    print(f"morph m(t): {m_samples.min():.3f}..{m_samples.max():.3f}   q(t): {q_samples.min():.3f}..{q_samples.max():.3f}")
    print(f"in {len(loop)} @ {sr_in:g}Hz -> render {n} @ {RUNTIME_SR:g}Hz -> out {len(out)} @ {sr_in:g}Hz  peak {peak:.3f}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
