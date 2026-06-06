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

TEST_CASE ("Filter 00 is always a packed-word No Filter body")
{
    REQUIRE (trench::kNoFilterIndex == 0);
    REQUIRE (trench::bodyDisplayName (trench::kNoFilterIndex) == trench::kNoFilterName);
    REQUIRE (trench::bodyIsNoFilter (trench::kNoFilterIndex));

    const auto json = juce::JSON::parse (trench::bodyCartridgeJson (trench::kNoFilterIndex));
    REQUIRE (! json.isVoid());
    REQUIRE (json.getProperty ("name", juce::String()) == trench::kNoFilterName);

    const auto* keyframes = json.getProperty ("keyframes", juce::var()).getArray();
    REQUIRE (keyframes != nullptr);
    REQUIRE (keyframes->size() == 4);
    for (const auto& keyframe : *keyframes)
    {
        const auto* stages = keyframe.getProperty ("packedWords", juce::var()).getArray();
        REQUIRE (stages != nullptr);
        REQUIRE (stages->size() == 6);
        for (const auto& stage : *stages)
        {
            const auto* words = stage.getArray();
            REQUIRE (words != nullptr);
            REQUIRE (words->size() == 5);
        }
    }
}

TEST_CASE ("PluginProcessor No Filter packed body is explicitly bypassed")
{
    juce::ScopedJuceInitialiser_GUI juce;

    for (const double sampleRate : { 44100.0, 48000.0, 96000.0 })
    {
        CAPTURE (sampleRate);

        PluginProcessor processor;
        REQUIRE (processor.getLastLoadOk());
        REQUIRE (processor.getLoadedBodyIndex() == trench::kNoFilterIndex);

        constexpr int blockSize = 512;
        processor.setRateAndBufferSizeDetails (sampleRate, blockSize);
        processor.prepareToPlay (sampleRate, blockSize);

        juce::AudioBuffer<float> buffer (2, blockSize);
        juce::AudioBuffer<float> expected (2, blockSize);
        juce::MidiBuffer midi;
        for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
            for (int i = 0; i < buffer.getNumSamples(); ++i)
                buffer.setSample (ch, i, std::sin ((float) (i + 1) * 0.071f) * (ch == 0 ? 0.31f : -0.23f));
        expected.makeCopyOf (buffer);

        processor.processBlock (buffer, midi);

        for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
            for (int i = 0; i < buffer.getNumSamples(); ++i)
                REQUIRE (buffer.getSample (ch, i) == Catch::Approx (expected.getSample (ch, i)).margin (1.0e-7f));

        processor.releaseResources();
    }
}

TEST_CASE ("PluginProcessor No Filter bypass keeps digital silence silent")
{
    juce::ScopedJuceInitialiser_GUI juce;

    for (const double sampleRate : { 44100.0, 48000.0, 96000.0 })
    {
        CAPTURE (sampleRate);

        PluginProcessor processor;
        REQUIRE (processor.getLastLoadOk());
        REQUIRE (processor.getLoadedBodyIndex() == trench::kNoFilterIndex);
        REQUIRE (processor.apvts.getRawParameterValue (ParamID::body)->load()
                 == (float) trench::kNoFilterIndex);
        REQUIRE (processor.getProgramName (0) == trench::kNoFilterName);

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
