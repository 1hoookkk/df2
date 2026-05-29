#!/usr/bin/env python3
"""chimera_describe_refs — read reference 240-byte bodies, emit RESPONSE DESCRIPTORS ONLY.

This is the first half of the Chimera authoring-only workflow. It is NOT a ROM
copier. The P2K/ROM `.bin` files are **internal authoring guardrails**: we read
their *response shape* (band balance, peak/notch landmarks, pole-radius heat,
Morph/Q motion) and write that summary to a descriptor file. We deliberately do
NOT emit any packed words, stages, poles, zeros, or coefficients — the descriptor
is a target *shape* a generator can be steered toward, never source material to
splice.

Input  : one or more `ref/presets/*.bin` (exactly 240 bytes each).
Output : dev/tmp/chimera_refs/<timestamp>/reference_descriptors.json

Run (handoff smoke command):
  python tools/chimera_describe_refs.py --refs \
      ref/presets/P2k_013_talking_hedz.bin \
      ref/presets/P2k_015_dj_alkaline.bin \
      ref/presets/P2k_031_ear_bender.bin
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── path discipline ──────────────────────────────────────────────────────────
# Run directly (`python tools/chimera_describe_refs.py`) puts tools/ first on
# sys.path, where tools/pyruntime/ SHADOWS the real pyruntime and breaks
# pyruntime.packed_interp. Strip the script dir, put repo ROOT first, then the
# real pyruntime + the tools package both resolve.
ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", _HERE, str(ROOT))]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import tools.teleport_stress as ts  # noqa: E402  (loads raw .bin -> A/B/C/D words)
import tools.hedz_floor_profile as hf  # noqa: E402  (band_levels, BANDS)
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db  # noqa: E402
from pyruntime.packed_interp import packed_bilinear, words_to_coeffs  # noqa: E402

AUTHORING_SR = 39062.5
FREQS = np.logspace(math.log10(20.0), math.log10(16000.0), 2048)
CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_KEY = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
BANDS = hf.BANDS  # ("low",20,120),("body",120,800),("bite",800,4000),("air",4000,16000)
BAND_NAMES = [b[0] for b in BANDS]

REUSE_POLICY = (
    "Response descriptors only. No packed words, stages, poles, zeros, or "
    "coefficients are emitted here. References are INTERNAL authoring guardrails "
    "(reference-guided original authoring), never source material to copy."
)


def corner_db(words: list[tuple[int, ...]]) -> np.ndarray:
    """Full-cascade magnitude (dB) for one corner's 6 stages of packed words."""
    enc = [EncodedCoeffs(*words_to_coeffs(w)) for w in words]
    return cascade_response_db(enc, FREQS, AUTHORING_SR)


def band_levels_db(words: list[tuple[int, ...]]) -> dict[str, float]:
    enc = [EncodedCoeffs(*words_to_coeffs(w)) for w in words]
    raw = hf.band_levels(enc, FREQS, AUTHORING_SR, 1.0)
    return {k: round(float(v), 2) for k, v in raw.items()}


def centroid_hz(db: np.ndarray) -> float:
    """Magnitude-weighted spectral centroid (Hz) of a dB curve."""
    w = 10.0 ** (db / 20.0)
    return float(np.sum(FREQS * w) / max(np.sum(w), 1e-12))


def landmarks(db: np.ndarray, prom: float = 4.0, top: int = 6) -> dict[str, list[dict]]:
    """Prominent peaks and notches in a dB curve (shape landmarks, not coeffs)."""
    peaks: list[tuple[float, float, float]] = []
    notches: list[tuple[float, float, float]] = []
    win = 16
    for i in range(2, len(db) - 2):
        seg_lo = min(db[max(0, i - win):i].min(), db[i:i + win].min())
        seg_hi = max(db[max(0, i - win):i].max(), db[i:i + win].max())
        if db[i] >= db[i - 1] and db[i] > db[i + 1] and (db[i] - seg_lo) >= prom:
            peaks.append((float(FREQS[i]), float(db[i]), float(db[i] - seg_lo)))
        if db[i] <= db[i - 1] and db[i] < db[i + 1] and (seg_hi - db[i]) >= prom:
            notches.append((float(FREQS[i]), float(db[i]), float(seg_hi - db[i])))
    peaks.sort(key=lambda x: -x[2])
    notches.sort(key=lambda x: -x[2])

    def pack(items):
        return [
            {"freq_hz": round(f, 1), "level_db": round(l, 2), "prominence_db": round(p, 2)}
            for f, l, p in items[:top]
        ]

    return {"peaks": pack(peaks), "notches": pack(notches), "peak_count": len(peaks)}


def motion_summary(corners: dict[str, list[tuple[int, ...]]]) -> dict[str, Any]:
    """How the response moves across Morph and Q — the trajectory shape, no coeffs."""
    dbs = {lab: corner_db(corners[LABEL_TO_KEY[lab]]) for lab in CORNER_ORDER}
    cents = {lab: round(centroid_hz(dbs[lab]), 1) for lab in CORNER_ORDER}
    bl = {lab: band_levels_db(corners[LABEL_TO_KEY[lab]]) for lab in CORNER_ORDER}

    morph_band = {b: round(bl["M100_Q0"][b] - bl["M0_Q0"][b], 2) for b in BAND_NAMES}
    q_band = {b: round(bl["M0_Q100"][b] - bl["M0_Q0"][b], 2) for b in BAND_NAMES}
    morph_shift = round(cents["M100_Q0"] - cents["M0_Q0"], 1)
    q_shift = round(cents["M0_Q100"] - cents["M0_Q0"], 1)

    def word(v, up, down, flat="holds"):
        return up if v > 50 else (down if v < -50 else flat)

    summary = (
        f"Morph {word(morph_shift, 'opens brighter', 'darkens')} "
        f"(centroid {morph_shift:+.0f} Hz); "
        f"Q {word(q_shift, 'pushes energy up', 'tightens low')} "
        f"(centroid {q_shift:+.0f} Hz)."
    )
    return {
        "corner_centroid_hz": cents,
        "morph_centroid_shift_hz": morph_shift,
        "q_centroid_shift_hz": q_shift,
        "morph_band_delta_db": morph_band,
        "q_band_delta_db": q_band,
        "summary": summary,
    }


def stability(corners: dict[str, list[tuple[int, ...]]], grid: int = 24) -> dict[str, Any]:
    """Pole-radius heat over the Morph x Q surface (shipped probe, not a recipe)."""
    g = np.linspace(0.0, 1.0, grid)
    mm, qq = np.meshgrid(g, g)
    s = ts.static_probe(corners, mm.ravel(), qq.ravel())
    max_r = float(s["max_pole_radius"])
    return {
        "max_pole_radius": round(max_r, 5),
        "unstable_rows": int(s["unstable_denominator_rows"]),
        "nonfinite_rows": int(s["nonfinite_coeff_rows"]),
        "stable": max_r < 1.0 and s["unstable_denominator_rows"] == 0,
        "near_edge_warning": 0.985 <= max_r < 1.0,  # heat, not a reject
        "probe_grid": f"{grid}x{grid}",
    }


def load_manifest() -> dict[str, dict[str, str]]:
    """sha256 + basename -> {id, name} from the P2K manifest, for provenance only."""
    by_sha: dict[str, dict[str, str]] = {}
    by_file: dict[str, dict[str, str]] = {}
    mpath = ROOT / "ref" / "presets" / "P2K_MANIFEST.json"
    if not mpath.exists():
        return {"by_sha": by_sha, "by_file": by_file}
    man = json.loads(mpath.read_text(encoding="utf-8"))
    for e in man.get("entries", []):
        tag = {"id": e.get("id", ""), "name": e.get("name", "")}
        if e.get("sha256"):
            by_sha[e["sha256"]] = tag
        if e.get("file"):
            by_file[Path(e["file"]).name] = tag
        for v in e.get("variants", []):
            if v.get("sha256"):
                by_sha[v["sha256"]] = tag
    return {"by_sha": by_sha, "by_file": by_file}


def describe_ref(path: Path, manifest: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Compute the full response descriptor for one reference .bin. No coeffs out."""
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    name, corners = ts.load_packed_body(path)

    prov = manifest["by_sha"].get(sha) or manifest["by_file"].get(path.name) or {}
    representative = corners[LABEL_TO_KEY["M0_Q0"]]
    cw = {LABEL_TO_KEY[lab]: corners[LABEL_TO_KEY[lab]] for lab in CORNER_ORDER}
    mid = packed_bilinear(cw, 0.5, 0.5)
    mid_db = cascade_response_db([EncodedCoeffs(*c) for c in mid], FREQS, AUTHORING_SR)
    mid_bl = hf.band_levels([EncodedCoeffs(*c) for c in mid], FREQS, AUTHORING_SR, 1.0)

    return {
        "file": str(path).replace("\\", "/"),
        "stem": name,
        "bytes": len(raw),
        "sha256": sha,
        "provenance": {
            "manifest_id": prov.get("id", "unknown"),
            "manifest_name": prov.get("name", "unknown"),
            "role": "INTERNAL REFERENCE / GUARDRAIL ONLY — not shipped, not copied",
        },
        "stability": stability(corners),
        "band_levels_db": {
            "M0_Q0": band_levels_db(representative),
            "middle_M50_Q50": {k: round(float(v), 2) for k, v in mid_bl.items()},
        },
        "landmarks": {
            "M0_Q0": landmarks(corner_db(representative)),
            "middle_M50_Q50": landmarks(mid_db),
        },
        "motion": motion_summary(corners),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refs", nargs="+", required=True, type=Path,
                    help="one or more reference .bin files (240 bytes each)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output dir (default: dev/tmp/chimera_refs/<timestamp>)")
    args = ap.parse_args(argv)

    ts_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = args.out or (ROOT / "dev" / "tmp" / "chimera_refs" / ts_stamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest()
    refs: list[dict[str, Any]] = []
    for p in args.refs:
        if not p.exists():
            print(f"SKIP (missing): {p}", file=sys.stderr)
            continue
        d = describe_ref(p, manifest)
        refs.append(d)
        st = d["stability"]
        print(f"  {d['provenance']['manifest_name']:<16} "
              f"low/body/bite/air = "
              f"{d['band_levels_db']['M0_Q0']['low']:+5.1f}/"
              f"{d['band_levels_db']['M0_Q0']['body']:+5.1f}/"
              f"{d['band_levels_db']['M0_Q0']['bite']:+5.1f}/"
              f"{d['band_levels_db']['M0_Q0']['air']:+5.1f}  "
              f"maxR={st['max_pole_radius']:.4f}{'  NEAR-EDGE' if st['near_edge_warning'] else ''}"
              f"{'  UNSTABLE' if not st['stable'] else ''}")

    payload = {
        "tool": "chimera_describe_refs",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "reuse_policy": REUSE_POLICY,
        "authoring_sample_rate_hz": AUTHORING_SR,
        "bands_hz": {name: [lo, hi] for name, lo, hi in BANDS},
        "reference_count": len(refs),
        "references": refs,
    }
    out_file = out_dir / "reference_descriptors.json"
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {out_file} ({len(refs)} reference descriptor(s))")
    print("NOTE: descriptors are response shape only - no coefficients emitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
