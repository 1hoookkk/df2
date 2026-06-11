#!/usr/bin/env python
"""Visualize the verified table-AGC wrap behavior without copying table values.

The AGC curve is read from `pyruntime.trench_ffi.agc_table()`, whose source of
truth is the Rust core. This script emits behavior plots and summary metrics,
not the table itself.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi


DEFAULT_SR = 39_062.5
DEFAULT_OUT = Path("dev/tmp/agc_wrap_visualizer")


def active_table(base: np.ndarray, sample_rate: float) -> np.ndarray:
    """Mirror the verified sample-rate law in trench-core/src/agc.rs."""
    sqrt_count = 2 if sample_rate > 130_000.0 else 1 if sample_rate > 65_000.0 else 0
    table = base.astype(np.float32).copy()
    for _ in range(sqrt_count):
        table = np.sqrt(table, dtype=np.float32)
    return table


def agc_trace(
    table: np.ndarray,
    sample_rate: float,
    duration_s: float,
    tone_hz: float,
    peak_domain: float,
) -> dict[str, np.ndarray]:
    n = int(round(sample_rate * duration_s))
    t = np.arange(n, dtype=np.float64) / sample_rate

    # A swell plus a short shock. The shock shows the exact "transient crosses
    # 16 while gain is still high" case; the swell shows the stateful recovery.
    swell_peak = peak_domain * 0.55
    env_up = 0.35 + (swell_peak - 0.35) * np.sin(np.pi * np.minimum(t / (duration_s * 0.58), 1.0) / 2.0) ** 2
    env_down = swell_peak - (swell_peak - 0.20) * np.sin(
        np.pi * np.maximum((t - duration_s * 0.58) / (duration_s * 0.42), 0.0) / 2.0
    ) ** 2
    env = np.where(t < duration_s * 0.58, env_up, env_down)
    x = env * np.sin(2.0 * np.pi * tone_hz * t)
    spike_i = min(len(x) - 4, max(0, int(round(duration_s * 0.04 * sample_rate))))
    x[spike_i] = 32.0
    x[spike_i + 1] = 16.0
    x[spike_i + 2] = 15.0

    gain = np.float32(1.0)
    out = np.empty_like(x, dtype=np.float32)
    gains = np.empty_like(x, dtype=np.float32)
    raw_idx = np.empty_like(x, dtype=np.uint32)
    idx = np.empty_like(x, dtype=np.uint32)

    for i, sample in enumerate(x.astype(np.float32)):
        product = np.float32(gain * abs(sample))
        raw = np.uint32(product)
        wrapped = raw & np.uint32(0xF)
        new_gain = np.float32(gain * table[int(wrapped)])
        gain = new_gain if new_gain < np.float32(1.0) else np.float32(1.0)
        out[i] = np.float32(sample * gain)
        gains[i] = gain
        raw_idx[i] = raw
        idx[i] = wrapped

    return {
        "t": t,
        "input": x.astype(np.float32),
        "output": out,
        "gain": gains,
        "raw_idx": raw_idx,
        "idx": idx,
        "env": env.astype(np.float32),
    }


def recovery_time_seconds(table: np.ndarray, sample_rate: float) -> float | None:
    recovery = float(table[0])
    if recovery <= 1.0:
        return None
    return math.log(2.0) / math.log(recovery) / sample_rate


def make_plot(trace: dict[str, np.ndarray], sample_rate: float, out_png: Path) -> None:
    t_ms = trace["t"] * 1000.0
    raw_idx = trace["raw_idx"]
    wrapped = raw_idx >= 16

    mag = np.linspace(0.0, 48.0, 960)
    idx_map = (mag.astype(np.uint32) & np.uint32(0xF)).astype(np.int32)

    fig = plt.figure(figsize=(13.5, 9.0), constrained_layout=True)
    axes = fig.subplot_mosaic(
        [
            ["map", "map"],
            ["gain", "idx"],
            ["wave", "wave"],
        ],
        height_ratios=[1.0, 1.1, 1.3],
    )

    ax = axes["map"]
    ax.step(mag, idx_map, where="post", color="#1f6f77", linewidth=1.8)
    ax.axvspan(0, 2, color="#94d2bd", alpha=0.20, label="recovery/pass zone")
    for start in range(16, 49, 16):
        ax.axvline(start, color="#c1121f", alpha=0.55, linewidth=1.0)
    ax.set_title("AGC index wraps every 16 integer-magnitude units")
    ax.set_xlabel("gain * abs(sample) in AGC domain")
    ax.set_ylabel("table index")
    ax.set_yticks(range(16))
    ax.set_xlim(0, 48)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right", frameon=False)

    ax = axes["gain"]
    gain_db = 20.0 * np.log10(np.maximum(trace["gain"], 1e-12))
    ax.plot(t_ms, gain_db, color="#2d3142", linewidth=1.2)
    ax.scatter(t_ms[wrapped], gain_db[wrapped], s=4, color="#c1121f", alpha=0.45, label="wrapped samples")
    ax.set_title("Stateful gain follows the wrapped index")
    ax.set_xlabel("time (ms)")
    ax.set_ylabel("AGC gain (dB)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower left", frameon=False)

    ax = axes["idx"]
    dec = max(1, len(t_ms) // 3500)
    ax.plot(t_ms[::dec], trace["idx"][::dec], color="#7f4f24", linewidth=0.9)
    ax.scatter(t_ms[wrapped][:: max(1, wrapped.sum() // 1200)], trace["idx"][wrapped][:: max(1, wrapped.sum() // 1200)],
               s=6, color="#c1121f", alpha=0.55)
    ax.set_title("Wrapped index, not clamped index")
    ax.set_xlabel("time (ms)")
    ax.set_ylabel("index")
    ax.set_yticks(range(16))
    ax.grid(True, alpha=0.25)

    ax = axes["wave"]
    wrap_positions = np.flatnonzero(wrapped)
    if len(wrap_positions):
        center = int(wrap_positions[len(wrap_positions) // 2])
    else:
        center = len(t_ms) // 2
    half = int(sample_rate * 0.012)
    lo = max(0, center - half)
    hi = min(len(t_ms), center + half)
    scale = max(float(np.max(np.abs(trace["input"][lo:hi]))), 1e-6)
    ax.plot(t_ms[lo:hi], trace["input"][lo:hi] / scale, color="#9a9a9a", linewidth=1.0, label="pre-AGC domain, normalized")
    ax.plot(t_ms[lo:hi], trace["output"][lo:hi] / scale, color="#005f73", linewidth=1.3, label="post-AGC, same scale")
    local_wrapped = wrapped[lo:hi]
    if np.any(local_wrapped):
        xw = t_ms[lo:hi][local_wrapped]
        yw = (trace["output"][lo:hi] / scale)[local_wrapped]
        ax.scatter(xw, yw, s=10, color="#c1121f", alpha=0.65, label="wrap")
    ax.set_title("Waveform window around wrap engagement")
    ax.set_xlabel("time (ms)")
    ax.set_ylabel("normalized amplitude")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right", frameon=False)

    fig.suptitle("Verified AGC Wrap Visualizer", fontsize=16, fontweight="bold")
    fig.savefig(out_png, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-rate", type=float, default=DEFAULT_SR)
    parser.add_argument("--duration", type=float, default=0.75)
    parser.add_argument("--tone", type=float, default=110.0)
    parser.add_argument("--peak-domain", type=float, default=34.0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    table = active_table(np.asarray(trench_ffi.agc_table(), dtype=np.float32), args.sample_rate)
    trace = agc_trace(table, args.sample_rate, args.duration, args.tone, args.peak_domain)

    out_png = args.out / "agc_wrap.png"
    make_plot(trace, args.sample_rate, out_png)

    raw = trace["raw_idx"]
    wrapped = raw >= 16
    unique_wrapped = sorted(int(v) for v in np.unique(raw[wrapped]))
    report = {
        "provenance": {
            "agc_curve_source": "pyruntime.trench_ffi.agc_table() -> trench-core BASE_AGC_TABLE",
            "table_values_exported": False,
            "body_or_preset_data_used": False,
        },
        "observed_structure": {
            "index_formula": "idx = int(gain * abs(sample)) & 0xF",
            "index_count": 16,
            "sample_rate_law": "base <= 65000 Hz, sqrt above 65000 Hz, fourth-root above 130000 Hz",
            "state_update": "gain = min(gain * table[idx], 1.0)",
        },
        "simulation": {
            "sample_rate": args.sample_rate,
            "tone_hz": args.tone,
            "duration_s": args.duration,
            "peak_agc_domain": args.peak_domain,
            "wrapped_sample_fraction": float(np.mean(wrapped)),
            "max_unwrapped_integer_index_seen": int(np.max(raw)),
            "wrapped_integer_indices_seen": unique_wrapped[:48],
            "min_gain_db": float(20.0 * np.log10(max(float(np.min(trace["gain"])), 1e-12))),
            "gain_doubling_recovery_s": recovery_time_seconds(table, args.sample_rate),
        },
        "outputs": {
            "plot": str(out_png),
        },
    }
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(out_png)


if __name__ == "__main__":
    main()
