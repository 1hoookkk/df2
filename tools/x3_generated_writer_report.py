#!/usr/bin/env python3
"""Report the X3 generated/morph writer path without dumping vendor table values.

This is a study-only clean-room artifact. It inventories the generated writer
classes, their support-table shapes, and the observed formulas/structure from
the decompile. It deliberately avoids printing raw support words, coefficients,
or shippable reference bodies.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "ref" / "x3_menu" / "X3_MENU_MANIFEST.json"
OUT = ROOT / "dev" / "tmp" / "x3_generated_writers"


WRITER_OBSERVATIONS: dict[str, dict[str, Any]] = {
    "Dual EQ Morph": {
        "status": "decoded_writer",
        "formula_site": "FUN_1802c5d60 -> FUN_1802c59b0",
        "observed": [
            "Clears dirty flag at runtime+0x204 and calls the object refresh callback when set.",
            "Builds one six-word profile on the stack using sentinel/pass-through words.",
            "Computes spread = -32 - trunc((float[runtime+0x1e8] + float[runtime+0x200]) * DAT_1806f1048).",
            "Calls the shared three-stage generated writer with that fixed profile.",
        ],
        "inferred": [
            "This is a fallback/shared Dual EQ morph grammar, not a ROM table class and not a P2K body.",
        ],
    },
    "Dual EQ + LP Morph": {
        "status": "decoded_writer",
        "formula_site": "FUN_1802c5e40 -> FUN_1802c59b0",
        "observed": [
            "Computes profile_index = clamp(trunc((float[runtime+0x1e8] + float[runtime+0x200]) * DAT_18065a1ec), 0, 15).",
            "Passes support profile at DAT_1806d73c0 + profile_index * 12 to the shared three-stage writer.",
            "The support profile is six u16 words per profile.",
        ],
        "inferred": [
            "The profile table is a morph-position cartridge for the pole-side words consumed by the shared writer.",
        ],
    },
    "Dual EQ Morph/Expression": {
        "status": "decoded_writer",
        "formula_site": "FUN_1802c5f10 -> FUN_1802c59b0",
        "observed": [
            "Computes the same clamped 0..15 profile index as Dual EQ + LP Morph.",
            "Loads three u16 words from DAT_1806d7480 + profile_index * 6.",
            "Mirrors those three words into a six-word profile before calling the shared three-stage writer.",
        ],
        "inferred": [
            "Expression uses a smaller profile table whose triplet is duplicated for the two generated endpoints.",
        ],
    },
    "Peak/Shelf Morph": {
        "status": "decoded_writer",
        "formula_site": "FUN_1802c6020",
        "observed": [
            "Does not call the shared three-stage writer.",
            "Uses the per-rate tables at DAT_1806d74e0 and DAT_1806d74f0.",
            "Reads the same designer-byte area used by the morph writers: param2+0x16..0x1b.",
            "Computes two endpoint frequency centers, signed spreads, clamps/folds boundaries, and writes three stages into all four corner banks.",
            "Forces runtime stage count to 3.",
        ],
        "inferred": [
            "This is a separate peak/shelf authoring grammar; do not merge it into Morph Designer Type 1..3.",
        ],
    },
    "Morph Designer": {
        "status": "decoded_writer",
        "formula_site": "FUN_1802c6590",
        "observed": [
            "Reads six 6-byte descriptors starting at param2+0x20.",
            "Only type IDs 1..3 compile; other descriptors are skipped.",
            "Uses per-rate tables at DAT_1806d7510 and DAT_1806d7520.",
            "Writes endpoint A to M0_Q0 and M0_Q100; writes endpoint B to M100_Q0 and M100_Q100.",
            "The Q axis is therefore duplicated by this writer.",
            "If four or more rows compile, runtime row count is forced to six and missing rows are padded from DAT_1806d7500.",
        ],
        "inferred": [
            "Morph Designer is an authoring compiler, not a static body bank.",
        ],
    },
}


SHARED_HELPER = {
    "name": "FUN_1802c59b0",
    "status": "decoded_writer_helper",
    "observed": [
        "Uses sample-rate family index at param1+0x0c.",
        "Uses per-rate base table DAT_1806d73a0 and per-rate scale table DAT_1806d73b0.",
        "Reads six designer bytes at param2+0x16..0x1b.",
        "Builds three generated stages and writes each endpoint into both Q banks.",
        "Writes stage count 3 at runtime+0x420.",
        "Kernel slots 0/1 are numerator/zero side; slots 2/3 are denominator/pole side; slot 4 is gain.",
    ],
    "inferred": [
        "The support profile supplied by callers participates in the pole/denominator path of the generated stage layout.",
    ],
}


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def read_words(path: Path) -> list[int]:
    raw = path.read_bytes()
    if len(raw) % 2:
        return []
    return list(struct.unpack("<" + "H" * (len(raw) // 2), raw))


def table_shape(table: dict[str, Any]) -> dict[str, Any]:
    path = ROOT / table["file"]
    raw = path.read_bytes()
    words = read_words(path)
    unique_words = len(set(words)) if words else None
    shape: dict[str, Any] = {
        "name": table["name"],
        "base": table["base"],
        "file": table["file"],
        "bytes": len(raw),
        "word_count": len(words) if words else None,
        "sha256": table["sha256"],
        "value_policy": "raw values intentionally not emitted",
        "unique_word_count": unique_words,
    }
    if table["name"] in {"dual_eq_lp_profiles"}:
        shape.update({"interpreted_shape": "16 profiles x 6 u16 words", "profile_count": 16, "words_per_profile": 6})
    elif table["name"] in {"dual_eq_expression_profiles"}:
        shape.update({"interpreted_shape": "16 profiles x 3 u16 words", "profile_count": 16, "words_per_profile": 3})
    elif table["name"] in {
        "morph_shared_base",
        "morph_shared_scale",
        "peak_shelf_base",
        "peak_shelf_scale",
        "morph_designer_base",
        "morph_designer_scale",
    }:
        shape.update({"interpreted_shape": "4 sample-rate-family words", "sample_rate_families": [44100, 48000, 96000, 192000]})
    elif table["name"] == "morph_designer_bypass":
        shape.update({"interpreted_shape": "1 padding/bypass row x 5 u16 words"})
    return shape


def menu_generated(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        entry for entry in manifest["menu"]
        if entry.get("kind") in {"generated_class", "designer_compiler"}
    ]


def report() -> dict[str, Any]:
    manifest = load_manifest()
    generated_tables = manifest["generated_tables"]
    classes = []
    for entry in menu_generated(manifest):
        observations = WRITER_OBSERVATIONS[entry["name"]]
        classes.append({
            "menu_name": entry["name"],
            "kind": entry["kind"],
            "class": entry["class"],
            "writer": entry["writer"],
            "helper": entry.get("helper"),
            "vtable": entry["vtable"],
            "filter_id": entry.get("filter_id"),
            "support_tables": [
                table_shape(generated_tables[name])
                for name in entry.get("support_tables", [])
            ],
            **observations,
        })
    return {
        "format": "x3-generated-writer-report-v1",
        "scope": "X3 generated/morph menu classes only; study artifact; no vendor table values emitted",
        "source_manifest": str(MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        "shared_helper": SHARED_HELPER,
        "classes": classes,
        "clean_room_boundary": [
            "OBSERVED formulas and structure are retained.",
            "Raw support bytes, coefficient words, table values, and shippable reference bodies are not emitted.",
            "Generated support tables remain study evidence, not product assets.",
        ],
    }


def write_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# X3 Generated Writer Report",
        "",
        "Study-only clean-room report. It records writer structure and support-table shapes without dumping vendor table values.",
        "",
        "## Shared Helper",
        "",
        f"- Function: `{data['shared_helper']['name']}`",
        f"- Status: `{data['shared_helper']['status']}`",
        "",
        "OBSERVED:",
    ]
    lines.extend(f"- {item}" for item in data["shared_helper"]["observed"])
    lines.extend(["", "INFERRED:"])
    lines.extend(f"- {item}" for item in data["shared_helper"]["inferred"])
    for cls in data["classes"]:
        lines.extend([
            "",
            f"## {cls['menu_name']}",
            "",
            f"- Kind: `{cls['kind']}`",
            f"- Class: `{cls['class']}`",
            f"- Writer: `{cls['writer']}`",
            f"- Helper: `{cls['helper'] or '-'}`",
            f"- Status: `{cls['status']}`",
            "",
            "Support tables:",
        ])
        for table in cls["support_tables"]:
            lines.append(
                f"- `{table['name']}` at `{table['base']}`: {table['bytes']} bytes, "
                f"{table.get('interpreted_shape', 'unclassified shape')}; values not emitted"
            )
        lines.extend(["", "OBSERVED:"])
        lines.extend(f"- {item}" for item in cls["observed"])
        lines.extend(["", "INFERRED:"])
        lines.extend(f"- {item}" for item in cls["inferred"])
    lines.extend([
        "",
        "## Boundary",
        "",
    ])
    lines.extend(f"- {item}" for item in data["clean_room_boundary"])
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = report()
    (OUT / "report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (OUT / "README.md").write_text(write_markdown(data), encoding="utf-8")
    print(f"wrote {OUT / 'report.json'}")
    print(f"wrote {OUT / 'README.md'}")


if __name__ == "__main__":
    main()
