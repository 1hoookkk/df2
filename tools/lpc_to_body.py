#!/usr/bin/env python3
"""lpc_to_body - two recordings -> a manual pole-zero sketch bridge.

LPC is useful denominator evidence, not a complete body compiler. It recovers
candidate resonant poles from each recording. This bridge presents those pools,
asks the author how to spend all six persistent lanes, then asks which
numerator-zero treatment each active actor should carry. It never silently
claims that frequency rank proves lane identity.

For a fitted numerator and denominator from standalone recordings, use
`tools/fit_two_audio_arma.py`. This LPC bridge is deliberately for manual
gesture authoring only.

An ordinary run is interactive:

    python tools/lpc_to_body.py --name "Vowel Glide" \\
        --m0 "dev/tmp/recordings/ah.wav" --m100 "dev/tmp/recordings/ee.wav"

Use --sketch-defaults for a reproducible unattended starter: common frequency
ranks are paired as a sketch, unmatched denominator slots remain passthrough,
and every active actor receives a local cavity zero. The emitted .plan.json
records that approximation beside the packed TOML. It does not claim that lane
identity or authored zeros were recovered from the recording.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.lpc_extract import analyse_wav  # noqa: E402
from tools.corner_words import allpole_words, build_toml_words  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words  # noqa: E402

AUTHORING_SR = 39062.5
NUM_STAGES = 6
Q_POLE_DELTA = 0.02
Q_ZERO_DELTA = 0.03
PASS = coeffs_to_words(2.0, 1.0, 2.0, 1.0, 1.0)

ZERO_ROLE_HELP = {
    "local": "zero 7 semitones below the pole: nearby peak-plus-canyon cavity",
    "remote_low": "zero 2 octaves below the pole: low-body excavation",
    "remote_high": "zero 2 octaves above the pole: air cap / broad counterweight",
    "custom": "explicit zero frequency at each Morph endpoint",
    "none": "deliberate all-pole LPC sketch; incomplete as a reference-style actor",
}
ZERO_ROLE_KEYS = {
    "": "local",
    "l": "local",
    "local": "local",
    "d": "remote_low",
    "low": "remote_low",
    "remote_low": "remote_low",
    "a": "remote_high",
    "air": "remote_high",
    "remote_high": "remote_high",
    "c": "custom",
    "custom": "custom",
    "n": "none",
    "none": "none",
}


@dataclass
class Actor:
    label: str
    pole_m0_hz: float
    radius_m0: float
    pole_m100_hz: float
    radius_m100: float
    source: str
    zero_role: str = "local"
    zero_m0_hz: float | None = None
    zero_m100_hz: float | None = None
    zero_radius: float = 0.90


def poles_of(path: str) -> list[tuple[float, float]]:
    p = Path(path)
    if p.name.endswith(".lpc.json") or p.suffix == ".json":
        d = json.loads(p.read_text())
    else:
        d = analyse_wav(p)
    return [(float(x["freq_hz"]), float(x["radius"])) for x in d["poles"]]


def corner(poles: list[tuple[float, float]], sharp: bool) -> list[tuple[int, ...]]:
    """Legacy all-pole corner helper retained for probes and comparisons."""
    rows = [
        allpole_words(f, min(0.995, r + Q_POLE_DELTA) if sharp else min(r, 0.99))
        for f, r in poles[:NUM_STAGES]
    ]
    while len(rows) < NUM_STAGES:
        rows.append(PASS)
    return rows


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{text}{suffix}: ").strip()
    except EOFError:
        return default
    return value or default


def _pole_ref(
    text: str,
    m0_poles: list[tuple[float, float]],
    m100_poles: list[tuple[float, float]],
) -> tuple[float, float]:
    """Resolve a1/b2 endpoint candidate or an explicit frequency."""
    value = text.strip().lower()
    if len(value) >= 2 and value[0] in {"a", "b"} and value[1:].isdigit():
        poles = m0_poles if value[0] == "a" else m100_poles
        index = int(value[1:]) - 1
        if index < 0 or index >= len(poles):
            raise ValueError(f"{value}: candidate index is out of range")
        return poles[index]
    freq = float(value)
    if not 20.0 <= freq <= AUTHORING_SR * 0.48:
        raise ValueError(f"{freq:g} Hz is outside the 20..{AUTHORING_SR * 0.48:g} Hz authoring band")
    return freq, 0.95


def _print_candidates(label: str, poles: list[tuple[float, float]]) -> None:
    values = "  ".join(f"{label}{i + 1}={f:.0f}Hz/r{r:.4f}" for i, (f, r) in enumerate(poles))
    print(f"  {values or '(none)'}")


def allocate_actors(
    m0_poles: list[tuple[float, float]],
    m100_poles: list[tuple[float, float]],
    sketch_defaults: bool = False,
) -> list[Actor | None]:
    """Ask how to spend fixed lanes; optionally emit an explicit rank-paired sketch."""
    shared = min(len(m0_poles), len(m100_poles), NUM_STAGES)
    actors: list[Actor | None] = [None] * NUM_STAGES

    print()
    print("LPC supplied endpoint denominator candidates, not proven lane identities.")
    print("Candidate references:")
    _print_candidates("a", m0_poles)
    _print_candidates("b", m100_poles)
    print("Spend each persistent lane on:")
    print("  [p] passthrough")
    print("  [a] anchored pole pair: one candidate/frequency held across Morph")
    print("  [m] moving pole pair: choose an M0 and M100 candidate/frequency")
    print("  [s] accept the displayed same-rank moving-pair suggestion")

    for slot in range(NUM_STAGES):
        suggested = f"s (a{slot + 1}->b{slot + 1})" if slot < shared else "p"
        choice = ("s" if slot < shared else "p") if sketch_defaults else _prompt(
            f"lane {slot + 1}", suggested
        ).lower()
        if choice.startswith("s "):
            choice = "s"
        if choice in {"", "p", "pass", "passthrough"}:
            continue
        try:
            if choice in {"s", "suggest", "suggested"}:
                if slot >= shared:
                    raise ValueError("there is no same-rank suggestion for this lane")
                actors[slot] = Actor(
                    label=f"rank_sketch_{slot + 1}",
                    pole_m0_hz=m0_poles[slot][0], radius_m0=m0_poles[slot][1],
                    pole_m100_hz=m100_poles[slot][0], radius_m100=m100_poles[slot][1],
                    source=f"author accepted rank-pair sketch a{slot + 1}->b{slot + 1}",
                )
            elif choice in {"a", "anchor", "anchored"}:
                ref = _prompt("  candidate/frequency to anchor, e.g. b4 or 6200")
                pole = _pole_ref(ref, m0_poles, m100_poles)
                actors[slot] = Actor(
                    label=f"anchor_{slot + 1}",
                    pole_m0_hz=pole[0], radius_m0=pole[1],
                    pole_m100_hz=pole[0], radius_m100=pole[1],
                    source=f"authored anchored denominator from {ref}",
                )
            elif choice in {"m", "move", "moving"}:
                ref_a = _prompt("  M0 candidate/frequency, e.g. a3 or 2800")
                ref_b = _prompt("  M100 candidate/frequency, e.g. b5 or 7200")
                pole_a = _pole_ref(ref_a, m0_poles, m100_poles)
                pole_b = _pole_ref(ref_b, m0_poles, m100_poles)
                actors[slot] = Actor(
                    label=f"moving_{slot + 1}",
                    pole_m0_hz=pole_a[0], radius_m0=pole_a[1],
                    pole_m100_hz=pole_b[0], radius_m100=pole_b[1],
                    source=f"authored moving denominator {ref_a}->{ref_b}",
                )
            else:
                raise ValueError(f"unknown denominator choice {choice!r}")
        except ValueError as exc:
            raise SystemExit(f"!! denominator slot {slot + 1}: {exc}") from exc
    return actors


def assign_zero_roles(actors: list[Actor | None], defaults: bool = False) -> None:
    """Ask for numerator intent on every active stage, including LPC-derived ones."""
    print()
    print("Every active biquad also owns a numerator zero pair.")
    for key, desc in ZERO_ROLE_HELP.items():
        print(f"  {key:11} {desc}")
    print()
    for index, actor in enumerate(actors):
        if actor is None:
            continue
        movement = f"{actor.pole_m0_hz:.0f}->{actor.pole_m100_hz:.0f} Hz"
        answer = "local" if defaults else _prompt(
            f"slot {index + 1} {actor.label} ({movement}) zero role "
            "[l]ocal/[d]istant-low/[a]ir/[c]ustom/[n]one",
            "local",
        ).lower()
        role = ZERO_ROLE_KEYS.get(answer)
        if role is None:
            raise SystemExit(f"!! slot {index + 1}: unknown zero role {answer!r}")
        actor.zero_role = role
        if role == "custom":
            try:
                actor.zero_m0_hz = float(_prompt("  zero Hz at M0"))
                actor.zero_m100_hz = float(_prompt("  zero Hz at M100"))
                actor.zero_radius = float(_prompt("  zero radius", "0.90"))
            except ValueError as exc:
                raise SystemExit(f"!! slot {index + 1}: custom zero values must be numeric") from exc
            if not 0.0 <= actor.zero_radius <= 0.995:
                raise SystemExit(f"!! slot {index + 1}: zero radius must be inside 0..0.995")


def _zero_hz(actor: Actor, side: str) -> float | None:
    pole_hz = actor.pole_m0_hz if side == "m0" else actor.pole_m100_hz
    if actor.zero_role == "none":
        return None
    if actor.zero_role == "local":
        return pole_hz * 2.0 ** (-7.0 / 12.0)
    if actor.zero_role == "remote_low":
        return pole_hz * 2.0 ** -2.0
    if actor.zero_role == "remote_high":
        return pole_hz * 2.0 ** 2.0
    return actor.zero_m0_hz if side == "m0" else actor.zero_m100_hz


def _pole_zero_words(actor: Actor, side: str, sharp: bool) -> tuple[int, ...]:
    pole_hz = actor.pole_m0_hz if side == "m0" else actor.pole_m100_hz
    pole_r = actor.radius_m0 if side == "m0" else actor.radius_m100
    pole_r = min(0.995, pole_r + (Q_POLE_DELTA if sharp else 0.0))
    zero_hz = _zero_hz(actor, side)
    if zero_hz is None:
        return allpole_words(pole_hz, pole_r)

    zero_hz = min(AUTHORING_SR * 0.48, max(20.0, float(zero_hz)))
    zero_r = min(0.995, actor.zero_radius + (Q_ZERO_DELTA if sharp else 0.0))
    wp = 2.0 * math.pi * pole_hz / AUTHORING_SR
    wz = 2.0 * math.pi * zero_hz / AUTHORING_SR
    a1, a2 = -2.0 * pole_r * math.cos(wp), pole_r * pole_r
    nb1, nb2 = -2.0 * zero_r * math.cos(wz), zero_r * zero_r
    # Unity-DC cavity: the zero shapes the actor without inventing a level jump.
    gain = (1.0 + a1 + a2) / max(1.0 + nb1 + nb2, 1.0e-9)
    c0, c1 = 2.0 + nb1, 1.0 - nb2
    c2, c3, c4 = 2.0 + a1, 1.0 - a2, gain
    return coeffs_to_words(c0, c1, c2, c3, c4)


def authored_corner(actors: list[Actor | None], side: str, sharp: bool) -> list[tuple[int, ...]]:
    return [
        _pole_zero_words(actor, side, sharp) if actor is not None else PASS
        for actor in actors[:NUM_STAGES]
    ]


def build_corners(actors: list[Actor | None]) -> dict[str, list[tuple[int, ...]]]:
    return {
        "M0_Q0": authored_corner(actors, "m0", False),
        "M100_Q0": authored_corner(actors, "m100", False),
        "M0_Q100": authored_corner(actors, "m0", True),
        "M100_Q100": authored_corner(actors, "m100", True),
    }


def slugify(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower() or "untitled"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--m0", required=True, help="wav or .lpc.json for the M0 endpoint")
    ap.add_argument("--m100", help="wav or .lpc.json for M100; defaults to --m0")
    ap.add_argument("--sketch-defaults", action="store_true",
                    help="do not prompt: rank-pair common LPC poles and apply local zeros as a sketch")
    ap.add_argument("--defaults", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "bodies" / "factory",
                    help="packed TOML + authored plan output directory")
    ap.add_argument("--compile", action="store_true", help="also run author_body.py to .cart.json + .png")
    args = ap.parse_args(argv)

    print("NOTE: LPC recovers denominator candidates only. For fitted poles and zeros,")
    print("      use tools/fit_two_audio_arma.py. This command authors a manual sketch.")

    m0_poles = poles_of(args.m0)
    m100_poles = poles_of(args.m100) if args.m100 else m0_poles
    sketch_defaults = bool(args.sketch_defaults or args.defaults)
    actors = allocate_actors(m0_poles, m100_poles, sketch_defaults=sketch_defaults)
    assign_zero_roles(actors, defaults=sketch_defaults)
    corners = build_corners(actors)
    active_count = sum(actor is not None for actor in actors)

    slug = slugify(args.name)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    toml = args.out_dir / f"{slug}.packed.toml"
    plan = args.out_dir / f"{slug}.plan.json"
    toml.write_text(build_toml_words(args.name, corners))
    plan.write_text(json.dumps({
        "format": "lpc-pole-zero-plan-v1",
        "name": args.name,
        "boundary": (
            "LPC supplied endpoint denominator candidates. Lane identity and every "
            "numerator-zero treatment are authored choices, not recovered facts."
        ),
        "mode": "rank-paired-local-zero-sketch" if sketch_defaults else "interactive-authored-lanes",
        "inputs": {"m0": args.m0, "m100": args.m100 or args.m0},
        "slots": [
            {"slot": index + 1, "actor": asdict(actor) if actor is not None else None}
            for index, actor in enumerate(actors)
        ],
        "latent_slots": NUM_STAGES - active_count,
    }, indent=2) + "\n")
    print()
    print(f"wrote {toml}")
    print(f"wrote {plan}")
    print(f"  active pole-zero actors: {active_count}/{NUM_STAGES}")
    print(f"  latent passthrough slots: {NUM_STAGES - active_count}")

    if args.compile:
        cart = ROOT / "bodies" / f"{slug}.cart.json"
        png = ROOT / "dev" / "tmp" / "factory" / f"{slug}.png"
        subprocess.run([sys.executable, str(ROOT / "tools" / "author_body.py"),
                        str(toml), "--out", str(cart), "--png", str(png)], check=False)
        print(f"  -> {cart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
