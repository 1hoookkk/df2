#!/usr/bin/env python3
"""build_forge_overlays.py — normalize the reference tables into one
forge-web/data/overlays.json the bench fetches. Each entry is either a set of
frequency rails (Hz) to place poles against, or a set of radius rails.

Clean-room: these are study references (public physics + the measured q-radius
rail). The manifest carries frequencies/radii only — no shippable coefficients.

  python tools/build_forge_overlays.py
"""
import json, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "tables"
out = []


def add_freq(gid, label, freqs, labels=None):
    fs = [round(float(f), 1) for f in freqs if 20 <= float(f) <= 19000]
    if not fs:
        return
    out.append({"id": gid, "label": label, "kind": "freq", "freqs": fs,
                "labels": labels or [str(round(f)) for f in fs]})


# Peterson–Barney vowels
d = json.loads((T / "vowel_formants.json").read_text())
for v in d["vowels"]:
    keys = [k for k in ("f1", "f2", "f3") if v.get(k)]
    add_freq(f"vowel:{v['key']}", f"vowel {v['key']} ({v.get('example','')})",
             [v[k] for k in keys], [f"F{i+1}" for i in range(len(keys))])

# Klatt 1980 vowels
d = json.loads((T / "klatt_1980_formants.json").read_text())
for v in d["vowels"]:
    k = v["klatt"]
    keys = [x for x in ("f1", "f2", "f3", "f4") if k.get(x)]
    add_freq(f"klatt:{v['ipa']}", f"klatt /{v['ipa']}/", [k[x] for x in keys],
             [x.upper() for x in keys])

# struck metal (inharmonic modes × fundamental)
d = json.loads((T / "metallic_modes.json").read_text())
for o in d["objects"]:
    f0 = o.get("fundamental_hint_hz", 440)
    add_freq(f"metal:{o['key']}", f"metal {o['key']} @{f0}Hz",
             [r * f0 for r in o["ratios"]])

# tubes (harmonic / odd partials)
d = json.loads((T / "tube_resonances.json").read_text())
for t in d["tubes"]:
    add_freq(f"tube:{t['key']}", f"tube {t['key']}", t["partials_hz"])

# family intents — pull any aligned Hz freq list
d = json.loads((T / "family_intents.json").read_text())
def walk(node, path):
    if isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("_") or k in ("note", "comment", "description"):
                continue
            walk(v, path + [str(k)])
    elif isinstance(node, list):
        nums = [x for x in node if isinstance(x, (int, float))]
        if 2 <= len(nums) == len(node) and all(40 <= x <= 18000 for x in nums):
            add_freq("intent:" + ":".join(path), "intent " + " ".join(path[-2:]), nums)
        else:
            for i, x in enumerate(node):
                walk(x, path + [str(i)])
walk(d.get("families", {}), ["fam"])

# measured Q/radius rail (study reference, not coefficients)
d = json.loads((T / "q_radius_table.json").read_text())
radii = sorted({round(e["radius"], 4) for e in d["entries"] if e.get("corpus_hits", 0) >= 2}, reverse=True)
out.append({"id": "qradius", "label": "Q radius rail (measured)", "kind": "radius", "radii": radii})

dest = ROOT / "forge-web" / "data"
dest.mkdir(parents=True, exist_ok=True)
(dest / "overlays.json").write_text(json.dumps(out, separators=(",", ":")))
freq_n = sum(1 for o in out if o["kind"] == "freq")
print(f"{len(out)} overlays ({freq_n} freq) -> forge-web/data/overlays.json")
for o in out[:6]:
    print(" ", o["id"], o.get("freqs", o.get("radii"))[:6])
