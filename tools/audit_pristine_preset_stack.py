#!/usr/bin/env python3
"""Audit the pristine DF2 preset source stack.

This checks folder roles and source-shape hygiene. It does not claim a body is a
keeper; keeper status still requires packed runtime audit, rendered audio, and a
Tyson verdict in desk/bank/v1/BANK.md.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "recipes" / "pristine_preset_stack.json"
SOURCE_DIRS = ("tables", "filter_cards", "recipes", "ref")
FORBIDDEN_SOURCE_PATTERNS = ("*.body240", "*.wav", "*.png", "*.html")


@dataclass
class Finding:
    level: str
    path: str
    message: str


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path, findings: list[Finding]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        findings.append(Finding("ERROR", rel(path), f"invalid JSON: {exc}"))
        return None


def require_path(path: Path, findings: list[Finding], kind: str = "path") -> bool:
    if path.exists():
        return True
    findings.append(Finding("ERROR", rel(path), f"missing {kind}"))
    return False


def check_no_cache(findings: list[Finding]) -> None:
    for dirname in SOURCE_DIRS:
        root = ROOT / dirname
        if not root.exists():
            continue
        for path in root.rglob("__pycache__"):
            findings.append(Finding("ERROR", rel(path), "generated cache inside pristine source tree"))


def check_forbidden_outputs(findings: list[Finding]) -> None:
    source_roots = [ROOT / "recipes" / "laws", ROOT / "recipes" / "three_layer_acoustic_forge", ROOT / "tables"]
    for root in source_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in FORBIDDEN_SOURCE_PATTERNS):
                findings.append(Finding("ERROR", rel(path), "rendered/output artifact in source-truth tree"))


def check_type_primitives(path: Path, findings: list[Finding]) -> None:
    doc = read_json(path, findings)
    if not isinstance(doc, dict):
        return
    if doc.get("format") != "morph-designer-type-primitives-v1":
        findings.append(Finding("ERROR", rel(path), "unexpected primitive table format"))
    primitives = doc.get("primitives")
    if not isinstance(primitives, list) or len(primitives) != 3:
        findings.append(Finding("ERROR", rel(path), "must define exactly the three Morph Designer primitives"))
        return
    ids = [item.get("type_id") for item in primitives if isinstance(item, dict)]
    if ids != [1, 2, 3]:
        findings.append(Finding("ERROR", rel(path), f"type ids must be [1, 2, 3], got {ids!r}"))
    for item in primitives:
        if not isinstance(item, dict):
            findings.append(Finding("ERROR", rel(path), "primitive entries must be objects"))
            continue
        for key in ("name", "pole_policy", "zero_policy", "best_for", "mountain_canyon_use"):
            if key not in item:
                findings.append(Finding("ERROR", rel(path), f"primitive {item.get('type_id')} missing {key}"))


def check_law(path: Path, findings: list[Finding], seed: bool, repair: bool) -> None:
    doc = read_json(path, findings)
    if not isinstance(doc, dict):
        return
    name = doc.get("name")
    if not isinstance(name, str) or not name:
        findings.append(Finding("ERROR", rel(path), "law missing name"))
    fmt = str(doc.get("format", "scalar-law-v1"))
    if fmt == "section-law-v1":
        sections = doc.get("sections")
        if not isinstance(sections, list) or len(sections) != 6:
            findings.append(Finding("ERROR", rel(path), "section-law-v1 must carry exactly six sections"))
        else:
            for index, section in enumerate(sections):
                if not isinstance(section, dict):
                    findings.append(Finding("ERROR", rel(path), f"section {index} is not an object"))
                    continue
                if section.get("bypass"):
                    continue
                required = ("role", "fc_hz", "gain_db", "bw_oct", "zero_offset_oct", "morph_oct", "zero_morph_oct", "q_weight")
                for key in required:
                    if key not in section:
                        findings.append(Finding("ERROR", rel(path), f"section {index} missing {key}"))
        if "clean_room_note" not in doc:
            findings.append(Finding("ERROR", rel(path), "section law missing clean_room_note"))
        if "source_contract" not in doc:
            findings.append(Finding("ERROR", rel(path), "section law missing source_contract"))
    else:
        required = ("anchor_hz", "anchor_gain_db", "tilt_db", "canyon_depth", "q_crank", "morph_spread", "density")
        for key in required:
            if key not in doc:
                findings.append(Finding("ERROR", rel(path), f"scalar law missing {key}"))
    if repair:
        findings.append(Finding("WARN", rel(path), "present by design but not approved as a pristine seed yet"))
    elif not seed:
        findings.append(Finding("WARN", rel(path), "law exists but is not listed as an approved seed"))


def check_three_layer_recipe(path: Path, findings: list[Finding], candidate: bool = False) -> None:
    doc = read_json(path, findings)
    if not isinstance(doc, dict):
        return
    if doc.get("format") != "three-layer-acoustic-recipe-v1":
        findings.append(Finding("ERROR", rel(path), "unexpected three-layer recipe format"))
    if "clean_room_note" not in doc:
        findings.append(Finding("ERROR", rel(path), "recipe missing clean_room_note"))
    poles = doc.get("anatomy", {}).get("poles") if isinstance(doc.get("anatomy"), dict) else None
    zeros = doc.get("articulation", {}).get("zeros") if isinstance(doc.get("articulation"), dict) else None
    if not isinstance(poles, list) or len(poles) != 6:
        findings.append(Finding("ERROR", rel(path), "anatomy.poles must contain exactly six lanes"))
    if not isinstance(zeros, list) or len(zeros) != 6:
        findings.append(Finding("ERROR", rel(path), "articulation.zeros must contain exactly six lanes"))
    for group_name, rows, radius_keys in (
        ("anatomy.poles", poles if isinstance(poles, list) else [], ("pole_radius_q0", "pole_radius_q100")),
        ("articulation.zeros", zeros if isinstance(zeros, list) else [], ("zero_radius_q0", "zero_radius_q100")),
    ):
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                findings.append(Finding("ERROR", rel(path), f"{group_name}[{index}] is not an object"))
                continue
            if int(row.get("lane", -1)) != index:
                findings.append(Finding("ERROR", rel(path), f"{group_name}[{index}] lane index mismatch"))
            for key in radius_keys:
                if key in row and float(row[key]) >= 1.0:
                    level = "WARN" if candidate else "ERROR"
                    findings.append(Finding(level, rel(path), f"{group_name}[{index}].{key} is >= 1.0 before compiler clamp"))


def check_manifest(findings: list[Finding]) -> dict[str, Any] | None:
    if not require_path(MANIFEST, findings, "manifest"):
        return None
    doc = read_json(MANIFEST, findings)
    if not isinstance(doc, dict):
        return None
    if doc.get("format") != "df2-pristine-preset-stack-v1":
        findings.append(Finding("ERROR", rel(MANIFEST), "unexpected manifest format"))
    for group in ("source_truth", "supporting_evidence"):
        for item in doc.get("authority", {}).get(group, []):
            require_path(ROOT / item, findings, group)
    for item in doc.get("mathematical_primitives", []):
        require_path(ROOT / item, findings, "mathematical primitive")
    final_bank = doc.get("authority", {}).get("final_bank")
    if isinstance(final_bank, str):
        require_path(ROOT / final_bank, findings, "final bank")
    return doc


def run_compile_checks(manifest: dict[str, Any], findings: list[Finding]) -> None:
    for law in manifest.get("approved_seed_laws", []):
        path = ROOT / law
        out = ROOT / "dev" / "tmp" / "pristine_audit" / "laws" / path.stem
        cmd = [sys.executable, "tools/law_author.py", "--law", str(path), "--out", str(out), "--grid", "7"]
        proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            findings.append(Finding("ERROR", rel(path), f"compile audit failed with exit {proc.returncode}: {proc.stdout.strip()}"))
    recipe = ROOT / "recipes" / "three_layer_acoustic_forge" / "cleanroom_three_layer_acoustic_recipe.json"
    out_root = ROOT / "dev" / "tmp" / "pristine_audit" / "three_layer"
    cmd = [sys.executable, "tools/three_layer_acoustic_forge.py", "--recipe", str(recipe), "--out", str(out_root)]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        findings.append(Finding("ERROR", rel(recipe), f"three-layer compile failed with exit {proc.returncode}: {proc.stdout.strip()}"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", action="store_true", help="also run packed compile/audit checks for approved seeds")
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    manifest = check_manifest(findings)
    check_no_cache(findings)
    check_forbidden_outputs(findings)

    primitive_path = ROOT / "tables" / "morph_designer_type_primitives.json"
    if require_path(primitive_path, findings, "type primitive table"):
        check_type_primitives(primitive_path, findings)

    if manifest:
        approved = {str(Path(path).as_posix()) for path in manifest.get("approved_seed_laws", [])}
        repair = {str(Path(item["path"]).as_posix()) for item in manifest.get("repair_before_seed", []) if isinstance(item, dict)}
        for path in sorted((ROOT / "recipes" / "laws").glob("*.json")):
            rpath = rel(path)
            check_law(path, findings, rpath in approved, rpath in repair)
        canonical = ROOT / "recipes" / "three_layer_acoustic_forge" / "cleanroom_three_layer_acoustic_recipe.json"
        check_three_layer_recipe(canonical, findings)
        generated = ROOT / "recipes" / "three_layer_acoustic_forge" / "generated"
        if generated.exists():
            for path in sorted(generated.glob("*.json")):
                check_three_layer_recipe(path, findings, candidate=True)
        if args.compile:
            run_compile_checks(manifest, findings)

    errors = [item for item in findings if item.level == "ERROR"]
    warnings = [item for item in findings if item.level == "WARN"]
    for item in findings:
        print(f"{item.level}: {item.path}: {item.message}")
    print(f"pristine preset stack audit: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
