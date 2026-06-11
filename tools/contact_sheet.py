#!/usr/bin/env python3
"""contact_sheet — one grid of magnitude plots across different generators /
grammars, so the eye can pick which work. Each cell: M0_Q100 (green) and
M100_Q100 (orange) endpoint frames = the morph span, through the engine path.

    python tools/contact_sheet.py            # default cross-method roster
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pyruntime import trench_ffi                       # noqa: E402
from pyruntime.packed_interp import kernel_to_biquad   # noqa: E402

SR = 39062.5
FREQS = np.logspace(math.log10(30.0), math.log10(18000.0), 380)
W = 2.0 * math.pi * FREQS / SR
Z1 = np.exp(-1j * W); Z2 = Z1 * Z1

FAC = ROOT / "dev" / "tmp" / "factory"
GB = ROOT / "dev" / "tmp" / "grammar_bodies"
TMP = ROOT / "dev" / "tmp"

# (label, method tag, path) — spanning generators/grammars
ROSTER = [
    ("P2k_000 collapse", "factory grammar", FAC / "P2k_000.body240"),
    ("P2k_005 remote-cut", "factory grammar", FAC / "P2k_005.body240"),
    ("P2k_014 collapse", "factory grammar", FAC / "P2k_014.body240"),
    ("P2k_019 collapse", "factory grammar", FAC / "P2k_019.body240"),
    ("P2k_024 remote-cut", "factory grammar", FAC / "P2k_024.body240"),
    ("P2k_049 shelf/cliff", "factory grammar", FAC / "P2k_049.body240"),
    ("contrary_vocal", "row_program", GB / "contrary_vocal.body240"),
    ("vocal_cavity_00", "row_program", GB / "vocal_cavity_00.body240"),
    ("vocal_cavity_03", "row_program", GB / "vocal_cavity_03.body240"),
    ("vocal_six_talking", "row_program", GB / "vocal_six_talking.body240"),
    ("vowel_ah_ee", "vowel method", GB / "vowel_ah_ee.body240"),
    ("vowel_ah_ee_collide", "vowel method", GB / "vowel_ah_ee_collide.body240"),
    ("gen vowel (RBJ)", "gen server", TMP / "genvowel.body240"),
    ("gen analog (ellip)", "gen server", TMP / "genanalog.body240"),
    ("grounded millennium", "/ground", TMP / "ground_test.body240"),
]


def endpoint_db(body, m, q):
    rows = trench_ffi.packed_interpolate(body, m, q)
    h = np.ones_like(Z1)
    for r in rows:
        b0, b1, b2, a1, a2 = kernel_to_biquad(r)
        h = h * ((b0 + b1 * Z1 + b2 * Z2) / (1.0 + a1 * Z1 + a2 * Z2))
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-9))


def factory_roster(n=15):
    import json
    mani = json.loads((FAC / "manifest.json").read_text())
    fams = {}
    for m in mani:
        fams.setdefault(m["family"], []).append(m)
    out, i = [], 0
    while len(out) < min(n, len(mani)):                      # round-robin across families for spread
        for fam in sorted(fams):
            if i < len(fams[fam]) and len(out) < n:
                b = fams[fam][i]
                out.append((f"{b['id']} {fam.split()[0]}", fam, FAC / f"{b['id']}.body240"))
        i += 1
        if i > 20:
            break
    return out


def main():
    if "--factory" in sys.argv:
        roster = [(l, m, p) for (l, m, p) in factory_roster(25) if Path(p).exists()]
    else:
        roster = [(l, m, p) for (l, m, p) in ROSTER if Path(p).exists()]
    n = len(roster); cols = 5; rows = math.ceil(n / cols)
    fig, axs = plt.subplots(rows, cols, figsize=(cols * 3.0, rows * 2.1), facecolor="#0d0e11")
    for ax in np.atleast_1d(axs).flat:
        ax.axis("off")
    for ax, (label, method, path) in zip(np.atleast_1d(axs).flat, roster):
        ax.axis("on"); ax.set_facecolor("#15171b")
        body = Path(path).read_bytes()
        steps = 9
        for j in range(steps):                              # the FULL morph sweep at Q=100 (the preset's interior)
            t = j / (steps - 1)
            col = (0.37 + 0.54 * t, 0.68 - 0.11 * t, 0.43 - 0.20 * t)   # green(M0) -> orange(M100)
            ax.semilogx(FREQS, endpoint_db(body, float(t), 1.0), color=col,
                        lw=1.3 if j in (0, steps - 1) else 0.7, alpha=1.0 if j in (0, steps - 1) else 0.7)
        ax.axhline(0, color="#d6564c", lw=0.6, alpha=0.6)
        ax.set_xlim(30, 18000); ax.set_ylim(-40, 30)
        ax.set_xticks([100, 1000, 10000]); ax.set_xticklabels(["100", "1k", "10k"], fontsize=6, color="#878d97")
        ax.tick_params(colors="#878d97", labelsize=6)
        for s in ax.spines.values():
            s.set_color("#24272d")
        ax.set_title(label, color="#c4cad2", fontsize=8, pad=2)
        ax.text(0.02, 0.04, method, transform=ax.transAxes, color="#5a606a", fontsize=6, va="bottom")
    out = TMP / "contact_sheet.png"
    fig.suptitle("df2 — full morph sweep per preset @ Q=100  (green=M0 → orange=M100, the interior is the character)",
                 color="#e8923a", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out, dpi=110, facecolor="#0d0e11")
    print(f"wrote {out}  ({len(roster)} bodies)")


if __name__ == "__main__":
    main()
