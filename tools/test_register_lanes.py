#!/usr/bin/env python3
"""Focused tests for the registered-lane IR (tools/register_lanes.py).

  python -m tools.test_register_lanes
"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.register_lanes import (
    CORNERS, new_document, wrap_geometry, validate, emit_geometry, dumps,
)

ROOT = Path(__file__).resolve().parent.parent
COMPILER = ROOT / "target" / "release" / "body-from-geometry.exe"

fails = 0


def check(name, ok, detail=""):
    global fails
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    fails += 0 if ok else 1


def valid_doc():
    """A fully valid 4x6 registration: one active co-located lane, rest identity."""
    doc = new_document("test_body")
    doc["secondary_axis"]["note"] = "Q100 authored by hand for this test (tighter pole radius)"
    p = doc["stage_plan"][0]
    p["lane_id"] = "f1_ridge"
    p["role"] = "F1 ridge"
    p["law"] = "local_peak_notch"
    p["pole_zero_relation"] = "zero co-located just under the pole"
    doc["lanes"]["f1_ridge"] = doc["lanes"].pop("lane0")
    for corner, (phz, pr) in zip(CORNERS, [(700, 0.97), (300, 0.97), (700, 0.99), (300, 0.99)]):
        a = doc["lanes"]["f1_ridge"]["assignments"][corner]
        a.update(state="active",
                 pole={"hz": float(phz), "r": pr},
                 zero={"hz": float(phz) * 1.05, "r": pr - 0.02},
                 scale=1.0,
                 provenance={"source": "test fixture", "method": "hand-authored"})
    return doc


def errs_contain(errs, needle):
    return any(needle in e for e in errs)


# 1. valid registration validates and emits geometry that filter_cli accepts
doc = valid_doc()
errs = validate(doc)
check("valid 4x6 registration validates", errs == [], "; ".join(errs[:3]))
geo = emit_geometry(doc)
td = tempfile.mkdtemp()
geo_path = Path(td) / "test_body.geometry.json"
geo_path.write_text(dumps(geo), encoding="utf-8")
r = subprocess.run([sys.executable, "-m", "tools.filter_cli", "validate", str(geo_path)],
                   capture_output=True, text=True, cwd=ROOT)
check("emitted geometry passes filter_cli validate", r.returncode == 0, r.stdout + r.stderr)

# stage order preserved, canonical stage keys only
check("emit preserves stage order + canonical keys",
      geo["corners"][0][0]["pole_hz"] == 700.0
      and all(set(s) == {"pole_hz", "pole_r", "zero_hz", "zero_r", "scale"}
              for c in geo["corners"] for s in c))

# 2. repeated emission is byte-identical
check("repeated emission byte-identical", dumps(emit_geometry(doc)) == dumps(emit_geometry(doc)))

# 3. duplicate lane id fails
d = copy.deepcopy(doc)
d["stage_plan"][1]["lane_id"] = "f1_ridge"
check("duplicate lane id rejected", errs_contain(validate(d), "duplicate lane id"))

# 4. missing lane fails
d = copy.deepcopy(doc)
del d["lanes"]["lane3"]
check("missing lane rejected", errs_contain(validate(d), "missing="))

# 5. corner reordering fails
d = copy.deepcopy(doc)
asg = d["lanes"]["f1_ridge"]["assignments"]
d["lanes"]["f1_ridge"]["assignments"] = {c: asg[c] for c in reversed(CORNERS)}
check("corner reordering rejected", errs_contain(validate(d), "corner keys must be exactly"))
d = copy.deepcopy(doc)
d["corner_order"] = list(reversed(CORNERS))
check("corner_order change rejected", errs_contain(validate(d), "corner_order"))

# 6. derived Q100 fails
d = copy.deepcopy(doc)
d["secondary_axis"] = {"authored": False, "note": "derived from Q0 by radius transpose"}
check("derived Q100 rejected", errs_contain(validate(d), "derived Q100 is rejected"))

# 7. topology mismatch fails (real pair in a declared-conjugate lane)
d = copy.deepcopy(doc)
d["lanes"]["f1_ridge"]["assignments"]["M0_Q0"]["pole"] = {"real_roots": [0.5, -0.3]}
check("topology mismatch rejected", errs_contain(validate(d), "no silent conjugate/real conversion"))

# 8. real_pair lane cannot enter conjugate-only geometry
d = copy.deepcopy(doc)
d["stage_plan"][0]["topology"] = "real_pair"
for c in CORNERS:
    d["lanes"]["f1_ridge"]["assignments"][c]["pole"] = {"real_roots": [0.5, -0.3]}
    d["lanes"]["f1_ridge"]["assignments"][c]["zero"] = {"real_roots": [0.2, 0.1]}
check("real_pair lane validates in IR", validate(d) == [])
try:
    emit_geometry(d)
    check("real_pair lane refused at emit", False)
except ValueError as e:
    check("real_pair lane refused at emit", "conjugate-only" in str(e))

# 9. identity must be exact
d = copy.deepcopy(doc)
d["lanes"]["lane1"]["assignments"]["M0_Q0"]["scale"] = 1.0001
check("inexact identity rejected", errs_contain(validate(d), "identity must be EXACT"))

# 10. declared stage-law violation fails
d = copy.deepcopy(doc)
d["lanes"]["f1_ridge"]["assignments"]["M0_Q0"]["zero"] = {"hz": 8000.0, "r": 0.9}
check("stage-law violation rejected", errs_contain(validate(d), "local_peak_notch"))

# 11. pole radius outside runtime contract fails
d = copy.deepcopy(doc)
d["lanes"]["f1_ridge"]["assignments"]["M0_Q0"]["pole"]["r"] = 1.0
check("pole radius > 0.9999 rejected", errs_contain(validate(d), "runtime contract"))

# 12. nonfinite geometry fails
d = copy.deepcopy(doc)
d["lanes"]["f1_ridge"]["assignments"]["M0_Q0"]["pole"]["hz"] = float("nan")
check("nonfinite geometry rejected", len(validate(d)) > 0)

# 13. missing provenance fails
d = copy.deepcopy(doc)
d["lanes"]["f1_ridge"]["assignments"]["M0_Q0"]["provenance"] = {}
check("missing provenance rejected", errs_contain(validate(d), "provenance"))

# 14. continuity limit exceeded fails
d = copy.deepcopy(doc)
d["stage_plan"][0]["limits"]["max_pole_octave_step"] = 0.5
check("continuity limit exceeded rejected", errs_contain(validate(d), "oct (limit 0.5)"))

# 15. catalog: unknown reference / study_reference rejected
catalog = {"records": [
    {"id": "good-tf", "record_type": "measured_tf"},
    {"id": "study-rom", "record_type": "study_reference"},
]}
d = copy.deepcopy(doc)
d["lanes"]["f1_ridge"]["assignments"]["M0_Q0"]["candidate"]["catalog_record"] = "nope"
check("unknown catalog record rejected", errs_contain(validate(d, catalog), "unknown catalog record"))
d["lanes"]["f1_ridge"]["assignments"]["M0_Q0"]["candidate"]["catalog_record"] = "study-rom"
check("study_reference as evidence rejected", errs_contain(validate(d, catalog), "study_reference"))
d["lanes"]["f1_ridge"]["assignments"]["M0_Q0"]["candidate"]["catalog_record"] = "good-tf"
check("valid catalog record accepted", validate(d, catalog) == [])

# 16. wrap round-trip: wrapped doc validates and re-emits the same corners
src_geo = {"name": "wrapped", "corners": geo["corners"]}
w = wrap_geometry(src_geo, "test.geometry.json")
werrs = validate(w)
check("wrapped geometry validates", werrs == [], "; ".join(werrs[:3]))
check("wrap emit preserves corners verbatim", emit_geometry(w)["corners"] == src_geo["corners"])

# 17. acoustic-profiler ownership and hard bands are explicit/all-or-nothing
d = copy.deepcopy(doc)
d["stage_plan"][0]["analysis"] = {
    "source": "macro_body", "pole_band_hz": [55.0, 300.0],
    "zero_band_hz": [55.0, 500.0], "pole_radius": [0.0, 0.98],
    "zero_radius": [0.0, 0.98],
}
check("partial profiler plan rejected", errs_contain(validate(d), "all-or-nothing"))
for i, p in enumerate(d["stage_plan"]):
    p["analysis"] = {
        "source": "macro_body" if i == 0 else "residual",
        "pole_band_hz": [55.0 if i == 0 else 100.0 * i, 300.0 if i == 0 else 100.0 * i + 500.0],
        "zero_band_hz": [55.0 if i == 0 else 100.0 * i, 500.0 if i == 0 else 100.0 * i + 700.0],
        "pole_radius": [0.0, 0.98], "zero_radius": [0.05, 0.98],
    }
check("complete profiler plan accepted", validate(d) == [])
d["stage_plan"][2]["analysis"]["pole_band_hz"] = [900.0, 400.0]
check("reversed profiler band rejected", errs_contain(validate(d), "minimum < maximum"))

# 18. packing goes exclusively through the existing compiler
if COMPILER.exists():
    rl_path = Path(td) / "test_body.registered_lanes.json"
    rl_path.write_text(dumps(doc), encoding="utf-8")
    body_path = Path(td) / "test_body.body240"
    r = subprocess.run([sys.executable, "-m", "tools.register_lanes", "pack", str(rl_path), str(body_path)],
                       capture_output=True, text=True, cwd=ROOT)
    ok = r.returncode == 0 and body_path.exists() and body_path.stat().st_size == 240
    check("pack delegates to filter_cli/trench-core and yields 240 bytes", ok, r.stdout + r.stderr)
else:
    print("SKIP  pack (body-from-geometry.exe not built)")

sys.exit(1 if fails else 0)
