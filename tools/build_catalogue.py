"""Emit catalogue.json — the machine-readable build catalogue the compiler reads.

Indexes every input by ROLE (frame / recipe / voice_table / fundamental / wav_source)
with resolved paths + flags. Pointers only, no embedded ROM bytes/geometry (clean-room).
Frames are null-checked through trench-core; only nulling frames are marked verified.
Not a body designer — it maps what exists so the compiler can load it.
"""
from __future__ import annotations
import ctypes as C, struct, glob, os, json, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pyruntime.packed_interp import _packed_bilinear_reference, kernel_to_biquad, words_to_coeffs

DLL = os.path.join(ROOT, "target", "release", "trench_core.dll")
PAD = (0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000); SR = 39062.5
F = np.geomspace(30, 19000, 1000)
H = os.path.expanduser("~")

lib = C.CDLL(DLL)
lib.trench_packed_probe.restype = C.c_int32
lib.trench_packed_probe.argtypes = [C.c_char_p, C.c_size_t, C.c_double, C.c_double,
    C.POINTER(C.c_double), C.POINTER(C.c_double), C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]
PTS = [(0.,0.), (1.,0.), (0.,1.), (1.,1.), (0.5,0.5)]


def nulls(body):
    w = struct.unpack("<120H", body)
    cw = {k: [tuple(w[(c*6+s)*5:(c*6+s)*5+5]) for s in range(6)] for c, k in enumerate("ABCD")}
    for m, q in PTS:
        out = (C.c_double*30)(); mr = C.c_double(); um = C.c_uint32(); nm = C.c_uint32()
        lib.trench_packed_probe(body, 240, C.c_double(m), C.c_double(q), out, C.byref(mr), C.byref(um), C.byref(nm))
        ref = np.array([kernel_to_biquad(r) for r in _packed_bilinear_reference(cw, m, q)])
        if np.max(np.abs(np.array(out).reshape(6, 5) - ref)) > 1e-6:
            return False
    return True


def stage_split(body):
    """-> per-stage {role, band, slot} at corner A. slot: frame|voice."""
    w = struct.unpack("<120H", body); z = np.exp(-1j*2*np.pi*F/SR)
    stages = []
    for s in range(6):
        ww = w[(0*6+s)*5:(0*6+s)*5+5]
        if ww == PAD:
            stages.append({"role": "pad", "band": None, "slot": "frame"}); continue
        b0, b1, b2, a1, a2 = kernel_to_biquad(words_to_coeffs(ww))
        m = 20*np.log10(np.abs(b0+b1*z+b2*z*z)/np.abs(1+a1*z+a2*z*z)+1e-9); m -= np.median(m)
        p = np.roots([1, a1, a2]); ph = abs(np.angle(p[np.argmax(np.abs(p))]))/(2*np.pi)*SR
        notch = m.min() < -6 and m.min() < -m.max()
        role = "notch" if notch else ("dipole" if (m.max() > 6 and m.min() < -6) else ("peak" if m.max() > 1.5 else "flat"))
        band = "air" if ph >= 5000 else "body" if ph < 420 else "voice"
        slot = "voice" if role in ("peak", "dipole") and 420 <= ph < 5000 else "frame"
        stages.append({"role": role, "band": band, "slot": slot})
    return stages


FUND_NS = {"2_pole_lowpass":1,"4_pole_lowpass":2,"6_pole_lowpass":3,"2_pole_highpass":1,
  "4_pole_highpass":2,"2_pole_bandpass":1,"4_pole_bandpass":2,"contrary_bandpass":1,
  "swept_eq_1_octave":1,"swept_eq_2_1_octave":1,"swept_eq_3_1_octave":1,
  "phaser_1":2,"phaser_2":2,"bat_phaser":2,"flanger_lite":3,"vocal_ah_ay_ee":3,"vocal_oo_ah":3}


def _biq_char(bq):
    """(is_notch, is_dipole) for one biquad — 'cool' = has a zero doing work."""
    b0, b1, b2, a1, a2 = bq; z = np.exp(-1j*2*np.pi*F/SR)
    m = 20*np.log10(np.abs(b0+b1*z+b2*z*z)/np.abs(1+a1*z+a2*z*z)+1e-9); m -= np.median(m)
    return (m.min() < -6 and m.min() < -m.max()), (m.max() > 6 and m.min() < -6)


def sentinel_is_passthrough():
    bq = kernel_to_biquad(words_to_coeffs(PAD))
    z = np.exp(-1j*2*np.pi*F/SR)
    b0, b1, b2, a1, a2 = bq
    m = 20*np.log10(np.abs(b0+b1*z+b2*z*z)/np.abs(1+a1*z+a2*z*z)+1e-9)
    return float(np.max(np.abs(m)))  # ~0 dB => flat passthrough


def _block_type(stem):
    if "lowpass" in stem: return "lowpass"
    if "highpass" in stem: return "highpass"
    if "contrary" in stem: return "contrary_bandpass"
    if "bandpass" in stem: return "bandpass"
    if "swept_eq" in stem: return "peak_eq"
    if "phaser" in stem: return "phaser_notch"
    if "flanger" in stem: return "flanger_comb"
    if "vocal" in stem: return "formant"
    return "other"


def block_vocabulary():
    """ALL 17 fundamentals as blocks — a simple LP/HP/BP/EQ corner is a valid block."""
    out = []
    for stem, ns in FUND_NS.items():
        fp = rf"{H}\df2\ref\x3_menu\runtime_blocks\{stem}_48000.raw"
        if not os.path.exists(fp):
            continue
        out.append({"name": stem, "block": _block_type(stem), "real_biquads": ns})
    return out


def rel(p):
    return os.path.relpath(p, H).replace("\\", "/")


def frames():
    out = []
    for fp in sorted(glob.glob(rf"{H}\surface-forge\out\foundry\ROM_GOLD\P2k_*.body240")):
        body = open(fp, "rb").read()
        if len(body) != 240:
            continue
        sp = stage_split(body)
        out.append({
            "name": os.path.basename(fp)[:-8], "path": rel(fp), "source": "rom_gold",
            "verified_null": nulls(body),
            "real_biquads": sum(1 for s in sp if s["role"] != "pad"),
            "frame_stages": [i for i, s in enumerate(sp) if s["slot"] == "frame"],
            "voice_stages": [i for i, s in enumerate(sp) if s["slot"] == "voice"],
            "stages": sp,
        })
    return out


def globrel(pattern):
    return [rel(p) for p in sorted(glob.glob(pattern))]


cat = {
    "note": "Build catalogue for the frame+voice compiler. Pointers only (clean-room). "
            "Regenerate with tools/build_catalogue.py.",
    "laws": {
        "biquad_budget": 6,
        "sentinel_biquad": {"words": list(PAD), "role": "phantom passthrough — fills unused budget slots",
                            "max_abs_db": round(sentinel_is_passthrough(), 4)},
        "s5_notch": "stage 5 is a unit-circle notch in every ROM frame (mandatory)",
        "block_types": ["air", "body", "notch", "voice"],
    },
    "frames": frames(),
    "recipes": {
        "family_laws": globrel(rf"{H}\df2\recipes\laws\*.json"),
        "recipe_index": rel(rf"{H}\df2-workstation\recipe-index\recipe_index_v1.json"),
    },
    "voice_tables": {
        "formants": globrel(rf"{H}\df2-workstation\filters\tables\*formant*.json")
                    + globrel(rf"{H}\df2-workstation\filters\tables\klatt*.json"),
        "modes": globrel(rf"{H}\df2-workstation\filters\tables\*modes*.json"),
        "morph_fields": globrel(rf"{H}\df2-workstation\filters\tables\emu_*.json"),
        "modal_measured": rel(rf"{H}\trench-filters\data\modal"),
        "vowel_rails_dvtd": rel(rf"{H}\trench-filters\data\vocal\dvtd"),
        "hrtf": rel(rf"{H}\trench-filters\data\hrtf"),
    },
    "fundamentals": {
        "runtime_blocks": rel(rf"{H}\df2\ref\x3_menu\runtime_blocks"),
        "decoded_manifest": rel(rf"{H}\df2-workstation\filters\fundamentals\fundamentals_manifest.json"),
        "codec": "pyruntime.packed_interp (minifloat u16) — the ONLY correct decode",
        "blocks": block_vocabulary(),
    },
    "wav_sources": {
        "root": rel(rf"{H}\df2-workstation\wav-source-library"),
        "categories": [os.path.basename(d) for d in sorted(glob.glob(rf"{H}\df2-workstation\wav-source-library\*")) if os.path.isdir(d)],
    },
    "experimental_ignore": [
        "df2-workstation/dev", "df2-workstation/out/candidates_previous_*",
        "df2/dev/tmp", "df2/forge/target", "df2/experiments",
    ],
}

out = os.path.join(ROOT, "catalogue.json")
json.dump(cat, open(out, "w"), indent=2)
nfr = len(cat["frames"]); nver = sum(1 for f in cat["frames"] if f["verified_null"])
print(f"wrote {out}")
print(f"  biquad_budget: {cat['laws']['biquad_budget']}   sentinel flat to {cat['laws']['sentinel_biquad']['max_abs_db']} dB")
print(f"  frames: {nfr} ({nver} null-verified)  e.g. " + ", ".join(f"{f['name'][:14]}(real={f['real_biquads']})" for f in cat['frames'][:3]))
print(f"  block vocabulary: {len(cat['fundamentals']['blocks'])} fundamentals")
print(f"  family laws: {len(cat['recipes']['family_laws'])}")
print(f"  voice formant tables: {len(cat['voice_tables']['formants'])}, mode tables: {len(cat['voice_tables']['modes'])}")
print(f"  wav categories: {len(cat['wav_sources']['categories'])}")
