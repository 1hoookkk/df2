"""Forge optimizer — pymoo multi-objective body search.

Per-category fitness functions, fast in-process evaluation,
Pareto-optimal output to vault with matplotlib plots.

Usage:
    python pyruntime/forge_optimize.py --category vocal --generations 50 --pop 40
    python pyruntime/forge_optimize.py --category all
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.optimize import minimize
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.sampling.rnd import FloatRandomSampling

from pyruntime.body import Body
from pyruntime.constants import SR, NUM_BODY_STAGES
from pyruntime.corner import CornerArray, CornerName, CornerState
from pyruntime.macro_compile import (
    Actor, BodySpec, CompileMacro, PressureBehavior,
    SlotSpec, SlotState, compile_body, freq_to_place,
)
from pyruntime.stage_math import resonator, resonator_with_zero, zero_forced, zero_forced_offset
from pyruntime.encode import raw_to_encoded
from pyruntime.freq_response import cascade_response_db, freq_points
from pyruntime.analysis import morph_trajectory_distance
from pyruntime.target import _empty_slot
from pyruntime.zero_law import ContourKind

VAULT_DIR = Path(__file__).parent.parent / "vault"
FREQS = freq_points()

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
}
VOWEL_KEYS = list(VOWELS.keys())

ACTOR_CONTOUR = {
    Actor.FOUNDATION: (ContourKind.PURE, 0.0),
    Actor.MASS: (ContourKind.NEAR_ALLPASS, 0.3),
    Actor.THROAT: (ContourKind.INTERIOR_ZERO, 0.5),
    Actor.BITE: (ContourKind.UNIT_CIRCLE, 0.6),
    Actor.AIR: (ContourKind.INTERIOR_ZERO, 0.4),
    Actor.SCAR: (ContourKind.UNIT_CIRCLE, 0.0),
}


# ---------------------------------------------------------------------------
# Fast evaluation helpers (no file I/O)
# ---------------------------------------------------------------------------

def _eval_body(body: Body) -> dict:
    """Fast in-process body evaluation. Returns metrics dict."""
    enc_mid = body.corners.interpolate(0.5, 0.5)
    db_mid = cascade_response_db(enc_mid, FREQS, SR)

    peak = float(np.max(db_mid))
    valley = float(np.min(db_mid))
    dynamic_range = peak - valley

    # Ridge: max peak relative to mean
    mean_db = float(np.mean(db_mid))
    ridge = max(0.0, min(1.0, (peak - mean_db) / 40.0))

    # Talkingness proxy: count peaks in 200-5000 Hz range above mean
    mask = (FREQS >= 200) & (FREQS <= 5000)
    vocal_db = db_mid[mask]
    if len(vocal_db) > 2:
        vocal_peaks = 0
        for i in range(1, len(vocal_db) - 1):
            if vocal_db[i] > vocal_db[i-1] and vocal_db[i] > vocal_db[i+1]:
                if vocal_db[i] > mean_db + 3:
                    vocal_peaks += 1
        talkingness = min(1.0, vocal_peaks / 4.0)
    else:
        talkingness = 0.0

    # Ruggedness: std of dB response
    ruggedness = min(1.0, float(np.std(db_mid)) / 30.0)

    # Spectral tilt
    tilt = float(db_mid[-1] - db_mid[0])

    # Morph distance (lightweight: just check M0 vs M100 at Q=0.5)
    enc_m0 = body.corners.interpolate(0.0, 0.5)
    enc_m1 = body.corners.interpolate(1.0, 0.5)
    db_m0 = cascade_response_db(enc_m0, FREQS, SR)
    db_m1 = cascade_response_db(enc_m1, FREQS, SR)
    morph_dist = float(np.sqrt(np.mean((db_m0 - db_m1) ** 2)))

    # Coherence: 1 - fragmentation (std of peak-to-valley within octave bands)
    coherence = 1.0  # simplified

    return {
        "talkingness": talkingness,
        "ridge": ridge,
        "dynamic_range": dynamic_range,
        "ruggedness": ruggedness,
        "morph_distance": morph_dist,
        "spectral_tilt": tilt,
        "coherence": coherence,
        "peak_db": peak,
    }


# ---------------------------------------------------------------------------
# Stitch body builder (for vocal/drum/bass/pad/lead)
# ---------------------------------------------------------------------------

def _vowel_spec_from_params(name: str, vowel_idx: int, focus: float, weight: float) -> BodySpec:
    """Build a vowel BodySpec from optimizer parameters."""
    key = VOWEL_KEYS[int(vowel_idx) % len(VOWEL_KEYS)]
    f1, f2, f3, f4 = VOWELS[key]
    slots = [_empty_slot(a) for a in Actor.ALL]
    used = set()
    for freq in (f1, f2, f3, f4):
        for idx, actor in enumerate(Actor.ALL):
            if idx not in used and actor.freq_floor() <= freq <= actor.freq_ceiling():
                c, clr = ACTOR_CONTOUR.get(actor, (ContourKind.UNIT_CIRCLE, 0.5))
                state = SlotState(
                    place=freq_to_place(actor, freq), focus=focus, weight=weight,
                    contour=c, color=clr, hue=0.0, contour_override=None)
                slots[idx] = SlotSpec(actor=actor, state_a=state, state_b=state,
                                      pressure=PressureBehavior.TIGHTEN,
                                      compile_macro=CompileMacro.SINGLE, spread=0.0)
                used.add(idx)
                break
    return BodySpec(name=name, slots=slots, boost=4.0)


def _build_stitch(vowel_a_idx: int, vowel_b_idx: int,
                  focus: float, weight: float) -> Body:
    """Build a stitched body from two vowel indices + shared params."""
    sa = _vowel_spec_from_params("_a", vowel_a_idx, focus, weight)
    sb = _vowel_spec_from_params("_b", vowel_b_idx, focus, weight)
    ca = compile_body(sa)
    cb = compile_body(sb)
    corners = CornerArray(
        a=ca.corner(CornerName.A), b=ca.corner(CornerName.B),
        c=cb.corner(CornerName.C), d=cb.corner(CornerName.D),
    )
    return Body(name="opt", corners=corners, boost=4.0)


# ---------------------------------------------------------------------------
# 12-stage body builder (for 808/hihat/lofi/pluck/fx)
# ---------------------------------------------------------------------------

def _build_12stage(params: np.ndarray, category: str) -> Body:
    """Build a 12-stage body from a flat parameter vector.

    Per stage: [log_freq, radius, weight, notch_type(0-3)]
    Total: 12 * 4 = 48 params per morph endpoint, 96 total.
    params[0:48] = morph=0, params[48:96] = morph=1.
    """
    def _make_corner(p: np.ndarray, q_boost: float) -> CornerState:
        stages = []
        for i in range(12):
            base = i * 4
            freq = np.exp(p[base])  # log-freq space
            freq = max(20.0, min(SR * 0.48 - 50, freq))
            radius = min(0.998, max(0.30, p[base + 1]) + q_boost)
            weight = max(0.0, min(0.80, p[base + 2]))
            notch_type = int(p[base + 3]) % 4

            r = radius
            val1 = -1.0 + weight * 0.85

            if notch_type == 0:  # pure
                stage = resonator(freq, r, val1)
            elif notch_type == 1:  # unit_circle
                stage = zero_forced(freq, r, val1)
            elif notch_type == 2:  # interior
                zero_r = r * 0.6
                stage = resonator_with_zero(freq, r, val1, freq, zero_r)
            else:  # offset notch
                stage = zero_forced_offset(freq, r, val1, 3.0)

            stages.append(stage)

        return CornerState(stages=stages, boost=4.0)

    p_a = params[:48]
    p_b = params[48:96]

    # Interpolate for 4 corners
    corners = []
    for morph, q in [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]:
        p = p_a * (1 - morph) + p_b * morph
        q_boost = q * 0.02
        corners.append(_make_corner(p, q_boost))

    return Body(name="opt", corners=CornerArray(
        a=corners[0], b=corners[1], c=corners[2], d=corners[3]), boost=4.0)


# ---------------------------------------------------------------------------
# Pymoo Problem definitions
# ---------------------------------------------------------------------------

CATEGORY_OBJECTIVES = {
    "vocal":  ["talkingness", "ridge", "morph_distance"],
    "drum":   ["talkingness", "ridge", "morph_distance"],
    "bass":   ["talkingness", "ridge", "morph_distance"],
    "pad":    ["talkingness", "coherence", "morph_distance"],
    "lead":   ["talkingness", "ridge", "morph_distance"],
    "808":    ["dynamic_range", "ruggedness", "morph_distance"],
    "hihat":  ["ridge", "dynamic_range", "morph_distance"],
    "lofi":   ["dynamic_range", "morph_distance", "spectral_tilt"],
    "pluck":  ["ridge", "dynamic_range", "morph_distance"],
    "fx":     ["ridge", "morph_distance", "ruggedness"],
}

STITCH_CATEGORIES = {"vocal", "drum", "bass", "pad", "lead"}


class StitchProblem(Problem):
    """Optimize stitched bodies: search vowel pairs + focus/weight."""

    def __init__(self, category: str):
        n_vowels = len(VOWEL_KEYS)
        # x = [vowel_a_idx, vowel_b_idx, focus, weight]
        xl = np.array([0, 0, 0.80, 0.40])
        xu = np.array([n_vowels - 0.01, n_vowels - 0.01, 0.99, 0.80])
        self.objectives = CATEGORY_OBJECTIVES[category]
        super().__init__(n_var=4, n_obj=len(self.objectives), xl=xl, xu=xu)

    def _evaluate(self, X, out, *args, **kwargs):
        F = []
        for x in X:
            try:
                body = _build_stitch(int(x[0]), int(x[1]), x[2], x[3])
                metrics = _eval_body(body)
                # Pymoo minimizes, so negate objectives we want to maximize
                row = [-metrics[obj] for obj in self.objectives]
                # Penalize extreme dynamic range (>80 dB)
                if metrics["peak_db"] > 40:
                    row = [r + (metrics["peak_db"] - 40) * 0.1 for r in row]
                F.append(row)
            except Exception:
                F.append([0.0] * len(self.objectives))
        out["F"] = np.array(F)


class TwelveStageProblem(Problem):
    """Optimize 12-stage bodies: search frequencies, radii, weights, notch types."""

    def __init__(self, category: str):
        # 96 params: 48 per morph endpoint (12 stages * 4 params each)
        # Per stage: [log_freq, radius, weight, notch_type]
        freq_bounds = self._freq_bounds(category)
        xl, xu = [], []
        for _ in range(2):  # two morph endpoints
            for i in range(12):
                xl.extend([math.log(freq_bounds[i][0]), 0.30, 0.03, 0])
                xu.extend([math.log(freq_bounds[i][1]), 0.95, 0.70, 3.99])
        self.objectives = CATEGORY_OBJECTIVES[category]
        self.category = category
        super().__init__(n_var=96, n_obj=len(self.objectives),
                         xl=np.array(xl), xu=np.array(xu))

    def _freq_bounds(self, category: str) -> list[tuple[float, float]]:
        """Per-stage frequency bounds by category."""
        if category == "808":
            return [(20, 80)] * 4 + [(30, 500)] * 8
        elif category == "hihat":
            return [(400, 2000)] * 2 + [(1000, 6000)] * 4 + [(3000, 16000)] * 6
        elif category == "lofi":
            return [(60, 400)] * 3 + [(300, 3000)] * 3 + [(2000, 8000)] * 3 + [(5000, 18000)] * 3
        elif category == "pluck":
            return [(40, 400)] * 3 + [(200, 2000)] * 3 + [(1000, 8000)] * 3 + [(4000, 18000)] * 3
        elif category == "fx":
            return [(20, 200)] * 2 + [(100, 1000)] * 2 + [(500, 5000)] * 4 + [(3000, 18000)] * 4
        return [(20, 18000)] * 12

    def _evaluate(self, X, out, *args, **kwargs):
        F = []
        for x in X:
            try:
                body = _build_12stage(x, self.category)
                metrics = _eval_body(body)
                row = [-metrics[obj] for obj in self.objectives]
                # Penalize extreme dynamic range for non-808 categories
                if self.category != "808" and metrics["dynamic_range"] > 100:
                    penalty = (metrics["dynamic_range"] - 100) * 0.05
                    row = [r + penalty for r in row]
                F.append(row)
            except Exception:
                F.append([0.0] * len(self.objectives))
        out["F"] = np.array(F)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def _plot_pareto(results, objectives, out_path):
    """Plot Pareto front in objective space."""
    F = -results.F  # un-negate for display
    fig, axes = plt.subplots(1, min(3, len(objectives) - 1), figsize=(5 * min(3, len(objectives) - 1), 4))
    if len(objectives) == 2:
        axes = [axes]
    for i, ax in enumerate(axes if hasattr(axes, '__iter__') else [axes]):
        if i + 1 < F.shape[1]:
            ax.scatter(F[:, 0], F[:, i + 1], c="steelblue", s=20, alpha=0.7)
            ax.set_xlabel(objectives[0])
            ax.set_ylabel(objectives[i + 1])
            ax.set_title(f"Pareto front")
            ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"  Pareto plot: {out_path}")


def _plot_responses(bodies: list[Body], names: list[str], out_path):
    """Overlay frequency responses of top bodies."""
    fig, ax = plt.subplots(figsize=(10, 5))
    for body, name in zip(bodies, names):
        enc = body.corners.interpolate(0.5, 0.5)
        db = cascade_response_db(enc, FREQS, SR)
        ax.semilogx(FREQS, db, label=name, alpha=0.7)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude (dB)")
    ax.set_title("Top Candidates — Frequency Response @ M50 Q50")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(20, SR / 2)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"  Response plot: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def optimize_category(category: str, generations: int = 50, pop_size: int = 40) -> Path:
    """Run optimization for one category."""
    print(f"\n{'='*60}")
    print(f"  Optimizing: {category}")
    print(f"  Objectives: {CATEGORY_OBJECTIVES[category]}")
    print(f"  Generations: {generations}, Population: {pop_size}")
    print(f"{'='*60}")

    is_stitch = category in STITCH_CATEGORIES
    if is_stitch:
        problem = StitchProblem(category)
    else:
        problem = TwelveStageProblem(category)

    algorithm = NSGA2(
        pop_size=pop_size,
        sampling=FloatRandomSampling(),
        crossover=SBX(prob=0.9, eta=15),
        mutation=PM(eta=20),
    )

    result = minimize(problem, algorithm, ("n_gen", generations),
                      seed=42, verbose=False)

    # Build Pareto-optimal bodies
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = VAULT_DIR / f"opt_{category}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    bodies = []
    names = []
    metrics_list = []

    for i, x in enumerate(result.X):
        if is_stitch:
            body = _build_stitch(int(x[0]), int(x[1]), x[2], x[3])
            va = VOWEL_KEYS[int(x[0]) % len(VOWEL_KEYS)]
            vb = VOWEL_KEYS[int(x[1]) % len(VOWEL_KEYS)]
            name = f"{category.capitalize()}_{va}_{vb}_{i:03d}"
        else:
            body = _build_12stage(x, category)
            name = f"{category.capitalize()}_{i:03d}"

        body_named = Body(name=name, corners=body.corners, boost=body.boost)
        metrics = _eval_body(body_named)

        path = out_dir / f"{name}.json"
        path.write_text(body_named.to_compiled_json())

        bodies.append(body_named)
        names.append(name)
        metrics_list.append(metrics)

    # Sort by first objective for reporting
    obj0 = CATEGORY_OBJECTIVES[category][0]
    ranked = sorted(zip(names, metrics_list), key=lambda x: -x[1][obj0])

    print(f"\n  {len(bodies)} Pareto-optimal bodies saved to {out_dir}")
    print(f"\n  Top 10 by {obj0}:")
    for name, m in ranked[:10]:
        vals = "  ".join(f"{k}={m[k]:.2f}" for k in CATEGORY_OBJECTIVES[category])
        print(f"    {name}: {vals}")

    # Plots
    _plot_pareto(result, CATEGORY_OBJECTIVES[category], out_dir / "pareto.png")
    top_bodies = [b for b, _ in sorted(zip(bodies, metrics_list),
                  key=lambda x: -x[1][obj0])[:10]]
    top_names = [n for n, _ in ranked[:10]]
    _plot_responses(top_bodies, top_names, out_dir / "responses.png")

    return out_dir


def main():
    parser = argparse.ArgumentParser(description="Forge optimizer")
    parser.add_argument("--category", default="vocal", help="Category to optimize")
    parser.add_argument("--generations", type=int, default=50)
    parser.add_argument("--pop", type=int, default=40)
    args = parser.parse_args()

    categories = list(CATEGORY_OBJECTIVES.keys()) if args.category == "all" else [args.category]

    for cat in categories:
        optimize_category(cat, args.generations, args.pop)


if __name__ == "__main__":
    main()
