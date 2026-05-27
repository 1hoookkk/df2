"""Sonic table targeting: formant -> slot -> compile.

Maps acoustic vocabulary (vowels, nasals, landmarks) to the SINGLE macro
compiler pipeline. Formant frequencies assign to Actor slots via best-fit
frequency matching. The proved zero-family path handles all numerator shaping.

Transcribed from runtime/src/target.rs.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from pyruntime.macro_compile import (
    Actor,
    BodySpec,
    CompileMacro,
    PressureBehavior,
    SlotSpec,
    SlotState,
    compile_body,
    freq_to_place,
)
from pyruntime.zero_law import ContourKind
from pyruntime.corner import CornerArray

TABLES_PATH = Path(__file__).parent.parent / "docs" / "sonic_tables" / "tables.json"

_cached_tables: dict | None = None


def load_sonic_tables() -> dict:
    """Load the sonic tables JSON. Cached after first call."""
    global _cached_tables
    if _cached_tables is not None:
        return _cached_tables
    with open(TABLES_PATH) as f:
        _cached_tables = json.load(f)
    return _cached_tables


def get_vowel_keys() -> list[str]:
    """Return all vowel slugs from the sonic tables."""
    tables = load_sonic_tables()
    return list(tables["vowels"].keys())


def get_nasal_keys() -> list[str]:
    tables = load_sonic_tables()
    return list(tables["nasals"].keys())


def get_landmark_names() -> list[str]:
    tables = load_sonic_tables()
    return [e["name"] for e in tables["landmarks"]["entries"]]


def assign_formant_to_actor(
    freq_hz: float, start_idx: int = 0
) -> tuple[int, Actor] | None:
    """Find the best-fit Actor for a formant frequency.

    Greedy forward scan from start_idx. Returns (actor_index, Actor) or None.
    Matches the Rust target.rs assignment strategy exactly.
    """
    for idx in range(start_idx, 6):
        actor = Actor.ALL[idx]
        if freq_hz >= actor.freq_floor() and freq_hz <= actor.freq_ceiling():
            return (idx, actor)
    # Fallback: assign to start_idx if no range match
    if start_idx < 6:
        return (start_idx, Actor.ALL[start_idx])
    return None


def _empty_slot(actor: Actor) -> SlotSpec:
    state = SlotState(
        place=0.5,
        focus=0.0,
        weight=0.0,
        contour=ContourKind.PURE,
        color=0.0,
        hue=0.0,
        contour_override=None,
    )
    return SlotSpec(
        actor=actor,
        state_a=state,
        state_b=state,
        pressure=PressureBehavior.HOLD,
        compile_macro=CompileMacro.SINGLE,
        spread=0.0,
    )


_ACTOR_CONTOUR = {
    Actor.FOUNDATION: (ContourKind.PURE, 0.0),          # all-pole anchor
    Actor.MASS: (ContourKind.NEAR_ALLPASS, 0.3),         # subtle shaping
    Actor.THROAT: (ContourKind.INTERIOR_ZERO, 0.5),      # deep numerator — character
    Actor.BITE: (ContourKind.UNIT_CIRCLE, 0.6),           # on-circle nulls — presence
    Actor.AIR: (ContourKind.INTERIOR_ZERO, 0.4),          # pulled zeros — shimmer
    Actor.SCAR: (ContourKind.UNIT_CIRCLE, 0.0),           # on-circle — boundary null
}


def _make_formant_slot(actor: Actor, freq_hz: float, weight: float) -> SlotSpec:
    """Map a formant frequency to a SlotSpec.

    Place: normalized position within actor range (log-frequency).
    Focus: 0.97 → r=0.978 (P2K-calibrated — Talking Hedz runs 0.947-0.997).
    Weight: passed through (P2K shared val1=-0.438 ≈ weight 0.66).
    Contour: per-Actor — Foundation=Pure, Throat/Air=InteriorZero, Bite/Scar=UnitCircle.
    Pressure: Tighten (formants narrow and intensify under Q).
    """
    place = freq_to_place(actor, freq_hz)
    contour, color = _ACTOR_CONTOUR.get(actor, (ContourKind.UNIT_CIRCLE, 0.5))
    state = SlotState(
        place=place,
        focus=0.97,
        weight=weight,
        contour=contour,
        color=color,
        hue=0.0,
        contour_override=None,
    )
    return SlotSpec(
        actor=actor,
        state_a=state,
        state_b=state,
        pressure=PressureBehavior.TIGHTEN,
        compile_macro=CompileMacro.SINGLE,
        spread=0.0,
    )


def _make_antiformant_slot(actor: Actor, freq_hz: float, weight: float) -> SlotSpec:
    """Map an anti-formant (nasal zero) to a SlotSpec.

    Uses UnitCircle contour with zero co-located at the anti-formant frequency.
    The zero cancels energy at the target frequency — this is the nasal anti-resonance.
    Focus 0.95 (r=0.965) — anti-formants need sharp poles to create deep nulls.
    """
    place = freq_to_place(actor, freq_hz)
    state = SlotState(
        place=place,
        focus=0.95,
        weight=weight,
        contour=ContourKind.UNIT_CIRCLE,
        color=0.0,  # zero exactly on unit circle
        hue=0.0,    # zero co-located with pole
        contour_override=None,
    )
    return SlotSpec(
        actor=actor,
        state_a=state,
        state_b=state,
        pressure=PressureBehavior.HOLD,
        compile_macro=CompileMacro.SINGLE,
        spread=0.0,
    )


def build_vowel_target(name: str, vowel_key: str) -> BodySpec:
    """Build a BodySpec from a vowel's formant frequencies.

    Assigns F1-F4 to Actor slots via greedy forward scan. Higher formants
    get slightly lower weight (natural spectral rolloff).
    """
    tables = load_sonic_tables()
    vowel = tables["vowels"][vowel_key]

    slots = [_empty_slot(a) for a in Actor.ALL]

    formants = [
        vowel.get("f1"),
        vowel.get("f2"),
        vowel.get("f3"),
        vowel.get("f4"),
    ]

    current_idx = 0
    for fi, f in enumerate(formants):
        if f is None:
            continue
        f = float(f)
        result = assign_formant_to_actor(f, start_idx=current_idx)
        if result is not None:
            idx, actor = result
            weight = 0.66 - (fi * 0.05)  # P2K-calibrated: shared val1=-0.438
            slots[idx] = _make_formant_slot(actor, f, weight)
            current_idx = idx + 1

    return BodySpec(name=name, slots=slots, boost=4.0)


def build_nasal_target(name: str, nasal_key: str) -> BodySpec:
    """Build a BodySpec from a nasal's formants and anti-formants.

    Nasals have both formant poles (f1, f2) and anti-formant zeros (anti1, anti2).
    Anti-formants produce deep notches — the nasal cavity's signature.
    """
    tables = load_sonic_tables()
    nasal = tables["nasals"][nasal_key]

    slots = [_empty_slot(a) for a in Actor.ALL]
    current_idx = 0

    # Place formant poles first
    for key in ["f1", "f2"]:
        f = nasal.get(key)
        if f is None:
            continue
        f = float(f)
        result = assign_formant_to_actor(f, start_idx=current_idx)
        if result is not None:
            idx, actor = result
            slots[idx] = _make_formant_slot(actor, f, 0.66)
            current_idx = idx + 1

    # Place anti-formant zeros
    for key in ["anti1", "anti2"]:
        f = nasal.get(key)
        if f is None:
            continue
        f = float(f)
        result = assign_formant_to_actor(f, start_idx=current_idx)
        if result is not None:
            idx, actor = result
            slots[idx] = _make_antiformant_slot(actor, f, 0.60)
            current_idx = idx + 1

    return BodySpec(name=name, slots=slots, boost=4.0)


def build_landmark_target(name: str, landmark_name: str) -> BodySpec:
    """Build a BodySpec from a single named landmark frequency.

    Places one formant slot at the landmark frequency. If the landmark
    has a bandwidth, uses it to set focus.
    """
    tables = load_sonic_tables()
    entries = tables["landmarks"]["entries"]
    entry = None
    for e in entries:
        if e["name"] == landmark_name:
            entry = e
            break
    if entry is None:
        raise ValueError(f"Landmark '{landmark_name}' not found in sonic tables")

    freq_hz = float(entry["freq_hz"])
    bw_hz = entry.get("bw_hz")

    slots = [_empty_slot(a) for a in Actor.ALL]
    result = assign_formant_to_actor(freq_hz, start_idx=0)
    if result is not None:
        idx, actor = result
        slot = _make_formant_slot(actor, freq_hz, 0.80)
        # If bandwidth is given, map it to focus (narrower bw = higher focus)
        if bw_hz is not None:
            # Approximate: bw_hz maps inversely to focus
            # 20 Hz bw → focus~0.95 (very narrow), 500 Hz bw → focus~0.4 (broad)
            focus = max(0.2, min(0.95, 1.0 - float(bw_hz) / 600.0))
            state = SlotState(
                place=slot.state_a.place,
                focus=focus,
                weight=slot.state_a.weight,
                contour=slot.state_a.contour,
                color=slot.state_a.color,
                hue=slot.state_a.hue,
                contour_override=None,
            )
            slot = SlotSpec(
                actor=actor,
                state_a=state,
                state_b=state,
                pressure=PressureBehavior.TIGHTEN,
                compile_macro=CompileMacro.SINGLE,
                spread=0.0,
            )
        slots[idx] = slot

    return BodySpec(name=name, slots=slots, boost=4.0)


def compile_sonic_target(name: str, vowel_key: str) -> CornerArray:
    """Full pipeline: vowel key -> BodySpec -> CornerArray."""
    spec = build_vowel_target(name, vowel_key)
    return compile_body(spec)


# ---------------------------------------------------------------------------
# Helpers — key listing and formant extraction
# ---------------------------------------------------------------------------


def get_bell_names() -> list[str]:
    """Return all bell names from measured_bells in sonic tables."""
    tables = load_sonic_tables()
    return [b["name"] for b in tables["measured_bells"]]


def get_electronic_keys() -> list[str]:
    """Return all electronic preset keys from sonic tables."""
    tables = load_sonic_tables()
    return list(tables["electronic"].keys())


def _extract_vowel_formants(vowel_key: str) -> list[tuple[float, float]]:
    """Extract (freq_hz, weight) pairs from a vowel entry.

    Returns F1-F4 with descending weight (natural spectral rolloff).
    """
    tables = load_sonic_tables()
    vowel = tables["vowels"][vowel_key]
    formants = []
    for i, key in enumerate(["f1", "f2", "f3", "f4"]):
        f = vowel.get(key)
        if f is not None:
            weight = 0.85 - (i * 0.1)
            formants.append((float(f), weight))
    return formants


def _extract_nasal_formants(nasal_key: str) -> list[tuple[float, float]]:
    """Extract (freq_hz, weight) pairs from a nasal entry.

    Returns formant poles (f1, f2) AND anti-formant zeros (anti1, anti2).
    Anti-formants get the same weight — the contour family handles the
    zero placement. Without them, nasal bodies have no notches.
    """
    tables = load_sonic_tables()
    nasal = tables["nasals"][nasal_key]
    formants = []
    for key in ["f1", "f2", "anti1", "anti2"]:
        f = nasal.get(key)
        if f is not None:
            formants.append((float(f), 0.80))
    return formants


def _extract_landmark_formants(landmark_name: str) -> list[tuple[float, float]]:
    """Extract (freq_hz, weight) pair from a single landmark."""
    tables = load_sonic_tables()
    for e in tables["landmarks"]["entries"]:
        if e["name"] == landmark_name:
            return [(float(e["freq_hz"]), 0.80)]
    raise ValueError(f"Landmark '{landmark_name}' not found in sonic tables")


def _extract_bell_formants(bell_key: str) -> list[tuple[float, float]]:
    """Extract (freq_hz, weight) pairs from a measured bell's partials."""
    tables = load_sonic_tables()
    for b in tables["measured_bells"]:
        if b["name"] == bell_key:
            formants = []
            for i, p in enumerate(b["partials"]):
                weight = max(0.3, 0.80 - (i * 0.1))
                formants.append((float(p), weight))
            return formants
    raise ValueError(f"Bell '{bell_key}' not found in sonic tables")


def _extract_electronic_formants(elec_key: str) -> list[tuple[float, float]]:
    """Extract (freq_hz, weight) for an electronic entry.

    Returns only freq_start. For sweep behavior (freq_start → freq_end),
    use build_electronic_target directly — it handles both endpoints
    as state_a/state_b within a single slot.
    """
    tables = load_sonic_tables()
    entry = tables["electronic"][elec_key]
    return [(float(entry["freq_start"]), 0.75)]


def _extract_formants(source: str, key: str) -> list[tuple[float, float]]:
    """Dispatch formant extraction by source type."""
    if source == "vowel":
        return _extract_vowel_formants(key)
    elif source == "nasal":
        return _extract_nasal_formants(key)
    elif source == "landmark":
        return _extract_landmark_formants(key)
    elif source == "bell":
        return _extract_bell_formants(key)
    elif source == "electronic":
        return _extract_electronic_formants(key)
    else:
        raise ValueError(f"Unknown source type: {source}")


# ---------------------------------------------------------------------------
# Bell target builder
# ---------------------------------------------------------------------------


def build_bell_target(name: str, bell_key: str) -> BodySpec:
    """Build a BodySpec from a measured bell's partials.

    Bell partials are narrow resonances (high focus). PURE contour — clean
    poles with no zero shaping. HOLD pressure — bells ring at fixed pitch.
    State_a == state_b: bells are static in morph.
    """
    tables = load_sonic_tables()
    bell = None
    for b in tables["measured_bells"]:
        if b["name"] == bell_key:
            bell = b
            break
    if bell is None:
        raise ValueError(f"Bell '{bell_key}' not found in sonic tables")

    slots = [_empty_slot(a) for a in Actor.ALL]
    current_idx = 0

    for i, partial_hz in enumerate(bell["partials"]):
        partial_hz = float(partial_hz)
        result = assign_formant_to_actor(partial_hz, start_idx=current_idx)
        if result is not None:
            idx, actor = result
            place = freq_to_place(actor, partial_hz)
            weight = max(0.3, 0.80 - (i * 0.1))
            state = SlotState(
                place=place,
                focus=0.85,
                weight=weight,
                contour=ContourKind.PURE,
                color=0.0,
                hue=0.0,
                contour_override=None,
            )
            slots[idx] = SlotSpec(
                actor=actor,
                state_a=state,
                state_b=state,
                pressure=PressureBehavior.HOLD,
                compile_macro=CompileMacro.SINGLE,
                spread=0.0,
            )
            current_idx = idx + 1

    return BodySpec(name=name, slots=slots, boost=4.0)


# ---------------------------------------------------------------------------
# Electronic target builder
# ---------------------------------------------------------------------------


def build_electronic_target(name: str, key: str) -> BodySpec:
    """Build a sweep body from an electronic entry.

    State_a places resonance at freq_start, state_b at freq_end — the morph
    axis IS the sweep. Single slot, tight resonance, UNIT_CIRCLE contour,
    TIGHTEN pressure.
    """
    tables = load_sonic_tables()
    entry = tables["electronic"][key]
    freq_start = float(entry["freq_start"])
    freq_end = float(entry["freq_end"])

    slots = [_empty_slot(a) for a in Actor.ALL]

    # Find an actor that can host both endpoints (or at least freq_start)
    result_a = assign_formant_to_actor(freq_start, start_idx=0)
    if result_a is None:
        return BodySpec(name=name, slots=slots, boost=4.0)

    idx, actor = result_a
    place_a = freq_to_place(actor, freq_start)

    # Place freq_end in same actor if possible, otherwise clamp to 0/1
    ceil = actor.freq_ceiling()
    floor = actor.freq_floor()
    if freq_end >= floor and freq_end <= ceil:
        place_b = freq_to_place(actor, freq_end)
    else:
        # freq_end outside this actor's range — clamp place to boundary
        place_b = 1.0 if freq_end > ceil else 0.0

    state_a = SlotState(
        place=place_a,
        focus=0.80,
        weight=0.75,
        contour=ContourKind.UNIT_CIRCLE,
        color=0.2,
        hue=0.0,
        contour_override=None,
    )
    state_b = SlotState(
        place=place_b,
        focus=0.80,
        weight=0.75,
        contour=ContourKind.UNIT_CIRCLE,
        color=0.2,
        hue=0.0,
        contour_override=None,
    )
    slots[idx] = SlotSpec(
        actor=actor,
        state_a=state_a,
        state_b=state_b,
        pressure=PressureBehavior.TIGHTEN,
        compile_macro=CompileMacro.SINGLE,
        spread=0.0,
    )

    return BodySpec(name=name, slots=slots, boost=4.0)


# ---------------------------------------------------------------------------
# Morph target builder
# ---------------------------------------------------------------------------


def _spread_fill(candidates: list[tuple[float, float, str]], n: int = 6) -> list[tuple[float, float, str]]:
    """Pick n targets from candidates maximizing log-frequency spread.

    Claim the spectrum first, beautify second. Greedy selection:
    each pick maximizes minimum log-distance to already-chosen targets.
    First pick = highest salience (weight). Rest = coverage.

    candidates: [(freq_hz, weight, side_tag), ...]
    Returns: up to n selected candidates, spread across the spectrum.
    """
    if not candidates or n <= 0:
        return []
    if len(candidates) <= n:
        return candidates

    log_freqs = [math.log(max(f, 1.0)) for f, _, _ in candidates]

    # First pick: highest weight (most salient)
    chosen_indices = [max(range(len(candidates)), key=lambda i: candidates[i][1])]

    for _ in range(n - 1):
        chosen_logs = [log_freqs[i] for i in chosen_indices]
        best_idx = -1
        best_score = -1.0

        for i in range(len(candidates)):
            if i in chosen_indices:
                continue
            # Min log-distance to any already-chosen target
            min_dist = min(abs(log_freqs[i] - cl) for cl in chosen_logs)
            # Score = spread reward + salience bonus
            score = min_dist + 0.3 * candidates[i][1]
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx < 0:
            break
        chosen_indices.append(best_idx)

    # Return in frequency order
    chosen_indices.sort(key=lambda i: candidates[i][0])
    return [candidates[i] for i in chosen_indices]


def build_morph_target(
    name: str,
    source_a: str, key_a: str,
    source_b: str, key_b: str,
    mode: str = "spread",
) -> BodySpec:
    """Build a morphing body from two source/key pairs.

    The morph axis traverses between two acoustic identities.

    mode="spread": spread-fill allocation (claim spectrum first)
    mode="greedy": legacy greedy-pack (dense vocal clusters)

    Strategy: collect all formant frequencies from BOTH sources, deduplicate
    nearby frequencies (within same actor band) into unified positions, assign
    those positions to actors via greedy forward scan, then populate state_a
    and state_b independently from the nearest formant each side offers.
    A side with no formant near a position gets weight=0 (silent at that slot).
    """
    formants_a = _extract_formants(source_a, key_a)
    formants_b = _extract_formants(source_b, key_b)

    # Step 1: Collect all unique frequency positions from both sources.
    all_freqs = sorted(
        [(f, w, "a") for f, w in formants_a]
        + [(f, w, "b") for f, w in formants_b],
        key=lambda t: t[0],
    )

    # Spread-fill: thin to 6 most spread candidates when surplus exists
    if mode == "spread" and len(all_freqs) > 6:
        all_freqs = _spread_fill(all_freqs, n=6)

    # Group nearby frequencies (within 15% ratio) into a single position
    # using the average, so both sides can share the same actor slot.
    positions = []  # list of {"freq": float, "a": (freq, weight)|None, "b": ...}
    for freq, weight, side in all_freqs:
        merged = False
        for pos in positions:
            ratio = freq / pos["freq"] if pos["freq"] > 0 else 999
            if 0.87 < ratio < 1.15 and pos[side] is None:
                # Close enough and this side hasn't claimed this position yet
                pos[side] = (freq, weight)
                # Update position centroid
                other = "b" if side == "a" else "a"
                if pos[other] is not None:
                    pos["freq"] = (pos["a"][0] + pos["b"][0]) / 2.0
                else:
                    pos["freq"] = freq
                merged = True
                break
        if not merged:
            pos = {"freq": freq, "a": None, "b": None}
            pos[side] = (freq, weight)
            positions.append(pos)

    # Sort positions by frequency
    positions.sort(key=lambda p: p["freq"])

    # Step 2: Assign each position to an actor via greedy forward scan
    slots = [_empty_slot(a) for a in Actor.ALL]
    current_idx = 0

    for pos in positions:
        result = assign_formant_to_actor(pos["freq"], start_idx=current_idx)
        if result is None:
            continue
        idx, actor = result

        # State A
        if pos["a"] is not None:
            a_freq, a_weight = pos["a"]
            a_place = freq_to_place(actor, a_freq)
        else:
            a_place = 0.5
            a_weight = 0.0

        # State B
        if pos["b"] is not None:
            b_freq, b_weight = pos["b"]
            b_place = freq_to_place(actor, b_freq)
        else:
            b_place = 0.5
            b_weight = 0.0

        contour, color = _ACTOR_CONTOUR.get(actor, (ContourKind.UNIT_CIRCLE, 0.5))
        state_a = SlotState(
            place=a_place,
            focus=0.97,
            weight=a_weight,
            contour=contour,
            color=color,
            hue=0.0,
            contour_override=None,
        )
        state_b = SlotState(
            place=b_place,
            focus=0.97,
            weight=b_weight,
            contour=contour,
            color=color,
            hue=0.0,
            contour_override=None,
        )
        slots[idx] = SlotSpec(
            actor=actor,
            state_a=state_a,
            state_b=state_b,
            pressure=PressureBehavior.TIGHTEN,
            compile_macro=CompileMacro.SINGLE,
            spread=0.0,
        )
        current_idx = idx + 1

    return BodySpec(name=name, slots=slots, boost=4.0)


# ---------------------------------------------------------------------------
# Composite target builder
# ---------------------------------------------------------------------------


def build_composite_target(name: str, slot_defs: list[dict]) -> BodySpec:
    """Build a body from per-slot independent formant assignments.

    Each slot_def = {
        "source": "vowel"|"nasal"|"landmark"|"bell"|"electronic",
        "key": str,
        "formant_index": int,   # which formant from that source (0-based)
        "pressure": str         # optional, defaults by source type
    }

    Up to 6 slot_defs (one per actor). State_a == state_b — composite bodies
    are placement tools, morph comes from morph_target.
    """
    if len(slot_defs) > 6:
        raise ValueError(f"Too many slot_defs ({len(slot_defs)}), max 6")

    # Pre-resolve frequencies and sort ascending for greedy actor assignment
    resolved = []
    for sdef in slot_defs:
        formants = _extract_formants(sdef["source"], sdef["key"])
        fi = sdef.get("formant_index", 0)
        if fi < len(formants):
            resolved.append((formants[fi][0], sdef))
    resolved.sort(key=lambda x: x[0])

    slots = [_empty_slot(a) for a in Actor.ALL]
    current_idx = 0

    for _freq_sort_key, sdef in resolved:
        source = sdef["source"]
        key = sdef["key"]
        fi = sdef.get("formant_index", 0)

        formants = _extract_formants(source, key)
        if fi >= len(formants):
            continue  # requested formant index doesn't exist, skip

        freq, weight = formants[fi]

        # Pressure defaults: HOLD for bell/electronic, TIGHTEN for vocal
        pressure_str = sdef.get("pressure")
        if pressure_str is not None:
            pressure = PressureBehavior(pressure_str.capitalize())
        elif source in ("bell", "electronic"):
            pressure = PressureBehavior.HOLD
        else:
            pressure = PressureBehavior.TIGHTEN

        result = assign_formant_to_actor(freq, start_idx=current_idx)
        if result is None:
            continue

        idx, actor = result
        place = freq_to_place(actor, freq)
        # Source-appropriate acoustic parameters
        if source == "bell":
            contour, focus, color = ContourKind.PURE, 0.85, 0.0
        else:
            contour, focus, color = ContourKind.UNIT_CIRCLE, 0.75, 0.2
        state = SlotState(
            place=place,
            focus=focus,
            weight=weight,
            contour=contour,
            color=color,
            hue=0.0,
            contour_override=None,
        )
        slots[idx] = SlotSpec(
            actor=actor,
            state_a=state,
            state_b=state,
            pressure=pressure,
            compile_macro=CompileMacro.SINGLE,
            spread=0.0,
        )
        current_idx = idx + 1

    return BodySpec(name=name, slots=slots, boost=4.0)
