"""Load ROM study fixtures and reduce them to aggregate calibration metrics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from src.utils.terrain_metrics import analyze_body


def _median(rows: list[dict[str, Any]], key: str) -> float:
    return float(np.median([float(row[key]) for row in rows if row.get(key) is not None]))


def load_reference_aggregate(root: Path, cfg: Any) -> dict[str, Any]:
    """Return aggregate-only calibration. Raw reference bodies never leave this function."""
    path = root / str(cfg.reference_jsonl)
    variant = int(cfg.reference_variant)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if int(record["variant"]) != variant:
            continue
        rows.append(analyze_body(bytes.fromhex(record["bytes_hex"])))
    if not rows:
        raise RuntimeError(f"no reference calibration rows found in {path}")
    return {
        "policy": str(cfg.reference_policy),
        "reference_jsonl": str(path.relative_to(root)).replace("\\", "/"),
        "variant": variant,
        "bodies": len(rows),
        "median_endpoint_span_db": _median(rows, "endpoint_span_db_mean"),
        "median_center_span_db": _median(rows, "center_span_db"),
        "median_morph_contrast_db": _median(rows, "morph_contrast_rms_db"),
        "median_secondary_contrast_db": _median(rows, "secondary_contrast_rms_db"),
        "median_center_peaks": _median(rows, "center_response_peaks"),
        "median_center_valleys": _median(rows, "center_response_valleys"),
        "median_max_pole_radius": _median(rows, "max_pole_radius"),
    }
