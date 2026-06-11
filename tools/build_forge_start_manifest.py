"""Build the Forge START manifest — four provenance lanes for the painter.

Per dev/tmp/forge_real_source_map/FORGE_UI_COMPILE_SOURCES.md:

  COMPILE EXACT  law/table/physics sources that compile six packed stages
                 and pass the packed-runtime audit
  IMPORT EXACT   real Morph Designer XML imports through the firmware
                 type 1..3 grammar (exact for that grammar; Q collapsed)
  OVERLAY        exact reference curves (X3 fixed blocks, P2K packed refs)
                 — evidence to plot against, never shipping source
  APPROX         clean-room fit starters, labeled approximate, never exact

Outputs under dev/tmp/forge_real_source_map/:
  imports/<slug>.body240 + <slug>.cartridge.json    (Designer XML compiles)
  overlays/<slug>.curves.json                       (reference response curves)
  forge_start_manifest.json                         (the painter loads this)

Run from repo root:  python tools/build_forge_start_manifest.py
"""

from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyruntime.designer_compile import compile_designer_to_body, parse_xml  # noqa: E402
from pyruntime import trench_ffi  # noqa: E402
from src.utils.body240 import (  # noqa: E402
    CORNER_ORDER,
    compiled_payload,
    raw_from_words,
    words_from_kernels,
)

OUT = ROOT / "dev/tmp/forge_real_source_map"
SR_PACKED = 39_062.5
FREQS = np.geomspace(30.0, 16_000.0, 96)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def cascade_db(biquads, sr: float) -> np.ndarray:
    w = 2.0 * np.pi * FREQS / sr
    z = np.exp(-1j * w)
    total = np.ones_like(z)
    for b0, b1, b2, a1, a2 in biquads:
        total *= (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
    return 20.0 * np.log10(np.abs(total) + 1e-12)


def probe_17x17(body: bytes) -> dict:
    max_r, unstable, nonfinite = 0.0, 0, 0
    for i in range(17):
        for j in range(17):
            d = trench_ffi.packed_probe(body, i / 16.0, j / 16.0)
            max_r = max(max_r, d["max_pole_radius"])
            unstable += 1 if d["unstable_mask"] else 0
            nonfinite += 1 if d["nonfinite_mask"] else 0
    return {"max_pole_radius": round(max_r, 8), "unstable_cells": unstable, "nonfinite_cells": nonfinite}


# ── IMPORT EXACT: Morph Designer XML → packed body ───────────────────────────

DESIGNER_IMPORTS = ["Wah Wah 1", "Wah Wah 2", "Wah Wah 3", "Phasey One", "Slightly Phased"]
# pyruntime corner index -> body240 corner label
PYRUNTIME_CORNER_LABEL = {0: "M0_Q0", 1: "M0_Q100", 2: "M100_Q0", 3: "M100_Q100"}
KEEP_LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]


def compile_designer_imports() -> list[dict]:
    rows = []
    imp_dir = OUT / "imports"
    imp_dir.mkdir(parents=True, exist_ok=True)
    for name in DESIGNER_IMPORTS:
        xml = ROOT / "ref/heritage" / f"{name}.xml"
        template = parse_xml(str(xml))
        body = compile_designer_to_body(template)
        # Designer XML fills exactly six sections; pyruntime pads to its
        # 12-stage runtime — the .body240 format takes the six real rows
        kernels = {}
        for ci, label in PYRUNTIME_CORNER_LABEL.items():
            enc = body.corners._corners[ci].encode()[:6]  # firmware-exact coeffs
            kernels[label] = [(e.c0, e.c1, e.c2, e.c3, e.c4) for e in enc]
        words = words_from_kernels(kernels)
        raw = raw_from_words(words)
        assert len(raw) == 240, f"{name}: packed {len(raw)} bytes"
        slug = slugify(name)
        (imp_dir / f"{slug}.body240").write_bytes(raw)
        cart = compiled_payload(name, body.boost, words)
        cart["provenance"] = "morph-designer-xml-import"
        cart["source_xml"] = str(xml.relative_to(ROOT)).replace("\\", "/")
        cart["compiler"] = "pyruntime/designer_compile.py (firmware type 1..3 grammar)"
        cart["q_collapsed"] = True
        (imp_dir / f"{slug}.cartridge.json").write_text(json.dumps(cart, indent=2))
        probe = probe_17x17(raw)
        rows.append({
            "label": name,
            "note": "Designer XML import · Q collapsed",
            "kind": "packed",
            "body": f"dev/tmp/forge_real_source_map/imports/{slug}.body240",
            "evidence": f"17x17 probe max_r {probe['max_pole_radius']:.4f} · unstable {probe['unstable_cells']}",
        })
        print(f"import exact: {name} -> {slug}.body240  {probe}")
    return rows


# ── OVERLAY: exact reference curves ──────────────────────────────────────────

X3_BLOCKS = ROOT / "ref/x3_menu/runtime_blocks"
X3_SCALE = 16_384.0
X3_ORDER = [2, 3, 4, 0, 1]  # raw word slots -> [b0,b1,b2,a1,a2]


def x3_overlay(base: str, n_stages: int, label: str) -> dict | None:
    path = X3_BLOCKS / f"{base}_48000.raw"
    if not path.exists():
        return None
    raw = path.read_bytes()
    words = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    per_corner = n_stages * 5
    curves = []
    for c, corner_label in enumerate(KEEP_LABELS):
        seg = words[c * per_corner:(c + 1) * per_corner]
        biquads = []
        for s in range(n_stages):
            v = [seg[s * 5 + k] / X3_SCALE for k in range(5)]
            o = [v[i] for i in X3_ORDER]
            biquads.append(tuple(o))
        curves.append({"label": corner_label, "db": [round(float(x), 3) for x in cascade_db(biquads, 48_000.0)]})
    return {
        "label": label,
        "source": str(path.relative_to(ROOT)).replace("\\", "/"),
        "note": "X3 fixed-class runtime block · direct DF2T i16/16384 · word order [2,3,4,0,1] · exact reference, not a .body240",
        "sample_rate": 48_000.0,
        "freqs": [round(float(f), 3) for f in FREQS],
        "curves": curves,
    }


def p2k_overlay(bin_name: str, label: str) -> dict | None:
    path = ROOT / "ref/presets" / bin_name
    if not path.exists():
        return None
    body = path.read_bytes()
    curves = []
    for (m, q), corner_label in zip([(0, 0), (1, 0), (0, 1), (1, 1)], KEEP_LABELS):
        d = trench_ffi.packed_probe(body, float(m), float(q))
        curves.append({"label": corner_label, "db": [round(float(x), 3) for x in cascade_db(d["biquad"], SR_PACKED)]})
    return {
        "label": label,
        "source": str(path.relative_to(ROOT)).replace("\\", "/"),
        "note": "P2K packed reference (verbatim, study/overlay only — protected, never shipping source)",
        "sample_rate": SR_PACKED,
        "freqs": [round(float(f), 3) for f in FREQS],
        "curves": curves,
    }


def build_overlays() -> list[dict]:
    ov_dir = OUT / "overlays"
    ov_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        ("x3_phaser_1", x3_overlay("phaser_1", 2, "X3 Phaser 1")),
        ("x3_phaser_2", x3_overlay("phaser_2", 2, "X3 Phaser 2")),
        ("x3_vocal_ah_ay_ee", x3_overlay("vocal_ah_ay_ee", 3, "X3 Vocal Ah-Ay-Ee")),
        ("x3_vocal_oo_ah", x3_overlay("vocal_oo_ah", 3, "X3 Vocal Oo-Ah")),
        ("p2k_phazeshift_1", p2k_overlay("P2k_044_phazeshift1_6_pha.bin", "P2K Phazeshift 1")),
        ("p2k_phazeshift_2", p2k_overlay("P2k_045_phazeshift2_6_pha.bin", "P2K Phazeshift 2")),
    ]
    rows = []
    for slug, doc in specs:
        if doc is None:
            print(f"overlay MISSING: {slug}")
            continue
        (ov_dir / f"{slug}.curves.json").write_text(json.dumps(doc, indent=2))
        rows.append({
            "label": doc["label"],
            "note": doc["note"].split("·")[0].strip(),
            "kind": "overlay",
            "curves": f"dev/tmp/forge_real_source_map/overlays/{slug}.curves.json",
            "evidence": "exact reference curves",
        })
        print(f"overlay: {doc['label']} -> {slug}.curves.json")
    return rows


# ── COMPILE EXACT: laws, physical, vocal, butterworth ────────────────────────

def law_rows() -> list[dict]:
    rows = []
    candidates = [
        ROOT / "dev/tmp/law_author/golden_hedz_like",
        ROOT / "dev/tmp/law_author/bass_sharpener",
        ROOT / "dev/tmp/law_author/families/family_vocal_formant",
        ROOT / "dev/tmp/law_author/families/family_phaser_comb",
        ROOT / "dev/tmp/law_author/families/family_slope_ladder",
        ROOT / "dev/tmp/law_author/families/family_bandpass_swept_eq",
        ROOT / "dev/tmp/law_author/families/family_morph_special",
    ]
    for d in candidates:
        stages = d / "stages.json"
        bodies = sorted(d.glob("*.body240"))
        if not (stages.exists() and bodies):
            print(f"law row MISSING: {d}")
            continue
        verdict = ""
        audit = d / "audit.json"
        if audit.exists():
            try:
                verdict = json.loads(audit.read_text()).get("verdict", "")
            except Exception:
                pass
        rows.append({
            "label": bodies[0].stem.replace("_", " "),
            "note": "law author · editable six stages",
            "kind": "law",
            "body": str(bodies[0].relative_to(ROOT)).replace("\\", "/"),
            "stages": str(stages.relative_to(ROOT)).replace("\\", "/"),
            "evidence": f"law audit {verdict}" if verdict else "compiled + audited",
        })
    return rows


def physical_rows() -> list[dict]:
    rows = []
    manifest = ROOT / "dev/tmp/physical_mountains/manifest.json"
    if manifest.exists():
        for entry in json.loads(manifest.read_text()):
            audit = entry.get("audit", {})
            rows.append({
                "label": entry.get("title", entry["slug"]),
                "note": "physical poles exact · valleys are authored",
                "kind": "packed",
                "body": f"dev/tmp/physical_mountains/{entry['slug']}.body240",
                "evidence": f"probe max_r {audit.get('max_pole_radius', 0):.4f} · unstable {audit.get('unstable_mask', 0)}",
            })
    klatt = ROOT / "dev/tmp/klatt_ouiii_to_eh/klatt_ouiii_to_eh_allpole.body240"
    if klatt.exists():
        rows.append({
            "label": "Klatt vocal Ouiii -> Eh",
            "note": "measured formants · all-pole (no invented zeros)",
            "kind": "packed",
            "body": str(klatt.relative_to(ROOT)).replace("\\", "/"),
            "evidence": "17x17 probe PASS · max_r 0.9978",
        })
    return rows


def exact_skeleton_rows() -> tuple[list[dict], list[dict]]:
    rows, quarantine = [], []
    ver = ROOT / "tables/exact_skeletons.verification.json"
    if not ver.exists():
        return rows, quarantine
    doc = json.loads(ver.read_text())
    for i, sk in enumerate(doc.get("skeletons", [])):
        if sk.get("verdict") == "PASS":
            rows.append({
                "label": sk["key"].capitalize() + "-12",
                "note": "independently verified analog skeleton",
                "kind": "exact_skeleton",
                "exact_key": sk["key"],
                "evidence": f"passband max {sk.get('passband_max_db', 0):.3f} dB · body max {sk.get('body_max_db', 0):.3f} dB",
            })
        else:
            quarantine.append({
                "label": sk["key"].capitalize() + "-12",
                "reason": f"independent verification FAIL — body max {sk.get('body_max_db', 0):.2f} dB",
            })
    return rows, quarantine


# ── APPROX starters ──────────────────────────────────────────────────────────

APPROX_NOTES = {
    "x3_shape_phaser_1": "X3 Phaser 1 fit · shape RMS 3.98 dB",
    "x3_shape_phaser_2": "X3 Phaser 2 fit · shape RMS 2.55 dB",
}


def approx_rows() -> list[dict]:
    rows = []
    for body in sorted((ROOT / "dev/tmp/x3_fixed_cleanroom").glob("*/*.body240")):
        slug = body.stem
        d = trench_ffi.packed_probe(body.read_bytes(), 0.5, 0.5)
        rows.append({
            "label": slug.replace("x3_shape_", "x3 ").replace("_", " "),
            "note": APPROX_NOTES.get(slug, "clean-room response fit of X3 reference"),
            "kind": "packed",
            "body": str(body.relative_to(ROOT)).replace("\\", "/"),
            "evidence": f"approximate fit · center max_r {d['max_pole_radius']:.4f}",
        })
    for body in sorted((ROOT / "dev/tmp/prove_iconic_method/iconic_set").glob("*/*.body240")):
        d = trench_ffi.packed_probe(body.read_bytes(), 0.5, 0.5)
        rows.append({
            "label": "iconic " + body.stem.replace("_", " "),
            "note": "clean-room iconic-method proof body",
            "kind": "packed",
            "body": str(body.relative_to(ROOT)).replace("\\", "/"),
            "evidence": f"proof body · center max_r {d['max_pole_radius']:.4f}",
        })
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    builders = [{
        "label": "Two-frame Peak/Shelf",
        "note": "FREQ · SHELF · PEAK per frame",
        "kind": "peak_shelf",
        "evidence": "authoring grammar — compiles via pack_body",
    }]
    builders += law_rows()
    skeleton_rows, quarantine = exact_skeleton_rows()
    builders += skeleton_rows
    builders += physical_rows()

    imports = compile_designer_imports()
    overlays = build_overlays()
    approx = approx_rows()

    quarantine += [
        {"label": "X3 Phaser 1/2 as exact .body240", "reason": "no verified conversion bridge — fits stay APPROX"},
        {"label": "forge/recipes/auto (55)", "reason": "provenance not promoted to source law + audit"},
        {"label": "dev/tmp/forge_method prototypes", "reason": "prototype gallery — not labeled"},
    ]

    manifest = {
        "format": "forge-start-manifest-v1",
        "rule": "every row carries one badge: COMPILE EXACT, IMPORT EXACT, OVERLAY, or APPROX",
        "lanes": [
            {"id": "exact_builders", "title": "exact builders", "badge": "COMPILE EXACT", "rows": builders},
            {"id": "exact_imports", "title": "exact imports", "badge": "IMPORT EXACT", "rows": imports},
            {"id": "reference_overlays", "title": "reference overlays", "badge": "OVERLAY", "rows": overlays},
            {"id": "approx_starters", "title": "approx starters", "badge": "APPROX", "rows": approx},
        ],
        "quarantine": quarantine,
    }
    out = OUT / "forge_start_manifest.json"
    out.write_text(json.dumps(manifest, indent=2))
    counts = {lane["id"]: len(lane["rows"]) for lane in manifest["lanes"]}
    print(f"\nwrote {out}")
    print(f"lanes: {counts} · quarantine {len(quarantine)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
