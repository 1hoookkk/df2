# Thumbwheel Bitmap Filmstrip Spec

## Production Asset

| Field | Value |
|---|---:|
| Frame count | 129 |
| Native frame size | 96 x 14 px |
| Native strip size | 12384 x 14 px |
| Upscaled frame size | 384 x 56 px |
| Upscaled strip size | 49536 x 56 px |
| Layout | horizontal |
| Source pixels | none |

## Required Production Files

- `native_strip_129_96x14.png`
- `upscaled_strip_129_384x56.png`
- `frame_000.png`
- `frame_064.png`
- `frame_128.png`
- `contact_sheet_every8.png`
- `README.txt`
- `JuceThumbwheelFilmstrip.h`

## Production Acceptance

- Output strip has exactly 129 frames.
- Every upscaled frame is exactly 384 x 56 px.
- Native strip is exactly 12384 x 14 px.
- No E-mu/X3 bitmap pixels are loaded or copied.
- No rails, teeth, square tile grid, caterpillar tread, 3D cylinder, or solid cyan rectangle.
- The baked bitmap contains warm off-white molded ABS lips, rib shading,
  end rolloff, center clearance, and semi-transparent internal apertures.
- The ultralight-violet glow is rendered at runtime underneath the bitmap. It is
  visible only through the smoked clearance and inter-rib openings.

## Reference Boundary

`remaster_emu_reference.py` is source-derived and reference-only. Do not ship its output.
