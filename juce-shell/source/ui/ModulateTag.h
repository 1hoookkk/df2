#pragma once

#include "Theme.h"
#include "../TrenchBodyRoster.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>
#include <functional>
#include <memory>

namespace trench::ui
{

// Seated MOTION switch on the graph glass. Clicking it no longer arms a
// behavior directly (that decision moved to the tile grid on GraphDisplay,
// via onRequestGrid) — it only reflects the current armed/disarmed state.
class ModulateTag : public juce::Component
{
public:
    static inline const juce::Colour kQuietInk { 0xffd9bcc4 };

    std::function<void()> onRequestGrid; // set by PluginEditor -> graph->openTileGrid()

    ModulateTag (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : state (apvts), t (theme)
    {
        motionOnParam = state.getParameter (ParamID::motionOn);
        if (motionOnParam != nullptr)
        {
            attachment = std::make_unique<juce::ParameterAttachment> (
                *motionOnParam, [this] (float) { repaint(); });
            attachment->sendInitialUpdate();
        }

        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Motion");
        setHelpText ("Open the Modulation tile grid");
    }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }

    bool hitTest (int x, int y) override
    {
        return wordHitBounds().contains ((float) x, (float) y);
    }

    void mouseDown (const juce::MouseEvent&) override
    {
        down = true;
        repaint();
        if (onRequestGrid)
            onRequestGrid();
    }

    void mouseUp (const juce::MouseEvent&) override
    {
        down = false;
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const bool on = isOn();
        const auto b = getLocalBounds().toFloat();
        const auto amberOrange = t.amber();
        const auto dotRect = lampBounds (b);

        if (on)
        {
            g.setColour (amberOrange.withAlpha (0.22f));
            g.fillEllipse (dotRect.expanded (5.5f));
            g.setColour (amberOrange.withAlpha (0.50f));
            g.fillEllipse (dotRect.expanded (2.5f));
            g.setColour (amberOrange.brighter (0.35f));
            g.fillEllipse (dotRect);
        }
        else
        {
            g.setColour (kQuietInk.withAlpha (0.88f));
            g.fillEllipse (dotRect);
        }

        const auto textRect = wordHitBounds().expanded (0.0f, 3.0f);
        auto font = displayFont (12.5f, false).withStyle (juce::Font::italic);
        g.setFont (font);

        if (on)
        {
            g.setColour (amberOrange.withAlpha (0.35f));
            g.drawText ("Modulation", textRect.translated (0.0f, 1.0f), juce::Justification::centredLeft);
            g.setColour (juce::Colour (0xfffbeadd).withAlpha (hover ? 1.0f : 0.96f));
        }
        else
            g.setColour (kQuietInk.withAlpha (hover ? 1.0f : 0.88f));

        g.drawText ("Modulation", textRect, juce::Justification::centredLeft);
    }

private:
    static juce::Rectangle<float> lampBounds (juce::Rectangle<float> b)
    {
        constexpr float dotSize = 8.0f;
        return juce::Rectangle<float> (dotSize, dotSize)
            .withCentre ({ b.getX() + dotSize / 2.0f + 2.0f, b.getCentreY() });
    }

    juce::Rectangle<float> wordHitBounds() const
    {
        const auto b = getLocalBounds().toFloat();
        const auto font = displayFont (12.5f, false).withStyle (juce::Font::italic);
        const auto dot = lampBounds (b);
        const float w = juce::GlyphArrangement::getStringWidth (font, "Modulation") + 8.0f;
        const float h = juce::jmax (16.0f, font.getHeight() + 4.0f);
        return { dot.getRight() + 4.0f, b.getCentreY() - h * 0.5f, w, h };
    }

    bool isOn() const { return motionOnParam != nullptr && motionOnParam->getValue() > 0.5f; }

    juce::AudioProcessorValueTreeState& state;
    Theme t;
    juce::RangedAudioParameter* motionOnParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> attachment;
    bool hover = false;
    bool down = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ModulateTag)
};

} // namespace trench::ui
