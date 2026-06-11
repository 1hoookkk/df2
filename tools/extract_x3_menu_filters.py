"""Extract exact Emulator X menu-filter reference artifacts through Morph Designer.

This keeps the actual X3 computed classes separate from the similarly named
P2K packed skins. Fixed classes are preserved as raw fixed-point ROM tables and
writer-faithful runtime corner snapshots. Generated Morph classes are preserved
as their exact supporting constant tables because they are not static body240
banks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.extract_emulatorx_rom_filters import DEFAULT_DLL, IMAGE_BASE, PeImage, sha256


SAMPLE_RATES = [44100, 48000, 96000, 192000]
CORNER_LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
STAGE_BYTES = 40

ROM_TABLES = {
    "lp": {"base": 0x1806D65E0, "source_stages": 1},
    "hp": {"base": 0x1806D6680, "source_stages": 1},
    "swept_eq_1": {"base": 0x1806D6720, "source_stages": 1},
    "swept_eq_2": {"base": 0x1806D67C0, "source_stages": 1},
    "swept_eq_3": {"base": 0x1806D6860, "source_stages": 1},
    "bandpass": {"base": 0x1806D6900, "source_stages": 1},
    "contrary_bandpass": {"base": 0x1806D69A0, "source_stages": 1},
    "phaser_1": {"base": 0x1806D6A40, "source_stages": 2},
    "phaser_2": {"base": 0x1806D6B80, "source_stages": 2},
    "bat_phaser": {"base": 0x1806D6CC0, "source_stages": 2},
    "flanger_lite": {"base": 0x1806D6E00, "source_stages": 3},
    "vocal_ah_ay_ee": {"base": 0x1806D6FE0, "source_stages": 3},
    "vocal_oo_ah": {"base": 0x1806D71C0, "source_stages": 3},
}

FIXED_CLASSES = [
    ("2 Pole Lowpass", "CPhantomLP2Pole", "FUN_1802c4b80", "0x1806d5e50", "lp", 1),
    ("4 Pole Lowpass", "CPhantomLP4Pole", "FUN_1802c4c40", "0x1806d5e78", "lp", 2),
    ("6 Pole Lowpass", "CPhantomLP6Pole", "FUN_1802c4d20", "0x1806d5ea0", "lp", 3),
    ("2 Pole Highpass", "CPhantomHP2Pole", "FUN_1802c4e00", "0x1806d5ec8", "hp", 1),
    ("4 Pole Highpass", "CPhantomHP4Pole", "FUN_1802c4ec0", "0x1806d5ef0", "hp", 2),
    ("2 Pole Bandpass", "CPhantomBP2Pole", "FUN_1802c51e0", "0x1806d5f78", "bandpass", 1),
    ("4 Pole Bandpass", "CPhantomBP4Pole", "FUN_1802c52a0", "0x1806d5f98", "bandpass", 2),
    (
        "Contrary Bandpass",
        "CPhantomContraryBandpass",
        "FUN_1802c5380",
        "0x1806d5fb8",
        "contrary_bandpass",
        1,
    ),
    ("Swept EQ 1 Octave", "CPhantomSweptEq1", "FUN_1802c4fa0", "0x1806d5f18", "swept_eq_1", 1),
    ("Swept EQ 2/1 Octave", "CPhantomSweptEq2", "FUN_1802c5060", "0x1806d5f38", "swept_eq_2", 1),
    ("Swept EQ 3/1 Octave", "CPhantomSweptEq3", "FUN_1802c5120", "0x1806d5f58", "swept_eq_3", 1),
    ("Phaser 1", "CPhantomPhaser1", "FUN_1802c5440", "0x1806d5fe0", "phaser_1", 2),
    ("Phaser 2", "CPhantomPhaser2", "FUN_1802c5530", "0x1806d6008", "phaser_2", 2),
    ("Bat Phaser", "CPhantomBatman", "FUN_1802c5620", "0x1806d6030", "bat_phaser", 2),
    ("Flanger Lite", "CPhantomFlanger1", "FUN_1802c5710", "0x1806d6058", "flanger_lite", 3),
    ("Vocal Ah-Ay-Ee", "CPhantomVocal1", "FUN_1802c57f0", "0x1806d6078", "vocal_ah_ay_ee", 3),
    ("Vocal Oo-Ah", "CPhantomVocal2", "FUN_1802c58d0", "0x1806d6098", "vocal_oo_ah", 3),
]

GENERATED_TABLES = {
    "morph_shared_base": (0x1806D73A0, 16),
    "morph_shared_scale": (0x1806D73B0, 16),
    "dual_eq_lp_profiles": (0x1806D73C0, 192),
    "dual_eq_expression_profiles": (0x1806D7480, 96),
    "peak_shelf_base": (0x1806D74E0, 16),
    "peak_shelf_scale": (0x1806D74F0, 16),
    "morph_designer_bypass": (0x1806D7500, 10),
    "morph_designer_base": (0x1806D7510, 16),
    "morph_designer_scale": (0x1806D7520, 16),
}

GENERATED_CLASSES = [
    {
        "name": "Dual EQ Morph",
        "kind": "generated_class",
        "class": "CPhantomMorph1",
        "writer": "FUN_1802c5d60",
        "helper": "FUN_1802c59b0",
        "vtable": "0x1806d60b8",
        "filter_id": "0x60",
        "support_tables": ["morph_shared_base", "morph_shared_scale"],
    },
    {
        "name": "Dual EQ + LP Morph",
        "kind": "generated_class",
        "class": "CPhantomMorphLP",
        "writer": "FUN_1802c5e40",
        "vtable": "0x1806d60d8",
        "filter_id": "0x61",
        "support_tables": ["dual_eq_lp_profiles"],
    },
    {
        "name": "Dual EQ Morph/Expression",
        "kind": "generated_class",
        "class": "CPhantomMorphLPX",
        "writer": "FUN_1802c5f10",
        "vtable": "0x1806d60f8",
        "filter_id": "0x62",
        "support_tables": ["dual_eq_expression_profiles"],
    },
    {
        "name": "Peak/Shelf Morph",
        "kind": "generated_class",
        "class": "CPhantomMorph2",
        "writer": "FUN_1802c6020",
        "vtable": "0x1806d6118",
        "filter_id": "0x68",
        "support_tables": ["peak_shelf_base", "peak_shelf_scale"],
    },
    {
        "name": "Morph Designer",
        "kind": "designer_compiler",
        "class": "CPhantomMorphDesigner",
        "writer": "FUN_1802c6590",
        "vtable": "0x1806d6138",
        "filter_id": "0x6c",
        "support_tables": [
            "morph_designer_bypass",
            "morph_designer_base",
            "morph_designer_scale",
        ],
        "grammar_notes": "ref/ghidra_extracts/morphdesigner_types.md",
    },
]

VERIFIED_FILTER_IDS = {
    "Bat Phaser": "0x42",
    "Flanger Lite": "0x48",
    "Vocal Ah-Ay-Ee": "0x50",
    "Vocal Oo-Ah": "0x51",
}


def slug(text: str) -> str:
    return (
        text.lower()
        .replace("+", " plus ")
        .replace("/", " ")
        .replace("-", " ")
        .replace(" ", "_")
        .replace("__", "_")
        .strip("_")
    )


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def write_raw(image: PeImage, out_dir: Path, name: str, base: int, size: int) -> dict[str, object]:
    raw = image.bytes_at(base, size)
    path = out_dir / f"{name}.raw"
    path.write_bytes(raw)
    return {
        "name": name,
        "base": hex(base),
        "bytes": len(raw),
        "sha256": sha256(raw),
        "file": relative(path),
    }


def compact_corner_snapshot(source_block: bytes, source_stages: int, output_stages: int) -> bytes:
    """Expand the fixed-class writer source as compact corner-major raw i16 rows."""

    if len(source_block) != source_stages * STAGE_BYTES:
        raise ValueError("source block does not match its stage count")
    stages = [
        source_block[stage * STAGE_BYTES : (stage + 1) * STAGE_BYTES]
        for stage in range(source_stages)
    ]
    if source_stages == 1 and output_stages > 1:
        stages *= output_stages
    if len(stages) != output_stages:
        raise ValueError("writer stage expansion is not represented")

    corners = [bytearray() for _ in CORNER_LABELS]
    for stage in stages:
        for corner in range(len(CORNER_LABELS)):
            corners[corner].extend(stage[corner * 10 : corner * 10 + 10])
    return b"".join(corners)


def build_manifest(image: PeImage, out_dir: Path) -> dict[str, object]:
    raw_dir = out_dir / "raw_tables"
    runtime_dir = out_dir / "runtime_blocks"
    raw_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    rom_tables = {}
    for name, spec in ROM_TABLES.items():
        stride = spec["source_stages"] * STAGE_BYTES
        entry = write_raw(image, raw_dir, name, spec["base"], stride * len(SAMPLE_RATES))
        entry["sample_rate_stride_bytes"] = stride
        entry["sample_rates"] = SAMPLE_RATES
        entry["source_stages"] = spec["source_stages"]
        rom_tables[name] = entry

    generated_tables = {}
    for name, (base, size) in GENERATED_TABLES.items():
        generated_tables[name] = write_raw(image, raw_dir, name, base, size)

    menu = [
        {
            "name": "No Filter",
            "kind": "bypass",
            "note": "Menu bypass selection; no coefficient writer.",
        }
    ]
    for name, class_name, writer, vtable, table_name, output_stages in FIXED_CLASSES:
        table = ROM_TABLES[table_name]
        table_raw = image.bytes_at(
            table["base"], table["source_stages"] * STAGE_BYTES * len(SAMPLE_RATES)
        )
        stride = table["source_stages"] * STAGE_BYTES
        snapshots = []
        for index, sample_rate in enumerate(SAMPLE_RATES):
            source_block = table_raw[index * stride : (index + 1) * stride]
            runtime = compact_corner_snapshot(source_block, table["source_stages"], output_stages)
            path = runtime_dir / f"{slug(name)}_{sample_rate}.raw"
            path.write_bytes(runtime)
            snapshots.append(
                {
                    "sample_rate": sample_rate,
                    "file": relative(path),
                    "bytes": len(runtime),
                    "sha256": sha256(runtime),
                }
            )
        entry = {
            "name": name,
            "kind": "rom_table_class",
            "class": class_name,
            "writer": writer,
            "vtable": vtable,
            "rom_table": table_name,
            "output_stages": output_stages,
            "runtime_snapshots": snapshots,
        }
        if name in VERIFIED_FILTER_IDS:
            entry["filter_id"] = VERIFIED_FILTER_IDS[name]
        menu.append(entry)

    menu.extend(GENERATED_CLASSES)
    return {
        "source_dll": str(image.path),
        "source_dll_sha256": sha256(image.data),
        "image_base": hex(image.image_base),
        "scope": "X3 menu filters from No Filter through Morph Designer",
        "corners": CORNER_LABELS,
        "sample_rates": SAMPLE_RATES,
        "fixed_point_decode_status": "intentionally unclassified; raw i16 words preserved exactly",
        "rom_tables": rom_tables,
        "generated_tables": generated_tables,
        "menu": menu,
    }


README = """# X3 menu filters through Morph Designer

This is an exact reference extraction from the installed `EmulatorX.dll`.
It keeps the actual X3 computed menu classes separate from the similarly named
P2K packed skins.

## What is here

- `X3_MENU_MANIFEST.json`: class roster in menu order.
- `raw_tables/*.raw`: verbatim fixed-class ROM tables and Morph support tables.
- `runtime_blocks/*.raw`: compact corner snapshots expanded from each
  fixed-class writer source for every sample-rate family.

The runtime blocks are raw fixed-point coefficient words. They are not P2K
minifloat `.body240` banks and must not be loaded through the P2K path.

The Morph classes are dynamic generators. Their writers and exact support
tables are recorded, but they are deliberately not flattened into fake static
banks. `Morph Designer` grammar notes remain in
`ref/ghidra_extracts/morphdesigner_types.md`.

## Corrected classification

The older `ref/batman` study grouped four adjacent writers as Bat Phaser
sample-rate loaders. RTTI and vtables prove that only `FUN_1802c5620` is
`CPhantomBatman`. The adjacent writers are separate classes:

- `FUN_1802c5710`: `CPhantomFlanger1`
- `FUN_1802c57f0`: `CPhantomVocal1`
- `FUN_1802c58d0`: `CPhantomVocal2`

Generate this directory with:

```text
python tools/extract_x3_menu_filters.py
```
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dll", type=Path, default=DEFAULT_DLL)
    parser.add_argument("--out", type=Path, default=ROOT / "ref" / "x3_menu")
    args = parser.parse_args()

    image = PeImage(args.dll)
    if image.image_base != IMAGE_BASE:
        raise ValueError(f"Unexpected image base {image.image_base:#x}; expected {IMAGE_BASE:#x}")

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(image, args.out)
    (args.out / "X3_MENU_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (args.out / "README.md").write_text(README, encoding="utf-8")

    fixed = sum(entry["kind"] == "rom_table_class" for entry in manifest["menu"])
    generated = sum(entry["kind"] in {"generated_class", "designer_compiler"} for entry in manifest["menu"])
    snapshots = sum(len(entry.get("runtime_snapshots", [])) for entry in manifest["menu"])
    print(f"wrote {len(manifest['menu'])} menu entries -> {args.out}")
    print(f"fixed ROM classes: {fixed}; generated classes/compiler: {generated}")
    print(f"raw tables: {len(manifest['rom_tables']) + len(manifest['generated_tables'])}")
    print(f"fixed runtime snapshots: {snapshots}")


if __name__ == "__main__":
    main()
