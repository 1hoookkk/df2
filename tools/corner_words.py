"""corner_words — turn a whole-corner recipe into verbatim packed-16 words.

The DSP grunt-work library for the `forge-corners` skill. A subagent writes a
compact recipe (resonances per corner) and calls `build_toml` to get a
packed-body-v1 document whose `words` are verbatim 6x5 u16 minifloat words
(the 240-byte format). No stage ceremony: a corner is authored as a whole set
of stages in one pass.

Every band-peak carries a unit-circle DC-nulling zero, so a low-end pedestal
(the BRIEF reject case) is impossible by construction.

Recipe shape (per body): dict of the four corner labels ->
  list of EXACTLY 6 StageParams (use bp / edge / pas).

    from tools.corner_words import bp, edge, pas, build_toml
    corners = {
        "M0_Q0":     [bp(380, .86), bp(920, .84), bp(1610, .82), pas(), pas(), pas()],
        "M100_Q0":   [bp(640, .90), bp(1820, .88), bp(3400, .86), bp(5200, .84), pas(), pas()],
        "M0_Q100":   [bp(520, .95), bp(1480, .94), bp(2950, .93), edge(.985), pas(), pas()],
        "M100_Q100": [bp(1180, .975), bp(3050, .97), edge(.992), pas(), pas(), pas()],
    }
    Path("bodies/factory/gong.packed.toml").write_text(build_toml("Gong", corners))
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyruntime.stage_math import zero_forced_offset, resonator_with_zero  # noqa: E402
from pyruntime.stage_params import StageParams  # noqa: E402
from pyruntime.encode import raw_to_encoded  # noqa: E402
from pyruntime.packed_interp import coeffs_to_words  # noqa: E402

CORNER_LABELS = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")

AUTHORING_SR = 39062.5


def r_from_bw(bw_hz: float, sharpen: float = 1.0) -> float:
    """Exact pole radius from a formant bandwidth (Hz). r = exp(-pi*BW/SR).
    `sharpen` < 1 narrows the band (the Q axis): sharpen=0.35 ~ 3x tighter.
    This is the table-driven path — radius is *derived from published
    bandwidths*, not guessed."""
    import math
    r = math.exp(-math.pi * max(bw_hz * sharpen, 1.0) / AUTHORING_SR)
    return min(r, 0.9985)


def formant(freq_hz: float, bw_hz: float, sharpen: float = 1.0) -> StageParams:
    """A formant placed EXACTLY: pole at the table frequency, radius from the
    table bandwidth. The Rossum move — look up, don't invent."""
    return bp(freq_hz, r_from_bw(bw_hz, sharpen))

# Pole + a zero this many semitones below it = a stable band-peak that rolls
# off below the peak (no pedestal). Reverse-engineered from the clean Neon Vane
# body. A pure all-pole resonator (no zero) is UNSTABLE here — do not use it.
_ZERO_BELOW_SEMIS = -7.0
_DEPTH = -0.08  # val1; matches Neon Vane's gain trim


def bp(freq: float, radius: float = 0.95, depth: float = _DEPTH) -> StageParams:
    """Band-peak: a pole at `freq` with a zero ~7 semitones below — the stable
    bandpass shape proven by Neon Vane. Rolls off below the peak, no pedestal.

    radius is sharpness/Q: ~0.93-0.95 = tame, ~0.97-0.99 = sharp/ringing.
    USE HIGH RADIUS (>=0.93) or the peak flattens into a shelf."""
    return zero_forced_offset(freq, radius, depth, _ZERO_BELOW_SEMIS)


def edge(radius: float = 0.992, freq: float = 16500.0, depth: float = _DEPTH) -> StageParams:
    """Near-Nyquist bite — a pole parked against the wall (~16.5 kHz). The
    character/edge stage. Use on the violent corners. radius >= 0.99."""
    return zero_forced_offset(freq, radius, depth, _ZERO_BELOW_SEMIS)


def lp(freq: float, radius: float = 0.95, depth: float = _DEPTH) -> StageParams:
    """Dark band-peak: a pole at `freq` with a zero up near Nyquist, so the
    response ROLLS OFF ABOVE the peak (the opposite of `bp`, which stays bright
    up top). Use to make dark/closed corners that genuinely differ in
    brightness from the bright corners — the key to distinct (non-costume)
    corners. Stable; same resonator+zero family as `bp`."""
    return resonator_with_zero(freq, radius, depth, 17800.0, 1.0)


def peak_eq_words(freq: float, bw: float, gain_db: float) -> tuple:
    """Parametric peaking-EQ section as packed words (RBJ): FLAT 0 dB baseline
    with a bump of `gain_db` at `freq`, width set by `bw` (Q = freq/bw). This is
    the E-mu 'parametric EQ' stage — formants as boosts on flatness, so a cascade
    is flat + formant bumps (no low-end pedestal, no notch). Verified vs voice."""
    import math
    from pyruntime.packed_interp import coeffs_to_words
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq / AUTHORING_SR
    Q = max(freq / max(bw, 1.0), 0.4)
    al = math.sin(w0) / (2.0 * Q)
    b0 = 1 + al * A; b1 = -2 * math.cos(w0); b2 = 1 - al * A
    a0 = 1 + al / A; a1 = -2 * math.cos(w0); a2 = 1 - al / A
    b0 /= a0; b1 /= a0; b2 /= a0; a1 /= a0; a2 /= a0
    c4 = b0; c2 = a1 + 2.0; c3 = 1.0 - a2; c0 = b1 / b0 + 2.0; c1 = 1.0 - b2 / b0
    return coeffs_to_words(c0, c1, c2, c3, c4)


def allpole_words(freq: float, radius: float, gain: float = 1.0) -> tuple:
    """A TRUE all-pole resonator section as packed words:
        H(z) = gain / (1 - 2r cos w0 z^-1 + r^2 z^-2)
    Use to reconstruct an LPC fit faithfully — a cascade of these IS 1/A(z),
    i.e. the source's spectral envelope (the voice). Numerator is a constant
    (c0=2, c1=1), so unlike `bp` there is NO DC-cancelling zero: it reproduces
    whatever real low end the source actually has, and the formant balance is
    the LPC's, not a stack of equal band-peaks."""
    import math
    from pyruntime.packed_interp import coeffs_to_words
    th = 2.0 * math.pi * freq / AUTHORING_SR
    c0, c1 = 2.0, 1.0
    c2 = 2.0 - 2.0 * radius * math.cos(th)
    c3 = 1.0 - radius * radius
    c4 = gain
    return coeffs_to_words(c0, c1, c2, c3, c4)


def hedz_body(anchors: list[float], crosser_a: tuple[float, float],
              crosser_b: tuple[float, float], r_broad: float = 0.95,
              r_sharp: float = 0.997) -> dict:
    """The Talking-Hedz structure as a template (decoded from the ROM):

      * up to 4 ANCHOR poles — fixed frequency in all four corners (the
        stable "bones": air band, mids, presence).
      * 2 CROSSER poles that swap frequency across the MORPH axis — one falls,
        one rises, crossing near the middle = the formant migration / "talking".
      * the Q axis TIGHTENS every radius (broad r_broad -> sharp r_sharp), just
        like Hedz where every pole climbs toward 0.999 at Q100.

    Crossers are pinned to stage slots 4 and 5 so they stay registered across
    corners (the lerp slides them, doesn't crossfade). Returns a corners dict
    ready for build_toml.

    anchors:   up to 4 fixed frequencies (Hz).
    crosser_a: (freq@M0, freq@M100) — e.g. (900, 200), falls.
    crosser_b: (freq@M0, freq@M100) — e.g. (200, 1700), rises -> they cross.
    """
    def corner(morph: float, q: float) -> list[StageParams]:
        r = r_broad + (r_sharp - r_broad) * q          # Q tightens all radii
        st = [bp(f, r) for f in anchors[:4]]
        while len(st) < 4:
            st.append(pas())
        fa = crosser_a[0] + (crosser_a[1] - crosser_a[0]) * morph
        fb = crosser_b[0] + (crosser_b[1] - crosser_b[0]) * morph
        st.append(bp(fa, r))
        st.append(bp(fb, r))
        return st

    return {
        "M0_Q0":     corner(0.0, 0.0),
        "M100_Q0":   corner(1.0, 0.0),
        "M0_Q100":   corner(0.0, 1.0),
        "M100_Q100": corner(1.0, 1.0),
    }


def notch(freq: float, radius: float, depth: float, zero_freq: float, zero_radius: float = 1.0) -> StageParams:
    """Advanced: resonator with an explicit zero at an arbitrary frequency
    (e.g. a between-formant null for vocal bodies). Prefer `bp` by default."""
    return resonator_with_zero(freq, radius, depth, zero_freq, zero_radius)


def pas() -> StageParams:
    """Passthrough (inactive stage)."""
    return StageParams.passthrough()


def corner_words(stages: list[StageParams]) -> list[tuple[int, ...]]:
    if len(stages) != 6:
        raise ValueError(f"a corner is exactly 6 stages, got {len(stages)}")
    out = []
    for sp in stages:
        ec = raw_to_encoded(sp)
        out.append(coeffs_to_words(ec.c0, ec.c1, ec.c2, ec.c3, ec.c4))
    return out


def build_toml_words(name: str, corners: dict, boost: float = 1.0) -> str:
    """Like build_toml but takes VERBATIM packed-16 words directly
    ({label: [ (5 u16) x6 ]}) — no stage/freq/radius design layer."""
    missing = [c for c in CORNER_LABELS if c not in corners]
    if missing:
        raise ValueError(f"missing corners: {missing}")
    lines = [
        f"# {name} -- verbatim packed-16 words (no stage design)",
        'format = "packed-body-v1"',
        f'name = "{name}"',
        f"boost = {boost}",
        "authoring_sample_rate_hz = 39062.5",
        "",
    ]
    for label in CORNER_LABELS:
        lines.append(f"[corner.{label}]")
        lines.append("words = [")
        for w in corners[label]:
            lines.append("  [" + ", ".join(f"0x{int(v) & 0xFFFF:04X}" for v in w) + "],")
        lines.append("]")
        lines.append("")
    return "\n".join(lines)


def build_toml(name: str, corners: dict[str, list[StageParams]], boost: float = 1.0) -> str:
    missing = [c for c in CORNER_LABELS if c not in corners]
    if missing:
        raise ValueError(f"missing corners: {missing}")
    lines = [
        f"# {name} -- factory body (verbatim packed-16 words)",
        'format = "packed-body-v1"',
        f'name = "{name}"',
        f"boost = {boost}",
        "authoring_sample_rate_hz = 39062.5",
        "",
    ]
    for label in CORNER_LABELS:
        lines.append(f"[corner.{label}]")
        lines.append("words = [")
        for w in corner_words(corners[label]):
            lines.append("  [" + ", ".join(f"0x{v:04X}" for v in w) + "],")
        lines.append("]")
        lines.append("")
    return "\n".join(lines)
