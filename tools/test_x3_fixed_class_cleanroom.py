from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi
from tools import x3_fixed_class_cleanroom as x3


def _entry(name: str):
    manifest = x3.load_manifest()
    for entry in x3.fixed_entries(manifest):
        if entry["name"] == name:
            return entry
    raise AssertionError(f"missing X3 fixed entry: {name}")


def test_x3_fixed_decode_lowpass_oracle_is_stable_lowpass():
    entry = _entry("2 Pole Lowpass")
    corners = x3.read_target_corners(entry, 48_000)
    assert len(corners) == 4
    for corner in corners:
        assert all(x3.poles_stable(stage[3], stage[4]) for stage in corner.stages)
        low = float(np.mean(corner.response_db[(x3.FIT_FREQS >= 80.0) & (x3.FIT_FREQS <= 180.0)]))
        high = float(np.mean(corner.response_db[(x3.FIT_FREQS >= 8_000.0) & (x3.FIT_FREQS <= 12_000.0)]))
        assert low - high > 3.0


def test_x3_cleanroom_compile_emits_recipe_body240_and_shape_report(tmp_path):
    assert trench_ffi.available()
    row = x3.process_entry(_entry("2 Pole Lowpass"), 48_000, tmp_path, plots=False, audit_grid=3)
    out_dir = tmp_path / row["name"]
    body = (out_dir / f"{row['name']}.body240").read_bytes()
    recipe = json.loads((out_dir / f"{row['name']}.recipe.json").read_text(encoding="utf-8"))
    compare = json.loads((out_dir / f"{row['name']}.shape_compare.json").read_text(encoding="utf-8"))
    cart = json.loads((out_dir / f"{row['name']}.cart.json").read_text(encoding="utf-8"))

    assert len(body) == trench_ffi.BODY_BYTES
    assert recipe["format"] == "x3-fixed-cleanroom-recipe-v1"
    assert recipe["source_policy"]["decoded_response_only"] is True
    assert recipe["compile_policy"]["comparison"] == "offset-normalized magnitude shape RMS; bytes are not compared"
    assert compare["policy"] == "shape_only_no_byte_comparison"
    assert compare["mean_offset_normalized_rms_db"] >= 0.0
    assert cart["format"] == "compiled-v1"
    assert all(len(kf["packedWords"]) == 6 for kf in cart["keyframes"])
