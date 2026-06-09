"""V1 verification-first compiler: target surface -> stable packed body + artifacts.
Emits .body240, .report.json, .surface.npy, .response.png. The loop's synthesize+verify."""
from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import yaml
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.compiler.surface_target import FREQS, GRID, target_from_tables, Q_RADIUS_MAX
from src.compiler.surface_fit import fit_surface, surface
from src.compiler.encode import body_from_params
from src.utils.packed_runtime import evaluate_body, gate_failures

_n = lambda a: a - a.max(1, keepdims=True)
ROOT = Path(__file__).resolve().parents[2]
# Corridor gate = the iconic-15 reference-derived gates (smoke.yaml). reference_* ratios are 0
# there, so the zero reference below is inert — the floors are already reference-derived.
_GATES = SimpleNamespace(**yaml.safe_load((ROOT / "configs/model/smoke.yaml").read_text())["gates"])
_REF0 = {"median_endpoint_span_db": 0.0, "median_morph_contrast_db": 0.0, "median_secondary_contrast_db": 0.0}


def _corridor(body):
    m = evaluate_body(body, 17)
    fails = gate_failures(m, _GATES, _REF0)
    keep = ("max_pole_radius", "center_span_db", "endpoint_span_db_mean", "morph_contrast_rms_db",
            "secondary_contrast_rms_db", "center_response_peaks", "center_response_valleys",
            "max_pole_motion_octaves", "max_zero_motion_octaves", "objective")
    return {**{k: float(m[k]) for k in keep}, "in_corridor": not fails, "gate_failures": fails}


def compile_surface(target, name, out_dir, seed=0, frozen_zeros=None, seed_P=None, free=None,
                    rp_max=None, n_restarts=2, fit=True):
    # fit=False: the seed IS the design — pack it, verify, no optimize.
    # fit=True: optimize (theta,r,g) through the shipped runtime to hit the target surface
    #           (rp_max caps pole radius at the real corpus ceiling for table-driven authoring).
    if fit:
        P = fit_surface(target, seed=seed, frozen_zeros=frozen_zeros, seed_P=seed_P, free=free,
                        rp_max=rp_max, n_restarts=n_restarts)
    else:
        P = seed_P.copy()
    body = body_from_params(P)
    s = surface(body)
    err = _n(s) - _n(target)
    m = evaluate_body(body, 17)
    fails = gate_failures(m, _GATES, _REF0)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.body240").write_bytes(body)
    np.save(out / f"{name}.surface.npy", s)
    fig, ax = plt.subplots(figsize=(8.5, 4.0), facecolor="#0a0c0b")
    for gi, lab in [(0, "M0Q0"), (4, "M100Q0"), (12, "M50Q50"), (24, "M100Q100")]:
        ax.semilogx(FREQS, _n(target)[gi], color="#667", lw=1.6)
        ax.semilogx(FREQS, _n(s)[gi], lw=1.2, ls="--", label=lab)
    ax.set_xlim(40, 16000); ax.set_ylim(-72, 6); ax.grid(alpha=.2); ax.legend(fontsize=8)
    ax.set_title(f"{name}  —  grey = target, dashed = achieved  ·  surface RMS "
                 f"{float(np.sqrt(np.mean(err**2))):.2f} dB", color="#cfe9df", fontsize=10)
    ax.tick_params(colors="#889"); fig.tight_layout()
    fig.savefig(out / f"{name}.response.png", dpi=110, facecolor="#0a0c0b"); plt.close(fig)
    corridor_keys = ("center_span_db", "endpoint_span_db_mean", "morph_contrast_rms_db",
                     "secondary_contrast_rms_db", "center_response_peaks", "center_response_valleys",
                     "max_pole_motion_octaves", "max_zero_motion_octaves", "objective")
    rep = {"name": name,
           "surface_rms_db": float(np.sqrt(np.mean(err ** 2))),
           "surface_p95_db": float(np.percentile(np.abs(err), 95)),
           "surface_max_db": float(np.abs(err).max()),
           "max_pole_radius": float(m["max_pole_radius"]),
           "max_response_db": float(s.max()),
           "ceiling": bool(s.max() > 30),
           "stable": bool(m["max_pole_radius"] < 1.0),
           "in_corridor": not fails,
           "gate_failures": fails,
           **{k: float(m[k]) for k in corridor_keys}}
    (out / f"{name}.report.json").write_text(json.dumps(rep, indent=2))
    return rep


def compile_table(template, intent_family, home, away, name, out_dir, **kw):
    """Table-driven method: (template, intent_family, HOME->AWAY) -> a verified packed body.
    Every number table-pulled; pole radius capped at the real corpus ceiling 0.9863. Feeds
    the one verified core (fit through the shipped runtime + corridor gate + artifacts)."""
    target = target_from_tables(template, intent_family, home, away)
    kw.setdefault("rp_max", Q_RADIUS_MAX)
    return compile_surface(target, name, out_dir, fit=True, **kw)
