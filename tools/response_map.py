"""response_map — embed every body in response space and project the manifold.

No semantics. Each body's signature = its four corners' log-magnitude responses
(shape, not labels). PCA projects them to 2D so distance = response similarity.
This is the manifold's first instance, built from the bodies we already have:
where keeper_04, the vowels, the metals, the search results actually land
relative to each other in response topology.

    python tools/response_map.py
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys; sys.path.insert(0, str(ROOT))
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db

ROSTER = ["keeper_04", "myvoice_aa", "search_01", "search_02", "search_03", "search_04",
          "search_05", "search_06", "hedz_template", "vox_ah_oo_ee", "vowel_morph", "bell",
          "tube", "neon_vane", "gong", "anvil", "razor", "scream", "bloom", "ascension",
          "talkbox", "vowelshift", "siphon", "spectre"]

# colour by rough family — for READABILITY ONLY. Position is response-distance.
FAM = {
    "vocal":  (["myvoice_aa", "vox_ah_oo_ee", "vowel_morph", "talkbox", "vowelshift"], "#2ec4ff"),
    "metal":  (["bell", "anvil", "gong"], "#ffd23e"),
    "tube":   (["tube"], "#8fc8ff"),
    "pad":    (["bloom", "ascension", "neon_vane"], "#9aef5a"),
    "sharp":  (["razor", "scream", "siphon", "spectre"], "#ff6b6b"),
    "search": (["search_01", "search_02", "search_03", "search_04", "search_05", "search_06"], "#9b8cff"),
    "keeper": (["keeper_04"], "#ffffff"),
    "hedz":   (["hedz_template"], "#ffa838"),
}
COLOR = {n: c for _, (names, c) in FAM.items() for n in names}

FREQS = np.logspace(np.log10(80), np.log10(16000), 48)


def signature(name):
    p = ROOT / "bodies" / f"{name}.cart.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    feats = []
    for kf in d["keyframes"]:
        enc = [EncodedCoeffs(s["c0"], s["c1"], s["c2"], s["c3"], s["c4"]) for s in kf["stages"]]
        db = np.clip(cascade_response_db(enc, FREQS), -48, 18)
        feats.append(db)
    return np.concatenate(feats)   # 4 corners x 48 = 192-dim response signature


def main():
    names, M = [], []
    for n in ROSTER:
        s = signature(n)
        if s is not None:
            names.append(n); M.append(s)
    M = np.array(M)
    Mc = M - M.mean(0)
    U, S, Vt = np.linalg.svd(Mc, full_matrices=False)
    xy = Mc @ Vt[:2].T
    var = (S[:2] ** 2 / (S ** 2).sum()) * 100

    plt.rcParams["figure.facecolor"] = "#070a09"
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.set_facecolor("#0b0f0e")
    for i, n in enumerate(names):
        c = COLOR.get(n, "#888")
        big = (n == "keeper_04")
        ax.scatter(xy[i, 0], xy[i, 1], s=180 if big else 90, c=c,
                   edgecolors="#fff" if big else "none", linewidths=1.5, zorder=3, alpha=.9)
        ax.annotate(n, (xy[i, 0], xy[i, 1]), color="#ddd", fontsize=8,
                    xytext=(6, 4), textcoords="offset points")
    ax.set_title(f"Response manifold (PCA of 4-corner log-mag) — distance = response similarity\n"
                 f"PC1 {var[0]:.0f}% · PC2 {var[1]:.0f}% variance · colour = family (readability only)",
                 color="#eaeaea", fontsize=12)
    ax.grid(True, alpha=.12)
    for s_ in ax.spines.values():
        s_.set_color("#333")
    ax.tick_params(colors="#666")
    fig.tight_layout()
    out = ROOT / "dev" / "tmp" / "factory" / "response_manifold.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}  ({len(names)} bodies, PC1/PC2 = {var[0]:.0f}%/{var[1]:.0f}%)")


if __name__ == "__main__":
    main()
