"""Canonical body240 serialization, compiled cartridge export, and plots."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pyruntime.encode import EncodedCoeffs
from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.packed_interp import coeffs_to_words, packed_bilinear, words_to_coeffs

CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
PACKED_KEYS = {"M0_Q0": "A", "M100_Q0": "B", "M0_Q100": "C", "M100_Q100": "D"}
AUTHORING_SR = 39_062.5
STAGES = 6
WORDS_PER_STAGE = 5
RAW_BYTES = len(CORNER_ORDER) * STAGES * WORDS_PER_STAGE * 2
FREQS = freq_points()


def words_from_kernels(kernels: dict[str, list[tuple[float, ...]]]) -> dict[str, list[tuple[int, ...]]]:
    return {
        label: [tuple(int(value) for value in coeffs_to_words(*row)) for row in kernels[label]]
        for label in CORNER_ORDER
    }


def raw_from_words(words: dict[str, list[tuple[int, ...]]]) -> bytes:
    flat = []
    for label in CORNER_ORDER:
        rows = words[label]
        if len(rows) != STAGES:
            raise ValueError(f"{label}: expected {STAGES} stages, got {len(rows)}")
        for row in rows:
            if len(row) != WORDS_PER_STAGE:
                raise ValueError(f"{label}: expected {WORDS_PER_STAGE} words per stage")
            flat.extend(int(value) for value in row)
    if any(value < 0 or value > 0xFFFF for value in flat):
        raise ValueError("body240 words must be unsigned 16-bit values")
    return np.array(flat, dtype="<u2").tobytes()


def _stage_dict_from_words(words: tuple[int, ...]) -> dict[str, float]:
    c0, c1, c2, c3, c4 = words_to_coeffs(words)
    return {"c0": c4, "c1": (c0 - 2.0) * c4, "c2": (1.0 - c1) * c4,
            "c3": c2 - 2.0, "c4": 1.0 - c3}


def compiled_payload(name: str, boost: float, words: dict[str, list[tuple[int, ...]]]) -> dict[str, Any]:
    keyframes = []
    for label in CORNER_ORDER:
        keyframes.append({
            "label": label,
            "morph": 1.0 if "M100" in label else 0.0,
            "q": 1.0 if "Q100" in label else 0.0,
            "boost": boost,
            "stages": [_stage_dict_from_words(row) for row in words[label]],
            "packedWords": [[int(value) for value in row] for row in words[label]],
        })
    return {
        "format": "compiled-v1",
        "name": name,
        "provenance": "direct-packed-240",
        "sampleRate": AUTHORING_SR,
        "authoring_sample_rate_hz": AUTHORING_SR,
        "stages": STAGES,
        "cornerOrder": list(CORNER_ORDER),
        "keyframes": keyframes,
    }


def _response_at(words: dict[str, list[tuple[int, ...]]], morph: float, secondary: float) -> np.ndarray:
    keyed = {PACKED_KEYS[label]: words[label] for label in CORNER_ORDER}
    rows = packed_bilinear(keyed, morph, secondary)
    return cascade_response_db([EncodedCoeffs(*row) for row in rows], FREQS)


def render_png(name: str, words: dict[str, list[tuple[int, ...]]], out: Path) -> None:
    plt.rcParams["figure.facecolor"] = "#070a09"
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.2))
    ymarks = [60, 150, 400, 1000, 2500, 6000]
    yidx = [int(np.argmin(np.abs(FREQS - freq))) for freq in ymarks]
    for axis, secondary, title in ((axes[0], 0.0, "Q0"), (axes[1], 1.0, "Q100")):
        image = np.array([_response_at(words, morph, secondary)
                          for morph in np.linspace(0.0, 1.0, 220)]).T
        lo, hi = float(np.nanpercentile(image, 5)), float(np.nanpercentile(image, 99.5))
        axis.imshow(np.clip(image, lo, max(hi, lo + 1.0)), aspect="auto", origin="lower",
                    cmap="magma", extent=[0, 1, 0, len(FREQS)], vmin=lo, vmax=max(hi, lo + 1.0))
        axis.set_yticks(yidx)
        axis.set_yticklabels([str(freq) for freq in ymarks], fontsize=7)
        axis.set_title(f"{name} -- packed morph sweep ({title})", color="#eaeaea", fontsize=10)
        axis.set_xlabel("morph", color="#aaa", fontsize=8)
        axis.tick_params(colors="#888")
    colors = {"M0_Q0": "#2ec4ff", "M100_Q0": "#ffd23e", "M0_Q100": "#ff6b6b", "M100_Q100": "#9b8cff"}
    for label in CORNER_ORDER:
        response = cascade_response_db([EncodedCoeffs(*words_to_coeffs(row)) for row in words[label]], FREQS)
        axes[2].semilogx(FREQS, np.clip(response - float(np.max(response)), -60, 6),
                         color=colors[label], lw=1.7, label=label)
    axes[2].set(xlim=(20, 20000), ylim=(-60, 6), title="four complete corners")
    axes[2].grid(True, which="both", alpha=0.15)
    axes[2].legend(fontsize=8)
    fig.suptitle(f"{name} -- direct 240-byte body", color="#eaeaea", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=115)
    plt.close(fig)
