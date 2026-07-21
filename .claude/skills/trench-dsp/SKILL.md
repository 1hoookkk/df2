---
name: trench-dsp
description: Transfer functions, filter design, packed-body numerics, audio-runtime behavior, stability analysis, response fitting, and listening or measurement evidence in the df2-workstation checkout (C:\Users\hooki\df2-workstation only, not sibling checkouts). Use when a task there involves poles and zeros, biquad coefficients, interpolation or morphing math, sample-rate-dependent behavior, fitting a target response into the shipped representation, diagnosing how something sounds, or judging whether a DSP claim is supported by evidence.
---

# TRENCH DSP

Choose the method — analytical design, measurement/system-ID, optimization, simulation, or a hybrid — by what the problem needs, not by habit. Ground every claim in evidence at the right point in the chain.

## Orient

- Identify the exact signal path in the current code before analyzing: which stages run, in what order, at what rates, and where the packed/quantized representation sits in that path. `AGENTS.md` states the runtime contract; verify it against code.
- Design-space math and runtime behavior are different objects. Coefficients as designed, coefficients as stored and decoded, and audio as heard are three distinct things — say which one a claim is about.

## Fit residuals vs representation limits

When a fit "cannot reach" a target, be precise about what the evidence can show:

- Any obtained residual is an **upper bound** on the achievable error — evidence of what was reached, never proof of a limit. Scatter across restarts or methods indicates the solver is the gap, not the math.
- Quantization error is measurable only for a candidate already in hand; encode-decoding a candidate bounds that candidate, not the format. Finding the truly nearest representable point is itself the global problem.
- A **representation-limit claim** requires stronger footing: an analytical constraint (a required value provably outside the encodable range, or a structure/order argument), a proven lower bound, exhaustive search over the finite representable set where feasible, or a method with global guarantees.

Never report an optimizer's failure as mathematical impossibility.

## Stability and runtime safety

- Verify stability on the coefficients the runtime actually executes (post-quantization, post-decode, across the interpolation range in use), not on the pre-quantization design.
- Changes touching the audio thread must stay real-time safe: no new allocation, locking, blocking IO, or unbounded work on that thread.
- Sampled grids over parameters and rates certify the sampled points. Present grid results as sampled evidence, never as continuum proof.

## Evidence for claims

- A plot computed from design coefficients shows the design; it cannot show downstream damage or prove what the audio sounds like. For audibility claims, measure the actual output — rendered audio, level-matched comparison, null test — whichever fits.
- Quantify fit quality honestly (error in dB over a stated range) instead of adjective-grading, and match the strength of the claim to the strength of the evidence.
- Perceptual verdicts belong to the user. Deliver level-matched, honestly labeled material to judge, and do not overrule an ear verdict with a clean plot — a clean plot upstream and bad sound downstream means the measurement is in the wrong place.
