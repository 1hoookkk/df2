#pragma once

#include "TrenchStyle.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

namespace trench
{

/// Recessed LCD-style readout. Digits sit in **bone-white** at rest; on every
/// parameter change they flash to **phosphor green** and fade back over ~180ms
/// — the active-state cue from the chassis-tier 60:30:10 palette.
class TrenchValueBox final : public juce::Component,
                             private juce::Timer
{
public:
    enum class Mode { Percent, Raw };

    explicit TrenchValueBox (juce::RangedAudioParameter& param, Mode m = Mode::Percent)
        : parameter (param), mode (m), lastValue (param.getValue())
    {
        setOpaque (false);
        startTimerHz (30);
    }

    void paint (juce::Graphics& g) override
    {
        const float v01 = parameter.getValue();
        const juce::String text = mode == Mode::Percent
            ? juce::String::formatted ("%5.1f%%", (double) (v01 * 100.0f))
            : juce::String::formatted ("%.2f", (double) parameter.convertFrom0to1 (v01));

        const auto lcd = getLocalBounds().reduced (4, 3);
        const auto lcdF = lcd.toFloat();

        g.setColour (juce::Colour (0xff010503).withAlpha (0.78f));
        g.fillRoundedRectangle (lcdF, 2.0f);
        g.setColour (style::primary().withAlpha (0.06f));
        g.drawHorizontalLine (lcd.getY() + 1, (float) lcd.getX() + 2.0f, (float) lcd.getRight() - 2.0f);
        g.setColour (juce::Colours::black.withAlpha (0.55f));
        g.drawHorizontalLine (lcd.getBottom() - 2, (float) lcd.getX() + 2.0f, (float) lcd.getRight() - 2.0f);

        // Subtle scanline texture in the well.
        for (int y = lcd.getY() + 4; y < lcd.getBottom() - 3; y += 3)
        {
            g.setColour (style::primary().withAlpha (0.025f));
            g.drawHorizontalLine (y, (float) lcd.getX() + 3.0f, (float) lcd.getRight() - 3.0f);
        }

        const auto textBounds = lcd.reduced (4, 1);
        const float fontSize = juce::jlimit (8.0f, 28.0f, (float) textBounds.getHeight() * 0.58f);
        auto font = style::readout (fontSize, true);
        const float textWidth = juce::GlyphArrangement::getStringWidth (font, text);
        if (textWidth > (float) textBounds.getWidth() && textWidth > 0.0f)
            font.setHeight (font.getHeight() * (float) textBounds.getWidth() / textWidth);
        g.setFont (font);

        // Resting colour: bone. While the parameter is moving, blend toward
        // phosphor green and fade back.
        const float now = (float) juce::Time::getMillisecondCounterHiRes() * 0.001f;
        const float fadeFor = 0.18f; // seconds
        const float t = juce::jlimit (0.0f, 1.0f, (lastChangeTime + fadeFor - now) / fadeFor);
        const auto col = style::primary().interpolatedWith (style::accent(), t);

        g.setColour (juce::Colours::black.withAlpha (0.45f));
        g.drawText (text, textBounds.translated (1, 1), juce::Justification::centred, false);
        g.setColour (col);
        g.drawText (text, textBounds, juce::Justification::centred, false);
    }

private:
    void timerCallback() override
    {
        const float v01 = parameter.getValue();
        if (! juce::approximatelyEqual (v01, lastValue))
        {
            lastValue = v01;
            lastChangeTime = (float) juce::Time::getMillisecondCounterHiRes() * 0.001f;
        }
        repaint();
    }

    juce::RangedAudioParameter& parameter;
    Mode mode;
    float lastValue = 0.0f;
    float lastChangeTime = -10.0f;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchValueBox)
};

} // namespace trench
