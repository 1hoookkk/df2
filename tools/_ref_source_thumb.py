"""3-frame thumbnails of the SOURCE references (the real P2K bodies) so we can compare
against our inspired-by generations at the same resolution."""
import json, math, struct, sys
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

OUT = ROOT / "dev" / "tmp" / "thumbs"
OUT.mkdir(parents=True, exist_ok=True)

FREQS = np.logspace(math.log10(20), math.log10(16000), 512)
AUTH_SR = 39062.5
LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]


def load_rom(p):
    d = json.loads(Path(p).read_text(encoding="utf-8"))
    kf = {k["label"]: k for k in d["keyframes"]}
    flat = []
    for lab in LABELS:
        for w in kf[lab]["packedWords"]:
            flat.extend(int(x) & 0xFFFF for x in w)
    return struct.pack("<" + "H" * 120, *flat), d["name"]


def shipped(body, m, q):
    rows = ff.packed_interpolate(body, m, q)
    return cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, AUTH_SR)


def render(name, body, out_path):
    fig, ax = plt.subplots(figsize=(7.8, 2.8), dpi=120)
    series = [
        ("HOME — M0/Q0",         0.0, 0.0, "#6ee7a8"),
        ("TIGHT HOME — M0/Q100", 0.0, 1.0, "#f1d76a"),
        ("CRANKED — M100/Q100",  1.0, 1.0, "#ff9d6d"),
    ]
    for lab, m, q, col in series:
        ax.semilogx(FREQS, shipped(body, m, q), lw=1.9, color=col, label=lab)
    ax.set_xlim(40, 16000)
    ax.set_ylim(-50, 18)
    ax.grid(alpha=0.16)
    ax.set_title(f"{name}  (source reference)", fontsize=15, color="#cfe9dc", pad=10)
    ax.text(0.99, 0.94, "reference", transform=ax.transAxes, ha="right", va="top",
            fontsize=10, color="#ff9d6d", family="monospace")
    ax.legend(loc="lower center", ncol=3, fontsize=8, frameon=False, labelcolor="#cfe9dc")
    ax.set_facecolor("#0c0f0e")
    fig.patch.set_facecolor("#0c0f0e")
    for s in ax.spines.values():
        s.set_color("#33433c")
    ax.tick_params(colors="#9aa", labelsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


for src, slug in [(ROOT / "bodies/rom/P2k_003_millennium.json", "src_millennium"),
                  (ROOT / "bodies/rom/P2k_015_dj_alkaline.json", "src_dj_alkaline")]:
    body, name = load_rom(src)
    out = OUT / f"{slug}.png"
    render(name, body, out)
    print(f"  {name}  ->  {out}")
