#pragma once

#include "Theme.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace trench::ui
{

// Shared popup styling for small secondary ComboBoxes (MOTION, TIME) — the
// same "hardware cartridge panel" dark popup TYPE uses (TypeSelectorView's
// MenuLookAndFeel), trimmed of the body-roster-specific bits (tick chip,
// seed/export action rows) since these are plain single-pick lists.
class SelectorLookAndFeel final : public juce::LookAndFeel_V4
{
public:
    void drawComboBox (juce::Graphics&, int, int, bool, int, int, int, int, juce::ComboBox&) override {}

    juce::Font getComboBoxFont (juce::ComboBox&) override { return displayFont (12.0f, true); }
    juce::Font getPopupMenuFont() override { return displayFont (13.0f, false); }

    // The popup is a little DISPLAY (2026-07-18, "simplify it make it fun"):
    // the same dark teal glass as the hero screen, phosphor ink, and the
    // accent lamp (#2BD8C3 — the wheel's own light) as tick + hover glow.
    // No stock-JUCE navy panel anywhere.
    static constexpr juce::uint32 kGlassTop = 0xff10201d, kGlassBot = 0xff0b1715;
    static constexpr juce::uint32 kInk = 0xffcfe8de, kInkDim = 0xff4e6a63;
    static constexpr juce::uint32 kLamp = 0xff2bd8c3;

    void drawPopupMenuBackground (juce::Graphics& g, int width, int height) override
    {
        const auto area = juce::Rectangle<float> (0.0f, 0.0f, (float) width, (float) height);
        juce::ColourGradient body (juce::Colour (kGlassTop), 0.0f, 0.0f,
                                   juce::Colour (kGlassBot), 0.0f, (float) height, false);
        g.setGradientFill (body);
        g.fillRect (area);
        // glass edge: dark seat below/right, faint sheen above — screen-bezel language
        g.setColour (juce::Colour (kInk).withAlpha (0.10f));
        g.drawLine (1.5f, 1.5f, (float) width - 1.5f, 1.5f, 1.0f);
        g.setColour (juce::Colours::black.withAlpha (0.70f));
        g.drawRect (area.reduced (0.5f), 1.0f);
    }

    void drawPopupMenuItem (juce::Graphics& g, const juce::Rectangle<int>& area,
                            bool isSeparator, bool isActive, bool isHighlighted,
                            bool isTicked, bool, const juce::String& text,
                            const juce::String&, const juce::Drawable*,
                            const juce::Colour*) override
    {
        auto r = area.toFloat();
        if (isSeparator)
        {
            g.setColour (juce::Colour (kInk).withAlpha (0.10f));
            g.fillRect (r.reduced (8.0f, 0.0f).withHeight (1.0f).withY (r.getCentreY()));
            return;
        }

        if (isHighlighted && isActive)
        {
            // hover = the row lights like a lamp warming, not a select-bar
            g.setColour (juce::Colour (kLamp).withAlpha (0.10f));
            g.fillRoundedRectangle (r.reduced (3.0f, 1.0f), 3.0f);
        }

        // tick = the lamp dot, lit; unticked rows keep a dark socket so the
        // eye reads a row of lamps with one on — the hardware joke of the face
        const float d = 5.0f;
        const auto dot = juce::Rectangle<float> (r.getX() + 8.0f, r.getCentreY() - d * 0.5f, d, d);
        if (isTicked)
        {
            g.setColour (juce::Colour (kLamp).withAlpha (0.35f));
            g.fillEllipse (dot.expanded (2.2f));      // bloom
            g.setColour (juce::Colour (kLamp));
        }
        else
            g.setColour (juce::Colours::black.withAlpha (0.50f));
        g.fillEllipse (dot);

        const auto textArea = area.reduced (22, 0);
        g.setFont (displayFont (13.0f, isTicked));
        juce::Colour textCol = isActive ? juce::Colour (kInk) : juce::Colour (kInkDim);
        if (isTicked) textCol = juce::Colour (kLamp).interpolatedWith (juce::Colour (kInk), 0.35f);
        g.setColour (textCol.withAlpha (isActive ? 1.0f : 0.75f));
        g.drawFittedText (text, textArea, juce::Justification::centredLeft, 1);
    }

    void getIdealPopupMenuItemSize (const juce::String& text, bool isSeparator,
                                    int standardMenuItemHeight,
                                    int& idealWidth, int& idealHeight) override
    {
        idealHeight = isSeparator ? 9 : juce::jmax (standardMenuItemHeight, 22);
        idealWidth = juce::jmax (110, text.length() * 8 + 28);
    }
};

} // namespace trench::ui
