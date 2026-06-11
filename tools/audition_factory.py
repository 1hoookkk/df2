#!/usr/bin/env python3
"""audition_factory — render every factory body's morph sweep through the SHIPPED
drive chain (pink noise, Q=100, morph 0->1->0) onto one audition page, grouped by
family. The ear picks keepers.

    python tools/audition_factory.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audition_one import render_sweep, pink_noise, write_wav  # noqa: E402

FAC = ROOT / "dev" / "tmp" / "factory"
OUT = ROOT / "dev" / "tmp" / "audition"
COL = {"high bank collapse": "#e8923a", "remote-cut violence": "#d6564c",
       "talking vowel glide": "#6fa8d0", "shelf/cliff frame": "#b0a060", "comb/phaser field": "#c98bd0"}


def main():
    manifest = json.loads((FAC / "manifest.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    src = pink_noise(4.0)
    by_fam = {}
    for m in manifest:
        body = (FAC / f"{m['id']}.body240").read_bytes()
        write_wav(OUT / f"fac_{m['id']}.wav", render_sweep(body, src, q=1.0))
        by_fam.setdefault(m["family"], []).append(m)
        print(f"  rendered {m['id']}  ({m['family']})")

    html = ["<!doctype html><meta charset=utf-8><title>factory audition</title>",
            "<style>body{background:#0b0f0e;color:#cdd;font:13px monospace;padding:22px}"
            "h1{color:#5bef6f}h2{margin:18px 0 6px}.row{margin:6px 0;padding:7px;border:1px solid #1c2722;border-radius:5px}"
            ".n{color:#ffd23e}.m{color:#789}audio{width:480px;vertical-align:middle}</style>",
            f"<h1>TRENCH factory — {len(manifest)} grounded grammar bodies</h1>",
            "<p class=m>Each = pink noise, Q=100, morph gliding 0→1→0 through the shipped drive chain. "
            "Every pole is a real disk resonance. Flag the keepers by ear.</p>"]
    for fam in sorted(by_fam):
        html.append(f'<h2 style="color:{COL.get(fam,"#cdd")}">{fam} ({len(by_fam[fam])})</h2>')
        for m in by_fam[fam]:
            html.append(f'<div class=row><span class=n>{m["id"]}</span> '
                        f'<span class=m>maxR {m["maxR"]} · midDev {m["midDev"]}dB</span><br>'
                        f'<audio controls src="fac_{m["id"]}.wav"></audio></div>')
    (OUT / "factory_audition.html").write_text("\n".join(html), encoding="utf-8")
    print(f"\nopen: {OUT / 'factory_audition.html'}")


if __name__ == "__main__":
    main()
