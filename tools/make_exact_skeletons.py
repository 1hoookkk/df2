"""Exact skeletons — closed-form optimal order-12 filters as forge seed material.

Three families with PROVABLY optimal magnitude properties at order 12:
  - butterworth: maximally flat passband (poles equally spaced on a circle)
  - cheby2:      equiripple stopband with exact unit-circle zeros
  - elliptic:    steepest possible transition for the order/ripple (Cauer) —
                 the mathematical maximum; nothing sharper exists at order 12

Each skeleton = the same design computed at TWO cutoffs (the low and high
morph frames), both on the 12-TET grid, so the morph sweep travels an exact
musical interval. Sections are conjugate pole pairs paired by frequency rank
(section index is the morph pairing); overall gain is split equally across
the six sections (products commute, so the split is exact).

Format projection (the honest part): pole r clamped to 0.9992, zero r to
0.9995 (elliptic/cheby2 zeros live ON the unit circle), frequencies clamped
to 30 Hz-16 kHz (Butterworth's Nyquist zeros land at the 16 kHz rail). The
self-check below measures exactly what that projection costs vs scipy's
unprojected reference and refuses to write a skeleton whose passband moves
more than 0.2 dB.

Output: tables/exact_skeletons.json (provenance embedded). Runtime truth is
still the painter's pack_body path — these are start states, not presets.
"""

import json
from pathlib import Path

import numpy as np
import scipy.signal as sig

ROOT = Path(r"C:\Users\hooki\df2")
SR = 39062.5
ORDER = 12
F_MIN, F_MAX = 30.0, 16000.0
RP_MAX = 0.9992
RZ_MAX = 0.9995
F_LO, F_HI = 220.0, 3520.0  # A3 -> A7: an exact four-octave travel

FAMILIES = [
    ("butterworth", "butterworth-12 sweep (maximally flat)",
     lambda wn: sig.butter(ORDER, wn, btype="low", output="zpk", fs=SR)),
    ("cheby2", "chebyshev-II-12 sweep (equiripple stopband, 60 dB)",
     lambda wn: sig.cheby2(ORDER, 60.0, wn, btype="low", output="zpk", fs=SR)),
    ("elliptic", "elliptic-12 sweep (optimal transition, 1/60 dB)",
     lambda wn: sig.ellip(ORDER, 1.0, 60.0, wn, btype="low", output="zpk", fs=SR)),
]


def pairs_by_freq(roots):
    """conjugate-pair representatives (imag >= 0), sorted by angle/frequency"""
    ups = [r for r in roots if np.imag(r) >= -1e-12]
    # real roots (e.g. Butterworth zeros at z=-1) arrive in even multiplicity:
    # each PAIR of real roots is one 'conjugate pair' at theta = pi (or 0)
    reals = sorted([r for r in ups if abs(np.imag(r)) <= 1e-12], key=np.real)
    cplx = [r for r in ups if np.imag(r) > 1e-12]
    merged = cplx + [complex(np.real(a), 0.0) for a in reals[::2]] + [
        complex(np.real(a), 0.0) for a in reals[1::2]
    ]
    merged.sort(key=lambda r: abs(np.angle(r)))
    return merged[: ORDER // 2]


def project(root, is_pole):
    """format projection: (freq Hz clamped, radius clamped, freq was railed)"""
    th = abs(np.angle(root))
    f_raw = th * SR / (2 * np.pi)
    f = float(np.clip(f_raw, F_MIN, F_MAX))
    r = float(np.clip(abs(root), 0.0, RP_MAX if is_pole else RZ_MAX))
    return f, r, abs(f - f_raw) > 0.01 * f_raw


def section_h(f_p, r_p, f_z, r_z, gain_db, freqs):
    w = 2 * np.pi * freqs / SR
    z = np.exp(1j * w)
    thp = 2 * np.pi * f_p / SR
    thz = 2 * np.pi * f_z / SR
    p = r_p * np.exp(1j * thp)
    q = r_z * np.exp(1j * thz)
    num = (1 - q / z) * (1 - np.conj(q) / z)
    den = (1 - p / z) * (1 - np.conj(p) / z)
    return 10 ** (gain_db / 20.0) * num / den


def build_frame(zpk):
    zeros, poles, k = zpk
    gain_db = 20.0 * np.log10(abs(k)) / (ORDER // 2)
    rows = []
    zp = pairs_by_freq(zeros)
    pp = pairs_by_freq(poles)
    railed = []
    for i, (pl, zr) in enumerate(zip(pp, zp)):
        fp, rp, _ = project(pl, True)
        fz, rz, z_railed = project(zr, False)
        rows.append({"pole_hz": fp, "pole_r": rp, "zero_hz": fz, "zero_r": rz, "gain_db": gain_db})
        if z_railed:
            railed.append(i)
    return rows, railed


def frame_response_db(rows, freqs):
    h = np.ones(len(freqs), dtype=complex)
    for r in rows:
        h *= section_h(r["pole_hz"], r["pole_r"], r["zero_hz"], r["zero_r"], r["gain_db"], freqs)
    return 20 * np.log10(np.maximum(np.abs(h), 1e-12))


def main():
    out = {"provenance": {
        "generated_by": "tools/make_exact_skeletons.py",
        "formulas": "scipy.signal butter/cheby2/ellip, order 12, bilinear, fs=39062.5",
        "cutoffs_hz": [F_LO, F_HI],
        "note_grid": "A3 -> A7 (exact four-octave morph travel)",
        "projection": {"pole_r_max": RP_MAX, "zero_r_max": RZ_MAX, "freq_hz": [F_MIN, F_MAX]},
        "gain_split": "20*log10(k)/6 per section (products commute; split exact)",
    }, "skeletons": []}

    freqs = np.geomspace(60.0, 16000.0, 600)
    for key, label, design in FAMILIES:
        skel = {"key": key, "label": label, "f_lo": F_LO, "f_hi": F_HI, "sections": []}
        ok = True
        for which, fc in (("lo", F_LO), ("hi", F_HI)):
            zpk = design(fc)
            rows, railed = build_frame(zpk)
            # self-check vs the unprojected scipy reference
            sos = sig.zpk2sos(*zpk)
            _, href = sig.sosfreqz(sos, worN=freqs, fs=SR)
            ref_db = 20 * np.log10(np.maximum(np.abs(href), 1e-12))
            pb = freqs <= fc * 0.85

            def trimmed_err(rows_):
                # level trim: restore the passband mean via the equal gain
                # split (flat in dB — leaves shape untouched), then measure
                m = frame_response_db(rows_, freqs)
                off = float(np.mean(ref_db[pb] - m[pb]))
                return off, float(np.max(np.abs(m[pb] + off - ref_db[pb])))

            # zeros railed to the 16 kHz format edge can't keep their exact
            # position — so project in RESPONSE space: their shared radius is
            # free, pick the one that minimizes passband error
            if railed:
                best = (None, np.inf)
                for r_try in np.linspace(0.30, RZ_MAX, 70):
                    for i in railed:
                        rows[i]["zero_r"] = float(r_try)
                    _, e = trimmed_err(rows)
                    if e < best[1]:
                        best = (float(r_try), e)
                for i in railed:
                    rows[i]["zero_r"] = best[0]
            offset, d_pass = trimmed_err(rows)
            for r in rows:
                r["gain_db"] += offset / (ORDER // 2)
            mine = frame_response_db(rows, freqs)
            # convert to the COMPILER's gain convention: trench_core's
            # stage_biquad DC-normalizes each section ((1+a1+a2)/(1+nb1+nb2)·g),
            # so the stored gain_db must be the section's value AT DC. The
            # conversion is exact — same section, different parameterization.
            for r in rows:
                dc = abs(section_h(r["pole_hz"], r["pole_r"], r["zero_hz"], r["zero_r"],
                                   r["gain_db"], np.array([1e-3])))[0]
                r["gain_db"] = float(20 * np.log10(max(dc, 1e-12)))
            # per-section gain distribution is free (the cascade only sees the
            # sum) — waterfill any section beyond [-26, +12] into sections
            # with headroom; endpoints stay exact, only interior gain
            # trajectories shift (the interior is emergent anyway)
            lo_cap, hi_cap = -25.5, 11.5
            for _ in range(8):
                excess = 0.0
                for r in rows:
                    if r["gain_db"] > hi_cap:
                        excess += r["gain_db"] - hi_cap
                        r["gain_db"] = hi_cap
                    elif r["gain_db"] < lo_cap:
                        excess += r["gain_db"] - lo_cap
                        r["gain_db"] = lo_cap
                if abs(excess) < 1e-9:
                    break
                room = [r for r in rows if lo_cap < r["gain_db"] < hi_cap]
                if not room:
                    break
                for r in room:
                    r["gain_db"] += excess / len(room)
            gmin = min(r["gain_db"] for r in rows)
            gmax = max(r["gain_db"] for r in rows)
            print(f"  section DC gains {gmin:6.1f} .. {gmax:6.1f} dB (after waterfill)")
            if gmin < -26.0 or gmax > 12.0:
                print("  REFUSED: section DC gains cannot fit the packed range [-26, +12]")
                ok = False
            body = ref_db > -70  # where the reference still has signal
            d_body = float(np.max(np.abs(np.clip(mine[body], -70, None) - np.clip(ref_db[body], -70, None))))
            print(f"{key:<12} {which} fc={fc:>6.0f}  passband |d| {d_pass:6.3f} dB · body(|H|>-70) |d| {d_body:6.3f} dB")
            if d_pass > 0.2:
                print(f"  REFUSED: passband moved {d_pass:.3f} dB under projection")
                ok = False
            skel[f"check_{which}"] = {"passband_max_d_db": round(d_pass, 4), "body_max_d_db": round(d_body, 4)}
            for i, r in enumerate(rows):
                if which == "lo":
                    skel["sections"].append({k2 + "_lo": v for k2, v in r.items()})
                else:
                    skel["sections"][i].update({k2 + "_hi": v for k2, v in r.items()})
        if ok:
            out["skeletons"].append(skel)

    path = ROOT / "tables/exact_skeletons.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path} ({len(out['skeletons'])} skeletons)")


if __name__ == "__main__":
    main()
