"""build_measured_object — first measured-object body via the TF lane.

violin_cave: 4 AUTHORED corners, each its own real measurement:
  M0_Q0     Violin Body Dampened     (tight instrument)
  M0_Q100   Violin Body Resonant     (open instrument — Q opens the body)
  M100_Q0   Gill Heads mine site1    (near cave)
  M100_Q100 Gill Heads mine site2    (deep cave)
MORPH = violin -> cave, Q = damped -> resonant. All sources CC (see
wav-source-library/measured_objects/*/LICENSE*).

Pipeline (the TF internal representative): ir_to_tf -> fit_corner_from_magnitude
-> coeffs_to_words -> raw_from_words -> 25x25 packed_probe certify -> QC.

  python tools/build_measured_object.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

WS = Path(__file__).resolve().parent.parent
DF2 = Path("C:/Users/hooki/df2")
for p in (str(WS / "tools"), str(DF2), str(DF2 / "pyruntime")):
    sys.path.insert(0, p)
from tf_ingest import ir_to_tf, FREQS
from pyruntime import trench_ffi
from pyruntime.packed_interp import coeffs_to_words
from src.utils.body240 import raw_from_words

ENGINE_SR = 39062.5
MO = WS / "wav-source-library/measured_objects"
OUT = WS / "dev/tmp/measured_objects"

CORNER_WAVS = {
    "M0_Q0": MO / "ir_library/violin/Violin Body Dampened.wav",
    "M0_Q100": MO / "ir_library/violin/Violin Body Resonant.wav",
    "M100_Q0": MO / "openair/gill-heads-mine/gill-heads-mine/mono/mine_site1_1way_mono.wav",
    "M100_Q100": MO / "openair/gill-heads-mine/gill-heads-mine/mono/mine_site2_2way_mono.wav",
}


def fit_corner(wav):
    tf = ir_to_tf(wav, detilt=True)  # features over tilt — see tf_ingest
    db = np.array(tf["mag_db"])
    # fit band 60..16k (engine authoring band; grid edges are unreliable in IRs)
    band = (FREQS >= 60.0) & (FREQS <= 16000.0)
    rows = trench_ffi.fit_corner_from_magnitude(
        list(zip(FREQS[band].tolist(), db[band].tolist())), ENGINE_SR)
    return [tuple(int(v) for v in coeffs_to_words(*r)) for r in rows]


def corner_rows(wav):
    tf = ir_to_tf(wav, detilt=True)
    db = np.array(tf["mag_db"])
    band = (FREQS >= 60.0) & (FREQS <= 16000.0)
    return trench_ffi.fit_corner_from_magnitude(
        list(zip(FREQS[band].tolist(), db[band].tolist())), ENGINE_SR)


def main():
    OUT.mkdir(exist_ok=True)
    CORNER_MQ = {"M0_Q0": (0.0, 0.0), "M100_Q0": (1.0, 0.0), "M0_Q100": (0.0, 1.0), "M100_Q100": (1.0, 1.0)}
    Z1 = np.exp(-2j * np.pi * FREQS / ENGINE_SR); Z2n = Z1 * Z1

    def rows_db(rows_words):
        body1 = raw_from_words({c: rows_words for c in CORNER_MQ})
        pr = trench_ffi.packed_probe(body1, 0.0, 0.0)
        mag = np.ones_like(FREQS)
        for (b0, b1, b2, a1, a2) in pr["biquad"]:
            mag *= np.abs(b0 + b1 * Z1 + b2 * Z2n) / np.maximum(np.abs(1 + a1 * Z1 + a2 * Z2n), 1e-12)
        return 20 * np.log10(np.maximum(mag, 1e-9))

    words = {}
    for c, w in CORNER_WAVS.items():
        rows = corner_rows(w)
        # floor renorm: pull the packed median to 0 dB, split across 6 stage gains
        wtmp = [tuple(int(v) for v in coeffs_to_words(*r)) for r in rows]
        med = float(np.median(rows_db(wtmp)))
        g = 10 ** (-med / 20.0 / 6.0)
        rows = [(c0, c1, c2, c3, c4 * g) for (c0, c1, c2, c3, c4) in rows]
        words[c] = [tuple(int(v) for v in coeffs_to_words(*r)) for r in rows]
    body = raw_from_words(words)
    bpath = OUT / "violin_cave.body240"
    bpath.write_bytes(body)

    # 25x25 certify on the packed runtime
    unstable = nonfinite = 0
    maxr = 0.0
    for m in np.linspace(0, 1, 25):
        for q in np.linspace(0, 1, 25):
            pr = trench_ffi.packed_probe(body, float(m), float(q))
            unstable += int(pr["unstable"]) if "unstable" in pr else 0
            for row in pr["biquad"]:
                if not all(np.isfinite(row)):
                    nonfinite += 1
                a1, a2 = row[3], row[4]
                r = np.sqrt(abs(a2)) if abs(a2) < 4 else 99
                maxr = max(maxr, r)
    print(f"certify 25x25: unstable {unstable}, nonfinite {nonfinite}, max pole radius {maxr:.4f}")

    # QC floors/crowns per corner from the packed bytes
    Z1 = np.exp(-2j * np.pi * FREQS / ENGINE_SR); Z2 = Z1 * Z1
    def corner_db(m, q):
        pr = trench_ffi.packed_probe(body, m, q)
        mag = np.ones_like(FREQS)
        for (b0, b1, b2, a1, a2) in pr["biquad"]:
            mag *= np.abs(b0 + b1 * Z1 + b2 * Z2) / np.maximum(np.abs(1 + a1 * Z1 + a2 * Z2), 1e-12)
        return 20 * np.log10(np.maximum(mag, 1e-9))
    for c, (m, q) in {"M0_Q0": (0, 0), "M100_Q0": (1, 0), "M0_Q100": (0, 1), "M100_Q100": (1, 1)}.items():
        db = corner_db(m, q)
        print(f"  {c}: floor {np.median(db):+.1f} dB crown {db.max():+.1f} dB @ {FREQS[int(np.argmax(db))]:.0f} Hz")
    print(f"wrote {bpath}")


if __name__ == "__main__":
    main()
