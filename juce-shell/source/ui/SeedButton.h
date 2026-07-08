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
class SeedButton : public juce::Component,
                   private juce::Timer
{
public:
    std::function<void()> onSeed;

    SeedButton()
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
        const auto ink = juce::Colour (0xffe9dfc6);
        const float base = down ? 0.7f : (hover ? 0.95f : 0.8f);
        g.setFont (displayFont (11.5f, false));
        g.setColour (ink.withAlpha (juce::jmax (base, flashAlpha)));
        g.drawText ("SEED", b, juce::Justification::centred, false);
        if (flashAlpha > 0.01f)
        {
            g.setColour (juce::Colour (0xffefa63c).withAlpha (flashAlpha * 0.5f));
            g.drawRect (b.reduced (1.0f), 1.0f);
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

    bool hover = false;
    bool down = false;
    float flashAlpha = 0.0f;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SeedButton)
};

} // namespace trench::ui
