# Current state — TRENCH DESIGNER SHIPPED (2026-07-25)

All four steps landed and proven on the real path:

1. Engine: `trench-core/src/designer.rs` + FFI (`trench_designer_compile_corner`,
   `trench_designer_body`). Parity 69/69 heritage XMLs byte-equal
   (`cargo test --test heritage_parity`; fixtures vendored under
   `trench-core/tests/heritage/`).
2. Panel: DESIGNER in the Workstation — SHAPE OFF/EQ/LP/HP/FREE, LO/HI rows,
   census zero-motif picker, Q0/Q100 pose pages, SKETCH Q100 x0.375 (MD-Q law),
   live 5-curve JOURNEY strip, TEMPLATE menu (7 census rails + attic-stack 303).
3. Gates: certify 9x9 on every edit; family-aware journey gate (RIDE
   no-collapse / ARCH mid-crest), advisory — ear stays the judge; SAVE (L10)
   frames active rows to +2/+8/+25/+27, re-certifies, drops to
   `bodies/candidates/`.
4. Proofs: Bass Shaper authored in-panel == heritage compile BYTE-EQUAL;
   TRENCH-303 rebuilt entirely in-panel (hand == template byte-equal, RIDE
   pass); headless TRENCH_WS_SCRIPT actions for every control
   (designer/dpage/dtype/dset/dshift/dtemplate/dmotif/dsketch/dfamily/dsave/ddump).

## Open, gated on Tyson

- VST3 install (ship-vst3) — explicit go required. The build now includes
  in-place hot-reload of the loaded body (done 2026-07-26): the DAW plugin
  follows Workstation saves the moment it is installed.
- Ear pass over `bodies/candidates/` (5 functional TRENCH_*, TRENCH_303,
  7 XSTUDY_* study-only, 21 CAVL) — author bodies in the Designer now.
