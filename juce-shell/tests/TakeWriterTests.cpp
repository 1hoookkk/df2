#include <catch2/catch_all.hpp>

#include "dsp/TakeWriter.h"

#include <cmath>

namespace
{
juce::AudioBuffer<float> makeStereoRamp (int numSamples)
{
    juce::AudioBuffer<float> b (2, numSamples);
    for (int i = 0; i < numSamples; ++i)
    {
        b.setSample (0, i, std::sin (juce::MathConstants<float>::twoPi * 4.0f * (float) i / (float) numSamples));
        b.setSample (1, i, -0.5f * std::sin (juce::MathConstants<float>::twoPi * 4.0f * (float) i / (float) numSamples));
    }
    return b;
}

juce::File tempWav (const juce::String& name)
{
    return juce::File::getSpecialLocation (juce::File::tempDirectory)
        .getChildFile (name + "_" + juce::String (juce::Random::getSystemRandom().nextInt (1'000'000)) + ".wav");
}
} // namespace

TEST_CASE ("writeTakeWav round-trips audio at the right rate and length", "[capture][take]")
{
    const auto file = tempWav ("trench_take");
    const auto take = makeStereoRamp (480);

    REQUIRE (trench::writeTakeWav (file, take, 48000.0, {}));
    REQUIRE (file.existsAsFile());

    juce::AudioFormatManager mgr;
    mgr.registerBasicFormats();
    std::unique_ptr<juce::AudioFormatReader> reader (mgr.createReaderFor (file));
    REQUIRE (reader != nullptr);
    CHECK (reader->numChannels == 2);
    CHECK (reader->lengthInSamples == 480);
    CHECK (reader->sampleRate == Catch::Approx (48000.0));

    juce::AudioBuffer<float> back ((int) reader->numChannels, (int) reader->lengthInSamples);
    reader->read (&back, 0, (int) reader->lengthInSamples, 0, true, true);
    // 24-bit quantization tolerance.
    CHECK (back.getSample (0, 120) == Catch::Approx (take.getSample (0, 120)).margin (1.0e-4));
    CHECK (back.getSample (1, 360) == Catch::Approx (take.getSample (1, 360)).margin (1.0e-4));

    file.deleteFile();
}

TEST_CASE ("writeTakeWav stamps TRENCH provenance and a one-shot tag", "[capture][take]")
{
    const auto file = tempWav ("trench_oneshot");
    REQUIRE (trench::writeTakeWav (file, makeStereoRamp (240), 48000.0, {}));

    juce::WavAudioFormat wav;
    std::unique_ptr<juce::FileInputStream> in (file.createInputStream().release());
    REQUIRE (in != nullptr);
    std::unique_ptr<juce::AudioFormatReader> reader (
        wav.createReaderFor (in.release(), true));
    REQUIRE (reader != nullptr);

    CHECK (reader->metadataValues[juce::WavAudioFormat::bwavOriginator] == "TRENCH");
    CHECK (reader->metadataValues[juce::WavAudioFormat::acidOneShot] == "1");

    file.deleteFile();
}

TEST_CASE ("writeTakeWav writes loop tempo/beats when not a one-shot", "[capture][take]")
{
    const auto file = tempWav ("trench_loop");
    trench::TakeTags tags;
    tags.oneShot = false;
    tags.bpm = 140.0;
    tags.beats = 16; // 4 bars of 4/4
    REQUIRE (trench::writeTakeWav (file, makeStereoRamp (960), 48000.0, tags));

    juce::WavAudioFormat wav;
    std::unique_ptr<juce::AudioFormatReader> reader (
        wav.createReaderFor (file.createInputStream().release(), true));
    REQUIRE (reader != nullptr);

    CHECK (reader->metadataValues[juce::WavAudioFormat::bwavOriginator] == "TRENCH");
    CHECK (reader->metadataValues[juce::WavAudioFormat::acidOneShot] == "0");
    CHECK (reader->metadataValues[juce::WavAudioFormat::acidBeats] == "16");

    file.deleteFile();
}
