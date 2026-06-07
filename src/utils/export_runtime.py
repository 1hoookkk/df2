"""Export searched programs as real runtime bodies and compiled cartridges."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
from typing import Any

from omegaconf import OmegaConf

from pyruntime import trench_ffi
from src.utils import audition
from src.utils.body240 import compiled_payload, raw_from_words, render_png
from src.utils.packed_runtime import evaluate_body, gate_failures


def export_candidate(candidate: Any, out_dir: Path, *, render_audio: bool,
                     audition_source: str, audition_drive: float) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = candidate.slug
    words = candidate.words
    body = raw_from_words(words)
    if len(body) != trench_ffi.BODY_BYTES:
        raise RuntimeError(f"export body length mismatch: {len(body)}")
    payload = compiled_payload(candidate.name, 1.0, words)
    payload["provenance"] = "clean-room trajectory program -> packed trench-core audit -> quality-diversity archive"
    payload["authoring"] = {
        "workflow": "production-authoring-v1",
        "family": candidate.genome.family,
        "specialist": candidate.specialist,
        "seed": candidate.genome.seed,
        "romPolicy": "aggregate calibration only; no reference coefficients used",
    }
    body_path = out_dir / f"{slug}.body240"
    cart_path = out_dir / f"{slug}.cart.json"
    genome_path = out_dir / f"{slug}.genome.json"
    metrics_path = out_dir / f"{slug}.metrics.json"
    plot_path = out_dir / f"{slug}.png"
    body_path.write_bytes(body)
    cart_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    genome_path.write_text(json.dumps(candidate.genome.to_dict(), indent=2) + "\n", encoding="utf-8")
    metrics_path.write_text(json.dumps(candidate.metrics, indent=2) + "\n", encoding="utf-8")
    render_png(candidate.name, words, plot_path)
    auditions = []
    if render_audio:
        audition.audition(body, slug, out_dir, source_name=audition_source, drive=audition_drive)
        auditions = sorted(path.name for path in out_dir.glob(f"{slug}_*.wav"))
    return {
        "slug": slug,
        "name": candidate.name,
        "family": candidate.genome.family,
        "seed": candidate.genome.seed,
        "objective": candidate.metrics["objective"],
        "body240": str(body_path),
        "cart_json": str(cart_path),
        "plot": str(plot_path),
        "auditions": auditions,
    }


def promote_run(run_dir: Path, destination: Path) -> dict[str, Any]:
    """Copy verified keeper artifacts without re-authoring them."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    cfg = OmegaConf.load(run_dir / "resolved_config.yaml")
    reference = json.loads((run_dir / "reference_aggregate.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    promoted = []
    for keeper in manifest["keepers"]:
        source_dir = run_dir / "keepers" / keeper["slug"]
        target_dir = destination / keeper["slug"]
        if target_dir.exists():
            raise FileExistsError(f"immutable promotion target already exists: {target_dir}")
        body_paths = list(source_dir.glob("*.body240"))
        if len(body_paths) != 1:
            raise RuntimeError(f"{source_dir}: expected exactly one body240 artifact")
        source_body = body_paths[0].read_bytes()
        metrics = evaluate_body(source_body, int(cfg.model.final_grid_steps))
        failures = gate_failures(metrics, cfg.model.gates, reference)
        if failures:
            raise RuntimeError(f"{body_paths[0]} failed promotion-time packed audit: {failures}")
        shutil.copytree(source_dir, target_dir)
        promoted_body = target_dir / body_paths[0].name
        promoted_bytes = promoted_body.read_bytes()
        source_sha256 = hashlib.sha256(source_body).hexdigest()
        promoted_sha256 = hashlib.sha256(promoted_bytes).hexdigest()
        if promoted_sha256 != source_sha256:
            raise RuntimeError(f"{promoted_body} differs from source keeper bytes")
        promoted_metrics = evaluate_body(promoted_bytes, int(cfg.model.final_grid_steps))
        promoted_failures = gate_failures(promoted_metrics, cfg.model.gates, reference)
        if promoted_failures:
            raise RuntimeError(f"{promoted_body} failed copied-byte packed audit: {promoted_failures}")
        promoted.append({
            "slug": keeper["slug"],
            "body240": body_paths[0].name,
            "body240_sha256": promoted_sha256,
            "grid_points": promoted_metrics["grid_points"],
            "max_pole_radius": promoted_metrics["max_pole_radius"],
        })
    report = {"format": "production-authoring-promotion-v1", "source_run": str(run_dir),
              "destination": str(destination), "promoted": promoted}
    (destination / "promotion.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
