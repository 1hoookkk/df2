#pragma once
#include "Theme.h"
#include <juce_gui_basics/juce_gui_basics.h>
#include <functional>
namespace trench::ui
{
class TakeButton : public juce::Component
{
public:
    explicit TakeButton (const Theme& theme) : t (theme)
    {
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Take");
        setHelpText ("Drag to capture what you just heard into your DAW");
    }
    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }
    void mouseDown (const juce::MouseEvent&) override
    {
        down = true;
        armedForDrag = false;
        repaint();
    }
    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (armedForDrag) return;
        if (e.getDistanceFromDragStart() < 10) return;
        armedForDrag = true;
        down = false;
        repaint();
        if (onDragTake)
            onDragTake (this);
    }
    void mouseUp (const juce::MouseEvent&) override
    {
        down = false;
        armedForDrag = false;
        repaint();
    }
    void paint (juce::Graphics& g) override
    {
        drawHardwareKey (g, getLocalBounds().toFloat(), "TAKE", hover, down, t);
    }
    std::function<void (juce::Component*)> onDragTake;
private:
    Theme t;
    bool hover = false;
    bool down = false;
    bool armedForDrag = false;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TakeButton)
};
}
