"""Quick swap into the Forge Audition slot — for fast A/B of vocal bodies.

Usage:
    python tools/swap_vocal.py            # list all 16 vocal bodies
    python tools/swap_vocal.py 3          # load #3 into the Forge Audition slot

After running, click "Forge Audition" in the TRENCH body strip — that body
hot-reloads in under a second. Run again with a different number to swap.
"""
import json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAL = ROOT / "dev" / "tmp" / "sweep" / "roster_intent_0528" / "families" / "vocal.json"
SLOT_PATHS = [
    Path.home() / "OneDrive" / "Documents" / "TRENCH" / "authoring_slot.json",
    Path.home() / "Documents"               / "TRENCH" / "authoring_slot.json",
]

def main():
    d = json.loads(VOCAL.read_text(encoding="utf-8"))
    sl = d["shortlist"]
    if len(sys.argv) < 2:
        print("\nVocal bodies (Klatt vowel pairs):\n")
        for i, c in enumerate(sl, 1):
            h, a, m = c.get("home_intent"), c.get("away_intent"), c.get("mid_intent")
            mid = f" -> [{m}]" if (m and c.get("third_state")) else ""
            print(f"  {i:>2}.  {h:>3}{mid} -> {a:<3}    motion {c['summary'].get('moves_on_morph_hz')}Hz")
        print("\nLoad one:  python tools/swap_vocal.py <number>")
        print("Then click 'Forge Audition' in the TRENCH body strip.")
        return
    n = int(sys.argv[1])
    if not (1 <= n <= len(sl)):
        print(f"pick 1-{len(sl)}"); return
    c = sl[n - 1]
    src = Path(c["dir"]) / f"{c['name']}.cart.json"
    h, a, m = c.get("home_intent"), c.get("away_intent"), c.get("mid_intent")
    mid = f" -> [{m}]" if (m and c.get("third_state")) else ""
    for p in SLOT_PATHS:
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, p)
    print(f"loaded #{n}: {h}{mid} -> {a}    (click Forge Audition in TRENCH)")

if __name__ == "__main__":
    main()
