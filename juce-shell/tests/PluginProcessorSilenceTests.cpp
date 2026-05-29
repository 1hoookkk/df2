#include <catch2/catch_all.hpp>

#include "PluginProcessor.h"
#include "TrenchBodyRoster.h"
#include "dsp/FixedRateTrenchIsland.h"
#include "dsp/TrenchDspBridge.h"

#include <iomanip>
#include <sstream>

namespace
{
struct PeakProbe
{
    float peak = 0.0f;
    float sample = 0.0f;
    int channel = -1;
    int index = -1;
};

PeakProbe probePeak (const juce::AudioBuffer<float>& buffer)
{
    PeakProbe probe;
    for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
    {
        const auto* data = buffer.getReadPointer (ch);
        for (int i = 0; i < buffer.getNumSamples(); ++i)
        {
            const auto mag = std::abs (data[i]);
            if (mag > probe.peak)
            {
                probe.peak = mag;
                probe.sample = data[i];
                probe.channel = ch;
                probe.index = i;
            }
        }
    }
    return probe;
}

std::string describe (const PeakProbe& probe, int block)
{
    std::ostringstream os;
    os << "block=" << block
       << " ch=" << probe.channel
       << " idx=" << probe.index
       << " sample=" << std::scientific << std::setprecision (9) << probe.sample
       << " peak=" << std::scientific << std::setprecision (9) << probe.peak;
    return os.str();
}
}

TEST_CASE ("PluginProcessor Bypass body keeps digital silence silent")
{
    juce::ScopedJuceInitialiser_GUI juce;

    for (const double sampleRate : { 44100.0, 48000.0, 96000.0 })
    {
        CAPTURE (sampleRate);

        PluginProcessor processor;
        REQUIRE (processor.getLastLoadOk());
        REQUIRE (processor.getLoadedBodyIndex() == 0);

        constexpr int blockSize = 512;
        processor.setRateAndBufferSizeDetails (sampleRate, blockSize);
        processor.prepareToPlay (sampleRate, blockSize);

        juce::AudioBuffer<float> buffer (2, blockSize);
        juce::MidiBuffer midi;

        for (int block = 0; block < 64; ++block)
        {
            buffer.clear();
            processor.processBlock (buffer, midi);
            const auto probe = probePeak (buffer);
            INFO (describe (probe, block));
            REQUIRE (probe.peak < 1.0e-12f);
        }

        processor.releaseResources();
    }
}

TEST_CASE ("FixedRateTrenchIsland keeps Bypass digital silence silent")
{
    for (const double sampleRate : { 44100.0, 48000.0, 96000.0 })
    {
        CAPTURE (sampleRate);

        TrenchDspBridge bridge;
        trench::FixedRateTrenchIsland island;

        constexpr int blockSize = 512;
        island.prepare (sampleRate, blockSize, bridge);
        REQUIRE (bridge.loadCartridge (trench::bodyCartridgeJson (0)));
        bridge.setInputMode (0);
        bridge.setSpatialMode (2);

        juce::AudioBuffer<float> buffer (2, blockSize);
        TrenchParams params;

        for (int block = 0; block < 64; ++block)
        {
            buffer.clear();
            island.process (buffer, bridge, params);
            const auto probe = probePeak (buffer);
            INFO (describe (probe, block));
            REQUIRE (probe.peak < 1.0e-12f);
        }
    }
}

TEST_CASE ("TrenchDspBridge directly keeps Bypass digital silence silent")
{
    for (const double sampleRate : { 39062.5, 44100.0, 48000.0, 96000.0 })
    {
        CAPTURE (sampleRate);

        TrenchDspBridge bridge;
        bridge.prepare (sampleRate, 512);
        REQUIRE (bridge.loadCartridge (trench::bodyCartridgeJson (0)));
        bridge.setInputMode (0);
        bridge.setSpatialMode (2);

        juce::AudioBuffer<float> buffer (2, 512);
        TrenchParams params;

        for (int block = 0; block < 64; ++block)
        {
            buffer.clear();
            bridge.process (buffer, params);
            const auto probe = probePeak (buffer);
            INFO (describe (probe, block));
            REQUIRE (probe.peak < 1.0e-12f);
        }
    }
}

TEST_CASE ("TrenchDspBridge load-before-prepare keeps Bypass digital silence silent")
{
    for (const double sampleRate : { 39062.5, 44100.0, 48000.0, 96000.0 })
    {
        CAPTURE (sampleRate);

        TrenchDspBridge bridge;
        REQUIRE (bridge.loadCartridge (trench::bodyCartridgeJson (0)));
        bridge.prepare (sampleRate, 512);
        bridge.setInputMode (0);
        bridge.setSpatialMode (2);

        juce::AudioBuffer<float> buffer (2, 512);
        TrenchParams params;

        for (int block = 0; block < 64; ++block)
        {
            buffer.clear();
            bridge.process (buffer, params);
            const auto probe = probePeak (buffer);
            INFO (describe (probe, block));
            REQUIRE (probe.peak < 1.0e-12f);
        }
    }
}
