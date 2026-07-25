#pragma once
#include "Theme.h"
#include <juce_gui_basics/juce_gui_basics.h>
namespace trench::ui
{
class SelectorLookAndFeel : public juce::LookAndFeel_V4
{
public:
    float itemFontSize = 13.5f;   // menus may compact this (modulation: 11.5)
    int itemHeight = 24;
    void drawComboBox (juce::Graphics&, int, int, bool, int, int, int, int, juce::ComboBox&) override {}
    juce::Font getComboBoxFont (juce::ComboBox&) override { return displayFont (12.0f, true); }
    juce::Font getPopupMenuFont() override { return displayFont (itemFontSize, false); }
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
        g.setColour (juce::Colour (kInk).withAlpha (0.10f));
        g.drawLine (1.5f, 1.5f, (float) width - 1.5f, 1.5f, 1.0f);
        g.setColour (juce::Colours::black.withAlpha (0.70f));
        g.drawRect (area.reduced (0.5f), 1.0f);
    }
    void drawPopupMenuItem (juce::Graphics& g, const juce::Rectangle<int>& area,
                            bool isSeparator, bool isActive, bool isHighlighted,
                            bool isTicked, bool hasSubMenu, const juce::String& text,
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
            g.setColour (juce::Colour (kLamp).withAlpha (0.10f));
            g.fillRoundedRectangle (r.reduced (3.0f, 1.0f), 3.0f);
            auto rail = r.reduced (3.0f, 1.0f);
            rail.setWidth (2.0f);
            g.setColour (juce::Colour (kLamp).withAlpha (0.85f));
            g.fillRect (rail);
        }
        const float d = 5.0f;
        const auto dot = juce::Rectangle<float> (r.getX() + 8.0f, r.getCentreY() - d * 0.5f, d, d);
        if (isTicked)
        {
            g.setColour (juce::Colour (kLamp).withAlpha (0.35f));
            g.fillEllipse (dot.expanded (2.2f));
            g.setColour (juce::Colour (kLamp));
        }
        else
            g.setColour (juce::Colours::black.withAlpha (0.50f));
        g.fillEllipse (dot);
        const auto textArea = area.reduced (22, 0);
        g.setFont (displayFont (itemFontSize, isTicked));
        juce::Colour textCol = isActive ? juce::Colour (kInk) : juce::Colour (kInkDim);
        if (isTicked) textCol = juce::Colour (kLamp).interpolatedWith (juce::Colour (kInk), 0.35f);
        g.setColour (textCol.withAlpha (isActive ? 1.0f : 0.75f));
        g.drawFittedText (text, textArea, juce::Justification::centredLeft, 1);
        if (hasSubMenu)
        {
            const auto arrow = area.toFloat().removeFromRight (14.0f).withSizeKeepingCentre (5.0f, 8.0f);
            juce::Path path;
            path.startNewSubPath (arrow.getX(), arrow.getY());
            path.lineTo (arrow.getRight(), arrow.getCentreY());
            path.lineTo (arrow.getX(), arrow.getBottom());
            g.setColour (juce::Colour (kInk).withAlpha (0.8f));
            g.strokePath (path, juce::PathStrokeType (1.2f));
        }
    }
    void getIdealPopupMenuItemSize (const juce::String& text, bool isSeparator,
                                    int standardMenuItemHeight,
                                    int& idealWidth, int& idealHeight) override
    {
        idealHeight = isSeparator ? 9 : juce::jmax (standardMenuItemHeight, itemHeight);
        idealWidth = juce::jmax (110, text.length() * 8 + 28);
    }
};
}
