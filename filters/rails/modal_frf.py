#!/usr/bin/env python3
"""Modal well -> FEM modal FRFs (evidence surfaces for LucifersQ + Meaty Gizmo).

Provenance: NeuralResonator repo (surface-forge/data/modal/neuralresonator/,
Diaz et al., arXiv:2210.15306). We run its REAL physics path, not the neural net:
  shape.generate_convex_mesh (Valtr convex polygons -> triangle mesh)
  modal.System (skfem 2D linear elasticity, clamped boundary, scipy sym eigsh)
  modal.MATERIALS (named physical materials: rho, E, nu, Rayleigh alpha/beta)

Per shape/material we eigen-solve k modes, apply a documented physical SIZE L
(linear elasticity: eigenvalues scale 1/L^2 — solving the same mesh scaled by L),
and evaluate the standard Rayleigh-damped drive-point receptance at an interior
node near the centroid:

  H(w) = sum_k g_k^2 / (lam_k - w^2 + 2j d_k w),   d_k = 0.5*(alpha + beta*lam_k)

Mode FREQUENCIES are exact FEM output (the archetype identity: Meaty's radii/Q
contrast is applied later by Q-pressure, per ARCHETYPES.md). One documented
conditioning step: an analysis bandwidth floor (BW_FLOOR_HZ) on d_k so razor
modes are resolvable on a 600-pt log grid — it touches radii only, never
frequencies.

Families:
  lucifer (REZ, inharmonic mid spray 250 Hz-5 kHz): ceramic/glass, 2 sizes
  meaty   (struck metal, dense modes):               steel/iron,   2 sizes

Output: data/modal/*.json + MANIFEST.md
Run: python tools/modal_frf.py   (needs scikit-fem, triangle — pip, installed)
"""
from __future__ import annotations

import json
import math
import random
import sys
from datetime import date
from pathlib import Path

import numpy as np

NR = Path(r"C:\Users\hooki\surface-forge\data\modal\neuralresonator")
sys.path.insert(0, str(NR))
from neuralresonator.modal import MATERIALS, System          # noqa: E402
from neuralresonator.shape import generate_convex_mesh       # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "modal"

F_LO, F_HI, N_GRID = 50.0, 16000.0, 600
GRID = np.logspace(math.log10(F_LO), math.log10(F_HI), N_GRID)
W = 2 * math.pi * GRID

SEED = 20260704
K_MODES = 192
N_SHAPES = 6
BW_FLOOR_HZ = 25.0            # analysis damping floor (radii only; freqs untouched)

FAMILIES = dict(
    lucifer=dict(materials=["ceramic", "glass"], f1_targets=[320.0, 950.0]),
    meaty=dict(materials=["steel", "iron"], f1_targets=[140.0, 420.0]),
)


def interior_node(sysm: System) -> int:
    """Interior node nearest the centroid (boundary nodes are clamped -> zero gain)."""
    G = sysm.get_mode_gains()                       # [nodes x modes]
    locs = sysm.basis.doflocs[:, sysm.basis.nodal_dofs[0, :].flatten()]
    cen = locs.mean(axis=1)
    d = np.hypot(locs[0] - cen[0], locs[1] - cen[1])
    for n in np.argsort(d):
        if G[n].max() > 1e-12:
            return int(n)
    raise RuntimeError("no interior node with nonzero mode gains")


def receptance(lam, dcoef, gains) -> np.ndarray:
    H = np.zeros_like(W, dtype=complex)
    for lk, dk, gk in zip(lam, dcoef, gains):
        H += (gk * gk) / (lk - W ** 2 + 2j * dk * W)
    return H


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    count = 0
    lines = []
    for fam, cfg in FAMILIES.items():
        for si in range(N_SHAPES):
            shape_seed = SEED + si + (0 if fam == "lucifer" else 1000)
            np.random.seed(shape_seed); random.seed(shape_seed)   # shape.py uses global RNGs
            n_pts = int(rng.integers(8, 14))
            mesh, poly = generate_convex_mesh(n_pts, 3)
            mat_name = cfg["materials"][si % 2]
            mat = MATERIALS[mat_name]
            sysm = System(mat, mesh=mesh, k=K_MODES)
            ev = sysm.eigenvalues.copy()
            ev = ev[ev > 0]
            f_unit = math.sqrt(float(ev[0])) / (2 * math.pi)
            node = interior_node(sysm)
            gains = sysm.get_mode_gains(node)[: len(ev)]
            for f1t in cfg["f1_targets"]:
                L = f_unit / f1t                     # physical size multiplier (m)
                lam = ev / (L * L)
                dcoef = 0.5 * (mat.alpha + mat.beta * lam)
                dcoef = np.maximum(dcoef, math.pi * BW_FLOOR_HZ)
                f_damped = np.sqrt(np.maximum(lam - dcoef ** 2, 0.0)) / (2 * math.pi)
                keep = (f_damped > 20.0) & (f_damped < 19000.0)
                H = receptance(lam[keep], dcoef[keep], gains[keep])
                med = np.median(np.abs(H))
                H = H / med if med > 0 else H
                in_band = int(((f_damped >= 250) & (f_damped <= 5000)).sum())
                rid = f"{fam}_s{si:02d}_{mat_name}_f1_{int(f1t)}"
                (OUT / f"{rid}.json").write_text(json.dumps(dict(
                    id=rid, well="modal", family=fam,
                    source="surface-forge/data/modal/neuralresonator (FEM path: shape.py + modal.py, arXiv:2210.15306)",
                    method="skfem 2D linear-elasticity clamped eigensolve -> Rayleigh-damped drive-point receptance; "
                           f"size-scaled (lam/L^2); bw floor {BW_FLOOR_HZ} Hz on damping only; 0 dB median norm",
                    settings=dict(shape_seed=shape_seed, n_polygon_points=n_pts, refinements=3,
                                  material=mat_name, material_props=mat._asdict(),
                                  k_modes=K_MODES, size_L_m=L, f1_target_hz=f1t,
                                  strike_node=node, bw_floor_hz=BW_FLOOR_HZ),
                    mode_freqs_hz=[float(x) for x in f_damped[keep]],
                    freq_hz=[float(f) for f in GRID],
                    H_re=[float(x) for x in H.real], H_im=[float(x) for x in H.imag],
                ), indent=1), encoding="utf-8")
                count += 1
                msg = (f"  {rid}: {int(keep.sum())} modes kept, {in_band} in 250-5k, "
                       f"f1 {f_damped[keep][0]:.0f} Hz, L={L:.3f} m")
                print(msg); lines.append(msg)

    manifest = f"""# data/modal MANIFEST — FEM modal FRFs

Generated {date.today().isoformat()} by tools/modal_frf.py, seed {SEED} (deterministic).

## Well inventory (surface-forge/data/modal/, checked {date.today().isoformat()})
- neuralresonator/  Diaz et al. arXiv:2210.15306 repo. Runnable physics:
  shape.generate_convex_mesh (Valtr polygons + triangle) and modal.System
  (skfem 2D linear elasticity, clamped boundary, k-mode eigsh) + named MATERIALS.
  Also a trained checkpoint (data/ethereal_dust-317-2.ckpt) — NOT used; we run
  the exact FEM, not the neural surrogate. No pre-generated dataset in repo.
- NeuralSound/      dataset_scripts/src only, no data, heavier 3D pipeline — unused.

## FRFs ({count} files, band {F_LO:.0f}-{F_HI:.0f} Hz, {N_GRID} log pts)
Drive-point receptance H(w) = sum g_k^2/(lam_k - w^2 + 2j d_k w) at an interior
node near the centroid; d_k = 0.5(alpha + beta lam_k) floored at pi*{BW_FLOOR_HZ:.0f}
(analysis resolvability floor — affects radii only; mode FREQUENCIES are raw FEM,
also stored per-file as mode_freqs_hz).

- lucifer_* : ceramic/glass convex plates, sizes tuned f1~320 / ~950 Hz
              -> inharmonic mid spray for the LucifersQ (REZ) archetype.
- meaty_*   : steel/iron convex plates, sizes tuned f1~140 / ~420 Hz
              -> dense struck-metal mode sets for Meaty Gizmo (frequencies are
              the identity; Q contrast is applied later by Q-pressure).

Per-run log:
{chr(10).join(lines)}
"""
    (OUT / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    print(f"wrote {count} FRFs + MANIFEST -> {OUT}")


if __name__ == "__main__":
    main()
