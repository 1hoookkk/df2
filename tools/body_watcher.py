#!/usr/bin/env python3
"""body-watcher — save a lanes file, hear it.

  python -m tools.body_watcher [--watch bodies/drafts] [--out bodies/candidates] [--once]

Watches a folder for edited *.registered_lanes.json (the authoring IR).
On every save: validate (register_lanes) -> pack+certify (filter_cli ->
trench-core, THE compiler) -> journey plot (L14 default proof) -> atomically
replace OUT/<name>.body240. A failed save never touches the last certified
body240 — the plugin keeps playing the last known-good state.

The plugin TYPE menu rescans bodies/candidates on open, so the loop is:
save file -> watcher line says CERTIFIED -> reopen TYPE menu -> hear it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# trench_ffi lives in df2; the WORKSTATION dll is the live one (df2's is stale).
sys.path.append(r"C:\Users\hooki\df2\pyruntime")
os.environ.setdefault("TRENCH_CORE_DLL", str(ROOT / "target" / "release" / "trench_core.dll"))
from pyruntime.packed_interp import (  # noqa: E402  (shipped core)
    coeffs_to_words, decode, encode, kernel_to_biquad, packed_probe, words_to_coeffs,
)

# Plot law: fixed -60..+30 dB, dense log grid, thin unsmoothed lines.
GRID = np.geomspace(20.0, 19500.0, 1024)
SR = 39062.5
_W = 2.0 * np.pi * GRID / SR
_EJW = np.exp(-1j * _W)
_EJW2 = _EJW * _EJW
MORPHS = (0.0, 0.25, 0.5, 0.75, 1.0)


IDENTITY_WORDS = tuple(int(w) for w in coeffs_to_words(2.0, 1.0, 2.0, 1.0, 1.0))
CROWN_TARGETS = [2.0, 8.0, 25.0, 27.0]  # L10: M0_Q0, M100_Q0, M0_Q100, M100_Q100


def _stage_response(word_row: tuple[int, ...]) -> np.ndarray:
    b0, b1, b2, a1, a2 = kernel_to_biquad(words_to_coeffs(word_row))
    h = (b0 + b1 * _EJW + b2 * _EJW2) / (1.0 + a1 * _EJW + a2 * _EJW2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def frame_l10(raw: bytes) -> bytes:
    """Active-row L10 framing: crowns to +2/+8/+25/+27 via SCALE words only.

    Spreads the correction over non-identity rows per corner — frame-all-6
    crushes identity rows to silence (the silent-body trap)."""
    words = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, 240, 2)]
    for c in range(4):
        rows = lambda: [tuple(words[(c * 6 + s) * 5:(c * 6 + s) * 5 + 5]) for s in range(6)]
        active = [s for s, row in enumerate(rows()) if row != IDENTITY_WORDS]
        if not active:
            continue
        for _ in range(6):  # encode() quantizes; iterate to converge
            crown = float(sum(_stage_response(r) for r in rows()).max())
            delta = CROWN_TARGETS[c] - crown
            if abs(delta) <= 0.1:
                break
            g = 10.0 ** (delta / (20.0 * len(active)))
            for s in active:
                idx = (c * 6 + s) * 5 + 4
                words[idx] = encode(decode(words[idx]) * g)
    return b"".join(int(w).to_bytes(2, "little") for w in words)


def certify_packed(raw: bytes) -> tuple[float, bool]:
    """9x9 Morph x Q stability grid through the shipped packed interpolator."""
    cw = corner_words_from_bytes(raw)
    max_r = 0.0
    for mi in range(9):
        for qi in range(9):
            probe = packed_probe(cw, mi / 8.0, qi / 8.0)
            max_r = max(max_r, probe["max_pole_radius"])
            if probe["unstable_mask"] or probe["nonfinite_mask"]:
                return max_r, False
    return max_r, True


def corner_words_from_bytes(raw: bytes) -> dict[str, list[tuple[int, ...]]]:
    words = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, 240, 2)]
    return {lab: [tuple(words[(c * 6 + s) * 5:(c * 6 + s) * 5 + 5]) for s in range(6)]
            for c, lab in enumerate(["A", "B", "C", "D"])}


def journey_curves(raw: bytes, q: float) -> list[np.ndarray]:
    cw = corner_words_from_bytes(raw)
    curves = []
    for m in MORPHS:
        probe = packed_probe(cw, m, q)
        total = np.zeros_like(GRID)
        for b0, b1, b2, a1, a2 in probe["biquad"]:
            h = (b0 + b1 * _EJW + b2 * _EJW2) / (1.0 + a1 * _EJW + a2 * _EJW2)
            total += 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))
        curves.append(total)
    return curves


def journey_plot(name: str, raw: bytes, out_png: Path) -> dict[float, list[float]]:
    crowns = {}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, q, title in ((axes[0], 0.0, "Q0"), (axes[1], 1.0, "Q100")):
        curves = journey_curves(raw, q)
        crowns[q] = [float(c.max()) for c in curves]
        for m, c in zip(MORPHS, curves):
            ax.semilogx(GRID, c, lw=0.9, label=f"M{int(m * 100)}")
        ax.set(xlim=(20, 19500), ylim=(-60, 30), title=f"{name} — journey {title}")
        ax.grid(True, which="both", alpha=0.2)
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    return crowns


def process(src: Path, out_dir: Path) -> bool:
    name = src.name.replace(".registered_lanes.json", "")
    run = lambda *a: subprocess.run([sys.executable, "-m", "tools.register_lanes", *a],
                                    cwd=ROOT, capture_output=True, text=True)
    v = run("validate", str(src))
    if v.returncode != 0:
        print(f"REFUSED  {name} (validate)\n{(v.stdout + v.stderr).strip()}")
        return False
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / f"{name}.body240"
        p = run("pack", str(src), str(tmp))
        if p.returncode != 0 or not tmp.exists():
            print(f"REFUSED  {name} (pack/certify)\n{(p.stdout + p.stderr).strip()}")
            return False
        raw = tmp.read_bytes()
    framed = frame_l10(raw)
    max_r, stable = certify_packed(framed)  # framing changed bytes: re-certify
    if not stable:
        print(f"REFUSED  {name} (post-frame certify) maxR={max_r:.5f}")
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    out_body = out_dir / f"{name}.body240"
    crowns = journey_plot(name, framed, out_dir / f"{name}_journey.png")
    tmp2 = out_body.with_suffix(".body240.tmp")
    tmp2.write_bytes(framed)
    os.replace(tmp2, out_body)  # last known-good replaced only now
    fmt = lambda cs: "[" + " ".join(f"{c:+.1f}" for c in cs) + "]"
    print(f"CERTIFIED {name}  maxR {max_r:.5f}  crowns Q0 {fmt(crowns[0.0])}"
          f"  Q100 {fmt(crowns[1.0])} dB  -> {out_body}")
    return True


def main() -> None:
    args = sys.argv[1:]
    def opt(flag, default):
        return Path(args[args.index(flag) + 1]) if flag in args else Path(default)
    watch = (ROOT / opt("--watch", "bodies/drafts")).resolve() \
        if not opt("--watch", "bodies/drafts").is_absolute() else opt("--watch", "bodies/drafts")
    out = (ROOT / opt("--out", "bodies/candidates")).resolve() \
        if not opt("--out", "bodies/candidates").is_absolute() else opt("--out", "bodies/candidates")
    watch.mkdir(parents=True, exist_ok=True)
    pattern = "*.registered_lanes.json"
    if "--once" in args:
        files = sorted(watch.glob(pattern))
        if not files:
            sys.exit(f"no {pattern} in {watch}")
        ok = [process(f, out) for f in files]
        sys.exit(0 if all(ok) else 1)
    print(f"watching {watch} -> {out}  (Ctrl+C to stop)")
    seen: dict[Path, float] = {f: f.stat().st_mtime for f in watch.glob(pattern)}
    for f in sorted(seen):
        process(f, out)
    while True:
        time.sleep(0.25)
        for f in watch.glob(pattern):
            m = f.stat().st_mtime
            if seen.get(f) != m:
                seen[f] = m
                time.sleep(0.05)  # let the editor finish writing
                process(f, out)


if __name__ == "__main__":
    main()
