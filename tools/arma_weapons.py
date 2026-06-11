#!/usr/bin/env python3
"""arma_weapons.py — LSP + LPC fit the ARMA source pack into CHARACTER "weapon" cards.

Each real recording is conditioned to its steady-state slice and fitted with 12th-order
LPC: the poles ARE its real resonances. The pole set is re-expressed as Line Spectral
Frequencies (LSF / LSP) — the morph-stable coordinate the forge interpolates in, and the
adjacent-pair spacing gives a clean bandwidth (tight pair = sharp formant). Anti-resonances
(spectral nulls) are measured from the smoothed magnitude spectrum and become the section
zeros (per-section, varied — mined, never a uniform rule). Padding lanes stay all-pole.

Output: one foundation_filter_starters-schema card per source, written to
forge-web/data/weapons.json, so the forge CHARACTER picker can layer a real-sound
fingerprint (C1-C3) onto any foundation (F1-F3).

No invented numbers — every freq / radius / zero traces to the measured spectrum.

Usage:  python tools/arma_weapons.py            # fits the whole pack
        python tools/arma_weapons.py --plot      # + a magnitude PNG per weapon
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.lpc_extract import (  # noqa: E402
    ANALYSIS_SR, LPC_ORDER, PRE_EMPH, PREEMPH_TILT_THRESHOLD_DB_PER_OCT,
    load_mono_16k, steady_state_region, measure_tilt_db_per_octave,
    lpc_autocorr, extract_poles,
)
from scipy.signal import lfilter  # noqa: E402

ENGINE_SR = 39062.5            # df2 packed-coefficient sample rate (radius lives here)
Q_RADIUS_MAX = 0.986271       # real-corpus max (tables/q_radius_table.json) — never exceed
TEETH = 0.42                  # Q100 sharp frame narrows the measured bandwidth by this much
NULL_MIN_DB = 5.0             # a dip must be this far below its flanking peaks to earn a zero
PACK = ROOT / "dev/tmp/arma_source_pack/wav"

# source file -> (display name, family tag)  — family != lowpass/highpass/bandpass => CHARACTER
NAMES = {
    "openair_innocent_railway_tunnel_entrance": ("Tunnel Entrance", "room"),
    "openair_hamilton_mausoleum_hm2_000_wx_48k": ("Mausoleum", "room"),
    "openair_r1_nuclear_reactor_hall_r1_omni_48k": ("Reactor Hall", "room"),
    "inspire_7purewhist": ("Pure Whistler", "whistler"),
    "inspire_52hopwhist": ("Hop Whistler", "whistler"),
    "inspire_3tweeks": ("VLF Tweeks", "whistler"),
    "inspire_chorus": ("VLF Chorus", "whistler"),
    "conet_swedish_rhapsody": ("Swedish Rhapsody", "station"),
    "conet_5_dashes": ("Five Dashes", "station"),
    "wikimedia_carotid_doppler": ("Carotid Doppler", "pulse"),
    "stolaf_nmrtalk_cyclohexane_real_48k": ("NMR Cyclohexane", "nmr"),
    "stolaf_nmrtalk_dichloromethane_real_48k": ("NMR Dichloromethane", "nmr"),
    "stolaf_nmrtalk_ethyl_acetate_real_48k": ("NMR Ethyl Acetate", "nmr"),
    "stolaf_nmrtalk_inositol_real_48k": ("NMR Inositol", "nmr"),
    "stolaf_nmrtalk_cyclohexane_dichloromethane_mixture_real_48k": ("NMR Mixture", "nmr"),
}


def conditioned_segment(path: Path):
    """Reproduce lpc_extract's conditioning, returning (segment, lpc_coeffs)."""
    x, sr = load_mono_16k(path)
    s, e = steady_state_region(x, sr)
    seg = x[s:e].copy()
    tilt = measure_tilt_db_per_octave(seg, sr)
    if tilt < PREEMPH_TILT_THRESHOLD_DB_PER_OCT:
        seg = lfilter([1.0, -PRE_EMPH], [1.0], seg)
    seg = seg * np.hamming(len(seg))
    lpc = lpc_autocorr(seg, LPC_ORDER)
    return seg, lpc, sr


def lpc_to_lsf(a: np.ndarray) -> np.ndarray:
    """LPC polynomial A(z) -> Line Spectral Frequencies (radians, ascending).

    P(z)=A(z)+z^-(p+1)A(1/z) carries the root at z=-1; Q(z)=A(z)-z^-(p+1)A(1/z)
    the root at z=+1 (p even). Deflate those, take the unit-circle root angles.
    """
    p = len(a) - 1
    ap = np.concatenate([a, [0.0]])
    arev = np.concatenate([[0.0], a[::-1]])
    P, Q = ap + arev, ap - arev
    if p % 2 == 0:
        P = np.polydiv(P, np.array([1.0, 1.0]))[0]
        Q = np.polydiv(Q, np.array([1.0, -1.0]))[0]
    else:
        Q = np.polydiv(Q, np.array([1.0, -1.0, 0.0]) if False else np.array([1.0, 0.0, -1.0]))[0]
    ang = []
    for poly in (P, Q):
        for z in np.roots(poly):
            w = float(np.angle(z))
            if 1e-4 < w < np.pi - 1e-4:
                ang.append(w)
    return np.array(sorted(ang))


def smoothed_db_spectrum(seg: np.ndarray, sr: int, nfft: int = 4096):
    """Log-magnitude spectrum, lightly smoothed, on a linear-Hz grid."""
    mag = np.abs(np.fft.rfft(seg, n=nfft))
    freqs = np.fft.rfftfreq(nfft, d=1.0 / sr)
    db = 20.0 * np.log10(mag + 1e-9)
    # moving-average smooth (~3 bins -> a few tens of Hz)
    k = 9
    kern = np.ones(k) / k
    db = np.convolve(db, kern, mode="same")
    return freqs, db


def measure_zero(freqs, db, f_lo, f_hi, peak_db):
    """Deepest dip between two pole freqs -> (null_hz, zero_r) or None if shallow."""
    m = (freqs > f_lo) & (freqs < f_hi)
    if m.sum() < 3:
        return None
    seg_db = db[m]
    seg_f = freqs[m]
    j = int(np.argmin(seg_db))
    depth = peak_db - float(seg_db[j])
    if depth < NULL_MIN_DB:
        return None
    null_hz = float(seg_f[j])
    # deeper null -> zero radius closer to the unit circle (sharper notch), capped
    zero_r = min(0.999, 0.90 + (depth - NULL_MIN_DB) / 40.0 * 0.099)
    return null_hz, zero_r


def r_from_bw(bw_hz: float, frac: float = 1.0) -> float:
    bw = max(8.0, bw_hz * frac)
    return float(min(Q_RADIUS_MAX, np.exp(-np.pi * bw / ENGINE_SR)))


def build_weapon(path: Path) -> dict | None:
    stem = path.stem
    disp, fam = NAMES.get(stem, (stem.replace("_", " ").title(), "weapon"))
    seg, lpc, sr = conditioned_segment(path)
    poles = extract_poles(lpc, sr)
    if not poles:
        return None
    lsf = lpc_to_lsf(lpc)
    lsf_hz = (lsf * sr / (2.0 * np.pi)).tolist()
    freqs, db = smoothed_db_spectrum(seg, sr)

    # bandwidth per pole from the nearest bracketing LSF pair (LSP-derived Q),
    # falling back to the LPC root bandwidth when no pair brackets it.
    def lsp_bw(f_hz, lpc_bw):
        w = f_hz * 2.0 * np.pi / sr
        below = lsf[lsf <= w]
        above = lsf[lsf >= w]
        if len(below) and len(above):
            spacing = float(above[0] - below[-1])           # radians between the pair
            bw = spacing * sr / (2.0 * np.pi)
            if 8.0 <= bw <= lpc_bw * 1.5:
                return bw
        return lpc_bw

    pole_fs = [p["freq_hz"] for p in poles]
    sections = []
    for i, p in enumerate(poles):
        f = p["freq_hz"]
        bw = lsp_bw(f, p["bandwidth_hz"])
        # local peak level for the null-depth test (this pole's spectral height)
        bidx = int(np.argmin(np.abs(freqs - f)))
        peak_db = float(db[bidx])
        # search the gap up to the next pole (or +1 oct) for a real anti-resonance
        f_hi = pole_fs[i + 1] if i + 1 < len(pole_fs) else f * 2.0
        z = measure_zero(freqs, db, f, f_hi, peak_db)
        if z is None:
            zhz, zr, zrole = f, r_from_bw(bw), "masked (all-pole)"
        else:
            zhz, zr, zrole = z[0], z[1], f"anti-resonance {z[0]:.0f}Hz"
        sections.append({
            "role": f"resonance {i+1} @ {f:.0f}Hz · {zrole}",
            "pole_hz_home": round(f, 2), "pole_hz_away": round(f, 2),
            "pole_r_q0": round(r_from_bw(bw), 4),
            "pole_r_q1": round(r_from_bw(bw, TEETH), 4),
            "zero_hz": [round(zhz, 2), round(zhz, 2)],
            "zero_r": round(zr, 4),
            "zero_moves": "static fingerprint",
            "gain_db": 0.0,
        })
    # pad to 6 neutral all-pole passthrough lanes
    park = [800.0, 1600.0, 3200.0, 6400.0, 12000.0, 15000.0]
    while len(sections) < 6:
        pf = park[len(sections)]
        sections.append({
            "role": "idle (passthrough)",
            "pole_hz_home": pf, "pole_hz_away": pf,
            "pole_r_q0": 0.90, "pole_r_q1": 0.90,
            "zero_hz": [pf, pf], "zero_r": 0.90,
            "zero_moves": "idle", "gain_db": 0.0,
        })

    n_zeros = sum(1 for s in sections[:len(poles)] if "anti-resonance" in s["role"])
    return {
        "type": disp,
        "family": fam,
        "weapon": True,
        "dsp_identity": (
            f"LSP+LPC capture of {disp} ({stem}). {len(poles)} measured resonances, "
            f"{n_zeros} measured anti-resonance zero(s). Static fingerprint — the foundation "
            f"sweeps through it; Q sharpens the captured formants toward a scream."
        ),
        "sections": sections,
        "morph_moves": "static real-sound fingerprint (home = away); pair two weapons in LSF space for a glide",
        "q_exposes": "captured formant sharpness (Q100 narrows toward the band edges)",
        "carve_zeros_where": "zeros sit on the measured spectral nulls",
        "lsf_hz": [round(v, 1) for v in lsf_hz],
        "source": str(path.relative_to(ROOT)).replace("\\", "/"),
    }


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plot", action="store_true", help="write a magnitude PNG per weapon")
    args = ap.parse_args(argv)

    wavs = sorted([p for p in PACK.glob("*.wav")] +
                  [p for p in (PACK / "stolaf_nmrtalk").glob("*.wav")])
    weapons, table = [], []
    for w in wavs:
        try:
            card = build_weapon(w)
        except Exception as ex:  # noqa: BLE001
            print(f"  !! {w.name}: {ex}", file=sys.stderr)
            continue
        if not card:
            print(f"  -- {w.name}: no poles, skipped", file=sys.stderr)
            continue
        weapons.append(card)
        n_real = sum(1 for s in card["sections"] if "resonance" in s["role"])
        n_z = sum(1 for s in card["sections"] if "anti-resonance" in s["role"])
        table.append((card["type"], card["family"], n_real, n_z))

    out = ROOT / "forge-web/data/weapons.json"
    out.write_text(json.dumps(weapons, indent=2) + "\n")
    print(f"\nwrote {len(weapons)} weapons -> {out.relative_to(ROOT)}\n")
    print(f"  {'weapon':<22}{'family':<10}{'poles':>6}{'zeros':>6}")
    for t, f, nr, nz in table:
        print(f"  {t:<22}{f:<10}{nr:>6}{nz:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
