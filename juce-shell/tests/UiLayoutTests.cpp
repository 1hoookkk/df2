#include <catch2/catch_all.hpp>

#include "UiLayout.h"

using trench::UiLayout;

TEST_CASE ("Default UI layout matches the shipped well rectangles")
{
    const auto d = UiLayout::defaults();
    REQUIRE (d.sourceRectFor ("morphWheel")   == juce::Rectangle<float> (127, 694, 423, 101));
    REQUIRE (d.sourceRectFor ("qWheel")       == juce::Rectangle<float> (127, 871, 423, 101));
    REQUIRE (d.sourceRectFor ("typeSelector") == juce::Rectangle<float> (230, 142, 672, 73));
    REQUIRE (d.sourceRectFor ("morphReadout") == juce::Rectangle<float> (603, 712, 168, 77));
    REQUIRE (d.sourceRectFor ("qReadout")     == juce::Rectangle<float> (602, 889, 169, 79));
    REQUIRE (d.sourceRectFor ("unknownId")    == juce::Rectangle<float>());
}

TEST_CASE ("Malformed or versionless JSON falls back to defaults")
{
    const auto d = UiLayout::defaults();

    REQUIRE (UiLayout::fromJson (juce::var(), d).sourceRectFor ("morphWheel")
             == d.sourceRectFor ("morphWheel"));

    auto* obj = new juce::DynamicObject();
    obj->setProperty ("elements", juce::var());
    REQUIRE (UiLayout::fromJson (juce::var (obj), d).sourceRectFor ("qWheel")
             == d.sourceRectFor ("qWheel"));
}

TEST_CASE ("A valid override changes only the named element")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({
        "version": 1,
        "elements": { "morphReadout": { "rect": [600, 700, 160, 70] } }
    })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE (l.sourceRectFor ("morphReadout") == juce::Rectangle<float> (600, 700, 160, 70));
    REQUIRE (l.sourceRectFor ("qReadout")     == d.sourceRectFor ("qReadout"));
    REQUIRE (l.sourceRectFor ("morphWheel")   == d.sourceRectFor ("morphWheel"));
}

TEST_CASE ("Unknown element ids are ignored")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({ "version": 1, "elements": { "foobar": { "rect": [1,2,3,4] } } })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE (l.elements.find ("foobar") == l.elements.end());
    REQUIRE (l.sourceRectFor ("morphWheel") == d.sourceRectFor ("morphWheel"));
}

TEST_CASE ("Invalid rect leaves that element at its default")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({
        "version": 1,
        "elements": {
            "morphWheel":   { "rect": [1, 2, 3] },
            "qWheel":       { "rect": [1, 2, 0, 10] },
            "typeSelector": { "rect": [1, 2, 3, "x"] }
        }
    })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE (l.sourceRectFor ("morphWheel")   == d.sourceRectFor ("morphWheel"));
    REQUIRE (l.sourceRectFor ("qWheel")       == d.sourceRectFor ("qWheel"));
    REQUIRE (l.sourceRectFor ("typeSelector") == d.sourceRectFor ("typeSelector"));
}

TEST_CASE ("Readout style overrides parse")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({
        "version": 1,
        "elements": { "morphReadout": { "rect": [603,712,168,77], "fontSize": 15, "textColor": "ff112233" } }
    })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE (l.fontSizeFor ("morphReadout").has_value());
    REQUIRE (*l.fontSizeFor ("morphReadout") == Catch::Approx (15.0f));
    REQUIRE (l.textColourFor ("morphReadout").has_value());
    REQUIRE (*l.textColourFor ("morphReadout") == juce::Colour (0xff112233));
}

TEST_CASE ("Invalid style values are ignored")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({
        "version": 1,
        "elements": { "qReadout": { "rect": [602,889,169,79], "fontSize": -3, "textColor": "nothex" } }
    })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE_FALSE (l.fontSizeFor ("qReadout").has_value());
    REQUIRE_FALSE (l.textColourFor ("qReadout").has_value());
}

TEST_CASE ("loadUiLayoutFromFile reads overrides and falls back when absent")
{
    const auto d = UiLayout::defaults();

    auto temp = juce::File::createTempFile (".json");
    temp.replaceWithText (R"({ "version": 1, "elements": { "qReadout": { "rect": [10,20,30,40] } } })");
    const auto loaded = trench::loadUiLayoutFromFile (temp);
    REQUIRE (loaded.sourceRectFor ("qReadout") == juce::Rectangle<float> (10, 20, 30, 40));
    REQUIRE (loaded.sourceRectFor ("morphWheel") == d.sourceRectFor ("morphWheel"));
    temp.deleteFile();

    auto missing = juce::File::getSpecialLocation (juce::File::tempDirectory)
                       .getChildFile ("trench_nonexistent_layout_xyz.json");
    missing.deleteFile();
    REQUIRE (trench::loadUiLayoutFromFile (missing).sourceRectFor ("morphWheel")
             == d.sourceRectFor ("morphWheel"));
}

TEST_CASE ("UiLayout round-trips through JSON serialization")
{
    const auto d = UiLayout::defaults();
    const auto reparsed = UiLayout::fromJson (juce::JSON::parse (d.toJsonString()),
                                              UiLayout::defaults());
    for (const auto* id : { "morphWheel", "qWheel", "typeSelector", "morphReadout", "qReadout" })
        REQUIRE (reparsed.sourceRectFor (id) == d.sourceRectFor (id));
}

TEST_CASE ("ensureUiLayoutFileExists creates defaults when missing and never overwrites")
{
    const auto d = UiLayout::defaults();
    auto dir = juce::File::getSpecialLocation (juce::File::tempDirectory)
                   .getChildFile ("trench_ensure_test");
    dir.deleteRecursively();
    auto file = dir.getChildFile ("ui_layout.json");
    REQUIRE_FALSE (file.existsAsFile());

    // Creates a defaults file (and its parent directory) when missing.
    trench::ensureUiLayoutFileExists (file);
    REQUIRE (file.existsAsFile());
    REQUIRE (trench::loadUiLayoutFromFile (file).sourceRectFor ("morphWheel")
             == d.sourceRectFor ("morphWheel"));

    // Must not clobber a file the user has already edited.
    file.replaceWithText (R"({ "version": 1, "elements": { "morphWheel": { "rect": [1,2,3,4] } } })");
    trench::ensureUiLayoutFileExists (file);
    REQUIRE (trench::loadUiLayoutFromFile (file).sourceRectFor ("morphWheel")
             == juce::Rectangle<float> (1, 2, 3, 4));

    dir.deleteRecursively();
}
