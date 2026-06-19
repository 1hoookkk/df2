# CLAUDE.md - df2 working contract

Read `AGENTS.md` first. If this file and `AGENTS.md` disagree, `AGENTS.md`
wins. Tyson's current instruction wins over both.

## 1. Job Split

- Tyson owns taste: sound, product feel, keep/kill, sellability.
- Claude owns execution: code, builds, files, plots, tests, cleanup, and DSP
  proof.
- Do not make Tyson debug assumptions. Surface only real taste/product
  decisions or true blockers.

## 2. Runtime Truth

- A body is exactly `240 bytes = 4 corners x 6 sections x 5 packed words x 2`.
- It is one original 12th-order Z-plane filter type, not a preset description.
- Corners are `C0 low morph/lo Q`, `C1 high morph/lo Q`,
  `C2 low morph/hi Q`, `C3 high morph/hi Q`.
- Section index is the morph pairing across corners. Do not scramble it.
- Cascade order inside a corner is free because sections multiply.
- Every section has poles, zeros, and gain. Zeros are not optional.
- Morph moves the body. Secondary/Q is a co-leader resonance control, not a
  tiny trim.

## 3. Authoring Rule

Do not invent poles.

Valid sources, in order:

1. Real audio capture / LPC / fitted source surfaces.
2. Physical acoustic models: vocal tract, tubes, cavities, modal bodies.
3. Measured tables: formants, bandwidths, modal frequencies, frequency rails.
4. Clean-room P2K study grammar.

Reference material teaches behavior only. Do not ship copied coefficients,
packed bytes, protected names, or preset tables.

## 4. Product Target

df2 is a destructive morphing filter FX for bass, 808s, vocals, drums, and bus
processing. The target is expensive, violent, moving, resonant, and distinctive.

Preserve bass power while moving upper resonance. Prefer one clear dramatic DSP
gesture over subtle generic motion.

Judge through the real product chain:

```text
AGC -> Mackie saturation -> QSound
```

AGC is on by default. Do not judge only the bare cascade unless the task is
explicitly a raw-DSP probe.

## 5. Evidence Gate

Mark claims:

- `OBSERVED`: proven by file, test, runtime output, plot, or Tyson verdict.
- `INFERRED`: useful hypothesis, not yet proven.
- `UNKNOWN`: not known.
- `REJECTED`: contradicted by current evidence.

Never promote `INFERRED` or `UNKNOWN` to `OBSERVED`.

Before trusting a metric gate, run the reference bodies through it. A gate that
rejects the known iconic corridor is broken.

## 6. Proof Standard

A body is not real until it has:

- a 240-byte `.body240`,
- packed/runtime audit through `trench_core`,
- Morph/Q grid stability proof,
- response plots from the packed/runtime path,
- audio audition through the product chain,
- Tyson keep/kill verdict if it is bank-bound.

The plot is the first judgment surface. Ear confirms. If the plot is wrong, the
body is wrong.

## 7. Desk Discipline

- `desk/` is Tyson's cockpit.
- `desk/bank/v1/` is the product bank.
- A bank body needs Tyson's verdict in `BANK.md`, then export, audit, and JUCE
  roster wiring.
- Rejections go in `desk/KILLS.md` because they calibrate future work.
- A session that ends with a new tool but no sound verdict is only progress if a
  failed verdict justified the tool.

## 8. Ownership Boundaries

- Packed-body and morph math live in `trench-core`.
- Python, Forge, and tools call the core path through FFI/WASM.
- Do not add another packer, interpolator, or engine copy.
- Exploratory tools stay labeled exploratory until tested and promoted.

## 9. Language

Use textbook DSP language:

```text
Hz, poles, zeros, radius, angle, Q, |p| < 1, gain, spectral tilt,
formants F1-F4, modal frequencies, shelf, peak, lowpass, highpass
```

Do not invent mythology or new abstraction vocabularies. Avoid vague labels
when a DSP term is available.

## 10. Work Loop

```text
inspect actual files/code
make the smallest coherent change
run the relevant test/build/plot/audit
report what changed and what proved it
```

No theory essays when the real issue is a missing plot, stale build, broken
path, bad metric, or unverified assumption.

Ask only when taste is the bottleneck, a destructive action is required, or two
irreversible architectures are genuinely tied.

## 11. Build And Git

- If audio does not match the build, suspect stale host/plugin cache first.
- Use Standalone or AudioPluginHost for fast iteration when FL Studio caches the
  plugin DLL.
- Commit only coherent units.
- Preserve unrelated dirty files.
- Final reports must include changed files, commands run, test result, and
  remaining risks.
