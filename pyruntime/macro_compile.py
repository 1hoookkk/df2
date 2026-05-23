"""Macro compiler — Station surface vocabulary to physical stages.

Translates Actor/SlotSpec/BodySpec into compiled CornerArray.
Day one: SINGLE macro only.

Transcribed from runtime/src/macro_compile.rs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pyruntime.constants import SR, TWO_PI, NUM_BODY_STAGES
from pyruntime.corner import CornerArray, CornerName, CornerState
from pyruntime.stage_params import StageParams
from pyruntime.zero_law import ContourFamily, ContourKind, resolve_contour
from pyruntime import stage_math


# ---------------------------------------------------------------------------
# Actor enum — frequency bands for the six station slots
# ---------------------------------------------------------------------------

class Actor(Enum):
    FOUNDATION = "Foundation"
    MASS = "Mass"
    THROAT = "Throat"
    BITE = "Bite"
    AIR = "Air"
    SCAR = "Scar"

    def freq_floor(self) -> float:
        return {
            "Foundation": 20.0, "Mass": 60.0, "Throat": 250.0,
            "Bite": 1200.0, "Air": 2800.0, "Scar": 20.0,
        }[self.value]

    def freq_ceiling(self) -> float:
        return {
            "Foundation": 250.0, "Mass": 600.0, "Throat": 2500.0,
            "Bite": 5500.0, "Air": 14000.0, "Scar": 18000.0,
        }[self.value]


Actor.ALL = [Actor.FOUNDATION, Actor.MASS, Actor.THROAT, Actor.BITE, Actor.AIR, Actor.SCAR]


# ---------------------------------------------------------------------------
# Pressure behavior and compile macro enums
# ---------------------------------------------------------------------------

class PressureBehavior(Enum):
    HOLD = "Hold"
    TIGHTEN = "Tighten"
    YIELD = "Yield"
    CROSS = "Cross"
    COLLAPSE = "Collapse"


class CompileMacro(Enum):
    SINGLE = "Single"


# ---------------------------------------------------------------------------
# SlotState, SlotSpec, BodySpec
# ---------------------------------------------------------------------------

@dataclass
class SlotState:
    place: float
    focus: float
    weight: float
    contour: ContourKind
    color: float
    hue: float
    contour_override: Optional[ContourFamily]


@dataclass
class SlotSpec:
    actor: Actor
    state_a: SlotState
    state_b: SlotState
    pressure: PressureBehavior
    compile_macro: CompileMacro
    spread: float


@dataclass
class BodySpec:
    name: str
    slots: list  # list[SlotSpec]
    boost: float


# ---------------------------------------------------------------------------
# CompiledSlot
# ---------------------------------------------------------------------------

@dataclass
class CompiledSlot:
    primary: StageParams
    secondary: Optional[StageParams] = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def place_to_freq(actor: Actor, place: float) -> float:
    lo = math.log(actor.freq_floor())
    hi = math.log(actor.freq_ceiling())
    return math.exp(lo + max(0.0, min(1.0, place)) * (hi - lo))


def freq_to_place(actor: Actor, freq_hz: float) -> float:
    lo = math.log(actor.freq_floor())
    hi = math.log(actor.freq_ceiling())
    if abs(hi - lo) < 1e-10:
        return 0.5
    return max(0.0, min(1.0,
        (math.log(max(1.0, min(SR * 0.48, freq_hz))) - lo) / (hi - lo)
    ))


def focus_to_radius(focus: float) -> float:
    r_lo = 0.30
    r_hi = 0.998
    return r_lo + max(0.0, min(1.0, focus)) * (r_hi - r_lo)


def weight_to_val1(weight: float) -> float:
    v_silent = -1.0
    v_full = -0.15
    w = weight if math.isfinite(weight) else 0.0
    return v_silent + max(0.0, w) * (v_full - v_silent)


# ---------------------------------------------------------------------------
# apply_pressure — all 5 behaviors
# ---------------------------------------------------------------------------

def apply_pressure(
    stage: StageParams, behavior: PressureBehavior, pressure: float
) -> StageParams:
    p = max(0.0, min(1.0, pressure))

    if behavior == PressureBehavior.HOLD:
        return stage

    elif behavior == PressureBehavior.TIGHTEN:
        r_boost = p * 0.015
        gain_boost = p * 0.2
        new_r = min(stage.r + r_boost, 0.998)
        freq = stage.freq_hz()
        theta = TWO_PI * freq / SR
        new_a1 = -2.0 * new_r * math.cos(theta)
        new_val1 = min(stage.val1 + gain_boost, -0.05)
        return StageParams(
            a1=new_a1, r=new_r, val1=new_val1,
            val2=stage.val2, val3=stage.val3,
        )

    elif behavior == PressureBehavior.YIELD:
        r_drop = p * 0.10
        gain_drop = p * 0.3
        new_r = max(stage.r - r_drop, 0.5)
        freq = stage.freq_hz()
        theta = TWO_PI * freq / SR
        new_a1 = -2.0 * new_r * math.cos(theta)
        new_val1 = max(stage.val1 - gain_drop, -0.95)
        return StageParams(
            a1=new_a1, r=new_r, val1=new_val1,
            val2=stage.val2, val3=stage.val3,
        )

    elif behavior == PressureBehavior.CROSS:
        freq = stage.freq_hz()
        mid = (math.log(20.0) + math.log(14000.0)) / 2.0
        direction = 1.0 if math.log(max(freq, 1e-6)) < mid else -1.0
        shift_st = p * 12.0 * direction
        new_freq = max(20.0, min(SR * 0.48, freq * 2.0 ** (shift_st / 12.0)))
        theta = TWO_PI * new_freq / SR
        new_a1 = -2.0 * stage.r * math.cos(theta)
        return StageParams(
            a1=new_a1, r=stage.r, val1=stage.val1,
            val2=stage.val2, val3=stage.val3,
        )

    elif behavior == PressureBehavior.COLLAPSE:
        new_r = max(stage.r - p * 0.3, 0.3)
        new_val1 = max(stage.val1 - p * 0.5, -0.95)
        freq = stage.freq_hz()
        theta = TWO_PI * freq / SR
        new_a1 = -2.0 * new_r * math.cos(theta)
        new_val2 = p * 0.5
        new_val3 = new_r * new_r - (1.0 - p * 0.3)
        return StageParams(
            a1=new_a1, r=new_r, val1=new_val1,
            val2=new_val2, val3=new_val3,
        )

    return stage


# ---------------------------------------------------------------------------
# compile_slot_at — resolve one slot at a given state and pressure
# ---------------------------------------------------------------------------

def compile_slot_at(
    spec: SlotSpec, state: SlotState, pressure: float
) -> CompiledSlot:
    # Zero-weight slots compile to passthrough (not zero-gain resonators).
    # In a serial cascade, a zero-numerator stage kills the entire signal.
    if state.weight <= 0.0:
        return CompiledSlot(primary=StageParams.passthrough(), secondary=None)

    freq = place_to_freq(spec.actor, state.place)
    radius = focus_to_radius(state.focus)
    val1 = weight_to_val1(state.weight)
    theta = TWO_PI * freq / SR
    a1 = -2.0 * radius * math.cos(theta)

    # Resolve contour: override takes priority
    family = (
        state.contour_override
        if state.contour_override is not None
        else resolve_contour(state.contour, state.color, state.hue, a1, radius)
    )
    val2, val3 = family.val2_val3(a1, radius)

    if spec.compile_macro == CompileMacro.SINGLE:
        primary = stage_math.resonator(freq, radius, val1)
        primary = StageParams(
            a1=primary.a1, r=primary.r, val1=primary.val1,
            val2=val2, val3=val3,
        )
        primary = apply_pressure(primary, spec.pressure, pressure)
        return CompiledSlot(primary=primary, secondary=None)
    else:
        raise NotImplementedError(
            f"CompileMacro.{spec.compile_macro.name} not yet implemented"
        )


# ---------------------------------------------------------------------------
# compile_body — full 4-corner compilation
# ---------------------------------------------------------------------------

def compile_body(spec: BodySpec) -> CornerArray:
    corner_states = []

    for cn in CornerName:
        morph = cn.morph()
        pressure = cn.q()

        # Blend states by morph
        blended = []
        for slot in spec.slots:
            contour = (
                slot.state_a.contour if morph < 0.5 else slot.state_b.contour
            )
            contour_override = (
                slot.state_a.contour_override
                if morph < 0.5
                else slot.state_b.contour_override
            )
            blended.append(SlotState(
                place=slot.state_a.place + morph * (slot.state_b.place - slot.state_a.place),
                focus=slot.state_a.focus + morph * (slot.state_b.focus - slot.state_a.focus),
                weight=slot.state_a.weight + morph * (slot.state_b.weight - slot.state_a.weight),
                color=slot.state_a.color + morph * (slot.state_b.color - slot.state_a.color),
                hue=slot.state_a.hue + morph * (slot.state_b.hue - slot.state_a.hue),
                contour=contour,
                contour_override=contour_override,
            ))

        stages: list[StageParams] = [StageParams.passthrough()] * NUM_BODY_STAGES
        stage_idx = 0

        for i, slot in enumerate(spec.slots):
            compiled = compile_slot_at(slot, blended[i], pressure)
            if stage_idx < NUM_BODY_STAGES:
                stages[stage_idx] = compiled.primary
                stage_idx += 1
            if compiled.secondary is not None and stage_idx < NUM_BODY_STAGES:
                stages[stage_idx] = compiled.secondary
                stage_idx += 1

        corner_states.append(CornerState(stages=stages, boost=spec.boost))

    return CornerArray(
        a=corner_states[0], b=corner_states[1],
        c=corner_states[2], d=corner_states[3],
    )
