#include <catch2/catch_all.hpp>

#include "dsp/CaptureRing.h"

#include <vector>

namespace
{
// Writes a ramp value==index to L and index+1000 to R across n frames starting at
// `start`, in `chunk`-sized writes to exercise multi-call accumulation and wrap.
void writeRamp (trench::CaptureRing& r, int start, int n, int chunk)
{
    std::vector<float> l ((size_t) chunk), rr ((size_t) chunk);
    int done = 0;
    while (done < n)
    {
        const int c = std::min (chunk, n - done);
        for (int i = 0; i < c; ++i)
        {
            l[(size_t) i]  = float (start + done + i);
            rr[(size_t) i] = float (start + done + i + 1000);
        }
        r.write (l.data(), rr.data(), c);
        done += c;
    }
}
} // namespace

TEST_CASE ("CaptureRing returns the trailing window when under capacity", "[capture]")
{
    trench::CaptureRing r;
    r.prepare (1000.0, 1.0);
    CHECK (r.capacity() == 1000);

    writeRamp (r, 0, 100, 16);
    std::vector<float> oL (1000), oR (1000);
    const int frames = r.snapshotLast (0.05, oL.data(), oR.data(), 1000); // 50 frames

    CHECK (frames == 50);
    CHECK (oL[0] == Catch::Approx (50.0f));    // oldest of the window
    CHECK (oL[49] == Catch::Approx (99.0f));   // newest written
    CHECK (oR[0] == Catch::Approx (1050.0f));  // stereo channels independent
    CHECK (oR[49] == Catch::Approx (1099.0f));
}

TEST_CASE ("CaptureRing wraps and keeps only the newest capacity", "[capture]")
{
    trench::CaptureRing r;
    r.prepare (100.0, 1.0); // cap 100
    CHECK (r.capacity() == 100);

    writeRamp (r, 0, 250, 7); // chunked writes straddling the wrap
    std::vector<float> oL (100), oR (100);
    const int frames = r.snapshotLast (1.0, oL.data(), oR.data(), 100);

    CHECK (frames == 100);
    CHECK (oL[0] == Catch::Approx (150.0f));
    CHECK (oL[99] == Catch::Approx (249.0f));
}

TEST_CASE ("CaptureRing clamps the window to samples available", "[capture]")
{
    trench::CaptureRing r;
    r.prepare (100.0, 1.0);
    writeRamp (r, 0, 30, 30);
    std::vector<float> oL (100), oR (100);
    const int frames = r.snapshotLast (1.0, oL.data(), oR.data(), 100);

    CHECK (frames == 30);
    CHECK (oL[0] == Catch::Approx (0.0f));
    CHECK (oL[29] == Catch::Approx (29.0f));
}

TEST_CASE ("CaptureRing clamps the window to the caller's maxFrames", "[capture]")
{
    trench::CaptureRing r;
    r.prepare (1000.0, 1.0);
    writeRamp (r, 0, 100, 100);
    std::vector<float> oL (20), oR (20);
    const int frames = r.snapshotLast (0.05, oL.data(), oR.data(), 20); // wants 50, clamp to 20

    CHECK (frames == 20);
    CHECK (oL[0] == Catch::Approx (80.0f));   // newest 20 = 80..99
    CHECK (oL[19] == Catch::Approx (99.0f));
}

TEST_CASE ("CaptureRing with no audio yet returns zero frames", "[capture]")
{
    trench::CaptureRing r;
    r.prepare (48000.0, 4.0);
    std::vector<float> oL (16), oR (16);
    CHECK (r.snapshotLast (1.0, oL.data(), oR.data(), 16) == 0);
}
