#!/usr/bin/env python3
"""Quantisation-aware gradient fit of ONE corner (6 serial biquads) to a .wav.

The point of using gradient here — and the reason it beats a closed-form LPC/ARMA
solve — is that it optimises THROUGH the u16 packing. A closed-form fit hands you
perfect f64 roots which `encode()` then rounds, moving the response. This fits the
PACKED WORDS directly: quantise in the forward pass, pass gradients around it
(straight-through), so the optimum is one that survives packing.

The minifloat is NOT reimplemented here. Every encode/decode is a ctypes call into
the real trench-core kernel (`trench_packed_encode` / `trench_packed_decode`), so
there is exactly one packed-math kernel in the project, as there must be.

The 30 free parameters are literally the 6 stages x 5 packed words.

  cargo rustc -p trench-core --release --lib --crate-type cdylib
  python tools/fit_corner.py texture.wav --out corner_a.json

A 240-byte body is FOUR corners: run once per corner.
"""

import argparse, ctypes, json, math, sys
from pathlib import Path

import numpy as np
import torch
from scipy.io import wavfile
from scipy.optimize import minimize
from scipy.signal import get_window

STAGE_SR = 39062.5     # trench-core: STAGE_SR = compiler::AUTHORING_SR
N_STAGES = 6

# ---------------------------------------------------------------- the one kernel
_lib = None


def _kernel():
    global _lib
    if _lib is None:
        dll = Path(__file__).resolve().parents[1] / "target" / "release" / "trench_core.dll"
        if not dll.exists():
            sys.exit(f"missing {dll}\n  cargo rustc -p trench-core --release --lib --crate-type cdylib")
        _lib = ctypes.CDLL(str(dll))
        _lib.trench_packed_encode.argtypes = [ctypes.c_double]
        _lib.trench_packed_encode.restype = ctypes.c_uint16
        _lib.trench_packed_decode.argtypes = [ctypes.c_uint16]
        _lib.trench_packed_decode.restype = ctypes.c_double
    return _lib


def pack_words(v):
    """f64 -> u16, via the real kernel."""
    k = _kernel()
    return np.array([k.trench_packed_encode(float(x)) for x in np.ravel(v)],
                    dtype=np.uint16).reshape(np.shape(v))


def round_trip(v):
    """decode(encode(x)) — what the runtime will ACTUALLY hold."""
    k = _kernel()
    return np.array([k.trench_packed_decode(k.trench_packed_encode(float(x)))
                     for x in np.ravel(v)], dtype=np.float64).reshape(np.shape(v))


def quantise_ste(x):
    """Straight-through: forward = the packed value, backward = identity."""
    q = torch.tensor(round_trip(x.detach().numpy()), dtype=torch.float64)
    return x + (q - x).detach()


# ------------------------------------------------------------------- the target
def target_envelope(path, n_fft=4096, n_bins=512, f_lo=20.0):
    sr, x = wavfile.read(path)
    x = x.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x /= (np.abs(x).max() + 1e-12)

    win = get_window("hann", n_fft)
    hop = n_fft // 2
    frames = [x[i:i + n_fft] * win for i in range(0, max(1, len(x) - n_fft), hop)]
    if not frames:
        frames = [np.pad(x, (0, n_fft - len(x)))[:n_fft] * win]
    psd = np.mean([np.abs(np.fft.rfft(f)) ** 2 for f in frames], axis=0)
    fft_hz = np.fft.rfftfreq(n_fft, 1.0 / sr)

    f_hi = min(sr / 2.0, STAGE_SR / 2.0) - 1.0
    grid = np.geomspace(f_lo, f_hi, n_bins)
    db = 10.0 * np.log10(np.interp(grid, fft_hz, psd) + 1e-12)
    k = 21                       # 6 biquads hold an ENVELOPE, never the comb
    db = np.convolve(np.pad(db, (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")
    return grid, db - db.max()


# ------------------------------------------------------- packed words -> response
F_LO = 20.0
F_HI = min(STAGE_SR / 2.0 - 1.0, 20000.0)
R_CEIL = 0.9995        # |pole| < 1. NOT 0.995 — stage_law exercises 0.9999.
SCALE_MAX = 4.0

# L-BFGS-B takes the bounds directly, so the variables ARE the roots: no sigmoid
# squashing (which flattens the gradient at the extremes and hides the high-Q
# corner). log10(Hz) keeps the frequency axis well-conditioned — a linear Hz
# variable makes a 40 Hz pole and a 4 kHz pole differ by 100x in sensitivity.
#   per stage: [log10 pole_hz, pole_r, log10 zero_hz, zero_r, scale]
BOUNDS = [(math.log10(F_LO), math.log10(F_HI)), (0.0, R_CEIL),
          (math.log10(F_LO), math.log10(F_HI)), (0.0, 1.0),
          (0.0, SCALE_MAX)] * N_STAGES


def roots_to_words01(raw):
    """ROOT variables -> the five pre-encode packed quantities.

    Optimising directly in packed space fails: r enters the words as (1 - r^2), so
    r=0.99 lands at 0.0199 and a uniform search crushes the entire resonant region
    into a sliver — measured, it cost 2.3 dB of fit. Root space is the
    well-conditioned geometry; the packing is applied AFTER.

    Mirrors stage_law::words_from_roots exactly (pre-encode).
    """
    pole_hz = torch.pow(10.0, raw[:, 0])
    pole_r = raw[:, 1]
    zero_hz = torch.pow(10.0, raw[:, 2])
    zero_r = raw[:, 3]
    scale = raw[:, 4]

    wz = 2 * math.pi * zero_hz / STAGE_SR
    wp = 2 * math.pi * pole_hz / STAGE_SR
    c0 = 2.0 - 2.0 * zero_r * torch.cos(wz)
    c1 = 1.0 - zero_r ** 2
    c2 = 2.0 - 2.0 * pole_r * torch.cos(wp)
    c3 = 1.0 - pole_r ** 2
    return torch.stack([(c0 - c1) / 4.0, c1, (c2 - c3) / 4.0, c3, scale / 4.0], dim=1)


def response_db(words01, w, quantise=True):
    """words01: (6,5) in [0,1] — the pre-encode packed quantities.

    Decodes exactly as trench-core does (stage_law::geometry_from_words):
        q = 1 - d_rsq ;  c = 4*d_mag + d_rsq ;  p = c - 2
        section = (1 + p_z z^-1 + q_z z^-2) / (1 + p_p z^-1 + q_p z^-2), times SCALE
    """
    v = quantise_ste(words01) if quantise else words01

    zero_mag, zero_rsq, pole_mag, pole_rsq, scale01 = (v[:, i:i + 1] for i in range(5))
    qz = 1.0 - zero_rsq
    pz = (4.0 * zero_mag + zero_rsq) - 2.0
    qp = 1.0 - pole_rsq
    pp = (4.0 * pole_mag + pole_rsq) - 2.0
    k = 4.0 * scale01

    z1 = torch.exp(-1j * w)[None, :]
    z2 = z1 * z1
    num = k * (1.0 + pz * z1 + qz * z2)
    den = 1.0 + pp * z1 + qp * z2
    return 20.0 * torch.log10((num / (den + 1e-12)).abs() + 1e-9).sum(dim=0)


def pole_instability(words01):
    """Jury test on the denominator: stable iff |q| < 1 and |p| < 1 + q.

    q = 1 - d_rsq is in [0,1] by construction, so only the |p| bound can be violated.
    Returned as a hinge so the optimiser is pushed back inside the unit circle.
    """
    pole_mag, pole_rsq = words01[:, 2], words01[:, 3]
    qp = 1.0 - pole_rsq
    pp = (4.0 * pole_mag + pole_rsq) - 2.0
    return torch.relu(pp.abs() - (1.0 + qp) + 1e-3).sum()


# ------------------------------------------------------------------------- fit
def fit(grid, tgt_db, iters, seed):
    """L-BFGS-B on the bounded root variables.

    torch supplies the exact analytic gradient (including the straight-through path
    around the quantiser); scipy supplies the quasi-Newton step and the box. This is
    the right pairing: Adam has to be told a learning rate and then crawls, whereas
    L-BFGS-B builds curvature and converges in far fewer function evaluations.
    """
    w = torch.tensor(2 * math.pi * grid / STAGE_SR, dtype=torch.float64)
    t = torch.tensor(tgt_db, dtype=torch.float64)

    def objective(x):
        raw = torch.tensor(x.reshape(N_STAGES, 5), dtype=torch.float64, requires_grad=True)
        words01 = roots_to_words01(raw)
        h = response_db(words01, w)
        # Level-invariant LSD: SCALE carries loudness, the fit carries shape.
        loss = torch.mean(((h - h.mean()) - (t - t.mean())) ** 2)
        loss.backward()
        return loss.item(), raw.grad.numpy().ravel()

    rng = np.random.default_rng(seed)
    x0 = np.array([[rng.uniform(lo, hi) for lo, hi in BOUNDS[i * 5:(i + 1) * 5]]
                   for i in range(N_STAGES)]).ravel()

    res = minimize(objective, x0, jac=True, method="L-BFGS-B", bounds=BOUNDS,
                   options=dict(maxiter=iters, maxfun=iters * 2, ftol=1e-12, gtol=1e-10))

    with torch.no_grad():
        raw = torch.tensor(res.x.reshape(N_STAGES, 5), dtype=torch.float64)
        words01 = roots_to_words01(raw)
        h = response_db(words01, w)
        lsd = torch.sqrt(torch.mean(((h - h.mean()) - (t - t.mean())) ** 2)).item()
    return words01, lsd, res.nfev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--out", default="corner.json")
    ap.add_argument("--restarts", type=int, default=16)
    ap.add_argument("--iters", type=int, default=500)
    a = ap.parse_args()

    grid, tgt = target_envelope(a.wav)
    w = torch.tensor(2 * math.pi * grid / STAGE_SR, dtype=torch.float64)

    best, best_lsd = None, float("inf")
    for s in range(a.restarts):
        v, lsd, nfev = fit(grid, tgt, a.iters, seed=s)
        print(f"  restart {s}: LSD {lsd:6.2f} dB (packed)   {nfev} evals")
        if lsd < best_lsd:
            best, best_lsd = v, lsd

    # SCALE is unconstrained by a level-invariant loss, so pin the level: normalise the
    # cascade to unity peak, spread across stages, and RE-PACK (SCALE is a real word).
    with torch.no_grad():
        peak = response_db(best, w).max().item()
    k = 4.0 * best[:, 4]
    k = torch.clamp(k * (10.0 ** (-peak / 20.0)) ** (1.0 / N_STAGES), 0.0, 4.0)
    best[:, 4] = k / 4.0

    words = pack_words(best.numpy())          # the actual u16s, from the real kernel

    # HONEST ERROR BUDGET, measured on what the runtime will really hold.
    with torch.no_grad():
        h = response_db(best, w).numpy()
    err = (h - h.mean()) - (tgt - tgt.mean())
    peak_after = h.max()

    print(f"\npacked LSD {best_lsd:.2f} dB   mean|err| {np.abs(err).mean():.2f} dB   "
          f"max|err| {np.abs(err).max():.2f} dB")
    print(f"cascade peak after levelling: {peak_after:+.2f} dB")

    stages = []
    for i in range(N_STAGES):
        stages.append(dict(words=[int(x) for x in words[i]],
                           packed01=[float(x) for x in best[i].numpy()]))
    json.dump(dict(source=a.wav, stage_sr=STAGE_SR, lsd_db=best_lsd,
                   mean_err_db=float(np.abs(err).mean()),
                   max_err_db=float(np.abs(err).max()), stages=stages),
              open(a.out, "w"), indent=2)

    print(f"\n// one corner (30 packed words). -> {a.out}")
    print("static constexpr uint16_t kCorner[6][5] = {")
    for i in range(N_STAGES):
        print("    {{ {:5d}, {:5d}, {:5d}, {:5d}, {:5d} }},".format(*words[i]))
    print("};")


if __name__ == "__main__":
    main()
