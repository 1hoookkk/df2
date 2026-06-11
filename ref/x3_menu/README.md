# X3 menu filters through Morph Designer

This is an exact reference extraction from the installed `EmulatorX.dll`.
It keeps the actual X3 computed menu classes separate from the similarly named
P2K packed skins.

## What is here

- `X3_MENU_MANIFEST.json`: class roster in menu order.
- `raw_tables/*.raw`: verbatim fixed-class ROM tables and Morph support tables.
- `runtime_blocks/*.raw`: compact corner snapshots expanded from each
  fixed-class writer source for every sample-rate family.

The runtime blocks are raw fixed-point coefficient words. They are not P2K
minifloat `.body240` banks and must not be loaded through the P2K path.

The Morph classes are dynamic generators. Their writers and exact support
tables are recorded, but they are deliberately not flattened into fake static
banks. `Morph Designer` grammar notes remain in
`ref/ghidra_extracts/morphdesigner_types.md`.

## Corrected classification

The older `ref/batman` study grouped four adjacent writers as Bat Phaser
sample-rate loaders. RTTI and vtables prove that only `FUN_1802c5620` is
`CPhantomBatman`. The adjacent writers are separate classes:

- `FUN_1802c5710`: `CPhantomFlanger1`
- `FUN_1802c57f0`: `CPhantomVocal1`
- `FUN_1802c58d0`: `CPhantomVocal2`

Generate this directory with:

```text
python tools/extract_x3_menu_filters.py
```
