#!/usr/bin/env python3
"""Plot representative generated DF2 bodies through the shipped packed runtime."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

import audit_generated_presets as audit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dev" / "tmp" / "generated_preset_audit"
COLORS = ("#ffb02e", "#45e06f", "#31cbd3", "#ff4c43")
POSITIONS = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
LABELS = ("M0/S0", "M1/S0", "M0/S1", "M1/S1")
REPRESENTATIVES = (
    ("early_direct_packed", "Scream", "early: shaped but conservative"),
    ("early_direct_packed", "search_03", "early search: center collapse"),
    ("crazy", "crazy_01", "crazy: generic / under-moving"),
    ("vocal_low_to_high", "Ah -> Ee", "vocal rack: sparse cavities"),
    ("non_formant", "Gong (bloom up)", "modal rack: cliff"),
    ("hybrids", "throat_glass", "hybrid: over-carved"),
    ("juce_custom:voice walk", "Voice Walk", "JUCE custom: partial zeros"),
    ("juce_custom:maul", "Maul", "JUCE custom: stronger contour"),
)


def load_bodies() -> dict[tuple[str, str], tuple[bytes, dict]]:
    found: dict[tuple[str, str], tuple[bytes, dict]] = {}
    seen: set[str] = set()
    for path in audit.candidate_paths(False):
        loaded = audit.cart_bytes(path)
        if loaded is None:
            continue
        raw, doc = loaded
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        key = (audit.group_for(path, doc), str(doc.get("name", path.stem)))
        found[key] = (raw, doc)
    return found


def load_rows() -> dict[tuple[str, str], dict]:
    with (OUT / "bodies.csv").open(encoding="utf-8") as handle:
        return {(row["group"], row["name"]): row for row in csv.DictReader(handle)}


def plot_body(ax: plt.Axes, raw: bytes, title: str, row: dict) -> None:
    for color, label, (morph, secondary) in zip(COLORS, LABELS, POSITIONS):
        state = audit.state_metrics(raw, morph, secondary)
        ax.plot(audit.FREQS, np.clip(state["db"], -140.0, 20.0), color=color, lw=1.2, label=label)
    center = audit.state_metrics(raw, 0.5, 0.5)
    ax.plot(audit.FREQS, np.clip(center["db"], -140.0, 20.0), color="#f2f2ed", lw=1.7, label="center")
    ax.set_xscale("log")
    ax.set_xlim(40.0, 16000.0)
    ax.set_ylim(-140.0, 20.0)
    ax.grid(True, which="major", alpha=0.14, lw=0.6)
    ax.grid(True, which="minor", alpha=0.05, lw=0.4)
    ax.set_title(title, color="#f2f2ed", fontsize=9, loc="left", pad=6)
    ax.text(
        0.01,
        0.03,
        f"morph {float(row['morph_contrast_rms_db']):.1f} dB  "
        f"sec {float(row['secondary_contrast_rms_db']):.1f} dB  "
        f"center span {float(row['center_span_db']):.1f} dB",
        transform=ax.transAxes,
        color="#b9c3be",
        fontsize=7,
    )


def main() -> None:
    bodies = load_bodies()
    rows = load_rows()
    fig, axes = plt.subplots(4, 2, figsize=(15, 16), sharex=True, sharey=True)
    fig.patch.set_facecolor("#080d0c")
    for ax, (group, name, label) in zip(axes.flat, REPRESENTATIVES):
        ax.set_facecolor("#080d0c")
        for spine in ax.spines.values():
            spine.set_color("#40514d")
        ax.tick_params(colors="#b9c3be", labelsize=7)
        raw, _ = bodies[(group, name)]
        plot_body(ax, raw, label, rows[(group, name)])
    axes[0, 0].legend(loc="lower left", ncol=5, fontsize=6, framealpha=0.2)
    for ax in axes[:, 0]:
        ax.set_ylabel("dB", color="#b9c3be", fontsize=8)
    for ax in axes[-1, :]:
        ax.set_xlabel("frequency (Hz)", color="#b9c3be", fontsize=8)
    fig.suptitle(
        "DF2 GENERATED PRESET FAILURE AUDIT  |  packed runtime probe  |  four corners + bilinear center",
        color="#f2f2ed",
        fontsize=13,
        y=0.995,
    )
    fig.text(
        0.5,
        0.006,
        "Shared -140..+20 dB scale. White = packed bilinear center. "
        "This is diagnosis only; no reference coefficients are plotted.",
        ha="center",
        color="#b9c3be",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.02, 0.025, 0.99, 0.978))
    path = OUT / "representative_failure_sheet.png"
    fig.savefig(path, dpi=180, facecolor=fig.get_facecolor())
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
