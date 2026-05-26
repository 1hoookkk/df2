#!/usr/bin/env python3
"""Corner Bench — poke a 240-byte body, hear it, keep the ones that bite.

The body is the 240 bytes. Nothing here authors stages, BodySpec, Actors, EQ
primitives, or all-pole/LPC anything. You load a body, nudge a single packed
u16 word, and the bench re-renders WAVs so you can decide by ear. The renders
reuse the exact teleport_stress signal path, so what you hear here is what the
runtime does.

Inputs (all collapse to BodyBytes240 internally):
  - raw .body240 / .bin / .bytes / .raw
  - compiled cart JSON with packedWords
  - packed-body-v1 TOML/JSON

Poke one word:
  python tools/corner_bench.py bodies/neon_vane.body240 \
      --corner M100_Q100 --row 2 --word 3 --delta 0x0040

Keep one:
  python tools/corner_bench.py dev/tmp/corner_bench/current.body240 \
      --save-keeper my_keeper
"""
from __future__ import annotations

import argparse
import copy
import json
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
</style>
<main>
  <h1>Corner Bench — {report['name']}</h1>
  <p class="muted">origin: <code>{hist.get('origin_source','?')}</code> ·
     <span class="badge {badge_cls}">{badge}</span> ·
     max pole r {stab['max_pole_radius']:.5f}</p>

  <h2>Listen — original vs mutated</h2>
  <div class="ab">
    <section class="player">
      <h3>Original — slow sweep</h3>
      <p class="muted">the body before this session's pokes</p>
      <audio controls preload="none" src="sweep_slow_original.wav"></audio>
    </section>
    <section class="player">
      <h3>Mutated — slow sweep</h3>
      <p class="muted">current body, full morph/Q field</p>
      <audio controls preload="none" src="sweep_slow.wav"></audio>
    </section>
  </div>

  <h2>Teleport stress (mutated)</h2>
  {teleports}

  <h2>Current words (hex)</h2>
  {_hex_table(words, hot)}

  <h2>Mutation history</h2>
  {_history_html(hist)}

  <h2>Stability</h2>
  <table class="hist">
    <tr><th>nonfinite state events</th><td>{stab['nonfinite_state_events']}</td></tr>
    <tr><th>nonfinite coeff rows</th><td>{stab['nonfinite_coeff_rows']}</td></tr>
    <tr><th>unstable denominator rows</th><td>{stab['unstable_denominator_rows']}</td></tr>
    <tr><th>max pole radius</th><td>{stab['max_pole_radius']:.6f}</td></tr>
  </table>

  <h2>Keep it</h2>
  <p class="muted">If it bites, save it:</p>
  <p><code>python tools/corner_bench.py dev/tmp/corner_bench/current.body240 --save-keeper NAME</code></p>
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
    ap.add_argument("body", type=Path, help=".body240, compiled cart JSON, or packed-body-v1 TOML/JSON")
    ap.add_argument("--corner", choices=CORNER_ORDER, help="corner to poke")
    ap.add_argument("--row", type=int, help=f"stage row 0..{STAGES - 1}")
    ap.add_argument("--word", type=int, help=f"word 0..{WORDS_PER_STAGE - 1}")
    ap.add_argument("--delta", type=lambda s: int(s, 0), help="signed nudge, hex (0x..) or int")
    ap.add_argument("--save-keeper", metavar="NAME", default=None, help="save this body to dev/tmp/keepers/")
    ap.add_argument("--name", default=None, help="override body name")
    ap.add_argument("--sr", type=int, default=44_100)
    ap.add_argument("--seconds-sweep", type=float, default=2.5)
    ap.add_argument("--seconds-teleport", type=float, default=1.2)
    ap.add_argument("--seed", type=int, default=0x513DF2)
    ap.add_argument("--containment-drive", type=float, default=4.0)
    args = ap.parse_args(argv)

    if args.save_keeper:
        return save_keeper(args.body, args.save_keeper)

    # 1. load -> 240 bytes
    try:
        name, boost, raw_in = load_body(args.body)
    except (BenchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"corner_bench error: {exc}", file=sys.stderr)
        return 1
    if args.name:
        name = args.name

    # 2. session continuity: only continue when re-poking our own current body
    out_current = OUT / "current.body240"
    continuing = HISTORY.exists() and args.body.resolve() == out_current.resolve()
    hist = load_history() if continuing else None
    if hist is None:
        hist = {
            "origin_source": str(args.body),
            "origin_name": name,
            "origin_bytes_hex": raw_in.hex(),
            "mutations": [],
        }

    # 3. apply mutation (if any)
    words = copy.deepcopy(words_from_bytes(raw_in))
    hot: tuple[str, int, int] | None = None
    if args.corner is not None:
        if args.row is None or args.word is None or args.delta is None:
            print("corner_bench error: --corner requires --row, --word and --delta", file=sys.stderr)
            return 1
        try:
            old, new = apply_mutation(words, args.corner, args.row, args.word, args.delta)
        except BenchError as exc:
            print(f"corner_bench error: {exc}", file=sys.stderr)
            return 1
        hist["mutations"].append({
            "corner": args.corner, "row": args.row, "word": args.word,
            "delta": int(args.delta), "old": old, "new": new,
        })
        hot = (args.corner, args.row, args.word)
        print(f"poke {args.corner} r{args.row} w{args.word}: {old:04X} -> {new:04X} ({int(args.delta):+d})")

    mutated_bytes = ab.raw_from_words(words)
    assert len(mutated_bytes) == RAW_BYTES, f"mutated body must be {RAW_BYTES} bytes"

    # 4. write current + cart, then render both original and mutated
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "current.body240").write_bytes(mutated_bytes)
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

    # 5. report + audition
    report = {
        "name": name,
        "source": str(args.body),
        "sample_rate": args.sr,
        "doctrine": "the body is the 240 bytes; sound first; one packed word at a time",
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

    # 6. summary
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
    print(f"mutations: {len(hist['mutations'])}")
    print("keep it  -> python tools/corner_bench.py dev/tmp/corner_bench/current.body240 --save-keeper NAME")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
