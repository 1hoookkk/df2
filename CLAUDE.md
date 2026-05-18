# df2

12-stage DF2T biquad cascade, 4-corner bilinear interpolation, kernel-form
`[c0, c1, c2, c3, c4]` coefficients. Rust core, JUCE wrapper. Authoring SR
39062.5 Hz, runtime SR 44100 Hz. Runtime is frozen and patent-faithful
(Rossum 1992, US5170369).

## Rules

- Never modify cascade topology, interpolation order, or cartridge format.
- No RBJ cookbook formulas in shipped cartridge coefficients. Filter
  Factory may use RBJ peaking as an authoring primitive provided the
  result nulls against the heritage realization. The spatial post-stage
  (`qsound_spatial.rs`) is exempt — not the character path.
- Never save AI chat output back as a repo file or notebook source.
- Clean Room: capture E-mu binary coefficients for reference only; author
  df2 frames that match behavior (null test, not coefficient copy).
- Auditioning is the gate. Visual plot match is decorative.

## Validation

Bodies are validated by null test against E-mu wet renders at known corner
and midpoint M/Q positions. Threshold: ≤ −60 dB null depth at every
tested position. ≤ −90 dB = bit-accurate. ≥ −30 dB = pipeline failure.

Tool: `tools/null_test.py`.

## Session protocol

1. Read CLAUDE.md, SPEC.md, FRAME_BANK.md, BODIES.md, STATE.md before
   acting on any task.
2. If STATE.md contradicts the repo (file claimed that doesn't exist,
   status that's wrong), update STATE.md to match reality before doing
   new work.
3. Every code change updates STATE.md in the same commit.
4. Every session writes a dated entry to SESSION_LOG/ on close.

## Operating mode

Small reversible changes: do them and report. Large or irreversible:
surface with recommended answer attached. One taste call per response.
No flattery, no preambles. Lead with audible consequences when relevant.

The owner (Tyson) makes all taste decisions. Claude owns code, math,
debugging, verification, cleanup. He writes zero code.
