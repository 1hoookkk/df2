#!/usr/bin/env python3
"""Phase-1 knowledge-layer slice: author a vowel MORPH straight from the tables.

Composes two dormant tables + two behavioral laws into one legal .body240:
  - klatt_1980_formants.json   -> pole center frequencies (F1..F3)   [phonetic SEED]
  - klatt_1980_bandwidths.json -> pole radius via r = exp(-pi*BW/SR)  [physical law]
  - Q scene                    -> baseline damping plus one explicit sentinel-stage wake
  - law_author.unity_dc_gain   -> per-lane gain staging               [gain-staging law]

It authors the four corners DIRECTLY (all-pole vowel ridges, Klatt is all-pole),
then reuses df2's proven pack -> body240 -> stages.json path. The morph axis runs
vowel A (M0) -> vowel B (M100). Q100 is a second authored scene: it tightens the
existing lanes and wakes one identity-sentinel lane at the measured F2 position.

Output: a body240 + stages.json editable sidecar (drop-in for the painter's
Verified-Editable START lane) + a verification plot with the Klatt formant
frequencies marked, so we can SEE the peaks land before wiring it into START.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DF2 = Path(r"C:\Users\hooki\df2")
TABLES = Path(r"C:\Users\hooki\trench-filters\data\tables")
if str(DF2) not in sys.path:
    sys.path.insert(0, str(DF2))

# law_author inserts df2 on sys.path and carries every helper we need.
from tools import law_author as la  # noqa: E402
from tools.author_lanes import AUTHORING_SR, body_to_packed_v1  # noqa: E402
from tools import author_body  # noqa: E402
from pyruntime import trench_ffi  # noqa: E402

SR = AUTHORING_SR
Q100_TIGHTEN = 0.35       # r -> 1-(1-r)*0.35; Q100 is allowed to bloom
BASELINE_RADIUS_MAX = 0.98  # Q0 headroom; raw/source radii are not changed here
RUNTIME_RADIUS_MAX = 0.9988  # final authoring/runtime safety ceiling
TRAILING_ZERO_OCTAVES = -0.6  # one trailing zero below the F1/throat pole
TRAILING_ZERO_RADIUS = 0.98
Q100_WAKE_STAGE = 3        # first identity-sentinel lane after F1..F3
Q100_WAKE_FORMANT = 1      # wake it at the existing F2 peak, not a made-up frequency
STAGE_ROLES = (
    "vowel body / F1 + trailing zero",
    "vowel body / F2",
    "presence / F3",
    "Q wake reserve",
    "upper-mid reserve",
    "throat / floor",
)

# Klatt formant table keys by IPA (a e o u); bandwidth table keys by i/a/u.
# Vowels with BOTH a Klatt formant AND a Klatt bandwidth entry: ah(a), oo(u).
VOWELS = {
    "ah": {"formant_ipa": "a", "bw_key": "a"},
    "oo": {"formant_ipa": "u", "bw_key": "u"},
}
FORMANT_SLOTS = ("f1", "f2", "f3")
BW_SLOTS = ("B1", "B2", "B3")

FREQS = np.geomspace(60.0, SR * 0.49, 700)


def load_vowel(name: str) -> dict:
    if name not in VOWELS:
        raise SystemExit(f"vowel '{name}' unsupported here (have {list(VOWELS)}); "
                         "ee/i needs Peterson-Barney vowel_formants.json, a later slice.")
    fdoc = json.loads((TABLES / "klatt_1980_formants.json").read_text())
    bdoc = json.loads((TABLES / "klatt_1980_bandwidths.json").read_text())
    ipa = VOWELS[name]["formant_ipa"]
    frow = next(v for v in fdoc["vowels"] if v["ipa"] == ipa)["klatt"]
    brow = bdoc["vowels"][VOWELS[name]["bw_key"]]
    formants = [float(frow[s]) for s in FORMANT_SLOTS]
    bandwidths = [float(brow[s]) for s in BW_SLOTS]
    return {"name": name, "formants": formants, "bandwidths": bandwidths}


def r_from_bw(bw_hz: float) -> float:
    """Physical law from klatt_1980_bandwidths.json header: r = exp(-pi*BW/SR)."""
    return min(math.exp(-math.pi * float(bw_hz) / SR), BASELINE_RADIUS_MAX)


def q100_radius(baseline_radius: float) -> float:
    """Open a damped baseline lane for Q100 without touching its source centre."""
    return min(1.0 - (1.0 - baseline_radius) * Q100_TIGHTEN, RUNTIME_RADIUS_MAX)


def active_lane(**kwargs) -> dict:
    row = la.lane(**kwargs)
    row["state"] = "active"
    return row


def identity_lane(role: str) -> dict:
    """Exact packed sentinel: one serialized section with unity response."""
    return {
        "pole_hz": 0.0,
        "pole_r": 0.0,
        "zero_hz": 0.0,
        "zero_r": 0.0,
        "gain": 1.0,
        "role": role,
        "state": "identity",
    }


def formant_lanes(formants, bandwidths, q100: bool) -> list[dict]:
    """Six named lanes: active formants plus explicit identity sentinels."""
    rows = []
    for i, (fhz, bw) in enumerate(zip(formants, bandwidths)):
        baseline_r = r_from_bw(bw)
        r = q100_radius(baseline_r) if q100 else baseline_r
        # The first lane carries the explicit trailing zero below the F1/throat pole.
        # Other vowel lanes keep the shallow co-located zero used by the table author.
        zero_hz = fhz * 2.0 ** TRAILING_ZERO_OCTAVES if i == 0 else fhz
        zero_r = TRAILING_ZERO_RADIUS if i == 0 else 0.30
        gain = la.unity_dc_gain(fhz, r, zero_hz, zero_r)
        rows.append(active_lane(pole_hz=fhz, pole_q=None, zero_hz=zero_hz, zero_r=zero_r,
                                gain=gain, role=STAGE_ROLES[i], pole_r=r))
    while len(rows) < la.STAGES:  # every slot is serialized; unused slots are exact identity
        if q100 and len(rows) == Q100_WAKE_STAGE:
            # Q must change the topology visibly. Reuse an existing table peak (F2)
            # rather than inventing a new frequency: the parked lane becomes an
            # additional active F2 resonance only in the authored Q100 scene.
            wake_hz = float(formants[Q100_WAKE_FORMANT])
            wake_r = q100_radius(r_from_bw(bandwidths[Q100_WAKE_FORMANT]))
            wake_zero_hz, wake_zero_r = wake_hz, 0.30
            wake_gain = la.unity_dc_gain(wake_hz, wake_r, wake_zero_hz, wake_zero_r)
            rows.append(active_lane(pole_hz=wake_hz, pole_q=None, zero_hz=wake_zero_hz,
                                    zero_r=wake_zero_r, gain=wake_gain,
                                    role="Q100 wake F2", pole_r=wake_r))
        else:
            rows.append(identity_lane(f"{STAGE_ROLES[len(rows)]} (sentinel)"))
    return rows


def build_corners(vowel_a: dict, vowel_b: dict) -> dict:
    return {
        "M0_S0": formant_lanes(vowel_a["formants"], vowel_a["bandwidths"], q100=False),
        "M1_S0": formant_lanes(vowel_b["formants"], vowel_b["bandwidths"], q100=False),
        "M0_S1": formant_lanes(vowel_a["formants"], vowel_a["bandwidths"], q100=True),
        "M1_S1": formant_lanes(vowel_b["formants"], vowel_b["bandwidths"], q100=True),
    }


def pack(name: str, corners: dict, out_dir: Path) -> tuple[bytes, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    body_doc = body_to_packed_v1(name, corners, boost=1.0, sr=SR)
    packed_source = out_dir / "packed-body-v1.json"
    packed_source.write_text(json.dumps(body_doc, indent=2) + "\n", encoding="utf-8")
    (out_dir / "stages.json").write_text(json.dumps(corners, indent=2) + "\n", encoding="utf-8")
    pname, boost, words = author_body.load_packed_words(packed_source)
    cart = author_body.compiled_payload(pname, boost, words)
    cart["provenance"] = "vowel-from-tables-v3"
    cart["sourceTables"] = ["klatt_1980_formants.json", "klatt_1980_bandwidths.json"]
    cart["authoringRules"] = {
        "baselineRadiusMax": BASELINE_RADIUS_MAX,
        "q100RadiusRule": "1-(1-r)*0.35",
        "trailingZero": {
            "lane": "F1",
            "octavesBelowPole": abs(TRAILING_ZERO_OCTAVES),
            "radius": TRAILING_ZERO_RADIUS,
        },
        "q100Wake": {
            "stage": Q100_WAKE_STAGE,
            "target": "F2",
            "mode": "identity sentinel becomes an additional active F2 peak",
        },
        "identitySentinel": {
            "pole": {"hz": 0.0, "r": 0.0},
            "zero": {"hz": 0.0, "r": 0.0},
            "scale": 1.0,
        },
        "stageRoles": list(STAGE_ROLES),
    }
    (out_dir / f"{name}.cartridge.json").write_text(json.dumps(cart, indent=2) + "\n", encoding="utf-8")
    body = author_body.raw_from_words(words)
    body_path = out_dir / f"{name}.body240"
    body_path.write_bytes(body)
    return body, body_path


def response_db(body: bytes, morph: float, q: float) -> np.ndarray:
    probe = trench_ffi.packed_probe(body, morph, q)
    total = np.zeros_like(FREQS)
    w = 2.0 * np.pi * FREQS / SR
    z1, z2 = np.exp(-1j * w), np.exp(-2j * w)
    for b0, b1, b2, a1, a2 in probe["biquad"]:
        num = b0 + b1 * z1 + b2 * z2
        den = 1.0 + a1 * z1 + a2 * z2
        total += 20.0 * np.log10(np.maximum(np.abs(num) / np.maximum(np.abs(den), 1e-12), 1e-12))
    return total, probe


def nearest_peak_hz(db: np.ndarray, target_hz: float, tol_ratio: float = 0.18) -> float:
    lo, hi = target_hz * (1 - tol_ratio), target_hz * (1 + tol_ratio)
    band = (FREQS >= lo) & (FREQS <= hi)
    if not band.any():
        return float("nan")
    idx = np.where(band)[0]
    return float(FREQS[idx[int(np.argmax(db[idx]))]])


def verify_and_plot(body: bytes, vowel_a: dict, vowel_b: dict, out_png: Path) -> dict:
    corners = [("M0_Q0  " + vowel_a["name"], 0.0, 0.0, vowel_a, "#63d7ff"),
               ("M100_Q0  " + vowel_b["name"], 1.0, 0.0, vowel_b, "#ff8b6b"),
               ("M0_Q100  " + vowel_a["name"] + " wake", 0.0, 1.0, vowel_a, "#af9cff"),
               ("M100_Q100  " + vowel_b["name"] + " wake", 1.0, 1.0, vowel_b, "#96e6bf")]
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), facecolor="#070908")
    axes = axes.flatten()
    report = {"vowel_a": vowel_a["name"], "vowel_b": vowel_b["name"], "landings": [], "max_pole_r": 0.0,
              "unstable": False}
    for ax, (title, m, q, vw, col) in zip(axes, corners):
        ax.set_facecolor("#0c100e")
        ax.grid(True, which="both", color="#26352e", alpha=0.35, lw=0.5)
        ax.tick_params(colors="#a8b5ad", labelsize=8)
        for s in ax.spines.values():
            s.set_color("#2e3d35")
        db, probe = response_db(body, m, q)
        report["max_pole_r"] = max(report["max_pole_r"], float(probe["max_pole_radius"]))
        report["unstable"] = report["unstable"] or int(probe["unstable_mask"]) != 0
        ax.semilogx(FREQS, np.clip(db, -48, 48), color=col, lw=1.7)
        if vw is not None:
            for i, fhz in enumerate(vw["formants"]):
                ax.axvline(fhz, color="#e6d7a7", lw=1.0, ls="--", alpha=0.8)
                got = nearest_peak_hz(db, fhz)
                err = (got - fhz) / fhz * 100.0 if got == got else float("nan")
                ax.text(fhz, 44, f"F{i+1}\n{fhz:.0f}", color="#e6d7a7", fontsize=7,
                        ha="center", va="top")
                ax.text(fhz, -42, f"got {got:.0f}\n{err:+.1f}%", color=col, fontsize=6.5,
                        ha="center", va="bottom")
                report["landings"].append({"corner": title.strip(), "formant": f"F{i+1}",
                                           "target_hz": fhz, "peak_hz": got,
                                           "err_pct": round(err, 2)})
        ax.set_title(title, color="#edf3ee", fontsize=11)
        ax.set_xlim(60, SR * 0.49)
        ax.set_ylim(-48, 48)
        ax.set_xlabel("Hz", color="#a8b5ad", fontsize=8)
    worst = max((abs(l["err_pct"]) for l in report["landings"] if l["err_pct"] == l["err_pct"]),
                default=float("nan"))
    fig.suptitle(f"vowel from Klatt tables — {vowel_a['name']}→{vowel_b['name']} morph  ·  "
                 f"peaks vs table freqs (dashed)  ·  worst landing {worst:.1f}%  ·  "
                 f"max|pole| {report['max_pole_r']:.5f}  ·  {'UNSTABLE' if report['unstable'] else 'stable'}",
                 color="#edf3ee", fontsize=12)
    fig.text(0.01, 0.005, "trench_ffi.packed_probe @ 39062.5 Hz · four authored corners · "
             "Q0 r≤0.98 · Q100 wake at F2 · F1 trailing zero −0.6 oct · gain=unity_dc_gain",
             color="#6f7f75", fontsize=7)
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.savefig(out_png, dpi=120, facecolor="#070908")
    plt.close(fig)
    report["worst_landing_pct"] = None if worst != worst else round(worst, 2)
    return report


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", default="oo", help="morph-start vowel (default oo)")
    ap.add_argument("--b", default="ah", help="morph-end vowel (default ah)")
    ap.add_argument("--out", type=Path,
                    default=DF2 / "dev" / "tmp" / "vowel_from_tables")
    args = ap.parse_args(argv)
    if not trench_ffi.available():
        raise SystemExit("trench_core packed probe unavailable; build -p trench-core")
    va, vb = load_vowel(args.a), load_vowel(args.b)
    name = f"vowel_{va['name']}_to_{vb['name']}"
    out_dir = args.out / name
    corners = build_corners(va, vb)
    body, body_path = pack(name, corners, out_dir)
    report = verify_and_plot(body, va, vb, out_dir / "verify.png")
    (out_dir / "verify.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"body    -> {body_path} ({body_path.stat().st_size} bytes)")
    print(f"stages  -> {out_dir / 'stages.json'}")
    print(f"plot    -> {out_dir / 'verify.png'}")
    print(f"worst landing error: {report['worst_landing_pct']}%  |  max pole r "
          f"{report['max_pole_r']:.6f}  |  {'UNSTABLE' if report['unstable'] else 'stable'}")
    for l in report["landings"]:
        print(f"  {l['corner']:<22} {l['formant']} target {l['target_hz']:>6.0f}  "
              f"peak {l['peak_hz']:>7.1f}  {l['err_pct']:+.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
