from pathlib import Path

from PIL import Image, ImageDraw


SOURCE = Path(r"C:\Users\hooki\do-it\emu-x3-bitmap-dump\BITMAP4331_2.bmp")
OUTPUT = Path(r"C:\Users\hooki\df2-workstation\plugin\assets\trench_roller_strip.png")

SOURCE_FRAME_WIDTH = 85
SOURCE_FRAME_HEIGHT = 16
# Keep the supplied bitmap at its native frame resolution.  WheelControl is
# the only place that scales it to the live aperture; pre-enlarging here and
# then scaling again in JUCE softens the rib edges and glow packet.
RUNTIME_FRAME_WIDTH = SOURCE_FRAME_WIDTH
RUNTIME_FRAME_HEIGHT = SOURCE_FRAME_HEIGHT


def main() -> None:
    source = Image.open(SOURCE).convert("RGB")
    assert source.height == SOURCE_FRAME_HEIGHT
    assert source.width % SOURCE_FRAME_WIDTH == 0

    source_count = source.width // SOURCE_FRAME_WIDTH
    # BITMAP4331_2 contains 128 usable value frames plus a final frame-0
    # wrap. The wrap is not a useful 100% pose: the real terminal frame is 127,
    # which is the bright packet parked at the far-right side of the drum.
    usable_count = source_count - 1
    assert usable_count == 128, usable_count

    output = Image.new("RGBA", (RUNTIME_FRAME_WIDTH * usable_count,
                                 RUNTIME_FRAME_HEIGHT), (0, 0, 0, 0))

    for index in range(usable_count):
        frame = source.crop((index * SOURCE_FRAME_WIDTH, 0,
                             (index + 1) * SOURCE_FRAME_WIDTH, SOURCE_FRAME_HEIGHT))
        # Keep the measured bitmap's rib/face angle. Do not resize here: the
        # live component performs the one display-scale conversion, avoiding a
        # second filtered pass before the image reaches the well.

        alpha = Image.new("L", frame.size, 0)
        ImageDraw.Draw(alpha).rounded_rectangle(
            (0, 0, RUNTIME_FRAME_WIDTH - 1, RUNTIME_FRAME_HEIGHT - 1),
            radius=5, fill=255)
        rgba = frame.convert("RGBA")
        rgba.putalpha(alpha)
        output.paste(rgba, (index * RUNTIME_FRAME_WIDTH, 0), rgba)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output.save(OUTPUT)
    print(f"wrote {OUTPUT} {output.size} from {source_count} source frames")


if __name__ == "__main__":
    main()
