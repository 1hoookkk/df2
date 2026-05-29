"""Build physically-modelled cavity intents from real object dimensions.

For each named object: declare physical dimensions, compute resonance freqs from
tables/physical_models.py, write the 4-slot intent into family_intents.json.

No hand-tuning — every number is derived from a standard textbook formula. The
'physics' field in each intent's describe documents the formula used, and the
'dims' object is the input the freqs were computed from (the receipt).
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tables.physical_models import (
    helmholtz, closed_pipe_modes, open_pipe_modes,
    rectangular_room_modes, tin_can_modes, geom_mean,
)

INTENTS_FILE = ROOT / "tables" / "family_intents.json"


# ── Cavity object specs (real-world dimensions, cm/litres) ───────────────────

CAVITIES = {
    "wine_bottle": {
        "physics": "Helmholtz + closed-pipe body modes",
        "dims": {"volume_l": 0.75, "neck_d_cm": 1.85, "neck_l_cm": 6.0, "body_l_cm": 24.0},
    },
    "beer_bottle": {
        "physics": "Helmholtz + closed-pipe body modes",
        "dims": {"volume_l": 0.355, "neck_d_cm": 1.6, "neck_l_cm": 5.0, "body_l_cm": 16.0},
    },
    "plastic_jug": {
        "physics": "Helmholtz + closed-pipe body modes",
        "dims": {"volume_l": 2.0, "neck_d_cm": 2.0, "neck_l_cm": 3.0, "body_l_cm": 28.0},
    },
    "mason_jar": {
        "physics": "open-top closed-bottom cylinder (quarter-wave)",
        "dims": {"body_l_cm": 12.0},
    },
    "tin_can": {
        "physics": "thin steel cylindrical shell — Donnell flexural modes",
        "dims": {"radius_cm": 3.5, "length_cm": 11.0, "thickness_mm": 0.25},
    },
    "stone_pipe": {
        "physics": "open-open pipe — full harmonic series",
        "dims": {"length_cm": 120.0},
    },
    "bathtub": {
        "physics": "rectangular cavity room modes",
        "dims": {"L_cm": 160.0, "W_cm": 70.0, "H_cm": 50.0},
    },
}


def compute_freqs(spec: dict) -> tuple[list[int], str]:
    """Return (freqs[4], formatted_describe_string) for one cavity spec."""
    d = spec["dims"]
    p = spec["physics"]
    if "Helmholtz" in p:
        f_h = helmholtz(d["volume_l"], d["neck_d_cm"], d["neck_l_cm"])
        body = closed_pipe_modes(d["body_l_cm"], n=3)
        f0, b1, b2 = f_h, body[0], body[1]
        notch = geom_mean(b1, b2)
        freqs = [f0, b1, notch, b2]
        describe = (f"Helmholtz {round(f_h)}Hz (V={d['volume_l']}L, neck d={d['neck_d_cm']}cm L={d['neck_l_cm']}cm) "
                    f"+ body modes {round(b1)}/{round(b2)}Hz (closed-pipe, L={d['body_l_cm']}cm)")
    elif "quarter-wave" in p:
        body = closed_pipe_modes(d["body_l_cm"], n=4)
        f0, f1, f2 = body[0], body[1], body[2]
        notch = geom_mean(f1, f2)
        freqs = [f0, f1, notch, f2]
        describe = (f"closed-bottom cylinder L={d['body_l_cm']}cm — quarter-wave "
                    f"{round(f0)}/{round(f1)}/{round(f2)}Hz")
    elif "shell" in p:
        modes = tin_can_modes(d["radius_cm"], d["length_cm"], d["thickness_mm"])
        f0, f1, f2 = modes[0], modes[1], modes[2]
        notch = geom_mean(f1, f2)
        freqs = [f0, f1, notch, f2]
        describe = (f"steel shell R={d['radius_cm']}cm L={d['length_cm']}cm h={d['thickness_mm']}mm — "
                    f"flexural modes {round(f0)}/{round(f1)}/{round(f2)}Hz")
    elif "open-open" in p:
        modes = open_pipe_modes(d["length_cm"], n=4)
        f0, f1, f2 = modes[0], modes[1], modes[2]
        notch = geom_mean(f1, f2)
        freqs = [f0, f1, notch, f2]
        describe = (f"open pipe L={d['length_cm']}cm — full series "
                    f"{round(f0)}/{round(f1)}/{round(f2)}Hz")
    elif "rectangular cavity" in p:
        modes = rectangular_room_modes(d["L_cm"], d["W_cm"], d["H_cm"], n_terms=2)
        f0, f1, f2 = modes[0], modes[1], modes[2]
        notch = geom_mean(f1, f2)
        freqs = [f0, f1, notch, f2]
        describe = (f"rect cavity {d['L_cm']}×{d['W_cm']}×{d['H_cm']}cm — room modes "
                    f"{round(f0)}/{round(f1)}/{round(f2)}Hz")
    else:
        raise ValueError(f"unknown physics: {p}")
    return [round(f) for f in freqs], describe


def main():
    lib = json.loads(INTENTS_FILE.read_text(encoding="utf-8"))
    fam = lib["families"]["cavity"]
    intents = {}
    print("Computed cavity intents from physical models:")
    print(f"{'name':<14} {'f0':>5} {'f1':>5} {'notch':>6} {'f2':>5}   physics")
    for name, spec in CAVITIES.items():
        freqs, describe = compute_freqs(spec)
        intents[name] = {"freqs": freqs, "describe": describe,
                         "physics": spec["physics"], "dims": spec["dims"]}
        print(f"{name:<14} {freqs[0]:>5} {freqs[1]:>5} {freqs[2]:>6} {freqs[3]:>5}   {spec['physics']}")
    fam["intents"] = intents
    fam["slots"] = ["fundamental", "second_mode", "scoop_notch", "upper_mode"]
    INTENTS_FILE.write_text(json.dumps(lib, indent=2), encoding="utf-8")
    print(f"\nwrote -> {INTENTS_FILE}")


if __name__ == "__main__":
    main()
