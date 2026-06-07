from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db, freq_points
from tools import three_layer_acoustic_forge as forge


def _response(body: bytes, morph: float, secondary: float) -> np.ndarray:
    rows = trench_ffi.packed_interpolate(body, morph, secondary)
    return cascade_response_db([EncodedCoeffs(*row) for row in rows], freq_points(), forge.AUTHORING_SR)


def test_three_layer_compiler_outputs_stable_legal_body240():
    body, words, report = forge.build_body(forge.AUTHORING_SR, survival_factor=0.45)
    audit = forge.audit(body, grid=9)

    assert len(body) == trench_ffi.BODY_BYTES
    assert tuple(words) == forge.CORNER_ORDER
    assert all(len(rows) == 6 for rows in words.values())
    assert audit["unstable_mask"] == 0
    assert audit["nonfinite_mask"] == 0
    assert audit["max_pole_radius"] < 1.0
    assert report["corners"]["M100_Q100"][0]["survival_db"] > 0.0


def test_json_recipe_is_the_compiler_input_surface():
    recipe = forge.load_recipe(
        ROOT / "recipes" / "three_layer_acoustic_forge" / "cleanroom_three_layer_acoustic_recipe.json"
    )
    body, words, report = forge.build_body(
        recipe.sample_rate_hz,
        anatomy=recipe.anatomy,
        articulation=recipe.articulation,
        survival=recipe.survival,
    )
    audit = forge.audit(body, grid=9)

    assert recipe.name == "cleanroom_three_layer_acoustic_recipe"
    assert len(body) == trench_ffi.BODY_BYTES
    assert tuple(words) == forge.CORNER_ORDER
    assert report["survival"]["gain_compensation_strategy"] == "normalize_stages"
    assert audit["unstable_mask"] == 0
    assert audit["nonfinite_mask"] == 0


def test_survival_budget_prevents_pressurized_collapse():
    survived, _, _ = forge.build_body(forge.AUTHORING_SR, survival_factor=0.45)
    dry, _, _ = forge.build_body(forge.AUTHORING_SR, survival_factor=0.0)
    freqs = freq_points()
    band = (freqs >= 80.0) & (freqs <= 8000.0)

    survived_db = _response(survived, 1.0, 1.0)
    dry_db = _response(dry, 1.0, 1.0)

    assert float(np.mean(survived_db[band] - dry_db[band])) > 20.0
