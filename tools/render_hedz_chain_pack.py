#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from pathlib import Path

from pyruntime import trench_ffi
from tools.hedz_control_player import BODY, SR, source, stereo_wav

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dev" / "tmp" / "hedz_chain_pack"

MORPH = 0.5
Q = 0.5
SLAM = 0.65
SPACE = 0.75
AGC_DRIVE = 4.0

STATES = [
    ("00_DRY_INPUT", "Dry pink-noise input", False, 0.0, False),
    ("01_RAW_FILTER", "Talking Hedz only", False, 0.0, False),
    ("02_AGC", "Talking Hedz + AGC", True, 0.0, False),
    ("03_MACKIE_SLAM", "Mackie Slam -> Talking Hedz", False, SLAM, False),
    ("04_QSOUND", "Talking Hedz -> QSound", False, 0.0, True),
    ("05_AGC_MACKIE", "Mackie Slam -> Talking Hedz -> AGC", True, SLAM, False),
    ("06_AGC_QSOUND", "Talking Hedz -> AGC -> QSound", True, 0.0, True),
    ("07_MACKIE_QSOUND", "Mackie Slam -> Talking Hedz -> QSound", False, SLAM, True),
    ("08_FULL_CHAIN", "Mackie Slam -> Talking Hedz -> AGC -> QSound", True, SLAM, True),
]


def render() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cart = BODY.read_text(encoding="utf-8")
    pink = source("pink")
    dry = pink.astype("<f4").tobytes()
    manifest = []
    for slug, label, agc, slam, qsound in STATES:
        path = OUT / f"{slug}.wav"
        if slug == "00_DRY_INPUT":
            wav = stereo_wav(dry, dry)
        else:
            left, right = trench_ffi.engine_render_controls_stereo(
                cart,
                MORPH,
                Q,
                dry,
                slam_drive=slam,
                qsound_enabled=qsound,
                space=SPACE,
                agc_enabled=agc,
                agc_drive=AGC_DRIVE,
                sr=SR,
            )
            wav = stereo_wav(left, right)
        path.write_bytes(wav)
        manifest.append(
            {
                "file": path.name,
                "label": label,
                "agc": agc,
                "slam": slam,
                "qsound": qsound,
            }
        )
        print(f"wrote {path}")

    metadata = {
        "body": str(BODY),
        "source": "pink",
        "sample_rate": SR,
        "morph": MORPH,
        "q": Q,
        "slam_amount": SLAM,
        "qsound_space": SPACE,
        "agc_drive": AGC_DRIVE,
        "states": manifest,
    }
    (OUT / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (OUT / "audition.html").write_text(audition_page(manifest), encoding="utf-8")
    print(f"open {OUT / 'audition.html'}")


def audition_page(states: list[dict]) -> str:
    rows = []
    for state in states:
        rows.append(
            f"""<article>
  <div><b>{html.escape(state["file"][:-4])}</b><span>{html.escape(state["label"])}</span></div>
  <audio controls loop preload="none" src="{html.escape(state["file"])}"></audio>
</article>"""
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Talking Hedz chain pack</title>
<style>
body{{font:15px system-ui;background:#f2f0eb;color:#252723;max-width:900px;margin:36px auto;padding:0 22px}}
h1{{letter-spacing:-.04em;margin-bottom:4px}}p{{color:#68635a;margin-top:0}}
article{{display:grid;grid-template-columns:1fr 360px;gap:18px;align-items:center;background:#fffdf8;border:1px solid #d8d0c4;border-radius:12px;padding:13px 16px;margin:9px 0}}
b,span{{display:block}}span{{color:#746e65;font-size:13px;margin-top:3px}}audio{{width:100%}}
@media(max-width:700px){{article{{grid-template-columns:1fr}}}}
</style>
<h1>Talking Hedz chain pack</h1>
<p>Identical pink noise · Morph 50 · Q 50 · AGC engagement x4 · Mackie Slam 65 · QSound Space 75</p>
{"".join(rows)}
"""


if __name__ == "__main__":
    render()
