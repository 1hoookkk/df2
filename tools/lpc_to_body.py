#!/usr/bin/env python3
"""lpc_to_body — the missing bridge: a recording (or two) -> a morph body.

`lpc_extract` stops at the poles; this turns those poles into a player-loadable
240-byte body. Point M0 at one vowel and M100 at another and the morph GLIDES
between two real captured vowels (the Talking-Hedz move with your own voice).
Q sharpens (broad -> ringing).

    # one command, voice in -> body out (compile with author_body after):
    python tools/lpc_to_body.py --name "Vowel Glide" \\
        --m0 "dev/tmp/recordings/ah.wav" --m100 "dev/tmp/recordings/ee.wav"

Accepts .wav (runs LPC extraction) or a pre-made .lpc.json for --m0/--m100.
"""
from __future__ import annotations
import argparse, json, sys, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.lpc_extract import analyse_wav  # noqa: E402
from tools.corner_words import allpole_words, build_toml_words  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words  # noqa: E402

PASS = coeffs_to_words(2.0, 1.0, 2.0, 1.0, 1.0)  # passthrough stage word


def poles_of(path: str):
    p = Path(path)
    if p.name.endswith(".lpc.json") or p.suffix == ".json":
        d = json.loads(p.read_text())
    else:
        d = analyse_wav(p)            # run LPC on the wav
    return [(x["freq_hz"], x["radius"]) for x in d["poles"]]


def corner(P, sharp: bool):
    # ALL-POLE reconstruction (1/A(z)) — the LPC filter itself, the way Talking
    # Hedz uses its poles. NOT band-peaks: that boosts every pole equally and
    # wrecks the envelope. `sharp` tightens radii for the Q axis.
    w = [allpole_words(f, min(0.995, r + 0.02) if sharp else min(r, 0.99)) for f, r in P[:6]]
    while len(w) < 6:
        w.append(PASS)
    return w


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--m0", required=True, help="wav or .lpc.json for the M0 corner (e.g. an 'ah')")
    ap.add_argument("--m100", help="wav or .lpc.json for M100 (e.g. an 'ee'); defaults to --m0 (static body)")
    ap.add_argument("--compile", action="store_true", help="also run author_body.py to .cart.json + .png")
    args = ap.parse_args()

    A = poles_of(args.m0)
    B = poles_of(args.m100) if args.m100 else A
    corners = {"M0_Q0": corner(A, False), "M100_Q0": corner(B, False),
               "M0_Q100": corner(A, True), "M100_Q100": corner(B, True)}

    slug = args.name.lower().replace(" ", "_")
    toml = ROOT / "bodies" / "factory" / f"{slug}.packed.toml"
    toml.parent.mkdir(parents=True, exist_ok=True)
    toml.write_text(build_toml_words(args.name, corners))
    print(f"wrote {toml}")
    print(f"  M0  poles: {[f'{f:.0f}Hz' for f,_ in A]}")
    print(f"  M100 poles: {[f'{f:.0f}Hz' for f,_ in B]}" if args.m100 else "  (static — pass --m100 a different vowel to make it glide)")

    if args.compile:
        cart = ROOT / "bodies" / f"{slug}.cart.json"
        png = ROOT / "dev" / "tmp" / "factory" / f"{slug}.png"
        subprocess.run([sys.executable, str(ROOT / "tools" / "author_body.py"),
                        str(toml), "--out", str(cart), "--png", str(png)], check=False)
        print(f"  -> {cart}")


if __name__ == "__main__":
    main()
