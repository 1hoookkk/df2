from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi
from tools import build_acoustic_recipe as builder
from tools import three_layer_acoustic_forge as forge


def _assert_recipe_compiles(doc):
    recipe_path = ROOT / "dev" / "tmp" / "anatomy_forge_verify" / f"{doc['name']}.json"
    recipe_path.parent.mkdir(parents=True, exist_ok=True)
    recipe_path.write_text(__import__("json").dumps(doc, indent=2) + "\n", encoding="utf-8")
    recipe = forge.load_recipe(recipe_path)
    body, words, report = forge.build_body(
        recipe.sample_rate_hz,
        anatomy=recipe.anatomy,
        articulation=recipe.articulation,
        survival=recipe.survival,
    )
    audit = forge.audit(body, grid=5)
    assert len(body) == trench_ffi.BODY_BYTES
    assert tuple(words) == forge.CORNER_ORDER
    assert len(report["anatomy"]) == 6
    assert len(report["articulation"]) == 6
    assert audit["unstable_mask"] == 0
    assert audit["nonfinite_mask"] == 0


def test_vocal_recipe_uses_formant_and_bandwidth_tables():
    tables = builder.load_tables()
    doc = builder.vocal_recipe(tables, "uw", "iy", "male")
    assert "vowel_formants.json" in doc["table_sources"]
    assert "klatt_1980_bandwidths.json" in doc["table_sources"]
    assert doc["articulation"]["zero_table_archetype"] == "vowel:uw->iy"
    _assert_recipe_compiles(doc)


def test_tube_recipe_uses_tube_table():
    tables = builder.load_tables()
    doc = builder.tube_recipe(tables, "oo_50cm", "oo_10cm")
    assert "tube_resonances.json" in doc["table_sources"]
    _assert_recipe_compiles(doc)


def test_metal_recipe_uses_metallic_table():
    tables = builder.load_tables()
    doc = builder.metal_recipe(tables, "bell", "free_plate", None)
    assert "metallic_modes.json" in doc["table_sources"]
    _assert_recipe_compiles(doc)


def test_family_recipe_uses_family_intents_table():
    tables = builder.load_tables()
    doc = builder.family_recipe(tables, "comb", "chambered_phaser", "phasing_sweep")
    assert "family_intents.json" in doc["table_sources"]
    _assert_recipe_compiles(doc)
