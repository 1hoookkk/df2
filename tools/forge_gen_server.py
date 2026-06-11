"""forge_gen_server — stdlib JSON API for the zedit generator toolbelt. No deps but numpy/scipy.
GET /ellip?ca=8000&cb=300        -> analog brick-wall sweep (elliptic), per corner
GET /vowel?va=ah&vb=ee           -> acoustic vocal tract (3 formant poles + valley notch zeros)
Each lane: {lane,pole_hz,pole_r,zero_hz,zero_r,gain}. The UI duplicates Q from morph by default.
Run:  python tools/forge_gen_server.py    (serves on 127.0.0.1:8131)
"""
import json, math, struct, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, unquote
import numpy as np
import scipy.signal as sig

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.author_lanes import biquad_to_kernel, lane_words  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words, kernel_to_biquad, words_to_coeffs  # noqa: E402

SR = 39062.5; NY = SR/2; MAXR = 0.985

# ---- RBJ bells vowel: low-shelf foundation + 5 flat-both-ends formant bells ----
# Every vowel from the canonical Peterson-Barney table (tables/vowel_formants.json);
# F4/F5 held at 3300/3850 Hz (Klatt 1980). Legacy aliases keep ah/ee/oo working.
def _load_vowels():
    d = json.loads((Path(__file__).resolve().parent.parent / "tables" / "vowel_formants.json").read_text(encoding="utf-8"))
    out = {}
    for v in d["vowels"]:
        out[v["key"]] = ([v["f1"], v["f2"], v["f3"], 3300, 3850],
                         [v.get("bw1", 60), v.get("bw2", 90), v.get("bw3", 150), 250, 200])
    return out


VOW = _load_vowels()
VOWEL_KEYS = list(VOW.keys())                       # the 10 canonical table vowels
for _alias, _key in (("ah", "aa"), ("ee", "iy"), ("oo", "uw")):
    if _key in VOW:
        VOW[_alias] = VOW[_key]
SHELF_HZ, SHELF_DB = 180.0, 14.0   # the bass body — held across morph/Q


def _rbj_peak(f, Q, gain_db):
    w = 2*math.pi*min(f, SR*0.49)/SR; A = 10**(gain_db/40); al = math.sin(w)/(2*Q)
    b0, b1, b2 = 1+al*A, -2*math.cos(w), 1-al*A
    a0, a1, a2 = 1+al/A, -2*math.cos(w), 1-al/A
    return b0/a0, b1/a0, b2/a0, a1/a0, a2/a0


def _rbj_lowshelf(f, gain_db, S=0.9):
    w = 2*math.pi*min(f, SR*0.49)/SR; A = 10**(gain_db/40); cw = math.cos(w); sq = math.sqrt(A)
    al = math.sin(w)/2*math.sqrt((A+1/A)*(1/S-1)+2)
    b0 = A*((A+1)-(A-1)*cw+2*sq*al); b1 = 2*A*((A-1)-(A+1)*cw); b2 = A*((A+1)-(A-1)*cw-2*sq*al)
    a0 = (A+1)+(A-1)*cw+2*sq*al; a1 = -2*((A-1)+(A+1)*cw); a2 = (A+1)+(A-1)*cw-2*sq*al
    return b0/a0, b1/a0, b2/a0, a1/a0, a2/a0


def _dc_flat(b0, b1, b2, a1, a2):
    num = b0+b1+b2; den = 1.0+a1+a2; s = (den/num) if abs(num) > 1e-12 else 1.0
    return b0*s, b1*s, b2*s, a1, a2


BODY_HZ, BODY_Q, BODY_DB = 150.0, 1.1, 13.0   # low resonant bell = the bass body ("low shelf peak")


FORMANT_DB = 8.0   # modest, fixed boost — Q does NOT change gain


def _vowel_words(vowel, q):
    F, BW = VOW.get(vowel, VOW["ah"])
    # lane 1 = low body bell (representable bass hump; a true shelf dies in the minifloat)
    rows = [coeffs_to_words(*biquad_to_kernel(*_dc_flat(*_rbj_peak(BODY_HZ, BODY_Q, BODY_DB))))]
    for i in range(5):
        natQ = F[i] / BW[i]
        bellQ = natQ * (0.4 + 1.4 * q)            # Q -> sharpness => pole radius climbs to the rim
        bq = _dc_flat(*_rbj_peak(F[i], bellQ, FORMANT_DB))   # fixed gain, no loudness pump
        rows.append(coeffs_to_words(*biquad_to_kernel(*bq)))
    return rows


def _p2w(p):                               # pole/zero/gain param dict -> packed 5 words
    wp = 2*math.pi*min(p["pole_hz"], SR*0.49)/SR; a1 = -2*p["pole_r"]*math.cos(wp); a2 = p["pole_r"]**2
    wz = 2*math.pi*min(p["zero_hz"], SR*0.49)/SR; g = p["gain"]
    b1 = -2*p["zero_r"]*math.cos(wz)*g; b2 = p["zero_r"]**2*g
    return coeffs_to_words(*biquad_to_kernel(g, b1, b2, a1, a2))


def _analog_words(cutoff, q):
    # resonant lowpass (cheby1): flat passband keeps bass, resonant edge sings at the cutoff.
    rp = 1.0 + 7.0*q                       # passband ripple = resonance; Q raises pole radii
    z, p, k = sig.cheby1(12, rp, min(cutoff, NY*0.49)/NY, btype="lowpass", analog=False, output="zpk")
    poles = sorted([c for c in p if c.imag >= 0], key=lambda x: np.angle(x))
    zeros = sorted([c for c in z if c.imag >= 0], key=lambda x: np.angle(x))
    rows = []
    for i in range(6):
        ph = float(np.angle(poles[i])*(SR/(2*np.pi))); pr = float(min(abs(poles[i]), MAXR))
        if i < len(zeros):
            zh = float(np.angle(zeros[i])*(SR/(2*np.pi))); zr = float(min(abs(zeros[i]), 0.9999))
        else:
            zh = NY*0.99; zr = 0.999
        rows.append({"pole_hz": max(20, ph), "pole_r": pr, "zero_hz": max(20, zh), "zero_r": zr, "gain": 1.0})
    _pin(rows, 50.0)                        # pin passband to 0 dB
    return [_p2w(p) for p in rows]


def _pack(corners):
    out = bytearray()
    for lab in ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"):
        for row in corners[lab]:
            for w in row:
                out += struct.pack("<H", int(w) & 0xFFFF)
    return out.hex()


def gen_analog_body_hex(ca, cb):
    return _pack({"M0_Q0": _analog_words(ca, 0), "M100_Q0": _analog_words(cb, 0),
                  "M0_Q100": _analog_words(ca, 1), "M100_Q100": _analog_words(cb, 1)})


def gen_vowel_body_hex(va, vb):
    corners = {"M0_Q0": _vowel_words(va, 0), "M100_Q0": _vowel_words(vb, 0),
               "M0_Q100": _vowel_words(va, 1), "M100_Q100": _vowel_words(vb, 1)}
    out = bytearray()
    for lab in ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"):
        for row in corners[lab]:
            for w in row:
                out += struct.pack("<H", int(w) & 0xFFFF)
    return out.hex()

# 3-formant view of the same table (used by gen_vowel).
VOWELS = {k: (F[:3], BW[:3]) for k, (F, BW) in VOW.items()}


def _mag(lanes, f):
    z = math.e ** (-1j*2*math.pi*f/SR); H = 1.0
    for l in lanes:
        wp = 2*math.pi*min(l["pole_hz"], NY*0.999)/SR
        a1, a2 = -2*l["pole_r"]*math.cos(wp), l["pole_r"]**2
        zr = l["zero_r"]
        if l["zero_hz"] and zr > 0:
            wz = 2*math.pi*min(l["zero_hz"], NY*0.999)/SR; b1, b2 = -2*zr*math.cos(wz), zr*zr
        else:
            b1 = b2 = 0.0
        g = l["gain"]; H *= (g + g*b1*z + g*b2*z*z)/(1 + a1*z + a2*z*z)
    return abs(H)


def _pin(lanes, f0, target_db=0.0):
    # global scalar to hit target at f0, distributed over all lanes (6th root) so each
    # per-lane gain stays inside the packer's [0.05, 4.0] range (no clamp -> pin holds).
    cur = max(1e-9, _mag(lanes, f0)); g = ((10**(target_db/20))/cur) ** (1.0/len(lanes))
    for l in lanes:
        l["gain"] = round(l["gain"] * g, 5)
    return lanes


def L(p_hz, p_r, z_hz, z_r, g=1.0):
    return {"pole_hz": round(max(20, p_hz), 2), "pole_r": round(min(p_r, MAXR), 4),
            "zero_hz": round(max(20, z_hz), 2), "zero_r": round(min(z_r, 0.9999), 4), "gain": round(g, 5)}


def gen_ellip(cutoff_hz, rp=1.0, rs=40.0):
    z, p, k = sig.ellip(12, rp, rs, cutoff_hz/NY, btype="lowpass", analog=False, output="zpk")
    poles = sorted([c for c in p if c.imag >= 0], key=lambda x: np.angle(x))
    zeros = sorted([c for c in z if c.imag >= 0], key=lambda x: np.angle(x))
    lanes = [L(np.angle(poles[i])*(SR/(2*np.pi)), abs(poles[i]),
              np.angle(zeros[i])*(SR/(2*np.pi)), abs(zeros[i])) for i in range(6)]
    return [dict(l, lane=i+1) for i, l in enumerate(_pin(lanes, 50.0))]


def gen_vowel(vowel):
    F, BW = VOWELS.get(vowel, VOWELS["ah"])
    r = [math.exp(-math.pi*BW[i]/SR) for i in range(3)]
    mid12, mid23 = math.sqrt(F[0]*F[1]), math.sqrt(F[1]*F[2])     # valley notches (r=1)
    lanes = [L(F[0], r[0], mid12, 0.999), L(F[1], r[1], mid23, 0.999), L(F[2], r[2], NY*0.99, 0.999),
             L(1000, 0.9, 1000, 0.9), L(1000, 0.9, 1000, 0.9), L(1000, 0.9, 1000, 0.9)]  # 3 flat fillers
    return [dict(l, lane=i+1) for i, l in enumerate(_pin(lanes, 60.0))]


# ---- frame quarry: grounded frames mined from real sources ----
# Clean-room: exclude _heritage / _reference / _rom (the protected P2K material).
QUARRY_ROOT = Path(__file__).resolve().parent.parent / "dev" / "tmp" / "arma_source_pack" / "corners_audio_only"
QUARRY_EXCLUDE = {"_heritage", "_reference", "_rom"}


def _kernel_to_param(c):
    """Decode one kernel row (c0..c4) to {pole/zero} params — mirrors zedit biquadToParams."""
    b0, b1, b2, a1, a2 = kernel_to_biquad(tuple(c))
    rp = math.sqrt(max(0.0, a2))
    cwp = max(-1.0, min(1.0, -a1 / (2 * rp))) if rp > 1e-6 else 1.0
    pole_hz = max(20.0, min(NY * 0.999, math.acos(cwp) * SR / (2 * math.pi)))
    zon, zhz, zr = 0, NY, 0.95
    if abs(b0) > 1e-9 and (abs(b1) > 1e-9 or abs(b2) > 1e-9):
        zr = math.sqrt(max(0.0, b2 / b0))
        sg = math.sqrt(max(1e-12, b0 * b2))
        zhz = max(20.0, min(NY * 0.999, math.acos(max(-1.0, min(1.0, -b1 / (2 * sg)))) * SR / (2 * math.pi)))
        zon = 1
    return {"pole_hz": round(pole_hz, 2), "pole_r": round(min(rp, 0.9999), 5),
            "zero_hz": round(zhz, 2), "zero_r": round(min(zr, 0.9999), 5),
            "gain": round(b0, 5), "zon": zon}


def _frame_from_corner_json(path, keyframe="M0_Q100"):
    d = json.loads(path.read_text())
    kfs = d.get("keyframes", [])
    kf = next((k for k in kfs if k.get("label") == keyframe), kfs[0] if kfs else None)
    if not kf:
        raise ValueError("no keyframes")
    rows = [[s["c0"], s["c1"], s["c2"], s["c3"], s["c4"]] for s in kf["stages"]]
    lanes = [_kernel_to_param(r) for r in rows]
    # verbatim packed words — the canonical representation; loaded directly so the
    # exact audited coeffs survive (param decode is lossy on baked-gain frames).
    words = [list(coeffs_to_words(*r)) for r in rows]
    return lanes, d.get("name", path.stem), words


def _centroid(lanes):
    fs = np.logspace(math.log10(60.0), math.log10(16000.0), 160)
    mags = np.array([_mag(lanes, float(f)) for f in fs])
    s = float(np.sum(mags))
    return float(np.sum(fs * mags) / s) if s > 1e-9 else 0.0


def gen_vowel_frames():
    """Every table vowel as a grounded frame (sharp Q100), so its formants are
    available as stage-fillers in the palette."""
    out = []
    for key in VOWEL_KEYS:
        words = [list(w) for w in _vowel_words(key, 1.0)]
        lanes = [_kernel_to_param(list(words_to_coeffs(w))) for w in words]
        out.append({"id": f"vowel_{key}", "name": f"vowel {key}", "src": "vowel",
                    "centroid": round(_centroid(lanes), 1), "lanes": lanes, "words": words})
    return out


def _all_frames():
    """Grounded frames: every vowel + every mined corner.json (clean-room excluded)."""
    frames = gen_vowel_frames()
    for p in sorted(QUARRY_ROOT.rglob("*.corner.json")):
        if any(part in QUARRY_EXCLUDE for part in p.parts):
            continue
        try:
            lanes, name, words = _frame_from_corner_json(p)
            frames.append({"id": p.stem, "name": name, "src": p.relative_to(QUARRY_ROOT).parts[0],
                           "centroid": round(_centroid(lanes), 1), "lanes": lanes, "words": words})
        except Exception:
            continue
    return frames


def gen_quarry():
    return sorted(_all_frames(), key=lambda x: x["centroid"])


SECTION_PEAK_DB = 12.0   # each standalone filler normalized to this peak — strong, consistent, not singular


def _norm_section_words(w):
    """Re-gain one section's words so its peak response = SECTION_PEAK_DB — a
    consistent, audible resonance when dropped in standalone (the frame's baked
    per-lane gain is calibrated for the 6-lane sum, not a single filler).
    Pole/zero geometry is untouched; only the numerator is scaled."""
    b0, b1, b2, a1, a2 = kernel_to_biquad(tuple(words_to_coeffs(w)))
    fs = np.logspace(math.log10(40.0), math.log10(17000.0), 400)
    z = np.exp(-1j * 2 * np.pi * fs / SR)
    peak = float(np.max(np.abs((b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z))))
    s = (10.0 ** (SECTION_PEAK_DB / 20.0)) / peak if peak > 1e-9 else 1.0
    nw = list(coeffs_to_words(*biquad_to_kernel(b0 * s, b1 * s, b2 * s, a1, a2)))
    return nw, _kernel_to_param(list(words_to_coeffs(nw)))


def gen_sections():
    """Flatten the grounded frames into individual sections (one pole+zero each)
    with normalized verbatim words — the stage-filler palette. Skips parked/flat
    filler lanes and dedupes near-identical resonances."""
    raw = []
    for fr in _all_frames():
        for i, (par0, w0) in enumerate(zip(fr["lanes"], fr["words"])):
            if par0["pole_hz"] > 15500 or par0["pole_r"] < 0.55:
                continue                         # parked / flat filler — not a real resonance
            w, par = _norm_section_words(w0)
            raw.append({"id": f"{fr['id']}_L{i}", "name": f"{fr['name']} · L{i}", "src": fr["src"],
                        "pole_hz": round(par["pole_hz"], 1), "pole_r": par["pole_r"],
                        "lane": par, "words": w})
    seen, uniq = set(), []
    for s in sorted(raw, key=lambda x: x["pole_hz"]):
        key = (round(s["pole_hz"] / 10.0), s["src"], round(s["pole_r"], 2))
        if key in seen:
            continue
        seen.add(key); uniq.append(s)
    return uniq


def gen_fit(path, name=None):
    """Fit a real recording into a grounded 6-section frame via the SHIPPED Rust
    ARMA factorizer (trench_core). Returns the frame + its sections (verbatim
    words), same shape as the quarry — so a fitted result drops into the same
    stage-filler palette and load path."""
    from pyruntime import trench_ffi                                  # lazy: DLL
    from tools.fit_two_audio_arma import load_mono, steady_slice      # canonical conditioning
    src = Path(path)
    sr, samples = load_mono(src)
    conditioned, meta = steady_slice(samples, sr)
    rows = [list(r) for r in trench_ffi.fit_corner_arma(conditioned, sr)]
    lanes = [_kernel_to_param(r) for r in rows]
    words = [list(coeffs_to_words(*r)) for r in rows]
    nm = name or src.stem
    sections = []
    for i, (par, w) in enumerate(zip(lanes, words)):
        if par["pole_hz"] > 15500 or par["pole_r"] < 0.55:
            continue
        sections.append({"id": f"fit_{src.stem}_L{i}", "name": f"{nm} · L{i}", "src": "fit",
                         "pole_hz": round(par["pole_hz"], 1), "pole_r": par["pole_r"], "lane": par, "words": w})
    return {"name": nm, "src": "fit", "lanes": lanes, "words": words,
            "centroid": round(_centroid(lanes), 1), "sections": sections,
            "meta": {"sample_rate_hz": sr, **meta}}


# ---- GRAMMAR generator: the P2K construction recipe as Hz-spectrum features ----
# Sub anchor (held low) + a MOUNTAIN that sweeps across Morph (Q drives its razor
# radius) + flanking CANYONS + a held EDGE cap. Decoded from the real P2k_003
# (Millennium) behaviour; built from frequencies only (no E-mu bytes).
def _grammar_lanes(mtn, fr, anchor_hz, cap_hz):
    c_lo = max(mtn * 0.5, 40.0)
    c_hi = min(mtn * 2.0, 17000.0)
    return [
        {"pole_hz": anchor_hz, "pole_r": 0.990, "zero_hz": 9000.0, "zero_r": 0.80, "gain": 0.5},  # SUB anchor (held)
        {"pole_hz": mtn, "pole_r": fr, "zero_hz": None, "zero_r": 0.0, "gain": 0.60},              # MOUNTAIN tip (Q-driven)
        {"pole_hz": mtn, "pole_r": 0.80, "zero_hz": None, "zero_r": 0.0, "gain": 0.40},            # MOUNTAIN base
        {"pole_hz": c_lo, "pole_r": 0.50, "zero_hz": c_lo, "zero_r": 0.996, "gain": 0.5},          # CANYON below
        {"pole_hz": c_hi, "pole_r": 0.50, "zero_hz": c_hi, "zero_r": 0.996, "gain": 0.5},          # CANYON above
        {"pole_hz": cap_hz, "pole_r": 0.90, "zero_hz": 17800.0, "zero_r": 0.999, "gain": 0.5},     # EDGE cap (held)
    ]


def gen_grammar_body(mtn_hi, mtn_lo, anchor_hz=70.0, cap_hz=12000.0, rest_r=0.88, razor_r=0.965):
    corners = {
        "M0_Q0":    [lane_words(l) for l in _grammar_lanes(mtn_hi, rest_r,  anchor_hz, cap_hz)],
        "M100_Q0":  [lane_words(l) for l in _grammar_lanes(mtn_lo, rest_r,  anchor_hz, cap_hz)],
        "M0_Q100":  [lane_words(l) for l in _grammar_lanes(mtn_hi, razor_r, anchor_hz, cap_hz)],
        "M100_Q100": [lane_words(l) for l in _grammar_lanes(mtn_lo, razor_r, anchor_hz, cap_hz)],
    }
    out = bytearray()
    for lab in ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"):
        for row in corners[lab]:
            for w in row:
                out += struct.pack("<H", int(w) & 0xFFFF)
    return out.hex()


# ---- GROUNDED grammar: the iconic structure, every pole a REAL disk resonance ----
# The grammar gives the skeleton (sub anchor · sweeping mountain · canyons · cap);
# every pole is snapped to the nearest real grounded resonance (vowel/tube/bell/fit).
# The morph travels the mountain between TWO real resonances. No invented poles.
_SECTIONS_CACHE = None


def _sections_cached():
    global _SECTIONS_CACHE
    if _SECTIONS_CACHE is None:
        _SECTIONS_CACHE = gen_sections()
    return _SECTIONS_CACHE


def _nearest(hz, lo=None, hi=None):
    secs = _sections_cached()
    pool = [s for s in secs if (lo is None or s["pole_hz"] >= lo) and (hi is None or s["pole_hz"] <= hi)] or secs
    return min(pool, key=lambda s: abs(math.log2(max(20.0, s["pole_hz"]) / max(20.0, hz))))


def _q_radius(pr, q01):
    """q01=0 -> broad, q01=1 -> the real resonance's own sharpness."""
    broad = max(0.5, min(pr, 1.0 - (1.0 - pr) * 4.0))
    return broad + (pr - broad) * q01


def _grounded_lanes(mtn, q01, anchor_hz, cap_hz, used):
    a = _nearest(anchor_hz, hi=260); m = _nearest(mtn); c = _nearest(cap_hz, lo=5000)
    used["anchor"] = (a["name"], round(a["pole_hz"]))
    used["mountain"] = (m["name"], round(m["pole_hz"]))
    used["cap"] = (c["name"], round(c["pole_hz"]))
    al, ml, cl = a["lane"], m["lane"], c["lane"]
    c_lo = max(mtn * 0.5, 40.0); c_hi = min(mtn * 2.0, 17000.0)
    def L(ph, pr, zh, zr, g):
        return {"pole_hz": ph, "pole_r": min(0.999, pr), "zero_hz": zh, "zero_r": zr, "gain": g}
    return [
        L(al["pole_hz"], _q_radius(min(al["pole_r"], 0.99), 0.4),
          al["zero_hz"] if al["zon"] else 9000.0, al["zero_r"] if al["zon"] else 0.80, 0.5),   # SUB anchor (grounded, held)
        L(ml["pole_hz"], _q_radius(ml["pole_r"], q01), None, 0.0, 0.60),                        # MOUNTAIN (grounded, Q-driven)
        L(ml["pole_hz"], _q_radius(min(ml["pole_r"], 0.90), 0.3), None, 0.0, 0.40),             # mountain base
        L(c_lo, 0.50, c_lo, 0.996, 0.5),                                                        # CANYON below (notch)
        L(c_hi, 0.50, c_hi, 0.996, 0.5),                                                        # CANYON above (notch)
        L(cl["pole_hz"], _q_radius(min(cl["pole_r"], 0.97), 0.5),
          cl["zero_hz"] if cl["zon"] else 17800.0, cl["zero_r"] if cl["zon"] else 0.999, 0.5),  # EDGE cap (grounded, held)
    ]


def gen_grounded_grammar(mtn_hi, mtn_lo, anchor_hz=70.0, cap_hz=12000.0):
    used = {}
    corners = {
        "M0_Q0":     [lane_words(l) for l in _grounded_lanes(mtn_hi, 0.0, anchor_hz, cap_hz, used)],
        "M100_Q0":   [lane_words(l) for l in _grounded_lanes(mtn_lo, 0.0, anchor_hz, cap_hz, used)],
        "M0_Q100":   [lane_words(l) for l in _grounded_lanes(mtn_hi, 1.0, anchor_hz, cap_hz, used)],
        "M100_Q100": [lane_words(l) for l in _grounded_lanes(mtn_lo, 1.0, anchor_hz, cap_hz, used)],
    }
    out = bytearray()
    for lab in ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"):
        for row in corners[lab]:
            for w in row:
                out += struct.pack("<H", int(w) & 0xFFFF)
    body = bytes(out)
    # audit through the shipped engine
    maxr = 0.0
    try:
        from pyruntime import trench_ffi
        for qi in range(5):
            for mi in range(5):
                pr = trench_ffi.packed_probe(body, mi / 4.0, qi / 4.0)
                maxr = max(maxr, float(pr["max_pole_radius"]))
    except Exception:
        maxr = -1.0
    grounded = sorted({round(s["pole_hz"], 1) for s in _sections_cached()})
    return {"body": body.hex(), "used": used, "maxR": round(maxr, 4), "grounded": grounded}


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/save":
            try:
                n = int(self.headers.get("Content-Length", 0))
                hexbody = self.rfile.read(n).decode().strip()
                body = bytes.fromhex(hexbody)
                if len(body) != 240:
                    return self._send({"error": f"expected 240 bytes, got {len(body)}"}, 400)
                name = q.get("name", ["keep"])[0]
                name = "".join(c for c in name if c.isalnum() or c in "_-")[:64] or "keep"
                d = Path(__file__).resolve().parent.parent/"dev"/"tmp"/"forge_keepers"
                d.mkdir(parents=True, exist_ok=True)
                p = d/f"{name}.body240"; p.write_bytes(body)
                self._send({"saved": str(p)})
            except Exception as e:
                self._send({"error": str(e)}, 500)
        else:
            self._send({"error": "unknown endpoint"}, 404)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        try:
            if u.path == "/ellip":
                ca = float(q.get("ca", ["6000"])[0]); cb = float(q.get("cb", ["400"])[0])
                self._send({"body": gen_analog_body_hex(ca, cb)})   # resonant sweep + body, not a dead lowpass
            elif u.path == "/vowel":
                va = q.get("va", ["ah"])[0]; vb = q.get("vb", ["ee"])[0]
                self._send({"body": gen_vowel_body_hex(va, vb)})   # RBJ bells, packed words
            elif u.path == "/quarry":
                self._send({"frames": gen_quarry()})
            elif u.path == "/sections":
                self._send({"sections": gen_sections()})
            elif u.path == "/grammar":
                mh = float(q.get("mtn_hi", ["9000"])[0]); ml = float(q.get("mtn_lo", ["450"])[0])
                an = float(q.get("anchor", ["70"])[0]); cap = float(q.get("cap", ["12000"])[0])
                self._send({"body": gen_grammar_body(mh, ml, an, cap),
                            "features": {"anchor": an, "mtn_hi": mh, "mtn_lo": ml, "cap": cap}})
            elif u.path == "/ground":
                mh = float(q.get("mtn_hi", ["9000"])[0]); ml = float(q.get("mtn_lo", ["450"])[0])
                an = float(q.get("anchor", ["70"])[0]); cap = float(q.get("cap", ["12000"])[0])
                self._send(gen_grounded_grammar(mh, ml, an, cap))
            elif u.path == "/factory":
                fac = Path(__file__).resolve().parent.parent / "dev" / "tmp" / "factory" / "manifest.json"
                self._send({"bodies": json.loads(fac.read_text()) if fac.exists() else []})
            elif u.path == "/factory_body":
                fid = "".join(c for c in q.get("id", [""])[0] if c.isalnum() or c in "_-")
                p = Path(__file__).resolve().parent.parent / "dev" / "tmp" / "factory" / f"{fid}.body240"
                if p.exists():
                    self._send({"body": p.read_bytes().hex()})
                else:
                    self._send({"error": f"not found: {fid}"}, 404)
            elif u.path == "/fit":
                path = unquote(q.get("path", [""])[0])
                if not path or not Path(path).exists():
                    return self._send({"error": f"file not found: {path}"}, 404)
                self._send(gen_fit(path, q.get("name", [None])[0]))
            elif u.path in ("/", "/health"):
                self._send({"ok": True, "endpoints": ["/ellip?ca=&cb=", "/vowel?va=&vb=", "/quarry"], "vowels": list(VOWELS)})
            else:
                self._send({"error": "unknown endpoint"}, 404)
        except Exception as e:
            self._send({"error": str(e)}, 500)

    def log_message(self, *a): pass


if __name__ == "__main__":
    print("forge_gen_server on http://127.0.0.1:8131  (/ellip , /vowel)")
    HTTPServer(("127.0.0.1", 8131), Handler).serve_forever()
