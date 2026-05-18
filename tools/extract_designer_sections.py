#!/usr/bin/env python3
"""extract_designer_sections.py — parse genuine E-mu Filter template XML
into a designer-sections JSON.

Replaces the NotebookLM-derived `heritage_designer_sections.json`. Reads
the vendor `<designer-section>` arrays directly from the original E-mu
Emulator X Filter template `.xml` files (primary source), so the output
carries clean provenance instead of an AI-curated origin.

Usage:
    python tools/extract_designer_sections.py <xml_dir> <out.json>

Stdlib only.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path


def _int(el: ET.Element | None, default: int = 0) -> int:
    return int(el.text.strip()) if el is not None and el.text else default


def _float(el: ET.Element | None, default: float = 0.0) -> float:
    return float(el.text.strip()) if el is not None and el.text else default


def parse_template(path: Path) -> dict:
    root = ET.parse(path).getroot()
    filt = root.find("filter")
    if filt is None:
        raise ValueError(f"{path.name}: no <filter> element")
    sections = []
    for sec in filt.findall("designer-section"):
        sections.append({
            "index": int(sec.get("index", "0")),
            "type": _int(sec.find("type")),
            "low_freq": _int(sec.find("low-freq")),
            "low_gain": _int(sec.find("low-gain")),
            "high_freq": _int(sec.find("high-freq")),
            "high_gain": _int(sec.find("high-gain")),
        })
    return {
        "name": root.get("name", path.stem),
        "type_absolute": _int(filt.find("type-absolute")),
        "frequency": _float(filt.find("frequency")),
        "gain": _float(filt.find("gain")),
        "sections": sections,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    xml_dir, out_path = Path(argv[0]), Path(argv[1])
    xmls = sorted(xml_dir.glob("*.xml"))
    if not xmls:
        print(f"no .xml files in {xml_dir}", file=sys.stderr)
        return 1
    templates = [parse_template(p) for p in xmls]
    doc = {
        "format": "heritage-designer-sections-v2",
        "source": "E-mu Emulator X Family — genuine vendor Filter template XML",
        "source_dir": str(xml_dir),
        "generated": date.today().isoformat(),
        "generator": "tools/extract_designer_sections.py",
        "template_count": len(templates),
        "templates": templates,
    }
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(templates)} templates → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
