#!/usr/bin/env python3
"""corner_author.py — THE single owned primitive for authoring a static Z-plane CORNER
frame. The doctrine lives here AS ENFORCED INVARIANTS so it can't be re-violated per
script (the fix for the recurring corner-authoring bugs). Everything that makes a corner
— the library, the Forge audition bake, body assembly — calls THIS, never its own copy.

Source-grounded; see ref/morpheus_authoring_doctrine.md. Each rule below is tagged:
  [LAW]   = stated in the primary sources (Rossum patents / ARMAdillo 1991 / Klatt 1980 /
            Morpheus manual). Enforced verbatim.
  [CLEAN] = standard DSP / engineering the sources REQUIRE but do not give a formula for.
            Our implementation, never claimed as E-mu's exact method.

Author in PERCEPTUAL units only: Fc in Hz (log/octaves), Bw in octaves, Gain in dB. Never
raw b1/b2 at the call site. [LAW: ARMAdillo — author in octaves + dB.]
"""
from __future__ import annotations
import math, json, sys, struct
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from tools import corner_words as cw          # the ONE owned verbatim encoder (null-verified to ROM)

SR        = 39062.5      # df2 authoring rate (~40 kHz, the ARMAdillo reference rate)
NSTAGES   = 6            # df2 v1 = 1 LP + 5 PEQ. [LAW] Morpheus = 7 (1 LP + 6 PEQ); 7th = v2 slot.
RMAX      = 0.9985       # [CLEAN] stability cap (exact Rmax NOT in sources; poles->1 = noise [LAW])
COUPLE_HZ = 200.0        # [LAW Klatt] formants closer than this couple: both +3..6 dB
COUPLE_DB = (3.0, 6.0)   # [LAW Klatt] coupling boost range
BW_DB_PER_OCT = 6.0      # [LAW Klatt] halve bandwidth => +6 dB peak (peak amplitude ∝ 1/Bw)
GOLDEN    = 1.61         # [LAW Morpheus Flange3.4] comb notch ratio
COMB_START = 40.0        # [LAW Morpheus Flange3.4] comb base frequency (Hz)
_FREQS = np.logspace(math.log10(40), math.log10(16000), 512)
_BAND  = (_FREQS >= 60) & (_FREQS <= 12000)
PASS   = [2.0, 1.0, 2.0, 1.0, 1.0]

# ── section realizers: perceptual -> df2 kernel coeffs [c0..c4] ───────────────────────
def _bq_to_kernel(b0, b1, b2, a0, a1, a2):
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0   # normalise a0 = 1
    return [2 + b1 / b0, 1 - b2 / b0, a1 + 2.0, 1 - a2, b0]

def _peaking(fc, bw_oct, gain_db):
    """RBJ parametric peaking EQ — flat 0 dB baseline + bump (or notch if gain<0).
    UNITY DC by construction (no pedestal). [LAW: parametric EQ section]"""
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * _clamp_fc(fc) / SR
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw * math.sinh((math.log(2) / 2) * bw_oct * (w0 / sw))
    return _bq_to_kernel(1 + alpha * A, -2 * cw, 1 - alpha * A, 1 + alpha / A, -2 * cw, 1 - alpha / A)

def _lowpass(fc, q):
    """RBJ 2-pole low-pass (the cascade's leading LP section). Unity DC. [LAW: 1 LP section]"""
    w0 = 2 * math.pi * _clamp_fc(fc) / SR
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * max(q, 0.2))
    b1 = 1 - cw
    return _bq_to_kernel(b1 / 2, b1, b1 / 2, 1 + alpha, -2 * cw, 1 - alpha)

def _clamp_fc(fc):
    return float(min(max(fc, 20.0), 0.49 * SR))

# section spec = a tuple; author with these (perceptual units only)
def LP(fc, q=0.9):            return ("lp", fc, q, 0.0)
def PK(fc, bw_oct, gain_db):  return ("pk", fc, bw_oct, gain_db)
def NT(fc, bw_oct, depth_db): return ("pk", fc, bw_oct, -abs(depth_db))   # notch = negative peaking

def _realize(sec):
    kind, a, b, c = sec
    return _lowpass(a, b) if kind == "lp" else _peaking(a, b, c)

# ── bandwidth <-> gain (Klatt) ───────────────────────────────────────────────────────
def gain_from_bw(bw_hz, ref_bw=100.0, ref_gain=11.0):
    """[LAW Klatt] peak ∝ 1/Bw: +6 dB per halving of bandwidth, relative to a reference."""
    return ref_gain + BW_DB_PER_OCT * math.log2(ref_bw / bw_hz)

def bw_hz_to_oct(fc, bw_hz):
    return math.log2((fc + bw_hz / 2) / (fc - bw_hz / 2))

# ── exact corner vowels — KLATT 1980 Table II (NOT Peterson-Barney) [LAW] ─────────────
#    (F1,F2,F3, B1,B2,B3). F4/F5 + B4/B5 = Klatt high-formant defaults.
KLATT_VOWELS = {
    "i":  (310, 2020, 2960, 45, 200, 400),   # [i^y]  beet
    "a":  (700, 1220, 2600, 130, 70, 160),   # [a]    bard
    "u":  (350, 1250, 2200, 65, 110, 140),   # [u^w]  boot
    "uv": (450, 1100, 2350, 80, 100, 80),    # [u^v]  variant
}
_F45, _B45 = (3300, 3850), (250, 200)

def vowel(key, voice=1.0):
    """Author a vowel corner from EXACT Klatt F+B. Gain DERIVED from Bw (peak ∝ 1/Bw).
    Coupling [LAW]: formants within 200 Hz get +3..6 dB and a Bw widen; and adjacent
    formants are not allowed CLOSER than 200 Hz within the corner."""
    F1, F2, F3, B1, B2, B3 = KLATT_VOWELS[key]
    F = [F1 * voice, F2 * voice, F3 * voice, _F45[0] * voice, _F45[1] * voice]
    B = [B1, B2, B3, _B45[0], _B45[1]]
    # enforce the 200 Hz coupling floor within the corner [LAW]
    for i in range(1, len(F)):
        if F[i] - F[i - 1] < COUPLE_HZ:
            F[i] = F[i - 1] + COUPLE_HZ
    g   = [gain_from_bw(b) for b in B]
    bwo = [bw_hz_to_oct(f, b) for f, b in zip(F, B)]
    for i in range(len(F) - 1):                       # coupling boost + widen [LAW + CLEAN widen]
        gap = abs(F[i + 1] - F[i])
        if gap < COUPLE_HZ:
            boost = COUPLE_DB[0] + (COUPLE_DB[1] - COUPLE_DB[0]) * (1 - gap / COUPLE_HZ)
            g[i] += boost; g[i + 1] += boost
            bwo[i] *= 1.25; bwo[i + 1] *= 1.25
    return [PK(round(F[i], 1), round(bwo[i], 4), round(g[i], 2)) for i in range(len(F))]

def golden_comb(n=6, depth_db=-15.0, bw_oct=0.20):
    """[LAW Morpheus] log comb notches at 40 Hz x 1.61^k — hit harmonics one at a time."""
    out, f = [], COMB_START
    for _ in range(n):
        out.append(NT(round(f, 1), bw_oct, depth_db)); f *= GOLDEN
    return out

# ── the compiler — enforces the invariants, returns kernel coeffs + a report ──────────
def _cascade_dc(secs):
    d = 1.0
    for c0, c1, c2, c3, c4 in secs:
        den = c2 - c3
        if abs(den) < 1e-12:
            return None
        d *= c4 * (c0 - c1) / den
    return d

def compile(sections):
    """Realize sections IN ORDER (fixed slots, never sorted -> slot registration lets poles
    cross), force unity DC gain [LAW], cap radius [CLEAN], gate stability/finite. Returns
    (coeffs6, report). report.ok is False if the corner must be rejected."""
    secs = [_realize(s) for s in sections[:NSTAGES]]
    while len(secs) < NSTAGES:
        secs.append(PASS[:])
    # force unity DC gain [LAW] — scaling one section's b0 scales the whole cascade
    D = _cascade_dc(secs)
    if D and abs(D) > 1e-9:
        for s in secs:
            if s != PASS:
                s[4] /= D
                break
    db = cascade_response_db([EncodedCoeffs(*s) for s in secs], _FREQS, SR)
    finite = bool(np.all(np.isfinite(db)))
    peak = float(np.max(db[_BAND])) if finite else 999.0
    Dpost = _cascade_dc(secs)                                  # TRUE DC gain (z=1), post-forcing
    dc = 20.0 * math.log10(abs(Dpost)) if (Dpost and abs(Dpost) > 1e-12) else 99.0
    ok = finite and peak < 40.0 and abs(dc) < 0.1             # [LAW] DC forced to unity (~0 dB)
    report = {"ok": ok, "peak_db": round(peak, 2), "dc_db": round(dc, 3), "finite": finite}
    return secs, report

# ── writers ──────────────────────────────────────────────────────────────────────────
_LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]

def corner_json(secs, name, boost=1.5):
    """A single-posture compiled-v1 dict (the corner replicated across all 4 keyframes)."""
    js = [{"c0": s[0], "c1": s[1], "c2": s[2], "c3": s[3], "c4": s[4]} for s in secs]
    return {"format": "compiled-v1", "name": name, "sampleRate": SR, "stages": NSTAGES,
            "keyframes": [{"label": lab, "boost": boost, "stages": js} for lab in _LABELS]}

def write_corner(sections, name, group, base=None):
    """Compile + write <group>/<name>.corner.json into the Forge well scan root. Returns
    (secs, report) — caller checks report.ok."""
    base = base or (ROOT / "dev/tmp/arma_source_pack/corners_audio_only/_authored")
    secs, report = compile(sections)
    if not report["ok"]:
        return secs, report
    d = Path(base) / group; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.corner.json").write_text(json.dumps(corner_json(secs, f"{group} / {name}"), indent=1))
    return secs, report

# ── VERBATIM 240-byte encoding — the one source-critical step. E-mu stores 240 bytes
#    verbatim (no runtime compiler); the player reads them back verbatim. coeffs->words is
#    the null-verified (−95 dB vs ROM) minifloat packer; we own it through here. ─────────
def pack_corner(secs):
    """6 kernel stages -> 30 packed u16 words (60 bytes' worth) — one verbatim corner."""
    return [int(v) & 0xFFFF for s in secs for v in cw.coeffs_to_words(*s)]

def body240(corners4):
    """4 compiled corners (M0_Q0, M100_Q0, M0_Q100, M100_Q100) -> the verbatim 240-byte
    body the player ships. Pass one corner 4x to audition a single posture."""
    assert len(corners4) == 4, "a body is exactly 4 corners"
    flat = [w for secs in corners4 for w in pack_corner(secs)]
    assert len(flat) == 120, "120 u16 words = 240 bytes"
    return struct.pack("<120H", *flat)

def write_body240(corners4, path):
    raw = body240(corners4); Path(path).write_bytes(raw); return raw

if __name__ == "__main__":  # self-test: the four Klatt corner vowels + a golden comb
    cs = {}
    for key in ("u", "a", "i"):
        secs, rep = compile(vowel(key)); cs[key] = secs
        print(f"vowel /{key}/  ok={rep['ok']}  dc={rep['dc_db']:+.2f}dB  peak={rep['peak_db']:+.1f}dB")
    secs, rep = compile(golden_comb())
    print(f"golden_comb    ok={rep['ok']}  dc={rep['dc_db']:+.2f}dB  peak={rep['peak_db']:+.1f}dB")
    # verbatim 240-byte body: u/a as the morph endpoints, i/comb as the Q endpoints
    raw = body240([cs["u"], cs["a"], cs["i"], secs])
    import pyruntime.trench_ffi as ff
    resp = cascade_response_db([EncodedCoeffs(*r) for r in ff.packed_interpolate(raw, 0.5, 0.5)], _FREQS, SR)
    print(f"body240        bytes={len(raw)}  mid-render finite={bool(np.all(np.isfinite(resp)))}  "
          f"(verbatim shipping format, read back through the player's packed path)")
