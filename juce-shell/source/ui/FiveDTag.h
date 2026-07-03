#pragma once

#include "Theme.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>
#include <memory>

namespace trench::ui
{

// Seated 5D switch on the graph glass, below Modulation — same tag language
// (lamp dot + italic word, no painted face). One click toggles the real
// QSound spatial stage (the fiveD/Space parameter) between off and full.
class FiveDTag : public juce::Component
{
public:
    FiveDTag (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : state (apvts), t (theme)
    {
        param = state.getParameter (ParamID::fiveD);
        if (param != nullptr)
        {
            attachment = std::make_unique<juce::ParameterAttachment> (
                *param, [this] (float) { repaint(); });
            attachment->sendInitialUpdate();
        }
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("5D");
        setHelpText ("Toggle 5D spatial (QSound)");
    }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }

    bool hitTest (int x, int y) override
    {
        return wordHitBounds().contains ((float) x, (float) y);
    }

    void mouseDown (const juce::MouseEvent&) override
    {
        if (param == nullptr || attachment == nullptr)
            return;
        attachment->setValueAsCompleteGesture (param->convertFrom0to1 (isOn() ? 0.0f : 1.0f));
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const bool on = isOn();
        const auto b = getLocalBounds().toFloat();
        const auto amber = t.amber();
        const auto dot = lampBounds (b);

        if (on)
        {
            g.setColour (amber.withAlpha (0.22f));
            g.fillEllipse (dot.expanded (5.5f));
            g.setColour (amber.withAlpha (0.50f));
            g.fillEllipse (dot.expanded (2.5f));
            g.setColour (amber.brighter (0.35f));
            g.fillEllipse (dot);
        }
        else
        {
            g.setColour (kQuietInk.withAlpha (0.88f));
            g.fillEllipse (dot);
        }

        const auto textRect = wordHitBounds().expanded (0.0f, 3.0f);
        auto font = displayFont (12.5f, false).withStyle (juce::Font::italic);
        g.setFont (font);
        if (on)
        {
            g.setColour (amber.withAlpha (0.35f));
            g.drawText ("5D", textRect.translated (0.0f, 1.0f), juce::Justification::centredLeft);
            g.setColour (juce::Colour (0xfffbeadd).withAlpha (hover ? 1.0f : 0.96f));
        }
        else
            g.setColour (kQuietInk.withAlpha (hover ? 1.0f : 0.88f));
        g.drawText ("5D", textRect, juce::Justification::centredLeft);
    }

private:
    static inline const juce::Colour kQuietInk { 0xffd9bcc4 };  // same helper ink as Modulation

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
        const float w = juce::GlyphArrangement::getStringWidth (font, "5D") + 8.0f;
        const float h = juce::jmax (16.0f, font.getHeight() + 4.0f);
        return { dot.getRight() + 4.0f, b.getCentreY() - h * 0.5f, w, h };
    }

    bool isOn() const
    {
        return param != nullptr && param->getValue() > 0.5f;
    }

    juce::AudioProcessorValueTreeState& state;
    Theme t;
    juce::RangedAudioParameter* param = nullptr;
    std::unique_ptr<juce::ParameterAttachment> attachment;
    bool hover = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (FiveDTag)
};

} // namespace trench::ui
