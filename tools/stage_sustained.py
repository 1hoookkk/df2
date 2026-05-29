#!/usr/bin/env python3
"""stage_sustained.py — synthesize a palette of STRONG sustained, formant-rich
sources and drop them where the Forge scans, so the corner wells get a bigger
body-bearing palette (a `synth_sustained` group).

These are SCAFFOLDING, not heroes: real formant tables + rich harmonic excitation
(saw/square) + 1.6 s sustain + light vibrato, so each fits to a clear formant body
(unlike drums/reverbs). They have body but not the life of real voice — swap in
real sustained recordings when you have them.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import sawtooth, square, lfilter
from scipy.io import wavfile
from pathlib import Path

SR = 44100
DUR = 1.6
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dev/tmp/arma_source_pack/corners_audio_only/synth_sustained"

# (F1,F2,F3[,F4]) Hz — measured-ish adult-male formants
VOWELS = {
    "vowel_iy_beet":  [270, 2290, 3010, 3500],
    "vowel_ih_bit":   [390, 1990, 2550, 3400],
    "vowel_eh_bet":   [530, 1840, 2480, 3400],
    "vowel_ae_bat":   [660, 1720, 2410, 3300],
    "vowel_ah_father":[730, 1090, 2440, 3400],
    "vowel_aw_bought":[570,  840, 2410, 3300],
    "vowel_oh_boat":  [450,  900, 2300, 3300],
    "vowel_oo_boot":  [300,  870, 2240, 3300],
    "vowel_uh_but":   [640, 1190, 2390, 3400],
    "vowel_er_bird":  [490, 1350, 1690, 3300],
}
# instrument-ish: (f0, waveform, [(formant_hz, bw_hz)...])
INSTR = {
    "inst_brass":  (138.0, "saw",  [(520, 80), (1200, 100), (2400, 130), (3100, 160)]),
    "inst_string": (196.0, "saw",  [(300, 60), (460, 70), (600, 80), (2600, 220), (3300, 260)]),
    "inst_reed":   (147.0, "sq",   [(1500, 120), (3000, 200)]),
    "inst_organ":  (110.0, "saw",  [(400, 110), (1500, 160), (2600, 200)]),
    "inst_choir":  (130.0, "saw",  [(730, 90), (1090, 100), (2440, 140), (3400, 180)]),
}


def excite(f0, wave="saw"):
    n = int(DUR * SR)
    t = np.arange(n) / SR
    vib = 1.0 + 0.012 * np.sin(2 * np.pi * 5.2 * t)            # 1.2% vibrato
    phase = 2 * np.pi * np.cumsum(f0 * vib) / SR
    x = square(phase) if wave == "sq" else sawtooth(phase)
    x *= np.clip(1.0 + 0.025 * np.random.randn(n), 0.8, 1.2)  # mild shimmer -> non-degenerate fit
    return x


def formant_body(x, formants, default_bw=80.0):
    """Cascade of resonant biquads = vocal-tract-style all-pole envelope."""
    y = x.astype(np.float64)
    for f in formants:
        fc, bw = (f if isinstance(f, (tuple, list)) else (f, default_bw))
        r = np.exp(-np.pi * bw / SR)
        th = 2 * np.pi * fc / SR
        y = lfilter([1.0 - r], [1.0, -2 * r * np.cos(th), r * r], y)
    return y


def finish(y):
    y = y / (np.max(np.abs(y)) + 1e-12) * 0.9
    fade = int(0.025 * SR)
    env = np.ones(len(y)); env[:fade] = np.linspace(0, 1, fade); env[-fade:] = np.linspace(1, 0, fade)
    return (y * env * 32767).astype(np.int16)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    np.random.seed(1)
    made = 0
    for name, fs in VOWELS.items():
        y = formant_body(excite(120.0, "saw"), [(f, bw) for f, bw in zip(fs, [70, 90, 110, 130])])
        wavfile.write(OUT / f"{name}.wav", SR, finish(y)); made += 1
    for name, (f0, wave, fmts) in INSTR.items():
        y = formant_body(excite(f0, wave), fmts)
        wavfile.write(OUT / f"{name}.wav", SR, finish(y)); made += 1
    print(f"staged {made} sustained sources -> {OUT}")
    for p in sorted(OUT.glob("*.wav")):
        print("  ", p.name)


if __name__ == "__main__":
    main()
