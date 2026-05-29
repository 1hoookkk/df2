#!/usr/bin/env python3
"""morph_inspector.py — the prospecting rig. Drop in any 4 corners; see the
EMERGENT middle and the whole morph trajectory, then audition it.

The middle is a mathematical consequence of the corners, so you can't author it —
you assay it. This plots: (top) the 4 corner responses + the emergent middle,
(bottom) a heatmap of |H| across the morph path so you can SEE the trajectory
bloom (resonances sweeping, splitting, holes opening). Writes the slot too.

Corner specs (4 of them = M0_Q0, M100_Q0, M0_Q100, M100_Q100):
  <weapon>        a weapon-palette shape   (speaker_knockerz, cul_de_sac, razor, ...)
  v:<vowel>       a vocal-tract body       (v:a v:i v:u v:ae v:o v:e)
  tube:<cm>       a pipe                   (tube:18)
  bell:<f0> bar:<f0> plate:<f0> membrane:<f0>   modal bodies
  wav:<path>      YOUR sound, fit to a corner via LPC (the Rossum way)

  python tools/morph_inspector.py
  python tools/morph_inspector.py speaker_knockerz razor v:a cul_de_sac
  python tools/morph_inspector.py wav:kick.wav wav:snare.wav wav:vox.wav wav:synth.wav
  python tools/morph_inspector.py wav:my_loop.wav razor v:a cul_de_sac
"""
import argparse, importlib.util, math
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
lpc = L("lpc_extract", Path("tools/lpc_extract.py"))
SR, PASS = w.SR, w.PASS


def resolve(spec):
    """spec -> 6x5 corner."""
    if spec in w.WEAPONS:
        s, pk = w.WEAPONS[spec]
        return w.corner(s, pk, 1.0, 1.0)
    if ":" in spec:
        kind, val = spec.split(":", 1)
        if kind == "v":
            return pc.vowel_corner(val)
        if kind == "tube":
            return pc.build_corner(pc.tube_modes(float(val)))
        if kind in ("bell", "bar", "plate", "membrane"):
            return pc.build_corner(pc.modal_modes(kind, float(val)))
        if kind == "wav":                                  # fit YOUR sound into a corner
            wp = Path(val).expanduser()
            if not wp.exists():
                raise SystemExit(f"wav not found: {wp}")
            rep = lpc.analyse_wav(wp)
            modes = [(p["freq_hz"], p["bandwidth_hz"], 1.0) for p in rep["poles"]]
            return pc.build_corner(modes)
        if kind == "corner":                               # a baked *.corner.json (rom/design/physics)
            import json as _j
            kf = _j.loads(Path(val).read_text())["keyframes"][0]
            return [[s["c0"], s["c1"], s["c2"], s["c3"], s["c4"]] for s in kf["stages"]]
    raise SystemExit(f"unknown corner spec '{spec}'  (weapon, v:a, tube:18, bell:220, wav:my.wav, corner:x.json)")


def blend(C, M, Q):
    w00, w10, w01, w11 = (1 - M) * (1 - Q), M * (1 - Q), (1 - M) * Q, M * Q
    return [[w00 * C[0][s][k] + w10 * C[1][s][k] + w01 * C[2][s][k] + w11 * C[3][s][k]
             for k in range(5)] for s in range(6)]


def path_MQ(path, t):
    return {"diagonal": (t, t), "morph": (t, 0.0), "q": (0.0, t)}[path]


def resp_db(c6, freqs):
    out = []
    for f in freqs:
        ww = 2 * math.pi * f / SR
        m = 1.0
        for s in c6:
            m *= pc._section_mag(s, ww)
        out.append(20 * math.log10(max(m, 1e-9)))
    return np.array(out)


def resonances(c6):
    fr = []
    for s in c6:
        if s == PASS:
            continue
        a1, a2 = s[2] - 2, 1 - s[3]
        r = math.sqrt(max(a2, 0))
        if r > 1e-6 and abs(-a1 / (2 * r)) <= 1:
            fr.append(int(round(math.acos(-a1 / (2 * r)) * SR / (2 * math.pi))))
    return sorted(fr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corners", nargs="*",
                    default=["speaker_knockerz", "razor", "siren", "cul_de_sac"])
    ap.add_argument("--path", choices=["diagonal", "morph", "q"], default="diagonal")
    ap.add_argument("--boost", type=float, default=1.6)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "morph_inspector.png"))
    a = ap.parse_args()
    if len(a.corners) != 4:
        raise SystemExit("need exactly 4 corner specs")

    C = [resolve(s) for s in a.corners]
    mid = blend(C, 0.5, 0.5)

    freqs = np.logspace(math.log10(30), math.log10(18000), 260)
    ts = np.linspace(0, 1, 140)
    grid = np.empty((len(freqs), len(ts)))
    for j, t in enumerate(ts):
        M, Q = path_MQ(a.path, t)
        grid[:, j] = resp_db(blend(C, M, Q), freqs)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.5, 9), facecolor="#0c0c10",
                                   gridspec_kw={"height_ratios": [1, 1.25]})
    labels = ["C00 M0_Q0", "C10 M100_Q0", "C01 M0_Q100", "C11 M100_Q100"]
    cols = ["#ff6a3d", "#ffd23d", "#3dd6ff", "#ff3d8b"]
    for c, lb, col in zip(C, labels, cols):
        ax1.semilogx(freqs, resp_db(c, freqs), color=col, lw=1.2, alpha=0.55, label=lb)
    ax1.semilogx(freqs, resp_db(mid, freqs), color="#fff", lw=2.8, label="EMERGENT MIDDLE")
    ax1.set_facecolor("#0c0c10"); ax1.set_xlim(30, 18000); ax1.set_ylim(-42, 30)
    ax1.set_ylabel("dB", color="#aaa"); ax1.grid(True, which="both", color="#1e1e24", lw=.5)
    ax1.tick_params(colors="#888"); [sp.set_color("#333") for sp in ax1.spines.values()]
    ax1.set_title(f"corners: {'  '.join(a.corners)}", color="#ddd", fontsize=10)
    ax1.legend(facecolor="#15151a", edgecolor="#333", labelcolor="#ccc", fontsize=8, ncol=5, loc="upper center")

    pcm = ax2.pcolormesh(ts, freqs, grid, cmap="magma", vmin=-28, vmax=22, shading="auto")
    ax2.set_yscale("log"); ax2.set_ylim(30, 18000); ax2.set_facecolor("#000")
    ax2.axvline(0.5, color="#fff", lw=1.2, ls="--", alpha=.8)
    ax2.text(0.5, 16500, " middle", color="#fff", fontsize=8, ha="left", va="top")
    ax2.set_xlabel(f"morph along {a.path}  (0 = C00  ->  1 = C11)", color="#aaa")
    ax2.set_ylabel("Hz", color="#aaa"); ax2.tick_params(colors="#888")
    [sp.set_color("#333") for sp in ax2.spines.values()]
    cb = fig.colorbar(pcm, ax=ax2, pad=.01); cb.set_label("dB", color="#aaa")
    cb.ax.tick_params(colors="#888")

    fig.tight_layout(); fig.savefig(a.out, dpi=110, facecolor="#0c0c10")
    print("wrote", a.out)
    for lb, c in zip(labels, C):
        print(f"  {lb:<16} {resonances(c)}")
    print(f"  {'EMERGENT MIDDLE':<16} {resonances(mid)}")

    if not a.no_write:
        slot = pc.write_cartridge(C, "inspect", boost=a.boost)
        print(f"\nwrote -> {slot}  (audition the morph in the VST)")


if __name__ == "__main__":
    main()
