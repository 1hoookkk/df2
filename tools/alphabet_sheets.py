"""The eyeball exam: N real ROM stage sheets + N letter-sampled sheets,
shuffled into one pile. If Tyson can spot the fakes, the alphabet fails.
Output: dev/tmp/alphabet/pile.html + key.json (answer key kept separate)."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from tools.alphabet_exam import sample_lane
from tools.stage_features import FGRID, MUSICAL_33, body_features, load_body

OUT = os.path.join("dev", "tmp", "alphabet")
N_EACH = 18


def _mag(biquad):
    b0, b1, b2, a1, a2 = biquad
    z = np.exp(-1j * 2 * np.pi * FGRID / 39062.5)
    h = (b0 + b1 * z + b2 * z**2) / (1 + a1 * z + a2 * z**2)
    return 20 * np.log10(np.maximum(np.abs(h), 1e-12))


def _plot(mags, path):
    fig, ax = plt.subplots(figsize=(2.6, 1.3))
    for m in mags:
        ax.semilogx(FGRID, m, lw=1.0)
    ax.set_xlim(20, 19500); ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(pad=0.1); fig.savefig(path, dpi=90); plt.close(fig)


def main():
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(2026)
    cells = []
    # real lanes: random (body, stage), all 4 corner curves on one cell
    picks = [(d, s) for d in MUSICAL_33 for s in range(6)]
    idx = rng.choice(len(picks), N_EACH, replace=False)
    for d, s in (picks[int(j)] for j in idx):
        lane = body_features(load_body(d))[s]
        _plot([_mag(c["biquad"]) for c in lane["corners"]], os.path.join(OUT, f"cell_{len(cells):02d}.png"))
        cells.append({"kind": "ROM", "src": f"{os.path.basename(d)}/st{s+1}"})
    # sampled lanes: even spread over letters present in letters.json
    doc = json.load(open(os.path.join("desk", "letters.json"), encoding="utf-8"))
    names = [n for n in doc["letters"] for _ in range(max(1, N_EACH // len(doc["letters"])))][:N_EACH]
    for name in names:
        lane = sample_lane(name, doc["letters"][name], seed=int(rng.integers(1 << 30)))
        _plot([_mag(c["biquad"]) for c in lane["corners"]], os.path.join(OUT, f"cell_{len(cells):02d}.png"))
        cells.append({"kind": "SAMPLED", "src": name})
    order = rng.permutation(len(cells))
    imgs = "".join(f'<div class=c><img src="cell_{i:02d}.png"><br><small>#{n}</small></div>'
                   for n, i in enumerate(order))
    html = ("<!doctype html><meta charset=utf-8><title>alphabet pile</title>"
            "<style>body{background:#0a0c0b;color:#cfe9df;font:13px monospace}"
            ".c{display:inline-block;margin:6px;text-align:center}</style>"
            f"<h3>the pile — which are machine-sampled? ({len(cells)} cells)</h3>{imgs}")
    open(os.path.join(OUT, "pile.html"), "w", encoding="utf-8").write(html)
    key = [{"pos": int(n), "cell": int(i), **cells[i]} for n, i in enumerate(order)]
    json.dump(key, open(os.path.join(OUT, "key.json"), "w", encoding="utf-8"), indent=1)
    print("wrote", os.path.join(OUT, "pile.html"), "and key.json — do NOT open the key before judging")


if __name__ == "__main__":
    main()
