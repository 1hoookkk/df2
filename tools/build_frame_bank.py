"""Frame A/B bank: full vowel triangle (Peterson-Barney) + P2K clean-room rail
frames (built from the MEASURED recurring rails, not copied preset bytes).
Each frame = 3 source poles (f1,f2,f3). Sorted low->high by F2 so you pick a
dark start (A) and a bright end (B). Exports forge-web/data/frames.js.
"""
import sys, json
from pathlib import Path
ROOT = Path(r"C:\Users\hooki\df2"); sys.path.insert(0, str(ROOT))

VOW = json.load(open(ROOT / "tables/vowel_formants.json", encoding="utf-8"))["vowels"]
frames = [{"label": f"vowel /{v['ipa']}/", "group": "vowel",
           "f1": v["f1"], "f2": v["f2"], "f3": v["f3"], "hz": v["f2"]} for v in VOW]

# P2K clean-room: 3-pole frames drawn from the MEASURED rails (98/194/270/390/530
# foundations, 780 mouth, 2200 bite, 3790-4440 tear, 8250-9650 air). Behavior, not bytes.
P2K = [
    ("p2k dark body", 270, 530, 780),
    ("p2k mouth",     530, 780, 1560),
    ("p2k bite",      780, 2200, 4130),
    ("p2k comb",      390, 1560, 3120),
    ("p2k tear",      2200, 4130, 9650),
    ("p2k air bank",  4130, 8250, 9650),
]
frames += [{"label": n, "group": "p2k", "f1": a, "f2": b, "f3": c, "hz": b} for (n, a, b, c) in P2K]
frames.sort(key=lambda fr: fr["hz"])

(ROOT / "forge-web/data/frames.js").write_text(
    "// Frame A/B bank — vowel triangle + P2K clean-room rails, low->high by F2.\n"
    "window.FRAMES = " + json.dumps(frames, separators=(",", ":")) + ";\n", encoding="utf-8")
print(f"{len(frames)} frames (low->high): " + "  ".join(f"{f['label']}:{f['hz']}" for f in frames))
print("exported -> forge-web/data/frames.js")
