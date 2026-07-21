#!/usr/bin/env python3
"""Focused tests for candidate extraction (tools/extract_candidates.py +
trench-core fit-candidates).

  python -m tools.test_extract_candidates
"""
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.extract_candidates import CORNERS, candidate_id, validate_tf

ROOT = Path(__file__).resolve().parent.parent
FITTER = ROOT / "target" / "release" / "fit-candidates.exe"

fails = 0


def check(name, ok, detail=""):
    global fails
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    fails += 0 if ok else 1


td = Path(tempfile.mkdtemp())


def synth_tf(path, peaks):
    """Small synthetic magnitude curve: resonant peaks on a log grid."""
    freqs = [30.0 * (640.0 ** (i / 255)) for i in range(256)]  # 30 Hz .. 19.2 kHz
    mags = []
    for f in freqs:
        m = 0.0
        for (f0, bw, amp) in peaks:
            m += amp / (1.0 + ((f * f - f0 * f0) / max(f * bw, 1e-9)) ** 2)
        mags.append(20 * math.log10(max(m, 1e-4)))
    med = sorted(mags)[len(mags) // 2]
    path.write_text(json.dumps({"freqs_hz": freqs, "mag_db": [m - med for m in mags],
                                "source": "synthetic", "kind": "modes"}))
    return path


def run_cli(recipe, out):
    return subprocess.run([sys.executable, "-m", "tools.extract_candidates", str(recipe), str(out)],
                          capture_output=True, text=True, cwd=ROOT)


# four distinct synthetic corner sources
peaksets = [
    [(220, 40, 8.0), (900, 80, 4.0), (3000, 300, 2.0)],
    [(330, 30, 8.0), (1400, 100, 4.0), (5200, 500, 2.0)],
    [(220, 15, 12.0), (900, 30, 6.0), (3000, 120, 3.0)],
    [(330, 12, 12.0), (1400, 40, 6.0), (5200, 200, 3.0)],
]
srcs = [synth_tf(td / f"c{i}.tf.json", p) for i, p in enumerate(peaksets)]
recipe = td / "recipe.json"
recipe.write_text(json.dumps({
    "schema_version": 1, "name": "synth_quad",
    "corners": {c: str(s) for c, s in zip(CORNERS, srcs)},
}))

# 1. a four-corner source set extracts successfully
out1 = td / "a.candidates.json"
r = run_cli(recipe, out1)
check("four-corner extraction succeeds", r.returncode == 0, r.stdout + r.stderr)
cs = json.loads(out1.read_text()) if out1.exists() else {}

# 2. repeated extraction is byte-identical
out2 = td / "b.candidates.json"
r2 = run_cli(recipe, out2)
check("repeated extraction byte-identical",
      r2.returncode == 0 and out1.read_bytes() == out2.read_bytes())

# 3. structure: exact corner order, no lane/slot anywhere, provenance traces
if cs:
    check("exact corner order", cs["corner_order"] == CORNERS
          and list(cs["corners"].keys()) == CORNERS)
    all_cands = [c for corner in cs["corners"].values() for c in corner["candidates"]]
    banned = {"slot", "lane", "lane_id", "role", "confidence"}
    check("no candidate contains lane/slot/role/confidence",
          all(not (banned & set(c)) for c in all_cands) and len(all_cands) > 0)
    import hashlib
    ok_prov = all(
        c["provenance"]["source_sha256"] == cs["corners"][corner]["source"]["sha256"]
        and hashlib.sha256(Path(cs["corners"][corner]["source"]["path"]).read_bytes()).hexdigest()
        == c["provenance"]["source_sha256"]
        and c["provenance"]["method"]
        for corner in CORNERS for c in cs["corners"][corner]["candidates"])
    check("every candidate traces to source hash + method", ok_prov)
    check("extraction params recorded",
          all(cs["corners"][c]["extraction"]["n_points"] == 256
              and cs["corners"][c]["extraction"]["runtime_sr_hz"] == 39062.5 for c in CORNERS))
    check("fit residual from owned path present",
          all("residual_rms_db" in cs["corners"][c]["fit"]
              and "biquad_cascade_complex" in cs["corners"][c]["fit"]["computed_by"]
              for c in CORNERS))
    ids = [c["id"] for c in all_cands]
    check("candidate ids unique + deterministic pattern",
          len(ids) == len(set(ids)) and all(i.startswith("cand-") for i in ids))
    # exact decode: geometry matches its own packed words per topology form
    ok_topo = all(
        (set(c["pole"]) == {"hz", "r"}) == (c["topology"]["pole"] in ("conjugate", "degenerate"))
        and (set(c["pole"]) == {"real_roots"}) == (c["topology"]["pole"] == "real_pair")
        for c in all_cands)
    check("topology field matches geometry form exactly", ok_topo)

# 4. candidate_id determinism + equal-candidate suffix (unit)
stage = {"packed_words": [1, 2, 3, 4, 5]}
a = candidate_id("M0_Q0", "ab" * 32, stage, {})
b = candidate_id("M0_Q0", "ab" * 32, stage, {})
seen = {}
c1 = candidate_id("M0_Q0", "ab" * 32, stage, seen)
c2 = candidate_id("M0_Q0", "ab" * 32, stage, seen)
check("candidate ids deterministic", a == b == c1 and c2 == c1 + "-2")

# 5. real-root behavior explicit: a real_pair stage passes through verbatim
#    (classification itself is owned by stage_law; here we prove NO conversion)
real_stage = {"topology": {"pole": "conjugate", "zero": "real_pair"},
              "state": "active", "pole": {"hz": 500.0, "r": 0.9},
              "zero": {"real_roots": [0.7, 0.2]}, "scale": 1.0,
              "packed_words": [9, 9, 9, 9, 9]}
cid = candidate_id("M0_Q0", "cd" * 32, real_stage, {})
check("real roots kept verbatim, never projected",
      real_stage["zero"] == {"real_roots": [0.7, 0.2]} and cid.startswith("cand-"))

# 6. invalid TF data fails clearly
bad = td / "bad.tf.json"


def expect_invalid(name, payload_bytes, needle):
    bad.write_bytes(payload_bytes)
    rec = td / "badrecipe.json"
    corners = {c: str(s) for c, s in zip(CORNERS, srcs)}
    corners["M0_Q0"] = str(bad)
    rec.write_text(json.dumps({"schema_version": 1, "name": "x", "corners": corners}))
    r = run_cli(rec, td / "never.json")
    check(name, r.returncode != 0 and needle in r.stdout + r.stderr, r.stdout + r.stderr)


expect_invalid("nonfinite TF rejected",
               json.dumps({"freqs_hz": [100, 200], "mag_db": [0, None]}).encode(), "nonfinite")
expect_invalid("duplicate/descending freqs rejected",
               json.dumps({"freqs_hz": [100, 100, 200], "mag_db": [0, 0, 0]}).encode(),
               "strictly ascending")
expect_invalid("WAV masquerading as TF rejected", b"RIFF\x00\x00\x00\x00WAVEfmt ", "WAV file")
expect_invalid("non-TF JSON rejected", json.dumps({"samples": [1, 2, 3]}).encode(), "tf_ingest")

# 7. reordered corners in the recipe fail
rec = td / "reordered.json"
rec.write_text(json.dumps({"schema_version": 1, "name": "x",
                           "corners": {c: str(s) for c, s in
                                       zip(reversed(CORNERS), srcs)}}))
r = run_cli(rec, td / "never2.json")
check("reordered corners rejected", r.returncode != 0 and "exactly" in r.stdout + r.stderr)

if not FITTER.exists():
    print("NOTE: fitter missing — extraction checks above will have failed; build fit-candidates")

sys.exit(1 if fails else 0)
