"""Compare two packed .body240 bodies through the runtime-decoded response."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from tools.prove_master_body import ENGINE_SR, response_db


POINTS = [
    ("M0_Q0", 0.0, 0.0, "#5b9bd5"),
    ("M100_Q0", 1.0, 0.0, "#e0555f"),
    ("M0_Q100", 0.0, 1.0, "#5bef6f"),
    ("M100_Q100", 1.0, 1.0, "#ffd23e"),
    ("MID_Q0", 0.5, 0.0, "#ffffff"),
    ("MID_Q100", 0.5, 1.0, "#d7a7ff"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("boosted", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    original = args.original.read_bytes()
    boosted = args.boosted.read_bytes()
    freqs = np.geomspace(20.0, ENGINE_SR / 2.0, 2048)
    rows = []
    for label, morph, q, colour in POINTS:
        base = response_db(original, morph, q, freqs)
        trial = response_db(boosted, morph, q, freqs)
        rows.append((label, morph, q, colour, base, trial, trial - base))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(12.0, 8.0), dpi=160, sharex=True)
    fig.patch.set_facecolor("#0e1512")
    for ax in axes:
        ax.set_facecolor("#0e1512")
        ax.grid(True, which="both", color="#31443a", alpha=0.35, linewidth=0.5)
        ax.tick_params(colors="#d8e2dc")
        for spine in ax.spines.values():
            spine.set_color("#53665b")

    all_responses = np.concatenate([np.concatenate((row[4], row[5])) for row in rows])
    response_lo = float(np.floor(np.min(all_responses) / 5.0) * 5.0 - 5.0)
    response_hi = float(np.ceil(np.max(all_responses) / 5.0) * 5.0 + 5.0)
    axes[0].set_ylim(response_lo, response_hi)
    for label, _morph, _q, colour, base, trial, delta in rows:
        axes[0].semilogx(freqs, base, color=colour, linestyle="--", linewidth=1.0,
                         alpha=0.65, label=f"{label} original")
        axes[0].semilogx(freqs, trial, color=colour, linestyle="-", linewidth=1.2,
                         label=f"{label} r+0.010")
        axes[1].semilogx(freqs, delta, color=colour, linewidth=1.1, label=label)

    axes[0].set_ylabel("Response (dB)", color="#d8e2dc")
    axes[0].set_title("Packed/runtime-decoded comparison — dashed original, solid radius boost",
                      color="#d8e2dc")
    axes[0].legend(loc="upper right", ncol=2, fontsize=7)
    axes[1].axhline(0.0, color="#aab7ae", linewidth=0.8)
    axes[1].set_ylim(-2.0, max(12.0, float(np.max([np.max(row[6]) for row in rows]) + 1.0)))
    axes[1].set_ylabel("Boost − original (dB)", color="#d8e2dc")
    axes[1].set_xlabel("Frequency (Hz)", color="#d8e2dc")
    axes[1].legend(loc="upper right", ncol=3, fontsize=8)
    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, facecolor=fig.get_facecolor())
    plt.close(fig)

    max_delta = max(float(np.max(np.abs(row[6]))) for row in rows)
    print(f"wrote {args.out}")
    print(f"max absolute response delta: {max_delta:.6f} dB")
    for label, _morph, _q, _colour, _base, _trial, delta in rows:
        index = int(np.argmax(np.abs(delta)))
        print(f"{label}: peak delta {delta[index]:+.6f} dB at {freqs[index]:.2f} Hz; "
              f"RMS delta {np.sqrt(np.mean(delta * delta)):.6f} dB")


if __name__ == "__main__":
    main()
