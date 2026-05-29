"""Single-line M0/Q0 thumbnails for reference_brief outputs (Millennium, DJ Alkaline).
Picks top-N per reference by morph motion + advisory-clean (objective only)."""
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

OUT = ROOT / "dev" / "tmp" / "thumbs"
OUT.mkdir(parents=True, exist_ok=True)

FREQS = np.logspace(math.log10(20), math.log10(16000), 512)
AUTH_SR = 39062.5

RUNS = [
    ("Millennium",  ROOT / "dev" / "tmp" / "reference_brief" / "ref_millennium_s5001"),
    ("DJ Alkaline", ROOT / "dev" / "tmp" / "reference_brief" / "ref_dj_alkaline_s5001"),
]
TOP_N = 3


def shipped(body, m, q):
    rows = ff.packed_interpolate(body, m, q)
    return cascade_response_db([EncodedCoeffs(*r) for r in rows], FREQS, AUTH_SR)


def _pick_top(run_dir, n):
    cands = []
    for cdir in sorted(run_dir.glob("cand_*")):
        rep = cdir / "report.json"
        if not rep.exists():
            continue
        r = json.loads(rep.read_text(encoding="utf-8"))
        if r.get("status") != "original":
            continue
        gate = r.get("gate", {}); s = gate.get("summary", {})
        adv = gate.get("advisory_failed", [])
        cands.append({
            "dir": cdir, "name": cdir.name, "motion": s.get("moves_on_morph_hz", 0),
            "maxR": s.get("max_pole_radius", 1.0), "adv": adv,
        })
    cands.sort(key=lambda c: (len(c["adv"]), -c["motion"], c["maxR"]))
    return cands[:n]


def render(body, ref_name, idx, motion, out_path):
    fig, ax = plt.subplots(figsize=(7.6, 2.6), dpi=120)
    db = shipped(body, 0.0, 0.0)
    ax.semilogx(FREQS, db, lw=2.2, color="#81d4ff")
    ax.set_xlim(40, 16000)
    ax.set_ylim(-50, 18)
    ax.grid(alpha=0.16)
    ax.set_title(f"like {ref_name} · #{idx}", fontsize=15, color="#cfe9dc", pad=10)
    ax.text(0.99, 0.94, f"motion {int(motion)}Hz", transform=ax.transAxes,
            ha="right", va="top", fontsize=10, color="#f1c46a", family="monospace")
    ax.text(0.01, 0.04, "M0 · Q0", transform=ax.transAxes, ha="left", va="bottom",
            fontsize=9, color="#79827b", family="monospace")
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
    for ref_name, run_dir in RUNS:
        if not run_dir.exists():
            print(f"  skip {ref_name}: no run dir at {run_dir}")
            continue
        slug = ref_name.lower().replace(" ", "_")
        picks = _pick_top(run_dir, TOP_N)
        print(f"\n{ref_name}:")
        for i, p in enumerate(picks, 1):
            body = (p["dir"] / f"{p['name']}.body240").read_bytes()
            out = OUT / f"like_{slug}_{i}.png"
            render(body, ref_name, i, p["motion"], out)
            written.append(out.as_posix())
            adv = ", ".join(p["adv"]) or "clean"
            print(f"  #{i}  motion={p['motion']}Hz maxR={p['maxR']:.3f}  [{adv}]  -> {out}")
            print(f"        keep: python -m tools.reference_brief --keep {run_dir.as_posix()} {p['name']} --notes \"\"")
    return written


if __name__ == "__main__":
    main()
