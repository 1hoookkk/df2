#include <catch2/catch_test_macros.hpp>

#include "dsp/FixedRateTrenchIsland.h"
#include "dsp/TrenchDspBridge.h"

#include <cmath>

namespace
{
// Minimal passthrough body: every stage is unity (c0=1), so the only thing the
// island can do to the signal is the SRC round-trip. Lets us assert the path
// stays finite and length-correct without modelling a real filter.
const char* kPassthroughJson = R"({
    "format": "compiled-v1",
    "name": "passthrough",
    "sampleRate": 44100,
    "keyframes": [
        {"label":"M0_Q0","morph":0.0,"q":0.0,"boost":1.0,
         "stages":[{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                   {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                   {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}]},
        {"label":"M0_Q100","morph":0.0,"q":1.0,"boost":1.0,
         "stages":[{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                   {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                   {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}]},
        {"label":"M100_Q0","morph":1.0,"q":0.0,"boost":1.0,
         "stages":[{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                   {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                   {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}]},
        {"label":"M100_Q100","morph":1.0,"q":1.0,"boost":1.0,
         "stages":[{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                   {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},
                   {"c0":1,"c1":0,"c2":0,"c3":0,"c4":0},{"c0":1,"c1":0,"c2":0,"c3":0,"c4":0}]}
    ]
})";

void fillSine (juce::AudioBuffer<float>& buf, double& phase, double freq, double sr)
{
    const double inc = juce::MathConstants<double>::twoPi * freq / sr;
    for (int i = 0; i < buf.getNumSamples(); ++i)
    {
        const float s = (float) (0.5 * std::sin (phase));
        for (int ch = 0; ch < buf.getNumChannels(); ++ch)
            buf.setSample (ch, i, s);
        phase += inc;
    }
}

bool allFinite (const juce::AudioBuffer<float>& buf)
{
    for (int ch = 0; ch < buf.getNumChannels(); ++ch)
        for (int i = 0; i < buf.getNumSamples(); ++i)
            if (! std::isfinite (buf.getSample (ch, i)))
                return false;
    return true;
}
} // namespace

TEST_CASE ("FixedRateTrenchIsland SRC path stays finite and length-correct under sustained audio", "[island][rt]")
{
    TrenchDspBridge bridge;
    REQUIRE (bridge.loadCartridge (juce::String (kPassthroughJson)));

    const double sr = 44100.0;  // not the E-mu rate, so the real SRC path runs
    const int maxBlock = 512;
    trench::FixedRateTrenchIsland island;
    island.prepare (sr, maxBlock, bridge);

    TrenchParams params;
    params.morph = 0.5f;
    params.q = 0.5f;

    double phase = 0.0;
    // Many blocks of varying (<= max) sizes: this is the steady-state run that a
    // leaking/overflowing FIFO would eventually trip on.
    const int sizes[] = { 64, 128, 480, 512, 256, 32, 500, 128 };
    for (int rep = 0; rep < 400; ++rep)
    {
        const int n = sizes[rep % (int) (sizeof (sizes) / sizeof (sizes[0]))];
        juce::AudioBuffer<float> buf (2, n);
        fillSine (buf, phase, 440.0, sr);
        island.process (buf, bridge, params);
        REQUIRE (buf.getNumSamples() == n);
        REQUIRE (allFinite (buf));
    }
}

TEST_CASE ("FixedRateTrenchIsland bypasses SRC at the E-mu rate", "[island][rt]")
{
    TrenchDspBridge bridge;
    REQUIRE (bridge.loadCartridge (juce::String (kPassthroughJson)));

    trench::FixedRateTrenchIsland island;
    island.prepare (TrenchRates::emuInternalRate, 256, bridge);

    TrenchParams params;
    double phase = 0.0;
    juce::AudioBuffer<float> buf (2, 256);
    fillSine (buf, phase, 1000.0, TrenchRates::emuInternalRate);
    island.process (buf, bridge, params);
    REQUIRE (buf.getNumSamples() == 256);
    REQUIRE (allFinite (buf));
}

TEST_CASE ("FixedRateTrenchIsland degrades to silence on an over-contract block", "[island][rt]")
{
    TrenchDspBridge bridge;
    REQUIRE (bridge.loadCartridge (juce::String (kPassthroughJson)));

    trench::FixedRateTrenchIsland island;
    island.prepare (44100.0, 128, bridge); // declared max 128

    TrenchParams params;
    double phase = 0.0;
    juce::AudioBuffer<float> buf (2, 1024); // host violates contract: 1024 > 128
    fillSine (buf, phase, 440.0, 44100.0);
    island.process (buf, bridge, params); // must not allocate/crash; clears instead

    REQUIRE (buf.getNumSamples() == 1024);
    bool silent = true;
    for (int ch = 0; ch < buf.getNumChannels() && silent; ++ch)
        for (int i = 0; i < buf.getNumSamples(); ++i)
            if (buf.getSample (ch, i) != 0.0f) { silent = false; break; }
    REQUIRE (silent);
}
