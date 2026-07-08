#include <catch2/catch_all.hpp>

#include "PluginProcessor.h"
#include "TrenchBodyRoster.h"
#include "parameters/TrenchParameters.h"

// Proves the mechanical claim behind "hit SEED until it knocks, drag TAKE,
// hit SEED again, drag TAKE again": each SEED must produce a genuinely
// different, valid 240-byte body -- not the same bytes relabelled, not
// garbage. Uses the exact same public API path a user's SEED action does
// (seedCurrentBody), verified via exportCurrentBody's real file output
// rather than reaching into private state.

TEST_CASE ("SEED produces distinct, valid 240-byte bodies across repeated calls", "[seed][workflow]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    PluginProcessor processor;
    processor.setPlayConfigDetails (0, 2, 44100.0, 512);
    processor.prepareToPlay (44100.0, 512);

    // Arm a real body (roster has no "808 Body" yet -- see gap noted
    // separately -- Talking Hedz stands in for "load one body").
    auto* bodyParam = processor.apvts.getParameter (ParamID::body);
    REQUIRE (bodyParam != nullptr);
    bodyParam->setValueNotifyingHost (bodyParam->convertTo0to1 (1.0f)); // index 1 = Talking Hedz

    juce::AudioBuffer<float> buf (2, 512);
    buf.clear();
    juce::MidiBuffer midi;
    for (int i = 0; i < 4; ++i)
        processor.processBlock (buf, midi); // let the body actually load

    auto exportDir = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                          .getChildFile ("TRENCH").getChildFile ("exports");
    juce::Array<juce::File> before;
    if (exportDir.isDirectory())
        before = exportDir.findChildFiles (juce::File::findFiles, false, "*.body240");

    processor.seedCurrentBody();
    processor.exportCurrentBody();
    processor.seedCurrentBody();
    processor.exportCurrentBody();

    auto after = exportDir.findChildFiles (juce::File::findFiles, false, "*.body240");
    REQUIRE (after.size() >= before.size() + 2);

    // The two newest files are this test's two SEED+export calls.
    after.sort();
    auto f1 = after[after.size() - 2];
    auto f2 = after[after.size() - 1];

    juce::MemoryBlock b1, b2;
    REQUIRE (f1.loadFileAsData (b1));
    REQUIRE (f2.loadFileAsData (b2));
    REQUIRE (b1.getSize() == 240);
    REQUIRE (b2.getSize() == 240);
    REQUIRE (b1 != b2); // two SEED calls -> two genuinely different bodies, not the same bytes twice

    f1.deleteFile();
    f2.deleteFile();
}
