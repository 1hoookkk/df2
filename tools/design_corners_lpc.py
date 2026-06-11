#!/usr/bin/env python3
"""design_corners_lpc — pair LPC'd real-source corners into bodies, through the ONE encoder.

The corner inventory is `forge-web/data/sources.js` — each entry is 6 biquads fit by
LPC(12) from a REAL sound (vowels, a tunnel IR, a reactor hall, a VLF whistler). This tool
does NOT invent poles: it takes two inventory corners (A = Morph 0, B = Morph 1) and builds
a 4-corner body, adding a real Q bloom at the Q1 corners (q0 = broad LPC radius, q1 = pushed
toward the rim — the 6-34 dB resonant bloom the real iconic bodies actually have, per the
corrected doctrine). Packs via src.compiler.encode.body_from_params (== compile_body, the
shipped engine), then verifies each body through evaluate_body + the corridor gate (smoke.yaml).

  python -m tools.design_corners_lpc
"""
from __future__ import annotations
import json, math, re, struct
from pathlib import Path
from types import SimpleNamespace
import yaml

ROOT = Path(__file__).resolve().parent.parent
import sys; sys.path.insert(0, str(ROOT))
from src.compiler import encode
from src.architectures.trajectory_program import AUTHORING_SR as SR
from src.utils.packed_runtime import evaluate_body, gate_failures
from tools import target_browser as tb

OUT = ROOT / "dev" / "tmp" / "lpc_corners"
TAU = 2 * math.pi

def load_inventory():
    txt = (ROOT / "forge-web" / "data" / "sources.js").read_text(encoding="utf-8")
    arr = re.search(r"window\.SOURCES\s*=\s*(\[.*\])\s*;?\s*$", txt, re.S).group(1)
    return {s["name"]: s["sections"] for s in json.loads(arr)}

NYQ = SR / 2

def q_radii(pr):
    """q0 = broad (natural LPC radius, tamed); q1 = sharp resonant bloom (dialed to the 6-34 dB range)."""
    r0 = min(pr, 0.975)
    r1 = min(1.0 - (1.0 - min(pr, 0.985)) * 0.50, 0.9985)   # push 50% toward the rim
    return r0, max(r1, r0 + 0.004)

def _t(f):
    return TAU * float(f) / SR

def body_from_pair(srcA, srcB):
    """Iconic recipe on real LPC poles: flat-top low-shelf foundation (holds lows, kills the
    all-pole tilt so formants ride hot) + ONE leader (pole AND canyon-zero both sweep >1 oct)
    + held formant actors. Zeros are hand-authored (the law); poles are the real LPC captures.
    Corner order P[0..3] = M0Q0, M100Q0, M0Q100, M100Q100."""
    def corner(src, sharp, side):     # side 0 = A/M0, 1 = B/M100
        poles = sorted(src[:6], key=lambda s: float(s["pf"]))
        rows = []
        # 1-2: foundation low-shelves — pole + zero ~1.6 oct above => flat above the pole (no tilt)
        for s in poles[:2]:
            pf = float(s["pf"]); r0, r1 = q_radii(min(float(s.get("pr", .85)), .9))
            rows.append((_t(pf), min((r1 if sharp else r0), .9), _t(min(pf * 3.0, NYQ * .9)), 0.9, float(s.get("g", 1.0))))
        # 3: the ONE leader — pole sweeps 700->2200 Hz, canyon zero sweeps 500->3000 Hz (both >1 oct)
        r0, r1 = q_radii(0.972)
        rows.append((_t(700.0 if side == 0 else 2200.0), (r1 if sharp else r0),
                     _t(500.0 if side == 0 else 3000.0), 0.93, 1.0))
        # 4-6: held formant actors (the hot peaks), all-pole, Q bloom
        for s in poles[2:5]:
            pf = float(s["pf"]); r0, r1 = q_radii(float(s.get("pr", .97)))
            rows.append((_t(pf), (r1 if sharp else r0), 0.0, 0.0, float(s.get("g", 1.0))))
        while len(rows) < 6:
            rows.append((_t(8000), 0.0, 0.0, 0.0, 1.0))
        return rows[:6]
    P = [corner(srcA, False, 0), corner(srcB, False, 1), corner(srcA, True, 0), corner(srcB, True, 1)]
    return encode.body_from_params(P)

def load_gate():
    cfg = yaml.safe_load((ROOT / "configs" / "model" / "smoke.yaml").read_text(encoding="utf-8"))
    gates = SimpleNamespace(**cfg["gates"])
    ref = {k: 0.0 for k in ("median_endpoint_span_db", "median_morph_contrast_db",
                            "median_secondary_contrast_db", "median_center_span_db")}
    return gates, ref

PAIRS = [
    ("vowel oo", "vowel ee"),     # the classic oo->ee glide
    ("vowel ah", "vowel ee"),     # ah->ee opening
    ("vowel uh", "vowel ih"),
    ("vowel ah", "tunnel"),       # voice -> a real cathedral tunnel
    ("vowel ee", "vlf whistler"), # voice -> ionospheric whistler
    ("tunnel", "reactor hall"),   # two real spaces morphing
]

def main():
    inv = load_inventory(); gates, ref = load_gate()
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"inventory: {len(inv)} LPC corners | designing {len(PAIRS)} bodies through compile_body\n")
    index = []
    for a, b in PAIRS:
        if a not in inv or b not in inv:
            print(f"  SKIP {a}->{b} (missing)"); continue
        body = body_from_pair(inv[a], inv[b])   # == compile_body output -> nulls byte-0 by construction
        m = evaluate_body(body, 9)
        fails = gate_failures(m, gates, ref)
        name = f"{a}__{b}".replace(" ", "_")
        d = OUT / name; d.mkdir(exist_ok=True)
        (d / f"{name}.body240").write_bytes(body)
        verdict = "PASS" if not fails else "FAIL"
        sec = m["secondary_contrast_rms_db"]; mor = m["morph_contrast_rms_db"]
        print(f"  {a:14}-> {b:14} {verdict:4} | Q-bloom {sec:5.1f}dB  morph {mor:5.1f}dB  span {m['endpoint_span_db_mean']:5.1f}dB  maxR {m['max_pole_radius']:.4f}")
        if fails:
            print(f"        gate: {fails[:3]}")
        try:
            tb.render_candidate_audio(d, body)
        except Exception as e:
            print(f"        (render skipped: {e})")
        index.append({"name": name, "pair": [a, b], "verdict": verdict,
                      "secondary_contrast_db": round(sec, 2), "morph_contrast_db": round(mor, 2)})
    (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    npass = sum(1 for i in index if i["verdict"] == "PASS")
    print(f"\n{npass}/{len(index)} pass the corridor gate. bodies + audio -> {OUT.relative_to(ROOT)}")

if __name__ == "__main__":
    raise SystemExit(main())
