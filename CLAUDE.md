# Claude contract — workstation branch

Read `AGENTS.md` first. It is authoritative.

This branch is a clean product nucleus, not an archive of previous Forge
implementations. Do not recover deleted UI, authoring, training, study, or
sidecar systems from Git history unless Tyson explicitly asks.

## Runtime authority

- `trench-core` owns packing, packed-u16 interpolation, decode, response,
  stability sampling, and the shipped audio engine.
- A body is exactly 240 bytes: four authored corners, six registered stages,
  five little-endian u16 words per stage.
- Roots are an authoring coordinate system. Packed words and runtime-decoded
  coefficients are the executable result.
- SCALE means `b0`. Do not reintroduce ambiguous `gain dB` normalization.
- Real-root pairs must remain explicit. Never clamp them into conjugate roots.
- Inactive means the exact identity biquad; there is no packed on/off bit.

## Evidence boundary

`C:\Users\hooki\trench-filters` is an external, read-only evidence source.
Record its commit, relative path, and file hash in sessions. Do not copy its
compiler code or treat its prose as runtime law.

P2K material is study evidence only. Never copy protected bytes, names, rows,
tables, or presets into this branch.

## Work discipline

Before editing:

1. Confirm the active worktree and clean/dirty state.
2. State the files and behavior in scope.
3. Resolve authority conflicts with a runtime probe, not model agreement.

Before claiming completion:

1. Run the narrow tests and the retained `trench-core` suite.
2. Inspect the complete diff for unrelated files and generated lock churn.
3. Label sampled certification honestly; never call it a continuum proof.
4. Report `OBSERVED`, `INFERRED`, `UNKNOWN`, or `REJECTED` where applicable.

Do not build UI until load/save identity, declared edits, packed response,
BODY SOLO audio, PRODUCT audio, and proof-bundle contracts are executable.
