"""throat_bend — the Vowel Bending preset. Clean-room (tables + measured
statistics only, no ROM rows).

MORPH bends the vowel, Q opens the mouth. All four corners AUTHORED table poses:
  M0_Q0     'ee' (bead)  270/2290/3010, Klatt BW 52/200/400
  M100_Q0   'oo' (boot)  300/ 870/2240, Klatt BW 72/105/110
  M0_Q100   'ah' (bard)  730/1090/2440, Klatt BW 130/70/160  (mouth open, ee side)
  M100_Q100 'aw' (bought) 570/ 840/2410 (Peterson-Barney), ah bandwidths
Freqs: klatt_1980_formants / vowel_formants tables. Lane slots, zero motifs,
ballast/air/notch rails and gates identical to build_vowel_stress_cleanroom.
Use case: post-pitch-shifter throat imposer / automate MORPH+Q to re-open vowels.
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import numpy as np

WS = Path("C:/Users/hooki/df2-workstation")
OUT = WS / "dev/tmp/namesakes"
BIN = WS / "target/release/body-from-geometry.exe"
sys.path.insert(0, str(WS / "dev/tmp/bytes_fix"))
from build_vowel_stress_cleanroom import vowel_corner, ROOT
from fix_bodies import renorm_corner, trim_crown
from build_all_archetypes import rom_geometry_and_bytes, packed_db, surface, CORNERS, CORNER_MQ


def main():
    corners_geo = [
        # ballast / air / notch rails follow the cleanroom pattern:
        # ballast in the ROM lowest-lane band, notch hole per pose intent
        vowel_corner([270, 2290, 3010], [52, 200, 400], 240.0, 9500.0, 3600.0),   # ee
        vowel_corner([300, 870, 2240], [72, 105, 110], 240.0, 8000.0, 5200.0),    # oo
        vowel_corner([730, 1090, 2440], [130, 70, 160], 320.0, 10500.0, 3600.0),  # ah
        vowel_corner([570, 840, 2410], [130, 70, 160], 320.0, 9500.0, 5200.0),    # aw
    ]
    log = []
    for c in corners_geo:
        renorm_corner(c, log); trim_crown(c, log)
    gpath = OUT / "throat_bend.geometry.json"
    gpath.write_text(json.dumps({"name": "throat_bend", "corners": corners_geo}, indent=1))
    bpath = OUT / "throat_bend.body240"
    r = subprocess.run([str(BIN), str(gpath), str(bpath)], capture_output=True, text=True)
    if r.returncode != 0:
        print("COMPILE FAILED\n", r.stderr[-400:]); sys.exit(1)
    body = bpath.read_bytes()

    roms = sorted((ROOT / "bodies/rom").glob("P2k_*.json"))
    romsurf, names, romcorner_tfs = [], [], []
    for f in roms:
        _, raw, _ = rom_geometry_and_bytes(f)
        romsurf.append(surface(raw)); names.append(f.stem)
        for c in CORNERS:
            romcorner_tfs.append((f.stem + ":" + c, packed_db(raw, *CORNER_MQ[c])))
    d = np.sqrt(np.mean((np.array(romsurf) - surface(body)) ** 2, axis=1))
    i = int(np.argmin(d))
    print(f"surface copy-risk: nearest {names[i]} at {d[i]:.1f} dB ({'CLEAR' if d[i]>=6 else 'TOO CLOSE'})")
    worst = None
    for c in CORNERS:
        db = packed_db(body, *CORNER_MQ[c])
        dmin, nm = min((float(np.sqrt(np.mean((db - rtf) ** 2))), nm) for nm, rtf in romcorner_tfs)
        if worst is None or dmin < worst[0]:
            worst = (dmin, c, nm)
        print(f"  {c}: floor {np.median(db):+.1f} crown {db.max():+.1f} | nearest ROM corner {nm} at {dmin:.1f} dB")
    print(f"per-corner gate: worst {worst[0]:.1f} dB ({worst[1]} vs {worst[2]}) ({'CLEAR' if worst[0]>=6 else 'TOO CLOSE'})")
    bloom = max(float((packed_db(body, m, 1.0) - packed_db(body, m, 0.0)).max())
                for m in (0, 0.25, 0.5, 0.75, 1.0))
    print(f"bloom {bloom:.1f} dB ({'PASS' if 13.9 <= bloom <= 254 else 'OUT OF BAND'})")


if __name__ == "__main__":
    main()
