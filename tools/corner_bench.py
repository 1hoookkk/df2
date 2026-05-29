#!/usr/bin/env python3
"""Corner Bench — an audition + mutation surface for a 240-byte body.

The body is the 240 bytes; the vocabulary is the SOUND, not the words. Nothing
here authors stages, roles, BodySpec, Actors, or freq/Q tables. You roll a body,
hear it, mutate it, undo, A/B it, and keep the ones that bite. Every render
reuses the exact teleport_stress signal path, so what you hear is the runtime.

The verbs:
  random   roll a fresh body (gated stable + no pedestal)
  mutate   nudge the current body by one random stable move
  undo     step the current body back one move
  (A/B)    every page plays before-vs-now side by side
  teleport teleport-stress rack (noise / strobe / derivative)
  save     --save-keeper NAME  ->  dev/tmp/keepers/

    python tools/corner_bench.py --random
    python tools/corner_bench.py --mutate          # again, and again, by ear
    python tools/corner_bench.py --undo
    python tools/corner_bench.py --save-keeper rust_choir

Load an existing body to audition / continue it:
    python tools/corner_bench.py bodies/keeper_04.cart.json

The raw packed words are an emergency hatch (hidden in the audition page, and
the explicit --corner/--row/--word/--delta poke) — not the vocabulary.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import wavfile

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
for _p in (str(ROOT), str(TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import author_body as ab  # noqa: E402
import teleport_stress as ts  # noqa: E402
from pyruntime import packed_interp as pi  # noqa: E402  (the delegation chokepoint)
import packed_random as pr  # noqa: E402  (single owner: random body + stability gate)

CORNER_ORDER = ab.CORNER_ORDER  # M0_Q0, M100_Q0, M0_Q100, M100_Q100
RAW_BYTES = ab.RAW_BYTES  # 240
STAGES = ab.STAGES  # 6
WORDS_PER_STAGE = ab.WORDS_PER_STAGE  # 5
AUTHORING_SR = ab.AUTHORING_SR

OUT = ROOT / "dev" / "tmp" / "corner_bench"
KEEPERS = ROOT / "dev" / "tmp" / "keepers"
HISTORY = OUT / "history.json"

RAW_SUFFIXES = (".body240", ".bin", ".bytes", ".raw")


class BenchError(Exception):
    pass


# ── loading: anything -> (name, boost, 240 bytes) ──────────────────────────────


def _words_from_cart_json(doc: dict[str, Any], path: Path) -> tuple[str, float, dict[str, list[tuple[int, ...]]]]:
    by_label = {kf.get("label"): kf for kf in doc.get("keyframes", [])}
    missing = [label for label in CORNER_ORDER if label not in by_label]
    if missing:
        raise BenchError(f"{path}: missing corner(s): {', '.join(missing)}")
    words: dict[str, list[tuple[int, ...]]] = {}
    boost = 1.0
    for label in CORNER_ORDER:
        kf = by_label[label]
        rows = kf.get("packedWords")
        if not rows:
            raise BenchError(
                f"{path}: {label} has no packedWords; the bench needs the 240-byte body"
            )
        if len(rows) != STAGES or any(len(r) != WORDS_PER_STAGE for r in rows):
            raise BenchError(f"{path}: {label}.packedWords must be {STAGES} x {WORDS_PER_STAGE}")
        words[label] = [tuple(int(v) & 0xFFFF for v in r) for r in rows]
        boost = float(kf.get("boost", boost))
    name = str(doc.get("name") or path.stem)
    return name, boost, words


def load_body(path: Path) -> tuple[str, float, bytes]:
    """Load any supported container down to (name, boost, exactly 240 bytes)."""
    suffix = path.suffix.lower()
    if suffix in RAW_SUFFIXES:
        raw = path.read_bytes()
        if len(raw) != RAW_BYTES:
            raise BenchError(f"{path}: raw body must be exactly {RAW_BYTES} bytes, got {len(raw)}")
        return path.stem, 1.0, raw

    if suffix == ".json":
        doc = json.loads(path.read_text(encoding="utf-8"))
        fmt = doc.get("format")
        if fmt == "compiled-v1":
            name, boost, words = _words_from_cart_json(doc, path)
            return name, boost, ab.raw_from_words(words)
        # packed-body-v1 JSON falls through to author_body's parser.

    name, boost, words = ab.load_packed_words(path)
    return name, boost, ab.raw_from_words(words)


def words_from_bytes(raw: bytes) -> dict[str, list[tuple[int, ...]]]:
    return ab.words_from_raw(raw)


def corners_abcd(words: dict[str, list[tuple[int, ...]]]) -> dict[str, list[tuple[int, ...]]]:
    return {
        ts.LABEL_TO_KEY[label]: [tuple(int(v) & 0xFFFF for v in row) for row in words[label]]
        for label in CORNER_ORDER
    }


# ── mutation ───────────────────────────────────────────────────────────────────


def apply_mutation(words: dict[str, list[tuple[int, ...]]],
                   corner: str, row: int, word: int, delta: int) -> tuple[int, int]:
    if corner not in CORNER_ORDER:
        raise BenchError(f"--corner must be one of {', '.join(CORNER_ORDER)}")
    if not (0 <= row < STAGES):
        raise BenchError(f"--row must be 0..{STAGES - 1}")
    if not (0 <= word < WORDS_PER_STAGE):
        raise BenchError(f"--word must be 0..{WORDS_PER_STAGE - 1}")
    rows = [list(r) for r in words[corner]]
    old = int(rows[row][word]) & 0xFFFF
    new = (old + int(delta)) & 0xFFFF  # packed-domain wrap, faithful to lerp_u16
    rows[row][word] = new
    words[corner] = [tuple(r) for r in rows]
    return old, new


def random_stable_mutation(words: dict[str, list[tuple[int, ...]]], amount: int) -> tuple[str, int, int, int]:
    """Pick a random (corner,row,word) and a signed delta that leaves the poked
    stage stable. By ear, not by design — the move is blind on purpose. Never
    touches one row 'as a job'; it's a random nudge to the 240 bytes."""
    amount = max(1, int(amount))
    corner, row, word, delta = CORNER_ORDER[0], 0, 0, amount
    for _ in range(600):
        corner = random.choice(CORNER_ORDER)
        row = random.randrange(STAGES)
        word = random.randrange(WORDS_PER_STAGE)
        delta = random.randint(-amount, amount)
        if delta == 0:
            continue
        cur = int(words[corner][row][word]) & 0xFFFF
        trial = list(words[corner][row])
        trial[word] = (cur + delta) & 0xFFFF
        if pr.stage_stable(trial):
            return corner, row, word, delta
    return corner, row, word, delta  # best effort; the badge flags any instability


# ── history ─────────────────────────────────────────────────────────────────────


def load_history() -> dict[str, Any] | None:
    if not HISTORY.exists():
        return None
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ── rendering (reuses teleport_stress signal path) ──────────────────────────────


def sweep_drivers(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Slow Lissajous over the morph/Q field so every corner is audited by ear."""
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    morph = 0.5 - 0.5 * np.cos(2.0 * np.pi * 2.0 * t)   # 2 full passes
    q = 0.5 - 0.5 * np.cos(2.0 * np.pi * 0.5 * t)        # one slow 0->1 ramp
    return morph, q


def render_sweep(words: dict[str, list[tuple[int, ...]]], out_path: Path,
                 sr: int, seconds: float, drive: float) -> tuple[dict, dict]:
    n = int(round(seconds * sr))
    x = ts.source_signal(n, sr)
    morph, q = sweep_drivers(n)
    corners = corners_abcd(words)
    wet, dyn = ts.process_teleport(corners, x, morph, q, sr, drive)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(out_path, sr, wet)
    static = ts.static_probe(corners, morph, q)
    return dyn, static


def render_teleports(words: dict[str, list[tuple[int, ...]]], out_dir: Path,
                     sr: int, seconds: float, seed: int, drive: float,
                     source: np.ndarray) -> dict[str, dict]:
    corners = corners_abcd(words)
    modes: dict[str, dict] = {}
    for mode in ("noise", "square_150hz", "derivative"):
        morph, q = ts.drivers(mode, source, sr, seed)
        static = ts.static_probe(corners, morph, q)
        wet, dyn = ts.process_teleport(corners, source, morph, q, sr, drive)
        wavfile.write(out_dir / f"teleport_{mode}.wav", sr, wet)
        modes[mode] = {"static_probe": static, "dynamic": dyn}
    return modes


def aggregate_stability(sweep_static: dict, sweep_dyn: dict, modes: dict[str, dict]) -> dict:
    nonfinite_state = int(sweep_dyn["nonfinite_state_events"])
    nonfinite_coeff = int(sweep_static["nonfinite_coeff_rows"])
    unstable = int(sweep_static["unstable_denominator_rows"])
    max_r = float(sweep_static["max_pole_radius"])
    for info in modes.values():
        nonfinite_state += int(info["dynamic"]["nonfinite_state_events"])
        nonfinite_coeff += int(info["static_probe"]["nonfinite_coeff_rows"])
        unstable += int(info["static_probe"]["unstable_denominator_rows"])
        max_r = max(max_r, float(info["static_probe"]["max_pole_radius"]))
    return {
        "nonfinite_state_events": nonfinite_state,
        "nonfinite_coeff_rows": nonfinite_coeff,
        "unstable_denominator_rows": unstable,
        "max_pole_radius": max_r,
        "clean": nonfinite_state == 0 and nonfinite_coeff == 0 and unstable == 0,
    }


# ── audition.html (players first) ───────────────────────────────────────────────


def _hex_table(words: dict[str, list[tuple[int, ...]]], hot: tuple[str, int, int] | None) -> str:
    blocks = []
    for label in CORNER_ORDER:
        rows_html = []
        for ri, row in enumerate(words[label]):
            cells = []
            for wi, w in enumerate(row):
                is_hot = hot is not None and hot == (label, ri, wi)
                cls = ' class="hot"' if is_hot else ""
                cells.append(f"<td{cls}>{int(w) & 0xFFFF:04X}</td>")
            rows_html.append(f"<tr><th>r{ri}</th>{''.join(cells)}</tr>")
        blocks.append(
            f'<div class="corner"><h3>{label}</h3>'
            f'<table><tr><th></th><th>w0</th><th>w1</th><th>w2</th><th>w3</th><th>w4</th></tr>'
            f"{''.join(rows_html)}</table></div>"
        )
    return f'<div class="grid">{"".join(blocks)}</div>'


def _history_html(hist: dict[str, Any]) -> str:
    muts = hist.get("mutations", [])
    if not muts:
        return "<p class='muted'>no mutations yet — this is the original body.</p>"
    rows = []
    for i, m in enumerate(muts, 1):
        rows.append(
            f"<tr><td>{i}</td><td>{m['corner']}</td><td>r{m['row']} w{m['word']}</td>"
            f"<td>{m['delta']:+d} (0x{m['delta'] & 0xFFFF:04X})</td>"
            f"<td>{m['old']:04X} &rarr; {m['new']:04X}</td></tr>"
        )
    return (
        "<table class='hist'><tr><th>#</th><th>corner</th><th>cell</th>"
        "<th>delta</th><th>word</th></tr>" + "".join(rows) + "</table>"
    )


def write_audition_html(path: Path, report: dict[str, Any],
                        words: dict[str, list[tuple[int, ...]]],
                        hist: dict[str, Any],
                        hot: tuple[str, int, int] | None) -> None:
    stab = report["stability"]
    badge = "clean" if stab["clean"] else "UNSTABLE"
    badge_cls = "ok" if stab["clean"] else "bad"
    teleports = "".join(
        f"""
        <section class="player">
          <h3>{title}</h3>
          <p class="muted">{desc}</p>
          <audio controls preload="none" src="{wav}"></audio>
          <span class="stat">peak {report['modes'][key]['dynamic']['output_peak']:.3f} ·
          max r {report['modes'][key]['static_probe']['max_pole_radius']:.4f} ·
          nonfinite {report['modes'][key]['dynamic']['nonfinite_state_events']}</span>
        </section>"""
        for key, wav, title, desc in (
            ("noise", "teleport_noise.wav", "Noise Teleport", "random Morph/Q every sample"),
            ("square_150hz", "teleport_square_150hz.wav", "150 Hz Strobe", "hard Morph square, Q pinned hot"),
            ("derivative", "teleport_derivative.wav", "Derivative Rip", "input slope drives Morph/Q"),
        )
    )
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Corner Bench — {report['name']}</title>
<style>
  body{{margin:0;background:#090b0b;color:#ece9df;font:14px/1.45 system-ui,Segoe UI,sans-serif}}
  main{{max-width:1040px;margin:0 auto;padding:26px 20px 56px}}
  h1{{font-size:23px;margin:0 0 2px}}
  h2{{font-size:15px;letter-spacing:.08em;text-transform:uppercase;color:#7fd6b0;margin:30px 0 10px;border-bottom:1px solid #1d2422;padding-bottom:6px}}
  h3{{font-size:15px;margin:0 0 4px}}
  .muted{{color:#8f928a;margin:.2em 0 .5em}}
  audio{{width:100%;margin:4px 0}}
  .player{{margin:0 0 14px}}
  .stat{{font:12px ui-monospace,Consolas,monospace;color:#f6d76b}}
  .ab{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  .corner h3{{color:#9fe7c6}}
  table{{border-collapse:collapse;font:12px ui-monospace,Consolas,monospace}}
  td,th{{border:1px solid #20302b;padding:3px 8px;text-align:right;color:#cfe8dd}}
  th{{color:#6f9c8a}}
  td.hot{{background:#f6d76b;color:#111;font-weight:700}}
  .hist td,.hist th{{text-align:left}}
  .badge{{font:12px ui-monospace,Consolas,monospace;padding:2px 8px;border-radius:3px}}
  .badge.ok{{background:#173d2c;color:#7fe0aa}}
  .badge.bad{{background:#4a1414;color:#ff8a8a}}
  code{{background:#11201b;padding:1px 6px;border-radius:3px;color:#bfe}}
  details.hatch{{margin-top:30px;border-top:1px solid #1d2422;padding-top:10px}}
  details.hatch>summary{{cursor:pointer;color:#5f7d70;font:12px ui-monospace,Consolas,monospace}}
  details.hatch h3{{color:#6f9c8a;margin:16px 0 4px;font-size:13px}}
</style>
<main>
  <h1>Corner Bench — {report['name']}</h1>
  <p class="muted">origin: <code>{hist.get('origin_source','?')}</code> ·
     <span class="badge {badge_cls}">{badge}</span></p>

  <h2>A / B — before vs now</h2>
  <div class="ab">
    <section class="player">
      <h3>A — before</h3>
      <p class="muted">the body before this session's moves</p>
      <audio controls preload="none" src="sweep_slow_original.wav"></audio>
    </section>
    <section class="player">
      <h3>B — now</h3>
      <p class="muted">current body, full morph/Q field</p>
      <audio controls preload="none" src="sweep_slow.wav"></audio>
    </section>
  </div>

  <h2>Teleport stress</h2>
  {teleports}

  <h2>Keep it</h2>
  <p class="muted">If it bites, name it and keep it:</p>
  <p><code>python tools/corner_bench.py --save-keeper NAME</code></p>

  <details class="hatch">
    <summary>raw words &amp; moves — emergency hatch (the sound is the vocabulary, not this)</summary>
    <h3>Stability</h3>
    <table class="hist">
      <tr><th>nonfinite state events</th><td>{stab['nonfinite_state_events']}</td></tr>
      <tr><th>nonfinite coeff rows</th><td>{stab['nonfinite_coeff_rows']}</td></tr>
      <tr><th>unstable denominator rows</th><td>{stab['unstable_denominator_rows']}</td></tr>
      <tr><th>max pole radius</th><td>{stab['max_pole_radius']:.6f}</td></tr>
    </table>
    <h3>Current words</h3>
    {_hex_table(words, hot)}
    <h3>Moves this session</h3>
    {_history_html(hist)}
  </details>
</main>
"""
    path.write_text(html, encoding="utf-8")


# ── keeper ───────────────────────────────────────────────────────────────────────


def save_keeper(body: Path, keeper_name: str) -> int:
    try:
        name, boost, raw = load_body(body)
    except (BenchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"corner_bench error: {exc}", file=sys.stderr)
        return 1
    KEEPERS.mkdir(parents=True, exist_ok=True)
    body240 = KEEPERS / f"{keeper_name}.body240"
    cart = KEEPERS / f"{keeper_name}.cart.json"
    body240.write_bytes(raw)
    payload = ab.compiled_payload(keeper_name, boost, words_from_bytes(raw))
    cart.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"keeper -> {body240} ({len(raw)} bytes)")
    print(f"keeper -> {cart}")
    return 0


# ── main ───────────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("body", type=Path, nargs="?",
                    help=".body240 / compiled cart JSON / packed-body-v1 — omit for --random/--mutate/--undo")
    ap.add_argument("--random", action="store_true",
                    help="roll a fresh random body (gated stable + no pedestal) as the new current")
    ap.add_argument("--mutate", action="store_true",
                    help="nudge the current body by one random stable move (by ear, not by design)")
    ap.add_argument("--undo", action="store_true", help="step the current body back one move")
    ap.add_argument("--pick", type=lambda s: int(s, 0), default=None,
                    help="seed for --random/--mutate (reproducible); default entropy")
    ap.add_argument("--amount", type=lambda s: int(s, 0), default=0x0A00,
                    help="max packed delta for --mutate")
    # emergency hatch — explicit word poke (not the vocabulary):
    ap.add_argument("--corner", choices=CORNER_ORDER, help="[hatch] corner to poke")
    ap.add_argument("--row", type=int, help=f"[hatch] row 0..{STAGES - 1}")
    ap.add_argument("--word", type=int, help=f"[hatch] word 0..{WORDS_PER_STAGE - 1}")
    ap.add_argument("--delta", type=lambda s: int(s, 0), help="[hatch] signed nudge, hex (0x..) or int")
    ap.add_argument("--save-keeper", metavar="NAME", default=None, help="save current body to dev/tmp/keepers/")
    ap.add_argument("--name", default=None, help="override body name")
    ap.add_argument("--sr", type=int, default=44_100)
    ap.add_argument("--seconds-sweep", type=float, default=2.5)
    ap.add_argument("--seconds-teleport", type=float, default=1.2)
    ap.add_argument("--seed", type=int, default=0x513DF2, help="teleport-driver seed")
    ap.add_argument("--containment-drive", type=float, default=4.0)
    ap.add_argument("--require-core", action="store_true",
                    help="fail unless interpolation runs through the shipped trench-core (FFI)")
    args = ap.parse_args(argv)

    backend = pi.core_backend()
    if args.require_core and not pi.core_available():
        print("corner_bench error: trench-core FFI not available "
              f"(backend={backend}); build it with `cargo build -p trench-core`", file=sys.stderr)
        return 1
    print(f"interp   -> {backend}"
          + (f" [{pi._core.lib_path()}]" if pi.core_available() else ""))

    OUT.mkdir(parents=True, exist_ok=True)
    out_current = OUT / "current.body240"

    if args.save_keeper:
        return save_keeper(args.body or out_current, args.save_keeper)

    name = "body"
    boost = 1.0
    hot: tuple[str, int, int] | None = None
    hist: dict[str, Any] | None = None

    # ── choose the working body + history per verb ───────────────────────────────
    if args.random:
        seed = args.pick if args.pick is not None else random.randrange(1 << 32)
        print(f"random   -> seed 0x{seed:08X}")
        corners, emergence = pr.random_body(seed=seed)
        words = {label: corners[i] for i, label in enumerate(CORNER_ORDER)}
        name = args.name or f"random_{seed & 0xFFFF:04X}"
        raw0 = ab.raw_from_words(words)
        hist = {
            "origin_source": f"random(seed=0x{seed:08X})",
            "origin_name": name, "origin_bytes_hex": raw0.hex(),
            "boost": boost, "mutations": [],
        }
        print(f"emergence-> {emergence:.2f} dB (middle vs corner mean)")

    elif args.mutate or args.undo:
        hist = load_history()
        if hist is None or not out_current.exists():
            print("corner_bench error: no current body — load one or use --random first", file=sys.stderr)
            return 1
        name = args.name or hist.get("origin_name", "body")
        boost = float(hist.get("boost", 1.0))
        words = copy.deepcopy(words_from_bytes(out_current.read_bytes()))
        if args.mutate:
            if args.pick is not None:
                random.seed(args.pick)
            corner, row, word, delta = random_stable_mutation(words, args.amount)
            old, new = apply_mutation(words, corner, row, word, delta)
            hist["mutations"].append({"corner": corner, "row": row, "word": word,
                                      "delta": int(delta), "old": old, "new": new})
            hot = (corner, row, word)
            print(f"mutate   -> {corner} r{row} w{word}: {old:04X} -> {new:04X} ({delta:+d})")
        else:
            if not hist["mutations"]:
                print("corner_bench error: nothing to undo", file=sys.stderr)
                return 1
            m = hist["mutations"].pop()
            old, new = apply_mutation(words, m["corner"], m["row"], m["word"], -int(m["delta"]))
            hot = (m["corner"], m["row"], m["word"])
            print(f"undo     -> {m['corner']} r{m['row']} w{m['word']}: {old:04X} -> {new:04X}")

    else:
        if args.body is None:
            print("corner_bench error: give a body path, or use --random / --mutate / --undo",
                  file=sys.stderr)
            return 1
        try:
            name, boost, raw_in = load_body(args.body)
        except (BenchError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"corner_bench error: {exc}", file=sys.stderr)
            return 1
        if args.name:
            name = args.name
        continuing = HISTORY.exists() and args.body.resolve() == out_current.resolve()
        hist = load_history() if continuing else None
        if hist is None:
            hist = {"origin_source": str(args.body), "origin_name": name,
                    "origin_bytes_hex": raw_in.hex(), "boost": boost, "mutations": []}
        words = copy.deepcopy(words_from_bytes(raw_in))
        if args.corner is not None:  # hatch poke
            if args.row is None or args.word is None or args.delta is None:
                print("corner_bench error: --corner requires --row, --word and --delta", file=sys.stderr)
                return 1
            try:
                old, new = apply_mutation(words, args.corner, args.row, args.word, args.delta)
            except BenchError as exc:
                print(f"corner_bench error: {exc}", file=sys.stderr)
                return 1
            hist["mutations"].append({"corner": args.corner, "row": args.row, "word": args.word,
                                      "delta": int(args.delta), "old": old, "new": new})
            hot = (args.corner, args.row, args.word)
            print(f"poke     -> {args.corner} r{args.row} w{args.word}: {old:04X} -> {new:04X} ({int(args.delta):+d})")

    mutated_bytes = ab.raw_from_words(words)
    assert len(mutated_bytes) == RAW_BYTES, f"mutated body must be {RAW_BYTES} bytes"

    # ── write current + cart, render A/B + teleport ──────────────────────────────
    out_current.write_bytes(mutated_bytes)
    payload = ab.compiled_payload(name, boost, words)
    (OUT / "current.cart.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    origin_bytes = bytes.fromhex(hist["origin_bytes_hex"])
    origin_words = words_from_bytes(origin_bytes)

    render_sweep(origin_words, OUT / "sweep_slow_original.wav",
                 args.sr, args.seconds_sweep, args.containment_drive)
    sweep_dyn, sweep_static = render_sweep(words, OUT / "sweep_slow.wav",
                                           args.sr, args.seconds_sweep, args.containment_drive)

    source = ts.source_signal(int(round(args.seconds_teleport * args.sr)), args.sr)
    modes = render_teleports(words, OUT, args.sr, args.seconds_teleport,
                             args.seed, args.containment_drive, source)

    stability = aggregate_stability(sweep_static, sweep_dyn, modes)

    report = {
        "name": name,
        "source": str(args.body) if args.body else hist["origin_source"],
        "sample_rate": args.sr,
        "doctrine": "the body is the 240 bytes; the sound is the vocabulary; one move at a time",
        "sweep": {"dynamic": sweep_dyn, "static_probe": sweep_static},
        "modes": modes,
        "stability": stability,
        "mutations": hist["mutations"],
        "outputs": {
            "body240": str(OUT / "current.body240"),
            "cart_json": str(OUT / "current.cart.json"),
            "sweep_original": str(OUT / "sweep_slow_original.wav"),
            "sweep": str(OUT / "sweep_slow.wav"),
            "teleport_noise": str(OUT / "teleport_noise.wav"),
            "teleport_square_150hz": str(OUT / "teleport_square_150hz.wav"),
            "teleport_derivative": str(OUT / "teleport_derivative.wav"),
            "audition": str(OUT / "audition.html"),
        },
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_audition_html(OUT / "audition.html", report, words, hist, hot)
    HISTORY.write_text(json.dumps(hist, indent=2), encoding="utf-8")

    print(f"body     -> {name}")
    print(f"current  -> {OUT / 'current.body240'}")
    print(f"audition -> {OUT / 'audition.html'}")
    print(
        f"stability: nonfinite={stability['nonfinite_state_events']} "
        f"coeff_nonfinite={stability['nonfinite_coeff_rows']} "
        f"unstable_rows={stability['unstable_denominator_rows']} "
        f"max_r={stability['max_pole_radius']:.6f} "
        f"{'CLEAN' if stability['clean'] else 'UNSTABLE'}"
    )
    print(f"moves    -> {len(hist['mutations'])} this session")
    if args.random:
        print("mutate   -> python tools/corner_bench.py --mutate    (again, by ear)")
    print("keep it  -> python tools/corner_bench.py --save-keeper NAME")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
