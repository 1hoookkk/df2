#!/usr/bin/env python3
"""extract-candidates — four TF JSON measurements -> one deterministic candidate set.

  python -m tools.extract_candidates RECIPE.json OUTPUT.candidates.json

RECIPE.json:
  {
    "schema_version": 1,
    "name": "my_body",
    "corners": {                        // exactly these four keys, this order
      "M0_Q0":    "path/to/a.tf.json",  // or {"path": "...", "catalog_record": "id"}
      "M100_Q0":  "...",
      "M0_Q100":  "...",
      "M100_Q100":"..."
    }
  }

Each TF JSON is the tf_ingest shape: {"freqs_hz": [...], "mag_db": [...]}.
Fitting, quantization, exact topology classification, the stability gate, and
the residual all run in trench-core's fit-candidates bin (arma::
fit_corner_from_magnitude -> minifloat::encode -> stage_law::
geometry_from_words) — this script does no filter math. Output contains NO
stage slots, NO lane ids, NO cross-corner correspondence: candidates are an
unordered per-corner collection for MANUAL lane registration.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FITTER = ROOT / "target" / "release" / "fit-candidates.exe"
CORNERS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
TOOL_VERSION = 1
METHOD = "arma::fit_corner_from_magnitude via trench-core fit-candidates v1"


def die(msg):
    print("INVALID:", msg)
    sys.exit(1)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_tf(path: Path):
    """Reject non-TF input before it reaches the fitter."""
    raw = path.read_bytes()
    if raw[:4] in (b"RIFF", b"RIFX"):
        die(f"{path}: is a WAV file, not a TF JSON — run tools/tf_ingest on it first "
            "(a raw WAV is not an impulse-response claim)")
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        die(f"{path}: not valid JSON")
    if not (isinstance(d, dict) and isinstance(d.get("freqs_hz"), list)
            and isinstance(d.get("mag_db"), list)):
        die(f"{path}: expected tf_ingest TF JSON with freqs_hz + mag_db arrays")
    f, m = d["freqs_hz"], d["mag_db"]
    if len(f) != len(m) or len(f) < 2:
        die(f"{path}: freqs_hz/mag_db must be equal-length with >= 2 points")
    prev = 0.0
    for i, (fv, mv) in enumerate(zip(f, m)):
        if not (isinstance(fv, (int, float)) and isinstance(mv, (int, float))
                and math.isfinite(fv) and math.isfinite(mv)):
            die(f"{path}: nonfinite TF data at index {i}")
        if fv <= prev:
            die(f"{path}: frequencies must be strictly ascending and > 0 "
                f"(index {i}: {prev} -> {fv} — duplicates are invalid)")
        prev = fv
    return d


def candidate_id(corner, source_sha, stage, seen):
    """Deterministic id from corner + source hash + the exact packed words.
    Identical stages within a corner get a stable -2/-3 suffix (occurrence
    among EQUAL candidates only — never an ordering over distinct ones)."""
    key = json.dumps([corner, source_sha, stage["packed_words"]], separators=(",", ":"))
    h = hashlib.sha256(key.encode()).hexdigest()[:12]
    n = seen.get(h, 0) + 1
    seen[h] = n
    return f"cand-{h}" if n == 1 else f"cand-{h}-{n}"


def extract(recipe_path: Path, out_path: Path):
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    if recipe.get("schema_version") != 1:
        die("recipe schema_version must be 1")
    name = recipe.get("name")
    if not (isinstance(name, str) and name):
        die("recipe name: required non-empty string")
    corners_in = recipe.get("corners")
    if not isinstance(corners_in, dict) or list(corners_in.keys()) != CORNERS:
        die(f"recipe corners must be exactly {CORNERS} in that order; "
            f"got {list(corners_in.keys()) if isinstance(corners_in, dict) else corners_in!r}")
    if not FITTER.exists():
        die(f"fitter missing: {FITTER}\n"
            "build: cargo build --release -p trench-core --bin fit-candidates")

    corners_out = {}
    report = []
    for corner in CORNERS:
        entry = corners_in[corner]
        if isinstance(entry, str):
            src_path, catalog_record = entry, None
        elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
            src_path, catalog_record = entry["path"], entry.get("catalog_record")
        else:
            die(f"corners.{corner}: must be a path string or {{path, catalog_record}}")
        src = Path(src_path)
        if not src.is_absolute():
            src = (recipe_path.parent / src).resolve()
        if not src.exists():
            die(f"corners.{corner}: {src} does not exist")
        validate_tf(src)
        src_sha = sha256(src)

        with tempfile.TemporaryDirectory() as td:
            fit_out = Path(td) / "fit.json"
            r = subprocess.run([str(FITTER), str(src), str(fit_out)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                die(f"corners.{corner}: fitter refused {src.name}:\n{r.stdout}{r.stderr}")
            fit = json.loads(fit_out.read_text(encoding="utf-8"))

        seen = {}
        candidates = []
        topo_count = {}
        for stage in fit["stages"]:
            cid = candidate_id(corner, src_sha, stage, seen)
            candidates.append({
                "id": cid,
                "topology": stage["topology"],
                "state": stage["state"],
                "pole": stage["pole"],
                "zero": stage["zero"],
                "scale": stage["scale"],
                "packed_words": stage["packed_words"],
                "provenance": {
                    "source": src.as_posix(),
                    "source_sha256": src_sha,
                    "method": METHOD,
                },
            })
            t = f"{stage['topology']['pole']}/{stage['topology']['zero']}"
            topo_count[t] = topo_count.get(t, 0) + 1
        corners_out[corner] = {
            "source": {"path": src.as_posix(), "catalog_record": catalog_record,
                       "sha256": src_sha},
            "extraction": {
                "runtime_sr_hz": fit["runtime_sr_hz"],
                "n_points": fit["n_points"],
                "fitter_tool_version": fit["tool_version"],
            },
            "fit": fit["fit"],
            "candidates": candidates,
        }
        report.append((corner, src.name, len(candidates), topo_count,
                       fit["fit"]["residual_rms_db"]))

    out = {
        "schema_version": 1,
        "extractor": {"tool": "tools/extract_candidates.py",
                      "tool_version": TOOL_VERSION,
                      "fitter": METHOD},
        "name": name,
        "corner_order": list(CORNERS),
        "corners": corners_out,
    }
    out_path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("wrote", out_path)
    for corner, srcname, n, topo, rms in report:
        topos = ", ".join(f"{k} x{v}" for k, v in sorted(topo.items()))
        print(f"  {corner}: {srcname} -> {n} candidates ({topos}) residual rms {rms:.2f} dB")
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    extract(Path(sys.argv[1]), Path(sys.argv[2]))


if __name__ == "__main__":
    main()
