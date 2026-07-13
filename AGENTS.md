# TRENCH Workstation Agent Contract

This branch has one job:

```text
typed grammar / LPC / measured evidence
  -> four authored poses
  -> six registered pole-zero lanes per pose
  -> exact packed .body240
  -> packed-runtime response + audio
  -> sampled stability/audibility certification
  -> reproducible body + session + proof bundle
```

Do not restore deleted Forge applications, production-training systems, study
corpora, sidecar editors, or plugin UI from Git history unless Tyson explicitly
asks. Build the workstation from the retained runtime contracts.

## Runtime facts

- A body is exactly 240 bytes: 4 corners × 6 stages × 5 u16 words × 2 bytes.
- Corner order is `M0_Q0`, `M100_Q0`, `M0_Q100`, `M100_Q100`.
- All four corners are authored. Q100 is a second pose, never derived.
- Stage index is sacred correspondence across corners; never sort lanes per pose.
- Packed-u16 Morph-first, then Q interpolation is runtime authority.
- Runtime decode produces direct `[b0,b1,b2,a1,a2]` DF2T sections.
- The six sections run as a serial cascade.

`trench-core` is the only packing, interpolation, response, certification, and
audio-engine owner. Do not create a second kernel or compiler.

## Stage authoring law

Every corner/lane exposes:

```text
pole geometry
zero geometry
SCALE = b0
identity/active state
evidence provenance
```

Conjugate roots use Hz/radius. Independent real-root pairs remain explicit and
must never be clamped into conjugate controls. Inactive means the exact identity
biquad; there is no packed on/off bit.

No hidden normalization, Q derivation, reordering, smoothing, gain correction,
or smart repair. Every selected action must report exactly which corners, lanes,
and packed words changed.

## Evidence boundary

`C:\Users\hooki\trench-filters` is external and read-only. A source session may
store its repository commit, relative path, file hash, and extracted evidence.
Do not copy its compiler code or promote its prose into runtime law.

P2K/reference material is study evidence only. Do not copy protected bytes,
names, coefficient rows, tables, or presets into this branch.

## Required product modes

- Default: packed response, four-pose selector, selected lane controls.
- Inspect: z-plane, all lanes, packed words, decoded coefficients, quantization
  diffs, per-corner diffs, and Morph×Q certification.
- BODY SOLO: cascade-only audio at unity I/O.
- PRODUCT: full retained `FilterEngine` path.

Technical data is available on demand, not used as decorative jargon.

## Proof gates

Before UI implementation, prove:

- no-op load/save is byte-identical;
- a declared edit changes only declared words/corners;
- raw body and JSON `packedWords` converge to identical packed corners;
- real-root rows cannot enter the conjugate editor silently;
- plots use packed/runtime-decoded coefficients and a shared dB scale;
- raw audio is not replaced by per-render normalization;
- body/cart parity is mandatory;
- zero unstable and zero nonfinite sampled rows;
- sessions and proof bundles are versioned and reproducible.

Call grid results sampled certification, never continuum proof.

## Work discipline

Inspect Git state and concurrent processes before editing. Work only in
`C:\Users\hooki\df2-workstation`. Keep one scoped change per verification step.
Do not modify model memory, lockfiles, docs, or unrelated files as a side effect.

Use claim labels when needed:

- `OBSERVED`: file, test, artifact, or runtime probe proves it.
- `INFERRED`: useful but not proven.
- `UNKNOWN`: evidence is missing.
- `REJECTED`: current evidence contradicts it.

Prefer probes, diffs, plots, and audio over additional doctrine.
