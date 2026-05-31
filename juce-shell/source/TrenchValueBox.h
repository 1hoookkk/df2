#pragma once

#include "TrenchStyle.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

namespace trench
{

/// Bold numeric ink painted directly over the physical faceplate.
class TrenchValueBox final : public juce::Component,
                             private juce::Timer
{
public:
    enum class Mode { Percent, Raw, IntPercent };

    explicit TrenchValueBox (juce::RangedAudioParameter& param, Mode m = Mode::Percent)
        : parameter (param), mode (m), lastValue (param.getValue())
    {
        setOpaque (false);
        startTimerHz (30);
    }

    void paint (juce::Graphics& g) override
    {
        const float v01 = parameter.getValue();
        juce::String text;
        switch (mode)
        {
            case Mode::Percent:    text = juce::String::formatted ("%5.1f%%", (double) (v01 * 100.0f)); break;
            case Mode::IntPercent: text = juce::String (juce::roundToInt (v01 * 100.0f)); break;
            case Mode::Raw:        text = juce::String::formatted ("%.2f", (double) parameter.convertFrom0to1 (v01)); break;
        }

        const auto textBounds = getLocalBounds().reduced (2, 1);
        const float fontSize = juce::jlimit (10.0f, 34.0f, (float) textBounds.getHeight() * 0.82f);
        auto font = style::wordmark (fontSize);
        const float textWidth = juce::GlyphArrangement::getStringWidth (font, text);
        if (textWidth > (float) textBounds.getWidth() && textWidth > 0.0f)
            font.setHeight (font.getHeight() * (float) textBounds.getWidth() / textWidth);
        g.setFont (font);

        g.setColour (style::chassisInk().darker (0.45f));
        g.drawText (text, textBounds, juce::Justification::centred, false);
    }

private:
    void timerCallback() override
    {
        const float v01 = parameter.getValue();
        if (! juce::approximatelyEqual (v01, lastValue))
        {
            lastValue = v01;
        }
        repaint();
    }

    juce::RangedAudioParameter& parameter;
    Mode mode;
    float lastValue = 0.0f;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchValueBox)
};

} // namespace trench
