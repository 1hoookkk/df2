#pragma once

#include "Theme.h"

#include <juce_gui_basics/juce_gui_basics.h>
#include <functional>

namespace trench::ui
{

// SEED — one tap, one related sibling. No parameters shown: the perturbation
// strength/certification all happens in PluginProcessor::seedCurrentBody ->
// trench-core's seed_legal (shared cross-corner theme + jitter, gated by
// certify_pass). This button is the verb, not a knob.
//
// A small dark recessed well (drawWell — the same material the MORPH/Q
// value readouts use) with cream text, not a full-width cream bar: it has
// to read as a small hardware button, not compete with the readouts.
class SeedButton : public juce::Component,
                   private juce::Timer
{
public:
    std::function<void()> onSeed;

    SeedButton (const Theme& theme) : t (theme)
    {
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Seed");
        setHelpText ("Make another related version of this sound");
    }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }

    void mouseDown (const juce::MouseEvent&) override { down = true; repaint(); }

    void mouseUp (const juce::MouseEvent& e) override
    {
        down = false;
        if (getLocalBounds().toFloat().contains (e.position) && onSeed)
        {
            onSeed();
            flashAlpha = 1.0f;
            startTimerHz (30);
        }
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds().toFloat();
        drawWell (g, b, t);

        g.setFont (displayFont (10.0f, false));
        g.setColour (juce::Colour (0xffe9dfc6).withAlpha (down ? 0.75f : (hover ? 1.0f : 0.9f)));
        g.drawText ("SEED", b, juce::Justification::centred, false);

        if (flashAlpha > 0.01f)
        {
            g.setColour (juce::Colour (0xffefa63c).withAlpha (flashAlpha * 0.6f));
            g.drawRoundedRectangle (b.reduced (0.5f), juce::jmax (3.0f, t.wellRadius() - 4.0f), 1.4f);
        }
    }

private:
    void timerCallback() override
    {
        flashAlpha = juce::jmax (0.0f, flashAlpha - 0.08f);
        repaint();
        if (flashAlpha <= 0.0f)
            stopTimer();
    }

    Theme t;
    bool hover = false;
    bool down = false;
    float flashAlpha = 0.0f;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SeedButton)
};

} // namespace trench::ui
