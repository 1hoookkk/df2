"""Plot the INDIVIDUAL biquads of a fixed-class fundamental, decoded from code
the way the DLL does it: minifloat-packed u16 -> words_to_coeffs -> kernel biquad
(oracle: df2/ref/ghidra_extracts/morphdesigner_types.md, FUN_1802c3600).

NOT df2t/scale-16384 (the wrong codec decode_and_plot.py guessed), NOT the audio
render. Each stage on its own axis, 4 corners overlaid, poles (peaks) and zeros
(notches) marked, with a pole/zero table printed. Bottom row = the summed filter.
"""
from __future__ import annotations
import struct, sys
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad

BLOCKS = Path(r"C:\Users\hooki\df2\ref\x3_menu\runtime_blocks")
HERE = Path(__file__).resolve().parent
# Oracle (morphdesigner_types.md): the historical Q axis is collapsed. The two
# real axes are MORPH (moves the notch comb) and RES (pole radius / resonance).
CORNERS = ["MORPH0 RES0", "MORPH100 RES0", "MORPH0 RES100", "MORPH100 RES100"]
COLS = {CORNERS[0]: "#2ec4ff", CORNERS[1]: "#ffd23e", CORNERS[2]: "#ff6b6b", CORNERS[3]: "#9b8cff"}
# name -> (stem, family, stages), from decode_and_plot FUND
NS = {"2_pole_lowpass": 1, "4_pole_lowpass": 2, "6_pole_lowpass": 3, "2_pole_highpass": 1,
      "4_pole_highpass": 2, "2_pole_bandpass": 1, "4_pole_bandpass": 2, "contrary_bandpass": 1,
      "swept_eq_1_octave": 1, "swept_eq_2_1_octave": 1, "swept_eq_3_1_octave": 1,
      "phaser_1": 2, "phaser_2": 2, "bat_phaser": 2, "flanger_lite": 3,
      "vocal_ah_ay_ee": 3, "vocal_oo_ah": 3}


def decode(stem, sr):
    """-> corners[4][ns] = (b0,b1,b2,a1,a2), minifloat codec."""
    ns = NS[stem]
    raw = (BLOCKS / f"{stem}_{sr}.raw").read_bytes()
    w = struct.unpack(f"<{len(raw)//2}H", raw)
    per = ns * 5
    return [[kernel_to_biquad(words_to_coeffs(w[c*per+s*5: c*per+s*5+5])) for s in range(ns)]
            for c in range(4)], ns


def mag_db(stages, freqs, sr):
    w = 2 * np.pi * freqs / sr; z = np.exp(-1j * w); t = np.zeros_like(freqs)
    for (b0, b1, b2, a1, a2) in stages:
        t += 20 * np.log10(np.abs(b0 + b1*z + b2*z*z) / np.abs(1 + a1*z + a2*z*z) + 1e-12)
    return t


def hz(z, sr):
    return abs(np.angle(z)) / (2 * np.pi) * sr


def main():
    stem = sys.argv[1] if len(sys.argv) > 1 else "phaser_1"
    sr = int(sys.argv[2]) if len(sys.argv) > 2 else 48000
    corners, ns = decode(stem, sr)
    freqs = np.geomspace(30, sr / 2 * 0.98, 1024)

    fig, axes = plt.subplots(2, max(ns, 1), figsize=(6.5 * max(ns, 1), 9),
                             facecolor="#0b0f0e", squeeze=False)
    print(f"{stem}  ({ns} biquad stage(s), minifloat decode @ {sr} Hz)")
    worst_r = 0.0
    for si in range(ns):
        ax = axes[0][si]; ax.set_facecolor("#0b0f0e")
        for c, lab in enumerate(CORNERS):
            b0, b1, b2, a1, a2 = corners[c][si]
            ax.semilogx(freqs, mag_db([corners[c][si]], freqs, sr), color=COLS[lab], lw=1.3, label=lab)
            poles = np.roots([1, a1, a2]); zeros = np.roots([b0, b1, b2])
            pr = max(abs(p) for p in poles); worst_r = max(worst_r, pr)
            for z in zeros:
                if abs(z) > 0.5:
                    ax.axvline(hz(z, sr), color=COLS[lab], ls=":", lw=0.6, alpha=0.5)
            print(f"  stg{si+1} {lab:10s} pole r={pr:.3f}@{max(hz(p,sr) for p in poles):6.0f}Hz  "
                  f"zero r={max(abs(z) for z in zeros):.3f}@{max(hz(z,sr) for z in zeros):6.0f}Hz"
                  f"  {'UNSTABLE' if pr>=1 else ''}")
        ax.set(xlim=(30, sr/2), ylim=(-45, 35), title=f"biquad stage {si+1} (notch=dotted)")
        ax.grid(True, which="both", alpha=0.15); ax.tick_params(colors="#777", labelsize=7)
        ax.title.set_color("#cfc")
        if si == 0:
            ax.legend(fontsize=8, labelcolor="#ccc", facecolor="#111")
    # bottom-left: the summed filter per corner (the actual response)
    axf = axes[1][0]; axf.set_facecolor("#0b0f0e")
    for c, lab in enumerate(CORNERS):
        axf.semilogx(freqs, mag_db(corners[c], freqs, sr), color=COLS[lab], lw=1.6, label=lab)
    axf.axhline(0, color="#555", lw=0.5)
    axf.set(xlim=(30, sr/2), ylim=(-45, 45),
            title=f"summed filter — 4 corners  (max pole r={worst_r:.3f}, {'STABLE' if worst_r<1 else 'UNSTABLE'})")
    axf.grid(True, which="both", alpha=0.15); axf.tick_params(colors="#777", labelsize=7)
    axf.title.set_color("#cfc" if worst_r < 1 else "#f77"); axf.legend(fontsize=8, labelcolor="#ccc", facecolor="#111")
    for si in range(1, ns):
        axes[1][si].axis("off")

    fig.suptitle(f"{stem} — biquads from code (minifloat/oracle decode, no render)", color="#eaeaea", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = HERE / f"biquads_{stem}.png"
    fig.savefig(out, dpi=110); print("wrote", out, f"| max pole r={worst_r:.3f}")


if __name__ == "__main__":
    main()
