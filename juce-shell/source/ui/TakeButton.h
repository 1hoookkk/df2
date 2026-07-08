#pragma once

#include "Theme.h"

#include <juce_gui_basics/juce_gui_basics.h>
#include <functional>

namespace trench::ui
{

// TAKE — drag it into the DAW. Always contains the last few seconds of the
// real heard wet output (PluginProcessor::captureSmartTake), no offline
// render, no tray. Same drag-distance-threshold pattern as TakeView's
// existing per-cell drag, just for a single always-current take.
//
// A small dark recessed well (drawWell), matching SeedButton — a small
// pressable/draggable hardware button, not a floating label.
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
        const auto b = getLocalBounds().toFloat();
        drawWell (g, b, t);

        g.setFont (displayFont (10.0f, false));
        g.setColour (juce::Colour (0xffe9dfc6).withAlpha (down ? 0.75f : (hover ? 1.0f : 0.9f)));
        g.drawText ("TAKE", b, juce::Justification::centred, false);
    }

    // Fired once per drag gesture, past the distance threshold. `this` is
    // passed as the drag source for performExternalDragDropOfFiles.
    std::function<void (juce::Component*)> onDragTake;

private:
    Theme t;
    bool hover = false;
    bool down = false;
    bool armedForDrag = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TakeButton)
};

} // namespace trench::ui
