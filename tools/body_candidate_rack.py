#!/usr/bin/env python3
"""Generate a playable rack of packed-body candidates.

Surface rule: candidates are 240-byte bodies plus WAVs. No row roles, no stage
story, no body-spec ceremony. Internally this uses pole/zero coordinates as a
compact way to create stable packed words, then immediately collapses to the
canonical body bytes.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
for _p in (str(ROOT), str(TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import author_body as ab  # noqa: E402
import corner_bench as cb  # noqa: E402
import corner_words as cw  # noqa: E402
import teleport_stress as ts  # noqa: E402


def slug(s: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", s.strip().lower()).strip("_")
    return cleaned or "body"


def log_uniform(rng: random.Random, lo: float, hi: float) -> float:
    return lo * ((hi / lo) ** rng.random())


def clamp_freq(f: float) -> float:
    return max(70.0, min(17800.0, f))


def tighten_radius(r0: float, factor: float) -> float:
    # Radius is misleading near 1.0; shrink distance-to-edge instead.
    return min(0.9985, 1.0 - (1.0 - r0) * factor)


def profile_for(vibe: str) -> dict[str, Any]:
    v = vibe.lower()
    profile = {
        "freq_bands": ((120, 520), (420, 1600), (900, 3600), (1800, 7200), (3600, 12500), (7600, 16800)),
        "moves_oct": (-0.75, 1.15),
        "radius": (0.935, 0.978),
        "tighten": (0.12, 0.55),
        "zero_semis": (-24, -12, -7, -7, -5),
    }
    if any(k in v for k in ("glass", "metal", "tear", "shatter", "chrome", "wire")):
        profile.update({
            "freq_bands": ((180, 700), (700, 2200), (1500, 5200), (3000, 9800), (6200, 15500), (9500, 17600)),
            "moves_oct": (-0.35, 1.35),
            "radius": (0.952, 0.986),
            "tighten": (0.06, 0.35),
            "zero_semis": (-24, -19, -7, -7, -3),
        })
    if any(k in v for k in ("talk", "mouth", "voice", "throat", "vowel")):
        profile.update({
            "freq_bands": ((180, 520), (450, 1100), (800, 2400), (1400, 4200), (2400, 7200), (5200, 13500)),
            "moves_oct": (-1.05, 1.05),
            "radius": (0.945, 0.977),
            "tighten": (0.10, 0.45),
            "zero_semis": (-24, -12, -7, -7, -7),
        })
    if any(k in v for k in ("slam", "desk", "bass", "808", "thump")):
        profile.update({
            "freq_bands": ((85, 260), (180, 650), (360, 1250), (900, 2800), (1800, 6200), (5000, 15000)),
            "moves_oct": (-0.6, 1.0),
            "radius": (0.940, 0.976),
            "tighten": (0.14, 0.50),
            "zero_semis": (-24, -12, -7, -7, -7),
        })
    return profile


def make_words(vibe: str, rng: random.Random) -> dict[str, list[tuple[int, ...]]]:
    p = profile_for(vibe)
    bands = list(p["freq_bands"])
    rng.shuffle(bands)
    bands = bands[:6]
    bands.sort(key=lambda x: x[0])

    specs = []
    for lo, hi in bands:
        f0 = log_uniform(rng, lo, hi)
        move = rng.uniform(*p["moves_oct"])
        if f0 > 5000 and move > 0.65:
            move *= 0.55
        if rng.random() < 0.28:
            move *= -1.0
        f1 = clamp_freq(f0 * (2.0 ** move))
        r0 = rng.uniform(*p["radius"])
        r1 = tighten_radius(r0, rng.uniform(*p["tighten"]))
        zero_semis = rng.choice(p["zero_semis"])
        specs.append((f0, f1, r0, r1, zero_semis))

    def section(freq: float, radius: float, zero_semis: float):
        zero_freq = clamp_freq(freq * (2.0 ** (zero_semis / 12.0)))
        return cw.notch(freq, radius, -0.08, zero_freq, 1.0)

    corners = {}
    for label, morph, q in (
        ("M0_Q0", 0.0, 0.0),
        ("M100_Q0", 1.0, 0.0),
        ("M0_Q100", 0.0, 1.0),
        ("M100_Q100", 1.0, 1.0),
    ):
        params = []
        for f0, f1, r0, r1, zero_semis in specs:
            freq = f0 * ((f1 / f0) ** morph)
            radius = r0 + (r1 - r0) * q
            params.append(section(freq, radius, zero_semis))
        corners[label] = cw.corner_words(params)
    return corners


def render_candidate(name: str,
                     vibe: str,
                     words: dict[str, list[tuple[int, ...]]],
                     out_dir: Path,
                     sr: int,
                     seconds_sweep: float,
                     seconds_teleport: float,
                     seed: int,
                     drive: float) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = ab.raw_from_words(words)
    body_path = out_dir / f"{name}.body240"
    cart_path = out_dir / f"{name}.cart.json"
    body_path.write_bytes(raw)
    cart_path.write_text(json.dumps(ab.compiled_payload(name, 1.0, words), indent=2) + "\n",
                         encoding="utf-8")

    sweep_dyn, sweep_static = cb.render_sweep(words, out_dir / "sweep_slow.wav",
                                             sr, seconds_sweep, drive)
    # For generated bodies, original == current. Keep the filename shape the
    # same so existing audition pages and habits still work.
    (out_dir / "sweep_slow_original.wav").write_bytes((out_dir / "sweep_slow.wav").read_bytes())
    source = ts.source_signal(int(round(seconds_teleport * sr)), sr)
    modes = cb.render_teleports(words, out_dir, sr, seconds_teleport, seed, drive, source)
    stability = cb.aggregate_stability(sweep_static, sweep_dyn, modes)

    report = {
        "name": name,
        "vibe": vibe,
        "source": "generated packed body",
        "sample_rate": sr,
        "candidate_rack": True,
        "sweep": {"dynamic": sweep_dyn, "static_probe": sweep_static},
        "modes": modes,
        "stability": stability,
        "mutations": [],
        "outputs": {
            "body240": str(body_path),
            "cart_json": str(cart_path),
            "sweep": str(out_dir / "sweep_slow.wav"),
            "teleport_noise": str(out_dir / "teleport_noise.wav"),
            "teleport_square_150hz": str(out_dir / "teleport_square_150hz.wav"),
            "teleport_derivative": str(out_dir / "teleport_derivative.wav"),
            "audition": str(out_dir / "audition.html"),
        },
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_candidate_page(out_dir / "audition.html", report)
    return report


def write_candidate_page(path: Path, report: dict[str, Any]) -> None:
    st = report["stability"]
    html_doc = f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(report['name'])}</title>
<style>
body{{margin:0;background:#080a0a;color:#eee9dc;font:14px/1.4 system-ui,Segoe UI,sans-serif}}
main{{max-width:920px;margin:0 auto;padding:24px 18px 52px}}
h1{{font-size:24px;margin:0 0 4px}}
h2{{font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:#7fd6b0;margin:24px 0 8px}}
.muted{{color:#92978f}}
.panel{{border:1px solid #20342d;background:#0d1110;border-radius:8px;padding:14px;margin:12px 0}}
audio{{width:100%;margin-top:4px}}
.stat{{font:12px ui-monospace,Consolas,monospace;color:#f6d76b}}
a{{color:#81d4ff}}
</style>
<main>
  <h1>{html.escape(report['name'])}</h1>
  <p class="muted">{html.escape(report['vibe'])} · clean={str(st['clean']).lower()} · max_r={st['max_pole_radius']:.6f}</p>
  <section class="panel"><h2>Slow Morph/Q Sweep</h2><audio controls preload="none" src="sweep_slow.wav"></audio></section>
  <section class="panel"><h2>Noise Teleport</h2><audio controls preload="none" src="teleport_noise.wav"></audio></section>
  <section class="panel"><h2>150 Hz Strobe</h2><audio controls preload="none" src="teleport_square_150hz.wav"></audio></section>
  <section class="panel"><h2>Derivative</h2><audio controls preload="none" src="teleport_derivative.wav"></audio></section>
  <section class="panel">
    <h2>Files</h2>
    <p class="stat">nonfinite={st['nonfinite_state_events']} coeff_nonfinite={st['nonfinite_coeff_rows']} unstable={st['unstable_denominator_rows']}</p>
    <p><a href="{html.escape(Path(report['outputs']['body240']).name)}">body240</a> ·
       <a href="{html.escape(Path(report['outputs']['cart_json']).name)}">cart json</a> ·
       <a href="report.json">report</a></p>
  </section>
</main>
"""
    path.write_text(html_doc, encoding="utf-8")


def write_index(out_root: Path, reports: list[dict[str, Any]], vibe: str) -> None:
    cards = []
    for report in reports:
        name = report["name"]
        st = report["stability"]
        cards.append(f"""
<section class="card">
  <h2>{html.escape(name)}</h2>
  <p class="meta">clean={str(st['clean']).lower()} · max_r={st['max_pole_radius']:.6f}</p>
  <a href="{html.escape(name)}/audition.html">open full page</a>
  <div class="players">
    <label>sweep<audio controls preload="none" src="{html.escape(name)}/sweep_slow.wav"></audio></label>
    <label>noise<audio controls preload="none" src="{html.escape(name)}/teleport_noise.wav"></audio></label>
    <label>strobe<audio controls preload="none" src="{html.escape(name)}/teleport_square_150hz.wav"></audio></label>
    <label>derivative<audio controls preload="none" src="{html.escape(name)}/teleport_derivative.wav"></audio></label>
  </div>
</section>""")
    html_doc = f"""<!doctype html>
<meta charset="utf-8">
<title>Body Candidate Rack</title>
<style>
body{{margin:0;background:#080a0a;color:#eee9dc;font:14px/1.4 system-ui,Segoe UI,sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:24px 18px 52px}}
h1{{font-size:25px;margin:0 0 4px}}
h2{{font-size:17px;margin:0 0 4px;color:#9fe7c6}}
.muted,.meta{{color:#92978f}}
.card{{border:1px solid #20342d;background:#0d1110;border-radius:8px;padding:14px;margin:14px 0}}
.players{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;margin-top:12px}}
label{{display:block;color:#f1d76a;font:12px ui-monospace,Consolas,monospace}}
audio{{display:block;width:100%;margin-top:4px}}
a{{color:#81d4ff}}
@media(max-width:820px){{.players{{grid-template-columns:1fr}}}}
</style>
<main>
  <h1>Body Candidate Rack</h1>
  <p class="muted">{html.escape(vibe)}. Listen first. Keep nothing by default.</p>
  {''.join(cards)}
</main>
"""
    (out_root / "index.html").write_text(html_doc, encoding="utf-8")


def save_keeper_copy(name: str, report: dict[str, Any]) -> None:
    cb.KEEPERS.mkdir(parents=True, exist_ok=True)
    body = Path(report["outputs"]["body240"])
    cart = Path(report["outputs"]["cart_json"])
    (cb.KEEPERS / f"{name}.body240").write_bytes(body.read_bytes())
    (cb.KEEPERS / f"{name}.cart.json").write_text(cart.read_text(encoding="utf-8"),
                                                  encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("vibe", help="short sonic target, e.g. 'talking metal tear'")
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--attempts", type=int, default=120)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--save-keepers", action="store_true")
    ap.add_argument("--sr", type=int, default=44_100)
    ap.add_argument("--seconds-sweep", type=float, default=1.2)
    ap.add_argument("--seconds-teleport", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=0x513DF2)
    ap.add_argument("--containment-drive", type=float, default=4.0)
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    base = slug(args.vibe)
    out_root = args.out or (ROOT / "dev" / "tmp" / "body_rack" / base)
    out_root.mkdir(parents=True, exist_ok=True)

    reports: list[dict[str, Any]] = []
    attempts = 0
    while len(reports) < args.count and attempts < args.attempts:
        attempts += 1
        words = make_words(args.vibe, rng)
        name = f"{base}_{len(reports) + 1:02d}"
        out_dir = out_root / name
        report = render_candidate(name, args.vibe, words, out_dir,
                                  args.sr, args.seconds_sweep,
                                  args.seconds_teleport, args.seed + attempts,
                                  args.containment_drive)
        if not report["stability"]["clean"]:
            continue
        reports.append(report)
        if args.save_keepers:
            save_keeper_copy(name, report)
        st = report["stability"]
        print(f"{name}: clean max_r={st['max_pole_radius']:.6f} -> {out_dir / 'audition.html'}")

    write_index(out_root, reports, args.vibe)
    summary = {
        "vibe": args.vibe,
        "attempts": attempts,
        "count": len(reports),
        "index": str(out_root / "index.html"),
        "candidates": [
            {
                "name": r["name"],
                "clean": r["stability"]["clean"],
                "max_pole_radius": r["stability"]["max_pole_radius"],
                "audition": r["outputs"]["audition"],
                "body240": r["outputs"]["body240"],
                "cart_json": r["outputs"]["cart_json"],
            }
            for r in reports
        ],
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"index -> {out_root / 'index.html'}")
    print(f"summary -> {out_root / 'summary.json'}")
    return 0 if len(reports) == args.count else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
