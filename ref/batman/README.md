# Deprecated Bat Phaser study

Do not regenerate or use `batman_rom.json` as a Bat Phaser class map.

This study incorrectly grouped four adjacent class writers as Bat Phaser
sample-rate loaders. RTTI and vtables prove that only `FUN_1802c5620` is
`CPhantomBatman`. The adjacent writers are separate classes:

- `FUN_1802c5710`: `CPhantomFlanger1`
- `FUN_1802c57f0`: `CPhantomVocal1`
- `FUN_1802c58d0`: `CPhantomVocal2`

Use the full exact menu extraction instead:

```text
python tools/extract_x3_menu_filters.py
```

The corrected artifacts live in `ref/x3_menu`.
