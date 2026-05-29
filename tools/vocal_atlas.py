#!/usr/bin/env python3
"""Vocal-filter atlas — analysis only.

Decodes every usable vocal reference in dev/tmp/vocal_filter_roundup into a
per-row pole/zero/gain table, clusters pole frequencies in log2 space inside
three separated buckets (ROM/reference · local authored · source/physics vowel),
and writes a vocabulary + anchor grid for fitting and manual nudging.

Reads only. Writes only to dev/tmp/vocal_filter_atlas/. Authors nothing, ships
nothing, copies no ROM coefficients into bodies, touches no runtime.

  python tools/vocal_atlas.py
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(REPO, "dev", "tmp", "vocal_filter_roundup")
OUT = os.path.join(REPO, "dev", "tmp", "vocal_filter_atlas")
SR = 39062.5  # authoring rate (10 MHz / 256)

sys.path.insert(0, REPO)  # so `pyruntime` resolves as a package (script dir != cwd)

# ── minifloat decode (single owner) ──────────────────────────────────────────
try:
    from pyruntime.packed_interp import decode as _decode  # type: ignore
except Exception:  # pragma: no cover - fallback mirror of minifloat.rs

    def _decode(word: int) -> float:
        u = (word & 0xFFFF) + 1
        if u == 65536:
            return 1.0
        if u == 1:
            return 0.0
        e = (u >> 12) & 0xF
        m = u & 0xFFF
        x = m / 4096.0 if e == 0 else (m + 4096.0) / 8192.0
        return x * (2.0 ** (e - 15))


COMBINE_K = 4.0


def words_to_kernel(w):
    """5 packed u16 words -> kernel-form [c0..c4] (minifloat.rs stage_words_to_kernel)."""
    d = [_decode(int(x)) for x in w]
    return [
        COMBINE_K * d[0] + d[1],
        d[1],
        COMBINE_K * d[2] + d[3],
        d[3],
        COMBINE_K * d[4],
    ]


def kernel_to_biquad(c):
    """kernel [c0..c4] -> DF2T [b0,b1,b2,a1,a2] (denominator 1 + a1 z^-1 + a2 z^-2)."""
    c0, c1, c2, c3, c4 = c
    return [c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3]


def is_passthrough_kernel(c, eps=1e-6):
    return (
        abs(c[0] - 2.0) < eps
        and abs(c[1] - 1.0) < eps
        and abs(c[2] - 2.0) < eps
        and abs(c[3] - 1.0) < eps
        and abs(c[4] - 1.0) < eps
    )


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def pole_from_den(a1, a2, sr=SR, plus_conv=False):
    """Pole (freq_hz, radius, bw_hz, kind) from denominator coeffs.

    plus_conv=False : df2 convention  1 + a1 z^-1 + a2 z^-2  (cos = -a1/2r)
    plus_conv=True  : external/EOS    1 - a1 z^-1 + a2 z^-2  (cos = +a1/2r)
    """
    if not (math.isfinite(a1) and math.isfinite(a2)):
        return (None, float("nan"), float("nan"), "nonfinite")
    disc = a1 * a1 - 4.0 * a2
    r = max(a2, 0.0) ** 0.5
    if disc < 0.0 and r > 1e-9:  # complex conjugate pair -> resonance
        c = (a1 if plus_conv else -a1) / (2.0 * r)
        theta = math.acos(_clamp(c, -1.0, 1.0))
        freq = theta * sr / (2.0 * math.pi)
        bw = -sr / math.pi * math.log(min(r, 0.999999)) if r > 0 else float("inf")
        return (freq, r, bw, "complex")
    # real poles: no single resonant frequency
    sq = abs(disc) ** 0.5
    r1 = abs((-a1 + sq) / 2.0)
    r2 = abs((-a1 - sq) / 2.0)
    return (None, max(r1, r2), float("nan"), "real")


def zero_from_num(b0, b1, b2):
    """Zero (freq_hz, radius, kind). Returns (None,..,'none') when ~no zero."""
    if abs(b0) < 1e-12:
        return (None, float("nan"), "none")
    n1, n2 = b1 / b0, b2 / b0
    if abs(n1) < 0.02 and abs(n2) < 0.02:
        return (None, 0.0, "none")
    if abs(n2) < 1e-9:  # single real zero at z = -n1
        rz = abs(n1)
        # a real zero near +/-1 still shapes the band edge; report freq as 0/Nyq
        freq = 0.0 if n1 > 0 else SR / 2.0
        return (freq, min(rz, 4.0), "real")
    disc = n1 * n1 - 4.0 * n2
    rz = max(n2, 0.0) ** 0.5
    if disc < 0.0 and rz > 1e-9:
        theta = math.acos(_clamp(-n1 / (2.0 * rz), -1.0, 1.0))
        return (theta * SR / (2.0 * math.pi), rz, "complex")
    return (None, rz, "real")


def cascade_peak_db(corner_kernels, sr=SR):
    """Series-product peak magnitude (dB) over the band. (Approx for PARALLEL.)"""
    peak = 1e-12
    for i in range(120):
        f = 30.0 * (16000.0 / 30.0) ** (i / 119.0)
        w = 2.0 * math.pi * f / sr
        mag = 1.0
        for c in corner_kernels:
            b0, b1, b2, a1, a2 = kernel_to_biquad(c)
            cw, c2w, sw, s2w = math.cos(w), math.cos(2 * w), math.sin(w), math.sin(2 * w)
            nr = b0 + b1 * cw + b2 * c2w
            ni = -b1 * sw - b2 * s2w
            dr = 1.0 + a1 * cw + a2 * c2w
            di = -a1 * sw - a2 * s2w
            mag *= ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)) ** 0.5
        peak = max(peak, mag)
    return 20.0 * math.log10(peak + 1e-12)


# ── row record ────────────────────────────────────────────────────────────────
ROWS = []  # each: dict with bucket/body/corner/row + pole/zero/gain


def add_corner(bucket, body, corner_label, kernels, source_file, parallel=False, plus_conv=False):
    """Append one corner's active stages as rows."""
    active = [c for c in kernels if not is_passthrough_kernel(c)]
    peak_db = cascade_peak_db(active) if (active and not parallel) else float("nan")
    for ri, c in enumerate(kernels):
        if is_passthrough_kernel(c):
            continue
        b0, b1, b2, a1, a2 = kernel_to_biquad(c)
        pf, pr, pbw, pkind = pole_from_den(a1, a2, plus_conv=plus_conv)
        zf, zr, zkind = zero_from_num(b0, b1, b2)
        ROWS.append(
            dict(
                bucket=bucket,
                body=body,
                corner=corner_label,
                row=ri,
                pole_hz=pf,
                pole_r=pr,
                pole_bw_hz=pbw,
                pole_kind=pkind,
                zero_hz=zf,
                zero_r=zr,
                zero_kind=zkind,
                gain_b0=b0,
                corner_peak_db=peak_db,
                parallel=parallel,
                source_file=source_file,
            )
        )


def biquad_to_kernel(b0, b1, b2, a1, a2):
    """[b0,b1,b2,a1,a2] -> kernel [c0..c4] (inverse of kernel_to_biquad)."""
    if abs(b0) < 1e-12:
        return [2.0, 1.0, 2.0, 1.0, 1.0]
    return [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0]


# ── loaders ────────────────────────────────────────────────────────────────────
def _stage_kernel_from_obj(s):
    if isinstance(s, dict) and "c0" in s:
        return [s["c0"], s["c1"], s["c2"], s["c3"], s["c4"]]
    if isinstance(s, (list, tuple)) and len(s) == 5:
        return list(s)
    return None


def load_compiled_json(path, bucket, body):
    """compiled-v1 cartridge: per keyframe (corner), prefer packedWords, else stages.
    Collapses files whose keyframes are all identical (single-corner .corner.json)."""
    d = json.load(open(path, encoding="utf-8"))
    kfs = d.get("keyframes", [])
    corners = []
    for kf in kfs:
        label = kf.get("label", "?")
        pw = kf.get("packedWords")
        if pw:
            kernels = [words_to_kernel(w) for w in pw]
        else:
            kernels = [_stage_kernel_from_obj(s) for s in kf.get("stages", [])]
            kernels = [k for k in kernels if k]
        corners.append((label, kernels))
    # collapse identical keyframes (single-corner export)
    uniq = {json.dumps([[round(x, 6) for x in k] for k in kn]) for _, kn in corners}
    if len(uniq) == 1 and len(corners) > 1:
        corners = [(corners[0][0].split("_")[0] + " (single)", corners[0][1])]
    for label, kernels in corners:
        add_corner(bucket, body, label, kernels, os.path.relpath(path, REPO))


def load_kernels_json(path, bucket, body):
    """{'corners': [[[5]*6]*4]} kernel form."""
    d = json.load(open(path, encoding="utf-8"))
    labels = ["M0_Q0", "M0_Q100", "M100_Q0", "M100_Q100"]
    for ci, corner in enumerate(d["corners"]):
        kernels = [list(s) for s in corner]
        add_corner(bucket, body, labels[ci] if ci < 4 else f"C{ci}", kernels, os.path.relpath(path, REPO))


def load_body240(path, bucket, body):
    raw = open(path, "rb").read()
    assert len(raw) == 240, f"{path} not 240 bytes"
    words = []
    for i in range(0, 240, 2):
        words.append(raw[i] | (raw[i + 1] << 8))
    labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]  # body240 corner-major order
    idx = 0
    for ci in range(4):
        kernels = []
        for _si in range(6):
            kernels.append(words_to_kernel(words[idx : idx + 5]))
            idx += 5
        add_corner(bucket, body, labels[ci], kernels, os.path.relpath(path, REPO))


_HDR_ROW = re.compile(r"\{\s*([+\-0-9.eEf, ]+)\}")


def load_rom_header(path, bucket, body, plus_conv):
    """C header of BiquadCoeffs {b0,b1,b2,a1,a2}; arrays kQ100_m0.. = Morph frames."""
    txt = open(path, encoding="utf-8", errors="replace").read()
    # split into named arrays
    blocks = re.split(r"constexpr\s+BiquadCoeffs\s+(k[A-Za-z0-9_]+)\[\]\s*=\s*\{", txt)
    # blocks: [pre, name1, body1, name2, body2, ...]
    for i in range(1, len(blocks), 2):
        name = blocks[i]
        body_txt = blocks[i + 1].split("};")[0]
        rows = _HDR_ROW.findall(body_txt)
        kernels = []
        for r in rows:
            vals = [float(v.replace("f", "")) for v in r.split(",") if v.strip()]
            if len(vals) != 5:
                continue
            b0, b1, b2, a1, a2 = vals
            kernels.append(biquad_to_kernel(b0, b1, b2, a1, a2))
        if kernels:
            add_corner(bucket, body, name, kernels, os.path.relpath(path, REPO), parallel=True, plus_conv=plus_conv)


def load_heritage_xml(path, bucket, body):
    from pyruntime import designer_compile as dc  # noqa: E402
    from pyruntime.corner import CornerName  # noqa: E402

    labels = {0: "M0_Q0", 1: "M0_Q100", 2: "M100_Q0", 3: "M100_Q100"}
    t = dc.parse_xml(path)
    ca = dc.compile_designer(t, boost=4.0)
    for nm in [CornerName.A, CornerName.B, CornerName.C, CornerName.D]:
        enc = ca.corner(nm).encode()
        kernels = [[e.c0, e.c1, e.c2, e.c3, e.c4] for e in enc]
        add_corner(bucket, body, labels[nm.value], kernels, os.path.relpath(path, REPO))


# ── convention detection for ROM headers ────────────────────────────────────────
def detect_header_convention(path):
    """Pick the denominator sign convention that lands the most poles in the
    sensible audio band [120, 0.45*SR] for this header. Returns (plus_conv, score)."""
    txt = open(path, encoding="utf-8", errors="replace").read()
    rows = _HDR_ROW.findall(txt)
    in_band = {False: 0, True: 0}
    tot = 0
    for r in rows:
        vals = [float(v.replace("f", "")) for v in r.split(",") if v.strip()]
        if len(vals) != 5:
            continue
        _, _, _, a1, a2 = vals
        tot += 1
        for conv in (False, True):
            f, _r, _bw, kind = pole_from_den(a1, a2, plus_conv=conv)
            if kind == "complex" and f is not None and 120.0 <= f <= 0.45 * SR:
                in_band[conv] += 1
    return (in_band[True] >= in_band[False], in_band, tot)


# ── 1-D log2 clustering (pure-python weighted k-means) ───────────────────────────
def cluster_log2(freqs, k):
    xs = sorted(math.log2(f) for f in freqs if f and f > 0)
    if not xs:
        return []
    k = min(k, len(set(round(x, 3) for x in xs)))
    if k <= 0:
        return []
    # seed at quantiles
    cents = [xs[int((j + 0.5) / k * len(xs))] for j in range(k)]
    for _ in range(60):
        groups = [[] for _ in range(k)]
        for x in xs:
            j = min(range(k), key=lambda j: abs(x - cents[j]))
            groups[j].append(x)
        newc = []
        for j in range(k):
            newc.append(sum(groups[j]) / len(groups[j]) if groups[j] else cents[j])
        if max(abs(a - b) for a, b in zip(cents, newc)) < 1e-6:
            cents = newc
            break
        cents = newc
    out = []
    for j in range(k):
        g = groups[j]
        if not g:
            continue
        out.append(
            dict(
                center_hz=2.0 ** (sum(g) / len(g)),
                lo_hz=2.0 ** min(g),
                hi_hz=2.0 ** max(g),
                count=len(g),
            )
        )
    out.sort(key=lambda c: c["center_hz"])
    return out


def pct(vals, p):
    vals = sorted(v for v in vals if v is not None and math.isfinite(v))
    if not vals:
        return float("nan")
    i = _clamp(int(round(p / 100.0 * (len(vals) - 1))), 0, len(vals) - 1)
    return vals[i]


# ── morph / Q motion (within a body that has registered corners) ─────────────────
def body_corner_freqs(body):
    """{corner_label: sorted [(freq,radius)] of complex poles} for one body."""
    out = {}
    for r in ROWS:
        if r["body"] != body or r["pole_kind"] != "complex" or not r["pole_hz"]:
            continue
        out.setdefault(r["corner"], []).append((r["pole_hz"], r["pole_r"]))
    for k in out:
        out[k].sort()
    return out


def main():
    os.makedirs(OUT, exist_ok=True)

    # ── ROM / reference bucket ──
    rr = os.path.join(IN, "reference_rom")
    load_body240(os.path.join(rr, "talking_hedz.bin"), "rom", "talking_hedz")
    load_compiled_json(os.path.join(rr, "00_talking_hedz_compiled.json"), "rom", "P2k_013")
    load_kernels_json(os.path.join(rr, "P2k_003.kernels.json"), "rom", "P2k_003")
    # (skipped duplicates: 00_talking_hedz.json + P2k_003.json are raw a1/r twins;
    #  talking_hedz_*.corner.json are kernel exports of talking_hedz.bin)

    hdr_conv = {}
    for fn in sorted(os.listdir(os.path.join(IN, "rom_headers"))):
        if not fn.endswith(".h"):
            continue
        p = os.path.join(IN, "rom_headers", fn)
        plus, counts, tot = detect_header_convention(p)
        hdr_conv[fn] = dict(plus_conv=plus, in_band=counts, total=tot)
        load_rom_header(p, "rom", fn[:-2], plus)

    for fn in sorted(os.listdir(os.path.join(IN, "heritage_xml"))):
        if fn.endswith(".xml"):
            try:
                load_heritage_xml(os.path.join(IN, "heritage_xml", fn), "rom", "heritage:" + fn[:-4])
            except Exception as e:
                print(f"  heritage parse failed {fn}: {e}")

    # ── local authored bucket ──
    bdir = os.path.join(IN, "bodies")
    for fn in sorted(os.listdir(bdir)):
        if fn.endswith(".cart.json"):
            try:
                load_compiled_json(os.path.join(bdir, fn), "local", fn[:-10])
            except Exception as e:
                print(f"  body parse failed {fn}: {e}")
    # (skipped: *.packed.toml and small_talk.toml — the .cart.json twins carry the
    #  authoritative packedWords / decoded stages already)

    # ── source / physics vowel bucket ──
    pc = os.path.join(IN, "source_material", "physics_corners")
    for fn in sorted(os.listdir(pc)):
        if fn.endswith(".corner.json"):
            load_compiled_json(os.path.join(pc, fn), "physics", fn[:-12])

    # ── write CSV ──
    csv_path = os.path.join(OUT, "vocal_pole_zero_atlas.csv")
    cols = [
        "bucket", "body", "corner", "row", "pole_hz", "pole_r", "pole_bw_hz",
        "pole_kind", "zero_hz", "zero_r", "zero_kind", "gain_b0",
        "corner_peak_db", "parallel", "source_file",
    ]
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(",".join(cols) + "\n")
        for r in ROWS:
            def fmt(v):
                if v is None:
                    return ""
                if isinstance(v, float):
                    return "" if not math.isfinite(v) else f"{v:.4f}"
                return str(v)
            f.write(",".join(fmt(r[c]) for c in cols) + "\n")

    # ── per-bucket stats + clusters ──
    buckets = ["rom", "local", "physics"]
    bstats = {}
    for b in buckets:
        rows = [r for r in ROWS if r["bucket"] == b]
        cplx = [r for r in rows if r["pole_kind"] == "complex" and r["pole_hz"]]
        freqs = [r["pole_hz"] for r in cplx]
        radii = [r["pole_r"] for r in cplx]
        zoff = [
            math.log2(r["zero_hz"] / r["pole_hz"])
            for r in cplx
            if r["zero_kind"] == "complex" and r["zero_hz"] and r["pole_hz"]
        ]
        bstats[b] = dict(
            n_rows=len(rows),
            n_complex=len(cplx),
            clusters=cluster_log2(freqs, 6),
            r_p10=pct(radii, 10),
            r_p50=pct(radii, 50),
            r_p90=pct(radii, 90),
            r_min=min(radii) if radii else float("nan"),
            r_max=max(radii) if radii else float("nan"),
            zero_frac=sum(1 for r in cplx if r["zero_kind"] != "none") / max(1, len(cplx)),
            zoff_p10=pct(zoff, 10),
            zoff_p50=pct(zoff, 50),
            zoff_p90=pct(zoff, 90),
        )

    # ── morph & Q motion (bodies with multiple corners) ──
    morph_moves = []  # octaves |f(M100_Q0)/f(M0_Q0)| per registered row
    q_dr = []  # radius delta M0_Q100 - M0_Q0 per registered row
    motion_by_body = {}
    bodies = sorted({r["body"] for r in ROWS})
    for body in bodies:
        cf = body_corner_freqs(body)

        def reg(a, b):
            if a not in cf or b not in cf:
                return None
            n = min(len(cf[a]), len(cf[b]))
            return [(cf[a][i], cf[b][i]) for i in range(n)]

        mm = reg("M0_Q0", "M100_Q0")
        qq = reg("M0_Q0", "M0_Q100")
        rec = {}
        if mm:
            mv = [abs(math.log2(b[0] / a[0])) for a, b in mm if a[0] > 0 and b[0] > 0]
            if mv:
                rec["morph_oct_median"] = round(sorted(mv)[len(mv) // 2], 3)
                rec["morph_oct_max"] = round(max(mv), 3)
                morph_moves.extend(mv)
        if qq:
            dr = [b[1] - a[1] for a, b in qq]
            if dr:
                rec["q_dradius_median"] = round(sorted(dr)[len(dr) // 2], 4)
                q_dr.extend(dr)
        if rec:
            motion_by_body[body] = rec

    # ── anchor grid (named actor regions from the ROM bucket) ──
    # canonical vocal anchor regions (user's roundup vocabulary) cross-checked
    # against the measured ROM clusters.
    REGIONS = [
        ("sub", 30, 150, "chest weight / body floor"),
        ("F1_throat", 150, 950, "F1 — throat / jaw opening"),
        ("F2_vowel", 700, 2500, "F2 — tongue front/back (the vowel identity)"),
        ("F3_bite", 1800, 3600, "F3 — face / presence / bite"),
        ("F4_edge", 3000, 5200, "F4 — edge"),
        ("air", 5000, 12000, "air / sheen / breath"),
    ]
    rom_cplx = [r for r in ROWS if r["bucket"] == "rom" and r["pole_kind"] == "complex" and r["pole_hz"]]
    anchors = []
    for name, lo, hi, role in REGIONS:
        sel = [r for r in rom_cplx if lo <= r["pole_hz"] < hi]
        fs = [r["pole_hz"] for r in sel]
        rs = [r["pole_r"] for r in sel]
        anchors.append(
            dict(
                name=name,
                role=role,
                search_lo_hz=lo,
                search_hi_hz=hi,
                rom_count=len(sel),
                freq_p10=round(pct(fs, 10), 1) if fs else None,
                freq_typical=round(pct(fs, 50), 1) if fs else None,
                freq_p90=round(pct(fs, 90), 1) if fs else None,
                radius_p10=round(pct(rs, 10), 4) if rs else None,
                radius_typical=round(pct(rs, 50), 4) if rs else None,
                radius_p90=round(pct(rs, 90), 4) if rs else None,
            )
        )

    def r_to_bw(r):
        return None if not (r and 0 < r < 1) else round(-SR / math.pi * math.log(r), 1)

    grid = dict(
        what="Vocal anchor grid — log-frequency named-actor regions + radius/Q/zero "
        "vocabulary for Forge fitting and manual nudging. Analysis only; not a body.",
        authoring_rate_hz=SR,
        radius_bandwidth_note="r = exp(-pi*bw/sr); at 39062.5 Hz a 100 Hz formant ≈ "
        "r 0.992, a 60 Hz formant ≈ r 0.995, a 12 Hz whistle ≈ r 0.999.",
        anchors=anchors,
        radius_ranges_by_bucket={
            b: dict(
                p10=round(bstats[b]["r_p10"], 4),
                p50=round(bstats[b]["r_p50"], 4),
                p90=round(bstats[b]["r_p90"], 4),
                bw_p10_hz=r_to_bw(bstats[b]["r_p10"]),
                bw_p50_hz=r_to_bw(bstats[b]["r_p50"]),
                bw_p90_hz=r_to_bw(bstats[b]["r_p90"]),
            )
            for b in buckets
        },
        zero_offset_octaves_above_pole=dict(
            rom_p10=round(bstats["rom"]["zoff_p10"], 3),
            rom_p50=round(bstats["rom"]["zoff_p50"], 3),
            rom_p90=round(bstats["rom"]["zoff_p90"], 3),
            rom_fraction_of_poles_with_zero=round(bstats["rom"]["zero_frac"], 3),
        ),
        morph_pole_motion_octaves=dict(
            median=round(sorted(morph_moves)[len(morph_moves) // 2], 3) if morph_moves else None,
            p90=round(pct(morph_moves, 90), 3) if morph_moves else None,
            max=round(max(morph_moves), 3) if morph_moves else None,
            n_rows=len(morph_moves),
        ),
        q_radius_delta=dict(
            median=round(sorted(q_dr)[len(q_dr) // 2], 4) if q_dr else None,
            p90=round(pct(q_dr, 90), 4) if q_dr else None,
            n_rows=len(q_dr),
            note="M0_Q100 minus M0_Q0 pole radius per registered row (positive = Q tightens).",
        ),
        header_convention=hdr_conv,
        buckets={b: {k: v for k, v in bstats[b].items() if k != "clusters"} for b in buckets},
        clusters={b: bstats[b]["clusters"] for b in buckets},
    )
    json.dump(grid, open(os.path.join(OUT, "vocal_anchor_grid.json"), "w", encoding="utf-8"), indent=2)

    write_report(OUT, bstats, anchors, grid, motion_by_body, hdr_conv, morph_moves, q_dr)
    write_png(OUT, bstats)
    print(f"\nAtlas written -> {os.path.relpath(OUT, REPO)}")
    print(f"  rows: {len(ROWS)}  (rom {bstats['rom']['n_rows']} · local "
          f"{bstats['local']['n_rows']} · physics {bstats['physics']['n_rows']})")
    print(f"  complex poles: rom {bstats['rom']['n_complex']} · local "
          f"{bstats['local']['n_complex']} · physics {bstats['physics']['n_complex']}")


def write_report(out, bstats, anchors, grid, motion_by_body, hdr_conv, morph_moves, q_dr):
    L = []
    L.append("# Vocal-filter atlas — what real vocal filters actually do\n")
    L.append(
        "Decoded from `dev/tmp/vocal_filter_roundup` (analysis only — no bodies authored, "
        "no ROM coefficients copied into shipped bodies, no runtime changes). All "
        f"frequencies at the authoring rate **{SR:.1f} Hz**. Pole radius ↔ bandwidth: "
        "`r = exp(-pi·bw/sr)`, so a 100 Hz-wide formant is already `r ≈ 0.992` and a "
        "12 Hz whistle is `r ≈ 0.999` — high radii are normal, not impossible.\n"
    )
    L.append("## Buckets decoded\n")
    L.append("| bucket | rows | complex poles | what |")
    L.append("|---|---|---|---|")
    L.append(f"| ROM / reference | {bstats['rom']['n_rows']} | {bstats['rom']['n_complex']} | talking_hedz.bin, P2k_013, P2k_003, Vocal Ah-Ay-Ee / Oo-Ah ROM headers, heritage Vox/Wah XMLs |")
    L.append(f"| local authored | {bstats['local']['n_rows']} | {bstats['local']['n_complex']} | bodies/*.cart.json |")
    L.append(f"| source/physics vowel | {bstats['physics']['n_rows']} | {bstats['physics']['n_complex']} | physics_corners/vowel_*.corner.json |")
    L.append("")
    L.append(
        "> Source WAVs (`source_material/phonetic_*`) are raw audio, not filters — they "
        "carry no poles to decode and are excluded (they are fitting material).\n"
    )

    L.append("## 1. What frequency bands do real vocal filters use?\n")
    L.append("Pole-frequency clusters (log2 k-means), per bucket:\n")
    for b, title in [("rom", "ROM / reference"), ("physics", "physics vowel"), ("local", "local authored")]:
        cl = bstats[b]["clusters"]
        if not cl:
            continue
        L.append(f"**{title}** — " + " · ".join(
            f"{c['center_hz']:.0f} Hz ({c['lo_hz']:.0f}–{c['hi_hz']:.0f}, n={c['count']})" for c in cl
        ))
        L.append("")
    L.append(
        "The ROM/reference filters concentrate in the classic formant ladder: a low "
        "F1/throat region, an F2 vowel region, an F3 bite region, and a high air/sheen "
        "shelf — matching Peterson–Barney vowel formants, not a flat spread.\n"
    )

    L.append("## 2. What radius / Q ranges do they use?\n")
    L.append("| bucket | r p10 | r median | r p90 | r max | bw@median (Hz) |")
    L.append("|---|---|---|---|---|---|")
    for b in ["rom", "local", "physics"]:
        s = bstats[b]
        bw = "" if not (0 < s["r_p50"] < 1) else f"{-SR/math.pi*math.log(s['r_p50']):.0f}"
        L.append(f"| {b} | {s['r_p10']:.3f} | {s['r_p50']:.3f} | {s['r_p90']:.3f} | {s['r_max']:.3f} | {bw} |")
    L.append("")
    rr = bstats["rom"]
    bw10 = -SR / math.pi * math.log(rr["r_p10"]) if 0 < rr["r_p10"] < 1 else float("nan")
    bw50 = -SR / math.pi * math.log(rr["r_p50"]) if 0 < rr["r_p50"] < 1 else float("nan")
    L.append(
        f"The ROM reference is **Q100-heavy** (the explicit vocal headers are all Q100, the "
        f"P2k razor poles likewise), so its radius median sits right at the tight ceiling: "
        f"`r {rr['r_p50']:.3f}` (~{bw50:.0f} Hz bandwidth). The corridor runs from the broad "
        f"floor `r {rr['r_p10']:.3f}` (~{bw10:.0f} Hz) up to the tearing ceiling "
        f"`r {rr['r_p90']:.3f}`. Fitted *source* floors land lower (≈0.95–0.99); Q derivation "
        f"pushes up toward ~0.998. **Keep nudges inside `r 0.94 … 0.998`; past ~0.999 is "
        f"dead-whistle.** Radius is the design coordinate, not the packed word — "
        f"`target r → exp(-pi·bw/sr) → pack → audition`.\n"
    )

    L.append("## 3. Where do zeros sit relative to poles?\n")
    z = grid["zero_offset_octaves_above_pole"]
    L.append(
        f"- ROM poles carry a paired zero {z['rom_fraction_of_poles_with_zero']*100:.0f}% of "
        f"the time.\n"
        f"- When present, the zero sits **{z['rom_p50']:+.2f} octaves** from its pole "
        f"(p10 {z['rom_p10']:+.2f} … p90 {z['rom_p90']:+.2f}). "
        "Positive = above the pole (HF rolloff / bite); near-zero offset = a notch riding "
        "the resonance. The vocal convention in `small_talk` ('zero an octave above the "
        "formant') is consistent with this.\n"
    )

    L.append("## 4. How much do poles move across Morph?\n")
    mm = grid["morph_pole_motion_octaves"]
    if mm["median"] is not None:
        L.append(
            f"Across registered rows (M0_Q0 → M100_Q0): median **{mm['median']:.2f} oct**, "
            f"p90 {mm['p90']:.2f}, max {mm['max']:.2f} (n={mm['n_rows']}). "
            "Morph is mostly a *frequency slide* of the same skeleton (a vowel→vowel glide), "
            "not a wholesale re-spawn — which is why kin corners glide instead of mushing. "
            "(Rows are registered by sorted-frequency index; the large maxima are "
            "registration crossings where a corner has a different pole count — the **median** "
            "is the robust figure, ~a major sixth of F2/F3 travel.)\n"
        )
    per = [f"{b} M:{r.get('morph_oct_median','-')}oct / Qdr:{r.get('q_dradius_median','-')}" for b, r in sorted(motion_by_body.items()) if r]
    if per:
        L.append("Per body (morph octave median / Q radius Δ): " + " · ".join(per[:18]) + "\n")

    L.append("## 5. How much does radius change across Q?\n")
    qd = grid["q_radius_delta"]
    if qd["median"] is not None:
        L.append(
            f"Across registered rows (M0_Q0 → M0_Q100): median Δradius **{qd['median']:+.4f}**, "
            f"p90 {qd['p90']:+.4f} (n={qd['n_rows']}). The median is small and the *sign varies* "
            "by reference — some heritage corners actually loosen at Q100 (P2k_003's M100 row "
            "drops from r≈0.97 to r≈0.59). The robust, direction-free takeaway: **Q acts on "
            "radius/bandwidth, holding center frequency** — it is a radius axis, not a frequency "
            "axis. The references do not fix one tightening amount, so Q100 derivation is a "
            "design choice: push radius up the §2 corridor by ear.\n"
        )

    L.append("## 6. Which anchors should Forge expose for manual nudging?\n")
    L.append(
        "Named log-frequency actor regions, measured from the ROM bucket. These are the "
        "rows a fitter should *propose into* and a human should nudge between — `Slide` "
        "on the log grid, `Tighten`/`Loosen` within the radius corridor, `Bite` for the "
        "paired zero. (Values: measured ROM p10 / typical / p90; radius p10–p90.)\n"
    )
    L.append("| anchor | role | freq band (Hz) | ROM typical | radius corridor | ROM n |")
    L.append("|---|---|---|---|---|---|")
    for a in anchors:
        ft = "—" if a["freq_typical"] is None else f"{a['freq_typical']:.0f}"
        fb = f"{a['search_lo_hz']}–{a['search_hi_hz']}"
        rc = "—" if a["radius_typical"] is None else f"{a['radius_p10']}–{a['radius_p90']} (~{a['radius_typical']})"
        L.append(f"| {a['name']} | {a['role']} | {fb} | {ft} | {rc} | {a['rom_count']} |")
    L.append("")
    L.append(
        "**Fit floors, derive ceilings.** The atlas is the derivation table: fit M0_Q0 / "
        "M100_Q0 from real sources (anatomical truth), then derive the Q100 row by pushing "
        "radius up the corridor in §2 and the Morph row by sliding F2/F3 within §1 by the "
        "§4 amount — keeping the four corners kin. The design coordinate is "
        "**target pole frequency + radius → pack to words → audition**, never raw word pokes.\n"
    )

    L.append("## Appendix — ROM header coefficient convention\n")
    L.append(
        "The `rom_headers/*.h` are an external `rom_deep_scan` rip (`BiquadCoeffs "
        "{b0,b1,b2,a1,a2}`, PARALLEL banks). Their denominator sign was auto-detected per "
        "file by which convention lands poles in the audio band:\n"
    )
    for fn, c in hdr_conv.items():
        conv = "1 − a1·z⁻¹ + a2·z⁻² (cos=+a1/2r)" if c["plus_conv"] else "1 + a1·z⁻¹ + a2·z⁻² (cos=−a1/2r)"
        L.append(f"- `{fn}`: **{conv}** — in-band poles +conv {c['in_band'][True]} / −conv {c['in_band'][False]} of {c['total']}")
    L.append(
        "\nRadius (`√a2`) is convention-independent, so the Q/bandwidth findings hold "
        "regardless; only the header pole *frequencies* depend on this assumption.\n"
    )
    open(os.path.join(out, "vocal_atlas_report.md"), "w", encoding="utf-8").write("\n".join(L))


def write_png(out, bstats):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"  (matplotlib unavailable, skipping PNG: {e})")
        return
    colors = {"rom": "#5bef6f", "local": "#31c6c9", "physics": "#e8a33d"}
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 9), facecolor="#0a0d0c")
    for ax in (ax1, ax2):
        ax.set_facecolor("#0a0d0c")
        for s in ax.spines.values():
            s.set_color("#46534b")
        ax.tick_params(colors="#bec5be")
        ax.grid(True, color="#1c2722", lw=0.5)

    # panel 1: pole freq (log) vs radius, colored by bucket
    for b in ["rom", "local", "physics"]:
        xs = [r["pole_hz"] for r in ROWS if r["bucket"] == b and r["pole_kind"] == "complex" and r["pole_hz"]]
        ys = [r["pole_r"] for r in ROWS if r["bucket"] == b and r["pole_kind"] == "complex" and r["pole_hz"]]
        ax1.scatter(xs, ys, s=22, alpha=0.6, color=colors[b], label=f"{b} (n={len(xs)})", edgecolors="none")
    ax1.set_xscale("log")
    ax1.set_xlim(80, 16000)
    ax1.set_ylim(0.6, 1.001)
    ax1.set_xlabel("pole frequency (Hz, log)", color="#bec5be")
    ax1.set_ylabel("pole radius", color="#bec5be")
    ax1.set_title("Vocal pole/radius atlas — where vocal filters live", color="#5bef6f")
    # formant anchor bands
    for name, lo, hi in [("F1", 150, 950), ("F2", 700, 2500), ("F3", 1800, 3600), ("air", 5000, 12000)]:
        ax1.axvspan(lo, hi, color="#5bef6f", alpha=0.05)
        ax1.text((lo * hi) ** 0.5, 0.62, name, color="#69836f", ha="center", fontsize=8)
    ax1.legend(facecolor="#11150f", edgecolor="#46534b", labelcolor="#bec5be", fontsize=8)

    # panel 2: pole-frequency log-histogram per bucket
    import math as _m
    bins = [80 * (16000 / 80) ** (i / 48) for i in range(49)]
    for b in ["rom", "local", "physics"]:
        xs = [r["pole_hz"] for r in ROWS if r["bucket"] == b and r["pole_kind"] == "complex" and r["pole_hz"]]
        ax2.hist(xs, bins=bins, alpha=0.5, color=colors[b], label=b)
    ax2.set_xscale("log")
    ax2.set_xlim(80, 16000)
    ax2.set_xlabel("pole frequency (Hz, log)", color="#bec5be")
    ax2.set_ylabel("count", color="#bec5be")
    ax2.set_title("Pole-frequency density (the formant ladder)", color="#5bef6f")
    ax2.legend(facecolor="#11150f", edgecolor="#46534b", labelcolor="#bec5be", fontsize=8)

    fig.tight_layout()
    fig.savefig(os.path.join(out, "vocal_atlas.png"), dpi=110, facecolor="#0a0d0c")
    plt.close(fig)


if __name__ == "__main__":
    main()
