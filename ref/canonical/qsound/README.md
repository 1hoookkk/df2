# QCreator QSound Right-90 Primary Render Fixture

`qcreator_qright90_impulse_11025.wav` is a DLL-grounded primary-render
fixture. It is not a vendor-supplied WAV: it was rendered offline by the
vendor `Qcreator.exe` / `QMixer.dll` pair from a deliberately minimal test
stimulus.

## Target

The fixture uses the most exaggerated right-side QSound position exposed by
QCreator: `+90 degrees`.

Ghidra MCP analysis of `QMixer.dll` recovered the pan application law:

```text
angle_deg = (pan_index - 15) * 6
```

The corresponding raw pan index is `30`.

## Clean Stimulus

The input is mono PCM16 at `11025 Hz`, `166591` frames long, with exactly one
nonzero sample:

```text
sample 30000 = 0.5
```

The QCreator authoring chunk was based on vendor `Demo2.qchk`; all eight pan
records were replaced with `+90 degrees`, including the records active around
the impulse. The constructed input remains an analysis stimulus. The exported
stereo WAV is the fixture.

## Measured Export

The right channel is the leading ear: an immediate `0.49993896484375`
impulse at sample `30000`.

The left channel starts at sample `30001`, peaks at
`-0.29345703125`, and has `22` nonzero PCM16 samples through sample `30022`.

See `MANIFEST.json` for hashes and exact measurements.

## Local Recreation

The no-profile runtime fallback uses this clean `+90 degrees` response as its
right extreme. It mirrors the response for the left extreme and interpolates
toward dry mono at center. That interpolation is an intentionally bounded
local recreation; only the `+90 degrees` anchor is a recovered vendor render.
