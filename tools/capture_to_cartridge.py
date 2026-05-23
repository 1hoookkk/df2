#!/usr/bin/env python3
"""capture_to_cartridge.py — THE shipping path.

Takes one dry signal and four wet captures (one per M/Q corner), measures
the empirical transfer function each chain state produced, and joint-fits
a 4-corner df2 cartridge that reproduces those four sonic states with a
smooth morph trajectory between them.

This is the forge backend. The chain you put on a mixer channel — sub
bus with plugins, vocal chain with formant shifter, aluminum sheet
through a convolver — becomes a cartridge whose corners are exact
factorizations of the four chain states you captured. The per-stage
plots will look like Hedz's because the math is the same math that
produced Hedz: real-audio target, joint cascade decomposition.

No by-hand stage authoring. No formant guesses. No vocabulary tweaking.
Just capture → fit → ship.

Inputs:
    --name        body name (used for output filename and cartridge name)
    --dry         dry source signal (.wav, mono or stereo)
    --wet-m0-q0       wet capture at the M0/Q0 chain state
    --wet-m100-q0     wet capture at the M100/Q0 chain state
    --wet-m0-q100     wet capture at the M0/Q100 chain state
    --wet-m100-q100   wet capture at the M100/Q100 chain state

Output:
    bodies/<slug>.cart.json   — compiled-v1 cartridge, drop into the player

Quality gate:
    Each captured wet is post-encode null'd against the rendered cartridge
    corner. Gate is reported per corner. Less than -40 dB = good. Less
    than -60 dB = ROM-class. The number tells you how faithfully the
    cartridge bottled the chain.

Usage:
    python tools/capture_to_cartridge.py \\
        --name "Speaker Knockerz" \\
        --dry captures/dry.wav \\
        --wet-m0-q0 captures/sk_low_soft.wav \\
        --wet-m100-q0 captures/sk_high_soft.wav \\
        --wet-m0-q100 captures/sk_low_sharp.wav \\
        --wet-m100-q100 captures/sk_high_sharp.wav

Notes on capture:
    - All wets MUST be the same dry signal run through different chain
      states. Don't change the source between captures. Don't normalize
      between captures (the gain difference is part of the body).
    - Use 10-30 seconds of broadband material (pink noise is ideal,
      music works, drum loops work). Avoid silence or tonal material.
    - Save as WAV. 24-bit float32 best, 16-bit acceptable.
    - Sample rate must match between dry and all wets.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import csd, welch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.forge_fit import fit_grid, perceptual_weight  # noqa: E402
from pyruntime.forge_joint import joint_fit_corners  # noqa: E402
from tools.coefficient_field_bakeoff import kernel_to_words  # noqa: E402
from tools.rom_corner_audit import clean_null  # noqa: E402
from tools.verified_packed_audit import render  # noqa: E402

CORNER_KEYS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
LETTERS     = ["A",     "B",       "C",       "D"]   # joint_fit_corners letters
KEY_TO_LETTER = dict(zip(CORNER_KEYS, LETTERS))
SR_DEFAULT = 44100.0
PASSTHROUGH = {"c0": 2.0, "c1": 1.0, "c2": 2.0, "c3": 1.0, "c4": 1.0}
NUM_BODY_STAGES = 12  # cartridge schema requires 12 stages per keyframe


def load_mono(path: Path) -> tuple[float, np.ndarray]:
    """Load WAV, convert to mono float64, return (sample_rate, samples)."""
    sr, data = wavfile.read(str(path))
    arr = np.asarray(data)
    if arr.dtype.kind == "i":
        max_v = float(np.iinfo(arr.dtype).max)
        arr = arr.astype(np.float64) / max_v
    else:
        arr = arr.astype(np.float64)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    return float(sr), arr


def empirical_tf(
    dry: np.ndarray, wet: np.ndarray, sr: float,
    nperseg: int = 8192,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Empirical complex transfer function H(f) = S_xy / S_xx, plus coherence.

    Returns (freqs_lin, H_complex, coherence) on a linear freq grid 0..sr/2.
    """
    nperseg = min(nperseg, len(dry), len(wet))
    nperseg = max(nperseg, 256)
    f, S_xx = welch(dry, fs=sr, nperseg=nperseg, return_onesided=True,
                    detrend="constant", scaling="density")
    _, S_yy = welch(wet, fs=sr, nperseg=nperseg, return_onesided=True,
                    detrend="constant", scaling="density")
    _, S_xy = csd(dry, wet, fs=sr, nperseg=nperseg, return_onesided=True,
                  detrend="constant", scaling="density")
    H = S_xy / np.maximum(S_xx, 1e-30)
    coh = np.abs(S_xy) ** 2 / np.maximum(S_xx * S_yy, 1e-30)
    return f, H, coh


def sample_on_log_grid(
    f_lin: np.ndarray, H_lin: np.ndarray, coh_lin: np.ndarray,
    freqs_log: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Resample complex TF and coherence onto a log-spaced freq grid."""
    mag = np.abs(H_lin)
    phase = np.unwrap(np.angle(H_lin))
    # interpolate in linear-freq space; clip queries to measured range
    fq = np.clip(freqs_log, f_lin[0], f_lin[-1])
    mag_i = np.interp(fq, f_lin, mag)
    phase_i = np.interp(fq, f_lin, phase)
    coh_i = np.interp(fq, f_lin, coh_lin)
    H_log = mag_i * np.exp(1j * phase_i)
    return H_log, coh_i


def biquad_from_kernel(c0, c1, c2, c3, c4):
    """Match pyruntime/render.py:45-49 — kernel form → biquad (b0,b1,b2,a1,a2)."""
    a1 = c2 - 2.0
    a2 = 1.0 - c3
    b0 = c4
    b1 = (c0 - 2.0) * c4
    b2 = (1.0 - c1) * c4
    return b0, b1, b2, a1, a2


def kernel_to_stage_dict(kernel_5: list[float]) -> dict:
    return {
        "c0": float(kernel_5[0]),
        "c1": float(kernel_5[1]),
        "c2": float(kernel_5[2]),
        "c3": float(kernel_5[3]),
        "c4": float(kernel_5[4]),
    }


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower()
    return s or "untitled"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--name", required=True, help="body name")
    ap.add_argument("--dry", type=Path, required=True, help="dry source .wav")
    ap.add_argument("--wet-m0-q0",     type=Path, required=True, help="wet at M0/Q0")
    ap.add_argument("--wet-m100-q0",   type=Path, required=True, help="wet at M100/Q0")
    ap.add_argument("--wet-m0-q100",   type=Path, required=True, help="wet at M0/Q100")
    ap.add_argument("--wet-m100-q100", type=Path, required=True, help="wet at M100/Q100")
    ap.add_argument("--out", type=Path, default=None,
                    help="output cart.json path (default: bodies/<slug>.cart.json)")
    ap.add_argument("--boost", type=float, default=1.0)
    ap.add_argument("--restarts", type=int, default=8)
    ap.add_argument("--max-nfev", type=int, default=1500)
    ap.add_argument("--grid", type=int, default=1024)
    ap.add_argument("--profile", default="vocal",
                    help="perceptual weight profile (vocal/flat/etc — see forge_fit)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # ── load files, sanity-check SR consistency ──────────────────────────
    sr_dry, dry = load_mono(args.dry)
    wets = {}
    sr_check = sr_dry
    paths = {
        "M0_Q0":     args.wet_m0_q0,
        "M100_Q0":   args.wet_m100_q0,
        "M0_Q100":   args.wet_m0_q100,
        "M100_Q100": args.wet_m100_q100,
    }
    print(f"loaded dry: {args.dry}  ({len(dry)/sr_dry:.2f}s @ {sr_dry:g} Hz)")
    for key, path in paths.items():
        sr_w, w = load_mono(path)
        if sr_w != sr_check:
            print(f"!! SR mismatch: {path} = {sr_w} Hz, expected {sr_check}", file=sys.stderr)
            return 1
        wets[key] = w
        print(f"loaded wet  ({key:9}): {path}  ({len(w)/sr_w:.2f}s)")
    sr = float(sr_check)

    # ── fit grid & perceptual weight ────────────────────────────────────
    freqs, z_inv = fit_grid(sr, n=args.grid)
    base_weight = perceptual_weight(freqs, args.profile)

    # ── empirical TF per corner + coherence-weighted target weight ──────
    print()
    print("Empirical transfer functions:")
    targets = {}
    weights = {}
    for key, wet in wets.items():
        n = min(len(dry), len(wet))
        f_lin, H_lin, coh_lin = empirical_tf(dry[:n], wet[:n], sr)
        H_log, coh_log = sample_on_log_grid(f_lin, H_lin, coh_lin, freqs)
        # weight = perceptual * sqrt(coherence) — ignore untrustworthy bins
        weight = base_weight * np.sqrt(np.clip(coh_log, 0.0, 1.0))
        targets[KEY_TO_LETTER[key]] = H_log
        weights[KEY_TO_LETTER[key]] = weight
        mean_coh = float(np.mean(coh_log))
        print(f"   {key:9}  mean coherence = {mean_coh:.3f}   "
              f"|H| range = {float(np.min(np.abs(H_log))):.3e} .. {float(np.max(np.abs(H_log))):.3e}")

    # combine per-corner weights into one (use min — toughest gate per freq)
    weight_combined = np.minimum.reduce(list(weights.values()))

    # ── joint fit ────────────────────────────────────────────────────────
    print()
    print(f"Joint fit: 4 corners × 6 slots   "
          f"(restarts={args.restarts}, nfev={args.max_nfev}, grid={args.grid})")
    fit = joint_fit_corners(
        targets=targets, freqs=freqs, z_inv=z_inv, sr=sr,
        bands=None, seeds=None,                       # free-fit; no prior vocabulary
        profile=args.profile, weight=weight_combined,
        n_restarts=args.restarts, seed=1234,
        max_nfev=args.max_nfev, verbose=args.verbose,
    )

    print()
    print("Per-corner fit quality:")
    for key in CORNER_KEYS:
        L = KEY_TO_LETTER[key]
        db = fit.response_null_db[L]
        ok = "ok " if db <= -40 else ("hot" if db <= -20 else "FAIL")
        print(f"   {key:9}  weighted_null = {db:+7.2f} dB   [{ok}]")
    print(f"   best_restart: {fit.best_restart + 1}/{fit.restarts}")

    # ── post-encode verification: render dry through fit kernel, null vs wet ──
    print()
    print("Verification (rendered cartridge corner vs captured wet):")
    verify_rows = []
    for key in CORNER_KEYS:
        L = KEY_TO_LETTER[key]
        kernel = fit.kernel[L]
        rendered = render(dry, kernel, "agc_boost", args.boost).astype(np.float64)
        wet = wets[key].astype(np.float64)
        n = min(len(rendered), len(wet))
        lag, db = clean_null(rendered[:n], wet[:n])
        gate = "PASS" if db <= -40 else ("CLOSE" if db <= -20 else "FAIL")
        verify_rows.append((key, db, lag, gate))
        print(f"   {key:9}  null = {db:+7.2f} dB  (lag {lag})  [{gate}]")

    # ── pack to u16 words, build cartridge JSON ──────────────────────────
    print()
    print("Packing to u16 and writing cartridge...")
    keyframes = []
    for key in CORNER_KEYS:
        L = KEY_TO_LETTER[key]
        kernel = fit.kernel[L]                # shape (6, 5)
        stages = [kernel_to_stage_dict(kernel[i]) for i in range(6)]
        while len(stages) < NUM_BODY_STAGES:
            stages.append(PASSTHROUGH.copy())
        keyframes.append({
            "label": key,
            "boost": args.boost,
            "stages": stages[:NUM_BODY_STAGES],
        })

    payload = {
        "format": "compiled-v1",
        "name": args.name,
        "provenance": "capture_to_cartridge",
        "sampleRate": sr,
        "stages": NUM_BODY_STAGES,
        "keyframes": keyframes,
        "capture": {
            "dry": str(args.dry),
            "wets": {k: str(v) for k, v in paths.items()},
            "fit_restarts": args.restarts,
            "fit_grid_points": args.grid,
            "fit_profile": args.profile,
            "fit_best_restart": fit.best_restart + 1,
            "verification_db": {k: db for k, db, _, _ in verify_rows},
        },
    }

    out_path = args.out
    if out_path is None:
        out_path = ROOT / "bodies" / f"{slugify(args.name)}.cart.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    print()
    print(f"wrote: {out_path}")
    print()
    print(f"Drop this cartridge into tools/player.html via the file picker.")
    print(f"Move the M/Q pad across the surface — the body should sound like")
    print(f"a continuous morph between the four chain states you captured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
