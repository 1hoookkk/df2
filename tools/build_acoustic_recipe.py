#!/usr/bin/env python3
"""Build three-layer acoustic recipes from the repo's acoustic tables.

This tool turns table knowledge into editable recipe JSON. It does not emit
packed words or audio; `tools/three_layer_acoustic_forge.py` remains the baker.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.body240 import AUTHORING_SR  # noqa: E402


TABLES = ROOT / "tables"
OUT = ROOT / "recipes" / "three_layer_acoustic_forge" / "generated"
FORMAT = "three-layer-acoustic-recipe-v1"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((TABLES / name).read_text(encoding="utf-8"))


def load_tables() -> dict[str, Any]:
    return {
        "vowel_formants": load_json("vowel_formants.json"),
        "klatt_1980_formants": load_json("klatt_1980_formants.json"),
        "klatt_1980_bandwidths": load_json("klatt_1980_bandwidths.json"),
        "tube_resonances": load_json("tube_resonances.json"),
        "family_intents": load_json("family_intents.json"),
        "metallic_modes": load_json("metallic_modes.json"),
        "q_radius_table": load_json("q_radius_table.json"),
    }


def slug(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(ch if ch.isalnum() else "_")
    return "_".join(part for part in "".join(out).split("_") if part)


def radius_from_bw(bw_hz: float, sr: float = AUTHORING_SR) -> float:
    return math.exp(-math.pi * float(bw_hz) / float(sr))


def q_calibration_summary(q_table: dict[str, Any]) -> dict[str, Any]:
    radii = [float(item["radius"]) for item in q_table.get("entries", [])]
    if not radii:
        return {"policy": "not_used_for_exact_recipe_values", "entries": 0}
    radii = sorted(radii)
    return {
        "policy": "calibration_range_only_not_exact_value_copy",
        "entries": len(radii),
        "radius_min": round(radii[0], 9),
        "radius_max": round(radii[-1], 9),
        "radius_median": round(radii[len(radii) // 2], 9),
    }


def fit_six(freqs: list[float]) -> list[float]:
    values = sorted(float(f) for f in freqs if float(f) > 0.0)
    if not values:
        raise ValueError("need at least one positive frequency")
    while len(values) < 6:
        nxt = values[-1] * (2.0 if len(values) < 3 else 1.5)
        values.append(min(nxt, 15_000.0))
    return values[:6]


def make_poles(home: list[float], away: list[float], roles: list[str], radii: list[tuple[float, float]]) -> list[dict[str, Any]]:
    out = []
    for lane, (h, a) in enumerate(zip(fit_six(home), fit_six(away))):
        h = max(35.0, min(17_500.0, h))
        a = max(35.0, min(17_500.0, a))
        center = math.sqrt(h * a)
        motion = math.log2(a / h) if h > 0 and a > 0 else 0.0
        r0, r1 = radii[min(lane, len(radii) - 1)]
        out.append({
            "lane": lane,
            "role": roles[lane] if lane < len(roles) else f"mode {lane + 1}",
            "pole_hz": round(center, 6),
            "pole_radius_q0": round(r0, 9),
            "pole_radius_q100": round(max(r0, r1), 9),
            "morph_octaves": round(motion, 6),
            "note": f"table-derived endpoints {h:.1f} -> {a:.1f} Hz",
        })
    return out


def make_zeros(home: list[float], away: list[float], modes: list[str], *, depth: float = 0.82) -> list[dict[str, Any]]:
    h6, a6 = fit_six(home), fit_six(away)
    out = []
    for lane, (h, a) in enumerate(zip(h6, a6)):
        if lane == 0:
            zh = h * 2.15
            za = a * 2.35
            mode = "shelf-knee"
        elif lane % 2:
            zh = h6[max(0, lane - 1)] * 0.92
            za = a6[min(5, lane + 1)] * 0.78
            mode = "opposing-canyon"
        else:
            zh = h6[min(5, lane + 1)] * 0.86
            za = a6[max(0, lane - 1)] * 1.08
            mode = "cross-canyon"
        out.append({
            "lane": lane,
            "mode": modes[lane] if lane < len(modes) else mode,
            "zero_home_ratio": round(max(0.12, min(8.0, zh / h)), 6),
            "zero_away_ratio": round(max(0.12, min(8.0, za / a)), 6),
            "zero_radius_q0": round(min(0.995, 0.84 + 0.045 * min(lane, 4)), 6),
            "zero_radius_q100": round(min(0.9985, 0.965 + 0.007 * min(lane, 4)), 6),
            "depth": round(max(0.1, min(1.0, depth)), 6),
            "note": "clean-room zero relation generated from table endpoints",
        })
    return out


def survival(strategy: str = "normalize_stages") -> dict[str, Any]:
    return {
        "gain_compensation_strategy": strategy,
        "factor": 0.45,
        "cap_db": 12.0,
        "loss_percentile": 60.0,
        "band_ratio": 2.3,
        "depth_weight_min": 0.35,
        "pressure_weight_base": 0.7,
        "pressure_weight_q": 0.55,
        "base_gain": 0.54,
        "low_lane_gain_bias": 1.18,
        "high_lane_pressure_trim": 0.9,
        "high_lane_pressure_start": 4,
    }


def recipe_doc(
    name: str,
    poles: list[dict[str, Any]],
    zeros: list[dict[str, Any]],
    tables: dict[str, Any],
    *,
    archetype: str,
    table_sources: list[str],
    notes: dict[str, Any],
) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "name": name,
        "sample_rate_hz": AUTHORING_SR,
        "clean_room_note": "Generated from clean acoustic tables. Recovered q_radius_table is used only as range calibration metadata.",
        "table_sources": table_sources,
        "calibration": {
            "q_radius_table": q_calibration_summary(tables["q_radius_table"]),
        },
        "notes": notes,
        "anatomy": {"poles": poles},
        "articulation": {
            "zero_table_archetype": archetype,
            "zeros": zeros,
        },
        "survival": survival(),
    }


def vowel_lookup(vowels: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for item in vowels["vowels"]:
        out[str(item["key"])] = item
        out[str(item.get("ipa", ""))] = item
    aliases = {"ee": "iy", "oo": "uw", "ah": "aa"}
    for alias, key in aliases.items():
        if key in out:
            out[alias] = out[key]
    return out


def vocal_recipe(
    tables: dict[str, Any],
    start: str,
    end: str,
    voice: str,
    *,
    f0_hz: float | None = None,
    foundation: str = "direct_formants",
) -> dict[str, Any]:
    vowels = vowel_lookup(tables["vowel_formants"])
    if start not in vowels or end not in vowels:
        raise ValueError(f"unknown vowel; available: {', '.join(sorted(k for k in vowels if k))}")
    scale = float(tables["vowel_formants"]["voice_scaling"].get(voice, 1.0))
    home_item, away_item = vowels[start], vowels[end]
    formant_home = [float(home_item[f"f{i}"]) * scale for i in (1, 2, 3)]
    formant_away = [float(away_item[f"f{i}"]) * scale for i in (1, 2, 3)]
    bw_home = [float(home_item.get(f"bw{i}", 90.0 + 30.0 * i)) for i in (1, 2, 3)]
    bw_away = [float(away_item.get(f"bw{i}", 90.0 + 30.0 * i)) for i in (1, 2, 3)]
    if foundation in {"low_shelf", "low_and_peak_shelf"}:
        f0 = float(f0_hz or 92.0)
        home = [f0, *formant_home, 3300.0 * scale, 9000.0 * scale]
        away = [f0 * 1.015, *formant_away, 3300.0 * scale, 9800.0 * scale]
        bws = [160.0, *[(h + a) * 0.5 for h, a in zip(bw_home, bw_away)], 250.0, 180.0]
        radii = [
            (0.925, 0.985),
            *[(radius_from_bw(bw * 2.5), radius_from_bw(max(8.0, bw * 0.55))) for bw in bws[1:4]],
            (radius_from_bw(250.0), radius_from_bw(55.0)),
            (radius_from_bw(180.0), radius_from_bw(35.0)),
        ]
        if foundation == "low_and_peak_shelf":
            roles = ["F0 low shelf", "F1 body", "F2 mouth", "F3 presence", "F4 peak shelf", "air peak shelf"]
            modes = ["fundamental-shelf-knee", "F1-canyon", "F2-mouth-canyon", "F3-presence-canyon", "peak-shelf-canyon", "air-shelf-canyon"]
        else:
            roles = ["F0 low shelf", "F1 body", "F2 mouth", "F3 presence", "F4 air", "ceiling"]
            modes = ["fundamental-shelf-knee", "F1-canyon", "F2-mouth-canyon", "F3-presence-canyon", "air-canyon", "ceiling-canyon"]
        name = f"recipe_vocal_{slug(start)}_to_{slug(end)}_{slug(voice)}_{foundation}"
    elif foundation == "peak_shelf":
        home = [*formant_home, 3300.0 * scale, 6200.0 * scale, 9000.0 * scale]
        away = [*formant_away, 3300.0 * scale, 7600.0 * scale, 9800.0 * scale]
        bws = [*[(h + a) * 0.5 for h, a in zip(bw_home, bw_away)], 250.0, 150.0, 120.0]
        radii = [
            *[(radius_from_bw(bw * 2.5), radius_from_bw(max(8.0, bw * 0.55))) for bw in bws[:3]],
            (radius_from_bw(250.0), radius_from_bw(55.0)),
            (radius_from_bw(150.0), radius_from_bw(30.0)),
            (radius_from_bw(120.0), radius_from_bw(24.0)),
        ]
        roles = ["F1 body", "F2 mouth", "F3 presence", "F4 air", "upper peak shelf", "ceiling peak shelf"]
        modes = ["F1-canyon", "F2-mouth-canyon", "F3-presence-canyon", "air-canyon", "peak-shelf-canyon", "ceiling-shelf-canyon"]
        name = f"recipe_vocal_{slug(start)}_to_{slug(end)}_{slug(voice)}_peak_shelf"
    else:
        home = formant_home
        away = formant_away
        bws = fit_six([(h + a) * 0.5 for h, a in zip(bw_home, bw_away)])
        radii = [(radius_from_bw(bw * 2.5), radius_from_bw(max(8.0, bw * 0.55))) for bw in bws]
        roles = ["F1 body", "F2 mouth", "F3 presence", "F4 air", "upper color", "ceiling"]
        modes = ["shelf-knee", "mouth-canyon", "presence-canyon", "air-canyon", "upper-canyon", "ceiling-canyon"]
        name = f"recipe_vocal_{slug(start)}_to_{slug(end)}_{slug(voice)}"
    return recipe_doc(
        name,
        make_poles(home, away, roles, radii),
        make_zeros(home, away, modes, depth=0.86),
        tables,
        archetype=f"vowel:{start}->{end}",
        table_sources=["vowel_formants.json", "klatt_1980_formants.json", "klatt_1980_bandwidths.json", "q_radius_table.json"],
        notes={
            "source": "vowel formants plus bandwidth-derived radii",
            "from": start,
            "to": end,
            "voice": voice,
            "foundation": foundation,
            "f0_hz": f0_hz,
            "home_shape": home_item.get("shape"),
            "away_shape": away_item.get("shape"),
        },
    )


def tube_lookup(tubes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["key"]): item for item in tubes["tubes"]}


def tube_recipe(tables: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    tubes = tube_lookup(tables["tube_resonances"])
    if start not in tubes or end not in tubes:
        raise ValueError(f"unknown tube; available: {', '.join(sorted(tubes))}")
    home = [float(v) for v in tubes[start]["partials_hz"]]
    away = [float(v) for v in tubes[end]["partials_hz"]]
    radii = [(radius_from_bw(70.0), radius_from_bw(12.0)) for _ in range(6)]
    roles = [f"partial {i + 1}" for i in range(6)]
    name = f"recipe_tube_{slug(start)}_to_{slug(end)}"
    return recipe_doc(
        name,
        make_poles(home, away, roles, radii),
        make_zeros(home, away, ["odd-hollow-canyon" if i % 2 else "length-canyon" for i in range(6)], depth=0.55),
        tables,
        archetype=f"tube-length:{start}->{end}",
        table_sources=["tube_resonances.json", "q_radius_table.json"],
        notes={"source": "tube partial tables", "from": tubes[start]["name"], "to": tubes[end]["name"]},
    )


def metal_lookup(metal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["key"]): item for item in metal["objects"]}


def metal_recipe(tables: dict[str, Any], start: str, end: str | None, fundamental: float | None) -> dict[str, Any]:
    objects = metal_lookup(tables["metallic_modes"])
    if start not in objects:
        raise ValueError(f"unknown metal object; available: {', '.join(sorted(objects))}")
    end = end or start
    if end not in objects:
        raise ValueError(f"unknown metal object: {end}")
    f0 = float(fundamental or objects[start].get("fundamental_hint_hz", 440.0))
    home = [f0 * float(r) for r in objects[start]["ratios"]]
    away_f0 = float(fundamental or objects[end].get("fundamental_hint_hz", f0))
    away = [away_f0 * float(r) for r in objects[end]["ratios"]]
    radii = [(radius_from_bw(45.0), radius_from_bw(8.0)) for _ in range(6)]
    roles = ["low mode", "tierce/mid mode", "body mode", "clang mode", "shimmer mode", "ceiling mode"]
    name = f"recipe_metal_{slug(start)}_to_{slug(end)}"
    return recipe_doc(
        name,
        make_poles(home, away, roles, radii),
        make_zeros(home, away, ["modal-canyon", "strike-canyon", "inharmonic-canyon", "ring-canyon", "shimmer-canyon", "ceiling-canyon"], depth=0.72),
        tables,
        archetype=f"metal:{start}->{end}",
        table_sources=["metallic_modes.json", "physical_models.py", "q_radius_table.json"],
        notes={"source": "metallic modal ratios", "from": objects[start]["name"], "to": objects[end]["name"], "fundamental_hz": f0},
    )


def family_recipe(tables: dict[str, Any], family: str, start: str, end: str | None) -> dict[str, Any]:
    families = tables["family_intents"]["families"]
    if family not in families:
        raise ValueError(f"unknown family; available: {', '.join(sorted(families))}")
    intents = families[family]["intents"]
    if start not in intents:
        raise ValueError(f"unknown {family} intent; available: {', '.join(sorted(intents))}")
    end = end or start
    if end not in intents:
        raise ValueError(f"unknown {family} intent: {end}")
    home = [float(v) for v in intents[start]["freqs"]]
    away = [float(v) for v in intents[end]["freqs"]]
    if family == "cavity":
        radii = [(radius_from_bw(95.0), radius_from_bw(22.0)) for _ in range(6)]
        depth = 0.58
    elif family in {"resonant", "knock", "comb"}:
        radii = [(radius_from_bw(70.0), radius_from_bw(14.0)) for _ in range(6)]
        depth = 0.78
    else:
        radii = [(radius_from_bw(120.0), radius_from_bw(30.0)) for _ in range(6)]
        depth = 0.72
    roles = list(families[family].get("slots", [])) + [f"mode {i + 1}" for i in range(6)]
    name = f"recipe_family_{slug(family)}_{slug(start)}_to_{slug(end)}"
    return recipe_doc(
        name,
        make_poles(home, away, roles, radii),
        make_zeros(home, away, [f"{role}-canyon" for role in roles], depth=depth),
        tables,
        archetype=f"family:{family}:{start}->{end}",
        table_sources=["family_intents.json", "physical_models.py", "q_radius_table.json"],
        notes={
            "source": "family intent table",
            "family": family,
            "from": intents[start].get("describe", start),
            "to": intents[end].get("describe", end),
        },
    )


def write_recipe(doc: dict[str, Any], out: Path | None) -> Path:
    out = out or OUT / f"{doc['name']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return out


def list_options(tables: dict[str, Any]) -> None:
    print("vowels:", ", ".join(sorted(k for k in vowel_lookup(tables["vowel_formants"]) if k)))
    print("tubes:", ", ".join(sorted(tube_lookup(tables["tube_resonances"]))))
    print("metal:", ", ".join(sorted(metal_lookup(tables["metallic_modes"]))))
    print("families:")
    for family, data in tables["family_intents"]["families"].items():
        print(f"  {family}: {', '.join(sorted(data['intents']))}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build three-layer recipe JSON from acoustic tables")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")

    vocal = sub.add_parser("vocal")
    vocal.add_argument("--from", dest="start", default="uw")
    vocal.add_argument("--to", dest="end", default="iy")
    vocal.add_argument("--voice", default="male")
    vocal.add_argument("--f0", type=float)
    vocal.add_argument(
        "--foundation",
        choices=["direct_formants", "low_shelf", "peak_shelf", "low_and_peak_shelf"],
        default="direct_formants",
    )
    vocal.add_argument("--out", type=Path)

    tube = sub.add_parser("tube")
    tube.add_argument("--from", dest="start", default="oo_50cm")
    tube.add_argument("--to", dest="end", default="oo_10cm")
    tube.add_argument("--out", type=Path)

    metal = sub.add_parser("metal")
    metal.add_argument("--from", dest="start", default="bell")
    metal.add_argument("--to", dest="end")
    metal.add_argument("--fundamental", type=float)
    metal.add_argument("--out", type=Path)

    family = sub.add_parser("family")
    family.add_argument("--family", required=True)
    family.add_argument("--from", dest="start", required=True)
    family.add_argument("--to", dest="end")
    family.add_argument("--out", type=Path)

    args = parser.parse_args()
    tables = load_tables()
    if args.cmd == "list":
        list_options(tables)
        return
    if args.cmd == "vocal":
        doc = vocal_recipe(tables, args.start, args.end, args.voice, f0_hz=args.f0, foundation=args.foundation)
    elif args.cmd == "tube":
        doc = tube_recipe(tables, args.start, args.end)
    elif args.cmd == "metal":
        doc = metal_recipe(tables, args.start, args.end, args.fundamental)
    elif args.cmd == "family":
        doc = family_recipe(tables, args.family, args.start, args.end)
    else:
        raise AssertionError(args.cmd)
    path = write_recipe(doc, args.out)
    print(f"wrote {path}")
    print(f"name {doc['name']}")


if __name__ == "__main__":
    main()
