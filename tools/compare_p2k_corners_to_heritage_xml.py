#!/usr/bin/env python3
"""Study-only comparison of P2K corners against heritage MorphDesigner XML.

This answers a narrow question: do any of the local P2K 240-byte ROM reference
corners line up with the compiled heritage XML presets?

Clean-room boundary:
- emits only derived names, labels, aggregate match counts, and RMS distances;
- does not write packed words, coefficient tables, endpoint bodies, or curves;
- treats XML names as study labels only.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import packed_interp, trench_ffi  # noqa: E402
from pyruntime.designer_compile import compile_designer, parse_xml  # noqa: E402

P2K_DIR = ROOT / "ref" / "presets"
XML_DIR = ROOT / "ref" / "heritage"
OUT = ROOT / "dev" / "tmp" / "p2k_xml_corner_alignment"

CORNER_LABELS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
CORNER_POS = {
    "M0_Q0": (0.0, 0.0),
    "M100_Q0": (1.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q100": (1.0, 1.0),
}
FREQS = np.geomspace(50.0, 16_000.0, 420)
COMPARE_MASK = (FREQS >= 80.0) & (FREQS <= 12_000.0)
SR = 39_062.5
EPS = 1e-20


@dataclass(frozen=True)
class CornerSig:
    source: str
    preset: str
    corner: str
    body_path: str
    words_fingerprint: tuple[tuple[int, ...], ...]
    curve: np.ndarray
    norm_curve: np.ndarray
    span_db: float


def body_rows_by_corner(body: bytes) -> dict[str, list[tuple[int, ...]]]:
    if len(body) != trench_ffi.BODY_BYTES:
        raise ValueError(f"body must be {trench_ffi.BODY_BYTES} bytes")
    out: dict[str, list[tuple[int, ...]]] = {}
    offset = 0
    for label in CORNER_LABELS:
        rows = []
        for _stage in range(trench_ffi.NUM_STAGES):
            row = []
            for _coeff in range(trench_ffi.NUM_COEFFS):
                row.append(int.from_bytes(body[offset:offset + 2], "little"))
                offset += 2
            rows.append(tuple(row))
        out[label] = rows
    return out


def response_db_cascade(biquads: list[tuple[float, float, float, float, float]]) -> np.ndarray:
    z1 = np.exp(-1j * 2.0 * np.pi * FREQS / SR)
    z2 = z1 * z1
    h = np.ones_like(FREQS, dtype=np.complex128)
    for b0, b1, b2, a1, a2 in biquads:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), EPS))


def normalize(curve: np.ndarray) -> np.ndarray:
    return curve - float(np.mean(curve[COMPARE_MASK]))


def curve_span(curve: np.ndarray) -> float:
    band = curve[COMPARE_MASK]
    return float(np.max(band) - np.min(band))


def rms(a: np.ndarray, b: np.ndarray) -> float:
    d = a[COMPARE_MASK] - b[COMPARE_MASK]
    return float(np.sqrt(np.mean(d * d)))


def corner_curve(body: bytes, label: str) -> np.ndarray:
    probe = trench_ffi.packed_probe(body, *CORNER_POS[label])
    biquads = [tuple(map(float, bq)) for bq in probe["biquad"]]
    return response_db_cascade(biquads)


def enc_to_words(enc) -> tuple[int, ...]:
    return tuple(
        int(word) & 0xFFFF
        for word in packed_interp.coeffs_to_words(enc.c0, enc.c1, enc.c2, enc.c3, enc.c4)
    )


def xml_to_body(xml_path: Path) -> bytes:
    arr = compile_designer(parse_xml(str(xml_path)))
    # CornerArray internal order:
    # A=M0_Q0, B=M0_Q100, C=M100_Q0, D=M100_Q100.
    # trench_ffi body order:
    # A=M0_Q0, B=M100_Q0, C=M0_Q100, D=M100_Q100.
    enc = [corner.encode() for corner in arr._corners]
    # The old Python object model can pad to 12 physical stages. The heritage
    # XML format and the packed runtime body under study here are six sections.
    bank = {
        "A": [enc_to_words(e) for e in enc[0][:trench_ffi.NUM_STAGES]],
        "B": [enc_to_words(e) for e in enc[2][:trench_ffi.NUM_STAGES]],
        "C": [enc_to_words(e) for e in enc[1][:trench_ffi.NUM_STAGES]],
        "D": [enc_to_words(e) for e in enc[3][:trench_ffi.NUM_STAGES]],
    }
    return trench_ffi.body_bytes_from_corner_words(bank)


def load_p2k_sigs() -> list[CornerSig]:
    sigs: list[CornerSig] = []
    for path in sorted(P2K_DIR.glob("P2k_*.bin")):
        if path.name == "talking_hedz.bin":
            continue
        body = path.read_bytes()
        rows_by_corner = body_rows_by_corner(body)
        for label in CORNER_LABELS:
            curve = corner_curve(body, label)
            sigs.append(CornerSig(
                source="p2k",
                preset=path.stem,
                corner=label,
                body_path=str(path.relative_to(ROOT)),
                words_fingerprint=tuple(rows_by_corner[label]),
                curve=curve,
                norm_curve=normalize(curve),
                span_db=curve_span(curve),
            ))
    return sigs


def load_xml_sigs() -> tuple[list[CornerSig], list[dict[str, object]]]:
    sigs: list[CornerSig] = []
    compile_rows: list[dict[str, object]] = []
    for path in sorted(XML_DIR.glob("*.xml")):
        try:
            body = xml_to_body(path)
        except Exception as exc:
            compile_rows.append({"xml": path.stem, "status": "failed", "error": str(exc)})
            continue
        rows_by_corner = body_rows_by_corner(body)
        endpoint_rows = {
            "M0": rows_by_corner["M0_Q0"],
            "M100": rows_by_corner["M100_Q0"],
        }
        for endpoint, words in endpoint_rows.items():
            label = "M0_Q0" if endpoint == "M0" else "M100_Q0"
            curve = corner_curve(body, label)
            sigs.append(CornerSig(
                source="xml",
                preset=path.stem,
                corner=endpoint,
                body_path=str(path.relative_to(ROOT)),
                words_fingerprint=tuple(words),
                curve=curve,
                norm_curve=normalize(curve),
                span_db=curve_span(curve),
            ))
        compile_rows.append({"xml": path.stem, "status": "compiled", "endpoints": 2})
    return sigs, compile_rows


def exact_corner_matches(p2k: list[CornerSig], xml: list[CornerSig]) -> list[dict[str, object]]:
    index: dict[tuple[tuple[int, ...], ...], list[CornerSig]] = {}
    for sig in xml:
        index.setdefault(sig.words_fingerprint, []).append(sig)
    rows = []
    for psig in p2k:
        for xsig in index.get(psig.words_fingerprint, []):
            rows.append({
                "p2k_preset": psig.preset,
                "p2k_corner": psig.corner,
                "xml_template": xsig.preset,
                "xml_endpoint": xsig.corner,
                "match_type": "exact_full_corner_words",
            })
    return rows


def exact_stage_matches(p2k: list[CornerSig], xml: list[CornerSig]) -> list[dict[str, object]]:
    index: dict[tuple[int, ...], list[tuple[CornerSig, int]]] = {}
    for xsig in xml:
        for stage, row in enumerate(xsig.words_fingerprint, start=1):
            index.setdefault(row, []).append((xsig, stage))
    rows = []
    for psig in p2k:
        for pstage, row in enumerate(psig.words_fingerprint, start=1):
            for xsig, xstage in index.get(row, []):
                rows.append({
                    "p2k_preset": psig.preset,
                    "p2k_corner": psig.corner,
                    "p2k_stage": pstage,
                    "xml_template": xsig.preset,
                    "xml_endpoint": xsig.corner,
                    "xml_stage": xstage,
                    "match_type": "exact_single_stage_words",
                })
    return rows


def nearest_corner_matches(p2k: list[CornerSig], xml: list[CornerSig]) -> list[dict[str, object]]:
    rows = []
    for psig in p2k:
        best = min(xml, key=lambda xsig: rms(psig.norm_curve, xsig.norm_curve))
        score = rms(psig.norm_curve, best.norm_curve)
        if score < 1.0:
            strength = "very_close"
        elif score < 2.5:
            strength = "strong"
        elif score < 5.0:
            strength = "family"
        else:
            strength = "weak"
        rows.append({
            "p2k_preset": psig.preset,
            "p2k_corner": psig.corner,
            "nearest_xml_template": best.preset,
            "nearest_xml_endpoint": best.corner,
            "normalized_corner_rms_db": round(score, 5),
            "p2k_span_db": round(psig.span_db, 5),
            "xml_span_db": round(best.span_db, 5),
            "strength": strength,
        })
    return rows


def nearest_structural_corner_matches(p2k: list[CornerSig], xml: list[CornerSig]) -> list[dict[str, object]]:
    structural_p2k = [sig for sig in p2k if sig.span_db >= 3.0]
    structural_xml = [
        sig for sig in xml
        if sig.span_db >= 3.0 and sig.preset != "All Off Designer"
    ]
    rows = nearest_corner_matches(structural_p2k, structural_xml)
    for row in rows:
        row["filter"] = "p2k_span>=3_db; xml_span>=3_db; xml_not_all_off"
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    p2k: list[CornerSig],
    xml: list[CornerSig],
    compile_rows: list[dict[str, object]],
    exact_corners: list[dict[str, object]],
    exact_stages: list[dict[str, object]],
    nearest: list[dict[str, object]],
    structural_nearest: list[dict[str, object]],
) -> None:
    strength_counts = Counter(row["strength"] for row in nearest)
    strong_rows = [row for row in nearest if row["strength"] in {"very_close", "strong"}]
    strong_by_p2k = Counter(row["p2k_preset"] for row in strong_rows)
    strong_by_xml = Counter(row["nearest_xml_template"] for row in strong_rows)
    family_or_better = [row for row in nearest if row["strength"] in {"very_close", "strong", "family"}]
    structural_strength_counts = Counter(row["strength"] for row in structural_nearest)
    structural_strong_rows = [
        row for row in structural_nearest
        if row["strength"] in {"very_close", "strong"}
    ]
    structural_family_or_better = [
        row for row in structural_nearest
        if row["strength"] in {"very_close", "strong", "family"}
    ]
    structural_by_p2k = Counter(row["p2k_preset"] for row in structural_strong_rows)
    structural_by_xml = Counter(row["nearest_xml_template"] for row in structural_strong_rows)
    exact_stage_by_p2k = Counter(row["p2k_preset"] for row in exact_stages)
    compiled = sum(1 for row in compile_rows if row["status"] == "compiled")
    failed = len(compile_rows) - compiled

    lines = [
        "# P2K Corner Alignment Against Heritage XML",
        "",
        "Study-only clean-room report. XML template names are reference labels only.",
        "No packed words, coefficient tables, endpoint bodies, or response curves are emitted.",
        "",
        "## Boundary",
        "",
        "- Heritage XML compiles as a morph-only surface: two meaningful endpoints.",
        "- P2K bodies have four real corners: Morph x Q.",
        "- Therefore this compares each P2K corner against XML M0/M100 endpoints.",
        "",
        "## Result",
        "",
        f"- P2K corners tested: `{len(p2k)}` from `50` local P2K bodies.",
        f"- XML endpoints tested: `{len(xml)}` from `{compiled}` compiled XML templates; failed XML templates: `{failed}`.",
        f"- Exact full-corner word matches: `{len(exact_corners)}`.",
        f"- Exact single-stage word matches: `{len(exact_stages)}`.",
        f"- Strong/very-close full-corner response matches: `{len(strong_rows)}`.",
        f"- Family-or-better full-corner response matches: `{len(family_or_better)}`.",
        f"- Structural strong/very-close matches after removing flat/no-op corners: `{len(structural_strong_rows)}`.",
        f"- Structural family-or-better matches after removing flat/no-op corners: `{len(structural_family_or_better)}`.",
        "",
        "## Interpretation",
        "",
    ]
    if exact_corners:
        lines.append("- At least one P2K corner is byte-identical to a compiled XML endpoint.")
    else:
        lines.append("- No P2K corner is byte-identical to a compiled XML endpoint.")
    if structural_strong_rows:
        lines.append("- Some P2K corners do line up in response shape with XML endpoints.")
    else:
        lines.append("- No non-flat P2K corners line up strongly by full-corner response shape under this metric.")
    lines += [
        "- Exact single-stage matches, when present, are weaker evidence than full-corner matches.",
        "- A response-shape match means shared topology/grammar, not copied preset data.",
        "- Flat/no-op corners are separated because they trivially match all-off XML endpoints.",
        "",
        "## Strength Counts",
        "",
    ]
    for strength in ("very_close", "strong", "family", "weak"):
        lines.append(f"- `{strength}`: `{strength_counts[strength]}` P2K corners")
    lines += [
        "",
        "## Structural Strength Counts",
        "",
        "After filtering to corners with at least 3 dB in-band span and excluding `All Off Designer`:",
        "",
    ]
    for strength in ("very_close", "strong", "family", "weak"):
        lines.append(f"- `{strength}`: `{structural_strength_counts[strength]}` structural P2K corners")
    lines += ["", "## P2K Bodies With Most Strong XML-Corner Neighbors", ""]
    for preset, count in strong_by_p2k.most_common(20):
        lines.append(f"- `{preset}`: `{count}` strong/very-close corners")
    lines += ["", "## XML Templates Most Often Selected By Strong P2K Corners", ""]
    for preset, count in strong_by_xml.most_common(20):
        lines.append(f"- `{preset}`: `{count}` strong/very-close P2K corners")
    lines += ["", "## Structural P2K Bodies With Strong XML-Corner Neighbors", ""]
    if structural_by_p2k:
        for preset, count in structural_by_p2k.most_common(20):
            lines.append(f"- `{preset}`: `{count}` structural strong/very-close corners")
    else:
        lines.append("- none")
    lines += ["", "## Structural XML Templates Selected By Strong P2K Corners", ""]
    if structural_by_xml:
        for preset, count in structural_by_xml.most_common(20):
            lines.append(f"- `{preset}`: `{count}` structural strong/very-close P2K corners")
    else:
        lines.append("- none")
    if exact_stage_by_p2k:
        lines += ["", "## Exact Single-Stage Reuse", ""]
        for preset, count in exact_stage_by_p2k.most_common(20):
            lines.append(f"- `{preset}`: `{count}` exact single-stage matches")
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "p2k_corners_tested": len(p2k),
        "xml_endpoints_tested": len(xml),
        "xml_templates_compiled": compiled,
        "xml_templates_failed": failed,
        "exact_full_corner_matches": len(exact_corners),
        "exact_single_stage_matches": len(exact_stages),
        "strength_counts": dict(strength_counts),
        "structural_filter": "p2k_span>=3_db; xml_span>=3_db; xml_not_all_off",
        "structural_strength_counts": dict(structural_strength_counts),
        "note": "study-only; no packed words/coefficient tables emitted",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if not trench_ffi.available():
        raise SystemExit("trench-core packed runtime unavailable; build target/release/trench_core.dll first")
    OUT.mkdir(parents=True, exist_ok=True)
    p2k = load_p2k_sigs()
    xml, compile_rows = load_xml_sigs()
    exact_corners = exact_corner_matches(p2k, xml)
    exact_stages = exact_stage_matches(p2k, xml)
    nearest = nearest_corner_matches(p2k, xml)
    structural_nearest = nearest_structural_corner_matches(p2k, xml)

    write_csv(OUT / "exact_full_corner_matches.csv", exact_corners)
    write_csv(OUT / "exact_single_stage_matches.csv", exact_stages)
    write_csv(OUT / "nearest_corner_response_matches.csv", nearest)
    write_csv(OUT / "nearest_structural_corner_response_matches.csv", structural_nearest)
    write_csv(OUT / "xml_compile_status.csv", compile_rows)
    write_report(p2k, xml, compile_rows, exact_corners, exact_stages, nearest, structural_nearest)

    print(f"wrote {OUT}")
    print(f"exact full-corner matches: {len(exact_corners)}")
    print(f"exact single-stage matches: {len(exact_stages)}")


if __name__ == "__main__":
    main()
