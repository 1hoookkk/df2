// Proves Amount changes the exact coefficients the on-screen curve reads
// (dspBridge.readUiSnapshot), the same API GraphDisplay::updateFromCoeffs uses.
// Regression coverage for the original bug: the old audio-crossfade Amount
// never touched these coefficients, so the curve was structurally guaranteed
// to never move regardless of Amount.

#include <catch2/catch_all.hpp>

#include "PluginProcessor.h"
#include "TrenchBodyRoster.h"

#include <cmath>

namespace
{
void setP (PluginProcessor& p, const char* id, float v)
{
    if (auto* prm = p.apvts.getParameter (id))
        prm->setValueNotifyingHost (prm->convertTo0to1 (v));
}
}

TEST_CASE ("DIAGNOSTIC: readUiSnapshot coefficients differ between Amount=100 and Amount=0", "[amount][diagnostic]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    constexpr double sampleRate = 44100.0;
    constexpr int    block      = 512;

    PluginProcessor proc;
    proc.setRateAndBufferSizeDetails (sampleRate, block);
    proc.prepareToPlay (sampleRate, block);
    setP (proc, ParamID::body, (float) trench::kDefaultBodyIndex);
    juce::MessageManager::getInstance()->runDispatchLoopUntil (80);
    setP (proc, ParamID::morph, 0.5f);
    setP (proc, ParamID::q, 0.4f);

    juce::AudioBuffer<float> buf (2, block);
    juce::MidiBuffer midi;
    auto fillSine = [] (juce::AudioBuffer<float>& b)
    {
        for (int ch = 0; ch < b.getNumChannels(); ++ch)
            for (int i = 0; i < b.getNumSamples(); ++i)
                b.setSample (ch, i, std::sin ((float) (i + 1) * 0.071f) * 0.3f);
    };

    // Settle at amount=100 first (default), then process enough blocks at
    // amount=0 for the coefficient ramp to complete.
    setP (proc, ParamID::amount, 1.0f);
    for (int b = 0; b < 10; ++b) { fillSine (buf); proc.processBlock (buf, midi); }

    float coeffsFull[30] = {};
    float boostFull = 0.0f;
    REQUIRE (proc.dspBridge.readUiSnapshot (coeffsFull, boostFull));

    setP (proc, ParamID::amount, 0.0f);
    for (int b = 0; b < 10; ++b) { fillSine (buf); proc.processBlock (buf, midi); }

    float coeffsFlat[30] = {};
    float boostFlat = 0.0f;
    REQUIRE (proc.dspBridge.readUiSnapshot (coeffsFlat, boostFlat));

    UNSCOPED_INFO ("--- Amount=100 stage 0 coeffs (b0,b1,b2,a1,a2) ---");
    UNSCOPED_INFO (coeffsFull[0] << ", " << coeffsFull[1] << ", " << coeffsFull[2] << ", " << coeffsFull[3] << ", " << coeffsFull[4]);
    UNSCOPED_INFO ("--- Amount=0 stage 0 coeffs (b0,b1,b2,a1,a2) ---");
    UNSCOPED_INFO (coeffsFlat[0] << ", " << coeffsFlat[1] << ", " << coeffsFlat[2] << ", " << coeffsFlat[3] << ", " << coeffsFlat[4]);
    UNSCOPED_INFO ("boost: full=" << boostFull << " flat=" << boostFlat);

    // Amount=0 must drive every stage to passthrough (b0=1, everything else 0) —
    // exactly what the curve renders as a flat line.
    for (int s = 0; s < 6; ++s)
    {
        REQUIRE (coeffsFlat[s * 5 + 0] == Catch::Approx (1.0f).margin (1e-4));
        REQUIRE (coeffsFlat[s * 5 + 1] == Catch::Approx (0.0f).margin (1e-4));
        REQUIRE (coeffsFlat[s * 5 + 2] == Catch::Approx (0.0f).margin (1e-4));
        REQUIRE (coeffsFlat[s * 5 + 3] == Catch::Approx (0.0f).margin (1e-4));
        REQUIRE (coeffsFlat[s * 5 + 4] == Catch::Approx (0.0f).margin (1e-4));
    }

    // At least one coefficient must clearly differ from the full-strength body.
    bool anyDiff = false;
    for (int i = 0; i < 30; ++i)
        if (std::abs (coeffsFull[i] - coeffsFlat[i]) > 0.01f)
            anyDiff = true;
    REQUIRE (anyDiff);
}
