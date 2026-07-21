"""PROOF: does any decode reproduce the actual ROM filter?

Reference = the ROM filter's real rendered output (wet/dry render, the blue).
Overlays, per diagonal corner (A=morph0/res0 start, D=morph100/res100 end):
  - measured blue  (the ROM filter, ground truth)
  - ROM-block decode (df2/ref/x3_menu/runtime_blocks/phaser_1_44100.raw, from code)
  - our authored body240 (the system under test)

If a decode tracks the blue it is faithful; if it doesn't we do NOT call it correct.
"""
from __future__ import annotations
import os, struct, sys
import numpy as np
import soundfile as sf
from scipy.signal import stft, freqz
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tools.cascade_scope import load_corners

SR_ROM = 44100
ROM = rf"C:\Users\hooki\df2\ref\x3_menu\runtime_blocks\phaser_1_{SR_ROM}.raw"
WET = r"C:\Users\hooki\Downloads\phaser morph 0-100 res0to 100.wav"
DRY = r"C:\Users\hooki\OneDrive\Documents\Image-Line\FL Studio\Audio\Rendered\Pattern 3 (consolidated).wav"
BODY = os.path.join(os.path.expanduser("~"), "Documents", "TRENCH", "bodies",
                    "FUNDAMENTALS", "06_PHA", "phaser_1.body240")
STAGE_SR = 39_062.5
ORDER, SCALE, NS = (2, 3, 4, 0, 1), 16384.0, 2
FREQS = np.geomspace(80, SR_ROM / 2 * 0.98, 1024)


def rom_biquads():
    raw = open(ROM, "rb").read()
    w = list(struct.unpack(f"<{len(raw)//2}h", raw)); per = NS * 5
    corners = [[w[c*per + s*5: c*per + s*5 + 5] for s in range(NS)] for c in range(4)]
    out = []
    for c in range(4):
        stages = []
        for s in range(NS):
            v = [x / SCALE for x in corners[c][s]]; o = [v[i] for i in ORDER]
            stages.append(tuple(o))  # b0,b1,b2,a1,a2
        out.append(stages)
    return out


def summed_db(stages, sr):
    w = 2 * np.pi * FREQS / sr
    h = np.ones_like(w, dtype=complex)
    for (b0, b1, b2, a1, a2) in stages:
        _, hi = freqz([b0, b1, b2], [1.0, a1, a2], worN=w)
        h = h * hi
    return 20 * np.log10(np.maximum(np.abs(h), 1e-9))


def measured_blue():
    wet, sr = sf.read(WET, always_2d=True); wet = wet.mean(1)
    dry, _ = sf.read(DRY, always_2d=True); dry = dry.mean(1)
    a = np.abs(wet[:len(dry)]) - np.abs(wet[:len(dry)]).mean()
    b = np.abs(dry) - np.abs(dry).mean()
    lag = np.argmax(np.correlate(a, b, "full")) - (len(dry) - 1)
    dry_t = np.resize(np.roll(dry, max(lag, 0)), len(wet))
    nper = 8192
    f, tw, W = stft(wet, sr, nperseg=nper, noverlap=nper * 3 // 4)
    _, _, D = stft(dry_t, sr, nperseg=nper, noverlap=nper * 3 // 4)
    Wm, Dm = np.abs(W), np.abs(D)
    H = np.where(Dm > Dm.max() * 1e-3, Wm / np.maximum(Dm, 1e-12), np.nan)
    dur = len(wet) / sr
    def band(t0, t1):
        m = (tw >= t0) & (tw <= t1)
        col = np.nanmedian(H[:, m], axis=1)
        return f, 20 * np.log10(np.maximum(col, 1e-6))
    return band(0.2, 1.4), band(dur - 1.4, dur - 0.2)


def norm(y):
    return y - np.nanmedian(y)


def main():
    rom = rom_biquads()
    body = load_corners(BODY)
    (fA, blueA), (fD, blueD) = measured_blue()

    for tag, ci in [("A (M0/Q0 start)", 0), ("D (M100/Q100 end)", 3)]:
        for s in range(NS):
            b0, b1, b2, a1, a2 = rom[ci][s]
            pr = max(abs(z) for z in np.roots([1, a1, a2]))
            zr = np.roots([b0, b1, b2])
            zhz = [abs(np.angle(z)) / (2 * np.pi) * SR_ROM for z in zr]
            print(f"ROM {tag:20s} stage{s+1}: pole r={pr:.3f}  zeros@ {', '.join(f'{h:.0f}' for h in zhz)} Hz"
                  f"  {'UNSTABLE' if pr >= 1 else ''}")

    fig, (axA, axD) = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    for ax, fb, blue, ci, ttl in [(axA, fA, blueA, 0, "A  (morph0 / res0)"),
                                   (axD, fD, blueD, 3, "D  (morph100 / res100)")]:
        ax.semilogx(fb, norm(blue), color="royalblue", lw=2.4, label="ROM filter — measured render (blue)")
        ax.semilogx(FREQS, norm(summed_db(rom[ci], SR_ROM)), color="darkorange", lw=1.6,
                    label="ROM-block decode (from code)")
        ax.semilogx(FREQS, norm(summed_db(body[ci], STAGE_SR)), color="black", lw=1.3, ls="--",
                    label="our authored body240")
        ax.set_title(ttl); ax.grid(True, which="both", alpha=0.25)
        ax.set_xlim(80, SR_ROM / 2); ax.set_xlabel("Hz"); ax.set_ylim(-45, 45); ax.legend(fontsize=8)
    axA.set_ylabel("dB (median-normalised)")
    fig.suptitle("Phaser 1 — proof vs the ROM filter (does any decode track the blue?)", fontsize=13)
    fig.tight_layout()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proof_vs_rom_phaser_1.png")
    fig.savefig(out, dpi=115); print("wrote", out)


if __name__ == "__main__":
    main()
