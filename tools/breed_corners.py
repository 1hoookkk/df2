#!/usr/bin/env python3
"""breed_corners — cross-breed two decoded ROM bodies into one KIN hybrid.

The "Anchor + Fracture" merge, done the right way:
  - merge by ACTUAL FREQUENCY, never by stage index (stages aren't freq-ordered,
    so `hybrid[i] = fracture[i]` grabs arbitrary poles — that's the retired
    per-stage-role trap). We decode each parent's poles, take the ANCHOR's poles
    below the crossover + the FRACTURE's poles above it.
  - merge PER CORNER, so the hybrid's four corners stay kin: both parents are
    internally kin (same preset's variants), so a band-wise merge of corner ci
    from each keeps the hybrid's ci kin to its siblings → the morph glides, not
    mushes (clear low + complex high preserved through the morph).
  - realize through corner_words (bp = pole + DC-null zero, no pedestal; edge for
    the Nyquist bite) — the proven stable/packable path. No new math.

Inputs are the decoded 240-byte ROM stock under bodies/rom/. Output is a hybrid
240-byte body + compiled-v1 cartridge under bodies/hybrids/. Gated: finite,
stable (radius < 1, guaranteed by corner_words), peak sane (no gain-to-hell).
The hybrid is a SEED for audition — you keep the iconic ones by ear.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.packed_interp import words_to_coeffs
from tools.corner_words import bp, corner_words, edge, pas

SR = 39062.5
TAU = 2.0 * np.pi
LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
MQ = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
F = freq_points()


def decode_corner_poles(words30):
    """30 u16 (one corner) -> [(freq_hz, radius)] for its non-passthrough poles."""
    poles = []
    for s in range(6):
        c0, c1, c2, c3, c4 = words_to_coeffs(words30[s * 5 : s * 5 + 5])
        # passthrough = [2,1,2,1,1]
        if abs(c0 - 2) < 1e-6 and abs(c2 - 2) < 1e-6 and abs(c3 - 1) < 1e-6:
            continue
        a1 = c2 - 2.0
        a2 = 1.0 - c3
        r = max(0.0, a2) ** 0.5
        if not (1e-3 < r < 1.0):
            continue
        cos_t = max(-1.0, min(1.0, -a1 / (2.0 * r)))
        f = float(np.arccos(cos_t)) * SR / TAU
        if 10.0 < f < SR * 0.5:
            poles.append((f, r))
    return poles


def load_body_corners(path):
    b = Path(path).read_bytes()
    if len(b) != 240:
        raise ValueError(f"{path}: {len(b)} bytes, expected 240")
    w = struct.unpack("<" + "H" * 120, b)
    return [decode_corner_poles(w[ci * 30 : ci * 30 + 30]) for ci in range(4)]


def realize_poles(poles):
    """[(freq, radius)] -> 6 StageParams via corner_words (bp / edge / pas)."""
    poles = sorted(poles, key=lambda p: p[0])[:6]
    stages = []
    for f, r in poles:
        stages.append(edge(min(r, 0.996)) if f >= 12000.0 else bp(f, min(r, 0.997)))
    while len(stages) < 6:
        stages.append(pas())
    return stages


def band(db, lo, hi):
    m = (F >= lo) & (F < hi)
    return float(np.mean(db[m])) if m.any() else float("nan")


def breed(anchor_path, fracture_path, cross_hz):
    anchor = load_body_corners(anchor_path)
    fracture = load_body_corners(fracture_path)
    corners_words = []
    summary = []
    max_peak = -1e9
    for ci in range(4):
        low = [p for p in anchor[ci] if p[0] < cross_hz]
        high = [p for p in fracture[ci] if p[0] >= cross_hz]
        stages = realize_poles(low + high)
        words = corner_words(stages)
        corners_words.append(words)
        enc = [EncodedCoeffs(*words_to_coeffs(w)) for w in words]
        db = cascade_response_db(enc, F)
        max_peak = max(max_peak, float(np.max(db)))
        summary.append(
            {
                "label": LABELS[ci],
                "low": round(band(db, 20, 200), 1),
                "body": round(band(db, 200, 1200), 1),
                "bite": round(band(db, 1200, 5500), 1),
                "air": round(band(db, 5500, 16000), 1),
                "peak": round(float(np.max(db)), 1),
            }
        )
    stable = max_peak < 60.0 and all(
        np.all(np.isfinite([v for v in s.values() if isinstance(v, float)])) for s in summary
    )
    return corners_words, summary, stable


def to_body240(corners_words):
    flat = []
    for cw in corners_words:
        for w in cw:
            flat.extend(int(x) & 0xFFFF for x in w)
    return struct.pack("<" + "H" * 120, *flat)


def to_cartridge(name, corners_words):
    kf = []
    for ci, cw in enumerate(corners_words):
        m, q = MQ[ci]
        stages = []
        for w in cw:
            c = words_to_coeffs(w)
            stages.append({"c0": c[0], "c1": c[1], "c2": c[2], "c3": c[3], "c4": c[4]})
        kf.append(
            {
                "label": LABELS[ci],
                "morph": m,
                "q": q,
                "boost": 1.0,
                "packedWords": [list(int(x) & 0xFFFF for x in w) for w in cw],
                "stages": stages,
            }
        )
    return {
        "format": "compiled-v1",
        "name": name,
        "provenance": "bred-hybrid",
        "sampleRate": SR,
        "authoring_sample_rate_hz": SR,
        "stages": 6,
        "cornerOrder": LABELS,
        "keyframes": kf,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anchor", required=True, help="stem under bodies/rom/ (clear low)")
    ap.add_argument("--fracture", required=True, help="stem under bodies/rom/ (complex high)")
    ap.add_argument("--out", required=True, help="hybrid name")
    ap.add_argument("--cross", type=float, default=1000.0, help="low/high split Hz")
    a = ap.parse_args()

    rom = ROOT / "bodies" / "rom"
    anchor = rom / f"{a.anchor}.json"
    fracture = rom / f"{a.fracture}.json"
    # The stock is cart JSON; pull its body240 via the packed words.
    anchor_b = cart_to_body240(anchor)
    fracture_b = cart_to_body240(fracture)
    tmp = ROOT / "dev" / "tmp" / "breed"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "anchor.body240").write_bytes(anchor_b)
    (tmp / "fracture.body240").write_bytes(fracture_b)

    words, summary, stable = breed(tmp / "anchor.body240", tmp / "fracture.body240", a.cross)
    outdir = ROOT / "bodies" / "hybrids"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{a.out}.body240").write_bytes(to_body240(words))
    cart = to_cartridge(a.out, words)
    (outdir / f"{a.out}.cart.json").write_text(json.dumps(cart, indent=2))

    print(f"{a.out}: {a.anchor} (low) x {a.fracture} (high) @ {a.cross:.0f}Hz  ->  {'STABLE' if stable else 'REJECT'}")
    for s in summary:
        print(
            f"  {s['label']:10s} low={s['low']:6.1f} body={s['body']:6.1f} "
            f"bite={s['bite']:6.1f} air={s['air']:6.1f}  peak={s['peak']:6.1f}dB"
        )


def cart_to_body240(cart_path):
    d = json.loads(Path(cart_path).read_text())
    flat = []
    for kf in d["keyframes"]:
        for w in kf["packedWords"]:
            flat.extend(int(x) & 0xFFFF for x in w)
    return struct.pack("<" + "H" * 120, *flat)


if __name__ == "__main__":
    main()
