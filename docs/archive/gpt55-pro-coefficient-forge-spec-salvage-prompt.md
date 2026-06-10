# DF2 Private Forge Spec: Finish The Report

The prior `gpt-5.5-pro` xhigh request completed substantial architectural
reasoning but failed at the organization TPM boundary before emitting its final
report.

Do not restart the investigation. Do not ask questions. Do not produce a
thinking diary. Use the supplied saved reasoning summary as your working notes,
resolve its remaining choices decisively, and write the missing final technical
specification.

The report must be named:

`DF2 PRIVATE FORGE: DEFINITIVE STAGE-COMPOSER SPEC`

Keep these constraints locked:

- shipping body: four corners ordered `M0_S0`, `M1_S0`, `M0_S1`, `M1_S1`;
- exactly six serial DF2T biquads;
- exactly five packed `u16` words per stage;
- canonical body size: `240` bytes;
- poles and zeros both matter;
- release proof uses packed-domain interpolation and `trench_core` FFI plots;
- seven-stage expansion and eight-corner cube editing are out of scope;
- Forge is a private plot-first authoring bench;
- no random poles, random zeros, or AI taste selection;
- reference material is study-only and must not be copied into shipped bodies;
- a lawful constructor or two-frame program may start degenerate across
  Secondary, but the author must be able to expand it deliberately into a true
  four-corner DF2 surface.

Use this exact output structure:

1. `VERDICT`
2. `WHAT THE AUTHOR EDITS`
3. `SCREEN ANATOMY`
4. `FOUNDATION OPERATIONS`
5. `FOUR-CORNER EDIT SEMANTICS`
6. `ALWAYS-ON PACKED AUDIT`
7. `AUTHORING DOCUMENT SCHEMA`
8. `COMPILE AND PREVIEW PATH`
9. `FIRST IMPLEMENTATION SEQUENCE`
10. `REJECTED APPROACHES`
11. `OPEN EXPERIMENTS`

Requirements:

- Label claims `OBSERVED`, `INFERRED`, or `RECOMMENDED`.
- State the primary editable representation and diagnostic-only
  representations.
- Make zeros explicit in the UI.
- Define the smallest useful v0 constructor palette and the number of
  serialized stage slots each consumes.
- State the default edit scope when dragging one pole or zero.
- Separate hard export gates from warnings.
- Define the editable authoring artifact and the authoritative packed runtime
  artifact.
- Give a patch-ready phased implementation sequence.
- In `OPEN EXPERIMENTS`, request no more than six bounded captures and mark
  which are needed before v0.
- Be concise enough to finish. Prefer firm decisions over extended discussion.

