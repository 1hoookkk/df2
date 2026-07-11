#include <catch2/catch_all.hpp>

#include "UiLayout.h"
#include "ui/Theme.h"

using trench::UiLayout;

// These cover the current UiLayout API: defaults(), the JSON overlay used by the
// "See Your Plugin" hot-reload bridge, and the source->editor rect scaling the
// Theme layer applies. (The previous test file targeted an old fromJson(var,
// defaults) signature and stale rect values and was removed.)

TEST_CASE ("Default layout exposes the shipped element rects")
{
    const auto d = UiLayout::defaults();
    // Wells = recess MOUTHS of the recut beige plate (1010x1557), measured as
    // contiguous lum<90 runs through each well's centre (2026-07-11).
    REQUIRE (d.sourceRectFor ("morphWheel")   == juce::Rectangle<float> (115, 688, 428, 92));
    REQUIRE (d.sourceRectFor ("qWheel")       == juce::Rectangle<float> (114, 869, 429, 93));
    REQUIRE (d.sourceRectFor ("typeSelector") == juce::Rectangle<float> (218, 129, 676, 77));
    REQUIRE (d.sourceRectFor ("spectrumGrid") == juce::Rectangle<float> (110, 233, 795, 383));
    // An unknown id returns the (empty) fallback, not a garbage rect.
    REQUIRE (d.sourceRectFor ("nope")         == juce::Rectangle<float>());
}

TEST_CASE ("Every element id the editor lays out has a default")
{
    const auto d = UiLayout::defaults();
    for (const auto* id : { "morphWheel", "qWheel", "typeSelector", "morphReadout",
                            "qReadout", "spectrumGrid", "typeArrow", "modulateTag",
                            "typeLabel", "morphLabel", "qLabel" })
        REQUIRE (d.sourceRectFor (id).getWidth() > 0.0f);

    REQUIRE (! d.sourceRectFor ("brandLabel").isEmpty());   // TRENCH engraved top-left
    REQUIRE (d.sourceRectFor ("brandSub").isEmpty());       // no sub-line: TRENCH is the only name
}

TEST_CASE ("Malformed JSON falls back to the baked defaults")
{
    const auto d = UiLayout::defaults();
    for (const auto* bad : { "", "not json", "[1,2,3]", "{" })
    {
        const auto l = UiLayout::fromJson (bad);
        REQUIRE (l.sourceRectFor ("morphWheel") == d.sourceRectFor ("morphWheel"));
    }
}

TEST_CASE ("A valid override changes only the named element")
{
    // Also a regression for the dangling-var bug: if fromJson let the parsed var
    // die early, every lookup would silently fall back to defaults and this fails.
    const auto d = UiLayout::defaults();
    const auto l = UiLayout::fromJson (R"({ "elements": { "morphReadout": { "rect": [600,700,160,70] } } })");
    REQUIRE (l.sourceRectFor ("morphReadout") == juce::Rectangle<float> (600, 700, 160, 70));
    REQUIRE (l.sourceRectFor ("qReadout")     == d.sourceRectFor ("qReadout"));
    REQUIRE (l.sourceRectFor ("morphWheel")   == d.sourceRectFor ("morphWheel"));
}

TEST_CASE ("Style, colour, param and opacity overrides parse")
{
    const auto l = UiLayout::fromJson (R"({
        "elements": { "morphReadout": { "fontSize": 18, "textColor": "ff112233", "opacity": 0.5 } },
        "colours":  { "accent": "ff00ff00" },
        "params":   { "curveDbTop": 24 }
    })");
    REQUIRE (l.fontSizeFor ("morphReadout").value_or (0.0f) == Catch::Approx (18.0f));
    REQUIRE (l.textColourFor ("morphReadout").value_or (juce::Colour()) == juce::Colour (0xff112233));
    REQUIRE (l.opacityFor ("morphReadout") == Catch::Approx (0.5f));
    REQUIRE (l.colour ("accent", juce::Colours::black) == juce::Colour (0xff00ff00));
    REQUIRE (l.param ("curveDbTop", 0.0) == Catch::Approx (24.0));
}

TEST_CASE ("Out-of-range opacity is clamped to 0..1")
{
    const auto l = UiLayout::fromJson (R"({ "elements": { "qWheel": { "opacity": 5.0 } } })");
    REQUIRE (l.opacityFor ("qWheel") == Catch::Approx (1.0f));
}

TEST_CASE ("Free decals parse from the layout")
{
    const auto l = UiLayout::fromJson (R"({
        "decals": [ { "type": "text", "rect": [10,20,100,30], "text": "HELLO", "colour": "ffabcdef", "fontSize": 14 } ]
    })");
    REQUIRE (l.decals.size() == 1);
    REQUIRE (l.decals[0].type == juce::String ("text"));
    REQUIRE (l.decals[0].text == juce::String ("HELLO"));
    REQUIRE (l.decals[0].colour == juce::Colour (0xffabcdef));
    REQUIRE (l.decals[0].sourceRect == juce::Rectangle<float> (10, 20, 100, 30));
}

TEST_CASE ("source->editor mapping scales the full panel onto the editor")
{
    using namespace trench::ui;
    const auto full = sourceRectToEditor ({ 0.0f, 0.0f, kPanelSourceWidth, kPanelSourceHeight });
    REQUIRE (full.getX() == Catch::Approx (0.0f));
    REQUIRE (full.getY() == Catch::Approx (0.0f));
    REQUIRE (full.getWidth()  == Catch::Approx ((float) kEditorWidth));
    REQUIRE (full.getHeight() == Catch::Approx ((float) kEditorHeight));

    // Panel centre maps to editor centre.
    const auto centre = sourceRectToEditor ({ kPanelSourceWidth * 0.5f, kPanelSourceHeight * 0.5f, 0.0f, 0.0f });
    REQUIRE (centre.getX() == Catch::Approx ((float) kEditorWidth  * 0.5f));
    REQUIRE (centre.getY() == Catch::Approx ((float) kEditorHeight * 0.5f));
}
