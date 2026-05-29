#pragma once

#include "TrenchStyle.h"
#include "TrenchBodyRoster.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

namespace trench
{
// Live TYPE strip on the chassis bar above the screen. Cartridge name rides in
// bone (chassis-tier neutral); chevrons in dim bone. On cycle the name flashes
// phosphor green for ~220 ms — that's the chassis-tier 10% accent indicating
// active state, then settles back.
class TrenchBodyStrip final : public juce::Component,
                              private juce::Timer
{
public:
    explicit TrenchBodyStrip (juce::RangedAudioParameter& p)
        : parameter (p),
          attachment (p, [this] (float) { refresh(); })
    {
        setOpaque (false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        attachment.sendInitialUpdate();
        startTimerHz (30);
    }

    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds();

        const auto textArea = b.reduced (juce::jmax (22, b.getHeight()), 0);
        const float fontSize = juce::jmax (10.0f, (float) b.getHeight() * 0.45f);

        const float now = (float) juce::Time::getMillisecondCounterHiRes() * 0.001f;
        const float fadeFor = 0.22f;
        const float t = juce::jlimit (0.0f, 1.0f, (lastFlashTime + fadeFor - now) / fadeFor);
        const auto nameCol = style::primary().interpolatedWith (style::accent(), t);

        const auto name = trench::bodyDisplayName (index);
        g.setColour (juce::Colours::black.withAlpha (0.45f));
        g.setFont (style::label (fontSize, true));
        g.drawFittedText (name, textArea.translated (0, 1).expanded (0, 1),
                          juce::Justification::centred, 1, 0.9f);
        g.setColour (nameCol);
        g.drawFittedText (name, textArea, juce::Justification::centred, 1, 0.9f);

        // Chevrons either side — dim bone.
        const int cy = b.getCentreY();
        const int inset = juce::jmax (10, b.getHeight() / 2);
        drawArrow (g, b.getX() + inset, cy, -1);
        drawArrow (g, b.getRight() - inset, cy, +1);
    }

    void mouseDown (const juce::MouseEvent& e) override
    {
        const int dir = e.mods.isRightButtonDown() ? -1 : 1;
        if (e.position.x < (float) getWidth() / 3.0f)
            setIndex (index - 1);
        else
            setIndex (index + dir);
    }

    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w) override
    {
        if (w.deltaY > 0.0f) setIndex (index - 1);
        else if (w.deltaY < 0.0f) setIndex (index + 1);
    }

private:
    juce::RangedAudioParameter& parameter;
    juce::ParameterAttachment attachment;
    int index = 0;
    float lastFlashTime = -10.0f;

    void timerCallback() override
    {
        const float now = (float) juce::Time::getMillisecondCounterHiRes() * 0.001f;
        if (now < lastFlashTime + 0.30f)
            repaint();
    }

    static int wrapIndex (int i)
    {
        return trench::wrapBodyIndex (i);
    }

    static void drawArrow (juce::Graphics& g, int x, int y, int dir)
    {
        const float w = 3.5f, h = 5.0f;
        const float tip = (float) x - dir * w * 0.5f;
        const float back = (float) x + dir * w * 0.5f;
        juce::Path p;
        p.startNewSubPath (back, (float) y - h);
        p.lineTo (tip, (float) y);
        p.lineTo (back, (float) y + h);
        g.setColour (style::primaryDim().withAlpha (0.55f));
        g.strokePath (p, juce::PathStrokeType (1.4f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded));
    }

    void setIndex (int next)
    {
        next = wrapIndex (next);
        // `setValueAsCompleteGesture` expects the DENORMALIZED parameter value
        // (0..bodyCount-1), not a normalised 0..1. Passing 0..1 here caused
        // JUCE to renormalise again and collapsed every click to index 0 or 1
        // — the "only two presets reachable" bug. Every other control in the
        // codebase (shuttle, thumbwheel) passes denormalised already.
        attachment.setValueAsCompleteGesture ((float) next);
    }

    void refresh()
    {
        const auto denorm = parameter.convertFrom0to1 (parameter.getValue());
        const int newIndex = wrapIndex (juce::roundToInt (denorm));
        if (newIndex != index)
        {
            index = newIndex;
            lastFlashTime = (float) juce::Time::getMillisecondCounterHiRes() * 0.001f;
        }
        repaint();
    }

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchBodyStrip)
};
}
