#!/usr/bin/env python3
"""Ablate packed bodies into zero-only, pole-only, and gain-only motion.

Clean-room study tool. It never ships vendor bodies; it reads local study bodies
or a generated body, derives temporary packed variants, then measures how much
Morph movement is explained by zero slots vs pole slots vs gain.

Verified slot order:
  c0/c1 = numerator zeros
  c2/c3 = denominator poles
  c4    = gain
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import packed_interp, trench_ffi  # noqa: E402
from pyruntime.encode import EncodedCoeffs  # noqa: E402
from pyruntime.freq_response import cascade_response_db, freq_points  # noqa: E402


CORNER_ORDER = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
KEYS = ("A", "B", "C", "D")
SR = 39062.5
OUT = ROOT / "dev" / "tmp" / "zero_dominance"


def words_from_body(raw: bytes) -> dict[str, list[tuple[int, ...]]]:
    if len(raw) != trench_ffi.BODY_BYTES:
        raise ValueError(f"body must be 240 bytes, got {len(raw)}")
    arr = np.frombuffer(raw, dtype="<u2").reshape(4, 6, 5)
    return {
        key: [tuple(int(v) for v in row) for row in arr[index]]
        for index, key in enumerate(KEYS)
    }


def kernels_from_words(words: dict[str, list[tuple[int, ...]]]) -> dict[str, list[tuple[float, ...]]]:
    return {
        key: [tuple(float(v) for v in packed_interp.words_to_coeffs(row)) for row in rows]
        for key, rows in words.items()
    }


def words_from_kernels(kernels: dict[str, list[tuple[float, ...]]]) -> dict[str, list[tuple[int, ...]]]:
    return {
        key: [tuple(int(v) for v in packed_interp.coeffs_to_words(*row)) for row in rows]
        for key, rows in kernels.items()
    }


def body_from_words(words: dict[str, list[tuple[int, ...]]]) -> bytes:
    return trench_ffi.body_bytes_from_corner_words(words)


def response(body: bytes, morph: float, secondary: float, freqs: np.ndarray) -> np.ndarray:
    rows = trench_ffi.packed_interpolate(body, morph, secondary)
    return cascade_response_db([EncodedCoeffs(*row) for row in rows], freqs, SR)


def rms_db(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def make_variant(kernels: dict[str, list[tuple[float, ...]]], mode: str) -> bytes:
    """Keep one slot family moving while others are pinned to corner A."""
    base = kernels["A"]
    out: dict[str, list[tuple[float, ...]]] = {}
    for key, rows in kernels.items():
        out_rows = []
        for stage_i, row in enumerate(rows):
            b = base[stage_i]
            if mode == "zeros_only":
                out_rows.append((row[0], row[1], b[2], b[3], b[4]))
            elif mode == "poles_only":
                out_rows.append((b[0], b[1], row[2], row[3], b[4]))
            elif mode == "gain_only":
                out_rows.append((b[0], b[1], b[2], b[3], row[4]))
            elif mode == "zeros_plus_gain":
                out_rows.append((row[0], row[1], b[2], b[3], row[4]))
            elif mode == "poles_plus_gain":
                out_rows.append((b[0], b[1], row[2], row[3], row[4]))
            else:
                raise ValueError(mode)
        out[key] = out_rows
    return body_from_words(words_from_kernels(out))


def explain_fraction(total: float, error_to_target: float) -> float:
    if total <= 1e-9:
        return 0.0
    return float(1.0 - error_to_target / total)


def analyze_body(path: Path, out_dir: Path, plot: bool) -> dict[str, Any]:
    raw = path.read_bytes()
    words = words_from_body(raw)
    kernels = kernels_from_words(words)
    original_body = body_from_words(words)
    freqs = freq_points()

    variants = {
        mode: make_variant(kernels, mode)
        for mode in ("zeros_only", "poles_only", "gain_only", "zeros_plus_gain", "poles_plus_gain")
    }

    rows = []
    for secondary in (0.0, 1.0):
        home = response(original_body, 0.0, secondary, freqs)
        target = response(original_body, 1.0, secondary, freqs)
        total = rms_db(target, home)
        row: dict[str, Any] = {
            "secondary": secondary,
            "original_morph_rms_db": round(total, 6),
        }
        for mode, body in variants.items():
            moved = response(body, 1.0, secondary, freqs)
            movement = rms_db(moved, home)
            error = rms_db(moved, target)
            row[mode] = {
                "movement_rms_db": round(movement, 6),
                "error_to_original_away_rms_db": round(error, 6),
                "explained_fraction": round(explain_fraction(total, error), 6),
                "movement_ratio": round(movement / total, 6) if total > 1e-9 else 0.0,
            }
        rows.append(row)

    grid_rows = []
    for mode, body in variants.items():
        max_radius = 0.0
        unstable = 0
        nonfinite = 0
        for morph in np.linspace(0.0, 1.0, 5):
            for secondary in np.linspace(0.0, 1.0, 5):
                probe = trench_ffi.packed_probe(body, float(morph), float(secondary))
                max_radius = max(max_radius, float(probe["max_pole_radius"]))
                unstable |= int(probe["unstable_mask"])
                nonfinite |= int(probe["nonfinite_mask"])
        grid_rows.append({
            "mode": mode,
            "max_pole_radius": round(max_radius, 9),
            "unstable_mask": unstable,
            "nonfinite_mask": nonfinite,
        })

    summary = {
        "body": str(path.relative_to(ROOT)).replace("\\", "/") if path.is_relative_to(ROOT) else str(path),
        "body_sha256": __import__("hashlib").sha256(raw).hexdigest(),
        "runtime": str(trench_ffi.lib_path()),
        "result": rows,
        "variant_audit": grid_rows,
    }

    if plot:
        plot_body(path.stem, original_body, variants, freqs, out_dir / f"{path.stem}.png")
        summary["plot"] = f"{path.stem}.png"
    return summary


def plot_body(name: str, original: bytes, variants: dict[str, bytes], freqs: np.ndarray, out: Path) -> None:
    curves = {
        "original home": response(original, 0.0, 0.0, freqs),
        "original away": response(original, 1.0, 0.0, freqs),
        "zeros only": response(variants["zeros_only"], 1.0, 0.0, freqs),
        "poles only": response(variants["poles_only"], 1.0, 0.0, freqs),
        "gain only": response(variants["gain_only"], 1.0, 0.0, freqs),
    }
    ref = float(np.max(curves["original away"]))
    colors = {
        "original home": "#889088",
        "original away": "#f6f1b5",
        "zeros only": "#ff5f6d",
        "poles only": "#65c8ff",
        "gain only": "#a58bff",
    }
    fig, ax = plt.subplots(figsize=(10.8, 5.8), facecolor="#070a09")
    ax.set_facecolor("#090d0c")
    for label, curve in curves.items():
        ax.semilogx(freqs, np.clip(curve - ref, -70, 16), color=colors[label], lw=1.7, label=label)
    ax.set_xlim(20, 20000)
    ax.set_ylim(-70, 16)
    ax.grid(True, which="both", color="#26342f", alpha=0.42, linewidth=0.55)
    ax.tick_params(colors="#a7b4ad", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#25352e")
    ax.set_title(f"{name}: zero/pole/gain ablation at Morph 1, Secondary 0", color="#e9efe9")
    ax.set_xlabel("frequency Hz", color="#a7b4ad")
    ax.set_ylabel("dB, normalized to original away peak", color="#a7b4ad")
    ax.legend(facecolor="#101713", edgecolor="#27372f", labelcolor="#e9efe9", fontsize=8)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=125)
    plt.close(fig)


def write_index(out_dir: Path, report: dict[str, Any]) -> None:
    cards = []
    for item in report["bodies"]:
        plot = item.get("plot")
        metrics = item["result"][0]
        cards.append(
            "<section>"
            f"<h2>{item['body']}</h2>"
            f"{'<img src=' + json.dumps(plot) + '>' if plot else ''}"
            "<pre>"
            + json.dumps(metrics, indent=2)
            + "</pre></section>"
        )
    html = """<!doctype html><meta charset=utf-8>
<title>zero dominance ablation</title>
<style>
body{background:#070a09;color:#d7ded9;font:14px/1.45 system-ui,sans-serif;margin:24px}
img{max-width:100%;border:1px solid #26342f}
pre{background:#101713;color:#a7f0c1;padding:12px;overflow:auto}
section{margin-bottom:30px}
</style>
<h1>Zero Dominance Ablation</h1>
""" + "\n".join(cards)
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def default_bodies(limit_p2k: int) -> list[Path]:
    paths = [ROOT / "dev" / "tmp" / "verified_body_forge" / "cleanroom_macro_pole_forge" / "cleanroom_macro_pole_forge.body240"]
    paths.extend(sorted((ROOT / "ref" / "presets").glob("P2k_*.bin"))[:limit_p2k])
    return [path for path in paths if path.exists()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Test whether zeros or poles dominate Morph identity")
    parser.add_argument("bodies", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--limit-p2k", type=int, default=12)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()

    if not trench_ffi.available():
        raise SystemExit("trench-core unavailable; build with cargo build --release -p trench-core")

    bodies = args.bodies or default_bodies(args.limit_p2k)
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "zero-dominance-ablation-v1",
        "clean_room_note": "Derived variants are study-only. Slot families are ablated using verified packed decode semantics.",
        "bodies": [analyze_body(path, args.out, not args.no_plots) for path in bodies],
    }
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_index(args.out, report)

    print(f"wrote {args.out / 'report.json'}")
    print(f"open {args.out / 'index.html'}")
    for item in report["bodies"][:8]:
        q0 = item["result"][0]
        z = q0["zeros_only"]["explained_fraction"]
        p = q0["poles_only"]["explained_fraction"]
        g = q0["gain_only"]["explained_fraction"]
        print(f"{Path(item['body']).name}: Q0 explained zeros={z:+.3f} poles={p:+.3f} gain={g:+.3f}")


if __name__ == "__main__":
    main()
