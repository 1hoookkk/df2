#!/usr/bin/env python3
"""Author explicit four-corner master bodies from translated evidence.

This is the authoring gate between source evidence and the existing registered
lane / geometry / body240 tools.  It deliberately does *not* fit, sort, match,
normalize, derive Q100, or apply a verb transform.  A fit corner may carry an
explicit ``radius_boost`` declaration; that operator action changes pole
radius only, records the source packed words, and is never inferred.

Manifest shape (see filters/master_bodies.json):

  python -m tools.author_master_body validate filters/master_bodies.json
  python -m tools.author_master_body inspect filters/master_bodies.json
  python -m tools.author_master_body emit filters/master_bodies.json \
      --out-dir dev/tmp/master_body_candidates --name BODY
  python -m tools.author_master_body pack filters/master_bodies.json \
      --out-dir dev/tmp/master_body_candidates --name BODY

For evidence corners, ``lane_to_source_stage`` is a required, explicit
permutation.  The source fit's stage order is preserved; the mapping is the
operator's correspondence decision.  For authored corners, ``stages`` are
already in registered lane-slot order.  A Q100 verb is recorded as metadata
for the authored second scene only; this tool never computes its values.

Packing delegates to tools.filter_cli -> trench-core's body-from-geometry.
No production preset is written unless the operator explicitly supplies that
output directory after marking a body KEEP.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

from tools import register_lanes as rl


ROOT = Path(__file__).resolve().parent.parent
CORNERS = list(rl.CORNERS)
VERBS = ("BLOOM", "SPREAD", "SCREAM", "FLIP")
DECISIONS = ("PENDING", "KEEP", "KILL")
FIT_STATUS = "PACKED_CONJUGATE"
BODY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FORBIDDEN_ACTION_KEYS = {
    "auto_sort", "sort", "sort_by_pole_hz", "sort_by_frequency",
    "derive_from", "derived_from", "transform", "verb_transform",
}


class MasterBodyError(ValueError):
    """A refusal with one or more path-qualified reasons."""

    def __init__(self, errors):
        self.errors = [str(e) for e in errors]
        super().__init__("; ".join(self.errors))


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise MasterBodyError([f"{path}: file does not exist"])
    except (OSError, json.JSONDecodeError) as exc:
        raise MasterBodyError([f"{path}: cannot read JSON: {exc}"])


def _resolve_ref(raw, manifest_path: Path) -> Path:
    path = Path(raw)
    return path.resolve() if path.is_absolute() \
        else (manifest_path.parent / path).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_string(value, path, errors):
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: required non-empty string")


def _require_object(value, path, errors):
    if not isinstance(value, dict):
        errors.append(f"{path}: required object")


def _validate_mapping(mapping, path, errors):
    if not (isinstance(mapping, list) and len(mapping) == 6):
        errors.append(f"{path}: required six-entry lane_to_source_stage permutation")
        return
    if any(not isinstance(value, int) or isinstance(value, bool) for value in mapping):
        errors.append(f"{path}: every source stage index must be an integer")
        return
    if sorted(mapping) != list(range(6)):
        errors.append(f"{path}: must be a permutation of [0, 1, 2, 3, 4, 5]; no implicit sorting")


def _validate_radius_boost(spec, path, errors):
    boost = spec.get("radius_boost")
    if boost is None:
        return
    if not isinstance(boost, dict):
        errors.append(f"{path}.radius_boost: required object")
        return
    if boost.get("mode") != "add_and_cap":
        errors.append(f"{path}.radius_boost.mode: must be 'add_and_cap'")
    delta = boost.get("delta")
    cap = boost.get("cap")
    if not _is_num(delta) or delta <= 0.0:
        errors.append(f"{path}.radius_boost.delta: must be a positive finite number")
    if not _is_num(cap) or not 0.0 < cap < 1.0:
        errors.append(f"{path}.radius_boost.cap: must be finite and in (0, 1)")
    if _is_num(delta) and _is_num(cap) and delta > cap:
        errors.append(f"{path}.radius_boost.delta: must not exceed cap")
    _require_string(boost.get("note"), f"{path}.radius_boost.note", errors)


def _validate_stage_shape(stage, path, errors):
    if not isinstance(stage, dict):
        errors.append(f"{path}: required object")
        return
    if stage.get("state") not in ("active", "identity"):
        errors.append(f"{path}.state: must be explicitly 'active' or 'identity'")
        return
    if "lane_id" in stage and (not isinstance(stage["lane_id"], str) or not stage["lane_id"]):
        errors.append(f"{path}.lane_id: must be a non-empty string when supplied")
    if stage["state"] == "active":
        if not isinstance(stage.get("pole"), dict):
            errors.append(f"{path}.pole: required object for active stage")
        if not isinstance(stage.get("zero"), dict):
            errors.append(f"{path}.zero: required object for active stage")
        if not _is_num(stage.get("scale")):
            errors.append(f"{path}.scale: required finite number for active stage")
    else:
        # A supplied identity geometry is checked exactly by the registered-lane
        # validator.  Missing geometry is allowed because state=identity is the
        # authored declaration and the builder supplies the exact identity.
        for key in ("pole", "zero"):
            if key in stage and stage[key] != {"hz": 0.0, "r": 0.0}:
                errors.append(f"{path}.{key}: identity geometry must be exact {{hz: 0, r: 0}}")
        if "scale" in stage and stage["scale"] != 1.0:
            errors.append(f"{path}.scale: identity SCALE must be exactly 1.0")


def _fit_from_spec(spec, manifest_path: Path, path: str, errors):
    fit_ref = spec.get("fit")
    if not isinstance(fit_ref, str) or not fit_ref:
        errors.append(f"{path}.fit: required path to a translated fit JSON")
        return None, None
    fit_path = _resolve_ref(fit_ref, manifest_path)
    if not fit_path.exists():
        errors.append(f"{path}.fit: file does not exist: {fit_path}")
        return None, fit_path
    try:
        fit = _read_json(fit_path)
    except MasterBodyError as exc:
        errors.extend(f"{path}.fit: {e}" for e in exc.errors)
        return None, fit_path
    if fit.get("status") != FIT_STATUS:
        errors.append(f"{path}.fit: status must be {FIT_STATUS!r}; got {fit.get('status')!r}")
    stages = fit.get("stages")
    if not (isinstance(stages, list) and len(stages) == 6):
        errors.append(f"{path}.fit: requires exactly six packed decoded stages")
    role = (fit.get("source") or {}).get("role") if isinstance(fit.get("source"), dict) else None
    if role == "calculated_control" and spec.get("allow_calculated_control") is not True:
        errors.append(f"{path}: calculated-control evidence is inspection-only; set allow_calculated_control true explicitly")
    _validate_mapping(spec.get("lane_to_source_stage"), f"{path}.lane_to_source_stage", errors)
    return fit, fit_path


def _validate_corner_spec(spec, corner, body_path, manifest_path, errors):
    path = f"{body_path}.corners.{corner}"
    if not isinstance(spec, dict):
        errors.append(f"{path}: required object")
        return
    forbidden = sorted(FORBIDDEN_ACTION_KEYS.intersection(spec))
    if forbidden:
        errors.append(f"{path}: automatic action keys are forbidden: {forbidden}")
    kind = spec.get("kind")
    if kind == "fit":
        _validate_radius_boost(spec, path, errors)
        _fit_from_spec(spec, manifest_path, path, errors)
    elif kind == "authored":
        if "radius_boost" in spec:
            errors.append(f"{path}.radius_boost: only fit corners may declare a source radius boost")
        stages = spec.get("stages")
        if not (isinstance(stages, list) and len(stages) == 6):
            errors.append(f"{path}.stages: authored corner requires exactly six lane-slot stages")
        else:
            for index, stage in enumerate(stages):
                _validate_stage_shape(stage, f"{path}.stages[{index}]", errors)
        provenance = spec.get("provenance")
        if not isinstance(provenance, dict):
            errors.append(f"{path}.provenance: required {source, method} for authored values")
        else:
            _require_string(provenance.get("source"), f"{path}.provenance.source", errors)
            _require_string(provenance.get("method"), f"{path}.provenance.method", errors)
    else:
        errors.append(f"{path}.kind: must be 'fit' or 'authored'; Q100 cannot be derived")


def _validate_body_static(body, body_index, manifest_path: Path):
    errors = []
    path = f"bodies[{body_index}]"
    if not isinstance(body, dict):
        return [f"{path}: required object"]
    name = body.get("name")
    _require_string(name, f"{path}.name", errors)
    if isinstance(name, str) and name and not BODY_NAME_RE.fullmatch(name):
        errors.append(f"{path}.name: use only letters, numbers, '.', '_' and '-' for artifact safety")
    decision = body.get("decision")
    if decision not in DECISIONS:
        errors.append(f"{path}.decision: must be one of {DECISIONS}")
    if decision == "KILL":
        _require_string(body.get("kill_reason"), f"{path}.kill_reason", errors)
        return errors

    _require_string(body.get("source_family"), f"{path}.source_family", errors)
    secondary = body.get("secondary_axis")
    if not (isinstance(secondary, dict) and secondary.get("authored") is True
            and isinstance(secondary.get("note"), str) and secondary["note"]):
        errors.append(f"{path}.secondary_axis: requires authored=true and a note; derived Q100 is rejected")
    q_verb = body.get("q_verb")
    if q_verb not in VERBS:
        errors.append(f"{path}.q_verb: must be one of {VERBS}; it is metadata, not an automatic transform")
    _require_string(body.get("q_verb_note"), f"{path}.q_verb_note", errors)

    plan = body.get("stage_plan")
    if not (isinstance(plan, list) and len(plan) == 6):
        errors.append(f"{path}.stage_plan: requires exactly six explicit lane slots")
    else:
        lane_ids = []
        for index, entry in enumerate(plan):
            ep = f"{path}.stage_plan[{index}]"
            if not isinstance(entry, dict):
                errors.append(f"{ep}: required object")
                continue
            if entry.get("slot") != index:
                errors.append(f"{ep}.slot: must be {index}; stage order is sacred")
            lane_id = entry.get("lane_id")
            if not isinstance(lane_id, str) or not lane_id:
                errors.append(f"{ep}.lane_id: required non-empty string")
            elif lane_id in lane_ids:
                errors.append(f"{ep}.lane_id: duplicate {lane_id!r}")
            else:
                lane_ids.append(lane_id)
    corners = body.get("corners")
    if not isinstance(corners, dict) or list(corners) != CORNERS:
        errors.append(f"{path}.corners: keys must be exactly {CORNERS} in that order")
    else:
        for corner in CORNERS:
            _validate_corner_spec(corners[corner], corner, path, manifest_path, errors)
    return errors


def _root_from_fit(stage, side, path):
    topology = stage.get("topology")
    declared = topology.get(side) if isinstance(topology, dict) else None
    if declared == "conjugate":
        root = stage.get(side)
        if not (isinstance(root, dict) and set(root) == {"hz", "r"}
                and _is_num(root.get("hz")) and _is_num(root.get("r"))):
            raise MasterBodyError([f"{path}.{side}: packed fit lacks finite conjugate {{hz, r}} geometry"])
        return {"hz": float(root["hz"]), "r": float(root["r"])}
    if declared == "real_pair":
        root = stage.get(side)
        if isinstance(root, dict) and set(root) == {"real_roots"}:
            roots = root.get("real_roots")
        else:
            roots = stage.get(f"{side}_real_roots")
        if not (isinstance(roots, list) and len(roots) == 2 and all(_is_num(v) for v in roots)):
            raise MasterBodyError([f"{path}.{side}: real-root fit geometry is missing explicit real_roots; no conversion is allowed"])
        return {"real_roots": [float(roots[0]), float(roots[1])]}
    raise MasterBodyError([f"{path}.{side}: fit topology must be explicitly conjugate or real_pair"])


def _assignment(state, pole, zero, scale, candidate, provenance):
    if state == "identity":
        result = rl.blank_assignment(provenance["source"], provenance["method"])
        result["candidate"] = candidate
        return result
    return {
        "state": "active",
        "candidate": candidate,
        "pole": pole,
        "zero": zero,
        "scale": float(scale),
        "provenance": provenance,
    }


def _fit_assignment(fit, fit_path, spec, corner, lane_slot, source_index, body_name):
    stage = fit["stages"][source_index]
    path = f"{body_name}.corners.{corner}.fit.stages[{source_index}]"
    state = stage.get("state")
    if state not in ("active", "identity"):
        raise MasterBodyError([f"{path}.state: must be active or identity"])
    provenance = {
        "source": str(fit_path),
        "method": "author_master_body: packed fit stage decoded verbatim",
        "fit_sha256": _sha256(fit_path),
        "source_stage_index": source_index,
        "lane_slot": lane_slot,
        "source_provenance": copy.deepcopy(fit.get("source")),
    }
    packed_words = stage.get("packed_words")
    if isinstance(packed_words, list):
        provenance["packed_words"] = copy.deepcopy(packed_words)
    candidate = {
        "catalog_record": spec.get("catalog_record"),
        "selector": {
            "fit": str(fit_path),
            "source_stage_index": source_index,
            "lane_slot": lane_slot,
            "lane_to_source_stage": list(spec["lane_to_source_stage"]),
        },
    }
    if state == "identity":
        return _assignment(state, None, None, 1.0, candidate, provenance)
    pole = _root_from_fit(stage, "pole", path)
    zero = _root_from_fit(stage, "zero", path)
    scale = stage.get("scale")
    if not _is_num(scale):
        raise MasterBodyError([f"{path}.scale: packed fit lacks a finite scale"])
    boost = spec.get("radius_boost")
    if boost is not None:
        if "r" not in pole:
            raise MasterBodyError([
                f"{path}.pole: radius_boost requires a conjugate pole; real-root geometry is explicit and unchanged"
            ])
        base_pole = copy.deepcopy(pole)
        boosted_radius = min(float(pole["r"]) + float(boost["delta"]),
                             float(boost["cap"]))
        pole["r"] = boosted_radius
        provenance["source_packed_words"] = copy.deepcopy(packed_words)
        provenance["source_pole"] = base_pole
        provenance["operator_action"] = {
            "type": "radius_boost",
            "mode": boost["mode"],
            "delta": float(boost["delta"]),
            "cap": float(boost["cap"]),
            "note": boost["note"],
        }
        candidate["radius_boost"] = copy.deepcopy(provenance["operator_action"])
    return _assignment(state, pole, zero, scale, candidate, provenance)


def _authored_assignment(spec, stage, corner, lane_slot, body_name):
    path = f"{body_name}.corners.{corner}.stages[{lane_slot}]"
    state = stage.get("state")
    provenance = copy.deepcopy(spec["provenance"])
    provenance["corner"] = corner
    provenance["lane_slot"] = lane_slot
    candidate = {
        "catalog_record": spec.get("catalog_record"),
        "selector": {
            "manifest_corner": corner,
            "lane_slot": lane_slot,
            "authored": True,
        },
    }
    if state == "identity":
        return _assignment(state, None, None, 1.0, candidate, provenance)
    pole = copy.deepcopy(stage.get("pole"))
    zero = copy.deepcopy(stage.get("zero"))
    scale = stage.get("scale")
    if not _is_num(scale):
        raise MasterBodyError([f"{path}.scale: required finite number"])
    return _assignment(state, pole, zero, scale, candidate, provenance)


def build_registered_doc(body, manifest_path: Path):
    """Build one registered-lane document without changing authored order."""
    static_errors = _validate_body_static(body, 0, manifest_path)
    if static_errors:
        raise MasterBodyError(static_errors)
    if body["decision"] == "KILL":
        raise MasterBodyError([f"{body['name']}: KILL bodies cannot be emitted or packed"])

    plan = copy.deepcopy(body["stage_plan"])
    doc = {
        "schema_version": 1,
        "name": body["name"],
        "corner_order": list(CORNERS),
        "secondary_axis": {
            "authored": True,
            "note": body["secondary_axis"]["note"],
        },
        "source_catalog": body.get("source_catalog"),
        "stage_plan": plan,
        "lanes": {
            entry["lane_id"]: {"assignments": {}}
            for entry in plan
        },
    }

    for corner in CORNERS:
        spec = body["corners"][corner]
        if spec["kind"] == "fit":
            fit, fit_path = _fit_from_spec(spec, manifest_path, f"{body['name']}.corners.{corner}", [])
            # Static validation has already checked these; this guard keeps the
            # builder safe if called directly by another Python module.
            if fit is None or fit_path is None:
                raise MasterBodyError([f"{body['name']}.{corner}: fit could not be loaded"])
            mapping = spec["lane_to_source_stage"]
            for lane_slot, entry in enumerate(plan):
                assignment = _fit_assignment(
                    fit, fit_path, spec, corner, lane_slot, mapping[lane_slot], body["name"])
                doc["lanes"][entry["lane_id"]]["assignments"][corner] = assignment
        else:
            stages = spec["stages"]
            for lane_slot, entry in enumerate(plan):
                stage = stages[lane_slot]
                declared_lane = stage.get("lane_id")
                if declared_lane is not None and declared_lane != entry["lane_id"]:
                    raise MasterBodyError([
                        f"{body['name']}.corners.{corner}.stages[{lane_slot}].lane_id: "
                        f"{declared_lane!r} does not match registered slot {entry['lane_id']!r}"])
                assignment = _authored_assignment(spec, stage, corner, lane_slot, body["name"])
                doc["lanes"][entry["lane_id"]]["assignments"][corner] = assignment

    errors = rl.validate(doc)
    if errors:
        raise MasterBodyError([f"{body['name']}: registered-lane validation: {error}" for error in errors])
    return doc


def load_manifest(path: Path):
    manifest = _read_json(path)
    if not isinstance(manifest, dict):
        raise MasterBodyError([f"{path}: manifest root must be an object"])
    return manifest


def validate_manifest(manifest, manifest_path: Path):
    errors = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version: must be 1")
    bodies = manifest.get("bodies")
    if not isinstance(bodies, list):
        return errors + ["bodies: required array"]
    names = set()
    for index, body in enumerate(bodies):
        static_errors = _validate_body_static(body, index, manifest_path)
        errors.extend(static_errors)
        if isinstance(body, dict) and isinstance(body.get("name"), str):
            if body["name"] in names:
                errors.append(f"bodies[{index}].name: duplicate {body['name']!r}")
            names.add(body["name"])
        if not static_errors and isinstance(body, dict) and body.get("decision") != "KILL":
            try:
                build_registered_doc(body, manifest_path)
            except MasterBodyError as exc:
                errors.extend(exc.errors)
    return errors


def _json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _write_text(path: Path, text: str, force=False):
    if path.exists() and not force:
        raise MasterBodyError([f"refusing to overwrite existing file: {path} (use --force)"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, value, force=False):
    _write_text(path, _json_text(value), force=force)


def _selected_bodies(manifest, name):
    bodies = manifest.get("bodies", [])
    selected = [body for body in bodies if name is None or body.get("name") == name]
    if name is not None and not selected:
        raise MasterBodyError([f"body {name!r} is not present in the manifest"])
    return selected


def _validate_or_raise(manifest, manifest_path):
    errors = validate_manifest(manifest, manifest_path)
    if errors:
        raise MasterBodyError(errors)


def _artifact_root(args):
    raw = args.out_dir or (ROOT / "dev" / "tmp" / "master_body_candidates")
    return Path(raw).resolve()


def _emit_one(body, manifest, manifest_path: Path, out_root: Path, force=False, pack=False):
    if body.get("decision") == "KILL":
        raise MasterBodyError([f"{body.get('name')}: KILL is an explicit refusal and cannot emit"])
    if pack and body.get("decision") != "KEEP":
        raise MasterBodyError([f"{body['name']}: pack requires decision KEEP; PENDING is review-only"])
    doc = build_registered_doc(body, manifest_path)
    try:
        geometry = rl.emit_geometry(doc)
    except ValueError as exc:
        raise MasterBodyError([f"{body['name']}: {exc}"])
    artifact_dir = out_root / body["name"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    reg_path = artifact_dir / f"{body['name']}.registered_lanes.json"
    geo_path = artifact_dir / f"{body['name']}.geometry.json"
    snapshot_path = artifact_dir / "master_body.manifest.json"
    _write_json(reg_path, doc, force=force)
    _write_json(geo_path, geometry, force=force)
    _write_json(snapshot_path, {"schema_version": 1, "body": body}, force=force)
    print(f"wrote {reg_path}")
    print(f"wrote {geo_path}")
    if not pack:
        return artifact_dir

    body_path = artifact_dir / f"{body['name']}.body240"
    if body_path.exists() and not force:
        raise MasterBodyError([f"refusing to overwrite existing file: {body_path} (use --force)"])
    completed = subprocess.run(
        [sys.executable, "-m", "tools.filter_cli", "pack", str(geo_path), str(body_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr)
    if completed.returncode != 0:
        raise MasterBodyError([f"{body['name']}: trench-core packing failed with exit {completed.returncode}"])
    if not body_path.exists() or body_path.stat().st_size != 240:
        raise MasterBodyError([f"{body['name']}: compiler did not produce an exact 240-byte body"])
    print(f"wrote {body_path} (240 bytes; KEEP)")
    return artifact_dir


def _cmd_validate(args):
    manifest_path = Path(args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    errors = validate_manifest(manifest, manifest_path)
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print(f"OK: {manifest_path} — {len(manifest.get('bodies', []))} master bodies")
    for body in manifest.get("bodies", []):
        print(f"  {body['name']}: {body['decision']} / {body.get('q_verb', 'KILL')}")
    return 0


def _cmd_inspect(args):
    manifest_path = Path(args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    errors = validate_manifest(manifest, manifest_path)
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    for body in _selected_bodies(manifest, args.name):
        print(f"{body['name']}: decision={body['decision']} q_verb={body['q_verb']} (metadata only)")
        for index, lane in enumerate(body.get("stage_plan", [])):
            print(f"  lane slot {index}: {lane['lane_id']} / {lane['role']}")
        for corner in CORNERS:
            spec = body["corners"][corner]
            if spec["kind"] == "authored":
                print(f"  {corner}: authored lane-slot order; no reorder")
                continue
            fit, fit_path = _fit_from_spec(spec, manifest_path, f"{body['name']}.corners.{corner}", [])
            poles = []
            if fit:
                for stage in fit["stages"]:
                    pole = stage.get("pole")
                    poles.append(pole.get("hz") if isinstance(pole, dict) else None)
            print(f"  {corner}: fit={fit_path}")
            print(f"    source-stage pole_hz order: {poles}")
            print(f"    explicit lane_to_source_stage: {spec['lane_to_source_stage']}")
    return 0


def _cmd_emit(args, pack=False):
    manifest_path = Path(args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    _validate_or_raise(manifest, manifest_path)
    selected = _selected_bodies(manifest, args.name)
    out_root = _artifact_root(args)
    for body in selected:
        _emit_one(body, manifest, manifest_path, out_root, force=args.force, pack=pack)
    return 0


def _cmd_template(args):
    target = Path(args.out).resolve()
    template = {
        "schema_version": 1,
        "tool": "tools.author_master_body.py",
        "notes": [
            "Evidence and authoring decisions are separate; this file is the final four-corner manifest.",
            "For fit corners, lane_to_source_stage must be an explicit permutation. Never sort in the tool.",
            "Q100 is a second authored scene. q_verb is metadata only; write all Q100 stages explicitly.",
            "Set decision KEEP only after packed-runtime and audio review. KILL records an explicit refusal.",
        ],
        "bodies": [],
    }
    _write_json(target, template, force=args.force)
    print(f"wrote {target}")
    return 0


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("validate", help="validate the manifest and every selected fit")
    p.add_argument("manifest")
    p.set_defaults(handler=_cmd_validate)

    p = commands.add_parser("inspect", help="show source stage order and explicit correspondence")
    p.add_argument("manifest")
    p.add_argument("--name")
    p.set_defaults(handler=_cmd_inspect)

    for command, pack in (("emit", False), ("pack", True)):
        p = commands.add_parser(command, help="emit candidate artifacts" if not pack else "pack a KEEP body through trench-core")
        p.add_argument("manifest")
        p.add_argument("--out-dir", dest="out_dir")
        p.add_argument("--name")
        p.add_argument("--force", action="store_true")
        p.set_defaults(handler=lambda parsed, pack=pack: _cmd_emit(parsed, pack=pack))

    p = commands.add_parser("template", help="write an empty operator manifest")
    p.add_argument("out")
    p.add_argument("--force", action="store_true")
    p.set_defaults(handler=_cmd_template)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except MasterBodyError as exc:
        for error in exc.errors:
            print(f"REFUSED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
