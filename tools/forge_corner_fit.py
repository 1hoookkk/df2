#!/usr/bin/env python3
"""forge_corner_fit.py — author Talking Hedz corners from measured X3 wets.

The Clean Room calibration, done against true behaviour. For each of the 4
Talking Hedz corners:

  1. MEASURE — load the X3 corner wet, exact-lag-align it to the dry, and
     estimate the corner's complex transfer function H(f) = Y(f)/X(f) by
     full-length FFT quotient. This is a pure behavioural measurement: no
     ROM coefficients, no ROM words.
  2. AUTHOR — fit a fresh 6-biquad cascade to H(f) with forge_fit, the
     residual perceptually weighted (Bark mids) and excitation weighted
     (frequencies the dry does not excite are ignored).
  3. VERIFY — render the authored corner through the cascade and null it
     against the X3 corner wet. Gate: <= -60 dB.

This proves the Forge can author a single corner that reproduces measured
E-mu behaviour with its own coefficients. Morph coherence across the 4
corners (so the M/Q interpolation is musical) is the next layer and is NOT
solved here — see the report's closing note.

Offline analysis only. No cartridge asset / format / topology change.

Usage:
    python tools/forge_corner_fit.py [--restarts N]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.forge_fit import (  # noqa: E402
    cascade_response, fit_corner, perceptual_weight,
)
from tools.coefficient_field_bakeoff import kernel_to_words  # noqa: E402
from tools.rom_corner_audit import (  # noqa: E402
    CORNERS, clean_null, words_to_kernel_c4x4,
)
from tools.verified_packed_audit import (  # noqa: E402
    DRY, content_bounds, find_lag, load_mono, refine_lag, render,
)

SR = 44100.0
BOOST = 1.0
OUT_ROOT = ROOT / "dev" / "tmp" / "forge_corner_fit"
ROM_BIN = ROOT / "dev" / "tmp" / "cheat_engine_dump" / "skin13_corners_rom.bin"

DL = Path(r"C:\Users\hooki\Downloads")
# corner letter -> X3 corner wet
CORNER_WETS = {
    "A": DL / "hedz regions - m0q0.wav",   # M0_Q0
    "B": DL / "hedz regions - m1q0.wav",   # M100_Q0
    "C": DL / "hedz regions - m0q1.wav",   # M0_Q100
    "D": DL / "hedz regions - m1q1.wav",   # M100_Q100
}


def _align_segments(dry: np.ndarray, wet: np.ndarray,
                    lag: int, cs: int, ce: int) -> tuple:
    """wet[n] aligns with dry[n - lag]; return equal-length (w, d)."""
    w = wet[cs:ce]
    d = dry[cs - lag:ce - lag]
    n = min(len(w), len(d))
    return w[:n], d[:n]


def _preecho_ratio(dry: np.ndarray, wet: np.ndarray,
                   lag: int, cs: int, ce: int) -> float:
    """Pre-echo energy ratio of the measured impulse response at `lag`.

    With H_emp(f) = Y(f)/X(f), the impulse response onset sits at time
    delta = (true_lag - lag): exact lag -> onset at 0; lag too small ->
    onset delayed (still causal); lag too large -> onset before 0
    (pre-echo, non-causal). This returns max|h[n<0]| / max|h|, which is
    ~0 for lag <= true_lag and rises sharply once lag overshoots it.
    """
    w, d = _align_segments(dry, wet, lag, cs, ce)
    nfft = 1 << len(d).bit_length()
    X = np.fft.rfft(d, nfft)
    Y = np.fft.rfft(w, nfft)
    xm = np.abs(X)
    h = np.fft.irfft(np.where(xm < xm.max() * 1e-3, 0.0, Y / X), nfft)
    ah = np.abs(h)
    pre = float(np.max(ah[nfft - 64:nfft - 1]))
    return pre / (float(np.max(ah)) + 1e-30)


def exact_lag(dry: np.ndarray, wet: np.ndarray, cs: int, ce: int) -> int:
    """Find the exact integer wet/dry lag.

    `find_lag`'s cross-correlation peak is offset by the corner filter's
    group delay, so it is not sample-exact. A 1-sample error rotates the
    measured transfer function by z^k and makes it unfittable as a biquad
    cascade. Two-stage refinement: (1) Wiener-deconvolve to get the
    impulse-response onset (coarse, +-1); (2) the true lag is the LARGEST
    lag whose measured impulse response is still causal (no pre-echo) --
    overshooting it makes H non-causal.
    """
    coarse = find_lag(wet, dry)
    w, d = _align_segments(dry, wet, coarse, cs, ce)
    nfft = 1 << len(d).bit_length()
    X = np.fft.rfft(d, nfft)
    Y = np.fft.rfft(w, nfft)
    reg = float(np.max(np.abs(X) ** 2)) * 1e-6
    h = np.abs(np.fft.irfft(Y * np.conj(X) / (np.abs(X) ** 2 + reg), nfft))
    W = 256
    win_t = np.concatenate([np.arange(-W, 0), np.arange(0, W + 1)])
    hv = h[win_t % nfft]
    pk = int(np.argmax(hv))
    thr = hv[pk] * 0.05
    on = pk
    while on > 0 and hv[on - 1] > thr:
        on -= 1
    onset = coarse + int(win_t[on])

    # stage 2: largest lag whose measured IR is still causal
    cand = list(range(onset - 6, onset + 7))
    ratios = {lag: _preecho_ratio(dry, wet, lag, cs, ce) for lag in cand}
    causal = [lag for lag in cand if ratios[lag] < 0.03]
    return max(causal) if causal else min(cand, key=ratios.get)


def measure_tf(dry: np.ndarray, wet: np.ndarray, lag: int | None = None) -> tuple:
    """Estimate a corner's complex transfer function from a wet/dry pair.

    Exact-lag-aligns the wet to the dry, then estimates H(f) = Y(f)/X(f) by
    full-length FFT (the dry is a deterministic broadband excitation, so a
    direct quotient is the exact transfer function wherever the dry has
    energy). The per-bin excitation magnitude |X| is returned as a
    reliability weight — bins the dry does not excite are not trusted.

    `lag` may be supplied when a caller has already found the exact lag
    (e.g. by render-vs-wet alignment); otherwise it is estimated here.

    Returns (freqs, H_complex, excitation_mag, lag) on the FFT linear grid.
    """
    cs, ce = content_bounds(wet)
    if lag is None:
        lag = exact_lag(dry, wet, cs, ce)
    w, d = _align_segments(dry, wet, lag, cs, ce)

    nfft = 1 << len(d).bit_length()
    X = np.fft.rfft(d, nfft)
    Y = np.fft.rfft(w, nfft)
    f = np.fft.rfftfreq(nfft, 1.0 / SR)
    xmag = np.abs(X)
    floor = float(np.max(xmag)) * 1e-6
    h = Y / np.where(xmag < floor, np.nan, X)
    return f, h, xmag, lag


def prep_grid(f_lin: np.ndarray, h: np.ndarray, excit: np.ndarray,
              decim: int = 32) -> tuple:
    """Select the fit grid from the native FFT bins — no resampling.

    The corners carry Q up to ~600 (resonance bandwidths a few Hz wide); a
    coarse log grid cannot represent them and resampling onto one corrupts
    the fit target. The native FFT grid is ~0.1 Hz; decimating it by `decim`
    still leaves tens of bins across the sharpest resonance, and every kept
    point is a true measured bin. The audio band is selected; out-of-band
    and dry-silent bins are dropped."""
    band = (f_lin >= 20.0) & (f_lin <= SR * 0.499) & np.isfinite(h)
    idx = np.where(band)[0][::decim]
    f = f_lin[idx]
    z_inv = np.exp(-1j * 2.0 * np.pi * f / SR)
    return f, h[idx], excit[idx], z_inv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--restarts", type=int, default=24,
                    help="fit restarts per corner (default 24)")
    args = ap.parse_args()

    for letter, path in CORNER_WETS.items():
        if not path.exists():
            print(f"!! corner wet not found: {path}")
            return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    dry = load_mono(DRY)
    rom_words = None
    if ROM_BIN.exists():
        u16 = np.frombuffer(ROM_BIN.read_bytes(), dtype="<u2")
        rom_words = {CORNERS[i][0]: u16[i * 30:(i + 1) * 30].reshape(6, 5)
                     for i in range(4)}

    print(f"Forge corner fit — Talking Hedz from measured X3 wets  ({ts})")
    print(f"  restarts/corner={args.restarts}\n")
    print("  corner       fit(weighted)  render vs wet   words!=ROM  stable")

    rows = []
    authored_kernels = {}
    for letter, label in CORNERS:
        wet = load_mono(CORNER_WETS[letter])
        cs, ce = content_bounds(wet)
        lag = exact_lag(dry, wet, cs, ce)

        # The TF measurement needs a sample-exact lag. The deconvolution
        # estimate above can still be +-1; refine it by fitting once,
        # rendering the fit, and reading the exact lag back from the
        # render-vs-wet null alignment (the same alignment clean_null
        # uses, which is sample-accurate). Re-measure + refit if it moved.
        fit = None
        for _ in range(3):
            f_lin, h_lin, excit_lin, _ = measure_tf(dry, wet, lag=lag)
            f_fit, h_fit, excit_fit, z_inv = prep_grid(f_lin, h_lin, excit_lin)
            # weight = perceptual (Bark mids) x measurement reliability.
            # reliability saturates: well-excited bins count equally,
            # weakly-excited bins fade out of the fit.
            med = float(np.median(excit_fit)) + 1e-30
            reliability = np.clip(excit_fit / med, 0.0, 1.0)
            weight = perceptual_weight(f_fit, "vocal") * reliability
            weight = weight / max(np.mean(weight), 1e-12)

            fit = fit_corner(h_fit, f_fit, z_inv, SR, n_restarts=args.restarts,
                             seed=4000 + ord(letter), weight=weight)
            auth_render = render(dry, fit.kernel, "agc_boost", BOOST)
            coarse = find_lag(wet, auth_render)
            true_lag, _ = refine_lag(wet, auth_render, cs, ce, coarse)
            if true_lag == lag:
                break
            lag = true_lag

        meas_lag = lag
        authored_kernels[letter] = fit.kernel

        # verify: render authored corner, null vs the X3 corner wet
        vlag, vnull = clean_null(auth_render.astype(np.float64), wet)

        n_diff = "-"
        if rom_words is not None:
            words = kernel_to_words(fit.kernel)
            dw = words.astype(np.int64) - rom_words[letter].astype(np.int64)
            n_diff = f"{int(np.count_nonzero(dw))}/30"

        rows.append({
            "letter": letter, "label": label,
            "fit_db": fit.response_null_db, "render_null": vnull,
            "vlag": vlag, "meas_lag": meas_lag,
            "words_diff": n_diff, "stable": fit.stable,
            "mean_reliability": float(np.mean(reliability)),
        })
        print(f"  {label:11}  {fit.response_null_db:+8.2f} dB  "
              f"{vnull:+8.2f} dB     {str(n_diff):>7}   "
              f"{'yes' if fit.stable else 'NO'}")

    n_pass = sum(1 for r in rows if r["render_null"] <= -60.0)
    print(f"\n  {n_pass}/4 corners pass the -60 dB gate against their wet.")

    # ── report ───────────────────────────────────────────────────────────────
    L = ["# Forge corner fit — Talking Hedz from measured X3 wets", "",
         f"Generated {ts} by `tools/forge_corner_fit.py`", "",
         "Each corner is authored from a pure behavioural measurement of the "
         "X3 corner wet (transfer function H = Y/X, exact-lag-aligned "
         "full-FFT quotient, fitted on the native FFT grid). No ROM "
         "coefficients or words enter the fit targets. The authored 6-biquad "
         "cascade is then rendered and nulled against the same X3 corner "
         "wet.", "",
         f"- fit restarts/corner: {args.restarts}   gate: **-60 dB**", "",
         "## Per-corner result", "",
         "`fit(weighted)` — Bark/excitation-weighted complex response match to "
         "the measured TF. `render vs wet` — authored corner rendered through "
         "the cascade, lag-aligned clean-window null vs the X3 corner wet "
         "(the real gate). `words!=ROM` — authored u16 words differing from "
         "ROM (independence check; ROM words are reference-only).", "",
         "| corner | fit weighted | render vs wet | words != ROM | mean reliab | stable |",
         "|---|---:|---:|---:|---:|:--:|"]
    for r in rows:
        gate = "PASS" if r["render_null"] <= -60.0 else "fail"
        L.append(f"| {r['label']} | {r['fit_db']:+.2f} dB | "
                 f"**{r['render_null']:+.2f} dB** ({gate}) | {r['words_diff']} | "
                 f"{r['mean_reliability']:.3f} | {'yes' if r['stable'] else 'NO'} |")
    L += ["", "## Verdict", ""]
    if n_pass == 4:
        L += ["**PASS — all 4 corners.** The Forge authored 4 original "
              "6-biquad corners from measured X3 behaviour alone; each renders "
              "within the -60 dB gate of its E-mu corner wet. Per-corner "
              "Clean Room authoring is proven on real measurements."]
    else:
        L += [f"**{n_pass}/4 corners pass.** Corners short of -60 dB are "
              "limited either by measurement reliability (see `mean "
              "reliab`) or by non-LTI X3 behaviour the 6-biquad model cannot "
              "capture. Inspect those corners before extending."]
    L += ["", "## Next layer — morph coherence (NOT solved here)", "",
          "These 4 corners are fitted independently, so each lands on a "
          "different valid factorisation of its response. The M/Q "
          "interpolation lerps u16 words stage-by-stage, so independent "
          "factorisations do not morph coherently — stage 0 of corner A is a "
          "different resonator than stage 0 of corner B. Reproducing the X3 "
          "**midpoint** requires a *joint* fit: all 4 corners sharing one "
          "stage decomposition, with the measured M50/Q50 wet "
          "(`hedzm50q50.wav`) as a 5th target. That is the next build.", ""]
    report = out_dir / "CORNER_FIT_REPORT.md"
    report.write_text("\n".join(L) + "\n")
    np.savez(out_dir / "authored_corners.npz",
             **{f"kernel_{k}": v for k, v in authored_kernels.items()})
    print(f"\nwrote: {report}")
    return 0 if n_pass == 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
