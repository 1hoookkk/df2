#!/usr/bin/env python3
"""icon_hunt - one-command DF2 body hunt for producer-facing keepers.

This is intentionally thin. The real generator is tools.sweep_roster:
it already makes bold four-corner bodies, renders shipped-engine auditions,
scores motion, and builds a browser queue. This wrapper makes the workflow
dumb-easy:

  python -m tools.icon_hunt --sweep icons_001

Then open the printed audition page, listen fast, and mark KEEP/MAYBE/REJECT.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWEEP_ROOT = ROOT / "dev" / "tmp" / "sweep"

MODES = {
    "quick": {
        "families": ["knock", "violence", "resonant", "comb", "wild", "insane"],
        "count": 24,
        "passes": 1,
        "seed_base": 9101,
    },
    "standard": {
        "families": ["knock", "violence", "resonant", "comb", "cut", "vocal", "cavity", "wild", "insane"],
        "count": 48,
        "passes": 1,
        "seed_base": 9201,
    },
    "overkill": {
        "families": ["knock", "violence", "resonant", "comb", "cut", "vocal", "cavity", "wild", "insane"],
        "count": 96,
        "passes": 3,
        "seed_base": 9301,
    },
}


def _csv(values: list[int]) -> str:
    return ",".join(str(v) for v in values)


def _seeds(seed_base: int, family_index: int, passes: int) -> list[int]:
    start = seed_base + family_index * 100
    return [start + i for i in range(passes)]


def _run(cmd: list[str], *, dry_run: bool) -> int:
    print("\n> " + " ".join(cmd), flush=True)
    if dry_run:
        return 0
    return subprocess.call(cmd, cwd=ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Generate a bold DF2 icon-hunt queue, analyze it, and merge it into "
            "one browser audition page."
        )
    )
    ap.add_argument("--sweep", required=True, help="sweep id under dev/tmp/sweep")
    ap.add_argument(
        "--mode",
        choices=sorted(MODES),
        default="standard",
        help="quick = short hunt, standard = useful default, overkill = overnight",
    )
    ap.add_argument(
        "--families",
        help="comma list overriding the mode, e.g. knock,violence,resonant,wild",
    )
    ap.add_argument("--count", type=int, help="candidates per seed per family")
    ap.add_argument("--passes", type=int, help="number of seeds per family")
    ap.add_argument("--seed-base", type=int, help="base seed for reproducible hunts")
    ap.add_argument("--skip-analyze", action="store_true", help="skip complete-morph analysis")
    ap.add_argument("--dry-run", action="store_true", help="print commands without running them")
    args = ap.parse_args()

    mode = MODES[args.mode]
    families = (
        [f.strip() for f in args.families.split(",") if f.strip()]
        if args.families
        else list(mode["families"])
    )
    count = max(4, int(args.count if args.count is not None else mode["count"]))
    passes = max(1, int(args.passes if args.passes is not None else mode["passes"]))
    seed_base = int(args.seed_base if args.seed_base is not None else mode["seed_base"])

    print("DF2 ICON HUNT")
    print(f"root: {ROOT}")
    print(f"sweep: {args.sweep}")
    print(f"mode: {args.mode}")
    print(f"families: {', '.join(families)}")
    print(f"count: {count} per seed")
    print(f"passes: {passes} seed(s) per family")
    print("")
    print("Listening rule: KEEP only if it has a use in 10 seconds.")
    print("MAYBE means one corner is promising. Everything else is REJECT.")

    for idx, family in enumerate(families):
        seeds = _seeds(seed_base, idx, passes)
        rc = _run(
            [
                sys.executable,
                "-m",
                "tools.sweep_roster",
                "--sweep",
                args.sweep,
                "--family",
                family,
                "--seeds",
                _csv(seeds),
                "--count",
                str(count),
            ],
            dry_run=args.dry_run,
        )
        if rc != 0:
            return rc

    if not args.skip_analyze:
        rc = _run(
            [sys.executable, "-m", "tools.sweep_roster", "--sweep", args.sweep, "--analyze"],
            dry_run=args.dry_run,
        )
        if rc != 0:
            return rc

    rc = _run(
        [sys.executable, "-m", "tools.sweep_roster", "--sweep", args.sweep, "--merge"],
        dry_run=args.dry_run,
    )
    if rc != 0:
        return rc

    audition = SWEEP_ROOT / args.sweep / "audition.html"
    index = SWEEP_ROOT / args.sweep / "index.md"
    print("")
    print("NEXT")
    print(f"audition page: {audition}")
    print(f"index: {index}")
    print("body player: python -m tools.body240_player")
    print("")
    print("Do not hand-tune first. Generate, listen, keep, then author around winners.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
