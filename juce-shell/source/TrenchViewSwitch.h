#pragma once

#include "TrenchStyle.h"

#include <juce_gui_basics/juce_gui_basics.h>

#include <functional>

namespace trench
{
// Tiny two-cell MAIN | FX tab that rides in the top-right corner of the screen.
// Flips the central window between the response scope and the FX pane. Active
// cell lit phosphor-green (the 10% accent), inactive dim bone.
class TrenchViewSwitch final : public juce::Component
{
public:
    std::function<void (bool /*showFx*/)> onToggle;

    explicit TrenchViewSwitch (bool startShowFx = false) : showFx (startShowFx)
    {
        setOpaque (false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
    }

    bool isShowingFx() const noexcept { return showFx; }

    void setShowFx (bool v)
    {
        if (v == showFx) return;
        showFx = v;
        repaint();
        if (onToggle) onToggle (showFx);
    }

    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds();
        const auto mainCell = b.withWidth (b.getWidth() / 2);
        const auto fxCell   = b.withTrimmedLeft (b.getWidth() / 2);
        drawCell (g, mainCell, "MAIN", ! showFx);
        drawCell (g, fxCell,   "FX",     showFx);
    }

    void mouseDown (const juce::MouseEvent& e) override
    {
        setShowFx (e.position.x >= (float) getWidth() * 0.5f);
    }

private:
    void drawCell (juce::Graphics& g, juce::Rectangle<int> cell, const juce::String& label, bool active)
    {
        g.setColour (juce::Colours::black.withAlpha (active ? 0.55f : 0.35f));
        g.fillRect (cell);
        g.setColour ((active ? style::accent() : style::primaryDim()).withAlpha (0.7f));
        g.drawRect (cell, 1);
        g.setColour (active ? style::accent() : style::primaryDim());
        g.setFont (style::label (juce::jlimit (8.0f, 12.0f, (float) cell.getHeight() * 0.55f), true));
        g.drawText (label, cell, juce::Justification::centred, false);
    }

    bool showFx = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchViewSwitch)
};
} // namespace trench
