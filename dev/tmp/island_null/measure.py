"""Mission D: sweep-null the island SRC.

Renders an exponential sine sweep through the installed TRENCH.vst3 with the
NO FILTER body (exact identity cascade) at several host rates, then measures
what the island + SRC (+ AGC, which stays in-chain -- reported as such) does:
passband ripple, HF rolloff, and residual vs dry after gain + delay alignment.
"""

import numpy as np
from pedalboard import load_plugin
from pedalboard.io import AudioFile
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PLUGIN = r"C:\Program Files\Common Files\VST3\TRENCH.vst3\Contents\x86_64-win\TRENCH.vst3"
OUT = r"C:\Users\hooki\df2-workstation\dev\tmp\island_null"
RATES = [44100, 48000, 96000]
F0, F1, DUR, PAD = 20.0, 22000.0, 10.0, 1.0
AMP = 0.25  # comfortably below any clipper knee


def ess(fs):
    t = np.arange(int(DUR * fs)) / fs
    r = np.log(F1 / F0)
    sweep = AMP * np.sin(2 * np.pi * F0 * DUR / r * (np.exp(t * r / DUR) - 1))
    pad = np.zeros(int(PAD * fs))
    return np.concatenate([pad, sweep, pad]).astype(np.float32)


def render(dry, fs):
    p = load_plugin(PLUGIN)
    # defaults already: body=NO FILTER, motion off, slam 0, amount max.
    # pin the ones that matter anyway, by matching parameter names loosely.
    want = {"body": 0.0, "slam": 0.0, "motion": 0.0}
    for name, param in p.parameters.items():
        low = name.lower()
        if low == "body":
            param.raw_value = 0.0
        elif "slam" in low and "drive" in low:
            param.raw_value = 0.0
        elif low == "motion" or low == "motion on":
            param.raw_value = 0.0
        elif low == "amount":
            param.raw_value = 1.0
    stereo = np.stack([dry, dry])
    wet = p.process(stereo, fs)
    return np.asarray(wet[0], dtype=np.float64)


def align(dry, wet, fs):
    """Integer + fractional delay align, gain match. Returns aligned wet, delay, gain."""
    d = dry.astype(np.float64)
    n = len(d)
    xc = np.fft.irfft(np.fft.rfft(wet, 2 * n) * np.conj(np.fft.rfft(d, 2 * n)))
    lag = int(np.argmax(xc[: n]))  # wet is delayed vs dry (causal chain)
    # fractional part + gain from cross-spectrum phase slope in the passband
    w = wet[lag : lag + n] if lag + n <= len(wet) else np.pad(wet[lag:], (0, lag + n - len(wet)))
    D, W = np.fft.rfft(d), np.fft.rfft(w)
    f = np.fft.rfftfreq(n, 1 / fs)
    band = (f > 100) & (f < 10000)
    H = W[band] / D[band]
    frac = -np.polyfit(2 * np.pi * f[band], np.unwrap(np.angle(H)), 1)[0] * fs  # samples
    # apply fractional shift to wet via phase ramp
    W_full = np.fft.rfft(w)
    w = np.fft.irfft(W_full * np.exp(2j * np.pi * np.fft.rfftfreq(n, 1 / fs) * frac / fs), n)
    gain = np.dot(w, d) / np.dot(d, d)
    return w / gain, lag + frac, gain


def response(dry, wet, fs):
    n = len(dry)
    D, W = np.fft.rfft(dry), np.fft.rfft(wet)
    f = np.fft.rfftfreq(n, 1 / fs)
    good = np.abs(D) > np.abs(D).max() * 1e-4  # only where the sweep put energy
    mag = np.full(len(f), np.nan)
    mag[good] = 20 * np.log10(np.abs(W[good] / D[good]))
    return f, mag


def smooth_oct(f, mag, frac=1 / 12):
    out = np.full_like(mag, np.nan)
    valid = ~np.isnan(mag)
    fv, mv = f[valid], mag[valid]
    for i, fc in enumerate(f):
        if np.isnan(mag[i]) or fc < F0:
            continue
        m = (fv >= fc * 2 ** (-frac / 2)) & (fv <= fc * 2 ** (frac / 2))
        if m.any():
            out[i] = mv[m].mean()
    return out


def at(f, mag, hz):
    i = np.nanargmin(np.abs(f - hz))
    return mag[i]


results = {}
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9))
for fs in RATES:
    dry = ess(fs).astype(np.float64)
    wet = render(dry.astype(np.float32), fs)
    w, delay, gain = align(dry, wet, fs)
    f, mag = response(dry, w, fs)
    mags = smooth_oct(f, mag)
    mags -= at(f, mags, 1000)  # normalize to 1 kHz: report shape, absolute gain separately
    resid = w - dry
    sweep_zone = slice(int(PAD * fs), int((PAD + DUR) * fs))
    resid_db = 20 * np.log10(
        np.sqrt(np.mean(resid[sweep_zone] ** 2)) / np.sqrt(np.mean(dry[sweep_zone] ** 2))
    )
    # ESS time<->freq map: t(f) = DUR/ln(F1/F0) * ln(f/F0); passband-only residual
    r_ = np.log(F1 / F0)
    t_lo, t_hi = (DUR / r_ * np.log(hz / F0) for hz in (100.0, 15000.0))
    pz = slice(int((PAD + t_lo) * fs), int((PAD + t_hi) * fs))
    resid_pb_db = 20 * np.log10(
        np.sqrt(np.mean(resid[pz] ** 2)) / np.sqrt(np.mean(dry[pz] ** 2))
    )
    band = (f >= 100) & (f <= 15000) & ~np.isnan(mags)
    ripple = np.nanmax(mags[band]) - np.nanmin(mags[band])
    r = {
        "delay_samples": delay,
        "gain_db": 20 * np.log10(abs(gain)),
        "residual_db": resid_db,
        "residual_passband_db": resid_pb_db,
        "ripple_100_15k_db": ripple,
        "at15k": at(f, mags, 15000),
        "at18k": at(f, mags, 18000),
        "at19k5": at(f, mags, 19500),
    }
    results[fs] = r
    ax1.semilogx(f[1:], mags[1:], label=f"host {fs} Hz")
    ax2.semilogx(f[1:], mags[1:], label=f"host {fs} Hz")
    print(f"host {fs}: delay {delay:.2f} smp ({delay/fs*1000:.2f} ms), "
          f"gain {r['gain_db']:+.2f} dB, residual {resid_db:.1f} dB "
          f"(passband-only {resid_pb_db:.1f} dB), "
          f"ripple(100-15k) {ripple:.3f} dB, "
          f"15k {r['at15k']:+.2f} / 18k {r['at18k']:+.2f} / 19.5k {r['at19k5']:+.2f} dB")

for ax, ylim, title in [(ax1, (-60, 6), "TRENCH island SRC — NO FILTER body (full view)"),
                        (ax2, (-3, 1), "zoom: passband ripple")]:
    ax.set_xlim(20, 48000)
    ax.set_ylim(*ylim)
    ax.grid(True, which="both", alpha=0.3)
    ax.axvline(19531, color="r", ls="--", alpha=0.5, label="island Nyquist 19531 Hz")
    ax.set_title(title)
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB")
    ax.legend()
fig.tight_layout()
fig.savefig(f"{OUT}/island_src_response.png", dpi=110)
print(f"plot -> {OUT}/island_src_response.png")
