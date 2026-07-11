#include <catch2/catch_all.hpp>

#include "dsp/CapturePlan.h"

using trench::CaptureRange;
using trench::planCapture;

TEST_CASE ("planCapture: Hit and Tail are fixed one-shots", "[capture][plan]")
{
    const auto hit = planCapture (CaptureRange::Hit, 120.0);
    CHECK (hit.seconds == Catch::Approx (0.6));
    CHECK (hit.oneShot);
    CHECK (hit.beats == 0);

    const auto tail = planCapture (CaptureRange::Tail, 120.0);
    CHECK (tail.seconds == Catch::Approx (3.0));
    CHECK (tail.oneShot);
    CHECK (tail.beats == 0);
}

TEST_CASE ("planCapture: bar ranges lock to host tempo as loops", "[capture][plan]")
{
    const auto bar = planCapture (CaptureRange::OneBar, 120.0); // 60/120*4
    CHECK (bar.seconds == Catch::Approx (2.0));
    CHECK_FALSE (bar.oneShot);
    CHECK (bar.beats == 4);

    const auto four = planCapture (CaptureRange::FourBar, 120.0); // 60/120*16
    CHECK (four.seconds == Catch::Approx (8.0));
    CHECK_FALSE (four.oneShot);
    CHECK (four.beats == 16);

    const auto fourFast = planCapture (CaptureRange::FourBar, 140.0);
    CHECK (fourFast.seconds == Catch::Approx (60.0 / 140.0 * 16.0));
    CHECK (fourFast.beats == 16);
}

TEST_CASE ("planCapture: bar ranges fall back to 120 BPM with no host tempo", "[capture][plan]")
{
    const auto bar = planCapture (CaptureRange::OneBar, 0.0);
    CHECK (bar.seconds == Catch::Approx (2.0));
    CHECK_FALSE (bar.oneShot);
    CHECK (bar.beats == 4);

    const auto four = planCapture (CaptureRange::FourBar, 0.0);
    CHECK (four.seconds == Catch::Approx (8.0));
    CHECK (four.beats == 16);
}
