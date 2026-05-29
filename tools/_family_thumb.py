"""Render top picks for one family from a given sweep id — 3 frames each."""
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

FREQS = np.logspace(math.log10(20), math.log10(16000), 512)
AUTH_SR = 39062.5
OUT_DIR = ROOT / "dev" / "tmp" / "thumbs"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def shipped(body, m, q):
    rows = ff.packed_interpolate(body, m, q)
    return cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, AUTH_SR)


def render(morph_name, family, body, idx, out_path):
    fig, ax = plt.subplots(figsize=(7.8, 2.8), dpi=120)
    for lab, m, q, col in [("HOME — M0/Q0", 0.0, 0.0, "#6ee7a8"),
                            ("TIGHT HOME — M0/Q100", 0.0, 1.0, "#f1d76a"),
                            ("CRANKED — M100/Q100", 1.0, 1.0, "#ff9d6d")]:
        ax.semilogx(FREQS, shipped(body, m, q), lw=1.9, color=col, label=lab)
    ax.set_xlim(40, 16000)
    ax.set_ylim(-50, 22)
    ax.grid(alpha=0.16)
    ax.set_title(morph_name, fontsize=15, color="#cfe9dc", pad=10)
    ax.text(0.99, 0.94, f"{family}  ·  #{idx}", transform=ax.transAxes, ha="right", va="top",
            fontsize=10, color="#f1c46a", family="monospace")
    ax.legend(loc="lower center", ncol=3, fontsize=8, frameon=False, labelcolor="#cfe9dc")
    ax.set_facecolor("#0c0f0e")
    fig.patch.set_facecolor("#0c0f0e")
    for s in ax.spines.values():
        s.set_color("#33433c")
    ax.tick_params(colors="#9aa", labelsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def main(sweep_id, family, top_n, out_prefix):
    sweep = ROOT / "dev" / "tmp" / "sweep" / sweep_id
    d = json.loads((sweep / "families" / f"{family}.json").read_text(encoding="utf-8"))
    sl = d.get("shortlist", [])[:top_n]
    written = []
    for i, c in enumerate(sl, 1):
        cdir = Path(c["dir"])
        body = (cdir / f"{c['name']}.body240").read_bytes()
        h, a, mi, third = c.get("home_intent"), c.get("away_intent"), c.get("mid_intent"), c.get("third_state")
        if h and a:
            morph = f"{h}  →  [{mi}]  →  {a}" if (mi and third) else f"{h}  →  {a}"
        else:
            morph = f"wild · #{i:02d}"
        out = OUT_DIR / f"{out_prefix}_{i}.png"
        render(morph, d["name"], body, i, out)
        written.append(out.as_posix())
        s = c.get("summary", {})
        ascii_morph = morph.encode("ascii", "replace").decode()
        print(f"  #{i}  {ascii_morph}  motion={s.get('moves_on_morph_hz')}Hz")
        print(f"      keep: python -m tools.make_class_bodies --keep {cdir.parent.as_posix()} {c['name']} --notes \"\"")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4])
