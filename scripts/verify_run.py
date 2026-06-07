#!/usr/bin/env python3
"""Prove a production-authoring run end to end from persisted artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from omegaconf import OmegaConf  # noqa: E402

from src.utils.packed_runtime import evaluate_body, gate_failures  # noqa: E402


def _require(path: Path) -> Path:
    if not path.exists():
        raise RuntimeError(f"missing required artifact: {path}")
    return path


def _median(rows: list[dict], key: str) -> float:
    return float(statistics.median(float(row[key]) for row in rows))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(run_dir: Path, promotion_dir: Path | None) -> dict:
    manifest = json.loads(_require(run_dir / "manifest.json").read_text(encoding="utf-8"))
    cfg = OmegaConf.load(_require(run_dir / "resolved_config.yaml"))
    reference = json.loads(_require(run_dir / "reference_aggregate.json").read_text(encoding="utf-8"))
    _require(run_dir / "archive_checkpoint.json")
    _require(run_dir / "events.jsonl")
    artifact_manifest = json.loads(_require(run_dir / "wandb_artifact_manifest.json").read_text(encoding="utf-8"))
    if "keepers" not in artifact_manifest.get("paths", []):
        raise RuntimeError("W&B artifact manifest does not include keeper artifacts")
    wandb_runs = list(_require(run_dir / "wandb").glob("offline-run-*/*.wandb"))
    if not wandb_runs:
        raise RuntimeError("missing W&B offline run record")
    keepers = manifest.get("keepers", [])
    if not keepers:
        raise RuntimeError("manifest contains no keepers")
    required_specialists = [str(slot.id) for slot in cfg.specialists.slots]
    exported_specialists = [str(keeper.get("specialist", "")) for keeper in keepers]
    coverage = manifest.get("specialist_coverage", {})
    if len(set(exported_specialists)) != len(exported_specialists):
        raise RuntimeError("manifest contains duplicate specialist keepers")
    if bool(cfg.model.require_full_specialist_coverage):
        if set(exported_specialists) != set(required_specialists):
            raise RuntimeError("manifest specialist keeper coverage mismatch")
        if coverage.get("missing") or set(coverage.get("exported", [])) != set(required_specialists):
            raise RuntimeError("manifest specialist coverage report mismatch")
    audited = []
    for keeper in keepers:
        folder = run_dir / "keepers" / keeper["slug"]
        bodies = list(folder.glob("*.body240"))
        carts = list(folder.glob("*.cart.json"))
        plots = list(folder.glob("*.png"))
        wavs = list(folder.glob("*.wav"))
        if len(bodies) != 1 or len(carts) != 1 or not plots or len(wavs) < 3:
            raise RuntimeError(f"incomplete keeper artifact set: {folder}")
        cart = json.loads(carts[0].read_text(encoding="utf-8"))
        if cart.get("format") != "compiled-v1":
            raise RuntimeError(f"{carts[0]} is not compiled-v1")
        metrics = evaluate_body(bodies[0].read_bytes(), int(cfg.model.final_grid_steps))
        failures = gate_failures(metrics, cfg.model.gates, reference)
        if failures:
            raise RuntimeError(f"{bodies[0]} failed verifier gates: {failures}")
        audited.append(metrics)
    aggregate = {
        "keepers": len(audited),
        "median_endpoint_span_db": _median(audited, "endpoint_span_db_mean"),
        "median_morph_contrast_db": _median(audited, "morph_contrast_rms_db"),
        "median_secondary_contrast_db": _median(audited, "secondary_contrast_rms_db"),
        "median_center_span_db": _median(audited, "center_span_db"),
        "minimum_max_pole_radius": min(float(row["max_pole_radius"]) for row in audited),
        "unstable_rows": sum(int(row["grid_unstable_rows"]) for row in audited),
        "nonfinite_rows": sum(int(row["grid_nonfinite_rows"]) for row in audited),
    }
    comparisons = {
        "endpoint_span_vs_rom": aggregate["median_endpoint_span_db"] > reference["median_endpoint_span_db"],
        "morph_contrast_vs_rom": aggregate["median_morph_contrast_db"] > reference["median_morph_contrast_db"],
        "secondary_contrast_vs_rom": aggregate["median_secondary_contrast_db"] > reference["median_secondary_contrast_db"],
    }
    if not all(comparisons.values()):
        raise RuntimeError(f"keeper aggregate does not beat ROM calibration: {comparisons}")
    if promotion_dir is not None:
        promotion = json.loads(_require(promotion_dir / "promotion.json").read_text(encoding="utf-8"))
        if promotion.get("format") != "production-authoring-promotion-v1":
            raise RuntimeError("promotion manifest is not production-authoring-promotion-v1")
        if Path(promotion.get("source_run", "")).resolve() != run_dir.resolve():
            raise RuntimeError("promotion manifest source run mismatch")
        if len(promotion.get("promoted", [])) != len(keepers):
            raise RuntimeError("promotion manifest keeper count mismatch")
        promoted = {row["slug"]: row for row in promotion["promoted"]}
        if set(promoted) != {keeper["slug"] for keeper in keepers}:
            raise RuntimeError("promotion manifest keeper slugs mismatch")
        for keeper in keepers:
            row = promoted[keeper["slug"]]
            folder = promotion_dir / row["slug"]
            body = _require(folder / row["body240"])
            carts = list(folder.glob("*.cart.json"))
            if len(carts) != 1:
                raise RuntimeError(f"incomplete promoted cartridge set: {folder}")
            cart = json.loads(carts[0].read_text(encoding="utf-8"))
            if cart.get("format") != "compiled-v1":
                raise RuntimeError(f"{carts[0]} is not compiled-v1")
            source_body = _require(run_dir / "keepers" / row["slug"] / row["body240"])
            digest = _sha256(body)
            if digest != row.get("body240_sha256") or digest != _sha256(source_body):
                raise RuntimeError(f"promoted body hash mismatch: {body}")
            metrics = evaluate_body(body.read_bytes(), int(cfg.model.final_grid_steps))
            failures = gate_failures(metrics, cfg.model.gates, reference)
            if failures:
                raise RuntimeError(f"{body} failed promoted-byte verifier gates: {failures}")
    return {"run_dir": str(run_dir), "aggregate": aggregate, "reference": reference, "comparisons": comparisons}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--promotion-dir", type=Path)
    args = parser.parse_args()
    report = verify(args.run_dir.resolve(), args.promotion_dir.resolve() if args.promotion_dir else None)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
