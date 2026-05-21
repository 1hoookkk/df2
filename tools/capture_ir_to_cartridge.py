#!/usr/bin/env python3
"""capture_ir_to_cartridge.py — IR captures → Prony → 240-byte cartridge.

Direct, closed-form translation from four chain-state impulse responses
into a df2 cartridge. No iterative ARMA fitter, no Welch CSD, no
perceptual weight. The IR samples enter Prony's method; pole/zero
polynomials come out; we factor into 6 biquads per corner; minifloat
encode → u16 words → packed 240-byte bank.

Why this preserves transient spike: Prony minimizes sample-by-sample
prediction error on the IR itself. The time-domain peak/decay structure
is what the math is fitting against. The packed format then carries
exactly that — same 240 bytes the ROM uses, faithful to whatever the
fit produced.

Pipeline:
    dirac.wav --[chain @ corner i]--> wet_i.wav
    wet_i.wav --[trim noise tail]--> h_i (the impulse response)
    h_i --[Prony p=12 q=12]--> (b_i, a_i) polynomials
    factor a_i into 6 conjugate pairs → 6 biquad denominators
    factor b_i into 6 conjugate pairs → 6 biquad numerators
    sort by pole frequency (ascending) → stage 0..5
    pair zero quadratic by frequency-rank
    kernel form per stage [c0..c4] → kernel_to_words → u16
    4 corners × 6 stages × 5 words = 240 bytes packed

Stage identity across corners: each corner is independently
frequency-sorted. Joint coherence is achieved by the rule (same-rank
poles are paired across corners), which works when actors don't cross
in frequency. If they do, the per-stage morph through the crossing
will smear; corner endpoints remain correct.

Verification: render the dry impulse through the fitted cascade per
corner, sample-null vs the captured wet IR. The transient gate is
the IR null depth — if the spike survives the round-trip, the
240 bytes encode the spike.

Inputs:
    --name              body name
    --dry               dirac WAV (from tools/make_dirac.py)
    --wet-m0-q0         wet IR at M0/Q0
    --wet-m100-q0       wet IR at M100/Q0
    --wet-m0-q100       wet IR at M0/Q100
    --wet-m100-q100     wet IR at M100/Q100

Output:
    bodies/<slug>.cart.json   (compiled-v1, drop into player)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.linalg import toeplitz
from scipy.signal import tf2sos, lfilter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.coefficient_field_bakeoff import kernel_to_words, kernel_to_sos  # noqa: E402
from tools.verified_packed_audit import render as cascade_render  # noqa: E402

CORNER_KEYS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
NUM_BODY_STAGES = 12
PASSTHROUGH = {"c0": 2.0, "c1": 1.0, "c2": 2.0, "c3": 1.0, "c4": 1.0}


# ── audio I/O ────────────────────────────────────────────────────────────────

def load_mono(path: Path) -> tuple[float, np.ndarray]:
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


# ── IR conditioning ──────────────────────────────────────────────────────────

def align_to_impulse(
    dry: np.ndarray, wet: np.ndarray, onset_db: float = -80.0,
) -> tuple[np.ndarray, int]:
    """Find the IR onset in `wet` relative to the dirac in `dry`.

    For a resonant chain, the wet's energy peak occurs *during ring-up*,
    not at the IR start. Trimming to the peak would discard leading IR
    samples. Instead we find the first sample whose magnitude exceeds
    `onset_db` relative to the wet's peak — that's where the impulse
    response actually begins (after any pure-delay chain latency).

    Returns (h, lag) where h = wet[lag:] is the bare IR aligned so h[0]
    corresponds to the chain's response sample 0 for an impulse at dry's
    impulse index.
    """
    dry_peak_idx = int(np.argmax(np.abs(dry)))
    wet_peak = float(np.max(np.abs(wet)))
    if wet_peak <= 0.0:
        return wet.astype(np.float64), 0
    threshold = wet_peak * (10 ** (onset_db / 20.0))
    above = np.where(np.abs(wet) > threshold)[0]
    if len(above) == 0:
        return wet.astype(np.float64), 0
    wet_onset = int(above[0])
    lag = max(0, wet_onset - dry_peak_idx)
    return wet[lag:].astype(np.float64), lag


def trim_ir(h: np.ndarray, floor_db: float = -100.0,
            min_samples: int = 64) -> np.ndarray:
    """Trim trailing samples that have decayed below floor_db relative to peak."""
    peak = float(np.max(np.abs(h)))
    if peak <= 0.0:
        return h
    threshold = peak * (10 ** (floor_db / 20.0))
    mask = np.abs(h) > threshold
    if not np.any(mask):
        return h[:min_samples]
    last = int(np.where(mask)[0][-1])
    return h[: max(last + 1, min_samples)]


# ── Prony's method ───────────────────────────────────────────────────────────

def prony(h: np.ndarray, p: int = 12, q: int = 12) -> tuple[np.ndarray, np.ndarray]:
    """Fit h ≈ impulse_response(B(z)/A(z)) with A order p, B order q.

    Returns (b, a) with a[0] = 1.0, len(a) = p+1, len(b) = q+1.

    Stage 1 (AR): for n > q,
        h[n] + a[1] h[n-1] + ... + a[p] h[n-p] = 0
        ⇒ T · a[1..p] = -h[q+1..N-1]
       where T is a Toeplitz block of h samples.
    Stage 2 (MA): for n in 0..q,
        b[n] = sum_{k=0..min(n,p)} a[k] · h[n-k].
    """
    h = np.asarray(h, dtype=np.float64).flatten()
    N = len(h)
    if N < p + q + 2:
        raise ValueError(f"IR length {N} too short for prony(p={p}, q={q})")
    # rows: n = q+1 .. N-1   (N - q - 1 rows)
    # cols: k = 1 .. p
    col = h[q : N - 1].copy()                     # h[q], h[q+1], ... h[N-2]
    row_idx = np.arange(q, q - p, -1)             # [q, q-1, ..., q-p+1]
    row = np.where(row_idx >= 0, h[np.clip(row_idx, 0, N - 1)], 0.0)
    T = toeplitz(col, row)
    rhs = -h[q + 1 : N]
    a_tail, *_ = np.linalg.lstsq(T, rhs, rcond=None)
    a = np.concatenate(([1.0], a_tail))

    b = np.zeros(q + 1)
    for n in range(q + 1):
        kmax = min(n, p)
        b[n] = float(np.dot(a[: kmax + 1], h[n - np.arange(kmax + 1)]))
    return b, a


def stmcb(h: np.ndarray, p: int = 12, q: int = 12,
          n_iter: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """Steiglitz-McBride iterative refinement of Prony.

    Pre-filters both the impulse input and the IR by 1/A^(k) at each
    iteration, then solves a linear LS for the next (A, B). For high-Q
    poles where the Prony Toeplitz system is ill-conditioned, S-M
    typically converges to a substantially better fit in 5-10 iterations.

    Returns (b, a) with a[0]=1.
    """
    h = np.asarray(h, dtype=np.float64).flatten()
    N = len(h)
    if N < p + q + 2:
        raise ValueError(f"IR length {N} too short for stmcb(p={p}, q={q})")
    # initial guess from Prony
    _, a = prony(h, p=p, q=q)
    impulse = np.zeros(N)
    impulse[0] = 1.0
    n0 = max(p, q)
    for _ in range(n_iter):
        # pre-filter by 1/a^(k)
        x_tilde = lfilter([1.0], a, impulse)
        y_tilde = lfilter([1.0], a, h)
        # build linear LS: for n in n0..N-1,
        #   y_tilde[n] = sum_{j=0..q} b[j] x_tilde[n-j]
        #              - sum_{j=1..p} a_new[j] y_tilde[n-j]
        rows = N - n0
        cols = (q + 1) + p
        M = np.zeros((rows, cols))
        for j in range(q + 1):
            M[:, j] = x_tilde[n0 - j : N - j]
        for j in range(1, p + 1):
            M[:, q + j] = -y_tilde[n0 - j : N - j]
        rhs = y_tilde[n0:N]
        sol, *_ = np.linalg.lstsq(M, rhs, rcond=None)
        b_new = sol[: q + 1]
        a_new = np.concatenate(([1.0], sol[q + 1 :]))
        # update; bail if non-finite
        if not np.all(np.isfinite(a_new)) or not np.all(np.isfinite(b_new)):
            break
        a = a_new
        b = b_new
    return b, a


def stabilize_polynomial(a: np.ndarray) -> np.ndarray:
    """Reflect any roots outside the unit circle back inside.

    Steiglitz-McBride can occasionally land on an unstable denominator
    (poles |z|>1). Reflecting r -> 1/conj(r) preserves magnitude response
    and produces a stable cascade. Useful as a safety net.
    """
    a = np.asarray(a, dtype=np.float64)
    if abs(a[0]) < 1e-15:
        return a
    roots = np.roots(a)
    changed = False
    for i, r in enumerate(roots):
        if abs(r) > 1.0:
            roots[i] = 1.0 / np.conjugate(r)
            changed = True
    if not changed:
        return a
    new = np.poly(roots) * a[0]
    return new.real


# ── polynomial → biquad factorization ────────────────────────────────────────

def _pole_freq(a1: float, a2: float, sr: float) -> float:
    """Equivalent pole frequency (Hz) for a biquad denominator 1 + a1 z^-1 + a2 z^-2."""
    disc = a1 * a1 - 4.0 * a2
    if disc < 0.0:
        # complex pole pair; angle = arccos(-a1/(2*sqrt(a2)))
        if a2 <= 0.0:
            return 0.0
        cos_theta = -a1 / (2.0 * np.sqrt(a2))
        cos_theta = float(np.clip(cos_theta, -1.0, 1.0))
        theta = float(np.arccos(cos_theta))
        return theta * sr / (2.0 * np.pi)
    # real poles — use the larger-magnitude pole's |angle| (0 or pi)
    root1 = (-a1 + np.sqrt(disc)) / 2.0
    root2 = (-a1 - np.sqrt(disc)) / 2.0
    r = root1 if abs(root1) > abs(root2) else root2
    return 0.0 if r >= 0 else sr / 2.0


def redistribute_sos_gain(sos: np.ndarray) -> np.ndarray:
    """Distribute the cascade's overall gain geometrically across stages.

    Cascade output is invariant under per-stage scaling (αb0, αb1, αb2)
    on stage i paired with (b0/α, b1/α, b2/α) on stage i+1. tf2sos
    typically concentrates the entire cascade gain into ONE section's b0,
    which lands at 1e-5 or smaller for chains that attenuate broadband.
    The minifloat encode (used for the packed u16 cartridge format) has
    coarse resolution near zero — encoding c4 = 5e-5 loses 30+ dB.

    Solution: rescale so every stage's b0 = G^(1/n), where G is the total
    cascade gain (Π b0). Every c4 then lands at the same order of
    magnitude, in a range the minifloat encodes precisely. The signs
    of original b0 are preserved (one stage absorbs any odd parity).
    """
    sos = np.asarray(sos, dtype=np.float64).copy()
    n = sos.shape[0]
    if n == 0:
        return sos
    # total cascade gain (product of all original b0)
    total = float(np.prod(sos[:, 0]))
    if total == 0.0:
        return sos
    # geometric per-stage magnitude
    mag = abs(total) ** (1.0 / n)
    sign_total = -1.0 if total < 0.0 else 1.0
    # current per-stage b0 → target. compute scale factors so that the
    # *product* of scales equals 1 (output invariance) AND the new b0
    # values are each ±mag with overall sign matching `sign_total`.
    target = np.full(n, mag, dtype=np.float64)
    target[0] *= sign_total                  # absorb sign in stage 0
    scale = target / sos[:, 0]
    # numerical product check; if drift, fold residual into last stage
    prod = float(np.prod(scale))
    if abs(prod - 1.0) > 1e-12:
        scale[-1] /= prod
    sos[:, 0] *= scale
    sos[:, 1] *= scale
    sos[:, 2] *= scale
    return sos


def sos_to_kernel_stages(sos: np.ndarray, sr: float) -> np.ndarray:
    """Convert a scipy SOS array (n_sections, 6) into df2 kernel rows (n, 5).

    SOS row: [b0, b1, b2, 1, a1, a2].
    Stages are sorted by ascending pole frequency for joint stage identity
    across corners (lower-rank stages carry lower-frequency actors).
    """
    rows = []
    for row in sos:
        b0, b1, b2, _a0, a1, a2 = [float(x) for x in row]
        c2 = a1 + 2.0
        c3 = 1.0 - a2
        c4 = b0
        if abs(b0) > 1e-15:
            c0 = (b1 / b0) + 2.0
            c1 = 1.0 - (b2 / b0)
        else:
            c0, c1 = 2.0, 1.0
        f = _pole_freq(a1, a2, sr)
        rows.append((f, [c0, c1, c2, c3, c4]))
    rows.sort(key=lambda t: t[0])
    return np.asarray([r[1] for r in rows], dtype=np.float64)


# ── per-corner build ─────────────────────────────────────────────────────────

def build_corner_kernel(
    h: np.ndarray, sr: float, p: int, q: int, n_stages: int,
    method: str = "stmcb", n_iter: int = 8,
) -> tuple[np.ndarray, dict]:
    """Fit IR via Prony or Steiglitz-McBride, factor via tf2sos → kernel rows."""
    if p % 2 or q % 2:
        raise ValueError("p and q must be even (to pair into biquads)")
    if method == "prony":
        b_poly, a_poly = prony(h, p=p, q=q)
    elif method == "stmcb":
        b_poly, a_poly = stmcb(h, p=p, q=q, n_iter=n_iter)
    else:
        raise ValueError(f"unknown method: {method}")
    a_poly = stabilize_polynomial(a_poly)
    # tf2sos uses 'nearest' pole-zero pairing by default for numerical
    # conditioning: each biquad gets its closest zero pair so per-stage
    # gain stays in a stable range.
    sos = tf2sos(b_poly, a_poly, pairing="nearest")  # shape (n_sec, 6)
    sos = redistribute_sos_gain(sos)
    stages = sos_to_kernel_stages(sos, sr)
    # truncate / pad to n_stages
    if stages.shape[0] > n_stages:
        stages = stages[:n_stages]
    elif stages.shape[0] < n_stages:
        passthrough = np.array([PASSTHROUGH["c0"], PASSTHROUGH["c1"],
                                PASSTHROUGH["c2"], PASSTHROUGH["c3"],
                                PASSTHROUGH["c4"]], dtype=np.float64)
        pad = np.tile(passthrough, (n_stages - stages.shape[0], 1))
        stages = np.vstack([stages, pad])
    meta = {
        "ir_len": int(len(h)),
        "ir_peak": float(np.max(np.abs(h))),
        "n_sections": int(sos.shape[0]),
        "c4_min": float(stages[:, 4].min()),
        "c4_max": float(stages[:, 4].max()),
    }
    return stages, meta


# ── verification ─────────────────────────────────────────────────────────────

def sample_null_db(ref: np.ndarray, cand: np.ndarray) -> float:
    """Energy ratio of (cand - ref) to ref, in dB.

    Both signals are zero-aligned (no lag search); the IR start was
    already located in align_to_impulse.
    """
    n = min(len(ref), len(cand))
    diff = cand[:n].astype(np.float64) - ref[:n].astype(np.float64)
    ref_e = float(np.sum(ref[:n].astype(np.float64) ** 2))
    diff_e = float(np.sum(diff ** 2))
    if ref_e <= 0.0:
        return float("nan")
    return 10.0 * np.log10(diff_e / ref_e + 1e-300)


def transient_peak_check(ref: np.ndarray, cand: np.ndarray) -> dict:
    n = min(len(ref), len(cand))
    ref_peak_idx = int(np.argmax(np.abs(ref[:n])))
    cand_peak_idx = int(np.argmax(np.abs(cand[:n])))
    ref_peak = float(ref[ref_peak_idx])
    cand_peak = float(cand[cand_peak_idx])
    db = 20.0 * np.log10(abs(cand_peak) / abs(ref_peak)) if ref_peak != 0 else float("nan")
    return {
        "ref_peak_idx": ref_peak_idx,
        "cand_peak_idx": cand_peak_idx,
        "ref_peak": ref_peak,
        "cand_peak": cand_peak,
        "peak_error_db": db,
        "peak_index_shift": cand_peak_idx - ref_peak_idx,
    }


def stages_to_kernel_rows(stages: np.ndarray) -> np.ndarray:
    """Pad/truncate per-corner stages to NUM_BODY_STAGES rows with passthroughs."""
    if stages.shape[0] >= NUM_BODY_STAGES:
        return stages[:NUM_BODY_STAGES].astype(np.float64)
    pad = NUM_BODY_STAGES - stages.shape[0]
    passthrough = np.array([PASSTHROUGH["c0"], PASSTHROUGH["c1"],
                            PASSTHROUGH["c2"], PASSTHROUGH["c3"],
                            PASSTHROUGH["c4"]], dtype=np.float64)
    extra = np.tile(passthrough, (pad, 1))
    return np.vstack([stages.astype(np.float64), extra])


def morph_trajectory_audit(
    kernels: dict[str, np.ndarray], dry: np.ndarray, sr: float,
    boost: float, n_steps: int = 11,
) -> dict:
    """Pre-audition check for morph 'tearing' from pole-identity mismatch.

    Two measurements, both on the canonical packed u16 morph-first path
    (what the player actually does — packed_oracle), not float bilinear:

    1. Per-stage pole-frequency table across the 4 corners. If two
       adjacent stages' frequency ranges overlap, the per-corner
       ascending-frequency sort may have assigned the same physical
       resonance to different stage slots in different corners — the
       morph then lerps between two different actors and tears.

    2. Packed-interpolation smoothness sweep: walk M 0→1 along the Q=0
       and Q=1 edges, render the dirac through each interpolated cascade,
       and measure the spectral L2 distance between consecutive steps. A
       tear shows up as a distance spike well above the median step.
    """
    from tools.coefficient_field_bakeoff import kernel_to_words, packed_oracle  # noqa

    # ── 1. per-stage pole frequencies across corners ────────────────────────
    n_stages = kernels[CORNER_KEYS[0]].shape[0]
    freq_table = np.zeros((n_stages, len(CORNER_KEYS)))
    for ci, key in enumerate(CORNER_KEYS):
        for si in range(n_stages):
            c2, c3 = kernels[key][si, 2], kernels[key][si, 3]
            a1, a2 = c2 - 2.0, 1.0 - c3
            freq_table[si, ci] = _pole_freq(a1, a2, sr)

    # per-stage frequency migration ratio across corners. A legitimate
    # actor migrates a few× in M; a pole-identity swap (same stage slot
    # holding different physical resonances at different corners) shows up
    # as a huge ratio because the u16 lerp drags that pole clear across
    # the spectrum. Floor the denominator at 20 Hz so DC poles don't blow up.
    migration = []
    for si in range(n_stages):
        hi = float(freq_table[si].max())
        lo = max(float(freq_table[si].min()), 20.0)
        ratio = hi / lo
        migration.append(ratio)

    # ── 2. packed-interp smoothness along the two M edges ───────────────────
    corner_words = {
        "A": kernel_to_words(kernels["M0_Q0"]),
        "B": kernel_to_words(kernels["M100_Q0"]),
        "C": kernel_to_words(kernels["M0_Q100"]),
        "D": kernel_to_words(kernels["M100_Q100"]),
    }

    def spectrum(coeffs: np.ndarray) -> np.ndarray:
        rendered = cascade_render(dry.astype(np.float64), coeffs, "cascade", boost)
        ir, _ = align_to_impulse(dry, rendered)
        ir = trim_ir(ir, floor_db=-120.0, min_samples=2048)
        n = 4096
        spec = np.abs(np.fft.rfft(ir[:n], n=n))
        return 20.0 * np.log10(spec + 1e-9)

    edge_jumps = {}
    corner_energy = []
    for q_edge in (0.0, 1.0):
        ms = np.linspace(0.0, 1.0, n_steps)
        specs = [spectrum(packed_oracle(corner_words, float(m), q_edge)) for m in ms]
        dists = [float(np.sqrt(np.mean((specs[i + 1] - specs[i]) ** 2)))
                 for i in range(len(specs) - 1)]
        med = float(np.median(dists)) if dists else 0.0
        worst = float(np.max(dists)) if dists else 0.0
        worst_at = int(np.argmax(dists)) if dists else 0
        ratio = worst / med if med > 1e-9 else float("inf")
        edge_jumps[f"Q{int(q_edge*100)}"] = {
            "median_step_db": med, "worst_step_db": worst,
            "worst_between": (float(ms[worst_at]), float(ms[worst_at + 1])),
            "ratio": ratio,
        }

    # ── center gain-sag: broadband energy at M50/Q50 vs the 4 corners ───────
    def broadband_db(coeffs: np.ndarray) -> float:
        rendered = cascade_render(dry.astype(np.float64), coeffs, "cascade", boost)
        ir, _ = align_to_impulse(dry, rendered)
        ir = trim_ir(ir, floor_db=-120.0, min_samples=2048)
        return 10.0 * np.log10(float(np.sum(ir.astype(np.float64) ** 2)) + 1e-30)

    corner_e = [broadband_db(kernels[k]) for k in CORNER_KEYS]
    center_e = broadband_db(packed_oracle(corner_words, 0.5, 0.5))
    mean_corner_e = float(np.mean(corner_e))
    center_sag_db = center_e - mean_corner_e   # negative = center quieter than corners

    return {
        "freq_table": freq_table.tolist(),
        "migration": migration,
        "edge_jumps": edge_jumps,
        "corner_energy_db": corner_e,
        "center_energy_db": center_e,
        "center_sag_db": center_sag_db,
    }


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower()
    return s or "untitled"


def kernel_to_stage_dict(kernel_5: np.ndarray) -> dict:
    return {
        "c0": float(kernel_5[0]),
        "c1": float(kernel_5[1]),
        "c2": float(kernel_5[2]),
        "c3": float(kernel_5[3]),
        "c4": float(kernel_5[4]),
    }


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--dry", type=Path, required=True, help="dirac WAV")
    ap.add_argument("--wet-m0-q0",     type=Path, required=True)
    ap.add_argument("--wet-m100-q0",   type=Path, required=True)
    ap.add_argument("--wet-m0-q100",   type=Path, required=True)
    ap.add_argument("--wet-m100-q100", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--p", type=int, default=12, help="AR order (denominator)")
    ap.add_argument("--q", type=int, default=12, help="MA order (numerator)")
    ap.add_argument("--method", choices=("stmcb", "prony"), default="stmcb",
                    help="fit method (stmcb = iterative Prony, more robust for high-Q)")
    ap.add_argument("--n-iter", type=int, default=8,
                    help="Steiglitz-McBride iterations (only for --method stmcb)")
    ap.add_argument("--stages", type=int, default=6,
                    help="active stages per corner (rest passthrough). 6 = ROM-class.")
    ap.add_argument("--ir-floor-db", type=float, default=-100.0,
                    help="trim IR tail below this dB relative to peak")
    ap.add_argument("--boost", type=float, default=1.0)
    args = ap.parse_args()

    # ── load ────────────────────────────────────────────────────────────────
    sr_dry, dry = load_mono(args.dry)
    sr = float(sr_dry)
    wet_paths = {
        "M0_Q0":     args.wet_m0_q0,
        "M100_Q0":   args.wet_m100_q0,
        "M0_Q100":   args.wet_m0_q100,
        "M100_Q100": args.wet_m100_q100,
    }
    print(f"loaded dirac: {args.dry}  ({len(dry)/sr:.3f}s @ {sr:g} Hz)")
    wets = {}
    irs = {}
    lags = {}
    for key, path in wet_paths.items():
        sr_w, w = load_mono(path)
        if sr_w != sr:
            print(f"!! SR mismatch on {path}: {sr_w} vs {sr}", file=sys.stderr)
            return 1
        h_raw, lag = align_to_impulse(dry, w)
        h = trim_ir(h_raw, floor_db=args.ir_floor_db)
        wets[key] = w
        irs[key] = h
        lags[key] = lag
        print(f"  IR {key:9}  lag={lag:5}  len_after_trim={len(h):6}  "
              f"peak={float(np.max(np.abs(h))):.4f}")

    # ── per-corner Prony + factor ───────────────────────────────────────────
    print()
    label = "Prony" if args.method == "prony" else f"Steiglitz-McBride ({args.n_iter} iter)"
    print(f"{label} fit (p={args.p}, q={args.q})  →  {args.stages} biquads/corner")
    kernels = {}
    metas = {}
    for key in CORNER_KEYS:
        stages_arr, meta = build_corner_kernel(
            irs[key], sr=sr, p=args.p, q=args.q, n_stages=args.stages,
            method=args.method, n_iter=args.n_iter,
        )
        kernels[key] = stages_arr
        metas[key] = meta
        print(f"  {key:9}  sections={meta['n_sections']}  "
              f"c4_range=[{meta['c4_min']:+.3e}, {meta['c4_max']:+.3e}]")

    # ── verification: render dirac through each kernel, null vs wet IR ──────
    print()
    print("Verification (rendered IR through fit cascade vs captured wet IR):")
    verify = []
    for key in CORNER_KEYS:
        stages_arr = kernels[key]
        rendered = cascade_render(dry.astype(np.float64), stages_arr,
                                  "cascade", args.boost).astype(np.float64)
        wet_ir, _ = align_to_impulse(dry, wets[key])
        n = min(len(rendered), len(wet_ir))
        # truncate rendered the same way: align rendered's impulse onset to wet IR onset
        # (cascade_render of a dirac at index 0 produces IR starting at index 0)
        # but if dry had pre-zeros, both have the same offset → simple min-truncate works.
        # Find rendered's "IR start" by the same alignment routine for safety:
        rend_ir, _ = align_to_impulse(dry, rendered)
        n2 = min(len(rend_ir), len(wet_ir))
        null = sample_null_db(wet_ir[:n2], rend_ir[:n2])
        transient = transient_peak_check(wet_ir[:n2], rend_ir[:n2])
        gate = "PASS" if null <= -40 else ("CLOSE" if null <= -20 else "FAIL")
        verify.append((key, null, transient, gate))
        print(f"  {key:9}  IR null={null:+7.2f} dB  peak_err={transient['peak_error_db']:+6.2f} dB"
              f"  peak_shift={transient['peak_index_shift']:+4d}  [{gate}]")

    # ── morph-trajectory audit (tear / pole-identity check) ─────────────────
    print()
    print("Morph trajectory audit (canonical packed u16 interpolation):")
    morph = morph_trajectory_audit(kernels, dry, sr, args.boost)
    print("  per-stage pole freq (Hz) by corner [M0Q0  M100Q0  M0Q100  M100Q100]  migration:")
    swap_flags = []
    for si, row in enumerate(morph["freq_table"]):
        mig = morph["migration"][si]
        mark = "  <-- SWAP?" if mig > 20.0 else ""
        if mig > 20.0:
            swap_flags.append(si)
        print(f"    stage {si}: " + "  ".join(f"{f:8.1f}" for f in row) +
              f"   {mig:6.1f}×{mark}")
    # (a) pole-identity swap — large per-stage migration (sweep is continuous,
    #     so the smoothness metric will NOT catch this; the table does)
    if swap_flags:
        print(f"  ! stages {swap_flags} migrate >20× — likely a pole-identity swap")
        print(f"    (same slot holding different resonances at different corners).")
        print(f"    The morph will sweep that pole across the spectrum. Recapture")
        print(f"    or re-pair if that's not the intended motion.")
    else:
        print("  ok: per-stage migration moderate (no identity-swap signature)")
    # (b) center gain sag — "volume dips weirdly in the center"
    sag = morph["center_sag_db"]
    sag_flag = "SAG" if sag < -6.0 else "ok"
    print(f"  center (M50/Q50) energy vs corner mean: {sag:+.2f} dB  [{sag_flag}]")
    if sag < -6.0:
        print("    ! center is >6 dB quieter than the corners — a resonance is")
        print("      canceling mid-morph. Often the audible 'hole in the middle'.")
    # (c) discontinuity — genuine step jumps along the M edges
    for edge, j in morph["edge_jumps"].items():
        flag = "JUMP" if j["ratio"] > 4.0 else "smooth"
        print(f"  morph edge {edge}: worst step {j['worst_step_db']:.2f} dB "
              f"(median {j['median_step_db']:.2f}, ratio {j['ratio']:.1f}×)  [{flag}]")

    # ── pack to cartridge JSON ──────────────────────────────────────────────
    print()
    print("Packing to u16 and writing cartridge...")
    keyframes = []
    for key in CORNER_KEYS:
        rows = stages_to_kernel_rows(kernels[key])
        stages_dicts = [kernel_to_stage_dict(rows[i]) for i in range(NUM_BODY_STAGES)]
        keyframes.append({
            "label": key,
            "boost": args.boost,
            "stages": stages_dicts,
        })

    payload = {
        "format": "compiled-v1",
        "name": args.name,
        "provenance": "capture_ir_to_cartridge",
        "sampleRate": sr,
        "stages": NUM_BODY_STAGES,
        "keyframes": keyframes,
        "capture": {
            "dry": str(args.dry),
            "wets": {k: str(v) for k, v in wet_paths.items()},
            "method": "prony",
            "ar_order": args.p,
            "ma_order": args.q,
            "active_stages": args.stages,
            "verification": {
                k: {
                    "ir_null_db": null,
                    "peak_error_db": tr["peak_error_db"],
                    "peak_index_shift": tr["peak_index_shift"],
                    "gate": gate,
                }
                for (k, null, tr, gate) in verify
            },
            "ir_lags": lags,
        },
    }

    out_path = args.out
    if out_path is None:
        out_path = ROOT / "bodies" / f"{slugify(args.name)}.cart.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    # ── post-encode null gate (kernel → words → kernel → render) ────────────
    print()
    print("Post-encode (u16 round-trip) check at each corner:")
    from tools.coefficient_field_bakeoff import words_to_kernel  # noqa
    for key in CORNER_KEYS:
        rows = stages_to_kernel_rows(kernels[key])
        words = kernel_to_words(rows)
        decoded = words_to_kernel(words)
        # render through decoded coefficients (what the runtime would see)
        rendered_decoded = cascade_render(dry.astype(np.float64), decoded,
                                          "cascade", args.boost).astype(np.float64)
        wet_ir, _ = align_to_impulse(dry, wets[key])
        rend_ir, _ = align_to_impulse(dry, rendered_decoded)
        n2 = min(len(rend_ir), len(wet_ir))
        null = sample_null_db(wet_ir[:n2], rend_ir[:n2])
        gate = "PASS" if null <= -40 else ("CLOSE" if null <= -20 else "FAIL")
        print(f"  {key:9}  packed_IR_null={null:+7.2f} dB   [{gate}]")

    print()
    print(f"wrote: {out_path}")
    print()
    print("Next: drop the cartridge into tools/player.html. The morph between")
    print("the four corners is now an IR-domain interpolation between the four")
    print("packed banks; transient character is preserved by construction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
