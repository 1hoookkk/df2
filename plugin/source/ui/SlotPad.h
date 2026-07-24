#pragma once
#include "Theme.h"
#include <juce_gui_basics/juce_gui_basics.h>
#include <array>
#include <functional>
namespace trench::ui
{
class SlotPad : public juce::Component
{
public:
    explicit SlotPad (const Theme& theme) : t (theme)
    {
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Slot");
        setHelpText ("Slot 1 / 2 - click to select");
    }
    std::function<void (int)> onSelect;
    void setActive (int idx)
    {
        idx = juce::jlimit (0, 1, idx);
        if (idx != active) { active = idx; repaint(); }
    }
    int getActive() const noexcept { return active; }
    void resized() override
    {
        const auto full = getLocalBounds().toFloat();
        padArea = full.reduced (0.5f);
        numFont = juce::jmax (7.4f, padArea.getHeight() * 0.58f);
        auto r = padArea;
        cell[0] = r.removeFromLeft (r.getWidth() * 0.5f);
        cell[1] = r;
    }
    void paint (juce::Graphics& g) override
    {
        for (int i = 0; i < 2; ++i)
            drawCell (g, cell[(size_t) i].reduced (0.4f), juce::String (i + 1),
                      i == active, i == hover);
    }
    void mouseMove (const juce::MouseEvent& e) override { setHover (cellAt (e.position)); }
    void mouseExit (const juce::MouseEvent&) override   { setHover (-1); }
    void mouseDown (const juce::MouseEvent& e) override
    {
        const int c = cellAt (e.position);
        if (c >= 0)
        {
            setActive (c);
            if (onSelect != nullptr)
                onSelect (c);
        }
    }
private:
    void drawCell (juce::Graphics& g, juce::Rectangle<float> r, const juce::String& num,
                   bool pressed, bool hovered) const
    {
        const auto ink = t.curveColour().darker (0.62f);
        const auto glass = t.phosphor().darker (pressed ? 0.24f : 0.16f);
        g.setColour (glass.withAlpha (pressed ? 0.54f : hovered ? 0.42f : 0.32f));
        g.fillRoundedRectangle (r, corner);
        g.setColour (ink.withAlpha (pressed ? 0.62f : 0.34f));
        g.drawRoundedRectangle (r, corner, 1.0f);
        auto txt = r.toNearestInt();
        g.setColour (ink.withAlpha (pressed ? 0.88f : 0.48f));
        g.setFont (displayFont (numFont, true));
        g.drawFittedText (num, txt, juce::Justification::centred, 1);
    }
    int cellAt (juce::Point<float> p) const
    {
        for (int i = 0; i < 2; ++i)
            if (cell[(size_t) i].contains (p)) return i;
        return -1;
    }
    void setHover (int h) { if (h != hover) { hover = h; repaint(); } }
    Theme t;
    juce::Rectangle<float> padArea;
    std::array<juce::Rectangle<float>, 2> cell {};
    float numFont = 10.0f;
    int active = 0;
    int hover  = -1;
    static constexpr float corner = 1.2f;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SlotPad)
};
}
