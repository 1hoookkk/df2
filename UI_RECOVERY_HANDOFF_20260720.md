# TRENCH UI recovery handoff — 2026-07-20

## User-approved target

The user’s latest confirmed face is:

`C:\WINDOWS\TEMP\codex-clipboard-31c43750-3dc2-40ce-8354-856c871e7c01.png`

The preserved in-workspace golden render is:

`C:\Users\hooki\df2-workstation\dev\tmp\key_snap_visual\trench_face_p0.png`

It is 326x503 and is the reference for the entire face, not only the plate.
The target has:

- the new beige photographed plate;
- the small TRENCH logo at the upper left;
- BODY at the left of the shallow, lower preset bar;
- the dark teal graph with the muted coral trace and `C m` chip;
- the two light grey textured horizontal wheels;
- the thin AMOUNT wheel;
- the short half-ellipse edge/shadow beneath each horizontal wheel.

The user explicitly asked for recovery of the UI code/state, not a visual redraw.

## Why the UI drifted

There is no single clean Git commit that equals the golden screenshot. The
screenshot was produced by a later dirty working-tree state after the compact
face commits. The checkout also contains substantial unrelated DSP, preset,
and tooling changes. Earlier recovery attempts mixed files from different UI
eras, stale embedded binaries, and different wheel/body assets. Because the
plate, wheel strip, and preset bodies are embedded at build time, running an
older executable made the source changes appear ineffective.

Do not use a whole-tree reset or checkout. It would discard unrelated user
work.

## Current state after this pass

### Preserved / correct direction

- `plugin/assets/df2_panel_beige.png` is the user’s new plate photo converted
  to the embedded PNG.
- `plugin/presets/bodies/Talker.body240` has been restored to the pre-test body:
  SHA-256 `01C512CCACCD638BCBFC78BDC89BAFE00D11FC490C89D29EBC62E2888F15075E`.
- The UI-only top geometry in `plugin/source/UiLayout.h` was measured from the
  golden image and set to:

  ```text
  typeSelector = { 198, 139, 704, 71 }
  typeLabel    = { 102, 139,  84, 74 }
  brandLabel   = {  96,  75, 230, 40 }
  ```

  The resulting top row is visibly aligned with the golden image in:

  `dev/recovery_faceshot_20260720_topfix/trench_face_p0.png`

- `plugin/source/ui/GraphDisplay.h` is currently the committed `8c85ad0c`
  version.
- `plugin/source/ui/FaceplateView.h` contains the shallow, clipped half-ellipse
  wheel-edge treatment. It does not contain the rejected amount-side shadow.

### Still wrong / not approved

`dev/recovery_faceshot_20260720_topfix/trench_face_p0.png` is not a finished
match. It still has:

- the wrong Talker trace;
- dark/current wheel artwork instead of the target light grey wheels;
- a dev-only `TABLES` button in the upper-right corner.

The current embedded wheel strip is the dark c2-era asset:

`plugin/assets/trench_roller_strip.png`

SHA-256 `83DCE21D23A5BC4E1E38405A7C2D39C957D28DB2713BDE37BA8F7AF9CF1350FC`.
It must not be assumed to be the target artwork.

The old Talker body test was rejected. It was temporarily copied from
`dev/tmp/usable/TALKER.body240` and had SHA-256
`E402E3AC6309F7C908CA1CF9E9A03C5EAA2A6738CE681BED1371A7DCB7B4EF21`.
It has been restored out of the working preset. Do not leave that body in the
checkout.

The rebuilt executable is:

`build/TRENCH_FaceShot_artefacts/Release/TRENCH_FaceShot.exe`

The executable under `plugin/build` is stale for this recovery and must not be
used as evidence.

## Important recovery evidence

Relevant Git points:

- `c2cea4e4`: compact 326x503 face, but dark c2-era wheel strip;
- `094e1a21`: later wheel-lamp asset (`b5ff0240...` blob), not confirmed as
  the golden light-wheel asset;
- `8c85ad0c`: gesture/announce GraphDisplay state;
- `2b78e434`: BODY token at the real `UiLayout` source, but not the whole
  golden face;
- `9ac18257` and `93307d43`: earlier thin-bar/ember UI lineage and older
  wheel assets; neither alone is the target because their editor/layout state
  differs.

Recovery backups made before source edits are under:

`dev/recovery_faceshot_20260720/`

In particular:

- `pre_source_restore_UiLayout.h`;
- `pre_source_restore_GraphDisplay.h`;
- `pre_source_restore_FaceplateView.h`;
- `pre_source_restore_WheelControl.h`;
- `trench_roller_strip_pre_restore.png`;
- `df2_panel_beige_pre_plate.png`.

## Safe next-pass order

1. Preserve the current dirty worktree. Do not reset, stash, or restore the
   whole checkout.
2. Disable/remove the `TABLES` dev overlay from the product FaceShot path and
   confirm the screenshot has no top-right button.
3. Recover the exact target-time Talker body by comparing 240-byte candidates
   and their packed/runtime graph output. The current `01C5...` body and the
   rejected `E402...` body are both known not to reproduce the golden trace.
4. Compare the golden wheel crop against the historical wheel-strip blobs,
   especially the thin/older asset lineage, before touching the external
   `C:\Users\hooki\df2\dev\tmp\roller_batch_az90\clean` batch. That batch was
   already reported by the user as having unwanted movement along the strip.
5. Build the current source once, run only that executable, and render into a
   new recovery directory.
6. Require visual inspection plus crop-level comparison against
   `dev/tmp/key_snap_visual/trench_face_p0.png` for the top row, graph, and
   wheels before calling the UI restored.

## Latest scoped readability pass (2026-07-20)

The remaining compact-face punch-list was implemented in the live source:

- key chip lifted into the upper-right screen corner and given a squarer edge;
- Morph/Q readouts widened and aligned, with emphasized readable numerals;
- BODY, MORPH, and Q labels given explicit emphasis without expanding their
  rows; the BODY source box was widened only enough to prevent ellipsis;
- TRENCH received the wider tracking treatment and a small rightward placement;
- the modulation lamp now uses a separate muted copper token, leaving the teal
  wheel illumination unchanged.

Fresh proof from the rebuilt FaceShot executable:

`dev/recovery_faceshot_20260720_readability_compact_v2/trench_face_p0.png`

The executable exited `0`; the packed wheel and key-snap probes reported
`PASS`. This was deliberately a scoped readability/layout pass: the unresolved
wheel-strip and Talker-trace recovery items above were not replaced or hidden.

The key control was then tightened to the requested interaction: a 38x26
square-ish button at the graph upper-right, clean vector `C m` text plus a
down-chevron, and a click popup grouped into `OFF`, `MINOR`, and `MAJOR`.
Wheel nudging remains supported. Fresh proof:

`dev/recovery_faceshot_20260720_key_button/trench_face_p0.png`

## User-facing explanation

The UI did not become harder because the target was ambiguous. It became worse
because recovery was attempted as a sequence of partial visual substitutions
instead of restoring one coherent source snapshot. The next pass must treat
the golden screenshot, its exact source state, and the embedded build output
as one unit.
