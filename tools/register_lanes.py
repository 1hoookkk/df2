#!/usr/bin/env python3
"""register-lanes — the registered-lane IR front door.

  python -m tools.register_lanes new      NAME [out.registered_lanes.json]
  python -m tools.register_lanes wrap     x.geometry.json [out.registered_lanes.json]
  python -m tools.register_lanes validate x.registered_lanes.json [--catalog cat.json]
  python -m tools.register_lanes emit     x.registered_lanes.json [out.geometry.json]
  python -m tools.register_lanes pack     x.registered_lanes.json [out.body240]
  python -m tools.register_lanes assign   DOC.json CANDS.json CAND_ID LANE_ID CORNER
  python -m tools.register_lanes laws

A body is a six-lane animation with four keyframes. Lane identity is stable
across all four corners. This tool never sorts, matches, repairs, normalizes,
derives Q100, or changes root topology — it validates what was authored and
refuses everything else. Packing delegates to tools/filter_cli (trench-core is
the only compiler).
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORNERS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
# adjacent Morph/Q edges: Morph at Q0, Morph at Q100, Q at M0, Q at M100
EDGES = [("M0_Q0", "M100_Q0"), ("M0_Q100", "M100_Q100"),
         ("M0_Q0", "M0_Q100"), ("M100_Q0", "M100_Q100")]
POLE_R_MAX = 0.9999   # runtime contract (filters/geometry.schema.json)
HZ_MAX = 19531.25
SCALE_MAX = 4.0       # SCALE = b0, representable k in [0,4] (stage_law.rs)

LAWS = {
    "local_peak_notch": "pole+zero co-located ridge (Type 1): |log2(zero_hz/pole_hz)| <= colocate_max_octaves (default 0.5)",
    "high_zero_cliff": "moving pole against a high-rail zero (Type 2): zero_hz >= pole_hz * 2^min_separation_octaves (default 0.5)",
    "low_zero_sub_cut": "moving pole against a low-rail zero (Type 3): zero_hz <= pole_hz / 2^min_separation_octaves (default 0.5)",
    "free": "no geometric constraint beyond the runtime contract",
}
DEFAULT_LIMITS = {"max_pole_octave_step": 3.0, "max_radius_step": 0.5, "max_scale_step_db": 24.0}

IDENTITY = {"pole": {"hz": 0.0, "r": 0.0}, "zero": {"hz": 0.0, "r": 0.0}, "scale": 1.0}


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def pair_form(g):
    """'conjugate' | 'real_pair' | error string."""
    if not isinstance(g, dict):
        return "not an object"
    if set(g) == {"hz", "r"}:
        return "conjugate" if is_num(g["hz"]) and is_num(g["r"]) else "nonfinite/non-numeric hz or r"
    if set(g) == {"real_roots"}:
        rr = g["real_roots"]
        if isinstance(rr, list) and len(rr) == 2 and all(is_num(v) for v in rr):
            return "real_pair"
        return "real_roots must be two finite numbers"
    return "must be {hz, r} or {real_roots: [a, b]}"


# ── validation ──────────────────────────────────────────────────────────────

def validate(doc, catalog=None):
    """Return a list of error strings. Empty list = valid."""
    errs = []

    def err(path, msg):
        errs.append(f"{path}: {msg}")

    if doc.get("schema_version") != 1:
        err("schema_version", "must be 1")
    if not (isinstance(doc.get("name"), str) and doc["name"]):
        err("name", "required non-empty string")
    if doc.get("corner_order") != CORNERS:
        err("corner_order", f"must be exactly {CORNERS}")

    sec = doc.get("secondary_axis")
    if not (isinstance(sec, dict) and sec.get("authored") is True
            and isinstance(sec.get("note"), str) and sec["note"]):
        err("secondary_axis", "Q100 must be explicitly authored: {authored: true, note: <how>} — derived Q100 is rejected")

    plan = doc.get("stage_plan")
    lane_ids = []
    plan_by_lane = {}
    analysis_entries = []
    if not (isinstance(plan, list) and len(plan) == 6):
        err("stage_plan", "need exactly 6 entries")
        plan = []
    for i, p in enumerate(plan):
        path = f"stage_plan[{i}]"
        if not isinstance(p, dict):
            err(path, "not an object")
            continue
        if p.get("slot") != i:
            err(f"{path}.slot", f"must be {i} (stage order is the file order; no reordering)")
        lid = p.get("lane_id")
        if not (isinstance(lid, str) and lid):
            err(f"{path}.lane_id", "required non-empty string")
            continue
        if lid in plan_by_lane:
            err(f"{path}.lane_id", f"duplicate lane id '{lid}'")
        lane_ids.append(lid)
        plan_by_lane[lid] = p
        if p.get("law") not in LAWS:
            err(f"{path}.law", f"unknown law {p.get('law')!r}; known: {sorted(LAWS)}")
        if p.get("topology") not in ("conjugate", "real_pair"):
            err(f"{path}.topology", "must be 'conjugate' or 'real_pair'")
        if not (isinstance(p.get("role"), str) and p["role"]):
            err(f"{path}.role", "required non-empty string")
        if not (isinstance(p.get("pole_zero_relation"), str) and p["pole_zero_relation"]):
            err(f"{path}.pole_zero_relation", "required non-empty string")
        if not isinstance(p.get("limits"), dict):
            err(f"{path}.limits", "required object (values may be null to disable a check)")
        analysis = p.get("analysis")
        if analysis is not None:
            analysis_entries.append((i, analysis))
            if not isinstance(analysis, dict):
                err(f"{path}.analysis", "must be an object")
            else:
                if analysis.get("source") not in ("macro_body", "residual"):
                    err(f"{path}.analysis.source", "must be 'macro_body' or 'residual'")
                for key in ("pole_band_hz", "zero_band_hz"):
                    band = analysis.get(key)
                    if not (isinstance(band, list) and len(band) == 2
                            and all(is_num(v) and math.isfinite(v) for v in band)):
                        err(f"{path}.analysis.{key}", "must be two finite Hz values [minimum, maximum]")
                    elif not (55.0 <= band[0] < band[1] <= 10_500.0):
                        err(f"{path}.analysis.{key}",
                            f"must satisfy 55 <= minimum < maximum <= 10500 (got {band})")
                for key, maximum in (("pole_radius", 0.9985), ("zero_radius", 0.995)):
                    bounds = analysis.get(key)
                    if not (isinstance(bounds, list) and len(bounds) == 2
                            and all(is_num(v) and math.isfinite(v) for v in bounds)):
                        err(f"{path}.analysis.{key}", "must be two finite values [minimum, maximum]")
                    elif not (0.0 <= bounds[0] <= bounds[1] <= maximum):
                        err(f"{path}.analysis.{key}",
                            f"must satisfy 0 <= minimum <= maximum <= {maximum} (got {bounds})")

    if analysis_entries:
        if len(analysis_entries) != 6:
            err("stage_plan", "acoustic-profiler analysis is all-or-nothing: author it on all 6 lanes")
        elif analysis_entries[0][1].get("source") != "macro_body" \
                or any(a.get("source") != "residual" for _, a in analysis_entries[1:]):
            err("stage_plan", "profiler ownership must be slot 0 = macro_body, slots 1..5 = residual")

    lanes = doc.get("lanes")
    if not isinstance(lanes, dict):
        err("lanes", "required object keyed by lane id")
        lanes = {}
    if lane_ids and sorted(lanes) != sorted(lane_ids):
        missing = set(lane_ids) - set(lanes)
        extra = set(lanes) - set(lane_ids)
        err("lanes", f"must be exactly the stage_plan lane ids; missing={sorted(missing)} extra={sorted(extra)}")

    cat_records = None
    if catalog is not None:
        cat_records = {r["id"]: r for r in catalog.get("records", []) if isinstance(r, dict) and "id" in r}

    for lid in lane_ids:
        lane = lanes.get(lid)
        p = plan_by_lane[lid]
        if not isinstance(lane, dict):
            continue
        asg = lane.get("assignments")
        path = f"lanes.{lid}.assignments"
        if not isinstance(asg, dict):
            err(path, "required object with the four corners")
            continue
        if list(asg.keys()) != CORNERS:
            err(path, f"corner keys must be exactly {CORNERS} in that order; got {list(asg.keys())}")
            continue
        for corner in CORNERS:
            a = asg[corner]
            apath = f"{path}.{corner}"
            if not isinstance(a, dict):
                err(apath, "not an object")
                continue
            state = a.get("state")
            if state not in ("active", "identity"):
                err(f"{apath}.state", "must be 'active' or 'identity'")
                continue
            cand = a.get("candidate")
            if not (isinstance(cand, dict) and "catalog_record" in cand and isinstance(cand.get("selector"), dict)):
                err(f"{apath}.candidate", "required {catalog_record: id|null, selector: {...}}")
            prov = a.get("provenance")
            if not (isinstance(prov, dict) and isinstance(prov.get("source"), str) and prov["source"]
                    and isinstance(prov.get("method"), str) and prov["method"]):
                err(f"{apath}.provenance", "required {source, method} — every assignment carries evidence provenance")
            if cat_records is not None and isinstance(cand, dict):
                ref = cand.get("catalog_record")
                if isinstance(ref, str):
                    rec = cat_records.get(ref)
                    if rec is None:
                        err(f"{apath}.candidate.catalog_record", f"unknown catalog record '{ref}'")
                    elif rec.get("record_type") == "study_reference":
                        err(f"{apath}.candidate.catalog_record",
                            f"'{ref}' is a study_reference — study material may not be numeric body evidence")

            if state == "identity":
                if a.get("pole") != IDENTITY["pole"] or a.get("zero") != IDENTITY["zero"] or a.get("scale") != 1.0:
                    err(apath, "identity must be EXACT: pole {hz:0,r:0}, zero {hz:0,r:0}, scale 1.0")
                continue

            # active: geometry checks
            for side in ("pole", "zero"):
                g = a.get(side)
                form = pair_form(g)
                if form not in ("conjugate", "real_pair"):
                    err(f"{apath}.{side}", form)
                    continue
                if form != p.get("topology"):
                    err(f"{apath}.{side}", f"topology '{form}' does not match the lane's declared '{p.get('topology')}' — no silent conjugate/real conversion")
                    continue
                if form == "conjugate":
                    if not (0 <= g["hz"] <= HZ_MAX):
                        err(f"{apath}.{side}.hz", f"{g['hz']} outside [0, {HZ_MAX}]")
                    rmax = POLE_R_MAX if side == "pole" else 1.0
                    if not (0 <= g["r"] <= rmax):
                        err(f"{apath}.{side}.r", f"{g['r']} outside [0, {rmax}] (runtime contract)")
                else:
                    if side == "pole" and any(abs(v) > POLE_R_MAX for v in g["real_roots"]):
                        err(f"{apath}.{side}", f"real pole root magnitude above {POLE_R_MAX} (runtime contract)")
            s = a.get("scale")
            if not is_num(s) or not (0 < s <= SCALE_MAX):
                err(f"{apath}.scale", f"{s!r} must be a finite number in (0, {SCALE_MAX}]")

        # law check per active corner (conjugate lanes only; laws are Hz-relations)
        if p.get("law") in LAWS and p.get("law") != "free" and p.get("topology") == "conjugate":
            params = p.get("law_params") or {}
            for corner in CORNERS:
                a = asg.get(corner)
                if not (isinstance(a, dict) and a.get("state") == "active"):
                    continue
                pg, zg = a.get("pole"), a.get("zero")
                if pair_form(pg) != "conjugate" or pair_form(zg) != "conjugate":
                    continue
                apath = f"{path}.{corner}"
                if pg["hz"] <= 0 or zg["hz"] <= 0:
                    err(apath, f"law '{p['law']}' requires pole_hz > 0 and zero_hz > 0 on active corners")
                    continue
                oct_sep = math.log2(zg["hz"] / pg["hz"])
                law = p["law"]
                if law == "local_peak_notch":
                    lim = params.get("colocate_max_octaves", 0.5)
                    if abs(oct_sep) > lim:
                        err(apath, f"local_peak_notch: zero is {oct_sep:+.2f} oct from the pole (limit ±{lim})")
                elif law == "high_zero_cliff":
                    lim = params.get("min_separation_octaves", 0.5)
                    if oct_sep < lim:
                        err(apath, f"high_zero_cliff: zero must sit >= {lim} oct ABOVE the pole (got {oct_sep:+.2f})")
                elif law == "low_zero_sub_cut":
                    lim = params.get("min_separation_octaves", 0.5)
                    if oct_sep > -lim:
                        err(apath, f"low_zero_sub_cut: zero must sit >= {lim} oct BELOW the pole (got {oct_sep:+.2f})")

        # continuity across adjacent edges (conjugate active↔active only)
        limits = p.get("limits") if isinstance(p.get("limits"), dict) else {}
        for ca, cb in EDGES:
            a, b = asg.get(ca), asg.get(cb)
            if not (isinstance(a, dict) and isinstance(b, dict)
                    and a.get("state") == "active" and b.get("state") == "active"):
                continue
            if pair_form(a.get("pole")) != "conjugate" or pair_form(b.get("pole")) != "conjugate":
                continue
            epath = f"{path} edge {ca}->{cb}"
            lim = limits.get("max_pole_octave_step")
            if lim is not None and a["pole"]["hz"] > 0 and b["pole"]["hz"] > 0:
                step = abs(math.log2(b["pole"]["hz"] / a["pole"]["hz"]))
                if step > lim:
                    err(epath, f"pole moves {step:.2f} oct (limit {lim})")
            lim = limits.get("max_radius_step")
            if lim is not None:
                step = abs(b["pole"]["r"] - a["pole"]["r"])
                if step > lim:
                    err(epath, f"pole radius steps {step:.4f} (limit {lim})")
            lim = limits.get("max_scale_step_db")
            if lim is not None and is_num(a.get("scale")) and is_num(b.get("scale")) \
                    and a["scale"] > 0 and b["scale"] > 0:
                step = abs(20 * math.log10(b["scale"] / a["scale"]))
                if step > lim:
                    err(epath, f"SCALE steps {step:.1f} dB (limit {lim})")

    return errs


# ── emit ────────────────────────────────────────────────────────────────────

def emit_geometry(doc):
    """Validated registered-lane doc -> canonical geometry dict (deterministic).

    Refuses real_pair lanes: canonical geometry stages are conjugate-only
    (filters/geometry.schema.json). A real-root assignment is rejected, never
    projected into approximate Hz/radius controls.
    """
    plan = doc["stage_plan"]
    for p in plan:
        if p["topology"] != "conjugate":
            raise ValueError(
                f"lane '{p['lane_id']}' declares real_pair topology: canonical geometry is "
                "conjugate-only; a real-root lane cannot enter geometry.json")
    corners = []
    provenance = {}
    for corner in CORNERS:
        stages = []
        for p in plan:
            a = doc["lanes"][p["lane_id"]]["assignments"][corner]
            if a["state"] == "identity":
                stages.append({"pole_hz": 0.0, "pole_r": 0.0, "zero_hz": 0.0, "zero_r": 0.0, "scale": 1.0})
            else:
                stages.append({
                    "pole_hz": float(a["pole"]["hz"]), "pole_r": float(a["pole"]["r"]),
                    "zero_hz": float(a["zero"]["hz"]), "zero_r": float(a["zero"]["r"]),
                    "scale": float(a["scale"]),
                })
            provenance.setdefault(p["lane_id"], {})[corner] = a["provenance"]
        corners.append(stages)
    return {
        "name": doc["name"],
        "corners": corners,
        "registered_lanes": {
            "schema_version": 1,
            "stage_plan": plan,
            "secondary_axis": doc["secondary_axis"],
            "provenance": provenance,
        },
    }


def dumps(obj):
    return json.dumps(obj, indent=1) + "\n"


# ── assign: candidate -> lane/corner ────────────────────────────────────────

def assign_candidate(doc, candset, cand_id, lane_id, corner):
    """Copy one extracted candidate into lane_id at corner, verbatim.
    Returns the mutated doc; raises ValueError with a clear message."""
    if corner not in CORNERS:
        raise ValueError(f"corner must be one of {CORNERS}")
    if lane_id not in doc.get("lanes", {}):
        raise ValueError(f"unknown lane '{lane_id}'; lanes: {sorted(doc.get('lanes', {}))}")
    found = None
    for src_corner in CORNERS:
        for c in candset.get("corners", {}).get(src_corner, {}).get("candidates", []):
            if c["id"] == cand_id:
                found = (src_corner, c)
                break
        if found:
            break
    if not found:
        raise ValueError(f"candidate '{cand_id}' not in candidate set '{candset.get('name')}'")
    src_corner, cand = found
    corner_src = candset["corners"][src_corner]["source"]
    if cand["state"] == "identity":
        a = blank_assignment(cand["provenance"]["source"], cand["provenance"]["method"])
    else:
        a = {
            "state": "active",
            "candidate": {"catalog_record": corner_src.get("catalog_record"),
                          "selector": {"candidate_set": candset["name"],
                                       "candidate_id": cand_id,
                                       "from_corner": src_corner}},
            "pole": cand["pole"],
            "zero": cand["zero"],
            "scale": cand["scale"],
            "provenance": dict(cand["provenance"]),
        }
    doc["lanes"][lane_id]["assignments"][corner] = a
    return doc


def cmd_assign(args):
    if len(args) < 5:
        sys.exit("usage: assign DOC.registered_lanes.json CANDIDATES.json CAND_ID LANE_ID CORNER")
    doc_path = Path(args[0])
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    candset = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    try:
        assign_candidate(doc, candset, args[2], args[3], args[4])
    except ValueError as e:
        sys.exit(f"REFUSED: {e}")
    errs = validate(doc)
    if errs:
        print(f"REFUSED — assignment would make {doc_path.name} invalid; nothing written:")
        for e in errs:
            print("  ", e)
        sys.exit(1)
    doc_path.write_text(dumps(doc), encoding="utf-8")
    a = doc["lanes"][args[3]]["assignments"][args[4]]
    print(f"assigned {args[2]} -> lane {args[3]} @ {args[4]}: "
          f"pole {a['pole']} zero {a['zero']} scale {a['scale']}")


# ── document builders ───────────────────────────────────────────────────────

def blank_assignment(source, method):
    return {
        "state": "identity",
        "candidate": {"catalog_record": None, "selector": {}},
        "pole": {"hz": 0.0, "r": 0.0},
        "zero": {"hz": 0.0, "r": 0.0},
        "scale": 1.0,
        "provenance": {"source": source, "method": method},
    }


def new_document(name):
    plan = [{
        "slot": i,
        "lane_id": f"lane{i}",
        "role": "UNASSIGNED — name this lane's musical role",
        "law": "free",
        "topology": "conjugate",
        "pole_zero_relation": "UNASSIGNED",
        "law_params": {},
        "limits": dict(DEFAULT_LIMITS),
    } for i in range(6)]
    lanes = {f"lane{i}": {"assignments": {
        c: blank_assignment("template", "register_lanes new") for c in CORNERS
    }} for i in range(6)}
    return {
        "schema_version": 1,
        "name": name,
        "corner_order": list(CORNERS),
        "secondary_axis": {"authored": True,
                           "note": "TEMPLATE — replace with how the Q100 pose was authored"},
        "source_catalog": None,
        "stage_plan": plan,
        "lanes": lanes,
    }


def wrap_geometry(geo, source_name):
    doc = new_document(geo["name"])
    doc["secondary_axis"]["note"] = f"wrapped verbatim from {source_name}; all four corners taken as authored"
    for i, p in enumerate(doc["stage_plan"]):
        p["role"] = f"wrapped stage {i}"
        p["pole_zero_relation"] = "wrapped (unclassified)"
    for i in range(6):
        for ci, corner in enumerate(CORNERS):
            s = geo["corners"][ci][i]
            a = doc["lanes"][f"lane{i}"]["assignments"][corner]
            a["provenance"] = {"source": source_name, "method": "register_lanes wrap"}
            if (s["pole_hz"], s["pole_r"], s["zero_hz"], s["zero_r"], s["scale"]) == (0.0, 0.0, 0.0, 0.0, 1.0):
                continue  # exact identity stays state=identity
            a["state"] = "active"
            a["pole"] = {"hz": s["pole_hz"], "r": s["pole_r"]}
            a["zero"] = {"hz": s["zero_hz"], "r": s["zero_r"]}
            a["scale"] = s["scale"]
    return doc


# ── CLI ─────────────────────────────────────────────────────────────────────

def load_doc(path, args):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    catalog = None
    cat_path = doc.get("source_catalog")
    if "--catalog" in args:
        cat_path = args[args.index("--catalog") + 1]
    if cat_path:
        catalog = json.loads(Path(cat_path).read_text(encoding="utf-8"))
    errs = validate(doc, catalog)
    if errs:
        for e in errs:
            print("INVALID:", e)
        sys.exit(1)
    return doc


def cmd_new(args):
    name = args[0]
    out = Path(args[1]) if len(args) > 1 else Path(f"{name}.registered_lanes.json")
    out.write_text(dumps(new_document(name)), encoding="utf-8")
    print("wrote", out)


def cmd_wrap(args):
    geo_path = Path(args[0])
    r = subprocess.run([sys.executable, "-m", "tools.filter_cli", "validate", str(geo_path)],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"input geometry invalid:\n{r.stdout}{r.stderr}")
    geo = json.loads(geo_path.read_text(encoding="utf-8"))
    out = Path(args[1]) if len(args) > 1 else geo_path.with_name(
        geo_path.name.replace(".geometry.json", "") + ".registered_lanes.json")
    doc = wrap_geometry(geo, geo_path.name)
    errs = validate(doc)
    if errs:
        for e in errs:
            print("INVALID (wrapped doc):", e)
        sys.exit(1)
    out.write_text(dumps(doc), encoding="utf-8")
    print("wrote", out)


def cmd_validate(args):
    doc = load_doc(args[0], args)
    print(f"OK: {doc['name']} — 6 registered lanes x 4 authored corners")


def cmd_emit(args):
    doc = load_doc(args[0], args)
    try:
        geo = emit_geometry(doc)
    except ValueError as e:
        sys.exit(f"REFUSED: {e}")
    out = Path(args[1]) if len(args) > 1 and not args[1].startswith("--") \
        else Path(args[0]).with_name(doc["name"] + ".geometry.json")
    out.write_text(dumps(geo), encoding="utf-8")
    print("wrote", out)


def cmd_pack(args):
    doc = load_doc(args[0], args)
    try:
        geo = emit_geometry(doc)
    except ValueError as e:
        sys.exit(f"REFUSED: {e}")
    out = Path(args[1]) if len(args) > 1 and not args[1].startswith("--") \
        else Path(args[0]).with_name(doc["name"] + ".body240")
    with tempfile.TemporaryDirectory() as td:
        tmp_geo = Path(td) / (doc["name"] + ".geometry.json")
        tmp_geo.write_text(dumps(geo), encoding="utf-8")
        # THE compiler boundary: filter_cli pack -> trench-core body-from-geometry
        r = subprocess.run([sys.executable, "-m", "tools.filter_cli", "pack", str(tmp_geo), str(out)],
                           cwd=ROOT)
        sys.exit(r.returncode)


def cmd_laws(args):
    for name, desc in LAWS.items():
        print(f"{name:20s} {desc}")


def main():
    cmds = {"new": cmd_new, "wrap": cmd_wrap, "validate": cmd_validate,
            "emit": cmd_emit, "pack": cmd_pack, "laws": cmd_laws, "assign": cmd_assign}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds or (sys.argv[1] != "laws" and len(sys.argv) < 3):
        print(__doc__)
        sys.exit(2)
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
