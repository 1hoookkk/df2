"""Single-line M0/Q0 thumbnails for the top picks, named by morph intent — no cand IDs."""
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

SWEEP = ROOT / "dev" / "tmp" / "sweep" / "roster_intent_0528"
OUT = ROOT / "dev" / "tmp" / "thumbs"
OUT.mkdir(parents=True, exist_ok=True)

FREQS = np.logspace(math.log10(20), math.log10(16000), 512)
AUTH_SR = 39062.5


def shipped(body, m, q):
    rows = ff.packed_interpolate(body, m, q)
    return cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, AUTH_SR)


def render(family_name, morph_name, body, out_path):
    fig, ax = plt.subplots(figsize=(7.8, 2.8), dpi=120)
    series = [
        ("HOME — M0/Q0",          0.0, 0.0, "#6ee7a8"),  # relaxed identity
        ("TIGHT HOME — M0/Q100",  0.0, 1.0, "#f1d76a"),  # Q-tightened HOME
        ("CRANKED — M100/Q100",   1.0, 1.0, "#ff9d6d"),  # fully intensified away end
    ]
    for lab, m, q, col in series:
        ax.semilogx(FREQS, shipped(body, m, q), lw=1.9, color=col, label=lab)
    ax.set_xlim(40, 16000)
    ax.set_ylim(-50, 18)
    ax.grid(alpha=0.16)
    ax.set_title(morph_name, fontsize=15, color="#cfe9dc", pad=10)
    ax.text(0.99, 0.94, family_name, transform=ax.transAxes, ha="right", va="top",
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


def main():
    written = []
    for fp in sorted((SWEEP / "families").glob("*.json")):
        d = json.loads(fp.read_text(encoding="utf-8"))
        sl = d.get("shortlist", [])
        if not sl:
            continue
        c = sl[0]
        cdir = Path(c["dir"])
        body = (cdir / f"{c['name']}.body240").read_bytes()
        h = c.get("home_intent", "?")
        a = c.get("away_intent", "?")
        mi = c.get("mid_intent")
        third = c.get("third_state")
        morph_name = f"{h}  →  [{mi}]  →  {a}" if (mi and third) else f"{h}  →  {a}"
        out = OUT / f"{d['campaign']}.png"
        render(d["name"], morph_name, body, out)
        written.append(out.as_posix())
        print(f"  {d['name']:<9}  {morph_name.encode('ascii', 'replace').decode()}  -> {out}")
    return written


if __name__ == "__main__":
    main()
