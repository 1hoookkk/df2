#!/usr/bin/env python3
"""Render the v1 filter-FX lineup through the shipped engine.

Each canonical presets/v1_*.body240 body is hash-checked against the v1 export
manifest, then rendered as:
  - frozen 808 snapshots at HOME, MORPH, TENSION, MORPH+TENSION, MIDDLE
  - moving pink-noise morph sweep at Q=100

The output page is for ear-culling the final $49 v1 product set.
"""
from __future__ import annotations

import hashlib
import html
import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from tools.audition_one import pink_noise, render_raw_body, render_sweep  # noqa: E402
from tools.render_audition import synth_808, write_wav  # noqa: E402

MANIFEST = ROOT / "dev" / "tmp" / "forge_v1_lineup" / "factory_export" / "manifest.json"
OUT = ROOT / "dev" / "tmp" / "forge_v1_lineup" / "audition"


def wav_peak(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    if not frames:
        return 0.0
    samples = np.frombuffer(frames, dtype="<i2")
    return float(np.max(np.abs(samples)) / 32767.0) if samples.size else 0.0


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> int:
    if not trench_ffi.engine_available():
        raise RuntimeError("shipped trench engine is unavailable; refusing AGC-less audition render")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])
    if len(entries) != 6:
        raise RuntimeError(f"expected 6 v1 entries, got {len(entries)}")

    OUT.mkdir(parents=True, exist_ok=True)
    source_808 = synth_808()
    source_pink = pink_noise(5.0)
    rendered = []

    for entry in entries:
        body_path = ROOT / entry["preset_body"]
        body = body_path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if len(body) != 240:
            raise RuntimeError(f"{entry['slug']}: expected 240 bytes, got {len(body)}")
        if digest != entry["body240_sha256"]:
            raise RuntimeError(f"{entry['slug']}: body hash mismatch")
        if entry.get("failures"):
            raise RuntimeError(f"{entry['slug']}: manifest has failures {entry['failures']}")
        if entry["score"]["verdict"] != "PASS":
            raise RuntimeError(f"{entry['slug']}: manifest verdict is not PASS")

        snap_path = OUT / f"{entry['slug']}_808_snapshots.wav"
        sweep_path = OUT / f"{entry['slug']}_pink_morph_q100.wav"
        write_wav(snap_path, render_raw_body(body, source_808))
        write_wav(sweep_path, render_sweep(body, source_pink, q=1.0))

        rendered.append({
            "name": entry["name"],
            "slug": entry["slug"],
            "fit_source": entry.get("fit_source"),
            "body240": entry["preset_body"],
            "body240_sha256": digest,
            "snapshots_wav": rel(snap_path),
            "sweep_wav": rel(sweep_path),
            "snapshots_peak": wav_peak(snap_path),
            "sweep_peak": wav_peak(sweep_path),
            "score": entry["score"]["metrics"],
        })
        print(f"rendered {entry['slug']} -> {rel(snap_path)}, {rel(sweep_path)}")

    report = {
        "format": "trench-v1-filter-fx-audition",
        "engine": "trench_ffi shipped engine path (AGC+saturate)",
        "source_manifest": rel(MANIFEST),
        "entries": rendered,
    }
    (OUT / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    rows = []
    for item in rendered:
        score = item["score"]
        rows.append(
            "<section class='row'>"
            f"<h2>{html.escape(item['name'])}</h2>"
            f"<p class='meta'>{html.escape(item['slug'])} | source {html.escape(str(item['fit_source']))} | "
            f"M {score['morph_contrast_rms_db']:.1f} dB | Q {score['secondary_contrast_rms_db']:.1f} dB | "
            f"peaks/valleys {score['center_response_peaks']}/{score['center_response_valleys']} | "
            f"zero {score['median_zero_motion_octaves']:.2f} oct</p>"
            f"<p><b>808 snapshots</b><br><audio controls src='{Path(item['snapshots_wav']).name}'></audio></p>"
            f"<p><b>Pink morph sweep Q=100</b><br><audio controls src='{Path(item['sweep_wav']).name}'></audio></p>"
            f"<p class='hash'>{item['body240_sha256']}</p>"
            "</section>"
        )

    doc = "\n".join([
        "<!doctype html><meta charset=utf-8><title>TRENCH v1 filter FX audition</title>",
        "<style>",
        "body{background:#080b0c;color:#d8e0df;font:14px ui-monospace,Consolas,monospace;padding:24px;max-width:980px;margin:auto}",
        "h1{font-size:22px;color:#f2c28a}h2{font-size:17px;margin:0 0 4px;color:#ffd23e}",
        ".row{border:1px solid #1d2a2d;border-radius:7px;padding:14px;margin:12px 0;background:#0d1113}",
        ".meta,.hash{color:#7f8f91;font-size:12px}.hash{word-break:break-all}audio{width:100%;max-width:720px}",
        "</style>",
        "<h1>TRENCH v1 filter FX audition</h1>",
        "<p class='meta'>Rendered through the shipped engine path with AGC+saturate. "
        "Each body is the canonical 240-byte preset and hash-matched against the v1 manifest.</p>",
        *rows,
    ])
    (OUT / "audition.html").write_text(doc, encoding="utf-8")
    print(f"manifest -> {rel(OUT / 'manifest.json')}")
    print(f"open -> {rel(OUT / 'audition.html')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
