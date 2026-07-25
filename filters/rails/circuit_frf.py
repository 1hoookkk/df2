#!/usr/bin/env python3
"""Circuit well -> small-signal FRFs (evidence surfaces for the FuzziFace archetype).

CITE-OR-REFUSE provenance
-------------------------
The circuit well (C:/Users/hooki/surface-forge/data/circuit/) contains NO Fuzz Face
netlist (checked: spice-datasets = LTspice/KiCad op-amp + power demo circuits only).
The distortion-pedal models that ARE on disk, with full component values:

  1. Tube Screamer clipping chain
     faust-wdf-library/examples/tube-screamer/tubeScreamer.dsp
       stage_a: C2=1uF, rA=220R, vB source R=10k        (input coupling HP)
       stage_b: C3=47nF, R4=4.7k                        (op-amp inverting-leg Zi)
       stage_c: Rf=51k + drive*500k, C4=41pF,
                antiparallel diodes Is=2.52nA, Vt=25.85mV, n=1   (feedback Zf)
     Small-signal: H(s) = HP_in(s) * (1 + Zf(s)/Zi(s)),
       Zf = Rf || 1/(sC4) || r_d,  Zi = R4 + 1/(sC3),
       HP_in = 10k / (10k + 220 + 1/(sC2)).
     r_d = n*Vt/(Id+Is) = diode incremental resistance at operating (bias) point Id.
     The bias axis Id in {0, 1u, 10u, 100u, 1m}A is the standard describing-point
     linearization of the SAME on-disk nonlinear model (harder playing -> larger
     average diode current -> smaller r_d).

  2. Diode clipper
     faust-wdf-library/examples/02-diode-clipper/diodeClipper.dsp
       Rs=4.7k source, C1=47nF, same antiparallel diode pair.
     Small-signal: H(s) = Zl/(Rs+Zl), Zl = 1/(sC1) || r_d.

Every number below is verbatim from those files; the ONLY derived quantity is r_d
(Shockley small-signal at a stated operating current). Each FRF is normalized to
0 dB median in band (documented; the fitter floors at -25 dB absolute).

Output: data/circuit/*.json + MANIFEST.md
Run: python tools/circuit_frf.py
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "circuit"

F_LO, F_HI, N_GRID = 50.0, 16000.0, 600
GRID = np.logspace(math.log10(F_LO), math.log10(F_HI), N_GRID)
S = 2j * math.pi * GRID

# ---- verbatim component values (tubeScreamer.dsp / diodeClipper.dsp) ----
TS = dict(C2=1e-6, RA=220.0, RB=10e3,          # stage_a
          C3=47e-9, R4=4.7e3,                  # stage_b (Zi leg)
          RF0=51e3, RPOT=500e3, C4=41e-12,     # stage_c (Zf leg)
          IS=2.52e-9, VT=25.85e-3, N=1.0)      # u_diodeAntiparallel(2.52e-9, 25.85e-3, 1, 1)
DC = dict(RS=4.7e3, C1=47e-9, IS=2.52e-9, VT=25.85e-3, N=1.0)

DRIVES = [0.0, 0.25, 0.5, 0.75, 1.0]
BIAS_ID = [0.0, 1e-6, 1e-5, 1e-4, 1e-3]        # diode operating current (A)


def r_diode(Id: float, Is: float, n: float, Vt: float) -> float:
    """Shockley small-signal incremental resistance of the antiparallel pair."""
    return n * Vt / (Id + Is)


def par(*zs):
    return 1.0 / sum(1.0 / z for z in zs)


def ts_chain(drive: float, Id: float) -> np.ndarray:
    c = TS
    rd = r_diode(Id, c["IS"], c["N"], c["VT"])
    hp_in = c["RB"] / (c["RB"] + c["RA"] + 1.0 / (S * c["C2"]))
    Zi = c["R4"] + 1.0 / (S * c["C3"])
    Rf = c["RF0"] + drive * c["RPOT"]
    Zf = par(np.full_like(S, Rf), 1.0 / (S * c["C4"]), np.full_like(S, rd))
    return hp_in * (1.0 + Zf / Zi)


def diode_clipper(Id: float) -> np.ndarray:
    c = DC
    rd = r_diode(Id, c["IS"], c["N"], c["VT"])
    Zl = par(1.0 / (S * c["C1"]), np.full_like(S, rd))
    return Zl / (c["RS"] + Zl)


def norm_med(H: np.ndarray) -> np.ndarray:
    m = np.median(np.abs(H))
    return H / m if m > 0 else H


def bias_tag(Id: float) -> str:
    return "cold" if Id == 0.0 else f"{Id*1e6:g}uA"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    recs = []
    for drive in DRIVES:
        for Id in BIAS_ID:
            H = norm_med(ts_chain(drive, Id))
            rid = f"ts_drive{int(drive*100):03d}_bias_{bias_tag(Id)}"
            recs.append((rid, "tube_screamer_chain",
                         dict(drive=drive, Id_A=Id, rd_ohm=r_diode(Id, TS["IS"], TS["N"], TS["VT"]),
                              **{k: v for k, v in TS.items()}), H))
    for Id in BIAS_ID:
        H = norm_med(diode_clipper(Id))
        rid = f"dc_bias_{bias_tag(Id)}"
        recs.append((rid, "diode_clipper",
                     dict(Id_A=Id, rd_ohm=r_diode(Id, DC["IS"], DC["N"], DC["VT"]),
                          **{k: v for k, v in DC.items()}), H))

    for rid, model, settings, H in recs:
        (OUT / f"{rid}.json").write_text(json.dumps(dict(
            id=rid, well="circuit", model=model,
            source=("surface-forge/data/circuit/faust-wdf-library/examples/tube-screamer/tubeScreamer.dsp"
                    if model == "tube_screamer_chain" else
                    "surface-forge/data/circuit/faust-wdf-library/examples/02-diode-clipper/diodeClipper.dsp"),
            method="small-signal AC (linearized diode r_d = n*Vt/(Id+Is)); normalized to 0 dB median",
            settings=settings, freq_hz=[float(f) for f in GRID],
            H_re=[float(x) for x in H.real], H_im=[float(x) for x in H.imag],
        ), indent=1), encoding="utf-8")
        print(f"  {rid}")

    manifest = f"""# data/circuit MANIFEST — small-signal circuit FRFs

Generated {date.today().isoformat()} by tools/circuit_frf.py (deterministic, no RNG).

## Well inventory (surface-forge/data/circuit/, checked {date.today().isoformat()})
- chowdsp_wdf/            C++ WDF library; tests carry BassmanToneStack.h (R1=250k,
                          R2=1M, R3=25k, R4=56k, C1=250p, C2=C3=20n), BaxandallEQ.h.
                          No fuzz circuit. Library code, no datasets.
- faust-wdf-library/      Faust WDF examples WITH component values: 02-diode-clipper,
                          tube-screamer (used here), basssman-tonestack, pultec,
                          chua-diode. No Fuzz Face.
- spice-datasets/         kicad_github/ + ltspice_demos/ + ltspice_examples/ =
                          LT/KiCad op-amp, supply, logic demo netlists. grep 'fuzz'
                          over all .cir/.net = zero hits. NOT audio-pedal material.
- dafx02_nonlinear_transfer_measurement.pdf  Moeller/Gromowski/Zoelzer DAFx-02
                          measurement-technique paper — method only, no dataset.

**NO Fuzz Face netlist exists in the well.** The FRFs here are the distortion-pedal
models the well actually contains. Anything labelled "fuzz face" would have been
invented — refused per cite-or-refuse.

## FRFs ({len(recs)} files, band {F_LO:.0f}-{F_HI:.0f} Hz, {N_GRID} log pts)
- ts_drive*_bias_*.json  (25) Tube Screamer input HP + clipping stage,
  H = HP_in * (1 + Zf/Zi); drive pot {DRIVES}; bias operating current {BIAS_ID} A
  (r_d = n*Vt/(Id+Is), Shockley small-signal of the on-disk diode model).
- dc_bias_*.json  (5) diode clipper Rs=4.7k / C=47n / diode pair, same bias axis.

All component values verbatim from the cited .dsp files. Each FRF normalized to
0 dB median in band. Complex H stored as H_re/H_im on freq_hz grid.
"""
    (OUT / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    print(f"wrote {len(recs)} FRFs + MANIFEST -> {OUT}")


if __name__ == "__main__":
    main()
