# Island SRC sweep-null — 2026-07-17

Method: 10 s ESS (20 Hz–22 kHz) through installed TRENCH.vst3 (pedalboard),
NO FILTER body, slam 0, motion off, amount max. Full chain — AGC in circuit
(reported as such). `measure.py` reproduces; probes in session transcript.

## Numbers (magnitude normalized to 1 kHz)

| host | ripple 100–15k | 15 k | 18 k | 19.5 k | residual (full / passband 100–15k) | chain gain |
|------|---------------|------|------|--------|-----------------------------------|-----------|
| 44100 | 0.17 dB | −0.1 dB | −13.3 dB | −59.6 dB | −7.5 / −13.7 dB | +1.73 dB |
| 48000 | 0.27 dB | +0.1 dB | −14.2 dB | −59.2 dB | −7.2 / −12.9 dB | +1.72 dB |
| 96000 | 0.17 dB | −0.0 dB | −17.0 dB | −61.1 dB | −6.8 / −11.6 dB | +1.61 dB |

## Findings

- Passband 100 Hz–15 kHz is FLAT (≤0.27 dB ripple, all rates). No darkness in the SRC passband. OBSERVED.
- Chain gain +1.6..1.7 dB, STEADY across the sweep (±0.05 dB, 100 Hz–15 k) — constant makeup (AGC), not a ride. OBSERVED.
- LF: −1.9 dB at 20 Hz, recovering by ~150 Hz — a DC-blocker/highpass in the chain. OBSERVED (location not isolated).
- HF: transition starts ~17 kHz; −60 dB at 19.5 k. The island Nyquist (19531 Hz) ceiling is the only real loss — by design, at every host rate. OBSERVED.
- Above-island-Nyquist leakage ~−14 dB (48/96 k hosts, >20 kHz region) — imaging/alias products, ultrasonic. OBSERVED.
- Distortion: H2 −51 dBc, H3 −63 dBc at −12 dBFS input. OBSERVED.
- Residual floors: full-sweep residual dominated by the HF wall segment; passband
  residual (−13 dB) dominated by non-linear-phase dispersion (magnitude flat, gain
  steady, distortion low) — level is not being lost. INFERRED from elimination.
- Down-SRC vs up-SRC not separable through the plugin alone; nothing found that
  needs localizing (passband clean).

Verdict input for the "dark" question: the SRC is innocent below 15 k. If TRENCH
reads dark vs bypass, it is the ~17.5 kHz ceiling (and only that) — which is what
mission C (HD island, Nyquist 39 k) addresses.
