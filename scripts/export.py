#!/usr/bin/env python3
"""Promote a verified production-authoring run without re-authoring bodies."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.export_runtime import promote_run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    destination = args.destination or ROOT / "dev" / "tmp" / "promoted_bodies" / args.run_dir.name
    report = promote_run(args.run_dir.resolve(), destination.resolve())
    print(f"promoted -> {report['destination']}")
    print(f"keepers  -> {len(report['promoted'])}")


if __name__ == "__main__":
    main()
