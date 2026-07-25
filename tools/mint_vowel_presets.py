"""Mint new vowel-morph presets: klatt vowel data -> frame+voice recipe ->
engine-verified body. Uses only this session's ecosystem (compile_frame_voice +
the catalogue's klatt table). Frame = air@9300 + body@200 + the S5 notch law;
voice = F1/F2/F3 morphing from vowel A (M0) to vowel B (M100), res sharpens Q.
"""
from __future__ import annotations
import json, os, struct, sys, itertools
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.compile_frame_voice import compile_recipe, engine_check

VOWELS = {v["ipa"]: v["klatt"] for v in json.load(open(os.path.join(ROOT, "filters/tables/klatt_1980_formants.json")))["vowels"]}
OUT = os.path.join(ROOT, "plugin", "presets", "bodies")
os.makedirs(OUT, exist_ok=True)


def voice_stage(fkey, a, b):
    return {"role": "voice",
            "M0_Q0": {"fc": a[fkey], "r": 0.97}, "M100_Q0": {"fc": b[fkey], "r": 0.97},
            "M0_Q100": {"fc": a[fkey], "r": 0.995}, "M100_Q100": {"fc": b[fkey], "r": 0.995}}


def recipe(va, vb):
    a, b = VOWELS[va], VOWELS[vb]
    return {"name": f"vox_{va}_to_{vb}", "stages": [
        {"role": "air",  "all": {"fc": 9300, "r": 0.97, "zoff": 0.4}},
        voice_stage("f1", a, b), voice_stage("f2", a, b), voice_stage("f3", a, b),
        {"role": "body", "all": {"fc": 200, "r": 0.99}},
        {"role": "s5",   "all": {"fc": 6000}},
    ]}


made, rejected = [], []
for va, vb in itertools.combinations(VOWELS, 2):
    r = recipe(va, vb)
    body = compile_recipe(r)
    worst, unst, nonf = engine_check(body)
    if worst < 1.0 and nonf == 0:
        open(os.path.join(OUT, r["name"] + ".body240"), "wb").write(body)
        json.dump(r, open(os.path.join(ROOT, "tools", "iconic_recipes", r["name"] + ".json"), "w"), indent=1)
        made.append((r["name"], worst))
    else:
        rejected.append((r["name"], worst, unst, nonf))

print(f"minted {len(made)} vowel-morph presets from klatt data (engine-verified):")
for n, w in made:
    print(f"  {n:16s}  max_pole_r={w:.3f}")
if rejected:
    print(f"rejected {len(rejected)}: {[r[0] for r in rejected]}")
