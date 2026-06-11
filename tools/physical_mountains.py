#!/usr/bin/env python3
"""Generate deterministic physical-mountain DF2 bodies and packed-path plots.

This is an authoring feedstock tool, not a preset curator. Each body starts from
one acoustic object whose six pole roles remain registered across the four
corners. The nearby zero for each pole is an explicit original cavity treatment:
it is deterministic, visible in the output metadata, and never presented as a
literal consequence of the physical model.

There is deliberately no random module, jitter, ranking, or automatic keeper
selection in this file. The author judges the plots downstream.
"""
from __future__ import annotations

import html
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyruntime import packed_interp, trench_ffi
from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db
from tables.physical_models import closed_pipe_modes, free_plate_modes, helmholtz

SR = 39062.5
TAU = 2.0 * math.pi
FREQS = np.logspace(math.log10(55.0), math.log10(16000.0), 520)
OUT = ROOT / "dev" / "tmp" / "physical_mountains"

FIELD = "#090d0c"
INK = "#c6cec8"
MUTED = "#819087"
GRID = "#17211d"
SPINE = "#46564e"
COLORS = ["#e6a13b", "#56ed70", "#2fc8cc", "#ee493c"]
GRADIENT = ["#56ed70", "#2fc8cc", "#e6a13b", "#ff873c", "#ee493c"]
CORNER_KEYS = ["A", "B", "C", "D"]
CORNER_LABELS = ["M0 / S0", "M1 / S0", "M0 / S1", "M1 / S1"]


@dataclass(frozen=True)
class Anchor:
    label: str
    poles_hz: tuple[float, ...]
    physical_state: dict


@dataclass(frozen=True)
class MountainProgram:
    slug: str
    title: str
    family: str
    source_law: str
    motion: str
    anchor_a: Anchor
    anchor_b: Anchor
    q_base: tuple[float, ...]
    q_stress: float
    zero_offsets_semitones: tuple[float, ...]
    zero_radius_base: float
    zero_radius_stress: float


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def biquad_to_kernel(b0: float, b1: float, b2: float,
                     a1: float, a2: float) -> tuple[float, ...]:
    return (b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


def cavity_kernel(fp: float, q: float, zero_semitones: float,
                  rz: float) -> tuple[tuple[float, ...], float, float]:
    """One unity-DC pole+zero cavity and its authored pole/zero radii.

    The pole frequency comes from the physical model. The close zero offset is
    the deterministic mountain treatment: it creates the canyon next to the
    pole without adding a broad EQ pedestal.
    """
    rp = min(0.9985, max(0.90, math.exp(-math.pi * (fp / q) / SR)))
    fz = min(0.47 * SR, max(25.0, fp * (2.0 ** (zero_semitones / 12.0))))
    wp, wz = TAU * fp / SR, TAU * fz / SR
    a1, a2 = -2.0 * rp * math.cos(wp), rp * rp
    nb1, nb2 = -2.0 * rz * math.cos(wz), rz * rz
    gain = (1.0 + a1 + a2) / (1.0 + nb1 + nb2)
    return biquad_to_kernel(gain, gain * nb1, gain * nb2, a1, a2), rp, fz


def make_corner(program: MountainProgram, anchor: Anchor, stressed: bool) -> dict:
    rows = []
    stages = []
    q_mul = program.q_stress if stressed else 1.0
    rz = program.zero_radius_stress if stressed else program.zero_radius_base
    for index, (fp, q0, zsemi) in enumerate(zip(
        anchor.poles_hz, program.q_base, program.zero_offsets_semitones
    )):
        row, rp, fz = cavity_kernel(fp, q0 * q_mul, zsemi, rz)
        rows.append(row)
        stages.append({
            "stage": index,
            "pole_hz": round(fp, 5),
            "pole_radius": round(rp, 8),
            "zero_hz": round(fz, 5),
            "zero_radius": rz,
            "zero_offset_semitones": zsemi,
            "q": round(q0 * q_mul, 5),
        })
    return {"rows": rows, "stages": stages}


def pack_rows(rows: list[tuple[float, ...]]) -> list[tuple[int, ...]]:
    return [packed_interp.coeffs_to_words(*row) for row in rows]


def body_for(program: MountainProgram) -> tuple[bytes, dict, dict]:
    corner_defs = [
        make_corner(program, program.anchor_a, stressed=False),
        make_corner(program, program.anchor_b, stressed=False),
        make_corner(program, program.anchor_a, stressed=True),
        make_corner(program, program.anchor_b, stressed=True),
    ]
    words = {
        key: pack_rows(corner_defs[index]["rows"])
        for index, key in enumerate(CORNER_KEYS)
    }
    return trench_ffi.body_bytes_from_corner_words(words), words, {
        key: corner_defs[index] for index, key in enumerate(CORNER_KEYS)
    }


def response_at(body: bytes, morph: float, secondary: float) -> np.ndarray:
    rows = trench_ffi.packed_interpolate(body, morph, secondary)
    return cascade_response_db([EncodedCoeffs(*row) for row in rows], FREQS, SR)


def style_axis(ax) -> None:
    ax.set_facecolor(FIELD)
    ax.set_xscale("log")
    ax.set_xlim(FREQS[0], FREQS[-1])
    ax.grid(True, color=GRID, linewidth=0.45)
    ax.tick_params(colors=INK, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(SPINE)


def plot_markers(ax, stages: list[dict], ylo: float, yhi: float) -> None:
    pole_y = yhi - 1.5
    zero_y = ylo + 1.5
    poles = [stage["pole_hz"] for stage in stages]
    zeros = [stage["zero_hz"] for stage in stages]
    ax.scatter(poles, [pole_y] * len(poles), marker="v", s=18,
               color="#ffdd76", edgecolors="none", zorder=4)
    ax.scatter(zeros, [zero_y] * len(zeros), marker="^", s=18,
               color="#ff6770", edgecolors="none", zorder=4)


def collision_pairs(stages: list[dict]) -> list[dict]:
    ordered = sorted((float(stage["pole_hz"]), int(stage["stage"])) for stage in stages)
    out = []
    for (fa, ia), (fb, ib) in zip(ordered, ordered[1:]):
        if fb - fa < 200.0:
            out.append({"stage_a": ia, "stage_b": ib, "delta_hz": round(fb - fa, 3)})
    return out


def audit(body: bytes, corner_defs: dict) -> dict:
    grid = [0.0, 0.25, 0.5, 0.75, 1.0]
    worst_radius = 0.0
    unstable = 0
    nonfinite = 0
    curve_min = math.inf
    curve_max = -math.inf
    for secondary in grid:
        for morph in grid:
            probe = trench_ffi.packed_probe(body, morph, secondary)
            worst_radius = max(worst_radius, float(probe["max_pole_radius"]))
            unstable |= int(probe["unstable_mask"])
            nonfinite |= int(probe["nonfinite_mask"])
            curve = response_at(body, morph, secondary)
            curve_min = min(curve_min, float(np.min(curve)))
            curve_max = max(curve_max, float(np.max(curve)))
    return {
        "shipping_probe": str(trench_ffi.lib_path()),
        "grid": "5x5",
        "max_pole_radius": round(worst_radius, 8),
        "unstable_mask": unstable,
        "nonfinite_mask": nonfinite,
        "response_min_db": round(curve_min, 3),
        "response_max_db": round(curve_max, 3),
        "response_span_db": round(curve_max - curve_min, 3),
        "corner_collisions_under_200_hz": {
            key: collision_pairs(corner_defs[key]["stages"]) for key in CORNER_KEYS
        },
    }


def plot_program(program: MountainProgram, body: bytes,
                 corner_defs: dict, out_path: Path) -> None:
    corner_curves = [
        response_at(body, 0.0, 0.0),
        response_at(body, 1.0, 0.0),
        response_at(body, 0.0, 1.0),
        response_at(body, 1.0, 1.0),
    ]
    morphs = [0.0, 0.25, 0.5, 0.75, 1.0]
    field_curves = [
        response_at(body, morph, secondary)
        for secondary in (0.0, 1.0) for morph in morphs
    ]
    curves = corner_curves + field_curves
    yhi = min(50.0, max(float(np.max(curve)) for curve in curves) + 4.0)
    ylo = max(-80.0, min(float(np.min(curve)) for curve in curves) - 4.0)
    if yhi - ylo < 55.0:
        ylo = yhi - 55.0

    fig = plt.figure(figsize=(12.5, 10.5), facecolor=FIELD)
    gs = GridSpec(4, 2, height_ratios=[1.0, 1.0, 1.24, 1.24],
                  hspace=0.48, wspace=0.15)
    for index, curve in enumerate(corner_curves):
        row, col = divmod(index, 2)
        ax = fig.add_subplot(gs[row, col])
        style_axis(ax)
        color = COLORS[index]
        ax.plot(FREQS, curve, color=color, linewidth=1.6)
        ax.fill_between(FREQS, curve, ylo, color=color, alpha=0.10)
        ax.set_ylim(ylo, yhi)
        key = CORNER_KEYS[index]
        stages = corner_defs[key]["stages"]
        plot_markers(ax, stages, ylo, yhi)
        poles = " ".join(str(round(stage["pole_hz"])) for stage in stages)
        ax.set_title(f"{CORNER_LABELS[index]}  {key}", color=INK,
                     family="monospace", fontsize=9)
        ax.text(0.02, 0.055, f"poles {poles} Hz",
                color=MUTED, family="monospace", fontsize=6.4,
                transform=ax.transAxes)

    for row, secondary in ((2, 0.0), (3, 1.0)):
        ax = fig.add_subplot(gs[row, :])
        style_axis(ax)
        for color, morph in zip(GRADIENT, morphs):
            ax.plot(FREQS, response_at(body, morph, secondary),
                    color=color, linewidth=1.45, label=f"M={morph:g}")
        ax.set_ylim(ylo, yhi)
        ax.set_ylabel("dB", color=INK, fontsize=8)
        ax.set_title(
            f"MORPH field  SECONDARY={secondary:g}  "
            f"({'natural damping' if secondary == 0.0 else 'stressed / ringing'})",
            color=COLORS[0] if secondary == 0.0 else COLORS[2],
            family="monospace", fontsize=9.5,
        )
        ax.legend(facecolor="#111610", edgecolor=SPINE, labelcolor=INK,
                  fontsize=7, ncol=5, loc="upper right")
    ax.set_xlabel("frequency (Hz)", color=INK, fontsize=9)

    fig.suptitle(
        f"PHYSICAL MOUNTAIN  {program.title}\n"
        f"{program.source_law}\n"
        f"MORPH: {program.motion}  |  SECONDARY: damping -> stressed/ringing  |  "
        "yellow triangles=poles  red triangles=zeros  |  exact shipped packed interpolation",
        x=0.055, y=0.995, ha="left", va="top", color=INK,
        family="monospace", fontsize=8.4,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.925])
    fig.savefig(out_path, dpi=145, facecolor=FIELD)
    plt.close(fig)


def vowel_anchor(vowels: dict, key: str, label: str) -> Anchor:
    row = next(vowel for vowel in vowels["vowels"] if vowel["key"] == key)
    # F4 is held constant in the Klatt cascade model; the last cavity is the
    # glottal/air outlet. Both stay role-locked while F1-F3 perform the vowel.
    poles = (185.0, float(row["f1"]), float(row["f2"]),
             float(row["f3"]), 3300.0, 5550.0)
    return Anchor(label, poles, {
        "source": "Peterson-Barney adult-male acoustic formants plus Klatt fixed F4",
        "vowel_key": key,
        "ipa": row["ipa"],
        "example": row["example"],
    })


def pipe_anchor(label: str, length_cm: float) -> Anchor:
    return Anchor(label, tuple(closed_pipe_modes(length_cm, 6)), {
        "model": "closed pipe odd quarter-wave modes",
        "length_cm": length_cm,
    })


def bottle_anchor(label: str, volume_l: float, neck_diameter_cm: float,
                  neck_length_cm: float, body_length_cm: float) -> Anchor:
    poles = [helmholtz(volume_l, neck_diameter_cm, neck_length_cm)]
    poles.extend(closed_pipe_modes(body_length_cm, 5))
    return Anchor(label, tuple(poles), {
        "model": "Helmholtz neck plus closed body odd quarter-wave modes",
        "volume_l": volume_l,
        "neck_diameter_cm": neck_diameter_cm,
        "neck_length_cm": neck_length_cm,
        "body_length_cm": body_length_cm,
    })


def plate_anchor(label: str, radius_cm: float, thickness_mm: float) -> Anchor:
    return Anchor(label, tuple(free_plate_modes(radius_cm, thickness_mm, n=6)), {
        "model": "free-edge circular steel plate transverse modes",
        "radius_cm": radius_cm,
        "thickness_mm": thickness_mm,
    })


def bell_anchor(label: str, prime_hz: float, ratios: tuple[float, ...]) -> Anchor:
    return Anchor(label, tuple(prime_hz * ratio for ratio in ratios), {
        "model": "tuned-bell partial set",
        "prime_hz": prime_hz,
        "ratios": ratios,
    })


def programs() -> list[MountainProgram]:
    vowels = load_json(ROOT / "tables" / "vowel_formants.json")
    metallic = load_json(ROOT / "tables" / "metallic_modes.json")
    bell = next(obj for obj in metallic["objects"] if obj["key"] == "bell")
    bell_ratios = tuple(float(x) for x in bell["ratios"][:6])
    return [
        MountainProgram(
            "vocal_open_to_front", "Vocal cavity: open Ah -> front Ee", "vocal",
            "Peterson-Barney vowel formants with Klatt fixed F4; six registered cavities",
            "open throat -> bright front vowel",
            vowel_anchor(vowels, "aa", "open Ah"),
            vowel_anchor(vowels, "iy", "front Ee"),
            (3.8, 12.0, 14.0, 16.0, 14.0, 10.0), 1.55,
            (-3.0, 5.0, 5.0, 6.0, 6.0, 5.0), 0.89, 0.945,
        ),
        MountainProgram(
            "tube_long_to_short", "Pipe cavity: long tube -> short tube", "tube",
            "Closed-pipe odd quarter-wave modes; six registered longitudinal modes",
            "large hollow tube -> small biting tube",
            pipe_anchor("long closed tube", 47.0),
            pipe_anchor("short closed tube", 17.0),
            (4.0, 11.0, 13.0, 15.0, 15.0, 14.0), 1.62,
            (-4.0, 5.0, -5.0, 6.0, -6.0, 7.0), 0.88, 0.95,
        ),
        MountainProgram(
            "bottle_jug_to_jar", "Bottle cavity: jug -> hard jar", "bottle",
            "Helmholtz neck fundamental plus closed-body odd quarter-wave modes",
            "large jug bloom -> small jar bark",
            bottle_anchor("large jug", 3.4, 2.3, 4.5, 35.0),
            bottle_anchor("small hard jar", 0.72, 3.1, 2.6, 17.0),
            (5.0, 8.0, 12.0, 14.0, 15.0, 14.0), 1.68,
            (-5.0, 4.0, 5.0, -6.0, 7.0, -7.0), 0.88, 0.952,
        ),
        MountainProgram(
            "plate_large_to_small", "Steel plate: broad sheet -> tight disc", "plate",
            "Leissa free-edge circular-plate transverse modes; six registered modes",
            "large sheet wash -> small hard disc",
            plate_anchor("large thin plate", 13.0, 0.55),
            plate_anchor("small thick disc", 7.5, 0.82),
            (8.0, 12.0, 15.0, 17.0, 17.0, 18.0), 1.75,
            (-5.0, 5.0, -6.0, 7.0, -7.0, 8.0), 0.91, 0.968,
        ),
        MountainProgram(
            "bell_muted_to_bright", "Bell body: deep bell -> bright bell", "bell",
            "Rossing tuned-bell partial ratios; six registered named partial roles",
            "deep bell body -> bright struck bell",
            bell_anchor("deep bell", 430.0, bell_ratios),
            bell_anchor("bright bell", 760.0, bell_ratios),
            (7.0, 10.0, 13.0, 15.0, 17.0, 18.0), 1.80,
            (-5.0, 5.0, -6.0, 7.0, -7.0, 8.0), 0.91, 0.972,
        ),
    ]


def write_index(records: list[dict]) -> None:
    cards = []
    for record in records:
        audit_row = record["audit"]
        cards.append(f"""
        <article>
          <h2>{html.escape(record["title"])}</h2>
          <p>{html.escape(record["motion"])}</p>
          <p><code>{html.escape(record["slug"])}</code> |
             radius {audit_row["max_pole_radius"]} |
             span {audit_row["response_span_db"]} dB |
             unstable {audit_row["unstable_mask"]}</p>
          <a href="{record["plot"]}"><img src="{record["plot"]}"></a>
          <p><a href="{record["json"]}">machine-readable JSON</a> |
             <a href="{record["body240"]}">240-byte body</a></p>
        </article>""")
    (OUT / "index.html").write_text(f"""<!doctype html>
<meta charset="utf-8">
<title>DF2 physical mountains</title>
<style>
body {{ margin: 24px; background:#090d0c; color:#c6cec8; font:14px Consolas,monospace; }}
h1 {{ color:#e6a13b; }} h2 {{ color:#56ed70; margin-bottom:4px; }}
article {{ max-width:1100px; margin:0 0 34px; padding:14px; border:1px solid #46564e; }}
img {{ display:block; width:100%; max-width:1060px; margin-top:10px; }}
a {{ color:#2fc8cc; }} code {{ color:#ffdd76; }}
</style>
<h1>DF2 PHYSICAL MOUNTAINS</h1>
<p>Plot-first feedstock. Deterministic physical pole tracks plus explicit nearby-zero cavity treatment.
No jitter. No random poles. No automatic keeper selection. All curves use the shipped packed path.</p>
{''.join(cards)}
""", encoding="utf-8")


def write_overview(records: list[dict]) -> None:
    fig, axes = plt.subplots(len(records), 1, figsize=(12.5, 5.1 * len(records)),
                             facecolor=FIELD)
    for ax, record in zip(axes, records):
        image = plt.imread(OUT / record["plot"])
        ax.imshow(image)
        ax.set_axis_off()
    fig.subplots_adjust(left=0.0, right=1.0, top=1.0, bottom=0.0, hspace=0.035)
    fig.savefig(OUT / "overview.png", dpi=105, facecolor=FIELD)
    plt.close(fig)


def main() -> None:
    if not trench_ffi.available():
        raise SystemExit("trench-core DLL missing: build with cargo build -p trench-core --release")
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for program in programs():
        body, words, corner_defs = body_for(program)
        audit_row = audit(body, corner_defs)
        if audit_row["unstable_mask"] or audit_row["nonfinite_mask"]:
            raise RuntimeError(f"{program.slug}: packed-path stability failure: {audit_row}")
        body_path = OUT / f"{program.slug}.body240"
        json_path = OUT / f"{program.slug}.json"
        plot_path = OUT / f"{program.slug}.png"
        body_path.write_bytes(body)
        plot_program(program, body, corner_defs, plot_path)
        payload = {
            "format": "df2-physical-mountain-v1",
            "boundary": (
                "Original deterministic authoring feedstock. Physical model supplies pole tracks. "
                "Nearby zeros are an explicit original cavity treatment, not copied data and not "
                "claimed as literal physical anti-resonances. Human author decides taste downstream."
            ),
            "program": asdict(program),
            "corners": corner_defs,
            "packedWords": {
                key: [list(row) for row in rows] for key, rows in words.items()
            },
            "body240": body_path.name,
            "audit": audit_row,
        }
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        records.append({
            "slug": program.slug,
            "title": program.title,
            "motion": program.motion,
            "plot": plot_path.name,
            "json": json_path.name,
            "body240": body_path.name,
            "audit": audit_row,
        })
        print(
            f"{program.slug:24} radius={audit_row['max_pole_radius']:.6f} "
            f"span={audit_row['response_span_db']:7.2f}dB "
            f"collisions={sum(len(v) for v in audit_row['corner_collisions_under_200_hz'].values())}"
        )
    (OUT / "manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    write_index(records)
    write_overview(records)
    print(f"wrote {len(records)} physical-mountain bodies to {OUT}")
    print(f"open {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
