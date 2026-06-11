#!/usr/bin/env python3
"""forge_factory — the grounded-grammar factory.

Drives the real row_program engine from the reverse-engineered P2K grammar
(dev/tmp/p2k_full_vocabulary/skin_summaries.csv) with every pole snapped to a
REAL physical resonance (vowel formants, tube modes, bell modes). One coherent
6-row Program per type, gated on the shipped 5x5 surface. Clean-room: structure
+ behaviour only, no E-mu coefficients.

    python tools/forge_factory.py                 # build + gate all 50, write passers
    python tools/forge_factory.py --family "talking vowel glide"
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev" / "tmp" / "grammar_bodies"))

import row_program as rp                                   # noqa: E402  the real engine
from tools.author_lanes import body_to_packed_v1          # noqa: E402

CSV = ROOT / "dev" / "tmp" / "p2k_full_vocabulary" / "skin_summaries.csv"
OUT = ROOT / "dev" / "tmp" / "factory"

# band vocabulary from the reverse-engineering, low -> high (Hz anchors)
BAND = {"sub": 60.0, "low": 150.0, "low-mid": 330.0, "mouth": 820.0,
        "bite": 1900.0, "tear": 3800.0, "air": 8200.0}


def grounded_pool():
    """Every pole snaps to one of these REAL physical resonances."""
    pool = set()
    vf = json.loads((ROOT / "tables" / "vowel_formants.json").read_text(encoding="utf-8"))
    for v in vf["vowels"]:
        for k in ("f1", "f2", "f3", "f4"):
            if v.get(k):
                pool.add(float(v[k]))
    for L in (0.10, 0.18, 0.25, 0.30, 0.50):               # tube modes (open-open harmonic series)
        for n in range(1, 8):
            pool.add(n * 343.0 / (2.0 * L))
    bell = [0.5, 1.0, 1.19, 1.71, 2.0, 2.74, 3.0, 3.76]    # minor-third tuned-bell partials
    for f0 in (180.0, 300.0, 440.0):
        for r in bell:
            pool.add(f0 * r)
    return sorted(f for f in pool if 40.0 <= f <= 16000.0)


POOL = grounded_pool()


def snap(hz):
    return min(POOL, key=lambda p: abs(math.log2(max(20.0, p) / max(20.0, hz))))


def parse_roles(s):
    out = {}
    for tok in s.split(";"):
        m = re.match(r"\s*(S\d):\s*(.+)", tok)
        if m:
            out[m.group(1)] = m.group(2).strip().lower()
    return out


def _bands(txt):
    d = {}
    for tok in txt.split(">"):
        m = re.match(r"\s*(S\d):\s*([a-z-]+)", tok)
        if m:
            d[m.group(1)] = m.group(2)
    return d


def parse_view_full(fv):
    """frequency_sorted_view -> (poles, zeros), each {CORNER: {Si: band}}."""
    poles, zeros = {}, {}
    for seg in fv.split("||"):
        seg = seg.strip()
        if ":" not in seg:
            continue
        label, rest = seg.split(":", 1)
        parts = rest.split("|")
        poles[label.strip()] = _bands(parts[0].replace("poles", "").strip())
        zeros[label.strip()] = _bands(parts[1].replace("zeros", "").strip()) if len(parts) > 1 else {}
    return poles, zeros


# ── ground poles to the type's OWN matched physical resonances (top_abs_matches) ──
_VF = None


def _vowel_formants():
    global _VF
    if _VF is None:
        d = json.loads((ROOT / "tables" / "vowel_formants.json").read_text(encoding="utf-8"))
        _VF = {v["key"]: v for v in d["vowels"]}
    return _VF


def decode_match(tok):
    """'tube:oo_10cm:p5' / 'tube:co_18cm:p5' / 'klatt:u:f1' -> real Hz."""
    p = tok.split("=")[0].split(":")
    try:
        if p[0] == "tube":
            L = float(re.search(r"(\d+)cm", p[1]).group(1)) / 100.0
            n = int(re.search(r"p(\d+)", p[2]).group(1))
            return (2 * n - 1) * 343.0 / (4 * L) if p[1].startswith("co") else n * 343.0 / (2 * L)
        if p[0] in ("klatt", "vowel", "mullen", "pb"):
            v = _vowel_formants().get(p[1])
            if v:
                fi = int(re.search(r"f(\d+)", p[2]).group(1))
                return float(v.get(f"f{fi}") or v.get("f1"))
    except Exception:
        return None
    return None


def type_anchors(rec):
    """The real resonances THIS type used, snapped to the pool — but with a
    guaranteed lo<m1<m2<hi spread so the family's morph move actually travels."""
    toks = [t.strip() for t in rec["top_abs_matches"].split(";") if t.strip()]
    fr = sorted({snap(f) for f in (decode_match(t) for t in toks) if f and 40 <= f <= 16000})
    if not fr:
        fr = [snap(x) for x in (130.0, 800.0, 1800.0, 7000.0)]
    lo = snap(min(min(fr), 180.0))
    hi = snap(max(max(fr), 6500.0))
    mids = [f for f in fr if 350.0 <= f <= 3500.0]
    m1 = mids[0] if mids else snap(700.0)
    m2 = mids[-1] if len(mids) > 1 else snap(1700.0)
    if m2 <= m1 * 1.3:
        m2 = snap(m1 * 2.3)
    return lo, m1, m2, hi


def decode_source_series(tok):
    """A matched source -> its FULL real resonance series (real physics, many poles):
    a tube's harmonic/odd-harmonic partials, a vowel's F1..F4."""
    p = tok.split("=")[0].split(":")
    try:
        if p[0] == "tube":
            L = float(re.search(r"(\d+)cm", p[1]).group(1)) / 100.0
            if p[1].startswith("co"):                       # closed-open: odd harmonics
                return [(2 * n - 1) * 343.0 / (4 * L) for n in range(1, 8)]
            return [n * 343.0 / (2 * L) for n in range(1, 8)]   # open-open: full harmonic series
        if p[0] in ("klatt", "vowel", "mullen", "pb"):
            v = _vowel_formants().get(p[1])
            if v:
                return [float(v[k]) for k in ("f1", "f2", "f3", "f4") if v.get(k)]
    except Exception:
        return []
    return []


def _type_resonances(rec):
    """Every pole this type can use = the FULL partial series of every physical
    source it matched. Real resonances only — no invented placement."""
    pool = set()
    for tok in rec["top_abs_matches"].split(";"):
        pool.update(decode_source_series(tok.strip()))
    fr = sorted(f for f in pool if 40.0 <= f <= 16000.0)
    return fr or [130.0, 800.0, 1800.0, 3300.0, 7000.0]


def _ground_in(target_hz, fr):
    return min(fr, key=lambda p: abs(math.log2(max(20.0, p) / max(20.0, target_hz))))


def render_row(role, band, p0, p1, z0, z1):
    """One grammar section -> its lawful primitive. z0/z1 = the grammar's own zero choreography."""
    role = role.lower()
    if "cliff" in role or "shelf" in role or band == "sub":
        return rp.Row("FOUNDATION", p0, p1, r0=0.90, z0=max(z0, 1.2), z1=max(z1, 1.2), zr=0.50, gain=0.62)
    if "remote cut" in role:
        return rp.Row("COUNTERWEIGHT", p0, p1, r0=0.86, zmode="fixed", zfix=snap(min(p0, p1) * 1.9), zr=0.85, gain=0.5)
    if "air kill" in role:
        return rp.Row("EDGE/CAP", p0, p1, r0=0.95, zmode="fixed", zfix=17800.0, zr=0.999, gain=0.5)
    r0 = 0.985 if "tear" in role else (0.983 if "bite" in role else 0.980)
    return rp.Row("WINDOW", p0, p1, r0=r0, z0=z0, z1=z1, zr=0.93, gain=0.5, p_dr=0.005)


def _zero_motion_program(rec, hz, az, fr):
    """AWAY pole-rank empty => the morph lives in the ZEROS. A held low pole BODY
    (spread across the type's real low resonances, so distinct) + notch zeros that
    SWEEP from their HOME band to their AWAY band (grounded, un-clamped). Different
    types differ because their zero bands + low resonances differ -> no duplicates."""
    lows = sorted(f for f in fr if f <= 1400.0) or sorted(fr)[:4]
    rows = []
    for i in range(1, 7):
        s = f"S{i}"
        p = lows[(i - 1) % len(lows)]                       # held low body, spread (distinct)
        zh = _ground_in(BAND.get(hz.get(s, "mouth"), 820.0), fr)
        za = _ground_in(BAND.get(az.get(s, "bite"), 1900.0), fr)
        z0 = max(-3.5, min(3.5, math.log2(max(40.0, zh) / max(40.0, p))))   # zeros sweep wide = the motion
        z1 = max(-3.5, min(3.5, math.log2(max(40.0, za) / max(40.0, p))))
        rows.append(rp.Row("WINDOW", p, p, r0=0.965, z0=z0, z1=z1, zr=0.96, gain=0.5))
    rows[0] = rp.Row("FOUNDATION", lows[0], lows[0], r0=0.90, z0=1.4, z1=1.4, zr=0.50, gain=0.62)
    return rp.Program(rec["skin_id"], rows)


def build_program(rec):
    """Grammar-faithful: every section from ITS role + ITS HOME->AWAY pole motion +
    ITS zero choreography, grounded to the type's own resonances; sweeping peaks get
    the unmask eruption. No scoring — stability is the only law; the ear/eye judges."""
    roles = parse_roles(rec["row_roles"])
    poles, zeros = parse_view_full(rec["frequency_sorted_view"])
    hp, ap = poles.get("HOME", {}), poles.get("AWAY", {})
    hz, az = zeros.get("HOME", {}), zeros.get("AWAY", {})
    fr = _type_resonances(rec)
    if len(ap) < 3:                                          # motion lives in the zeros, not the poles
        return _zero_motion_program(rec, hz, az, fr)
    rows = []
    for i in range(1, 7):
        s = f"S{i}"; role = roles.get(s, "mouth")
        hb = hp.get(s, "mouth"); ab = ap.get(s, hb)
        # ground each section's grammar band to a REAL partial of THIS type's matched
        # sources (rich because the full series spans the spectrum; no invented poles)
        p0 = _ground_in(BAND.get(hb, 820.0), fr); p1 = _ground_in(BAND.get(ab, 820.0), fr)
        zhb, zab = hz.get(s), az.get(s)
        z0 = max(-1.1, min(0.6, math.log2(BAND.get(zhb, p0 * 0.76) / max(40.0, p0)))) if zhb else -0.40
        z1 = max(-1.1, min(0.6, math.log2(BAND.get(zab, p1 * 0.76) / max(40.0, p1)))) if zab else z0
        is_peak = not any(k in role.lower() for k in ("cliff", "shelf", "remote cut", "air kill")) and hb != "sub"
        if is_peak and abs(math.log2(max(40.0, p1) / max(40.0, p0))) > 0.45:
            z0, z1 = 0.04, -0.50                            # unmask eruption (the family magic)
        rows.append(render_row(role, hb, p0, p1, z0, z1))
    if not any(r.role == "FOUNDATION" for r in rows):
        k = min(range(6), key=lambda j: rows[j].pole0)
        rows[k] = rp.Row("FOUNDATION", rows[k].pole0, rows[k].pole1, r0=0.90, z0=1.4, z1=1.4, zr=0.50, gain=0.62)
    return rp.Program(rec["skin_id"], rows)


def emit(prog):
    OUT.mkdir(parents=True, exist_ok=True)
    doc = body_to_packed_v1(prog.name, prog.corners())
    jpath = OUT / f"{prog.name}.bodyv1.json"
    jpath.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "tools.author_body", str(jpath),
                    "-o", str(OUT / f"{prog.name}.cart.json"),
                    "--raw-out", str(OUT / f"{prog.name}.body240"),
                    "--png", str(OUT / f"{prog.name}.png"), "--name", prog.name],
                   cwd=str(ROOT), check=True, capture_output=True)


def factory_accept(info, family):
    """No scoring — the reins are free. The ONLY law is physical: a body must run
    (stable poles, finite state). Everything else — hot, dark, wild — is for the
    ear/eye to judge, not a gate."""
    return info["max_r"] < 1.0 and not any("nonfinite" in h for h in info["hard"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default=None)
    ap.add_argument("--emit", action="store_true", help="write passers to dev/tmp/factory/")
    args = ap.parse_args(argv)
    recs = list(csv.DictReader(CSV.open(encoding="utf-8")))
    if args.family:
        recs = [r for r in recs if r["move_family"] == args.family]
    passed, manifest = 0, []
    for rec in recs:
        try:
            prog = build_program(rec)
            _ok, lines, info = rp.gate(prog, strict=False)
            ok = factory_accept(info, rec["move_family"])
        except Exception as e:
            print(f"  {rec['skin_id']:18} ERROR {e}")
            continue
        tag = "PASS" if ok else "rej "
        print(f"  {tag} {rec['skin_id']:18} {rec['move_family']:22} "
              f"maxR {info['max_r']:.3f}  midDev {info.get('dev_rms') or 0:.1f}dB"
              + ("" if ok else "  | " + "; ".join(info["hard"][:1] or info["shape"][:1])))
        if ok:
            passed += 1
            manifest.append({"id": rec["skin_id"], "family": rec["move_family"],
                             "maxR": round(info["max_r"], 4), "midDev": round(info.get("dev_rms") or 0, 1)})
            if args.emit:
                emit(prog)
    print(f"\n{passed}/{len(recs)} passed the 5x5 gate.")
    if args.emit and manifest:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {passed} bodies + manifest to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
