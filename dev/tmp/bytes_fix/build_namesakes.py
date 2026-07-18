"""The four TRENCH namesakes — archetype (x) NEW MEASURED RAILS.

THE method (FILTER_NOTEBOOK, converged 2026-07-17):
  frame lanes verbatim; mover lanes keep zero rail / radii / scale and get
  their pole CENTER re-railed to measured table frequencies (rank-matched);
  Q100 corners inherit the archetype's own per-lane Q0->Q100 transform
  (center ratio + Q-pose radius) applied around the new rails.

Archetypes and rails (all freqs table-pulled, never invented):
  P2k_007 Fuzzi Face   -> tube_resonances closed-open odd harmonics,
                          long tube L=0.60m -> short tube L=0.15m  ("tube_shout")
  P2k_029 Lucifer's Q  -> metallic_modes tuned bell partials,
                          f0 400 -> 1200 Hz                        ("bell_rake")
  P2k_004 Meaty Gizmo  -> membrane_modes drumhead,
                          f0 120 -> 400 Hz                         ("skin_hit")
  P2k_015 DJ Alkaline  -> Klatt vocal, 'oo' -> 'ae' + F4/F5 3300/3750
                          (klatt_1980_formants)                    ("acid_vox")

Gates (cleanroom standard): full-surface copy-risk >=6 dB vs all 33 ROM
bodies, per-corner response distance >=6 dB vs all 132 ROM corners, packed
QC floors/crowns, 25x25 certify via body-from-geometry.
"""
from __future__ import annotations
import json, math, subprocess, sys
from pathlib import Path
import numpy as np

ROOT = Path("C:/Users/hooki/df2")
WS = Path("C:/Users/hooki/df2-workstation")
OUT = WS / "dev/tmp/namesakes"
BIN = WS / "target/release/body-from-geometry.exe"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "pyruntime"))
sys.path.insert(0, str(WS / "dev/tmp/bytes_fix"))
import trench_ffi as ff
from fix_bodies import renorm_corner, trim_crown, FREQS, Z1, Z2
from build_all_archetypes import (rom_geometry_and_bytes, to_roots, packed_db,
                                  surface, CORNERS, CORNER_MQ)

SR = 39062.5
C_SOUND = 343.0

def closed_open(L, n):
    return (2 * n - 1) * C_SOUND / (4 * L)

BELL = [0.5, 1.0, 1.2, 1.5, 2.0, 2.67]           # metallic_modes tuned bell set
DRUM = [1.0, 1.594, 2.136, 2.296, 2.653, 2.918]  # membrane (0,1)..(1,2)
VOX_OO = [300, 870, 2240, 3300, 3750]            # Klatt 'oo' + F4/F5
VOX_AE = [660, 1720, 2410, 3300, 3750]           # Klatt 'ae' + F4/F5

SPECS = [
    ("tube_shout", "P2k_007",
     [closed_open(0.60, n) for n in range(1, 6)],   # 143..1286 Hz
     [closed_open(0.15, n) for n in range(1, 6)]),  # 572..5145 Hz
    ("bell_rake", "P2k_029",
     [r * 400.0 for r in BELL],
     [r * 1200.0 for r in BELL]),
    ("skin_hit", "P2k_004",
     [r * 120.0 for r in DRUM],
     [r * 400.0 for r in DRUM]),
    ("acid_vox", "P2k_015", VOX_OO, VOX_AE),
]


def conj_hz(s):
    k, a, b = s["pole"]
    return a if (k == "conj" and a > 20.0) else None


def build_corners(geo, home_rail, away_rail):
    """Re-rail mover pole centers; everything else verbatim from the archetype."""
    m0, m100 = geo["M0_Q0"], geo["M100_Q0"]
    movers = []
    for si in range(6):
        h0, h1 = conj_hz(m0[si]), conj_hz(m100[si])
        if h0 and h1 and abs(math.log2(h1 / h0)) > 0.3:
            movers.append(si)
    # rank-match: movers sorted by M0 center take rail freqs sorted ascending
    order = sorted(movers, key=lambda si: conj_hz(m0[si]))
    rails = {}
    for rank, si in enumerate(order):
        rails[si] = (sorted(home_rail)[rank % len(home_rail)],
                     sorted(away_rail)[rank % len(away_rail)])
    corners = []
    for c in CORNERS:
        q0c = geo["M0_Q0" if c.startswith("M0") else "M100_Q0"]
        newc = []
        for si in range(6):
            s = {k: v for k, v in geo[c][si].items()}
            if si in rails:
                base = conj_hz(q0c[si])
                cur = conj_hz(s)
                if base and cur:
                    rail = rails[si][0 if c.startswith("M0") else 1]
                    # archetype's own Q transform = cur/base ratio, kept around the new rail
                    hz = min(max(rail * (cur / base), 25.0), 19000.0)
                    s["pole"] = ("conj", hz, s["pole"][2])
            newc.append(s)
        corners.append(to_roots(newc, c))
    return corners, movers


def main():
    OUT.mkdir(exist_ok=True)
    roms = sorted((ROOT / "bodies/rom").glob("P2k_*.json"))
    romsurf, names, romcorner_tfs, geos = [], [], [], {}
    for f in roms:
        g, raw, _ = rom_geometry_and_bytes(f)
        geos[f.stem.split("_")[0] + "_" + f.stem.split("_")[1]] = g
        romsurf.append(surface(raw)); names.append(f.stem)
        for c in CORNERS:
            romcorner_tfs.append((f.stem + ":" + c, packed_db(raw, *CORNER_MQ[c])))
    romsurf = np.array(romsurf)

    report = {}
    for stem, arch, home, away in SPECS:
        geo = geos[arch]
        corners, movers = build_corners(geo, home, away)
        for c in corners:
            renorm_corner(c, []); trim_crown(c, [])
        gpath = OUT / f"{stem}.geometry.json"
        gpath.write_text(json.dumps({"name": stem, "corners": corners}, indent=1))
        bpath = OUT / f"{stem}.body240"
        r = subprocess.run([str(BIN), str(gpath), str(bpath)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"{stem}: COMPILE FAILED\n{r.stderr[-300:]}")
            report[stem] = {"ok": False, "why": "compile"}
            continue
        body = bpath.read_bytes()
        d = np.sqrt(np.mean((romsurf - surface(body)) ** 2, axis=1))
        i = int(np.argmin(d))
        worst = None
        mets = {}
        for c in CORNERS:
            db = packed_db(body, *CORNER_MQ[c])
            dc = min((float(np.sqrt(np.mean((db - rtf) ** 2))), nm) for nm, rtf in romcorner_tfs)
            mets[c] = {"floor": round(float(np.median(db)), 1),
                       "crown": round(float(db.max()), 1),
                       "nearest": dc[1], "dist": round(dc[0], 1)}
            if worst is None or dc[0] < worst[0]:
                worst = (dc[0], c, dc[1])
        ok = d[i] >= 6.0 and worst[0] >= 6.0
        report[stem] = {"ok": bool(ok), "arch": arch, "movers": movers,
                        "surface_nearest": names[i], "surface_dist": round(float(d[i]), 1),
                        "worst_corner": [round(worst[0], 1), worst[1], worst[2]],
                        "corners": mets}
        flag = "CLEAR" if ok else "TOO CLOSE"
        print(f"{stem} <- {arch}: movers {movers} | surface {d[i]:.1f} dB (nearest {names[i]}) | "
              f"worst corner {worst[0]:.1f} dB ({worst[1]} vs {worst[2]}) [{flag}]")
        for c in CORNERS:
            m = mets[c]
            print(f"    {c}: floor {m['floor']:+.1f} crown {m['crown']:+.1f}")
    (OUT / "namesakes_report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
