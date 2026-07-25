"""Copy-risk screen (CLAUDE.md §13 'aggregate copy-risk screen').
For each candidate body, measure distance to the NEAREST P2K reference:
  - response distance: RMS dB of the Morph x Q response surface (sound copy?)
  - word distance: mean |Δ| of the 120 packed u16 words (literal byte copy?)
We WANT large distances (does NOT null = independent = legal to ship).
Internal analysis only — no P2K audio rendered, nothing shipped."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

ROOT = Path("C:/Users/hooki/df2"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "pyruntime"))
import trench_ffi as ff

SR = 39062.5
FREQS = np.logspace(np.log10(30.0), np.log10(18000.0), 192)
M = [0.0, 0.25, 0.5, 0.75, 1.0]; Q = [0.0, 0.5, 1.0]
CLOSE_DB = 6.0   # < this RMS dB = suspiciously close -> reject

CAND = {
    "sweep_wide": "desk/sheets/grammar_proof/sweep_wide.body240",
    "blade_field": "desk/sheets/grammar_proof/blade_field.body240",
    "deep_canyons": "desk/sheets/grammar_proof/deep_canyons.body240",
    "scream_cuts": "desk/sheets/grammar_proof/scream_cuts.body240",
    "talker_rich": "desk/sheets/grammar_proof/talker_rich.body240",
    "vowel_pair": "desk/sheets/grammar_proof/vowel_pair.body240",
    "acid_contrary": "desk/sheets/grammar_proof/acid_contrary.body240",
    "mech_dense": "desk/sheets/grammar_proof/mech_dense.body240",
    "ah_ee": "bodies/vocal_low_to_high/ah_ee.body240",
    "oh_ee": "bodies/vocal_low_to_high/oh_ee.body240",
    "dark_bright": "bodies/vocal_low_to_high/dark_bright.body240",
    "bell": "bodies/non_formant/bell.body240",
    "gong": "bodies/non_formant/gong.body240",
    "tine_scream": "bodies/non_formant/tine_scream.body240",
    "bass_shatter": "bodies/hybrids/bass_shatter.body240",
    "neon_vane": "bodies/neon_vane.body240",
}
for f in sorted((ROOT / "dev/tmp/audition/creative").glob("*.body240")):
    CAND[f"creative/{f.stem}"] = str(f.relative_to(ROOT)).replace("\\", "/")

def surface(body):
    rows = []
    for m in M:
        for q in Q:
            pr = ff.packed_probe(body, m, q)
            w = 2 * np.pi * FREQS / SR; z1 = np.exp(-1j * w); z2 = z1 * z1
            mag = np.ones_like(FREQS)
            for (b0, b1, b2, a1, a2) in pr["biquad"]:
                mag *= np.abs(b0 + b1*z1 + b2*z2) / np.maximum(np.abs(1.0 + a1*z1 + a2*z2), 1e-9)
            rows.append(20*np.log10(np.maximum(mag, 1e-6)))
    return np.concatenate(rows)

def words(body):
    return np.frombuffer(body, dtype="<u2").astype(np.float64)

def main():
    refs = sorted((ROOT / "dev/tmp/factory").glob("P2k_*.body240"))
    refsurf = []; refword = []; refname = []
    for r in refs:
        b = r.read_bytes(); refname.append(r.stem); refsurf.append(surface(b)); refword.append(words(b))
    refsurf = np.array(refsurf); refword = np.array(refword)

    rows = []
    for name, rel in CAND.items():
        b = (ROOT / rel).read_bytes(); cs = surface(b); cw = words(b)
        d = np.sqrt(np.mean((refsurf - cs) ** 2, axis=1))   # RMS dB to each ref
        wd = np.mean(np.abs(refword - cw), axis=1)           # mean |Δword| to each ref
        i = int(np.argmin(d))
        rows.append((name, d[i], refname[i], wd[i]))
    rows.sort(key=lambda r: r[1])   # closest first
    print(f"{'candidate':22s} {'nearest P2K':22s} respDist(dB) wordDist  verdict")
    nflag = 0
    for name, dd, rn, wd in rows:
        flag = dd < CLOSE_DB
        if flag: nflag += 1
        print(f"{name:22s} {rn:22s} {dd:8.1f}   {wd:8.0f}  {'CLOSE!' if flag else 'clear'}")
    out = ROOT / "dev/tmp/audition/copy_risk.txt"
    with open(out, "w") as f:
        f.write("Copy-risk screen — RMS dB response distance + mean word distance to nearest P2K.\n")
        f.write("Large = independent (good). <%.0f dB RMS = CLOSE (reject).\n\n" % CLOSE_DB)
        f.write(f"{'candidate':24s} {'nearest P2K':24s} {'respDB':>8s} {'wordD':>8s}  verdict\n")
        for name, dd, rn, wd in rows:
            f.write(f"{name:24s} {rn:24s} {dd:8.1f} {wd:8.0f}  {'CLOSE' if dd<CLOSE_DB else 'clear'}\n")
    print(f"\n{len(rows)} candidates, {nflag} flagged CLOSE (<{CLOSE_DB} dB). Report -> {out}")

if __name__ == "__main__":
    main()
