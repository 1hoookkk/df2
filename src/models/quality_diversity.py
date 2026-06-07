"""Quality-diversity search orchestration for original packed DF2 bodies."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
from typing import Any

from omegaconf import OmegaConf

from pyruntime import trench_ffi
from src.architectures.trajectory_program import ProgramGenome, sample_specialist_program
from src.datamodules.calibration import load_reference_aggregate
from src.utils.body240 import raw_from_words, words_from_kernels
from src.utils.export_runtime import export_candidate
from src.utils.packed_runtime import archive_cell, evaluate_body, gate_failures
from src.utils.telemetry import Telemetry


@dataclass(frozen=True)
class Candidate:
    slug: str
    name: str
    specialist: str
    genome: ProgramGenome
    words: dict[str, list[tuple[int, ...]]]
    metrics: dict[str, Any]
    cell: tuple[int, ...]


def _candidate(seed: int, slot: Any, cfg: Any, reference: dict[str, Any]) -> tuple[Candidate, list[str]]:
    specialist = str(slot.id)
    genome = sample_specialist_program(
        seed,
        specialist,
        str(slot.profile),
        cfg.model.generation,
        cfg.specialists.profiles,
    )
    words = words_from_kernels(genome.corner_kernels())
    body = raw_from_words(words)
    metrics = evaluate_body(body, int(cfg.model.search_grid_steps))
    failures = gate_failures(metrics, cfg.model.gates, reference)
    slug = f"{specialist}_{seed:08d}"
    return Candidate(slug, specialist.replace("_", " ").title(), specialist, genome, words, metrics,
                     archive_cell(metrics, cfg.model.archive)), failures


def run(cfg: Any) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    if not trench_ffi.available() or not trench_ffi.engine_available():
        raise RuntimeError("current release trench_core.dll with packed probe and engine FFI is required")
    out_dir = (root / str(cfg.output_dir)).resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise RuntimeError(f"immutable run directory already exists and is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "resolved_config.yaml").write_text(OmegaConf.to_yaml(cfg, resolve=True), encoding="utf-8")
    reference = load_reference_aggregate(root, cfg.datamodule)
    (out_dir / "reference_aggregate.json").write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
    telemetry = Telemetry(out_dir, cfg.telemetry, str(cfg.run_name))
    telemetry.log("reference", reference, step=0)
    archive: dict[tuple[Any, ...], Candidate] = {}
    rejected: dict[str, int] = {}
    specialist_slots = list(cfg.specialists.slots)
    specialist_ids = [str(slot.id) for slot in specialist_slots]
    if len(set(specialist_ids)) != len(specialist_ids):
        raise RuntimeError("specialist IDs must be unique")
    rng = random.Random(int(cfg.seed))
    for iteration in range(int(cfg.model.iterations)):
        slot = specialist_slots[iteration % len(specialist_slots)]
        seed = rng.randrange(1, 2_147_483_647)
        candidate, failures = _candidate(seed, slot, cfg, reference)
        if failures:
            for failure in failures:
                rejected[failure] = rejected.get(failure, 0) + 1
            continue
        archive_key = (candidate.specialist, *candidate.cell)
        prior = archive.get(archive_key)
        if prior is None or candidate.metrics["objective"] > prior.metrics["objective"]:
            archive[archive_key] = candidate
            telemetry.log("archive", {
                "objective": candidate.metrics["objective"],
                "endpoint_span_db": candidate.metrics["endpoint_span_db_mean"],
                "center_span_db": candidate.metrics["center_span_db"],
                "morph_contrast_db": candidate.metrics["morph_contrast_rms_db"],
                "secondary_contrast_db": candidate.metrics["secondary_contrast_rms_db"],
                "zero_motion_octaves": candidate.metrics["median_zero_motion_octaves"],
                "archive_cells": len(archive),
            }, step=iteration + 1)
    if not archive:
        telemetry.finish()
        raise RuntimeError(f"search produced no packed-runtime survivors; rejection counts: {rejected}")
    ranked = sorted(archive.values(), key=lambda candidate: candidate.metrics["objective"], reverse=True)
    best_by_specialist: dict[str, Candidate] = {}
    for candidate in ranked:
        best_by_specialist.setdefault(candidate.specialist, candidate)
    missing_specialists = sorted(set(specialist_ids) - set(best_by_specialist))
    if missing_specialists and bool(cfg.model.require_full_specialist_coverage):
        telemetry.finish()
        raise RuntimeError(f"search missed required specialist slots: {missing_specialists}")
    checkpoint = {
        "format": "production-authoring-archive-v1",
        "cells": [
            {
                "cell": list(candidate.cell),
                "specialist": candidate.specialist,
                "family": candidate.genome.family,
                "seed": candidate.genome.seed,
                "sha256": hashlib.sha256(raw_from_words(candidate.words)).hexdigest(),
                "metrics": candidate.metrics,
                "genome": candidate.genome.to_dict(),
            }
            for candidate in ranked
        ],
    }
    checkpoint_path = out_dir / "archive_checkpoint.json"
    checkpoint_path.write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
    export_candidates = sorted(best_by_specialist.values(),
                               key=lambda candidate: candidate.metrics["objective"], reverse=True)
    export_candidates = export_candidates[: int(cfg.export.top_k)]
    keepers = []
    for rank, candidate in enumerate(export_candidates, start=1):
        # Full-resolution audit is mandatory before any runtime artifact leaves the run.
        final_metrics = evaluate_body(raw_from_words(candidate.words), int(cfg.model.final_grid_steps))
        failures = gate_failures(final_metrics, cfg.model.gates, reference)
        if failures:
            continue
        candidate = Candidate(candidate.slug, candidate.name, candidate.specialist,
                              candidate.genome, candidate.words,
                              final_metrics, candidate.cell)
        keeper_dir = out_dir / "keepers" / candidate.slug
        exported = export_candidate(
            candidate,
            keeper_dir,
            render_audio=bool(cfg.export.render_audio),
            audition_source=str(cfg.datamodule.audition_source),
            audition_drive=float(cfg.export.audition_drive),
        )
        exported["rank"] = rank
        exported["specialist"] = candidate.specialist
        exported["metrics"] = final_metrics
        keepers.append(exported)
    if not keepers:
        telemetry.finish()
        raise RuntimeError("archive had survivors but none passed the mandatory final 17x17 audit")
    final_missing_specialists = sorted(set(specialist_ids) - {keeper["specialist"] for keeper in keepers})
    if final_missing_specialists and bool(cfg.model.require_full_specialist_coverage):
        telemetry.finish()
        raise RuntimeError(f"final 17x17 audit missed required specialist slots: {final_missing_specialists}")
    report = {
        "format": "production-authoring-run-v1",
        "run_name": str(cfg.run_name),
        "workflow": "Hydra config -> aggregate calibration -> lawful whole-body trajectories -> "
                    "quality-diversity archive -> trench-core 17x17 audit -> body240 export -> engine audition",
        "reference": reference,
        "iterations": int(cfg.model.iterations),
        "archive_cells": len(archive),
        "specialist_coverage": {
            "required": specialist_ids,
            "exported": sorted(keeper["specialist"] for keeper in keepers),
            "missing": final_missing_specialists,
        },
        "rejection_counts": rejected,
        "keepers": keepers,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    telemetry.log("complete", {"archive_cells": len(archive), "keepers": len(keepers),
                               "specialists": len(best_by_specialist)},
                  step=int(cfg.model.iterations) + 1)
    telemetry.log_artifact(str(cfg.run_name), [
        manifest_path,
        checkpoint_path,
        out_dir / "reference_aggregate.json",
        out_dir / "resolved_config.yaml",
        out_dir / "events.jsonl",
        out_dir / "keepers",
    ])
    telemetry.finish()
    print(f"run      -> {out_dir}")
    print(f"archive  -> {len(archive)} diverse packed-runtime cells")
    print(f"coverage -> {len(best_by_specialist)}/{len(specialist_ids)} original specialist slots")
    print(f"keepers  -> {len(keepers)} real body240 cartridges")
    for keeper in keepers:
        metrics = keeper["metrics"]
        print(
            f"  {keeper['slug']:<34} score={metrics['objective']:.1f} "
            f"span={metrics['endpoint_span_db_mean']:.1f} "
            f"morph={metrics['morph_contrast_rms_db']:.1f} "
            f"secondary={metrics['secondary_contrast_rms_db']:.1f} "
            f"maxR={metrics['max_pole_radius']:.6f}"
        )
    return report
