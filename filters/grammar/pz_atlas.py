"""Pole-zero atlas + per-stage forensics: the 5 fav ROM references vs our current
bodies. Decode packed words -> biquads -> roots per stage per corner; plot the atlas
(freq x radius, LOW->HIGH motion drawn) and print the structural gap table."""
import sys, math
sys.path.insert(0, r"C:\Users\hooki\df2")
sys.path.insert(0, r"C:\Users\hooki\df2\dev\tmp\typed_vowl")
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tools import morph_designer as md
from pyruntime import trench_ffi

ROOT = Path(r"C:\Users\hooki\df2")
SR = md.SR

REFS = {
    "ROM talking_hedz": ROOT / "ref/presets/P2k_013_talking_hedz.bin",
    "ROM fuzzi_face":   ROOT / "ref/presets/P2k_007_fuzzi_face.bin",
    "ROM meaty_gizmo":  ROOT / "ref/presets/P2k_004_meaty_gizmo.bin",
    "ROM lucifers_q":   ROOT / "ref/presets/P2k_029_lucifer_s_q.bin",
    "ROM dj_alkaline":  ROOT / "ref/presets/P2k_015_dj_alkaline.bin",
}
import typed_vowl as tv
OURS = {
    "ours VOWL typed p12": tv.body,
    "ours MD_J01 chores":  (ROOT / "dev/tmp/audition/journeys_md/MD_J01_hollow_chores.body240").read_bytes(),
    "ours MD_J11 scissor": (ROOT / "dev/tmp/audition/journeys_md/MD_J11_scissor_current.body240").read_bytes(),
    "ours MD_J02 whistle": (ROOT / "dev/tmp/audition/journeys_md/MD_J02_paper_whistle.body240").read_bytes(),
}

def stage_roots(row):
    c0, c1, c2, c3, c4 = row
    b = np.array([c4, (c0 - 2.0) * c4, (1.0 - c1) * c4])
    a = np.array([1.0, c2 - 2.0, 1.0 - c3])
    poles = np.roots(a)
    zeros = np.roots(b / b[0]) if abs(b[0]) > 1e-12 else np.array([])
    def conv(rts):
        out = []
        for r in rts:
            if abs(r.imag) < 1e-6:                      # real root
                f = 10.0 if r.real >= 0 else SR / 2 * 0.999
                out.append((f, abs(r), True))
            elif r.imag > 0:
                out.append((abs(np.angle(r)) / (2 * np.pi) * SR, abs(r), False))
        return out
    return conv(poles), conv(zeros), 20 * math.log10(max(abs(c4), 1e-9))

def body_frames(bb):
    """per corner: list of (poles, zeros, gain_db) per stage."""
    return {lbl: [stage_roots(r) for r in trench_ffi.packed_interpolate(bb, m, q)]
            for lbl, (m, q) in [("C0", (0, 0)), ("C1", (1, 0)), ("C2", (0, 1)), ("C3", (1, 1))]}

def stats(frames):
    prad, zrad, pair_oct, travel_oct, gains, nreal = [], [], [], [], [], 0
    qshift = []
    for k in range(6):
        for c in ["C0", "C1", "C2", "C3"]:
            ps, zs, g = frames[c][k]
            gains.append(g)
            for f, r, real in ps:
                prad.append(r); nreal += int(real)
            for f, r, real in zs:
                zrad.append(r); nreal += int(real)
            if ps and zs:
                pair_oct.append(abs(math.log2(max(zs[0][0], 10) / max(ps[0][0], 10))))
        p0, p1 = frames["C0"][k][0], frames["C1"][k][0]
        if p0 and p1:
            travel_oct.append(abs(math.log2(max(p1[0][0], 10) / max(p0[0][0], 10))))
        pq0, pq1 = frames["C0"][k][0], frames["C2"][k][0]
        if pq0 and pq1:
            qshift.append(abs(math.log2(max(pq1[0][0], 10) / max(pq0[0][0], 10))))
    return dict(
        pole_rad=np.median(prad), pole_hi=np.percentile(prad, 90),
        zero_rad=np.median(zrad) if zrad else 0,
        pair=np.median(pair_oct) if pair_oct else 0,
        travel=np.median(travel_oct), travel_max=max(travel_oct) if travel_oct else 0,
        gain_lo=min(gains), gain_hi=max(gains), gain_spread=max(gains) - min(gains),
        real_frac=nreal / (6 * 4 * 4),
        qshift=np.median(qshift) if qshift else 0,
    )

ALL = list(REFS.items()) + list(OURS.items())
fig, axs = plt.subplots(3, 3, figsize=(17, 11), facecolor="#0a0c0b")
CS = plt.cm.tab10(np.linspace(0, 1, 6))
rows_stats = []
for idx, (name, src) in enumerate(ALL):
    bb = src.read_bytes() if isinstance(src, Path) else src
    frames = body_frames(bb)
    rows_stats.append((name, stats(frames)))
    a = axs[idx // 3][idx % 3]; a.set_facecolor("#111318")
    for k in range(6):
        p0, z0, _ = frames["C0"][k]
        p1, z1, _ = frames["C1"][k]
        for (f0, r0, _re0), (f1, r1, _re1) in zip(p0, p1):
            a.plot([f0, f1], [r0, r1], color=CS[k], lw=1.0, alpha=0.7)
            a.plot(f0, r0, "o", color=CS[k], ms=6)
            a.plot(f1, r1, "o", color=CS[k], ms=6, mfc="none")
        for (f0, r0, _re0), (f1, r1, _re1) in zip(z0, z1):
            a.plot([f0, f1], [r0, r1], color=CS[k], lw=1.0, alpha=0.4, ls=":")
            a.plot(f0, r0, "x", color=CS[k], ms=7)
            a.plot(f1, r1, "+", color=CS[k], ms=8)
    a.set_xscale("log"); a.set_xlim(10, 20000); a.set_ylim(0.3, 1.03)
    a.axhline(1.0, color="#ee493c", lw=0.6, alpha=0.6)
    a.grid(True, which="both", alpha=0.12, color="#3a4048")
    a.set_title(name, color="#cfe9df", fontsize=11)
    a.tick_params(colors="#8a968f", labelsize=7)
    if idx % 3 == 0: a.set_ylabel("radius", color="#8a968f", fontsize=8)
fig.suptitle("POLE/ZERO ATLAS — o pole (filled=LOW, open=HIGH) · x/+ zero (LOW/HIGH) · line = morph travel · Q0",
             color="#cfe9df", fontsize=12)
fig.tight_layout(rect=(0, 0, 1, 0.96))
png = ROOT / "dev/tmp/audition/pz_atlas.png"
fig.savefig(png, dpi=110, facecolor="#0a0c0b"); plt.close(fig)
print("wrote", png)

hdr = f"{'body':24s} {'pRad':>6s} {'p90':>6s} {'zRad':>6s} {'pair(oct)':>9s} {'travel':>6s} {'tMax':>6s} {'gainSpread':>10s} {'real%':>6s} {'Qshift':>6s}"
print(hdr)
for name, s in rows_stats:
    print(f"{name:24s} {s['pole_rad']:6.3f} {s['pole_hi']:6.3f} {s['zero_rad']:6.3f} {s['pair']:9.2f} "
          f"{s['travel']:6.2f} {s['travel_max']:6.2f} {s['gain_lo']:+5.1f}..{s['gain_hi']:+5.1f} "
          f"{s['real_frac']*100:5.0f}% {s['qshift']:6.2f}")
