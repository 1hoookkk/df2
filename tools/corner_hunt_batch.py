#!/usr/bin/env python3
"""Corner Hunt Batch - make a small playable rack of packed-word candidates.

This is not a solver and not a stage author. It starts from one 240-byte body,
applies a few weighted packed-word nudges, renders WAVs, and writes an audition
rack. The point is to pick apples by ear.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import random
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
import teleport_stress as ts  # noqa: E402


DELTAS = (-0x0800, -0x0200, -0x0040, -0x0008, 0x0008, 0x0040, 0x0200, 0x0800)
CORNER_WEIGHTS = {
    "M100_Q100": 46,
    "M0_Q100": 28,
    "M100_Q0": 20,
    "M0_Q0": 6,
}
WORD_WEIGHTS = {0: 18, 1: 12, 2: 26, 3: 28, 4: 16}
MATERIAL_NAMES = (
    "glass_throat",
    "wire_mouth",
    "radio_teeth",
    "burnt_bell",
    "chrome_cough",
    "rust_choir",
    "mouth_shrapnel",
    "concrete_angel",
)


def weighted_choice(rng: random.Random, weights: dict[Any, int]) -> Any:
    return rng.choices(tuple(weights.keys()), weights=tuple(weights.values()), k=1)[0]


def mutate(words: dict[str, list[tuple[int, ...]]],
           rng: random.Random, count: int) -> list[dict[str, Any]]:
    mutations: list[dict[str, Any]] = []
    for _ in range(count):
        corner = weighted_choice(rng, CORNER_WEIGHTS)
        row = rng.randrange(cb.STAGES)
        word = weighted_choice(rng, WORD_WEIGHTS)
        delta = rng.choice(DELTAS)
        old, new = cb.apply_mutation(words, corner, row, word, delta)
        mutations.append({
            "kind": "random",
            "corner": corner,
            "row": row,
            "word": word,
            "delta": int(delta),
            "old": old,
            "new": new,
        })
    return mutations


def render_candidate(name: str,
                     origin_name: str,
                     origin_source: Path,
                     boost: float,
                     origin_raw: bytes,
                     words: dict[str, list[tuple[int, ...]]],
                     mutations: list[dict[str, Any]],
                     out_dir: Path,
                     sr: int,
                     seconds_sweep: float,
                     seconds_teleport: float,
                     seed: int,
                     drive: float) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = ab.raw_from_words(words)
    (out_dir / f"{name}.body240").write_bytes(raw)
    (out_dir / f"{name}.cart.json").write_text(
        json.dumps(ab.compiled_payload(name, boost, words), indent=2) + "\n",
        encoding="utf-8",
    )

    origin_words = cb.words_from_bytes(origin_raw)
    cb.render_sweep(origin_words, out_dir / "sweep_slow_original.wav",
                    sr, seconds_sweep, drive)
    sweep_dyn, sweep_static = cb.render_sweep(words, out_dir / "sweep_slow.wav",
                                             sr, seconds_sweep, drive)

    source = ts.source_signal(int(round(seconds_teleport * sr)), sr)
    modes = cb.render_teleports(words, out_dir, sr, seconds_teleport, seed, drive, source)
    stability = cb.aggregate_stability(sweep_static, sweep_dyn, modes)
    hot = None
    if mutations:
        last = mutations[-1]
        hot = (last["corner"], int(last["row"]), int(last["word"]))

    hist = {
        "origin_source": str(origin_source),
        "origin_name": origin_name,
        "origin_bytes_hex": origin_raw.hex(),
        "mutations": mutations,
    }
    report = {
        "name": name,
        "source": str(origin_source),
        "sample_rate": sr,
        "batch_hunt": True,
        "sweep": {"dynamic": sweep_dyn, "static_probe": sweep_static},
        "modes": modes,
        "stability": stability,
        "mutations": mutations,
        "outputs": {
            "body240": str(out_dir / f"{name}.body240"),
            "cart_json": str(out_dir / f"{name}.cart.json"),
            "sweep_original": str(out_dir / "sweep_slow_original.wav"),
            "sweep": str(out_dir / "sweep_slow.wav"),
            "teleport_noise": str(out_dir / "teleport_noise.wav"),
            "teleport_square_150hz": str(out_dir / "teleport_square_150hz.wav"),
            "teleport_derivative": str(out_dir / "teleport_derivative.wav"),
            "audition": str(out_dir / "audition.html"),
        },
    }
    (out_dir / "history.json").write_text(json.dumps(hist, indent=2), encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    cb.write_audition_html(out_dir / "audition.html", report, words, hist, hot)
    return report


def save_keeper_copy(name: str, report: dict[str, Any]) -> None:
    cb.KEEPERS.mkdir(parents=True, exist_ok=True)
    body = Path(report["outputs"]["body240"])
    cart = Path(report["outputs"]["cart_json"])
    (cb.KEEPERS / f"{name}.body240").write_bytes(body.read_bytes())
    (cb.KEEPERS / f"{name}.cart.json").write_text(cart.read_text(encoding="utf-8"),
                                                  encoding="utf-8")


def write_index(out_root: Path, reports: list[dict[str, Any]]) -> None:
    cards = []
    for report in reports:
        name = report["name"]
        rel = html.escape(name)
        stab = report["stability"]
        cards.append(f"""
<section class="card">
  <h2>{html.escape(name)}</h2>
  <p class="meta">clean={str(stab['clean']).lower()} max_r={stab['max_pole_radius']:.6f}
     mutations={len(report['mutations'])}</p>
  <a href="{rel}/audition.html">open full audition</a>
  <div class="players">
    <label>slow sweep<audio controls preload="none" src="{rel}/sweep_slow.wav"></audio></label>
    <label>noise teleport<audio controls preload="none" src="{rel}/teleport_noise.wav"></audio></label>
    <label>150 Hz strobe<audio controls preload="none" src="{rel}/teleport_square_150hz.wav"></audio></label>
    <label>derivative<audio controls preload="none" src="{rel}/teleport_derivative.wav"></audio></label>
  </div>
</section>""")
    html_doc = f"""<!doctype html>
<meta charset="utf-8">
<title>Corner Hunt Batch</title>
<style>
body{{margin:0;background:#080a0a;color:#eee9dc;font:14px/1.4 system-ui,Segoe UI,sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:24px 18px 52px}}
h1{{font-size:24px;margin:0 0 4px}}
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
  <h1>Corner Hunt Batch</h1>
  <p class="muted">Generated from one 240-byte seed by packed-word nudges. These are audition candidates, not scored winners.</p>
  {''.join(cards)}
</main>
"""
    (out_root / "index.html").write_text(html_doc, encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("body", type=Path)
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--mutations-min", type=int, default=2)
    ap.add_argument("--mutations-max", type=int, default=5)
    ap.add_argument("--attempts", type=int, default=80)
    ap.add_argument("--out", type=Path, default=ROOT / "dev" / "tmp" / "keeper_hunt")
    ap.add_argument("--save-keepers", action="store_true",
                    help="also copy candidate .body240/.cart.json to dev/tmp/keepers")
    ap.add_argument("--sr", type=int, default=44_100)
    ap.add_argument("--seconds-sweep", type=float, default=1.0)
    ap.add_argument("--seconds-teleport", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=0x513DF2)
    ap.add_argument("--containment-drive", type=float, default=4.0)
    args = ap.parse_args(argv)

    if args.mutations_min < 1 or args.mutations_max < args.mutations_min:
        print("corner_hunt_batch error: invalid mutation range", file=sys.stderr)
        return 2

    origin_name, boost, origin_raw = cb.load_body(args.body)
    origin_words = cb.words_from_bytes(origin_raw)
    rng = random.Random(args.seed)
    reports: list[dict[str, Any]] = []
    attempts = 0

    args.out.mkdir(parents=True, exist_ok=True)
    while len(reports) < args.count and attempts < args.attempts:
        attempts += 1
        words = copy.deepcopy(origin_words)
        n_mutations = rng.randint(args.mutations_min, args.mutations_max)
        mutations = mutate(words, rng, n_mutations)
        name = f"{MATERIAL_NAMES[len(reports) % len(MATERIAL_NAMES)]}_{len(reports) + 1:02d}"
        out_dir = args.out / name
        report = render_candidate(name, origin_name, args.body, boost, origin_raw,
                                  words, mutations, out_dir, args.sr,
                                  args.seconds_sweep, args.seconds_teleport,
                                  args.seed + attempts, args.containment_drive)
        if not report["stability"]["clean"]:
            continue
        reports.append(report)
        if args.save_keepers:
            save_keeper_copy(name, report)
        print(
            f"{name}: clean max_r={report['stability']['max_pole_radius']:.6f} "
            f"mutations={len(mutations)} -> {out_dir / 'audition.html'}"
        )

    write_index(args.out, reports)
    summary = {
        "source": str(args.body),
        "attempts": attempts,
        "count": len(reports),
        "index": str(args.out / "index.html"),
        "candidates": [
            {
                "name": r["name"],
                "max_pole_radius": r["stability"]["max_pole_radius"],
                "mutations": len(r["mutations"]),
                "audition": r["outputs"]["audition"],
                "body240": r["outputs"]["body240"],
                "cart_json": r["outputs"]["cart_json"],
            }
            for r in reports
        ],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"index -> {args.out / 'index.html'}")
    print(f"summary -> {args.out / 'summary.json'}")
    return 0 if len(reports) == args.count else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
