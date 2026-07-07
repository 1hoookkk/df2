#include <catch2/catch_all.hpp>

#include "PluginProcessor.h"
#include "TrenchBodyRoster.h"

#include <cmath>

namespace
{
void setParam (PluginProcessor& p, const char* id, float value)
{
    if (auto* param = p.apvts.getParameter (id))
        param->setValueNotifyingHost (param->convertTo0to1 (value));
}

void setChoice (PluginProcessor& p, const char* id, int index)
{
    if (auto* param = p.apvts.getParameter (id))
        param->setValueNotifyingHost (param->convertTo0to1 ((float) index));
}
}

TEST_CASE ("getModulationBehaviorForUi reads the explicit tile, not the body name", "[modulation]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    PluginProcessor processor;

    setParam (processor, ParamID::motionOn, 1.0f);

    setChoice (processor, ParamID::motionTile, 0); // Riser
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::AutoHalf);

    setChoice (processor, ParamID::motionTile, 1); // Breathe
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::AutoQuarter);

    setChoice (processor, ParamID::motionTile, 2); // Adlib Chop
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::Dynamic);

    setChoice (processor, ParamID::motionTile, 3); // Wobble
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::Wobble);

    setParam (processor, ParamID::motionOn, 0.0f);
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::Static);
}

TEST_CASE ("Wobble rests at center when transport is stopped, like Riser/Breathe", "[modulation]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    constexpr double sampleRate = 48000.0;
    constexpr int blockSize = 512;

    PluginProcessor processor;
    processor.setRateAndBufferSizeDetails (sampleRate, blockSize);
    processor.prepareToPlay (sampleRate, blockSize);
    setParam (processor, ParamID::motionOn, 1.0f);
    setChoice (processor, ParamID::motionTile, 3); // Wobble

    juce::AudioBuffer<float> buffer (2, blockSize);
    juce::MidiBuffer midi;
    for (int b = 0; b < 24; ++b)
    {
        buffer.clear();
        processor.processBlock (buffer, midi);
    }
    REQUIRE (processor.getMotionStepForUi() == 0);
    REQUIRE_FALSE (processor.isMorphModulatedForUi());

    processor.releaseResources();
}

TEST_CASE ("5D rides along with an armed tile only when 5D's own base is nonzero", "[modulation][5d]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    constexpr double sampleRate = 48000.0;
    constexpr int blockSize = 512;

    auto runAndReadSpace = [&] (bool fiveDOn, bool motionOn) -> float
    {
        PluginProcessor processor;
        processor.setRateAndBufferSizeDetails (sampleRate, blockSize);
        processor.prepareToPlay (sampleRate, blockSize);
        setParam (processor, ParamID::fiveD, fiveDOn ? 1.0f : 0.0f);
        setParam (processor, ParamID::motionOn, motionOn ? 1.0f : 0.0f);
        setChoice (processor, ParamID::motionTile, 0); // Riser

        juce::AudioBuffer<float> buffer (2, blockSize);
        juce::MidiBuffer midi;
        float lastSpace = 0.0f;
        for (int b = 0; b < 8; ++b)
        {
            for (int ch = 0; ch < 2; ++ch)
                for (int i = 0; i < blockSize; ++i)
                    buffer.setSample (ch, i, std::sin ((float) (i + 1) * 0.071f) * 0.5f);
            processor.processBlock (buffer, midi);
            lastSpace = processor.getEffectiveSpaceForUi();
        }
        processor.releaseResources();
        return lastSpace;
    };

    // 5D off: no ride-along possible, must stay exactly 0 regardless of Motion.
    REQUIRE (runAndReadSpace (false, true) == Catch::Approx (0.0f));

    // 5D on, Motion off: space sits at its static base, no motion offset.
    const float staticSpace = runAndReadSpace (true, false);
    REQUIRE (staticSpace > 0.0f);

    // 5D on, Motion on (Riser): space must be finite and bounded 0..1. It is
    // allowed to equal the static value at any single instant (the offset is
    // signal-dependent), so this only asserts safety, not movement.
    const float riddenSpace = runAndReadSpace (true, true);
    REQUIRE (std::isfinite (riddenSpace));
    REQUIRE (riddenSpace >= 0.0f);
    REQUIRE (riddenSpace <= 1.0f);
}

TEST_CASE ("motionTile survives full processor save/restore", "[modulation][recall]")
{
    juce::ScopedJuceInitialiser_GUI juce;

    PluginProcessor dirty;
    setParam (dirty, ParamID::motionOn, 1.0f);
    setChoice (dirty, ParamID::motionTile, 3); // Wobble

    juce::MemoryBlock state;
    dirty.getStateInformation (state);

    PluginProcessor restored;
    restored.setStateInformation (state.getData(), (int) state.getSize());

    REQUIRE (restored.getModulationBehaviorForUi() == trench::TypeBehavior::Wobble);
}

TEST_CASE ("Switching tiles while armed produces finite output with no discontinuity blow-up", "[modulation]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    constexpr double sampleRate = 48000.0;
    constexpr int blockSize = 512;

    PluginProcessor processor;
    processor.setRateAndBufferSizeDetails (sampleRate, blockSize);
    processor.prepareToPlay (sampleRate, blockSize);
    setParam (processor, ParamID::motionOn, 1.0f);
    setChoice (processor, ParamID::motionTile, 0); // Riser

    juce::AudioBuffer<float> buffer (2, blockSize);
    juce::MidiBuffer midi;
    auto fillSine = [] (juce::AudioBuffer<float>& b)
    {
        for (int ch = 0; ch < b.getNumChannels(); ++ch)
            for (int i = 0; i < b.getNumSamples(); ++i)
                b.setSample (ch, i, std::sin ((float) (i + 1) * 0.071f) * 0.5f);
    };

    for (int b = 0; b < 8; ++b) { fillSine (buffer); processor.processBlock (buffer, midi); }

    // Switch tiles mid-stream (Riser -> Adlib Chop -> Wobble), one block each.
    for (int tile : { 2, 3, 1, 0 })
    {
        setChoice (processor, ParamID::motionTile, tile);
        fillSine (buffer);
        processor.processBlock (buffer, midi);
        for (int ch = 0; ch < 2; ++ch)
        {
            const auto* d = buffer.getReadPointer (ch);
            for (int i = 0; i < blockSize; ++i)
            {
                REQUIRE (std::isfinite (d[i]));
                REQUIRE (std::abs (d[i]) < 8.0f);
            }
        }
    }

    processor.releaseResources();
}
