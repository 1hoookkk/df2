#!/usr/bin/env python3
"""p2k_family_notes — generate grounded, machine-readable P2K family reverse-
engineering notes. EVERY per-preset number is MEASURED from ref/presets/*.bin
through the shipped engine; family taxonomy + aggregate bounds come from the
clean-room x3_p2k_family_browser contracts. Study-only; no bytes shipped.

    python tools/p2k_family_notes.py   ->  P2K_FAMILY_REVERSE_ENGINEERING.md
"""
from __future__ import annotations

import glob
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pyruntime import trench_ffi                      # noqa: E402
from pyruntime.packed_interp import kernel_to_biquad  # noqa: E402

SR = 39062.5
FREQS = np.logspace(math.log10(60.0), math.log10(16000.0), 400)
W = 2 * np.pi * FREQS / SR
Z1 = np.exp(-1j * W); Z2 = Z1 * Z1
PRESETS = ROOT / "ref" / "presets"
CONTRACTS = ROOT / "dev" / "tmp" / "x3_p2k_family_browser" / "contracts"
SUFFIX_FAMILY = {"lpf": "slope_ladder", "hpf": "slope_ladder", "bpf": "bandpass_swept_eq",
                 "eq": "bandpass_swept_eq", "pha": "phaser_comb", "flg": "phaser_comb",
                 "vow": "vocal_formant"}


def mag(body, m, q):
    h = np.ones_like(Z1)
    for r in trench_ffi.packed_interpolate(body, m, q):
        b0, b1, b2, a1, a2 = kernel_to_biquad(r)
        h = h * ((b0 + b1 * Z1 + b2 * Z2) / (1 + a1 * Z1 + a2 * Z2))
    return 20 * np.log10(np.maximum(np.abs(h), 1e-9))


def rms(a):
    return float(np.sqrt(np.mean(a ** 2)))


def measure(body):
    corners = [mag(body, 0, 0), mag(body, 1, 0), mag(body, 0, 1), mag(body, 1, 1)]
    # renderable through the packed-morph engine? (fixed-class blocks read silent/overflow)
    renderable = all(-120.0 < c.max() < 60.0 for c in corners)
    if not renderable:
        return dict(packed_renderable=False, note="fixed-class format — not a packed-morph body; not measurable through this engine")
    m00, m10, m01, m11 = corners
    morph_motion = 0.5 * (rms(m01 - m11) + rms(m00 - m10))       # how far it travels across Morph
    q_pressure = 0.5 * (rms(m00 - m01) + rms(m10 - m11))         # how hard Q reshapes it
    rows = trench_ffi.packed_interpolate(body, 0.0, 1.0)
    nz, poles = 0, []
    for r in rows:
        b0, b1, b2, a1, a2 = kernel_to_biquad(r)
        if abs(b1) + abs(b2) > 1e-6:
            nz += 1
        rp = math.sqrt(max(0.0, a2))
        if rp > 1e-6:
            poles.append(math.acos(max(-1, min(1, -a1 / (2 * rp)))) * SR / (2 * math.pi))
    maxr = max(float(trench_ffi.packed_probe(body, m / 8.0, q / 8.0)["max_pole_radius"])
               for q in range(9) for m in range(9))
    return dict(packed_renderable=True, morph_motion_db=round(morph_motion, 2), q_pressure_db=round(q_pressure, 2),
                active_zeros=nz, pole_lo_hz=round(min(poles)) if poles else None,
                pole_hi_hz=round(max(poles)) if poles else None, max_pole_r=round(maxr, 4))


def main():
    fams = {}
    for cf in sorted(CONTRACTS.glob("*.json")):
        d = json.loads(cf.read_text(encoding="utf-8"))
        fams[d["family"]] = d
    id_family = {}
    for fam, d in fams.items():
        for vid in d.get("p2k_verbs", []):
            num = int(re.match(r"P2k_(\d+)", vid).group(1))
            id_family.setdefault(num, []).append(fam)

    presets = []
    for f in sorted(PRESETS.glob("P2k_*.bin")):
        m = re.match(r"P2k_(\d+)_(.+)", f.stem)
        num, name = int(m.group(1)), m.group(2)
        suffix = name.rsplit("_", 1)[-1]
        fam_list = ([SUFFIX_FAMILY[suffix]] if suffix in SUFFIX_FAMILY else []) + id_family.get(num, [])
        fam_list = list(dict.fromkeys(fam_list)) or ["unclassified"]
        klass = "functional" if num >= 33 else "designer"
        presets.append({"id": f"P2k_{num:03d}", "name": name.replace("_", " "), "class": klass,
                        "families": fam_list, **measure(f.read_bytes())})

    # medians — measured only over packed-renderable bodies; functional baseline from contracts
    def med(rows, key):
        v = sorted(r[key] for r in rows if r.get(key) is not None)
        return round(v[len(v) // 2], 2) if v else None
    def cmed(fn):
        v = sorted(x for x in (fn(d) for d in fams.values()) if isinstance(x, (int, float)))
        return round(v[len(v) // 2], 2) if v else None
    renderable = [p for p in presets if p.get("packed_renderable")]
    desg = [p for p in renderable if p["class"] == "designer"]
    n_func_renderable = sum(1 for p in presets if p["class"] == "functional" and p.get("packed_renderable"))
    contract_morph = {"functional": cmed(lambda d: d["aggregate_metrics"].get("x3_median_morph_motion_rms_db")),
                      "designer": cmed(lambda d: d["aggregate_metrics"].get("p2k_median_morph_motion_rms_db"))}
    contract_q = {"functional": cmed(lambda d: d["aggregate_metrics"].get("x3_median_q_pressure_rms_db")),
                  "designer": cmed(lambda d: d["aggregate_metrics"].get("p2k_median_q_pressure_rms_db"))}
    data = {
        "format": "p2k-family-reverse-engineering-v1",
        "clean_room": "Study-only. No coefficients, bytes, names, or presets shipped to product.",
        "provenance": "Per-preset metrics MEASURED from ref/presets/*.bin via trench_core; families + bounds from x3_p2k_family_browser contracts.",
        "sample_rate_hz": SR,
        "format_finding": {
            "claim": "Designer and functional presets are DIFFERENT FORMATS, not just different motion.",
            "designer_P2k_000_032": "packed-morph 4-corner bodies — render through trench_core (measured here).",
            "functional_P2k_033_049": "fixed-class parametric blocks — read silent/overflow through the packed-morph engine; NOT measurable through trench_core.",
            "functional_renderable_count": n_func_renderable,
        },
        "key_finding": {
            "claim": "Functional 'noun' types and designer 'verb' presets are the SAME 5 families; iconic = far more MOTION + Q-pressure.",
            "source": "x3_p2k_family_browser contracts (validated; functional baseline from X3 analysis since the functional .bin do not render here)",
            "median_morph_motion_db": contract_morph,
            "median_q_pressure_db": contract_q,
            "measured_designer_corroboration_db": {"morph_motion": med(desg, "morph_motion_db"),
                                                   "q_pressure": med(desg, "q_pressure_db"),
                                                   "note": "measured from the 33 packed-morph designer .bin via trench_core; our band/methodology, corroborates direction"},
        },
        "families": {fam: {
            "title": d["title"], "intent": d.get("intent"), "contract_bias": d.get("contract_bias"),
            "x3_functional_nouns": d.get("x3_nouns") or d.get("x3_scored"),
            "median_morph_motion_db": {"functional": d["aggregate_metrics"].get("x3_median_morph_motion_rms_db"),
                                       "designer": d["aggregate_metrics"].get("p2k_median_morph_motion_rms_db")},
            "median_q_pressure_db": {"functional": d["aggregate_metrics"].get("x3_median_q_pressure_rms_db"),
                                     "designer": d["aggregate_metrics"].get("p2k_median_q_pressure_rms_db")},
        } for fam, d in fams.items()},
        "presets": presets,
    }

    L = []
    L.append("# P2K Family Reverse-Engineering Notes\n")
    L.append("> **Clean-room: study only.** No coefficients/bytes/names shipped. Per-preset numbers are")
    L.append("> MEASURED from `ref/presets/*.bin` through the shipped `trench_core` engine; family taxonomy and")
    L.append("> aggregate bounds come from `dev/tmp/x3_p2k_family_browser/` contracts. Generated by `tools/p2k_family_notes.py`.\n")
    ff = data["format_finding"]; kf = data["key_finding"]
    L.append("## Finding 1 — two different FORMATS\n")
    L.append(f"- **Designer `P2k_000–032`** = packed-morph 4-corner bodies. They render through `trench_core`")
    L.append(f"  (measured below). This is the *Morph Designer* format — the same one the forge authors.")
    L.append(f"- **Functional `P2k_033–049`** = **fixed-class parametric blocks** (2/4/6-pole LP/HP/BP, swept EQ,")
    L.append(f"  phaser, flanger, vowel). Through the packed engine they read **silent (−180 dB) or overflow (+227 dB)**")
    L.append(f"  — they are NOT packed-morph bodies. ({ff['functional_renderable_count']}/17 rendered.) Their metrics")
    L.append(f"  below come from the X3 reverse-engineering, not this engine.\n")
    L.append("## Finding 2 — iconic = MOTION (the number)\n")
    L.append(f"The functional **noun** types and the designer **verb** presets are the **same 5 families**. The")
    L.append(f"difference is **motion**, and it is large *(source: {kf['source']})*:\n")
    L.append(f"- median **morph-motion**: functional **{kf['median_morph_motion_db']['functional']} dB RMS** → designer **{kf['median_morph_motion_db']['designer']} dB RMS**")
    L.append(f"- median **Q-pressure**: functional **{kf['median_q_pressure_db']['functional']} dB RMS** → designer **{kf['median_q_pressure_db']['designer']} dB RMS**")
    mc = kf["measured_designer_corroboration_db"]
    L.append(f"- *(corroboration — the 33 packed designer .bin measured here through `trench_core`: morph-motion median **{mc['morph_motion']} dB**, Q-pressure **{mc['q_pressure']} dB**)*\n")
    L.append("**Iconic = same family, the actor travels far harder and Q exposes notches harder.** A behavioral")
    L.append("target as a number — not a copied coefficient.\n")
    L.append("## Families\n")
    for fam, fd in data["families"].items():
        mm, qp = fd["median_morph_motion_db"], fd["median_q_pressure_db"]
        L.append(f"### {fd['title']}  (`{fam}`)")
        L.append(f"- **intent:** {fd['intent']}")
        L.append(f"- **contract bias:** {fd['contract_bias']}")
        L.append(f"- **functional nouns (X3 menu):** {', '.join(fd['x3_functional_nouns'] or []) or '—'}")
        L.append(f"- **morph-motion:** func `{mm['functional']}` -> designer `{mm['designer']}` dB RMS")
        L.append(f"- **Q-pressure:** func `{qp['functional']}` -> designer `{qp['designer']}` dB RMS")
        mem = [p for p in presets if fam in p["families"]]
        L.append(f"- **members ({len(mem)}):** " + ", ".join(f"`{p['id']}` {p['name']}" for p in mem) + "\n")
    L.append("## Per-preset measurements\n")
    L.append("Designer (`000–032`) measured through `trench_core`. Functional (`033–049`) are fixed-class — not measurable here.\n")
    L.append("| id | name | class | family | morph-motion dB | Q-pressure dB | zeros | poles Hz | maxR |")
    L.append("|----|------|-------|--------|----------------:|--------------:|------:|----------|-----:|")
    for p in presets:
        if p.get("packed_renderable"):
            L.append(f"| {p['id']} | {p['name']} | {p['class']} | {p['families'][0]} | {p['morph_motion_db']} | "
                     f"{p['q_pressure_db']} | {p['active_zeros']} | {p['pole_lo_hz']}–{p['pole_hi_hz']} | {p['max_pole_r']} |")
        else:
            L.append(f"| {p['id']} | {p['name']} | {p['class']} | {p['families'][0]} | _fixed-class_ | _fixed-class_ | — | — | — |")
    L.append("\n## Machine-readable data\n")
    L.append("```json")
    L.append(json.dumps(data, ensure_ascii=False, indent=1))
    L.append("```")

    out = ROOT / "P2K_FAMILY_REVERSE_ENGINEERING.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out}  ({len(presets)} presets, {len(fams)} families)")
    print(f"morph-motion median: functional {kf['median_morph_motion_db']['functional']} -> designer {kf['median_morph_motion_db']['designer']} dB")


if __name__ == "__main__":
    main()
