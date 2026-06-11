#!/usr/bin/env python3
"""Forge four-corner ARMA bodies from real source recordings.

Morph is low -> high. Secondary is open -> closed. Each corner is fitted from
its own recording through the bounded quarry fitter, aligned into persistent
lanes, packed, probed through trench-core, and rendered through the shipped
FilterEngine with AGC enabled.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import html
import json
import math
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi  # noqa: E402
from pyruntime.capture_compiler import align_actor_lanes  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words, words_to_coeffs  # noqa: E402
from tools.author_body import compiled_payload, raw_from_words, render_png  # noqa: E402
from tools.fit_two_audio_arma import fit_audio  # noqa: E402
from tools.teleport_stress import source_signal  # noqa: E402

RUNTIME_SR = 39_062.5
AUDITION_SR = 39_062
CORNER_TO_LETTER = {
    "M0_Q0": "A",
    "M100_Q0": "B",
    "M0_Q100": "C",
    "M100_Q100": "D",
}
RADIUS_TOLERANCE = (0.98999, 0.99801)
PACK = ROOT / "dev" / "tmp" / "arma_source_pack" / "corners_audio_only"
DEFAULT_OUT = ROOT / "dev" / "tmp" / "real_source_surface_rack"


@dataclass(frozen=True)
class Recipe:
    slug: str
    name: str
    description: str
    corners: dict[str, str]


RECIPES = (
    Recipe(
        "vowel_aperture",
        "Vowel Aperture",
        "Real phonetic vowels: open a/ae against closed u/i.",
        {
            "M0_Q0": "phonetic_4corner_legisign/corner_3_open_vowel/prime_a_Vow-24a.wav",
            "M100_Q0": "phonetic_4corner_legisign/corner_3_open_vowel/alt_ae_Vow-22a.wav",
            "M0_Q100": "phonetic_4corner_legisign/corner_2_dark_back_vowel/prime_u_Vow-05a.wav",
            "M100_Q100": "phonetic_4corner_legisign/corner_1_bright_front_vowel/prime_i_Vow-00a.wav",
        },
    ),
    Recipe(
        "vowel_fricative_gate",
        "Vowel Fricative Gate",
        "Real voice material: open a/e into closed m/sh spectral modes.",
        {
            "M0_Q0": "phonetic_4corner_legisign/corner_3_open_vowel/alt_aa_Vow-26a.wav",
            "M100_Q0": "phonetic_4corner_legisign/corner_1_bright_front_vowel/alt_e_Vow-09a.wav",
            "M0_Q100": "phonetic_4corner_legisign/corner_4_consonant_rich_spectral_mode/support_m_Con-13a.wav",
            "M100_Q100": "phonetic_4corner_legisign/corner_4_consonant_rich_spectral_mode/prime_sh_Con-33a.wav",
        },
    ),
    Recipe(
        "drum_cavity_shutter",
        "Drum Cavity Shutter",
        "Real drum recordings: open floor/high toms into closed kick/block strikes.",
        {
            "M0_Q0": "other_sources/kb6/extracted/EMU_Proteus3/FloorTom.wav",
            "M100_Q0": "other_sources/kb6/extracted/Ensoniq_Mirage/Tom Hi.wav",
            "M0_Q100": "other_sources/kb6/extracted/EMU_Proteus3/Kick2.wav",
            "M100_Q100": "other_sources/kb6/extracted/EMU_Proteus3/Block.wav",
        },
    ),
    Recipe(
        "bell_metal_clench",
        "Bell Metal Clench",
        "Real percussion recordings: conga/bell bloom into tighter cowbell/block metal.",
        {
            "M0_Q0": "other_sources/kb6/extracted/EMU_Proteus3/Conga.wav",
            "M100_Q0": "other_sources/kb6/extracted/EMU_Proteus3/Bell1.WAV",
            "M0_Q100": "other_sources/kb6/extracted/Ensoniq_Mirage/Cowbell.wav",
            "M100_Q100": "other_sources/kb6/extracted/EMU_Proteus3/Block.wav",
        },
    ),
    Recipe(
        "field_lab_aperture",
        "Field Lab Aperture",
        "Real field and lab recordings: solar/plasma wash into narrow NMR line spectra.",
        {
            "M0_Q0": "other_sources/soho/3modes.wav",
            "M100_Q0": "other_sources/plasma/chorus.wav",
            "M0_Q100": "other_sources/nmr/nmrtalk/ch2cl2/fid.wav",
            "M100_Q100": "other_sources/nmr/nmrtalk/cyclohexane/fid.wav",
        },
    ),
)


def _fit_source(relative_path: str, cache: dict[str, tuple[list[tuple[float, ...]], dict]]) -> tuple[list[tuple[float, ...]], dict]:
    if relative_path not in cache:
        path = PACK / relative_path
        if not path.exists():
            raise FileNotFoundError(path)
        rows, meta = fit_audio(path)
        cache[relative_path] = (rows, meta)
    return cache[relative_path]


def _packed_radius_audit(words: dict[str, list[tuple[int, ...]]]) -> dict:
    radii = []
    real_rows = 0
    for rows in words.values():
        for row in rows:
            _c0, _c1, c2, c3, _c4 = words_to_coeffs(row)
            roots = np.roots((1.0, c2 - 2.0, 1.0 - c3))
            if abs(float(np.imag(roots[0]))) > 1.0e-7:
                radii.append(float(abs(roots[0])))
            else:
                real_rows += 1
    outside = [radius for radius in radii if not RADIUS_TOLERANCE[0] <= radius <= RADIUS_TOLERANCE[1]]
    if outside:
        raise RuntimeError(f"decoded complex radii outside hot band: {outside}")
    return {
        "decoded_complex_pairs": len(radii),
        "decoded_real_support_rows": real_rows,
        "decoded_complex_radius_min": min(radii) if radii else None,
        "decoded_complex_radius_max": max(radii) if radii else None,
        "decoded_complex_outside_tolerant_band": len(outside),
    }


def _packed_grid_audit(body: bytes) -> dict:
    probes = [
        trench_ffi.packed_probe(body, morph / 16.0, secondary / 16.0)
        for secondary in range(17)
        for morph in range(17)
    ]
    report = {
        "grid": "17x17",
        "points": len(probes),
        "max_pole_radius": max(float(probe["max_pole_radius"]) for probe in probes),
        "unstable_rows": sum(int(probe["unstable_mask"]).bit_count() for probe in probes),
        "nonfinite_rows": sum(int(probe["nonfinite_mask"]).bit_count() for probe in probes),
        "dll": str(trench_ffi.lib_path()),
    }
    if report["unstable_rows"] or report["nonfinite_rows"]:
        raise RuntimeError(f"packed-grid stability gate failed: {report}")
    return report


def _write_wav(path: Path, samples: np.ndarray) -> None:
    values = np.asarray(samples, dtype=np.float64)
    peak = max(float(np.max(np.abs(values))), 1.0e-12)
    wavfile.write(str(path), AUDITION_SR, (values * (0.92 / peak)).astype(np.float32))


def _render_automated(body: bytes, morph: np.ndarray, secondary: np.ndarray, source: np.ndarray) -> np.ndarray:
    rendered = trench_ffi.engine_render_automated(
        body,
        morph,
        secondary,
        source.astype("<f4").tobytes(),
        sr=AUDITION_SR,
        agc_enabled=True,
        agc_drive=trench_ffi.MUSICAL_AGC_DRIVE,
    )
    return np.frombuffer(rendered, dtype="<f4").astype(np.float64)


def _write_auditions(out_dir: Path, body: bytes) -> list[str]:
    seconds = 3.5
    source = source_signal(int(round(seconds * AUDITION_SR)), AUDITION_SR)
    blocks = math.ceil(len(source) / 512)
    rising = np.linspace(0.0, 1.0, blocks)
    zero = np.zeros(blocks)
    one = np.ones(blocks)
    sweeps = {
        "morph_open_q0.wav": (rising, zero),
        "morph_closed_q100.wav": (rising, one),
        "secondary_low_m0.wav": (zero, rising),
        "secondary_high_m100.wav": (one, rising),
        "diagonal.wav": (rising, rising),
    }
    for filename, (morph, secondary) in sweeps.items():
        _write_wav(out_dir / filename, _render_automated(body, morph, secondary, source))
    return list(sweeps)


def _forge_recipe(recipe: Recipe, out_root: Path, cache: dict[str, tuple[list[tuple[float, ...]], dict]], audio: bool) -> dict:
    out_dir = out_root / recipe.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_rows = {}
    sources = {}
    for label, relative_path in recipe.corners.items():
        rows, meta = _fit_source(relative_path, cache)
        letter = CORNER_TO_LETTER[label]
        raw_rows[letter] = np.asarray(rows, dtype=np.float64)
        sources[label] = {
            "role": label,
            "relative_path": relative_path,
            **meta,
        }
    aligned, mapping = align_actor_lanes(raw_rows, RUNTIME_SR)
    letter_words = {
        letter: [tuple(int(value) for value in coeffs_to_words(*row)) for row in aligned[letter]]
        for letter in "ABCD"
    }
    cart_words = {
        label: letter_words[letter]
        for label, letter in CORNER_TO_LETTER.items()
    }
    body = trench_ffi.body_bytes_from_corner_words(letter_words)
    if body != raw_from_words(cart_words):
        raise RuntimeError("raw body serialization mismatch")
    radius_audit = _packed_radius_audit(cart_words)
    grid_audit = _packed_grid_audit(body)

    body_path = out_dir / f"{recipe.slug}.body240"
    cart_path = out_dir / f"{recipe.slug}.cart.json"
    plot_path = out_dir / f"{recipe.slug}.png"
    report_path = out_dir / "report.json"
    body_path.write_bytes(body)
    payload = compiled_payload(recipe.name, 1.0, cart_words)
    payload["provenance"] = "real-source-envelope -> bounded quarry ARMA -> hot complex radius band -> packed trench-core readback"
    payload["authoring"] = {
        "axes": {
            "morph": "low -> high",
            "secondary": "open -> closed",
        },
        "complexPoleRadiusBand": [0.990, 0.998],
        "realSupportRows": "preserved",
        "sources": recipe.corners,
    }
    cart_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    render_png(recipe.name, cart_words, plot_path)
    plt.close("all")
    audition_files = _write_auditions(out_dir, body) if audio else []
    report = {
        "format": "real-source-surface-rack-v1",
        "slug": recipe.slug,
        "name": recipe.name,
        "description": recipe.description,
        "axes": {
            "morph": "low -> high",
            "secondary": "open -> closed",
        },
        "sources": sources,
        "lane_mapping": mapping,
        "radius_audit": radius_audit,
        "packed_probe": grid_audit,
        "outputs": {
            "body240": str(body_path),
            "cart_json": str(cart_path),
            "plot": str(plot_path),
            "auditions": audition_files,
        },
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _write_index(out_root: Path, reports: list[dict]) -> Path:
    cards = []
    for report in reports:
        folder = html.escape(report["slug"])
        source_rows = "".join(
            f"<li><code>{html.escape(label)}</code>: {html.escape(Path(source['relative_path']).name)}</li>"
            for label, source in report["sources"].items()
        )
        audio_rows = "".join(
            f"<label>{html.escape(Path(filename).stem.replace('_', ' '))}"
            f"<audio controls preload='none' src='{folder}/{html.escape(filename)}'></audio></label>"
            for filename in report["outputs"]["auditions"]
        )
        probe = report["packed_probe"]
        cards.append(
            f"<article><h2>{html.escape(report['name'])}</h2>"
            f"<p>{html.escape(report['description'])}</p>"
            f"<p class='meta'>17x17 stable | maxR {probe['max_pole_radius']:.6f}</p>"
            f"<img src='{folder}/{folder}.png' alt='{html.escape(report['name'])} plot'>"
            f"<ul>{source_rows}</ul>{audio_rows}</article>"
        )
    page = """<!doctype html><meta charset="utf-8">
<title>Real Source Surface Rack</title>
<style>
body{font:15px system-ui;background:#090d0f;color:#d7e1e8;margin:24px}
h1{margin-bottom:4px}p{max-width:980px}.meta{color:#81d982}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:18px}
article{background:#10171b;border:1px solid #26353d;border-radius:8px;padding:14px}
img{width:100%;background:#070a09}audio{display:block;width:100%;margin:3px 0 10px}
code{color:#f6c453}li{margin:3px 0}
</style>
<h1>Real Source Surface Rack</h1>
<p>Morph: low -&gt; high. Secondary: open -&gt; closed. All sweeps render through
the shipped trench-core FilterEngine with AGC enabled. These are audition
candidates, not shipped presets.</p><main>""" + "".join(cards) + "</main>"
    path = out_root / "audition.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()
    if not trench_ffi.available() or not trench_ffi.engine_available():
        raise SystemExit("current trench-core release DLL with engine FFI is required")
    out_root = args.out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    cache: dict[str, tuple[list[tuple[float, ...]], dict]] = {}
    reports = []
    for recipe in RECIPES:
        print(f"forge {recipe.slug:<22} {recipe.description}")
        report = _forge_recipe(recipe, out_root, cache, audio=not args.no_audio)
        reports.append(report)
        probe = report["packed_probe"]
        radius = report["radius_audit"]
        print(
            f"  stable {probe['grid']} maxR={probe['max_pole_radius']:.9f} "
            f"cx={radius['decoded_complex_pairs']} real={radius['decoded_real_support_rows']}"
        )
    index = _write_index(out_root, reports)
    (out_root / "rack.json").write_text(json.dumps({"reports": reports}, indent=2) + "\n", encoding="utf-8")
    print(f"rack -> {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
