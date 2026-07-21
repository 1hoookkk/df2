"""Convert GiantSteps+.xlsx to a clean filename,tonic,mode CSV for prepare_key_dataset.py.

Handles:
  - Multi-key annotations (takes the first/primary)
  - Mode variants (dorian, phrygian, harmonic etc. → min; mixolydian, ionian → maj)
  - Typos in the dataset (B_, D_, Eb^, phygian, aeonian etc.)
  - "other", "atonical", "monotonic" → skipped
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import openpyxl

NOTE_NAMES = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")

ENHARMONIC_MAP: dict[str, str] = {
    "db": "c#", "eb": "d#", "fb": "e",  # rare but possible
    "gb": "f#", "ab": "g#", "bb": "a#", "cb": "b",
}
TYPO_MAP: dict[str, str] = {
    "b_": "b",
    "d_": "d",
    "e_": "e",
    "eb^": "d#",
    "f#": "f#",  # keep as-is
    "c#": "c#",
}

MAJOR_FAMILY = {"major", "ionian", "mixolydian", "phrygian-major", "phyrgian-major"}
MINOR_FAMILY = {"minor", "aeolian", "dorian", "phrygian", "phyrgian", "phygian",
                "harmonic", "melodic", "aeonian"}
SKIP_MODES = {"other", "atonical", "monotonic", "locrian"}

KEY_RE = re.compile(
    r"^(?P<tonic>[a-gA-G][b#_]?[\^]?)\s+(?P<mode>[a-z-]+(?:\s+[a-z-]+)*)$"
)


def parse_single_key(raw: str) -> tuple[str, str] | None:
    """Parse a single key string like 'F minor aeolian' -> ('f', 'min')"""
    raw = raw.strip()
    m = KEY_RE.match(raw)
    if not m:
        return None

    tonic_raw = m.group("tonic").strip().lower()
    mode = m.group("mode").strip().lower()

    # Fix typos in tonic
    for typo, fixed in TYPO_MAP.items():
        if tonic_raw == typo:
            tonic_raw = fixed
            break

    # Normalize enharmonics
    tonic = ENHARMONIC_MAP.get(tonic_raw, tonic_raw)

    if tonic not in NOTE_NAMES:
        return None

    # Look at all mode words to determine major/minor family
    mode_words = set(mode.replace("-", " ").split())
    if mode_words & MAJOR_FAMILY:
        return tonic, "maj"
    if mode_words & MINOR_FAMILY:
        return tonic, "min"


def parse_key(raw: str) -> tuple[str, str] | None:
    """Parse a global-key field, handling multi-key annotations ('|')."""
    if not raw or raw.strip() in ("", "X", "X atonical"):
        return None

    raw = raw.strip()

    # Check for skip modes in the entire string
    lower = raw.lower()
    if "other" in lower or "atonical" in lower or "monotonic" in lower:
        return None

    # Multi-key: take the first
    parts = [p.strip() for p in raw.split("|")]
    for part in parts:
        result = parse_single_key(part)
        if result:
            return result

    return None


def main() -> int:
    xlsx_path = Path(sys.argv[1])
    output_csv = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("giantsteps_labels.csv")

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb["GiantSteps+ Key Dataset"]

    skipped: Counter[str] = Counter()
    written = 0

    with output_csv.open("w", encoding="utf-8", newline="") as f:
        f.write("filename,tonic,mode\n")
        for row in ws.iter_rows(min_row=2, values_only=True):
            track_id = row[0]
            raw_key = str(row[7]).strip() if row[7] else ""

            if not track_id:
                skipped["missing_id"] += 1
                continue

            result = parse_key(raw_key)
            if result is None:
                skipped[raw_key] += 1
                continue

            tonic, mode = result
            filename = f"{track_id}.wav"
            f.write(f"{filename},{tonic},{mode}\n")
            written += 1

    print(f"wrote {written} rows to {output_csv}")
    print(f"skipped {sum(skipped.values())}:")
    for reason, count in skipped.most_common():
        print(f"  {count:4d}  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
