#!/usr/bin/env python3
"""Author physics-grounded forge-cartridge-v1 recipes from tables/.

Maps the real acoustic models in tables/ — vowel formants, cavity/metal modes,
tube partials — onto 6-lane recipes with a NAMED HOME->AWAY morph (e.g.
"ah -> ee"), then optionally bakes each through the ONE byte-owner: `forge bake`.

No packed math lives here. Python authors *intent* (where the poles/zeros go and
how they move); the Rust bake turns a recipe into the 240-byte authority and runs
the survival gate. That keeps a single owner of recipe -> bytes.

    python tools/forge_author.py --family vocal --bake
    python tools/forge_author.py --family all --limit 40 --bake
"""
from __future__ import annotations
import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "tables"
SR = 39062.5
FORGE_EXE = ROOT / "forge" / "target" / "debug" / "forge.exe"

# pole radius (forge "sharp") from a -3 dB bandwidth, the textbook relation used
# across the tables: r = exp(-pi * BW / SR). Capped at the metal-ring ceiling.
def r_from_bw(bw_hz: float, cap: float = 0.9985) -> float:
    return round(min(cap, math.exp(-math.pi * bw_hz / SR)), 4)

def load(name: str) -> dict:
    return json.loads((TABLES / name).read_text(encoding="utf-8"))

def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "untitled"

# --- per-slot articulation: the zero is chosen from what the slot MEANS ----------
def articulation_for(slotname: str) -> tuple[dict, float]:
    """Return (articulation, gain_multiplier) for a slot, from its name."""
    s = slotname.lower()
    if "notch" in s or "scoop" in s:
        # a dip authored as a deep zero sitting on its own pole
        return {"cut": "custom", "zero": {"ratio": 1.0, "depth": 0.95}}, 0.55
    if "tear" in s or "razor" in s or "fracture" in s:
        return {"cut": "tear"}, 1.0
    if "air" in s or "top" in s:
        return {"cut": "air_cap"}, 0.8
    return {"cut": "hug"}, 1.0

# --- 6-lane normaliser -----------------------------------------------------------
def pad_to_six(items: list[dict]) -> list[dict]:
    """items: dicts with home, away, art, gain, role, label. Ensure exactly 6
    lanes by adding a sub foundation / air cap / midpoint fillers, then sort
    low->high so every slot is a stable actor across the morph."""
    items = [dict(it) for it in items]
    lo = min(it["home"] for it in items)
    hi = max(it["home"] for it in items)
    if len(items) < 6 and lo > 170:
        items.append({"home": 110.0, "away": 110.0, "art": {"cut": "hug"},
                      "gain": 1.0, "role": "foundation", "label": "sub dome"})
    if len(items) < 6 and hi < 7000:
        items.append({"home": 9500.0, "away": 9500.0, "art": {"cut": "air_kill"},
                      "gain": 0.6, "role": "edge_cap", "label": "air cap"})
    # fill remaining slots at the widest geometric gaps with mild resonators
    while len(items) < 6:
        order = sorted(items, key=lambda it: it["home"])
        gaps = [(order[i + 1]["home"] / order[i]["home"], i) for i in range(len(order) - 1)]
        _, gi = max(gaps)
        a, b = order[gi]["home"], order[gi + 1]["home"]
        f = math.sqrt(a * b)
        items.append({"home": f, "away": f, "art": {"cut": "hug"},
                      "gain": 0.8, "role": "filler", "label": "fill"})
    if len(items) > 6:
        # keep the 6 most spread (drop the closest-spaced neighbour repeatedly)
        while len(items) > 6:
            order = sorted(items, key=lambda it: it["home"])
            gaps = [(order[i + 1]["home"] / order[i]["home"], i) for i in range(len(order) - 1)]
            _, gi = min(gaps)
            # drop the lower-gain of the too-close pair
            drop = order[gi] if order[gi]["gain"] <= order[gi + 1]["gain"] else order[gi + 1]
            items.remove(drop)
    return sorted(items, key=lambda it: it["home"])

def build_recipe(name: str, family: str, items: list[dict], bw_hz: float,
                 sec_amount: float = 0.25, note: str = "") -> dict:
    lanes = []
    for i, it in enumerate(pad_to_six(items)):
        # lower lanes ring a touch broader; cap radius below the stability ceiling
        sharp = r_from_bw(bw_hz)
        anat = {"pole_hz": round(it["home"], 1), "sharp": sharp}
        if abs(it["away"] - it["home"]) > 0.5:
            anat["away_hz"] = round(it["away"], 1)
        lanes.append({
            "id": i,
            "role": it.get("role", "mode"),
            "label": it.get("label", f"mode {i}"),
            "anatomy": anat,
            "articulation": it["art"],
            "survival": {"gain": round(it["gain"], 3)},
        })
    return {
        "format": "forge-cartridge-v1",
        "name": name,
        "sampleRate": SR,
        "meta": {"source": "tables/ physical models", "family": family, "note": note},
        "recipe": {
            "axes": {
                "morph": {"low": "HOME", "high": "AWAY", "slide_semitones": 0.0, "scale": "log"},
                "secondary": {"low": "OPEN", "high": "TIGHT", "mode": "q_crank", "amount": sec_amount},
            },
            "lanes": lanes,
            "constraints": {"max_radius": 0.999, "unity_dc": True,
                            "on_unstable": "reject", "headroom_db": 18.0},
        },
    }

# --- generators per source table -------------------------------------------------
# Curated morphs that are known to be musical, by family (home_key -> away_key).
CURATED = {
    "vocal": [("ah", "ee"), ("oo", "ee"), ("oo", "ah"), ("ee", "ah"), ("aw", "ih"), ("uh", "ee")],
}

def gen_family(fam: str, fam_data: dict, limit: int) -> list[dict]:
    """Any family in family_intents.json: morph = HOME intent -> AWAY intent,
    per-lane, aligned slot-by-slot."""
    slots = fam_data["slots"]
    intents = fam_data["intents"]
    keys = list(intents.keys())
    pairs = CURATED.get(fam) or [(keys[i], keys[(i + 1) % len(keys)]) for i in range(len(keys))]
    # family bandwidth: vocal/cavity ring softer, metal/resonant ring hard
    bw = {"vocal": 90, "cavity": 45, "resonant": 14, "knock": 60,
          "comb": 70, "cut": 30, "violence": 50}.get(fam, 60)
    out = []
    for h, a in pairs[:limit]:
        if h not in intents or a not in intents or h == a:
            continue
        hf, af = intents[h]["freqs"], intents[a]["freqs"]
        items = []
        for si, sname in enumerate(slots):
            art, gmul = articulation_for(sname)
            items.append({"home": float(hf[si]), "away": float(af[si]),
                          "art": art, "gain": 1.0 * gmul,
                          "role": sname, "label": f"{sname}"})
        out.append(build_recipe(f"{fam}_{slug(h)}_to_{slug(a)}", fam, items, bw,
                                note=f"{intents[h].get('describe','')} -> {intents[a].get('describe','')}"))
    return out

def gen_tube(tubes: dict, limit: int) -> list[dict]:
    """Tube: SCALE morph — every partial slides in lock-step by the length ratio."""
    by_key = {t["key"]: t for t in tubes["tubes"]}
    out = []
    pairs = [(p["from"], p["to"]) for p in tubes.get("morph_pairs", [])]
    for h, a in pairs[:limit]:
        if h not in by_key or a not in by_key:
            continue
        hp = by_key[h]["partials_hz"][:6]
        ratio = by_key[a]["f1"] / by_key[h]["f1"]
        items = [{"home": float(f), "away": float(f) * ratio, "art": {"cut": "hug"},
                  "gain": 1.0, "role": f"partial {i+1}", "label": f"p{i+1}"}
                 for i, f in enumerate(hp)]
        out.append(build_recipe(f"tube_{slug(h)}_to_{slug(a)}", "tube", items, bw_hz=14,
                                note=f"{by_key[h]['name']} -> {by_key[a]['name']} (length scale)"))
    return out

def gen_metal(metal: dict, limit: int) -> list[dict]:
    """Metal: inharmonic modes; morph = a pitch/strike scale of the whole set."""
    out = []
    for obj in metal["objects"][:limit]:
        fund = float(obj.get("fundamental_hint_hz", 440))
        ratios = obj["ratios"][:6]
        freqs = [fund * r for r in ratios]
        items = [{"home": f, "away": f * 1.3333, "art": {"cut": "hug"},  # struck-up a 4th
                  "gain": 1.0, "role": f"mode {i+1}", "label": f"m{i+1}"}
                 for i, f in enumerate(freqs) if 20 < f < SR * 0.49]
        if len(items) < 2:
            continue
        out.append(build_recipe(f"metal_{slug(obj['key'])}", "metal", items, bw_hz=10,
                                note=obj.get("note", "")))
    return out

def main() -> int:
    ap = argparse.ArgumentParser(description="Author physics-grounded forge recipes from tables/.")
    ap.add_argument("--family", default="vocal",
                    help="vocal|cavity|resonant|knock|comb|cut|violence|tube|metal|all")
    ap.add_argument("--out", default=str(ROOT / "forge" / "recipes" / "auto"),
                    help="output directory for recipes")
    ap.add_argument("--limit", type=int, default=100, help="max recipes per family")
    ap.add_argument("--bake", action="store_true", help="also run `forge bake` on each recipe")
    args = ap.parse_args()

    fam_intents = load("family_intents.json")["families"]
    recipes: list[dict] = []
    want = list(fam_intents.keys()) + ["tube", "metal"] if args.family == "all" else [args.family]
    for fam in want:
        if fam in fam_intents:
            recipes += gen_family(fam, fam_intents[fam], args.limit)
        elif fam == "tube":
            recipes += gen_tube(load("tube_resonances.json"), args.limit)
        elif fam == "metal":
            recipes += gen_metal(load("metallic_modes.json"), args.limit)
        else:
            print(f"unknown family '{fam}'", file=sys.stderr)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, baked, passed = 0, 0, 0
    for rec in recipes:
        path = out_dir / f"{rec['name']}.cartridge.json"
        path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        written += 1
        if args.bake:
            if not FORGE_EXE.exists():
                print(f"  (no forge.exe at {FORGE_EXE} — build it first)", file=sys.stderr)
                args.bake = False
                continue
            r = subprocess.run([str(FORGE_EXE), "bake", str(path)],
                               capture_output=True, text=True)
            baked += 1
            ok = r.returncode == 0
            passed += int(ok)
            tag = "OK " if ok else "REJECT"
            msg = (r.stdout or r.stderr).strip().splitlines()
            print(f"  [{tag}] {rec['name']}  {msg[-1] if msg else ''}")

    print(f"\nwrote {written} recipe(s) to {out_dir}")
    if args.bake:
        print(f"baked {baked}, {passed} stable, {baked - passed} rejected")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
