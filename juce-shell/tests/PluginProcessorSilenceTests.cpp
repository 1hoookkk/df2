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

TEST_CASE ("No Filter is not a selectable demo preset")
{
    REQUIRE (trench::kNoFilterIndex < 0);
    REQUIRE (trench::bodyIsNoFilter (trench::kNoFilterIndex));
    REQUIRE_FALSE (trench::bodyIsNoFilter (trench::kDefaultBodyIndex));
}

TEST_CASE ("Every baked roster body resolves to a packed-word cartridge")
{
    int count = 0;
    const auto* roster = trench::bodyRoster (count);
    REQUIRE (roster != nullptr);
    REQUIRE (count > 0);

    for (int index = 0; index < count; ++index)
    {
        CAPTURE (index);
        CAPTURE (trench::bodyDisplayName (index));

        if (juce::String (roster[index].base) == trench::kAuditionBase)
            continue;

        const auto jsonText = trench::bodyCartridgeJson (index);
        if (jsonText.isEmpty())
        {
            // Diagnostics builds also scan Documents/TRENCH/bodies — those
            // entries resolve as raw 240-byte packed bodies from disk, not
            // baked cartridge JSON. Exactly one of the two paths must work.
            juce::MemoryBlock raw;
            REQUIRE (trench::bodyRawBytes (index, raw));
            REQUIRE (raw.getSize() == 240);
            continue;
        }

        const auto json = juce::JSON::parse (jsonText);
        REQUIRE (! json.isVoid());

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
}

TEST_CASE ("Default body roster is the friend-demo three")
{
    // 2026-07-03 demo roster: the three real P2K references (Meaty Gizmo,
    // Talking Hedz, Lucifers Q) + the audition slot in diagnostics builds.
    // The v1_* six-body roster this test previously pinned was retired with it.
    int count = 0;
    const auto* roster = trench::bodyRoster (count);
    REQUIRE (roster != nullptr);
#ifdef TRENCH_PLAYER_DIAGNOSTICS
    REQUIRE (count >= 4);
#else
    REQUIRE (count == 3);
#endif
    REQUIRE (trench::kDefaultBodyIndex == 0);
    REQUIRE (juce::String (roster[0].displayName) == "Meaty Gizmo");
    REQUIRE (juce::String (roster[0].base) == "P2k_004_meaty_gizmo");
    REQUIRE (juce::String (roster[1].displayName) == "Talking Hedz");
    REQUIRE (juce::String (roster[1].base) == "P2k_013_talking_hedz");
    REQUIRE (juce::String (roster[2].displayName) == "Lucifers Q");
    REQUIRE (juce::String (roster[2].base) == "P2k_029_lucifer_s_q");
#ifdef TRENCH_PLAYER_DIAGNOSTICS
    REQUIRE (juce::String (roster[3].displayName) == "@ Audition (live)");
    REQUIRE (juce::String (roster[3].base) == trench::kAuditionBase);
#endif

    for (int index = 0; index < count; ++index)
    {
        REQUIRE_FALSE (trench::bodyUsesLogMorph (index));
        REQUIRE_FALSE (trench::bodySecondaryDrivesSlam (index));
    }
}

TEST_CASE ("Restored state preserves demo body and runtime controls")
{
    juce::ScopedJuceInitialiser_GUI juce;

    PluginProcessor dirty;
    auto* body = dirty.apvts.getParameter (ParamID::body);
    auto* output = dirty.apvts.getParameter (ParamID::output);
    auto* slam = dirty.apvts.getParameter (ParamID::slamDrive);
    auto* fiveD = dirty.apvts.getParameter (ParamID::fiveD);
    REQUIRE (body != nullptr);
    REQUIRE (output != nullptr);
    REQUIRE (slam != nullptr);
    REQUIRE (fiveD != nullptr);

    body->setValueNotifyingHost (body->convertTo0to1 (1.0f));
    output->setValueNotifyingHost (output->convertTo0to1 (12.0f));
    slam->setValueNotifyingHost (slam->convertTo0to1 (0.75f));
    fiveD->setValueNotifyingHost (fiveD->convertTo0to1 (1.0f));

    juce::MemoryBlock state;
    dirty.getStateInformation (state);

    PluginProcessor restored;
    restored.setStateInformation (state.getData(), (int) state.getSize());

    REQUIRE (restored.apvts.getRawParameterValue (ParamID::body)->load()
             == Catch::Approx (1.0f));
    REQUIRE (restored.apvts.getRawParameterValue (ParamID::output)->load()
             == Catch::Approx (12.0f));
    REQUIRE (restored.apvts.getRawParameterValue (ParamID::slamDrive)->load()
             == Catch::Approx (0.75f));
    REQUIRE (restored.apvts.getRawParameterValue (ParamID::fiveD)->load()
             == Catch::Approx (1.0f));
}

TEST_CASE ("PluginProcessor defaults to Bite Static and produces finite audio")
{
    juce::ScopedJuceInitialiser_GUI juce;

    PluginProcessor processor;
    REQUIRE (processor.getLastLoadOk());
    REQUIRE (processor.getLoadedBodyIndex() == trench::kDefaultBodyIndex);
    REQUIRE (processor.getProgramName (0) == juce::String ("808 Push"));
    REQUIRE (processor.apvts.getRawParameterValue (ParamID::body)->load()
             == Catch::Approx ((float) trench::kDefaultBodyIndex));
    REQUIRE (processor.apvts.getRawParameterValue (ParamID::morph)->load()
             == Catch::Approx (0.5f));
    REQUIRE (processor.apvts.getRawParameterValue (ParamID::slamDrive)->load()
             == Catch::Approx (0.25f));
    REQUIRE (processor.apvts.getRawParameterValue (ParamID::motionOn)->load()
             == Catch::Approx (0.0f));

    constexpr double sampleRate = TrenchRates::emuInternalRate;
    constexpr int blockSize = 512;
    processor.setRateAndBufferSizeDetails (sampleRate, blockSize);
    processor.prepareToPlay (sampleRate, blockSize);

    juce::AudioBuffer<float> buffer (2, blockSize);
    juce::MidiBuffer midi;
    for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
        for (int i = 0; i < buffer.getNumSamples(); ++i)
            buffer.setSample (ch, i, std::sin ((float) (i + 1) * 0.071f) * (ch == 0 ? 0.31f : -0.23f));

    processor.processBlock (buffer, midi);
    const auto probe = probePeak (buffer);
    INFO (describe (probe, 0));
    REQUIRE (std::isfinite (probe.sample));
    REQUIRE (probe.peak > 1.0e-6f);
    REQUIRE (probe.peak < 8.0f);

    processor.releaseResources();
}

TEST_CASE ("PluginProcessor default preset keeps digital silence silent")
{
    juce::ScopedJuceInitialiser_GUI juce;

    constexpr double sampleRate = TrenchRates::emuInternalRate;

    PluginProcessor processor;
    REQUIRE (processor.getLastLoadOk());
    REQUIRE (processor.getLoadedBodyIndex() == trench::kDefaultBodyIndex);
    REQUIRE (processor.apvts.getRawParameterValue (ParamID::body)->load()
             == (float) trench::kDefaultBodyIndex);
    REQUIRE (processor.getProgramName (0) == juce::String ("808 Push"));

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
