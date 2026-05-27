"""Batch body generator — 10 iconic TRENCH bodies, final combined approach.

Vocal/Lead/Bass/Pad/Drum: 6-stage stitch (proven P2K-competitive).
HiHat/Cymbal: 12-stage inharmonic metallic (proven 0.68).
808/LoFi/Pluck/FX: 12-stage notch sculpture (ears-only, metric can't judge).

Usage:
    python -m pyruntime.forge_batch
    python -m pyruntime.forge_batch --variants 5
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pyruntime.body import Body
from pyruntime.constants import SR, NUM_BODY_STAGES
from pyruntime.corner import CornerArray, CornerName, CornerState
from pyruntime.macro_compile import (
    Actor, BodySpec, CompileMacro, PressureBehavior,
    SlotSpec, SlotState, compile_body, freq_to_place,
)
from pyruntime.stage_params import StageParams
from pyruntime.stage_math import resonator, resonator_with_zero, zero_forced
from pyruntime.target import build_vowel_target, build_nasal_target, _empty_slot
from pyruntime.zero_law import ContourKind

VAULT_DIR = Path(__file__).parent.parent / "vault"

P2K_FOCUS = 0.97
P2K_WEIGHT = 0.66
P2K_BOOST = 4.0

ACTOR_CONTOUR = {
    Actor.FOUNDATION: (ContourKind.PURE, 0.0),
    Actor.MASS: (ContourKind.NEAR_ALLPASS, 0.3),
    Actor.THROAT: (ContourKind.INTERIOR_ZERO, 0.5),
    Actor.BITE: (ContourKind.UNIT_CIRCLE, 0.6),
    Actor.AIR: (ContourKind.INTERIOR_ZERO, 0.4),
    Actor.SCAR: (ContourKind.UNIT_CIRCLE, 0.0),
}

VOWELS = {
    "oo": (378, 997, 2343, 3357),
    "ee": (342, 2322, 3000, 3657),
    "ah": (768, 1189, 2555, 3508),
    "eh": (660, 1720, 2410, 3500),
    "oh": (450, 1030, 2500, 3500),
    "ae": (730, 1090, 2440, 3500),
    "ih": (446, 1993, 2657, 3599),
    "er": (490, 1350, 1690, 3500),
    "aw": (570, 840, 2410, 3500),
    "uh": (640, 1190, 2390, 3500),
    "schwa": (500, 1500, 2500, 3500),
}


# ---------------------------------------------------------------------------
# Stitch infrastructure (6-stage, proven P2K-competitive)
# ---------------------------------------------------------------------------

def _vowel_spec(name: str, vowel_key: str) -> BodySpec:
    f1, f2, f3, f4 = VOWELS[vowel_key]
    slots = [_empty_slot(a) for a in Actor.ALL]
    used = set()
    for freq in (f1, f2, f3, f4):
        for idx, actor in enumerate(Actor.ALL):
            if idx not in used and actor.freq_floor() <= freq <= actor.freq_ceiling():
                c, clr = ACTOR_CONTOUR.get(actor, (ContourKind.UNIT_CIRCLE, 0.5))
                state = SlotState(place=freq_to_place(actor, freq), focus=P2K_FOCUS,
                                  weight=P2K_WEIGHT, contour=c, color=clr, hue=0.0,
                                  contour_override=None)
                slots[idx] = SlotSpec(actor=actor, state_a=state, state_b=state,
                                      pressure=PressureBehavior.TIGHTEN,
                                      compile_macro=CompileMacro.SINGLE, spread=0.0)
                used.add(idx)
                break
    return BodySpec(name=name, slots=slots, boost=P2K_BOOST)


def _stitch(name: str, spec_a: BodySpec, spec_b: BodySpec, boost: float = P2K_BOOST) -> Body:
    ca = compile_body(spec_a)
    cb = compile_body(spec_b)
    return Body(name=name, corners=CornerArray(
        a=ca.corner(CornerName.A), b=ca.corner(CornerName.B),
        c=cb.corner(CornerName.C), d=cb.corner(CornerName.D),
    ), boost=boost)


# ---------------------------------------------------------------------------
# 12-stage infrastructure (metallic/notch bodies)
# ---------------------------------------------------------------------------

NOTCH_RADIUS = 0.38
NOTCH_WEIGHT = 0.08


@dataclass
class StageDef:
    freq_hz: float
    radius: float = 0.95
    weight: float = 0.66
    notch: str = "none"
    notch_offset_hz: float = 0.0
    notch_depth: float = 0.5

    def to_stage_params(self) -> StageParams:
        r = self.radius
        val1 = -1.0 + max(0.0, self.weight) * 0.85

        if self.notch == "none":
            return resonator(self.freq_hz, r, val1)
        elif self.notch == "unit_circle":
            return zero_forced(self.freq_hz, r, val1)
        elif self.notch == "offset":
            zero_freq = max(20.0, min(SR * 0.48, self.freq_hz + self.notch_offset_hz))
            return resonator_with_zero(self.freq_hz, r, val1, zero_freq, 1.0)
        elif self.notch == "interior":
            zero_r = r * (1.0 - self.notch_depth)
            return resonator_with_zero(self.freq_hz, r, val1, self.freq_hz, zero_r)
        return resonator(self.freq_hz, r, val1)


def P(freq_hz: float, radius: float = 0.93, weight: float = 0.60) -> StageDef:
    return StageDef(freq_hz, radius=radius, weight=weight)


def N(freq_hz: float, notch: str = "unit_circle", offset_hz: float = 0.0,
      depth: float = 0.5, r: float = NOTCH_RADIUS, w: float = NOTCH_WEIGHT) -> StageDef:
    return StageDef(freq_hz, radius=r, weight=w, notch=notch,
                    notch_offset_hz=offset_hz, notch_depth=depth)


def _lerp(a: float, b: float, t: float) -> float:
    return a + t * (b - a)


def _build_12(name: str, sa: list[StageDef], sb: list[StageDef],
              q_boost: float = 0.02, boost: float = P2K_BOOST) -> Body:
    corners = []
    for morph, q in [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]:
        stages: list[StageParams] = []
        for i in range(NUM_BODY_STAGES):
            if i < len(sa) and i < len(sb):
                a, b = sa[i], sb[i]
                freq = math.exp(_lerp(math.log(max(a.freq_hz, 1)), math.log(max(b.freq_hz, 1)), morph))
                radius = min(0.998, _lerp(a.radius, b.radius, morph) + q * q_boost)
                weight = _lerp(a.weight, b.weight, morph)
                sd = a if morph < 0.5 else b
                stages.append(StageDef(freq, radius, weight, sd.notch,
                    _lerp(a.notch_offset_hz, b.notch_offset_hz, morph),
                    _lerp(a.notch_depth, b.notch_depth, morph)).to_stage_params())
            else:
                stages.append(StageParams.passthrough())
        corners.append(CornerState(stages=stages, boost=boost))
    return Body(name=name, corners=CornerArray(
        a=corners[0], b=corners[1], c=corners[2], d=corners[3]), boost=boost)


# ---------------------------------------------------------------------------
# #1 Vocal Sauce — stitch (0.80-0.91)
# ---------------------------------------------------------------------------

def _vocal_sauce(n: int) -> list[tuple[str, Body]]:
    pairs = [("oo", "ee"), ("ah", "eh"), ("oh", "ae"), ("er", "ih"), ("aw", "ee")]
    return [(f"Vocal_{a}_{b}",
             _stitch(f"Vocal_{a}_{b}", _vowel_spec(f"_a", a), _vowel_spec(f"_b", b)))
            for a, b in pairs[:n]]


# ---------------------------------------------------------------------------
# #2 808 Sub — 12-stage, ears-only
# ---------------------------------------------------------------------------

def _808_sub(n: int) -> list[tuple[str, Body]]:
    configs = [("808_Deep", 40), ("808_Chest", 55), ("808_Boom", 35),
               ("808_Thud", 60), ("808_Rumble", 30)]
    bodies = []
    for name, f0 in configs[:n]:
        sa = [P(f0, 0.94, 0.70), P(f0*2, 0.92, 0.55), P(f0*3, 0.88, 0.35), P(f0*5, 0.85, 0.20),
              N(f0*1.5), N(f0*2.5), N(f0*3.5), N(f0*4.5, "offset", f0*0.4),
              N(f0*6), N(f0*8), N(f0*10), N(f0*14)]
        sb = [P(f0, 0.92, 0.55), P(f0*2, 0.90, 0.50), P(f0*3, 0.88, 0.45), P(f0*5, 0.86, 0.40),
              N(f0*1.5, "offset", f0*0.6), N(f0*2.5, "offset", f0*0.5),
              N(f0*3.5), N(f0*4.5), N(f0*6, "offset", -f0*0.5),
              N(f0*8), N(f0*10, "interior", depth=0.4), N(f0*14)]
        bodies.append((name, _build_12(name, sa, sb, boost=5.0)))
    return bodies


# ---------------------------------------------------------------------------
# #3 Drum Color — stitch (0.61)
# ---------------------------------------------------------------------------

def _drum_color(n: int) -> list[tuple[str, Body]]:
    # Drum bodies use vowels that emphasize different spectral regions
    pairs = [("ah", "ee"), ("aw", "ih"), ("oh", "eh"), ("uh", "ae"), ("er", "ee")]
    names = ["Drum_Knock", "Drum_Crack", "Drum_Body", "Drum_Snap", "Drum_Weight"]
    bodies = []
    for i, (a, b) in enumerate(pairs[:n]):
        name = names[i]
        bodies.append((name, _stitch(name, _vowel_spec(f"_a", a), _vowel_spec(f"_b", b))))
    return bodies


# ---------------------------------------------------------------------------
# #4 HiHat / Cymbal — 12-stage metallic (0.60-0.68)
# ---------------------------------------------------------------------------

def _hihat_cymbal(n: int) -> list[tuple[str, Body]]:
    configs = [
        ("HiHat_Sizzle",  800, [1.0, 1.47, 2.09, 2.56, 3.34, 4.11, 5.23, 6.17, 7.44, 8.93, 10.6, 12.8]),
        ("Cymbal_Wash",    600, [1.0, 1.51, 2.13, 2.71, 3.45, 4.22, 5.01, 6.38, 7.82, 9.45, 11.2, 13.5]),
        ("HiHat_Crisp",   1000, [1.0, 1.39, 1.98, 2.44, 3.18, 3.97, 5.15, 6.33, 7.61, 9.12, 10.9, 13.1]),
        ("Cymbal_Dark",    500, [1.0, 1.55, 2.22, 2.89, 3.67, 4.56, 5.34, 6.78, 8.11, 9.89, 11.8, 14.2]),
        ("HiHat_Tight",   1200, [1.0, 1.44, 2.05, 2.63, 3.41, 4.19, 5.28, 6.42, 7.73, 9.31, 11.1, 13.4]),
    ]
    bodies = []
    for name, base, ratios in configs[:n]:
        sa, sb = [], []
        for i, ratio in enumerate(ratios):
            freq = min(base * ratio, SR * 0.48 - 100)
            if i % 4 == 3:
                sa.append(StageDef(freq, 0.88, 0.50, notch="offset", notch_offset_hz=base * 0.2))
                sb.append(StageDef(freq * 1.15, 0.92, 0.60, notch="unit_circle"))
            else:
                sa.append(StageDef(freq, 0.90, 0.60 - i * 0.015))
                sb.append(StageDef(freq * 1.15, 0.94, 0.66 - i * 0.01))
        bodies.append((name, _build_12(name, sa, sb, boost=3.0)))
    return bodies


# ---------------------------------------------------------------------------
# #5 Bass Growl — stitch vowel→nasal (0.64-0.69)
# ---------------------------------------------------------------------------

def _bass_growl(n: int) -> list[tuple[str, Body]]:
    pairs = [("oo", "nasal_m"), ("aw", "nasal_n"), ("oh", "nasal_m"),
             ("uh", "nasal_n"), ("ah", "nasal_m")]
    bodies = []
    for v, nk in pairs[:n]:
        name = f"Bass_{v}_{nk.split('_')[1]}"
        sa = build_vowel_target(f"_a", v)
        sb = build_nasal_target(f"_b", nk)
        bodies.append((name, _stitch(name, sa, sb, boost=5.0)))
    return bodies


# ---------------------------------------------------------------------------
# #6 Pad / Texture — stitch vowel→vowel, soft focus (0.55-0.60)
# ---------------------------------------------------------------------------

def _pad_texture(n: int) -> list[tuple[str, Body]]:
    pairs = [("aw", "ee"), ("oh", "ih"), ("er", "ae"), ("oo", "ah"), ("schwa", "eh")]
    bodies = []
    for a, b in pairs[:n]:
        name = f"Pad_{a}_{b}"
        sa = _vowel_spec(f"_a", a)
        sb = _vowel_spec(f"_b", b)
        # Soften focus for broader pad character
        for spec in (sa, sb):
            for slot in spec.slots:
                if slot.state_a.weight > 0:
                    slot.state_a = SlotState(
                        place=slot.state_a.place, focus=0.88, weight=0.60,
                        contour=slot.state_a.contour, color=slot.state_a.color,
                        hue=0.0, contour_override=None)
                    slot.state_b = SlotState(
                        place=slot.state_b.place, focus=0.88, weight=0.60,
                        contour=slot.state_b.contour, color=slot.state_b.color,
                        hue=0.0, contour_override=None)
        bodies.append((name, _stitch(name, sa, sb, boost=3.5)))
    return bodies


# ---------------------------------------------------------------------------
# #7 Lead / Synth Bite — stitch nasal→vowel (0.62-0.82)
# ---------------------------------------------------------------------------

def _lead_bite(n: int) -> list[tuple[str, Body]]:
    pairs = [("nasal_m", "ee"), ("nasal_n", "eh"), ("nasal_m", "ae"),
             ("nasal_n", "ah"), ("nasal_m", "ih")]
    bodies = []
    for nk, v in pairs[:n]:
        name = f"Lead_{nk.split('_')[1]}_{v}"
        sa = build_nasal_target(f"_a", nk)
        sb = build_vowel_target(f"_b", v)
        bodies.append((name, _stitch(name, sa, sb, boost=4.5)))
    return bodies


# ---------------------------------------------------------------------------
# #8 LoFi / Tape — 12-stage notch erosion, ears-only
# ---------------------------------------------------------------------------

def _lofi_tape(n: int) -> list[tuple[str, Body]]:
    configs = [
        ("LoFi_Warm",     [150, 400, 1000, 2500]),
        ("LoFi_Tape",     [120, 350, 800, 2000]),
        ("LoFi_Vinyl",    [100, 300, 700, 1800]),
        ("LoFi_Radio",    [200, 500, 1200, 3000]),
        ("LoFi_Cassette", [130, 380, 900, 2200]),
    ]
    bodies = []
    for name, wf in configs[:n]:
        sa = [P(wf[0], 0.88, 0.55), P(wf[1], 0.86, 0.50),
              P(wf[2], 0.84, 0.45), P(wf[3], 0.82, 0.40),
              N(math.sqrt(wf[0]*wf[1]), "interior", depth=0.3),
              N(math.sqrt(wf[1]*wf[2]), "interior", depth=0.3),
              N(math.sqrt(wf[2]*wf[3]), "interior", depth=0.3),
              N(wf[3]*1.5, "interior", depth=0.2),
              N(5000, "interior", depth=0.2), N(7000, "interior", depth=0.2),
              N(10000, "interior", depth=0.2), N(14000, "interior", depth=0.2)]
        sb = [P(wf[0], 0.90, 0.60), P(wf[1], 0.88, 0.55),
              P(wf[2], 0.85, 0.40), P(wf[3], 0.82, 0.30),
              N(math.sqrt(wf[0]*wf[1]), "offset", 50),
              N(math.sqrt(wf[1]*wf[2])), N(math.sqrt(wf[2]*wf[3])),
              N(wf[3]*1.5), N(5000), N(7000), N(10000), N(14000)]
        bodies.append((name, _build_12(name, sa, sb, boost=3.0)))
    return bodies


# ---------------------------------------------------------------------------
# #9 Pluck / Key — 12-stage bell + notch, ears-only
# ---------------------------------------------------------------------------

def _pluck_key(n: int) -> list[tuple[str, Body]]:
    configs = [
        ("Pluck_Hosanna",  135.4, [1.0, 1.97, 2.56, 2.70]),
        ("Pluck_Freedom",  82.1,  [1.0, 2.01, 2.43, 3.03]),
        ("Pluck_Tower",    201.9, [1.0, 1.60, 2.10, 2.79]),
        ("Pluck_Treble",   763.0, [1.0, 1.35, 2.25, 4.39]),
        ("Pluck_Deep",     55.0,  [1.0, 2.0, 3.0, 4.0]),
    ]
    bodies = []
    for name, bf, ratios in configs[:n]:
        p = [min(bf * r, SR * 0.48 - 50) for r in ratios]
        sa = [P(p[0], 0.93, 0.60), P(p[1], 0.91, 0.55), P(p[2], 0.89, 0.50), P(p[3], 0.87, 0.45),
              N(math.sqrt(p[0]*p[1])), N(math.sqrt(p[1]*p[2])),
              N(math.sqrt(p[2]*p[3]), "offset", bf*0.2), N(p[3]*1.5),
              N(p[0]*0.5, "interior", depth=0.4), N(p[0]*3, "offset", -bf*0.3),
              N(6000), N(10000, "interior", depth=0.5)]
        sb = [P(p[0], 0.90, 0.50), P(p[1], 0.88, 0.40), P(p[2], 0.85, 0.30), P(p[3], 0.82, 0.20),
              N(math.sqrt(p[0]*p[1]), "offset", bf*0.4), N(math.sqrt(p[1]*p[2])),
              N(math.sqrt(p[2]*p[3])), N(p[3]*1.5),
              N(p[0]*0.5), N(p[0]*3), N(6000), N(10000)]
        bodies.append((name, _build_12(name, sa, sb, boost=4.0)))
    return bodies


# ---------------------------------------------------------------------------
# #10 FX / Riser — 12-stage sweep + traveling notches, ears-only
# ---------------------------------------------------------------------------

def _fx_riser(n: int) -> list[tuple[str, Body]]:
    names = ["FX_SubToAir", "FX_Tornado", "FX_Shatter", "FX_Ascend", "FX_Implode"]
    peak_lo = [60, 250, 1000, 4000]
    peak_hi = [400, 2000, 8000, 16000]
    notch_lo = [100, 180, 500, 1500, 3000, 6000, 10000, 14000]
    notch_hi = [600, 1200, 3000, 6000, 10000, 14000, 17000, 19000]
    nt_a = ["unit_circle", "offset", "unit_circle", "interior",
            "offset", "unit_circle", "interior", "unit_circle"]
    nt_b = ["offset", "unit_circle", "interior", "unit_circle",
            "unit_circle", "offset", "unit_circle", "interior"]
    bodies = []
    for idx, name in enumerate(names[:n]):
        shift = 1.0 + idx * 0.12
        sa, sb = [], []
        for i in range(4):
            fa = min(peak_lo[i] * shift, SR * 0.48 - 50)
            fb = min(peak_hi[i] * shift, SR * 0.48 - 50)
            if name == "FX_Implode": fa, fb = fb, fa
            sa.append(P(fa, 0.91, 0.55))
            sb.append(P(fb, 0.91, 0.55))
        for i in range(8):
            fa = min(notch_lo[i] * shift, SR * 0.48 - 50)
            fb = min(notch_hi[i] * shift, SR * 0.48 - 50)
            if name == "FX_Implode": fa, fb = fb, fa
            sa.append(N(fa, nt_a[i], fa * 0.2, depth=0.4))
            sb.append(N(fb, nt_b[i], -fb * 0.15, depth=0.4))
        bodies.append((name, _build_12(name, sa, sb, boost=4.0)))
    return bodies


# ---------------------------------------------------------------------------
# All recipes
# ---------------------------------------------------------------------------

RECIPES = [
    ("Vocal_Sauce", _vocal_sauce),
    ("808_Sub", _808_sub),
    ("Drum_Color", _drum_color),
    ("HiHat_Cymbal", _hihat_cymbal),
    ("Bass_Growl", _bass_growl),
    ("Pad_Texture", _pad_texture),
    ("Lead_Bite", _lead_bite),
    ("LoFi_Tape", _lofi_tape),
    ("Pluck_Key", _pluck_key),
    ("FX_Riser", _fx_riser),
]


def generate_batch(variants_per_recipe: int = 5) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = VAULT_DIR / f"batch_{ts}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for category, fn in RECIPES:
        for name, body in fn(variants_per_recipe):
            path = batch_dir / f"{name}.json"
            path.write_text(body.to_compiled_json())
            manifest.append({"category": category, "name": name, "path": str(path)})
            print(f"  {category:15s} | {name}")
    (batch_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\n{len(manifest)} bodies saved to {batch_dir}")
    return batch_dir


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--variants", type=int, default=5)
    generate_batch(p.parse_args().variants)
