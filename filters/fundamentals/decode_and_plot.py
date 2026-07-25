"""Decode the X3 fixed-class fundamentals and plot all 4 corners for each, so we
can pattern-match them against the ROM character filters.

Decode convention: MINIFLOAT-packed u16, decoded the way the DLL does it
(oracle df2/ref/ghidra_extracts/morphdesigner_types.md, FUN_1802c3600):
  c0 = 4*decode(w0)+decode(w1); c1 = decode(w1); c2 = 4*decode(w2)+decode(w3);
  c3 = decode(w3); c4 = 4*decode(w4)   -> kernel_to_biquad.
This is pyruntime.packed_interp (same codec as body240). The earlier df2t /
scale-16384 / word-order (2,3,4,0,1) guess was the wrong codec — it looked
lowpass-ish but sent phaser/flanger poles outside the unit circle. The corners
are MORPH x RES (the historical Q axis is collapsed, per the oracle).

Evidence boundary: reads df2 study reference (ref/x3_menu, read-only); writes only
derived response plots + a shape manifest here. No ROM bytes or protected names.
"""
from __future__ import annotations
import struct, math, json, sys
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad

BLOCKS = Path(r"C:\Users\hooki\df2\ref\x3_menu\runtime_blocks")
HERE = Path(__file__).resolve().parent
SR = 48000
CORNERS = ["MORPH0 RES0", "MORPH100 RES0", "MORPH0 RES100", "MORPH100 RES100"]
COLS = {CORNERS[0]: "#2ec4ff", CORNERS[1]: "#ffd23e", CORNERS[2]: "#ff6b6b", CORNERS[3]: "#9b8cff"}
FREQS = np.geomspace(30, SR / 2 * 0.98, 512)

# name -> (family, output_stages)  from extract_x3_menu_filters FIXED_CLASSES
FUND = [
    ("2 Pole Lowpass", "2_pole_lowpass", "LPF", 1), ("4 Pole Lowpass", "4_pole_lowpass", "LPF", 2),
    ("6 Pole Lowpass", "6_pole_lowpass", "LPF", 3),
    ("2 Pole Highpass", "2_pole_highpass", "HPF", 1), ("4 Pole Highpass", "4_pole_highpass", "HPF", 2),
    ("2 Pole Bandpass", "2_pole_bandpass", "BPF", 1), ("4 Pole Bandpass", "4_pole_bandpass", "BPF", 2),
    ("Contrary Bandpass", "contrary_bandpass", "BPF", 1),
    ("Swept EQ 1 Oct", "swept_eq_1_octave", "EQ", 1), ("Swept EQ 2>1 Oct", "swept_eq_2_1_octave", "EQ", 1),
    ("Swept EQ 3>1 Oct", "swept_eq_3_1_octave", "EQ", 1),
    ("Phaser 1", "phaser_1", "PHA", 2), ("Phaser 2", "phaser_2", "PHA", 2),
    ("Bat Phaser", "bat_phaser", "PHA", 2), ("Flanger Lite", "flanger_lite", "FLG", 3),
    ("Vocal Ah-Ay-Ee", "vocal_ah_ay_ee", "VOW", 3), ("Vocal Oo-Ah", "vocal_oo_ah", "VOW", 3),
]


def read_corners(stem, ns):
    raw = (BLOCKS / f"{stem}_{SR}.raw").read_bytes()
    w = list(struct.unpack(f"<{len(raw)//2}H", raw)); per = ns * 5   # minifloat u16
    return [[w[c*per + s*5 : c*per + s*5 + 5] for s in range(ns)] for c in range(4)]


def biquad(words5):
    return kernel_to_biquad(words_to_coeffs(tuple(words5)))          # b0,b1,b2,a1,a2


def corner_db(stages):
    w = 2*np.pi*FREQS/SR; z = np.exp(-1j*w); t = np.zeros_like(FREQS); worst = 0.0
    for s in stages:
        b0, b1, b2, a1, a2 = biquad(s)
        worst = max(worst, math.sqrt(abs(a2)) if a2 >= 0 else abs(a2)**0.5)
        t += 20*np.log10(np.abs(b0 + b1*z + b2*z*z)/np.abs(1 + a1*z + a2*z*z) + 1e-12)
    return t, worst


def main():
    manifest = {"decode": {"codec": "minifloat-packed u16 (FUN_1802c3600)", "sr": SR,
                           "axes": "MORPH x RES (historical Q collapsed)",
                           "source": "df2/ref/x3_menu/runtime_blocks (study evidence, read-only)",
                           "oracle": "df2/ref/ghidra_extracts/morphdesigner_types.md",
                           "status": "codec fixed; suspect = unstable pole (r>=1)"},
                "filters": []}
    fig, axes = plt.subplots(3, 6, figsize=(24, 12), facecolor="#0b0f0e")
    for ax, (disp, stem, fam, ns) in zip(axes.flat, FUND):
        corners = read_corners(stem, ns)
        ax.set_facecolor("#0b0f0e"); mx = -99; mr = 0.0
        for c, lab in enumerate(CORNERS):
            d, r = corner_db(corners[c]); mr = max(mr, r)
            ax.semilogx(FREQS, d, color=COLS[lab], lw=1.2)
            mx = max(mx, float(np.max(d)))
        suspect = mr >= 1.0        # the real flaw is an unstable pole, not a loud resonance
        ax.axhline(0, color="#555", lw=0.5)
        ax.set(xlim=(30, 20000), ylim=(-45, 35),
               title=f"{disp}  [{fam}]\nmaxpeak={mx:+.0f}dB maxr={mr:.2f} {'SUSPECT' if suspect else 'ok'}")
        ax.grid(True, which="both", alpha=0.12); ax.tick_params(colors="#777", labelsize=6)
        ax.title.set_color("#f77" if suspect else "#cfc")
        manifest["filters"].append({"name": disp, "stem": stem, "family": fam, "stages": ns,
                                    "max_peak_db": round(mx, 1), "max_pole_r": round(mr, 3),
                                    "reads_true": not suspect})
    for ax in axes.flat[len(FUND):]:
        ax.axis("off")
    fig.suptitle("X3 fixed-class FUNDAMENTALS — 4-corner response (green=reads true, red=decode suspect)",
                 color="#eaeaea", fontsize=15)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(HERE / "fundamentals_contact.png", dpi=95); plt.close(fig)
    (HERE / "fundamentals_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    n_ok = sum(f["reads_true"] for f in manifest["filters"])
    print(f"plotted {len(FUND)} fundamentals -> {HERE/'fundamentals_contact.png'}")
    print(f"reads-true: {n_ok}/{len(FUND)}   suspect: {[f['name'] for f in manifest['filters'] if not f['reads_true']]}")


if __name__ == "__main__":
    main()
