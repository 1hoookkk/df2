"""Export the Studio v1 filter-FX lineup into plugin-facing factory artifacts.

Source of truth is the clean-room lane data generated for Forge Studio. This
tool repacks every body, scores the packed bytes through the runtime metrics,
writes canonical .body240 files under presets/, writes JUCE cartridge JSON into
juce-shell/assets/cartridges/, and emits a verification manifest.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.body240 import CORNER_ORDER, compiled_payload, raw_from_words, render_png  # noqa: E402
from tools.forge_author_server import pack, score_body  # noqa: E402

LINEUP = ROOT / "dev" / "tmp" / "forge_v1_lineup" / "lineup.json"
PRESETS = ROOT / "presets"
CARTRIDGES = ROOT / "juce-shell" / "assets" / "cartridges"
OUT = ROOT / "dev" / "tmp" / "forge_v1_lineup" / "factory_export"

PRODUCT_NAMES = {
    "808 Tear": "808 Tear",
    "Talking Mouth": "Talking Mouth",
    "Millennium Bank": "Epoch Bank",
    "Lucifer Cut": "Abyss Cut",
    "Klub Acid": "Warehouse Acid",
    "Ear Comb": "Needle Comb",
}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"v1_{slug}"


def body_from_cart_words(cart: dict[str, Any]) -> bytes:
    by_label: dict[str, list[tuple[int, ...]]] = {}
    for keyframe in cart["keyframes"]:
        label = keyframe["label"]
        by_label[label] = [tuple(int(v) for v in row) for row in keyframe["packedWords"]]
    return raw_from_words(by_label)


def main() -> int:
    lineup = json.loads(LINEUP.read_text(encoding="utf-8"))
    PRESETS.mkdir(parents=True, exist_ok=True)
    CARTRIDGES.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    manifest = {
        "format": "trench-v1-filter-fx-lineup",
        "source": str(LINEUP.relative_to(ROOT)),
        "body_contract": "4 corners x 6 stages x 5 packed u16 = 240 bytes",
        "clean_room_note": (
            "Original generated lane recipes. Study references were used only "
            "for aggregate scoring targets; no reference names, bytes, packed "
            "tables, coefficient tables, or preset tables are copied."
        ),
        "entries": [],
    }

    for item in lineup:
        original_label = item["label"]
        name = PRODUCT_NAMES.get(original_label, original_label)
        slug = slugify(name)
        body, words = pack(item["lanes"])
        if len(body) != 240:
            raise RuntimeError(f"{name}: expected 240 bytes, got {len(body)}")

        normalized_words = {
            label: [tuple(int(v) for v in row) for row in words[label]]
            for label in CORNER_ORDER
        }
        if raw_from_words(normalized_words) != body:
            raise RuntimeError(f"{name}: raw_from_words mismatch")

        score = score_body(body, 17)
        failures = list(score.get("failures", []))
        if failures:
            raise RuntimeError(f"{name}: score gate failures {failures}")

        cart = compiled_payload(name, 1.0, normalized_words)
        cart["provenance"] = "forge-studio-v1-clean-room-lanes"
        cart["source"] = {
            "lineup_label": original_label,
            "fit_source": item.get("source"),
            "artifact": str(LINEUP.relative_to(ROOT)),
        }
        cart["score"] = score
        cart["cleanRoomNote"] = manifest["clean_room_note"]

        if body_from_cart_words(cart) != body:
            raise RuntimeError(f"{name}: cartridge packedWords do not round-trip")

        body_path = PRESETS / f"{slug}.body240"
        cart_path = CARTRIDGES / f"{slug}.json"
        plot_path = OUT / f"{slug}.png"
        body_path.write_bytes(body)
        cart_path.write_text(json.dumps(cart, indent=2) + "\n", encoding="utf-8")
        render_png(name, normalized_words, plot_path)

        manifest["entries"].append({
            "name": name,
            "slug": slug,
            "source_label": original_label,
            "fit_source": item.get("source"),
            "preset_body": str(body_path.relative_to(ROOT)),
            "cartridge": str(cart_path.relative_to(ROOT)),
            "response_plot": str(plot_path.relative_to(ROOT)),
            "body240_bytes": len(body),
            "body240_sha256": hashlib.sha256(body).hexdigest(),
            "score": score,
            "failures": failures,
        })

    manifest_path = OUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"exported {len(manifest['entries'])} v1 filter-FX bodies")
    print(f"manifest -> {manifest_path.relative_to(ROOT)}")
    for entry in manifest["entries"]:
        print(
            f"PASS {entry['slug']}: obj {entry['score']['metrics']['objective']:.3f} "
            f"M {entry['score']['metrics']['morph_contrast_rms_db']:.2f} "
            f"Q {entry['score']['metrics']['secondary_contrast_rms_db']:.2f} "
            f"sha {entry['body240_sha256'][:12]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
