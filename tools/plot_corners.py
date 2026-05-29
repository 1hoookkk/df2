#!/usr/bin/env python3
"""plot_corners.py — author a distinct midpoint, derive the 4 corners from it,
and PLOT their magnitude responses so we can SEE whether middle-first corners
look sane or mangled. White = the declared midpoint; dashed grey = the morph's
actual center (average of the 4) — they should overlap if nothing clamped."""
import importlib.util, math
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
def L(n, r):
    s = importlib.util.spec_from_file_location(n, ROOT / r)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
pc  = L("physical_corners", Path(".claude/skills/physical-corners/physical_corners.py"))
w   = L("weapons", Path("tools/weapons.py"))
cfm = L("corners_from_middle", Path("tools/corners_from_middle.py"))
SR  = w.SR


def resp_db(c6, freqs):
    out = []
    for f in freqs:
        ww = 2 * math.pi * f / SR
        m = 1.0
        for s in c6:
            m *= pc._section_mag(s, ww)
        out.append(20 * math.log10(max(m, 1e-9)))
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--middle", default="a", help="vowel for the midpoint")
    ap.add_argument("--morph", default="speaker_knockerz")
    ap.add_argument("--q", default="cul_de_sac")
    ap.add_argument("--spread", type=float, default=0.5)
    a = ap.parse_args()

    mid = pc.vowel_corner(a.middle)
    dm  = w.corner(w.WEAPONS[a.morph][0], w.WEAPONS[a.morph][1], 1.0, 1.0)
    dq  = w.corner(w.WEAPONS[a.q][0], w.WEAPONS[a.q][1], 1.0, 1.0)
    corners = cfm.combine(mid, dm, dq, a.spread)
    cen = cfm.center(corners)

    freqs = np.logspace(math.log10(30), math.log10(18000), 600)
    fig = plt.figure(figsize=(11, 6.2), facecolor="#0c0c10")
    ax = plt.gca(); ax.set_facecolor("#0c0c10")
    labels = ["C00  M0_Q0", "C10  M100_Q0", "C01  M0_Q100", "C11  M100_Q100"]
    cols = ["#ff6a3d", "#ffd23d", "#3dd6ff", "#ff3d8b"]
    for c, lb, col in zip(corners, labels, cols):
        ax.semilogx(freqs, resp_db(c, freqs), color=col, lw=1.5, label=lb, alpha=0.92)
    ax.semilogx(freqs, resp_db(mid, freqs), color="#ffffff", lw=2.8,
                label=f"MIDPOINT  (vowel {a.middle})")
    ax.semilogx(freqs, resp_db(cen, freqs), color="#9aa", lw=1.3, ls="--",
                label="realized center (avg of 4)")

    ax.set_xlim(30, 18000); ax.set_ylim(-42, 30)
    ax.set_xlabel("Hz", color="#aaa"); ax.set_ylabel("dB", color="#aaa")
    ax.set_title(f"4 corners derived from midpoint '{a.middle}'   "
                 f"(Morph->{a.morph}, Q->{a.q}, spread={a.spread})", color="#ddd")
    ax.grid(True, which="both", color="#222", lw=0.5)
    ax.tick_params(colors="#888")
    for sp in ax.spines.values():
        sp.set_color("#333")
    leg = ax.legend(facecolor="#15151a", edgecolor="#333", labelcolor="#ccc", fontsize=9)
    out = ROOT / "corners_from_middle.png"
    fig.tight_layout(); fig.savefig(out, dpi=110, facecolor="#0c0c10")
    print("wrote", out)
    for lb, c in zip(labels, corners):
        print(f"  {lb:<16} {cfm.resonances(c)}")
    print(f"  {'MIDPOINT':<16} {cfm.resonances(mid)}")
    print(f"  {'realized center':<16} {cfm.resonances(cen)}")


if __name__ == "__main__":
    main()
