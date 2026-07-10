"""Corner remix — recombine the sheet's 48 existing corners into new bodies.
Law A (ladder): 4 corners from different bodies, centroids stepping ~1 oct.
Law B (slide): one strong corner octave-transposed into all 4 poses.
Transplants are byte-exact rows; slides re-encode via the one true kernel.
Gates: stability + copy-risk. Output: corner sheets in the same judging format."""
import sys, math, itertools
sys.path.insert(0, r"C:\Users\hooki\df2")
sys.path.insert(0, r"C:\Users\hooki\df2\dev\tmp\typed_vowl")
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tools import morph_designer as md
import typed_vowl as tv
from src.utils.packed_runtime import evaluate_body
from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db

ROOT = Path(r"C:\Users\hooki\df2")
A = ROOT / "dev/tmp/author_sheet"
U = ROOT / "dev/tmp/audition"
SRB, F = md.SR, tv.FREQS
SHEET = {
    "hero":    tv.body,
    "vowlS":   (A / "VOWL_aa_to_iy.body240").read_bytes(),
    "phon":    (A / "PHON_SPLITTER.body240").read_bytes(),
    "razor":   (A / "FUZZ_B_RAZOR.body240").read_bytes(),
    "chores":  (U / "journeys_md/MD_J01_hollow_chores.body240").read_bytes(),
    "scissor": (U / "journeys_md/MD_J11_scissor_current.body240").read_bytes(),
    "piston":  (U / "journeys_md/MD_J16_piston_knuckle.body240").read_bytes(),
    "whistle": (U / "journeys_md/MD_J02_paper_whistle.body240").read_bytes(),
    "sciv2":   (U / "scissor_v2/SCISSOR_V2.body240").read_bytes(),
    "meat":    (U / "cleanroom_favs/cr1_meat_machine.body240").read_bytes(),
    "fuzz":    (U / "cleanroom_favs/cr2_fuzz_band.body240").read_bytes(),
    "headtr":  (U / "headtrip/HEADTRIP_C4.body240").read_bytes(),
}

def corners_of(bb):
    """4 corners x 6 rows x 5 u16, byte-exact."""
    w = np.frombuffer(bb, dtype="<u2").reshape(4, 6, 5)
    return [[tuple(int(x) for x in row) for row in corner] for corner in w]

def body_from_corners(c0, c1, c2, c3):
    return md.raw_from_words({"M0_Q0": c0, "M100_Q0": c1, "M0_Q100": c2, "M100_Q100": c3})

def prod(bb, m, q):
    rows = trench_ffi.packed_interpolate(bb, float(m), float(q))
    return cascade_response_db([EncodedCoeffs(*r) for r in rows], F, SRB)

# per-corner metrics from the assembled single-corner probe
LIB = []   # (key, ci, rows, centroid_log2, span)
for key, bb in SHEET.items():
    cs = corners_of(bb)
    for ci in range(4):
        solo = body_from_corners(cs[ci], cs[ci], cs[ci], cs[ci])
        db = prod(solo, 0.0, 0.0)
        w = 10.0 ** (db / 10.0)
        cen = float(np.sum(w * np.log2(F)) / np.sum(w))
        LIB.append((key, ci, cs[ci], cen, float(db.max() - db.min())))
LIB.sort(key=lambda e: e[3])
print("corner library:", len(LIB), "corners; centroid range "
      f"{2**LIB[0][3]:.0f}–{2**LIB[-1][3]:.0f} Hz")

# ---- Law A: octave ladders (different source bodies, ~1 oct steps) ----------
def pick_ladder(start_idx, step_oct=1.0):
    chosen = [LIB[start_idx]]
    for _ in range(3):
        last = chosen[-1]
        cands = [e for e in LIB
                 if e[0] not in {c[0] for c in chosen}
                 and 0.6 <= (e[3] - last[3]) <= 1.6]
        if not cands:
            return None
        cands.sort(key=lambda e: abs((e[3] - last[3]) - step_oct))
        chosen.append(cands[0])
    return chosen

REMIX = []
for si in range(0, len(LIB) - 6, 7):
    lad = pick_ladder(si)
    if lad:
        name = "LAD_" + "_".join(f"{k}{ci}" for k, ci, *_ in lad)
        # wheel walks the ladder at Q0 (steps 1,2), Q wheel jumps the register (3,4)
        REMIX.append((f"L{len(REMIX)+1} " + "+".join(k for k, *_ in lad),
                      body_from_corners(lad[0][2], lad[1][2], lad[2][2], lad[3][2])))
    if len(REMIX) >= 5:
        break

# ---- Law B: octave slides (one corner, transposed poses) --------------------
def stage_pair(row):
    """decoded (pole f,r) (zero f,r) gain from one packed row (conjugate-pair form)."""
    c0, c1, c2, c3, c4 = row
    b = np.array([c4, (c0 - 2.0) * c4, (1.0 - c1) * c4])
    a = np.array([1.0, c2 - 2.0, 1.0 - c3])
    pr = np.roots(a); zr = np.roots(b / b[0]) if abs(b[0]) > 1e-12 else np.array([1e-3])
    def top(rts):
        cx = [r for r in rts if r.imag > 1e-6]
        if cx:
            r = cx[0]
            return abs(np.angle(r)) / (2 * np.pi) * SRB, abs(r)
        return 10.0, abs(rts[0])
    (pf, prad), (zf, zrad) = top(pr), top(zr)
    return pf, prad, zf, zrad, float(c4)

def transpose_corner(rows, k_oct):
    # decode packed words -> kernel coeffs through the runtime itself
    solo = body_from_corners(rows, rows, rows, rows)
    decoded = trench_ffi.packed_interpolate(solo, 0.0, 0.0)
    out = []
    for row in decoded:
        pf, prad, zf, zrad, g = stage_pair(row)
        s = 2.0 ** k_oct
        out.append(tuple(int(v) for v in md.coeffs_to_words(
            *md._kernel_raw(pf * s, prad, zf * s, zrad, g))))
    return out

# strongest single corners by span, one per source body
best = {}
for key, ci, rows, cen, span in LIB:
    if key not in best or span > best[key][2]:
        best[key] = (ci, rows, span)
for key in ["fuzz", "hero", "phon"]:
    ci, rows, _ = best[key]
    REMIX.append((f"S{len(REMIX)+1} {key}.C{ci} oct-slide",
                  body_from_corners(transpose_corner(rows, -1.0), transpose_corner(rows, +1.0),
                                    transpose_corner(rows, -2.0), transpose_corner(rows, +2.0))))

# ---- gates + sheets ----------------------------------------------------------
sys.path.insert(0, str(ROOT / "dev" / "tmp"))
import copy_risk as cr
refs = sorted((ROOT / "ref" / "presets").glob("P2k_*.bin"))
refsurf = np.array([cr.surface(r.read_bytes()) for r in refs])
refname = [r.stem for r in refs]

out = U / "corner_remix"
out.mkdir(parents=True, exist_ok=True)
kept = []
for name, bb in REMIX:
    ev = evaluate_body(bb, 17)
    bad = ev["grid_unstable_rows"] + ev["interior_unstable_rows"] + ev["grid_nonfinite_rows"] + ev["interior_nonfinite_rows"]
    if bad:
        print(f"  DROPPED {name}: {bad} broken rows"); continue
    d = np.sqrt(np.mean((refsurf - cr.surface(bb)) ** 2, axis=1))
    i = int(np.argmin(d))
    if d[i] < cr.CLOSE_DB:
        print(f"  DROPPED {name}: copy-risk {d[i]:.1f} to {refname[i]}"); continue
    fn = name.split()[0]
    (out / f"{fn}.body240").write_bytes(bb)
    kept.append((name, bb))
    print(f"  {name}  morphR={ev['morph_contrast_rms_db']:.1f} Qbloom={ev['secondary_contrast_rms_db']:.1f} "
          f"zmot={ev['max_zero_motion_octaves']:.2f}oct  nearest={refname[i]} @ {d[i]:.1f}dB")

CORNERS = [("C0  wheel0·Q0", 0, 0), ("C1  wheel100·Q0", 1, 0),
           ("C2  wheel0·Q100", 0, 1), ("C3  wheel100·Q100", 1, 1)]
for sheet in range((len(kept) + 3) // 4):
    group = kept[sheet * 4:(sheet + 1) * 4]
    fig, axs = plt.subplots(len(group), 4, figsize=(13, 2.8 * len(group)), facecolor="#0a0c0b", squeeze=False)
    for r, (name, bb) in enumerate(group):
        for c, (clab, m, q) in enumerate(CORNERS):
            a = axs[r][c]; a.set_facecolor("#111318")
            a.semilogx(F, prod(bb, m, q), lw=2.0, color="#ffb35c")
            a.axhline(0, color="#5a6068", lw=0.6)
            a.set_xlim(40, 18000); a.set_ylim(-45, 25)
            a.grid(True, which="both", alpha=0.12, color="#3a4048")
            a.tick_params(colors="#8a968f", labelsize=6)
            if r == 0: a.set_title(clab, color="#8a968f", fontsize=10)
            if c == 0: a.set_ylabel(name, color="#ffd23e", fontsize=10)
    fig.suptitle(f"CORNER REMIX {sheet+1} — ladders (mixed sources) + octave slides",
                 color="#cfe9df", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out / f"remix_sheet_{sheet+1}.png", dpi=110, facecolor="#0a0c0b")
    plt.close(fig)
    print("wrote remix sheet", sheet + 1)
