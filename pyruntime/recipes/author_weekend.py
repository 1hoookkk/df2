"""Weekend body authoring — 3 heritage bodies from E-mu XML blueprints.

Body 1: Morpheus Like (3-stage, Type 2+3 morph)
Body 2: Twin Peaks (2-stage, gain-crossfade morph)
Body 3: Dillusion Reese (Hz-domain peak/shelf morph)

Run: python -m pyruntime.recipes.author_weekend
Output: trench_live.json (compiled-v1, plugin-loadable)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from pyruntime.designer_compile import (
    compile_designer_to_body,
    make_template,
    make_hz_body,
    HzEndpoint,
    parse_xml,
)


def author_morpheus_like():
    """Body #1: AC Morpheus Like — 3 active stages."""
    template = make_template("MorpheusLike", [
        # (type, low_freq, low_gain, high_freq, high_gain)
        (2, 21, 127, 82, 127),   # Stage 1: peak, freq sweeps, gain constant
        (2, 29,  65, 78, 114),   # Stage 2: peak, both sweep
        (3,  0, 113, 127, 120),  # Stage 3: notch, full-range freq sweep
    ])
    return compile_designer_to_body(template, boost=4.0)


def author_twin_peaks():
    """Body #2: Twin Peaks — 2 active stages, gain crossfade."""
    template = make_template("TwinPeaks", [
        (2, 78, 127, 99, 0),    # Stage 1: peak fades out at morph=100
        (3,  0, 127, 78, 0),    # Stage 2: notch fades out at morph=100
    ])
    return compile_designer_to_body(template, boost=4.0)


def author_dillusion_reese():
    """Body #3: Dillusion Reese — Hz-domain peak/shelf morph.

    Start: 246 Hz, shelf -50 (deep cut), peak -24 dB
    Target: 4488 Hz, shelf +30 (boost), peak +1.5 dB
    """
    # Single-stage body: one peak filter that morphs position and gain
    peak_low = HzEndpoint(freq_hz=246.0, gain_db=-24.0, contour="pure")
    peak_high = HzEndpoint(freq_hz=4488.0, gain_db=1.5, contour="pure")

    # Shelf stage: unit_circle zeros create the shelving behavior
    shelf_low = HzEndpoint(freq_hz=246.0, gain_db=-12.0, contour="unit_circle")
    shelf_high = HzEndpoint(freq_hz=4488.0, gain_db=6.0, contour="unit_circle")

    return make_hz_body("DillusionReese", [
        (peak_low, peak_high),
        (shelf_low, shelf_high),
    ], boost=4.0)


def report_body(body, morph_points=(0.0, 0.25, 0.5, 0.75, 1.0)):
    """Print frequency response summary at morph positions."""
    print(f"\n{'='*60}")
    print(f"  {body.name}")
    print(f"{'='*60}")

    for cn in body.corners.names():
        c = body.corners.corner(cn)
        active = sum(1 for s in c.stages if s.r > 0.01)
        print(f"  {cn.json_key()}: {active} active stages")
        for i, s in enumerate(c.stages):
            if s.r > 0.01:
                print(f"    Stage {i+1}: freq={s.freq_hz():.1f} Hz, "
                      f"r={s.r:.3f}, b0={s.gain():.3f}, "
                      f"zero_e={s.zero_energy():.4f}")


def main():
    bodies = [
        author_morpheus_like(),
        author_twin_peaks(),
        author_dillusion_reese(),
    ]

    for body in bodies:
        report_body(body)

    # Write last body (or all) to trench_live.json
    # For now: write all three as separate files, and the first to trench_live
    out_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    for body in bodies:
        path = os.path.join(out_dir, "vault", f"{body.name}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(body.to_compiled_json(provenance="heritage-designer"))
        print(f"\n  Wrote: {path}")

    # Write first body to trench_live.json for plugin hot-reload
    live_path = os.path.join(out_dir, "trench_live.json")
    with open(live_path, "w") as f:
        f.write(bodies[0].to_compiled_json(provenance="heritage-designer"))
    print(f"\n  Live: {live_path} ({bodies[0].name})")


if __name__ == "__main__":
    main()
