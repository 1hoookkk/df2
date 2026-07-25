#!/usr/bin/env python3
"""Build a neutral, provenance-first source catalog.

This is an indexer, not a compiler. It never moves, copies, edits, decodes, or
packs source artifacts. The default scan is intentionally curated:

  python -m tools.source_catalog scan
  python -m tools.source_catalog scan --hash
  python -m tools.source_catalog summary dev/evidence/source_catalog.json

The output is a catalog of source candidates and logical artifact bundles. A
file extension never makes an artifact fit-eligible; each record carries an
explicit conversion and eligibility decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
DEFAULT_TMP = ROOT / "dev" / "tmp"
DEFAULT_WAV = ROOT / "wav-source-library"
DEFAULT_SURFACE_FORGE = Path(r"C:\Users\hooki\surface-forge")


def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower()
    return value or "record"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def location(root_id: str, root: Path, path: Path, with_hash: bool) -> dict:
    result = {
        "root": root_id,
        "relative_path": path.relative_to(root).as_posix(),
        "kind": "file" if path.is_file() else "directory",
    }
    if path.is_file():
        result["size_bytes"] = path.stat().st_size
        if with_hash:
            result["sha256"] = sha256(path)
    return result


def base_record(
    *,
    record_id: str,
    record_type: str,
    state: str,
    origin: str,
    loc: dict,
    fmt: str,
    to_tf: str,
    fit_input: str,
    ir_source: str,
    body_source: str,
    ship_allowed: bool,
    reason: str,
    next_action: str,
    notes: list[str] | None = None,
    label: str | None = None,
) -> dict:
    record = {
        "id": record_id,
        "record_type": record_type,
        "state": state,
        "origin": origin,
        "location": loc,
        "representation": {"format": fmt},
        "conversion": {
            "to_tf": to_tf,
            "fit_input": fit_input,
            "next_action": next_action,
        },
        "eligibility": {
            "ir_source": ir_source,
            "body_source": body_source,
            "ship_allowed": ship_allowed,
            "reason": reason,
        },
    }
    if label:
        record["label"] = label
    if notes:
        record["notes"] = notes
    return record


def classify_surface_file(root_id: str, root: Path, path: Path, with_hash: bool) -> dict | None:
    rel = path.relative_to(root).as_posix()
    low = rel.lower()
    name = path.name.lower()
    loc = location(root_id, root, path, with_hash)
    rid = slug(f"{root_id}-{rel}")

    if path.suffix.lower() == ".sofa":
        return base_record(
            record_id=rid,
            record_type="measured_ir",
            state="classified",
            origin="dataset",
            loc=loc,
            fmt="sofa_hrir",
            to_tf="sofa_to_tf",
            fit_input="conditional",
            ir_source="direct",
            body_source="no",
            ship_allowed=False,
            reason="External read-only HRIR dataset; license and chosen direction slice still need recording.",
            next_action="select_axes",
            notes=["Useful raw acoustic evidence. Convert selected directions to packed-runtime TF evidence."],
        )

    if "vvtf-measured" in name and path.suffix.lower() == ".txt":
        return base_record(
            record_id=rid,
            record_type="measured_tf",
            state="classified",
            origin="dataset",
            loc=loc,
            fmt="tf_table",
            to_tf="already_tf",
            fit_input="conditional",
            ir_source="not_ir",
            body_source="no",
            ship_allowed=False,
            reason="Direct measured frequency-response table; parser and source/license record are still required.",
            next_action="convert_to_tf",
            notes=["Do not label this text table as an impulse response."],
        )

    if path.suffix.lower() == ".csv" and ("phononic" in low or "aeroacoustic" in low):
        return base_record(
            record_id=rid,
            record_type="simulated_tf",
            state="classified",
            origin="dataset",
            loc=loc,
            fmt="spectrum_csv",
            to_tf="adapter_required",
            fit_input="conditional",
            ir_source="not_ir",
            body_source="no",
            ship_allowed=False,
            reason="Spectrum-like dataset; units, response meaning, and frequency mapping must be verified first.",
            next_action="inspect_metadata",
            notes=["May become TF evidence after an explicit adapter; not an IR by itself."],
        )

    return None


def classify_wav_file(root_id: str, root: Path, path: Path, with_hash: bool) -> dict:
    rel = path.relative_to(root).as_posix()
    loc = location(root_id, root, path, with_hash)
    low = rel.lower()
    if (
        "measured_objects/ir_library/" in low
        or "measured_objects/openair/" in low
        or "00_drop_new_wavs_here/" in low
    ):
        return base_record(
            record_id=slug(f"{root_id}-{rel}"),
            record_type="measured_ir",
            state="classified",
            origin="measurement",
            loc=loc,
            fmt="wav",
            to_tf="fft_ir",
            fit_input="conditional",
            ir_source="direct",
            body_source="no",
            ship_allowed=False,
            reason="Located in a measured-IR intake/library; confirm channel, sample rate, excitation/deconvolution, and level metadata.",
            next_action="inspect_metadata",
            notes=["The directory label is evidence of intent, not a substitute for a source card."],
        )
    return base_record(
        record_id=slug(f"{root_id}-{rel}"),
        record_type="unknown",
        state="quarantined",
        origin="dataset",
        loc=loc,
        fmt="wav",
        to_tf="unknown",
        fit_input="no",
        ir_source="unknown",
        body_source="no",
        ship_allowed=False,
        reason="Raw audio dataset or generated test audio; it is not a controlled IR by location or extension.",
        next_action="retain_as_reference",
        notes=["Promote only if a source card proves controlled excitation or a valid deconvolution path."],
    )


def classify_workspace_file(root_id: str, root: Path, path: Path, with_hash: bool) -> dict | None:
    rel = path.relative_to(root).as_posix()
    low = rel.lower()
    name = path.name.lower()
    loc = location(root_id, root, path, with_hash)
    rid = slug(f"{root_id}-{rel}")

    if path.suffix.lower() == ".geometry.json":
        return base_record(
            record_id=rid,
            record_type="authored_geometry",
            state="classified",
            origin="authored",
            loc=loc,
            fmt="geometry_json",
            to_tf="not_applicable",
            fit_input="yes",
            ir_source="not_ir",
            body_source="candidate",
            ship_allowed=True,
            reason="Authoring IR candidate; it becomes a product only after pack and packed-runtime proof.",
            next_action="pack_and_prove",
        )

    if path.suffix.lower() == ".body240":
        return base_record(
            record_id=rid,
            record_type="body_artifact",
            state="classified",
            origin="derived",
            loc=loc,
            fmt="body240",
            to_tf="not_applicable",
            fit_input="no",
            ir_source="not_ir",
            body_source="proof_only",
            ship_allowed=False,
            reason="Compiled output; it is not source evidence and must not be reverse-labelled as an IR.",
            next_action="listen_and_plot",
        )

    if path.suffix.lower() == ".wav":
        return classify_wav_file(root_id, root, path, with_hash)

    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None

        if isinstance(payload, dict) and isinstance(payload.get("corners"), list) and len(payload["corners"]) == 4:
            return base_record(
                record_id=rid,
                record_type="authored_geometry",
                state="classified",
                origin="authored",
                loc=loc,
                fmt="geometry_json",
                to_tf="not_applicable",
                fit_input="yes",
                ir_source="not_ir",
                body_source="candidate",
                ship_allowed=True,
                reason="Four-corner authoring IR detected by content; it still needs canonical validation and packed proof.",
                next_action="pack_and_prove",
            )

        if isinstance(payload, dict) and isinstance(payload.get("modes"), list):
            return base_record(
                record_id=rid,
                record_type="modal_evidence",
                state="classified",
                origin="measurement",
                loc=loc,
                fmt="modal_table",
                to_tf="modal_synthesis",
                fit_input="conditional",
                ir_source="not_ir",
                body_source="no",
                ship_allowed=False,
                reason="Modal rows can synthesize a transfer function but are not an impulse response.",
                next_action="convert_to_tf",
            )

        if isinstance(payload, dict) and {"freqs_hz", "mag_db"}.issubset(payload):
            return base_record(
                record_id=rid,
                record_type="measured_tf",
                state="prepared",
                origin="derived",
                loc=loc,
                fmt="tf_table",
                to_tf="already_tf",
                fit_input="conditional",
                ir_source="not_ir",
                body_source="no",
                ship_allowed=False,
                reason="Transfer-function table; retain the source link and processing recipe before fitting.",
                next_action="fit_geometry",
            )

        if isinstance(payload, dict) and ("rows6" in payload or "rows_res" in payload):
            return base_record(
                record_id=rid,
                record_type="unknown",
                state="quarantined",
                origin="derived",
                loc=loc,
                fmt="unknown",
                to_tf="unknown",
                fit_input="unknown",
                ir_source="unknown",
                body_source="unknown",
                ship_allowed=False,
                reason="Numeric rows are not a standard modal table or transfer-function schema.",
                next_action="inspect_metadata",
            )

    if name.endswith("candidate.cart.json") or name.endswith(".cart.json"):
        return base_record(
            record_id=rid,
            record_type="authored_geometry",
            state="classified",
            origin="derived",
            loc=loc,
            fmt="cart_json",
            to_tf="not_applicable",
            fit_input="conditional",
            ir_source="not_ir",
            body_source="candidate",
            ship_allowed=False,
            reason="Candidate cart/packed words; requires canonical geometry conversion and proof.",
            next_action="pack_and_prove",
        )

    if any(token in low for token in ("manifest", "provenance", "session", "verify_report", "hashes")):
        return base_record(
            record_id=rid,
            record_type="proof_bundle",
            state="classified",
            origin="derived",
            loc=loc,
            fmt="proof_json",
            to_tf="not_applicable",
            fit_input="no",
            ir_source="not_ir",
            body_source="proof_only",
            ship_allowed=False,
            reason="Session/provenance/verification output; it supports a candidate but is not a source.",
            next_action="listen_and_plot",
        )

    return None


def bundle_record(root_id: str, root: Path, path: Path, with_hash: bool) -> dict:
    files = [p for p in path.rglob("*") if p.is_file()]
    counts = Counter(p.suffix.lower() or "[no extension]" for p in files)
    examples = [p.relative_to(root).as_posix() for p in files[:8]]
    name = path.name.lower()
    if name in {"forge_all", "xml", "bytes_survivors", "ship_bodies", "usable"}:
        note = "Candidate/output body gallery; useful for audition and comparison, not a new IR source."
    elif "tf_oracle" in path.as_posix().lower() or name in {"tf_oracle", "measured_objects"}:
        note = "Fit/session/proof bundle; inspect provenance and raw source links before promoting anything."
    else:
        note = "Scratch or generated bundle; classify individual source files before fitting."
    record = base_record(
        record_id=slug(f"{root_id}-{path.relative_to(root).as_posix()}"),
        record_type="artifact_bundle",
        state="classified",
        origin="derived",
        loc=location(root_id, root, path, with_hash=False),
        fmt="bundle",
        to_tf="unknown",
        fit_input="unknown",
        ir_source="unknown",
        body_source="proof_only",
        ship_allowed=False,
        reason=note,
        next_action="inspect_metadata",
    )
    record["summary"] = {
        "file_count": len(files),
        "extension_counts": dict(sorted(counts.items())),
        "examples": examples,
    }
    return record


def add_surface_data(records: list[dict], root_id: str, root: Path, with_hash: bool) -> None:
    if not root.exists():
        return
    for family in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
        family_record = bundle_record(root_id, root, family, with_hash=False)
        family_name = family.name.lower()
        if family_name == "modal":
            family_record["eligibility"]["reason"] = "Generated modal audio family; export a controlled response or modal table before treating it as TF evidence."
            family_record["conversion"]["next_action"] = "inspect_metadata"
        elif family_name in {"circuit", "simulators"}:
            family_record["eligibility"]["reason"] = "Code/configuration family; produce an explicit frequency response before fitting."
            family_record["conversion"]["next_action"] = "convert_to_tf"
        elif family_name == "vocal":
            family_record["eligibility"]["reason"] = "Vocal dataset family; the measured TF text members are indexed separately."
            family_record["conversion"]["next_action"] = "convert_to_tf"
        elif family_name in {"hrtf", "phononic", "aeroacoustic"}:
            family_record["eligibility"]["reason"] = "Dataset family; usable members are indexed separately and still need an explicit adapter/axis decision."
            family_record["conversion"]["next_action"] = "select_axes"
        records.append(family_record)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        record = classify_surface_file(root_id, root, path, with_hash)
        if record is not None:
            records.append(record)


def add_workspace_sources(records: list[dict], root_id: str, root: Path, with_hash: bool) -> None:
    if not root.exists():
        return
    for path in root.iterdir():
        if path.is_dir():
            records.append(bundle_record(root_id, root, path, with_hash))
    # Keep the two folders most likely to contain direct local evidence useful
    # as source cards visible at file level without exploding the render gallery.
    for folder_name in ("measured_objects", "geometry"):
        folder = root / folder_name
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_file():
                record = classify_workspace_file(root_id, root, path, with_hash)
                if record is not None:
                    records.append(record)


def add_wav_library(records: list[dict], root_id: str, root: Path, with_hash: bool) -> None:
    if not root.exists():
        return
    for path in root.rglob("*.wav"):
        records.append(classify_wav_file(root_id, root, path, with_hash))


def build_catalog(tmp_root: Path, wav_root: Path, surface_root: Path, with_hash: bool) -> dict:
    records: list[dict] = []
    roots = [
        {"id": "workspace-tmp", "path": str(tmp_root), "role": "workspace"},
        {"id": "source-library", "path": str(wav_root), "role": "source_library"},
        {"id": "surface-forge-data", "path": str(surface_root / "data"), "role": "external_read_only"},
    ]
    add_workspace_sources(records, "workspace-tmp", tmp_root, with_hash)
    add_wav_library(records, "source-library", wav_root, with_hash)
    add_surface_data(records, "surface-forge-data", surface_root / "data", with_hash)
    records.sort(key=lambda item: item["id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": "workspace-evidence",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roots": roots,
        "records": records,
    }


def cmd_scan(args: argparse.Namespace) -> int:
    catalog = build_catalog(
        Path(args.tmp_root),
        Path(args.wav_root),
        Path(args.surface_forge),
        args.hash,
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    counts = Counter(record["record_type"] for record in catalog["records"])
    print(f"wrote {output} ({len(catalog['records'])} records)")
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value}")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    records = catalog.get("records", [])
    counts = Counter(record.get("record_type", "unknown") for record in records)
    actions = Counter(record.get("conversion", {}).get("next_action", "unknown") for record in records)
    print(f"catalog: {catalog.get('catalog_id', '<unknown>')}")
    print(f"records: {len(records)}")
    print("types:")
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value}")
    print("next actions:")
    for key, value in sorted(actions.items()):
        print(f"  {key}: {value}")
    candidates = [
        record for record in records
        if record.get("conversion", {}).get("fit_input") in {"yes", "conditional"}
    ]
    direct = [record for record in candidates if record["conversion"]["fit_input"] == "yes"]
    conditional = [record for record in candidates if record["conversion"]["fit_input"] == "conditional"]
    print(f"fit candidates: direct={len(direct)}, conditional={len(conditional)}")
    examples = sorted(direct + conditional, key=lambda record: (
        record["conversion"]["fit_input"] != "yes",
        record["record_type"],
        record["id"],
    ))[:args.show]
    for record in examples:
        print(f"  {record['id']} -> {record['conversion']['next_action']}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="scan local scratch/source roots without changing them")
    scan.add_argument("--tmp-root", default=str(DEFAULT_TMP))
    scan.add_argument("--wav-root", default=str(DEFAULT_WAV))
    scan.add_argument("--surface-forge", default=str(DEFAULT_SURFACE_FORGE))
    scan.add_argument("--out", default=str(ROOT / "dev" / "tmp" / "source_catalog.json"))
    scan.add_argument("--hash", action="store_true", help="hash individual files; can be slow for large datasets")
    scan.set_defaults(func=cmd_scan)
    summary = sub.add_parser("summary", help="summarize an existing catalog")
    summary.add_argument("catalog")
    summary.add_argument("--show", type=int, default=25, help="number of candidate examples to print")
    summary.set_defaults(func=cmd_summary)
    return p


if __name__ == "__main__":
    parsed = parser().parse_args()
    sys.exit(parsed.func(parsed))
