"""Pure four-corner pole-zero trajectory programs.

This module owns clean-room mathematical construction only. It does not search,
score, log, export, inspect ROM bytes, or write files.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import random
from typing import Any

AUTHORING_SR = 39_062.5
LABELS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
LABEL_TO_POINT = {
    "M0_Q0": (0.0, 0.0),
    "M100_Q0": (1.0, 0.0),
    "M0_Q100": (0.0, 1.0),
    "M100_Q100": (1.0, 1.0),
}


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _geo(a: float, b: float, amount: float) -> float:
    return float(a) * (float(b) / float(a)) ** float(amount)


def _snap_12tet(hz: float, ref: float = 440.0) -> float:
    """Snap a frequency to the nearest 12-TET note (A440 grid) — a landing pitch."""
    if hz <= 0.0:
        return hz
    return ref * 2.0 ** (round(12.0 * math.log2(hz / ref)) / 12.0)


def _kernel_from_biquad(b0: float, b1: float, b2: float, a1: float, a2: float) -> tuple[float, ...]:
    if b0 <= 1.0e-12:
        raise ValueError("biquad b0 must be positive")
    return (b1 / b0 + 2.0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0)


def _actor_kernel(pole_hz: float, pole_radius: float, zero_hz: float, zero_radius: float) -> tuple[float, ...]:
    wp = 2.0 * math.pi * pole_hz / AUTHORING_SR
    wz = 2.0 * math.pi * zero_hz / AUTHORING_SR
    a1, a2 = -2.0 * pole_radius * math.cos(wp), pole_radius * pole_radius
    z1, z2 = -2.0 * zero_radius * math.cos(wz), zero_radius * zero_radius
    gain = (1.0 + a1 + a2) / max(1.0 + z1 + z2, 1.0e-9)
    return (2.0 + z1, 1.0 - z2, 2.0 + a1, 1.0 - a2, gain)


def _rbj_lowpass(freq_hz: float, q: float) -> tuple[float, ...]:
    w0 = 2.0 * math.pi * freq_hz / AUTHORING_SR
    alpha, cw = math.sin(w0) / (2.0 * q), math.cos(w0)
    b0, b1, b2 = (1.0 - cw) / 2.0, 1.0 - cw, (1.0 - cw) / 2.0
    a0, a1, a2 = 1.0 + alpha, -2.0 * cw, 1.0 - alpha
    return _kernel_from_biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def _rbj_shelf(freq_hz: float, gain_db: float, *, high: bool) -> tuple[float, ...]:
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq_hz / AUTHORING_SR
    cw, sw = math.cos(w0), math.sin(w0)
    root = math.sqrt(2.0 * a) * sw
    if high:
        b0 = a * ((a + 1.0) + (a - 1.0) * cw + root)
        b1 = -2.0 * a * ((a - 1.0) + (a + 1.0) * cw)
        b2 = a * ((a + 1.0) + (a - 1.0) * cw - root)
        a0 = (a + 1.0) - (a - 1.0) * cw + root
        a1 = 2.0 * ((a - 1.0) - (a + 1.0) * cw)
        a2 = (a + 1.0) - (a - 1.0) * cw - root
    else:
        b0 = a * ((a + 1.0) - (a - 1.0) * cw + root)
        b1 = 2.0 * a * ((a - 1.0) - (a + 1.0) * cw)
        b2 = a * ((a + 1.0) - (a - 1.0) * cw - root)
        a0 = (a + 1.0) + (a - 1.0) * cw + root
        a1 = -2.0 * ((a - 1.0) + (a + 1.0) * cw)
        a2 = (a + 1.0) + (a - 1.0) * cw - root
    return _kernel_from_biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def _rbj_peaking(freq_hz: float, gain_db: float, q: float) -> tuple[float, ...]:
    """RBJ peaking EQ bell — flat both ends, a clean boost/cut at freq. Serial-cascade safe."""
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq_hz / AUTHORING_SR
    alpha, cw = math.sin(w0) / (2.0 * max(q, 1e-3)), math.cos(w0)
    b0, b1, b2 = 1.0 + alpha * a, -2.0 * cw, 1.0 - alpha * a
    a0, a1, a2 = 1.0 + alpha / a, -2.0 * cw, 1.0 - alpha / a
    return _kernel_from_biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


@dataclass(frozen=True)
class StageTrajectory:
    kind: str
    pole_start_hz: float = 1000.0
    pole_end_hz: float = 1000.0
    zero_start_hz: float = 1000.0
    zero_end_hz: float = 1000.0
    secondary_pole_octaves: float = 0.0
    secondary_zero_octaves: float = 0.0
    pole_radius_q0: float = 0.98
    pole_radius_q100: float = 0.999
    zero_radius_q0: float = 0.97
    zero_radius_q100: float = 0.999
    section_q: float = 0.70711
    gain_start_db: float = 0.0
    gain_end_db: float = 0.0
    secondary_gain_db: float = 0.0

    def kernel(self, morph: float, secondary: float) -> tuple[float, ...]:
        pole_hz = _geo(self.pole_start_hz, self.pole_end_hz, morph)
        pole_hz *= 2.0 ** (self.secondary_pole_octaves * secondary)
        pole_hz = _clip(pole_hz, 35.0, 17_500.0)
        if self.kind == "actor":
            zero_hz = _geo(self.zero_start_hz, self.zero_end_hz, morph)
            zero_hz *= 2.0 ** (self.secondary_zero_octaves * secondary)
            zero_hz = _clip(zero_hz, 35.0, 17_500.0)
            pole_radius = self.pole_radius_q0 + (self.pole_radius_q100 - self.pole_radius_q0) * secondary
            zero_radius = self.zero_radius_q0 + (self.zero_radius_q100 - self.zero_radius_q0) * secondary
            return _actor_kernel(
                pole_hz, _clip(pole_radius, 0.10, 0.99985),
                zero_hz, _clip(zero_radius, 0.10, 0.99999))
        if self.kind == "lowpass":
            return _rbj_lowpass(pole_hz, self.section_q)
        gain_db = self.gain_start_db + (self.gain_end_db - self.gain_start_db) * morph
        gain_db += self.secondary_gain_db * secondary
        if self.kind == "peaking":
            return _rbj_peaking(pole_hz, gain_db, self.section_q)
        if self.kind == "highshelf":
            return _rbj_shelf(pole_hz, gain_db, high=True)
        if self.kind == "lowshelf":
            return _rbj_shelf(pole_hz, gain_db, high=False)
        raise ValueError(f"unsupported stage kind: {self.kind}")

@dataclass(frozen=True)
class ProgramGenome:
    family: str
    seed: int
    stages: tuple[StageTrajectory, ...]
    specialist: str | None = None

    def __post_init__(self) -> None:
        if len(self.stages) != 6:
            raise ValueError(f"a DF2 program requires exactly 6 indexed stages, got {len(self.stages)}")

    def corner_kernels(self) -> dict[str, list[tuple[float, ...]]]:
        return {
            label: [stage.kernel(*LABEL_TO_POINT[label]) for stage in self.stages]
            for label in LABELS
        }

    def to_dict(self) -> dict[str, Any]:
        return {"family": self.family, "specialist": self.specialist, "seed": self.seed,
                "stages": [asdict(stage) for stage in self.stages]}


def _range(cfg: Any, key: str) -> tuple[float, float]:
    values = cfg[key]
    return float(values[0]), float(values[1])


def _range_or(primary: Any, fallback: Any, key: str) -> tuple[float, float]:
    return _range(primary, key) if key in primary else _range(fallback, key)


def _bounded_freq(value: float, cfg: Any) -> float:
    lo, hi = _range(cfg, "frequency_hz")
    return _clip(value, lo, hi)


def _random_actor(rng: random.Random, cfg: Any, base_hz: float, index: int, *,
                  contrary: bool, local: bool = False, profile: Any | None = None,
                  direction: float | None = None) -> StageTrajectory:
    profile = cfg if profile is None else profile
    motion_lo, motion_hi = _range_or(profile, cfg, "morph_motion_octaves")
    zero_lo, zero_hi = _range_or(profile, cfg, "zero_counter_motion_octaves")
    shift_lo, shift_hi = _range_or(profile, cfg, "secondary_shift_octaves")
    direction = (-1.0 if index % 2 else 1.0) if direction is None else float(direction)
    pole_move = direction * rng.uniform(motion_lo, motion_hi)
    zero_move = (-direction if contrary else direction) * rng.uniform(zero_lo, zero_hi)
    offset = rng.uniform(*_range(cfg, "local_zero_offset_octaves" if local else "global_zero_offset_octaves"))
    land = bool(cfg.get("land_peaks_on_notes", False))
    p0 = _bounded_freq(base_hz, cfg)
    if land:
        p0 = _bounded_freq(_snap_12tet(p0), cfg)        # Frame A peak lands on a note
    pend = _bounded_freq(p0 * 2.0 ** pole_move, cfg)
    if land:
        pend = _bounded_freq(_snap_12tet(pend), cfg)    # Frame B peak lands on a note
    z0 = _bounded_freq(p0 * 2.0 ** offset, cfg)
    pr0 = rng.uniform(*_range(cfg, "pole_radius_q0"))
    pr1 = rng.uniform(*_range(cfg, "pole_radius_q100"))
    zr0 = rng.uniform(*_range(cfg, "zero_radius_q0"))
    zr1 = rng.uniform(*_range(cfg, "zero_radius_q100"))
    # land=True => Q is radius-ONLY (no pole-freq shift) so every parked position
    # stays on its note; the morph glides (portamento) between the two landing notes.
    sec_pole = 0.0 if land else rng.uniform(-shift_hi, shift_hi) * float(
        profile.get("secondary_pole_scale", cfg.secondary_pole_scale))
    return StageTrajectory(
        kind="actor",
        pole_start_hz=p0,
        pole_end_hz=pend,
        zero_start_hz=z0,
        zero_end_hz=_bounded_freq(z0 * 2.0 ** zero_move, cfg),
        secondary_pole_octaves=sec_pole,
        secondary_zero_octaves=rng.uniform(-shift_hi, shift_hi),
        pole_radius_q0=pr0,
        pole_radius_q100=max(pr0, pr1),
        zero_radius_q0=zr0,
        zero_radius_q100=max(zr0, zr1),
    )


def _vowel_program(seed: int, specialist: str, profile: Any, cfg: Any) -> ProgramGenome:
    """Real-vowel formant filter: FIVE formants at measured Hz with real bandwidths.

    lane0 = low-body shelf (the voiced chest, flat above so the formants ride on top);
    lanes 1-3 = F1,F2,F3 from the Peterson-Barney table, gliding START->END vowel (the
    'talk'); lanes 4-5 = F4,F5 fixed high formants (the whispered-vowel ring that makes
    it read as a real vowel, not just a resonance). Bandwidths are real (Klatt-class):
    r = exp(-pi*BW/SR), tight so formants are CRISP not muddy. Zeros stay shallow so
    each formant is a clean peak (no scooped canyons). Q = radius only — it sharpens
    the formants, never moves them (the vowel law)."""
    rng = random.Random(int(seed))
    tr = profile.transitions.get(specialist) or next(iter(profile.transitions.values()))
    a = [float(x) for x in tr["start_hz"]]                              # [F1,F2,F3] START vowel
    b = [a[i] * 2.0 ** float(m) for i, m in enumerate(tr["move_oct"])]  # END vowel (table move)
    ca = a + [3400.0, 4700.0]                                           # 5 start centers (F4,F5 fixed)
    cb = b + [3400.0, 4700.0]                                           # 5 end centers

    def rad(bw_hz: float) -> float:                                     # bandwidth -> pole radius
        return math.exp(-math.pi * bw_hz / AUTHORING_SR)

    # Every formant is a genuine POLE+ZERO biquad (the DC-pinned _actor_kernel), NOT an
    # RBJ EQ bell. A resonant pole sits near the circle (it RINGS); a zero co-located at
    # the same angle but a little deeper in flattens the skirts. Because _actor_kernel is
    # DC-pinned (gain=1 at DC), a co-located pole+zero is a SHARP resonance on a ~flat
    # background — so it doesn't roll off -12 dB/oct and crush the upper formants. The
    # pole/zero radius GAP sets the formant boost; Q sharpens the pole, never moves it.
    bw_q0 = [110.0, 140.0, 190.0, 240.0, 300.0]                        # soft at Q0
    bw_q100 = [55.0, 80.0, 120.0, 180.0, 240.0]                        # crisp at Q100
    # Each formant is a pole+zero biquad whose ZERO sits in the VALLEY above the formant
    # (toward the next one), carving the inter-formant canyon — the anti-resonance that
    # is the vowel's character. Canyon DEPTH tracks the formant gap: a wide gap (/ee/'s
    # F1->F2) gets a deep canyon; close formants (/ah/'s F1,F2) get a shallow zero so the
    # merged hump survives. The canyon WALKS with the vowel (zero glides START->END).
    stages: list[StageTrajectory] = [
        StageTrajectory(kind="lowshelf",
            pole_start_hz=rng.uniform(*_range(profile, "foundation_hz")),
            pole_end_hz=rng.uniform(*_range(profile, "foundation_hz")),
            gain_start_db=4.0, gain_end_db=4.0, secondary_gain_db=0.0),
    ]
    for i in range(5):
        hi_a = ca[i + 1] if i < 4 else ca[i] * 1.6                      # valley toward the next formant
        hi_b = cb[i + 1] if i < 4 else cb[i] * 1.6
        gap = abs(math.log2(max(hi_a, 1.0) / max(ca[i], 1.0)))         # octaves to next formant
        depth = _clip(0.50 + 0.31 * min(gap, 1.5), 0.50, 0.965)        # wide gap -> deep canyon
        stages.append(StageTrajectory(kind="actor",
            pole_start_hz=ca[i], pole_end_hz=cb[i],
            zero_start_hz=math.sqrt(ca[i] * hi_a), zero_end_hz=math.sqrt(cb[i] * hi_b),
            secondary_pole_octaves=0.0, secondary_zero_octaves=0.0,
            pole_radius_q0=rad(bw_q0[i]), pole_radius_q100=rad(bw_q100[i]),
            zero_radius_q0=depth * 0.92, zero_radius_q100=depth))       # canyon deepens with Q
    return ProgramGenome(family="vowel_real", specialist=str(specialist),
                         seed=int(seed), stages=tuple(stages))


def sample_specialist_program(seed: int, specialist: str, profile_name: str, cfg: Any,
                              profiles: Any) -> ProgramGenome:
    """Sample one original specialist slot from a clean-room macro palette."""
    rng = random.Random(int(seed))
    profile = profiles[profile_name]
    if "transitions" in profile:
        return _vowel_program(seed, specialist, profile, cfg)
    jitter = lambda: 2.0 ** rng.uniform(*_range(cfg, "constructor_jitter_octaves"))
    directions = [float(value) for value in profile.direction_signs]
    bases = [float(value) for value in profile.bases_hz]
    contrary_indices = set(int(index) for index in profile.contrary_indices)
    local_indices = set(int(index) for index in profile.local_indices)
    if len(bases) != 6 or len(directions) != 6:
        raise ValueError(f"specialist profile {profile_name!r} requires six bases and directions")
    stages = [
        _random_actor(
            rng,
            cfg,
            base * jitter(),
            index,
            contrary=index in contrary_indices,
            local=index in local_indices,
            profile=profile,
            direction=directions[index],
        )
        for index, base in enumerate(bases)
    ]
    return ProgramGenome(
        family=str(profile_name),
        specialist=str(specialist),
        seed=int(seed),
        stages=tuple(stages),
    )


def sample_program(seed: int, family: str, cfg: Any) -> ProgramGenome:
    """Sample one lawful whole-body program. No ROM coefficients enter here."""
    rng = random.Random(int(seed))
    jitter = lambda: 2.0 ** rng.uniform(*_range(cfg, "constructor_jitter_octaves"))
    if family == "opposed_window":
        bases = list(cfg.opposed_window.bases_hz)
        stages = [_random_actor(rng, cfg, base * jitter(), i, contrary=True) for i, base in enumerate(bases)]
    elif family == "vocal_mountains":
        bases = list(cfg.vocal_mountains.bases_hz)
        contrary_indices = set(int(index) for index in cfg.vocal_mountains.contrary_indices)
        local_indices = set(int(index) for index in cfg.vocal_mountains.local_indices)
        stages = [
            _random_actor(rng, cfg, base * jitter(), i, contrary=i in contrary_indices, local=i in local_indices)
            for i, base in enumerate(bases)
        ]
    elif family == "lp6_tear":
        cutoff0 = rng.uniform(*_range(cfg.lp6_tear, "cutoff_start_hz"))
        cutoff1 = rng.uniform(*_range(cfg.lp6_tear, "cutoff_end_hz"))
        stages = [
            StageTrajectory(kind="lowpass", pole_start_hz=cutoff0, pole_end_hz=cutoff1,
                            secondary_pole_octaves=rng.uniform(*_range(cfg.lp6_tear, "secondary_pole_octaves")),
                            section_q=float(q))
            for q in cfg.lp6_tear.section_q
        ]
        stages += [
            _random_actor(rng, cfg, base * jitter(), i + 3, contrary=True, local=(i == 1))
            for i, base in enumerate(cfg.lp6_tear.actor_bases_hz)
        ]
    elif family == "shelf_crossing":
        low, high = cfg.shelf_crossing.lowshelf, cfg.shelf_crossing.highshelf
        stages = [
            StageTrajectory(kind="lowshelf", pole_start_hz=rng.uniform(*_range(low, "pole_start_hz")),
                            pole_end_hz=rng.uniform(*_range(low, "pole_end_hz")),
                            gain_start_db=rng.uniform(*_range(low, "gain_start_db")),
                            gain_end_db=rng.uniform(*_range(low, "gain_end_db")),
                            secondary_gain_db=rng.uniform(*_range(low, "secondary_gain_db"))),
            StageTrajectory(kind="highshelf", pole_start_hz=rng.uniform(*_range(high, "pole_start_hz")),
                            pole_end_hz=rng.uniform(*_range(high, "pole_end_hz")),
                            gain_start_db=rng.uniform(*_range(high, "gain_start_db")),
                            gain_end_db=rng.uniform(*_range(high, "gain_end_db")),
                            secondary_gain_db=rng.uniform(*_range(high, "secondary_gain_db"))),
        ]
        local_indices = set(int(index) for index in cfg.shelf_crossing.actor_local_indices)
        stages += [
            _random_actor(rng, cfg, base * jitter(), i + 2, contrary=True, local=i in local_indices)
            for i, base in enumerate(cfg.shelf_crossing.actor_bases_hz)
        ]
    else:
        raise ValueError(f"unknown constructor family: {family}")
    return ProgramGenome(family=family, seed=int(seed), stages=tuple(stages))
