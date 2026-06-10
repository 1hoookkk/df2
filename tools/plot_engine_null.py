"""plot_engine_null — the JS-vs-Rust magnitude-response harness.

Settles `plot == engine` by EXECUTION, not algebra: evaluates forge-web/js/packed.js
(packedDb, the browser plot) in node and trench_core packed_probe (the shipped DLL)
in Python over the same body and (morph, Q) grid, and reports max |diff| in dB.

Run:  python tools/plot_engine_null.py          (PASS = max |diff| < 1e-4 dB)
"""
import json, math, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pyruntime import trench_ffi as t

SR = 39062.5; TAU = 2 * math.pi
GRID = [(0, 0), (1, 0), (0, 1), (1, 1), (0.5, 0.5), (0.25, 0.75)]

NODE_SRC = """
import("%(packed)s").then(async ({wordsFromBytes, packedDb}) => {
  const fs = await import("fs");
  const words = wordsFromBytes(new Uint8Array(fs.readFileSync("%(body)s")));
  const freqs = Array.from({length:200},(_,i)=>30*Math.pow(16000/30,i/199));
  const curves = %(grid)s.map(([m,q])=>({m,q,db:freqs.map(f=>packedDb(words,m,q,f))}));
  console.log(JSON.stringify({freqs,curves}));
}).catch(e=>{console.error(e);process.exit(1)});
"""

def main():
    cards = [1,134,134,.7,4,6,1, 0,700,270,1.2,6,5,1, 0,1090,2290,1.2,6,5,1,
             0,2840,2840,2,5,3,1, 2,4130,4130,2,4,-18,1, 6,8250,8250,.7,.7,-4,1]
    body = t.compile_body_typed(cards)
    tmp = Path(tempfile.mkdtemp()) / "null_body.body240"
    tmp.write_bytes(body)
    src = NODE_SRC % {"packed": (ROOT / "forge-web/js/packed.js").as_uri(),
                      "body": tmp.as_posix(), "grid": json.dumps(GRID)}
    out = subprocess.run(["node", "-"], input=src, capture_output=True, text=True, cwd=ROOT)
    if out.returncode != 0:
        print(out.stderr); sys.exit(1)
    d = json.loads(out.stdout)
    worst = 0.0
    for c in d["curves"]:
        pr = t.packed_probe(body, c["m"], c["q"])
        for f, jsdb in zip(d["freqs"], c["db"]):
            s = 0.0
            for (b0, b1, b2, a1, a2) in pr["biquad"]:
                w = TAU * f / SR
                co, sn, c2, s2 = math.cos(w), math.sin(w), math.cos(2*w), math.sin(2*w)
                nr, ni = b0 + b1*co + b2*c2, -(b1*sn + b2*s2)
                dr, di = 1 + a1*co + a2*c2, -(a1*sn + a2*s2)
                s += 20*math.log10(max(1e-12, math.hypot(nr, ni) / max(1e-12, math.hypot(dr, di))))
            worst = max(worst, abs(s - jsdb))
    verdict = "PASS" if worst < 1e-4 else "FAIL"
    print(f"packed.js vs trench_core packed_probe: max |diff| = {worst:.6f} dB over "
          f"{len(GRID)} (morph,Q) points x 200 freqs -> {verdict}")
    sys.exit(0 if verdict == "PASS" else 1)

if __name__ == "__main__":
    main()
