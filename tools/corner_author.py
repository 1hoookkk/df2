#!/usr/bin/env python3
"""corner_author.py — thin owner for authoring a static corner frame. It COMPOSES the
canonical corner_words primitives (direct pole-zero: formant/bp/lp/notch — no RBJ, no
reinvented DSP) and the canonical packed encoder, adds the few real invariants (fixed
slots, 200 Hz coupling floor, Klatt vowels), and writes both .corner.json and the
verbatim 240-byte body. corner_words owns the sections; packed_interp owns the encode.
"""
from __future__ import annotations
import math, json, sys, struct
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from pyruntime.freq_response import cascade_response_db
# the canonical section vocabulary + encoder — author with these, never reinvent them:
from tools.corner_words import formant, bp, lp, notch, edge, pas, r_from_bw
from tools.corner_words import corner_words as _to_words

SR = 39062.5
FREQS = np.logspace(math.log10(40), math.log10(16000), 512)
BAND = (FREQS >= 60) & (FREQS <= 12000)
COUPLE_HZ = 200.0          # [Klatt] adjacent formants cannot sit closer than this
GOLDEN, COMB_START = 1.61, 40.0   # [Morpheus Flange3.4]

# ── corner vowels — Klatt 1980 Table II (F1..F3,B1..B3); F4/F5,B4/B5 = Klatt defaults ──
KLATT_VOWELS = {
    "i":  (310, 2020, 2960, 45, 200, 400),
    "a":  (700, 1220, 2600, 130, 70, 160),
    "u":  (350, 1250, 2200, 65, 110, 140),
    "uv": (450, 1100, 2350, 80, 100, 80),
}
def vowel(key, voice=1.0, sharpen=1.0):
    """Vowel = formants placed directly (bp: pole at F, radius from B). 200 Hz floor."""
    f1, f2, f3, b1, b2, b3 = KLATT_VOWELS[key]
    F = [f1 * voice, f2 * voice, f3 * voice, 3300 * voice, 3850 * voice]
    B = [b1, b2, b3, 250, 200]
    for i in range(1, len(F)):
        if F[i] - F[i - 1] < COUPLE_HZ:
            F[i] = F[i - 1] + COUPLE_HZ
    return [formant(F[i], B[i], sharpen) for i in range(len(F))]

def golden_comb(n=6, zero_r=0.985):
    """Direct-pole-zero comb: a zero on the rim at 40 Hz x 1.61^k (weak pole) = a dip."""
    out, f = [], COMB_START
    for _ in range(n):
        if f < 13000:
            out.append(notch(f, 0.45, -0.08, f, zero_r))
        f *= GOLDEN
    return out

C_CM = 35000.0
_MODAL = {"bar": [1.0, 2.756, 5.404, 8.933, 13.35, 18.65],
          "membrane": [1.0, 1.593, 2.136, 2.295, 2.653, 2.917],
          "plate": [1.0, 1.71, 2.43, 3.18, 4.05, 5.06],
          "bell": [0.5, 1.0, 1.183, 1.506, 2.0, 2.514]}
def tube(length_cm, ends="closed-open", n=6, q=11, sharpen=1.0):
    fs = ([(2 * k - 1) * C_CM / (4 * length_cm) for k in range(1, n + 1)] if ends == "closed-open"
          else [k * C_CM / (2 * length_cm) for k in range(1, n + 1)])
    return [formant(f, f / q, sharpen) for f in fs if 40 < f < 13000]
def modal(kind, f0, n=6, q=55, sharpen=1.0):
    return [formant(f0 * r, f0 * r / q, sharpen) for r in _MODAL[kind][:n] if 40 < f0 * r < 13000]

# ── compile / encode / write ──────────────────────────────────────────────────────
def compile(stages):
    """stages: corner_words primitives (StageParams), FIXED order (never sorted). Returns
    (coeffs, words, report). coeffs = kernel for gating/.corner.json; words = verbatim."""
    st = list(stages)[:6]
    while len(st) < 6:
        st.append(pas())
    coeffs = [s.encode() for s in st]
    words = _to_words(st)
    db = cascade_response_db(coeffs, FREQS, SR)
    finite = bool(np.all(np.isfinite(db)))
    peak = float(np.max(db[BAND])) if finite else 999.0
    sub = float(db[(FREQS >= 45) & (FREQS <= 70)].max()) if finite else 999.0   # no sub boost
    ok = finite and peak < 40.0 and sub < 2.0
    return coeffs, words, {"ok": ok, "peak_db": round(peak, 2), "sub_db": round(sub, 2), "finite": finite}

_LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]

def corner_json(coeffs, name, boost=1.5):
    js = [{"c0": e.c0, "c1": e.c1, "c2": e.c2, "c3": e.c3, "c4": e.c4} for e in coeffs]
    return {"format": "compiled-v1", "name": name, "sampleRate": SR, "stages": 6,
            "keyframes": [{"label": lab, "boost": boost, "stages": js} for lab in _LABELS]}

def body240(corner_words_4):
    """4 corners (each = 6 packed word-tuples) -> verbatim 240-byte body."""
    flat = [int(w) & 0xFFFF for cwl in corner_words_4 for stage in cwl for w in stage]
    assert len(flat) == 120, "120 u16 words = 240 bytes"
    return struct.pack("<120H", *flat)

def write_corner(stages, name, group, base=None):
    base = base or (ROOT / "dev/tmp/arma_source_pack/corners_audio_only/_authored")
    coeffs, words, rep = compile(stages)
    if not rep["ok"]:
        return coeffs, words, rep
    d = Path(base) / group; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.corner.json").write_text(json.dumps(corner_json(coeffs, f"{group} / {name}"), indent=1))
    (d / f"{name}.body240").write_bytes(body240([words] * 4))
    return coeffs, words, rep

if __name__ == "__main__":
    for key in ("u", "a", "i"):
        c, w, r = compile(vowel(key))
        print(f"vowel /{key}/  ok={r['ok']}  sub={r['sub_db']:+.1f}dB  peak={r['peak_db']:+.1f}dB")
    c, w, r = compile(golden_comb())
    print(f"golden_comb   ok={r['ok']}  sub={r['sub_db']:+.1f}dB  peak={r['peak_db']:+.1f}dB")
    raw = body240([compile(vowel(k))[1] for k in ("u", "a", "i", "u")])
    import pyruntime.trench_ffi as ff
    from pyruntime.encode import EncodedCoeffs
    resp = cascade_response_db([EncodedCoeffs(*x) for x in ff.packed_interpolate(raw, .5, .5)], FREQS, SR)
    print(f"body240       bytes={len(raw)}  mid-render finite={bool(np.all(np.isfinite(resp)))}")
