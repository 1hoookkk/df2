"""Render top picks from the Violence sweep — 3 frames each."""
import json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pyruntime import trench_ffi as ff
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db

SWEEP = ROOT / "dev" / "tmp" / "sweep" / "violence_0528"
OUT = ROOT / "dev" / "tmp" / "thumbs"
OUT.mkdir(parents=True, exist_ok=True)
FREQS = np.logspace(math.log10(20), math.log10(16000), 512)
AUTH_SR = 39062.5
TOP_N = 6


def shipped(body, m, q):
    rows = ff.packed_interpolate(body, m, q)
    return cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, AUTH_SR)


def render(morph_name, body, idx, out_path):
    fig, ax = plt.subplots(figsize=(7.8, 2.8), dpi=120)
    series = [
        ("HOME — M0/Q0",         0.0, 0.0, "#6ee7a8"),
        ("TIGHT HOME — M0/Q100", 0.0, 1.0, "#f1d76a"),
        ("CRANKED — M100/Q100",  1.0, 1.0, "#ff9d6d"),
    ]
    for lab, m, q, col in series:
        ax.semilogx(FREQS, shipped(body, m, q), lw=1.9, color=col, label=lab)
    ax.set_xlim(40, 16000)
    ax.set_ylim(-50, 22)
    ax.grid(alpha=0.16)
    ax.set_title(morph_name, fontsize=15, color="#cfe9dc", pad=10)
    ax.text(0.99, 0.94, f"Violence  ·  #{idx}", transform=ax.transAxes,
            ha="right", va="top", fontsize=10, color="#ff6d6d", family="monospace")
    ax.legend(loc="lower center", ncol=3, fontsize=8, frameon=False, labelcolor="#cfe9dc")
    ax.set_facecolor("#0c0f0e")
    fig.patch.set_facecolor("#0c0f0e")
    for s in ax.spines.values():
        s.set_color("#33433c")
    ax.tick_params(colors="#9aa", labelsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def main():
    d = json.loads((SWEEP / "families" / "violence.json").read_text(encoding="utf-8"))
    sl = d.get("shortlist", [])[:TOP_N]
    written = []
    for i, c in enumerate(sl, 1):
        cdir = Path(c["dir"])
        body = (cdir / f"{c['name']}.body240").read_bytes()
        h, a, mi = c.get("home_intent"), c.get("away_intent"), c.get("mid_intent")
        third = c.get("third_state")
        if mi and third:
            morph = f"{h}  →  [{mi}]  →  {a}"
        else:
            morph = f"{h}  →  {a}"
        out = OUT / f"violence_{i}.png"
        render(morph, body, i, out)
        written.append(out.as_posix())
        s = c.get("summary", {})
        adv = ", ".join(c.get("advisory", [])) or "clean"
        ascii_morph = morph.encode("ascii", "replace").decode()
        print(f"  #{i}  {ascii_morph}  motion={s.get('moves_on_morph_hz')}Hz  maxR={s.get('max_pole_radius')}  [{adv}]")
        print(f"      keep: python -m tools.make_class_bodies --keep {cdir.parent.as_posix()} {c['name']} --notes \"\"")
    return written


if __name__ == "__main__":
    main()
