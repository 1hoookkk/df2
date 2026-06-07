from __future__ import annotations

from pathlib import Path
import hashlib
import json

from omegaconf import OmegaConf

from pyruntime import trench_ffi
from src.architectures.trajectory_program import LABELS, sample_program, sample_specialist_program
from src.datamodules.calibration import load_reference_aggregate
from src.utils.body240 import raw_from_words, words_from_kernels
from src.utils.packed_runtime import evaluate_body, gate_failures
from src.utils.export_runtime import promote_run

ROOT = Path(__file__).resolve().parents[1]


def generation_cfg():
    return OmegaConf.load(ROOT / "configs" / "model" / "smoke.yaml").generation


def specialist_cfg():
    return OmegaConf.load(ROOT / "configs" / "specialists" / "full_bank.yaml")


def test_production_package_does_not_import_exploratory_tools():
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from tools" not in text and "import tools" not in text, path
    for path in (ROOT / "src" / "architectures").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from pyruntime" not in text and "import pyruntime" not in text, path


def test_lawful_program_authors_four_joint_packed_corners():
    program = sample_program(12345, "opposed_window", generation_cfg())
    words = words_from_kernels(program.corner_kernels())
    body = raw_from_words(words)
    assert tuple(words) == LABELS
    assert all(len(rows) == 6 for rows in words.values())
    assert len(body) == trench_ffi.BODY_BYTES


def test_full_bank_defines_fifty_original_specialists():
    cfg = specialist_cfg()
    slots = list(cfg.slots)
    assert len(slots) == 50
    assert len({str(slot.id) for slot in slots}) == 50
    forbidden = ("p2k", "lucifer", "razor", "angelz", "meaty", "millennium", "talking_hedz")
    assert not any(term in str(slot.id).lower() for slot in slots for term in forbidden)
    for index, slot in enumerate(slots):
        program = sample_specialist_program(
            10_000 + index, str(slot.id), str(slot.profile), generation_cfg(), cfg.profiles)
        assert program.specialist == str(slot.id)
        assert len(program.stages) == 6
        assert tuple(program.corner_kernels()) == LABELS


def test_real_packed_runtime_scores_generated_body():
    assert trench_ffi.available()
    body = raw_from_words(words_from_kernels(sample_program(321, "vocal_mountains", generation_cfg()).corner_kernels()))
    metrics = evaluate_body(body, 5)
    assert metrics["grid_points"] == 25
    assert metrics["grid_unstable_rows"] == 0
    assert metrics["grid_nonfinite_rows"] == 0
    assert metrics["median_zero_motion_octaves"] > 0.0


def test_audit_probes_between_grid_nodes_for_stability():
    assert trench_ffi.available()
    body = raw_from_words(words_from_kernels(sample_program(321, "vocal_mountains", generation_cfg()).corner_kernels()))
    metrics = evaluate_body(body, 5)
    # midpoints of a 5-node axis -> 4 interior nodes per axis -> 4x4 interior grid
    assert metrics["interior_grid_points"] == 16
    assert metrics["interior_unstable_rows"] == 0
    assert metrics["interior_nonfinite_rows"] == 0
    # the reported hottest pole must account for the between-node samples too
    assert metrics["max_pole_radius"] >= metrics["interior_max_pole_radius"]


def _loose_gates():
    model = OmegaConf.load(ROOT / "configs" / "model" / "smoke.yaml")
    model.gates.maximum_pole_radius = 1.0
    model.gates.minimum_ceiling_radius = 0.0
    model.gates.minimum_center_span_db = 0.0
    model.gates.minimum_endpoint_span_db = 0.0
    model.gates.maximum_span_db = 1_000.0
    model.gates.minimum_morph_contrast_db = 0.0
    model.gates.minimum_secondary_contrast_db = 0.0
    model.gates.minimum_center_peaks = 0
    model.gates.minimum_center_valleys = 0
    model.gates.minimum_zero_motion_octaves = 0.0
    model.gates.reference_endpoint_span_ratio = 0.0
    model.gates.reference_morph_contrast_ratio = 0.0
    model.gates.reference_secondary_contrast_ratio = 0.0
    return model.gates


def _passing_metrics(**overrides):
    metrics = {
        "stable": True, "finite": True,
        "grid_unstable_rows": 0, "grid_nonfinite_rows": 0,
        "interior_unstable_rows": 0, "interior_nonfinite_rows": 0,
        "max_pole_radius": 0.5,
        "center_span_db": 100.0, "endpoint_span_db_mean": 100.0,
        "morph_contrast_rms_db": 100.0, "secondary_contrast_rms_db": 100.0,
        "center_response_peaks": 5, "center_response_valleys": 5,
        "median_zero_motion_octaves": 1.0,
    }
    metrics.update(overrides)
    return metrics


def test_gate_rejects_instability_found_between_grid_nodes():
    gates = _loose_gates()
    reference = {"median_endpoint_span_db": 0.0, "median_morph_contrast_db": 0.0,
                 "median_secondary_contrast_db": 0.0}
    clean = gate_failures(_passing_metrics(), gates, reference)
    assert "packed surface is unstable or non-finite" not in clean
    between_node = gate_failures(_passing_metrics(interior_unstable_rows=1), gates, reference)
    assert "packed surface is unstable or non-finite" in between_node


def test_reference_datamodule_emits_aggregate_only():
    datamodule = OmegaConf.load(ROOT / "configs" / "datamodule" / "p2k_calibration.yaml")
    aggregate = load_reference_aggregate(ROOT, datamodule)
    assert aggregate["policy"] == "aggregate_metrics_only"
    assert aggregate["bodies"] > 0
    assert "bytes_hex" not in aggregate


def test_promotion_reaudits_real_body_and_is_immutable(tmp_path):
    source = tmp_path / "run"
    keeper = source / "keepers" / "proof"
    keeper.mkdir(parents=True)
    body = raw_from_words(words_from_kernels(sample_program(999, "opposed_window", generation_cfg()).corner_kernels()))
    (keeper / "proof.body240").write_bytes(body)
    (source / "manifest.json").write_text(json.dumps({"keepers": [{"slug": "proof"}]}), encoding="utf-8")
    model = OmegaConf.load(ROOT / "configs" / "model" / "smoke.yaml")
    model.gates.maximum_pole_radius = 1.0
    model.gates.minimum_ceiling_radius = 0.0
    model.gates.minimum_center_span_db = 0.0
    model.gates.minimum_endpoint_span_db = 0.0
    model.gates.maximum_span_db = 1_000.0
    model.gates.minimum_morph_contrast_db = 0.0
    model.gates.minimum_secondary_contrast_db = 0.0
    model.gates.minimum_center_peaks = 0
    model.gates.minimum_center_valleys = 0
    model.gates.minimum_zero_motion_octaves = 0.0
    model.gates.reference_endpoint_span_ratio = 0.0
    model.gates.reference_morph_contrast_ratio = 0.0
    model.gates.reference_secondary_contrast_ratio = 0.0
    OmegaConf.save({"model": model}, source / "resolved_config.yaml")
    aggregate = load_reference_aggregate(ROOT, OmegaConf.load(ROOT / "configs" / "datamodule" / "p2k_calibration.yaml"))
    (source / "reference_aggregate.json").write_text(json.dumps(aggregate), encoding="utf-8")
    destination = tmp_path / "promoted"
    report = promote_run(source, destination)
    assert report["promoted"][0]["grid_points"] == 289
    assert report["promoted"][0]["body240_sha256"] == hashlib.sha256(body).hexdigest()
    assert (destination / "proof" / "proof.body240").read_bytes() == body
    try:
        promote_run(source, destination)
    except FileExistsError:
        pass
    else:
        raise AssertionError("promotion must refuse to overwrite an existing immutable target")
