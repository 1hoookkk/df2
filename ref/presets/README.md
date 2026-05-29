# Verbatim preset store

Canonical preset format = the raw **240-byte ROM corner block** dumped from
Emulator X3, NOT JSON. JSON skins are derived/lossy and have been wrong
(corner mapping mismatches). These bytes are what the hardware actually plays.

Each `*.bin` is exactly 240 bytes: 4 corners × 6 stages × 5 u16, little-endian,
runtime order **A/B/C/D = M0_Q0 / M100_Q0 / M0_Q100 / M100_Q100**.

To add a preset from a live runtime object: in X3 (VST in FL, 44100 Hz) load the
filter, find the live `CPhantomRTFilter` object, dump 240 bytes at
`object+0x2C0..+0x3B0`, save here as `<name>.bin`. The forge's PRESET dropdown
lists every `.bin` here and loads it verbatim through the proven packed-decode
path.

- `talking_hedz.bin` — skin 13, bit-accurate (nulls −95 dB vs X3 wet).
- `P2k_000_*.bin` through `P2k_049_*.bin` — 50 P2K packed ROM skin banks
  extracted statically from `EmulatorX.dll` at `DAT_1806d762e`, transposed
  through the verified `FUN_1802d3ce0` layout. Names are from the Proteus
  Family SysEx filter table. See `P2K_MANIFEST.json`.
- `P2k_015_dj_alkaline.bin` — DJ Alkaline.

The P2K source table is grouped as four DAT variants per skin:
`dat_index = skin_index * 4 + variant`. The main `.bin` files here use
variant 0, which is the variant that byte-matches the verified Talking Hedz
runtime dump for `P2k_013`. All four raw variants per skin are preserved under
`ref/p2k_variants/`.

Batman / Bat Phaser is not stored here because it is a fixed-point ROM filter,
not a P2K minifloat bank. See `ref/batman/`.
