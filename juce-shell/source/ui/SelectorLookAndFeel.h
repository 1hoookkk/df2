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

    juce::Font getComboBoxFont (juce::ComboBox&) override { return displayFont (10.5f, false); }
    juce::Font getPopupMenuFont() override { return displayFont (11.5f, false); }

    void drawPopupMenuBackground (juce::Graphics& g, int width, int height) override
    {
        const auto area = juce::Rectangle<float> (0.0f, 0.0f, (float) width, (float) height);
        juce::ColourGradient body (juce::Colour (0xff1d2437), 0.0f, 0.0f,
                                   juce::Colour (0xff141a2a), 0.0f, (float) height, false);
        g.setGradientFill (body);
        g.fillRect (area);
        g.setColour (juce::Colour (0xff3a4560).withAlpha (0.85f));
        g.drawLine (1.5f, 1.5f, (float) width - 1.5f, 1.5f, 1.0f);
        g.drawLine (1.5f, 1.5f, 1.5f, (float) height - 1.5f, 1.0f);
        g.setColour (juce::Colours::black.withAlpha (0.55f));
        g.drawLine (1.5f, (float) height - 1.5f, (float) width - 1.5f, (float) height - 1.5f, 1.0f);
        g.drawLine ((float) width - 1.5f, 1.5f, (float) width - 1.5f, (float) height - 1.5f, 1.0f);
        g.setColour (juce::Colour (0xff0a0d16));
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
            return;

        if (isHighlighted && isActive)
        {
            g.setColour (juce::Colour (0xffe9dfc6).withAlpha (0.10f));
            g.fillRect (r.reduced (2.0f, 1.0f));
            auto rail = r.reduced (2.0f, 1.0f);
            rail.setWidth (2.0f);
            g.setColour (juce::Colour (0xffa4263c).withAlpha (0.85f));
            g.fillRect (rail);
        }

        if (isTicked)
        {
            g.setColour (juce::Colour (0xffe9dfc6).withAlpha (0.85f));
            float leftOffset = isHighlighted ? 6.0f : 2.0f;
            g.fillRoundedRectangle (r.removeFromLeft (4.0f).translated (leftOffset, 0.0f).reduced (1.0f, 4.0f), 1.0f);
        }

        const auto textArea = area.reduced (10, 0);
        g.setFont (displayFont (11.0f, false));
        juce::Colour textCol = isActive ? juce::Colour (0xffe9dfc6) : juce::Colour (0xff5d6478);
        if (isTicked) textCol = juce::Colour (0xfff4ecd8);
        g.setColour (textCol);
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
