#pragma once
#include "Theme.h"
#include <juce_gui_basics/juce_gui_basics.h>
#include <functional>
namespace trench::ui
{
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
        drawHardwareKey (g, b, "SEED", hover, down, t);
        if (flashAlpha > 0.01f)
        {
            g.setColour (juce::Colour (0xffefa63c).withAlpha (flashAlpha * 0.55f));
            g.drawRoundedRectangle (b.reduced (1.5f), juce::jmax (3.0f, t.wellRadius() - 3.0f), 1.4f);
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
}
