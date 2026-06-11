#!/usr/bin/env python3
"""forge_method.py — author df2 bodies by THE METHOD: a MOVER + a CHARACTER.

A 12-pole body = 6 second-order sections (2 poles each). THE METHOD spends them
as a FOUNDATION (mover: a wide cutoff/window sweep -> magnitude / frequency travel)
plus a DESIGN (character: vowel formants / comb / scream -> identity), BOTH morphing
on the one Morph knob. Contrary motion between them (cutoff climbs while formants
fall) = the iconic tear. TIGHT character zeros (zero_r -> ~0.995) carve deep, narrow
anti-formant valleys = the Hedz bite.

Spend all 12 poles, no idle rows:  6 sections = mover[k] + character[6-k].

Reuses the CANONICAL encoder (tools.three_layer_acoustic_forge: hz_radius_to_kernel
-> coeffs_to_words -> raw_from_words) + packed_probe stability audit + shipped-engine
response. No new DSP, no N+1 copy.

USAGE
  python tools/forge_method.py --list
  python tools/forge_method.py --mover lp6 --char ahayee --tight 0.995 --name 6plp_ahee
  python tools/forge_method.py --mover wah --char ayeooh --tight 0.99
  python tools/forge_method.py --matrix --tight 0.995          # every mover x char -> contact sheet
Outputs .body240 + .cart.json + response.png under dev/tmp/forge_method/<name>/.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pyruntime.packed_interp import coeffs_to_words
from pyruntime.freq_response import freq_points
from src.utils.body240 import AUTHORING_SR, CORNER_ORDER, compiled_payload, raw_from_words
from tools.three_layer_acoustic_forge import hz_radius_to_kernel, audit, response_at, CORNER_POINTS

OUT = ROOT / "dev" / "tmp" / "forge_method"


def S(role, ph_home, ph_away, rq0, rq1, zh_home, zh_away, zr, gain, kind="ridge"):
    return {"role": role, "pole_hz_home": ph_home, "pole_hz_away": ph_away,
            "pole_r_q0": rq0, "pole_r_q1": rq1, "zero_hz": [zh_home, zh_away],
            "zero_r": zr, "gain_db": gain, "kind": kind}


NYQ = 19531.25

# ── MOVERS (the foundation — supply magnitude / frequency travel) ──────────────
MOVERS = {
    "lp4":  [S("lp lo", 360, 5900, 0.990, 0.9964, NYQ, NYQ, 1.0, -0.5, "skirt"),
             S("lp hi", 520, 8400, 0.9905, 0.9976, NYQ, NYQ, 1.0, -0.5, "skirt")],
    "lp6":  [S("lp lo", 300, 4800, 0.990, 0.9958, NYQ, NYQ, 1.0, -0.7, "skirt"),
             S("lp mid", 430, 7000, 0.9905, 0.997, NYQ, NYQ, 1.0, -0.7, "skirt"),
             S("lp hi", 620, 9800, 0.991, 0.998, NYQ, NYQ, 1.0, -0.7, "skirt")],
    "hp4":  [S("hp lo", 55, 1250, 0.990, 0.9962, 0, 0, 1.0, -0.4, "skirt"),
             S("hp hi", 90, 2500, 0.9905, 0.9974, 0, 0, 1.0, -0.4, "skirt")],
    "bp":   [S("bp hp skirt", 90, 450, 0.9905, 0.9968, 0, 0, 1.0, -0.3, "skirt"),
             S("bp lp skirt", 520, 2400, 0.9905, 0.9968, NYQ, NYQ, 1.0, -0.3, "skirt")],
    "wah":  [S("wah peak", 300, 3200, 0.992, 0.9996, 55, 55, 1.0, 3.0, "skirt"),
             S("wah lp skirt", 700, 7000, 0.990, 0.9982, NYQ, NYQ, 1.0, 0.0, "skirt")],
    "reece": [S("growl", 180, 520, 0.9925, 0.9992, 180, 520, 0.986, 2.4, "ridge"),
              S("bite", 900, 2400, 0.992, 0.999, 900, 2400, 0.987, 2.2, "ridge")],
    "shelf": [S("sub boom", 85, 95, 0.95, 0.992, 60, 70, 0.30, 4.0, "skirt"),
              S("low body", 200, 230, 0.94, 0.988, 140, 160, 0.30, 2.0, "skirt")],
}

# ── CHARACTERS (the design — supply identity; first 6-len(mover) used) ─────────
CHARACTERS = {
    "ahayee": [S("F1", 730, 270, 0.993, 0.9992, 450, 350, 0.88, 2.0, "ridge"),
               S("F2", 1090, 2290, 0.993, 0.9992, 1450, 1650, 0.88, 2.4, "ridge"),
               S("F3", 2440, 3010, 0.9925, 0.9988, 1850, 2600, 0.89, 1.6, "ridge"),
               S("F1-F2 canyon", 900, 1250, 0.991, 0.997, 900, 1250, 0.9996, -3.0, "notch")],
    "ooah":   [S("F1", 300, 730, 0.993, 0.9992, 420, 520, 0.88, 2.2, "ridge"),
               S("F2", 870, 1090, 0.993, 0.999, 620, 900, 0.88, 2.0, "ridge"),
               S("F3", 2240, 2440, 0.9925, 0.9986, 1500, 1650, 0.89, 1.4, "ridge"),
               S("round anti", 520, 650, 0.991, 0.997, 520, 650, 0.9996, -3.0, "notch")],
    "ayeooh": [S("F1", 500, 300, 0.993, 0.9992, 380, 250, 0.88, 2.0, "ridge"),
               S("F2", 1800, 870, 0.993, 0.9992, 1300, 650, 0.88, 2.4, "ridge"),
               S("F3", 2500, 2240, 0.9925, 0.9988, 2100, 1700, 0.89, 1.6, "ridge"),
               S("F1-F2 canyon", 1050, 560, 0.991, 0.997, 1050, 560, 0.9996, -3.0, "notch")],
    "comb":   [S("n1", 220, 520, 0.993, 0.9992, 220, 520, 0.9999, -2.0, "notch"),
               S("n2", 420, 1000, 0.993, 0.9992, 420, 1000, 0.9999, -2.0, "notch"),
               S("n3", 800, 1900, 0.993, 0.9992, 800, 1900, 0.9999, -2.2, "notch"),
               S("n4", 1500, 3600, 0.993, 0.9992, 1500, 3600, 0.9999, -2.2, "notch")],
    "scream": [S("s1", 1400, 3500, 0.993, 0.9994, 1000, 2500, 0.50, 2.5, "ridge"),
               S("s2", 2100, 5000, 0.992, 0.9992, 1500, 3600, 0.50, 2.0, "ridge"),
               S("s3", 3000, 7000, 0.991, 0.999, 2200, 5000, 0.50, 1.5, "ridge"),
               S("s4", 800, 1800, 0.992, 0.999, 600, 1300, 0.50, 1.0, "ridge")],
}


def compose(mover_name, char_name, tight=None):
    mover = MOVERS[mover_name]
    n = 6 - len(mover)
    if n < 1:
        raise SystemExit(f"mover '{mover_name}' uses {len(mover)} sections; no room for a character")
    chars = [dict(s) for s in CHARACTERS[char_name][:n]]
    if len(chars) < n:
        raise SystemExit(f"character '{char_name}' has only {len(chars)} sections; need {n}")
    if tight is not None:
        for s in chars:
            if s["kind"] == "ridge":   # tighten the anti-formant carve; notches stay deep
                s["zero_r"] = float(tight)
    return mover + chars


def body_from_sections(secs, sr):
    words = {}
    for label in CORNER_ORDER:
        m, q = CORNER_POINTS[label]; away = m >= 0.5; hiq = q >= 0.5; rows = []
        for s in secs:
            ph = float(s["pole_hz_away"] if away else s["pole_hz_home"])
            pr = float(s["pole_r_q1"] if hiq else s["pole_r_q0"])
            zh = float(s["zero_hz"][1] if away else s["zero_hz"][0])
            g = 10.0 ** (float(s.get("gain_db", 0.0)) / 20.0)
            rows.append(tuple(int(v) for v in coeffs_to_words(*hz_radius_to_kernel(ph, pr, zh, float(s["zero_r"]), g, sr))))
        words[label] = rows
    return raw_from_words(words), words


def travel_oct(body, sr, freqs):
    pk = np.array([freqs[int(np.argmax(response_at(body, float(m), 1.0, sr)))] for m in np.linspace(0, 1, 41)])
    return float(np.log2(pk.max() / max(pk.min(), 1e-9)))


def plot_body(name, body, sr, out_png):
    freqs = freq_points()
    fig, axes = plt.subplots(1, 3, figsize=(17, 4.7), facecolor="#0a0c0b")
    morphs = np.linspace(0, 1, 200)
    for ax, q, title in ((axes[0], 0.0, "Q0 morph surface"), (axes[1], 1.0, "Q100 morph surface")):
        img = np.array([response_at(body, float(m), q, sr) for m in morphs]).T
        ax.pcolormesh(morphs, freqs, img, cmap="magma", shading="auto")
        ax.set_yscale("log"); ax.set_ylim(max(40, freqs[0]), freqs[-1])
        ax.set_title(title, color="#cfe9df"); ax.set_xlabel("Morph", color="#9aa"); ax.tick_params(colors="#8a968f", labelsize=7)
    ax = axes[2]
    for m, q, l in ((0, 0, "M0·Q0"), (1, 0, "M100·Q0"), (0, 1, "M0·Q100"), (1, 1, "M100·Q100")):
        ax.semilogx(freqs, response_at(body, float(m), float(q), sr), label=l, lw=1.3)
    ax.set_xlim(40, freqs[-1]); ax.grid(True, alpha=0.25); ax.legend(fontsize=8)
    ax.set_title("four corners", color="#cfe9df"); ax.set_xlabel("Hz", color="#9aa"); ax.tick_params(colors="#8a968f", labelsize=7)
    fig.suptitle(name, color="#9fe7c6"); fig.tight_layout()
    fig.savefig(out_png, dpi=120, facecolor="#0a0c0b"); plt.close(fig)


def forge(mover, char, tight, name, sr):
    secs = compose(mover, char, tight)
    body, words = body_from_sections(secs, sr)
    rep = audit(body, grid=13)
    d = OUT / name; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.body240").write_bytes(body)
    (d / f"{name}.cart.json").write_text(json.dumps(compiled_payload(name, 1.0, words), indent=2) + "\n", encoding="utf-8")
    plot_body(f"{name}  ({mover} x {char}, tight={tight})", body, sr, d / "response.png")
    oct_ = travel_oct(body, sr, freq_points())
    bad = bool(rep["unstable_mask"] or rep["nonfinite_mask"])
    print(f"{name:<22} {mover:>5} x {char:<7} travel={oct_:4.1f}oct  unstable={rep['unstable_mask']} "
          f"max_r={rep['max_pole_radius']:.5f}  {'*** BROKEN' if bad else 'OK'}  -> {d.name}/")
    return body, rep, oct_


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mover", choices=list(MOVERS))
    ap.add_argument("--char", choices=list(CHARACTERS))
    ap.add_argument("--tight", type=float, default=None, help="ridge anti-formant zero radius (~0.99-0.9985 = Hedz carve)")
    ap.add_argument("--name", default=None)
    ap.add_argument("--matrix", action="store_true", help="forge every mover x character pairing + a contact sheet")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    sr = AUTHORING_SR

    if args.list:
        print("MOVERS (foundation):   " + "  ".join(f"{k}({len(v)}sec)" for k, v in MOVERS.items()))
        print("CHARACTERS (design):   " + "  ".join(CHARACTERS))
        return 0

    if args.matrix:
        freqs = freq_points(); rows = []
        pairs = [(mv, ch) for mv in MOVERS for ch in CHARACTERS]
        ncols = len(CHARACTERS); nrows = len(MOVERS)
        fig, axes = plt.subplots(nrows, ncols, figsize=(3.4 * ncols, 2.4 * nrows), facecolor="#0a0c0b"); axes = np.array(axes).reshape(-1)
        morphs = np.linspace(0, 1, 110)
        for i, (mv, ch) in enumerate(pairs):
            ax = axes[i]
            try:
                body, rep, oct_ = forge(mv, ch, args.tight, f"{mv}_x_{ch}", sr)
                img = np.array([response_at(body, float(m), 1.0, sr) for m in morphs]).T
                ax.pcolormesh(morphs, freqs, img, cmap="magma", shading="auto"); ax.set_yscale("log"); ax.set_ylim(max(40, freqs[0]), freqs[-1])
                bad = bool(rep["unstable_mask"] or rep["nonfinite_mask"])
                ax.set_title(f"{mv}x{ch} {oct_:.1f}oct{' BAD' if bad else ''}", color=("#ff6d6d" if bad else "#cfe9df"), fontsize=7)
            except Exception as ex:
                ax.set_title(f"{mv}x{ch} ERR", color="#ff6d6d", fontsize=7); print("ERR", mv, ch, repr(ex))
            ax.set_xticks([]); ax.tick_params(colors="#8a968f", labelsize=6)
        fig.suptitle("forge_method matrix — mover (rows) x character (cols), Q100", color="#9fe7c6", fontsize=12)
        fig.tight_layout(); OUT.mkdir(parents=True, exist_ok=True)
        fig.savefig(OUT / "matrix.png", dpi=110, facecolor="#0a0c0b"); plt.close(fig)
        print(f"\nwrote {OUT / 'matrix.png'}")
        return 0

    if not args.mover or not args.char:
        raise SystemExit("need --mover and --char (or --matrix / --list)")
    name = args.name or f"{args.mover}_x_{args.char}"
    forge(args.mover, args.char, args.tight, name, sr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
