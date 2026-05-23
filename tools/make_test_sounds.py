#!/usr/bin/env python3
"""Synthesize clean test material for the Forge: vowels + a metal tube.

These are *resonant* sources (formants / modal peaks) — the kind of thing the
LPC fitter is built for. Drop them in the Forge and the amber filter snaps
onto the green peaks. Output: forge/test_sounds/*.wav (mono, 16-bit, 44.1k).
"""
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import lfilter

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "forge" / "test_sounds"
OUT.mkdir(parents=True, exist_ok=True)


def resonator(x, f, bw):
    r = np.exp(-np.pi * bw / SR)
    th = 2 * np.pi * f / SR
    return lfilter([1 - r], [1.0, -2 * r * np.cos(th), r * r], x)


def write(name, y):
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.7
    wavfile.write(OUT / name, SR, (y * 32767).astype(np.int16))
    print("  wrote", name)


def vowel(name, formants, dur=2.0, f0=120.0):
    n = int(SR * dur)
    src = np.zeros(n)
    src[:: int(SR / f0)] = 1.0  # buzzy glottal pulse train
    y = np.zeros(n)
    for f, bw, g in formants:
        y += g * resonator(src, f, bw)
    write(f"vowel_{name}.wav", y)


def tube(name, modes, dur=2.0):
    n = int(SR * dur)
    noise = np.random.default_rng(7).standard_normal(n) * 0.5
    y = np.zeros(n)
    for f, bw, g in modes:
        y += g * resonator(noise, f, bw)
    write(f"{name}.wav", y)


print("synthesizing test sounds ->", OUT)
# vowels (F1,F2,F3 with bandwidths)
vowel("ah", [(730, 80, 1.0), (1090, 90, 0.6), (2440, 120, 0.3)])
vowel("ee", [(270, 60, 1.0), (2290, 100, 0.7), (3010, 150, 0.3)])
vowel("oo", [(300, 60, 1.0), (870, 80, 0.5), (2240, 120, 0.2)])
vowel("eh", [(530, 70, 1.0), (1840, 100, 0.6), (2480, 130, 0.3)])
# metal tube: narrow inharmonic modal resonances (ringy, metallic)
tube("tube_metal", [(220, 6, 1.0), (540, 8, 0.8), (980, 12, 0.6), (1490, 16, 0.4), (2300, 26, 0.25)])
print("done.")
