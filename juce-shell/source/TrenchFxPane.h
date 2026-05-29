#pragma once

#include "TrenchStyle.h"
#include "PluginProcessor.h"
#include "parameters/TrenchParameters.h"

#include <juce_gui_basics/juce_gui_basics.h>

#include <array>
#include <cmath>

namespace trench
{
// The FX face of the central screen. It keeps the screen/OLED language, but
// groups the powerful controls by signal role instead of exposing them as a
// flat list of parameter IDs.
class TrenchFxPane final : public juce::Component,
                           private juce::Timer
{
public:
    explicit TrenchFxPane (PluginProcessor& proc)
        : processor (proc), apvts (proc.apvts)
    {
        setOpaque (false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        startTimerHz (20);
    }

    ~TrenchFxPane() override { stopTimer(); }

    void paint (juce::Graphics& g) override
    {
        const auto bounds = getLocalBounds().toFloat();
        const float corner = juce::jmin (10.0f, bounds.getHeight() * 0.045f);

        g.setColour (style::oledBg());
        g.fillRoundedRectangle (bounds, corner);

        juce::Path screenPath;
        screenPath.addRoundedRectangle (bounds, corner);
        juce::Graphics::ScopedSaveState clip (g);
        g.reduceClipRegion (screenPath);

        drawHeader (g);
        drawRouteSection (g, routeSection());
        drawTeleportSection (g, teleportSection());
        drawStatus (g);
    }

    void mouseDown (const juce::MouseEvent& e) override
    {
        const auto p = e.getPosition();

        if (setChoiceFromPoint (ParamID::inputMode, inputModeBounds(), p)) return;
        if (setChoiceFromPoint (ParamID::fiveD, fiveDBounds(), p)) return;
        if (setChoiceFromPoint (ParamID::teleportMode, teleportModeBounds(), p)) return;

        if (slamBarBounds().contains (p))       { dragging = ParamID::slamDrive; beginDrag (e); return; }
        if (outputBarBounds().contains (p))     { dragging = ParamID::output; beginDrag (e); return; }
        if (amountBarBounds().contains (p))     { dragging = ParamID::teleportAmount; beginDrag (e); return; }
        if (rateBarBounds().contains (p))       { dragging = ParamID::teleportRate; beginDrag (e); return; }
        if (morphDepthBounds().contains (p))    { dragging = ParamID::teleportMorphDepth; beginDrag (e); return; }
        if (qDepthBounds().contains (p))        { dragging = ParamID::teleportQDepth; beginDrag (e); return; }
    }

    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (dragging == nullptr) return;

        juce::Rectangle<int> bar;
        if      (dragging == ParamID::slamDrive)          bar = slamBarBounds();
        else if (dragging == ParamID::output)             bar = outputBarBounds();
        else if (dragging == ParamID::teleportAmount)     bar = amountBarBounds();
        else if (dragging == ParamID::teleportRate)       bar = rateBarBounds();
        else if (dragging == ParamID::teleportMorphDepth) bar = morphDepthBounds();
        else if (dragging == ParamID::teleportQDepth)     bar = qDepthBounds();

        const float v01 = juce::jlimit (0.0f, 1.0f,
            (float) (e.position.x - (float) bar.getX()) / (float) juce::jmax (1, bar.getWidth()));
        if (auto* param = apvts.getParameter (dragging))
            param->setValueNotifyingHost (v01);

        repaint();
    }

    void mouseUp (const juce::MouseEvent&) override
    {
        if (dragging != nullptr)
        {
            if (auto* param = apvts.getParameter (dragging))
                param->endChangeGesture();
            dragging = nullptr;
        }
    }

private:
    void timerCallback() override { repaint(); }

    juce::Rectangle<int> contentBounds() const
    {
        return getLocalBounds().reduced (10, 8);
    }

    juce::Rectangle<int> headerBounds() const
    {
        auto b = contentBounds();
        return b.removeFromTop (juce::jmax (19, getHeight() * 9 / 100));
    }

    juce::Rectangle<int> statusBounds() const
    {
        auto b = contentBounds();
        return b.removeFromBottom (juce::jmax (14, getHeight() * 8 / 100));
    }

    juce::Rectangle<int> bodyBounds() const
    {
        auto b = contentBounds();
        b.removeFromTop (headerBounds().getHeight() + 5);
        b.removeFromBottom (statusBounds().getHeight() + 4);
        return b;
    }

    juce::Rectangle<int> routeSection() const
    {
        auto b = bodyBounds();
        return b.removeFromTop (juce::roundToInt ((float) b.getHeight() * 0.44f));
    }

    juce::Rectangle<int> teleportSection() const
    {
        auto b = bodyBounds();
        b.removeFromTop (routeSection().getHeight() + 5);
        return b;
    }

    juce::Rectangle<int> leftHalf (juce::Rectangle<int> r) const
    {
        r.reduce (7, 15);
        return r.removeFromLeft ((r.getWidth() - 8) / 2);
    }

    juce::Rectangle<int> rightHalf (juce::Rectangle<int> r) const
    {
        r.reduce (7, 15);
        r.removeFromLeft ((r.getWidth() - 8) / 2 + 8);
        return r;
    }

    juce::Rectangle<int> controlTop (juce::Rectangle<int> r) const
    {
        return r.removeFromTop (juce::jmax (18, r.getHeight() / 2 - 1));
    }

    juce::Rectangle<int> controlBottom (juce::Rectangle<int> r) const
    {
        r.removeFromTop (juce::jmax (18, r.getHeight() / 2 + 3));
        return r;
    }

    juce::Rectangle<int> inputModeBounds() const { return valueStrip (controlTop (leftHalf (routeSection()))); }
    juce::Rectangle<int> slamBarBounds()   const { return valueStrip (controlBottom (leftHalf (routeSection()))); }
    juce::Rectangle<int> fiveDBounds()     const { return valueStrip (controlTop (rightHalf (routeSection()))); }
    juce::Rectangle<int> outputBarBounds() const { return valueStrip (controlBottom (rightHalf (routeSection()))); }

    juce::Rectangle<int> teleportModeBounds() const
    {
        auto t = teleportSection().reduced (7, 15);
        return valueStrip (t.removeFromTop (juce::jmax (20, t.getHeight() / 3)));
    }

    juce::Rectangle<int> amountBarBounds() const
    {
        auto grid = teleportGrid();
        return valueStrip (grid[0]);
    }

    juce::Rectangle<int> rateBarBounds() const
    {
        auto grid = teleportGrid();
        return valueStrip (grid[1]);
    }

    juce::Rectangle<int> morphDepthBounds() const
    {
        auto grid = teleportGrid();
        return valueStrip (grid[2]);
    }

    juce::Rectangle<int> qDepthBounds() const
    {
        auto grid = teleportGrid();
        return valueStrip (grid[3]);
    }

    std::array<juce::Rectangle<int>, 4> teleportGrid() const
    {
        auto t = teleportSection().reduced (7, 15);
        t.removeFromTop (juce::jmax (20, t.getHeight() / 3) + 5);

        const int gap = 8;
        const int colW = (t.getWidth() - gap) / 2;
        const int rowH = (t.getHeight() - 4) / 2;
        const int x0 = t.getX();
        const int x1 = x0 + colW + gap;
        const int y0 = t.getY();
        const int y1 = y0 + rowH + 4;

        return {{
            { x0, y0, colW, rowH },
            { x1, y0, colW, rowH },
            { x0, y1, colW, rowH },
            { x1, y1, colW, rowH },
        }};
    }

    juce::Rectangle<int> valueStrip (juce::Rectangle<int> r) const
    {
        r.removeFromTop (juce::jmax (9, r.getHeight() / 3));
        return r.reduced (0, 1);
    }

    void drawHeader (juce::Graphics& g) const
    {
        auto h = headerBounds();
        const auto clearForTabs = juce::jmax (96, h.getWidth() * 32 / 100);
        auto title = h.withTrimmedRight (clearForTabs);

        g.setColour (style::oledAmber());
        g.setFont (style::label (juce::jlimit (12.0f, 18.0f, (float) h.getHeight() * 0.82f), true));
        g.drawText ("FX", title, juce::Justification::centredLeft, false);

        g.setColour (style::oledCyan().withAlpha (0.35f));
        g.drawHorizontalLine (h.getBottom() - 1, (float) h.getX(), (float) title.getRight());
    }

    void drawStatus (juce::Graphics& g) const
    {
        auto status = statusBounds();
        const bool ok = processor.getLastLoadOk();
        const auto body = trench::bodyDisplayName (processor.getLoadedBodyIndex());

        g.setColour (ok ? style::oledCyan().withAlpha (0.92f) : style::oledRed());
        g.setFont (style::label (juce::jlimit (8.0f, 12.0f, (float) status.getHeight() * 0.70f), true));
        g.drawText (juce::String ("BODY  ") + body + (ok ? juce::String() : juce::String ("  LOAD FAIL")),
                    status, juce::Justification::centredLeft, false);
    }

    void drawRouteSection (juce::Graphics& g, juce::Rectangle<int> section) const
    {
        drawSectionShell (g, section, "SIGNAL", style::oledAmber());

        const auto left = leftHalf (section);
        const auto right = rightHalf (section);
        const bool slamActive = choiceIndex (ParamID::inputMode) == 1;

        drawSegmentControl (g, controlTop (left), "COLOR", ParamID::inputMode, style::oledAmber(), true);
        drawBarControl (g, controlBottom (left), "SLAM", ParamID::slamDrive, style::oledRed(), false, slamActive);

        drawSegmentControl (g, controlTop (right), "5D SPACE", ParamID::fiveD, style::oledGreen(), true);
        drawBarControl (g, controlBottom (right), "OUTPUT", ParamID::output, style::oledMagenta(), true, true);
    }

    void drawTeleportSection (juce::Graphics& g, juce::Rectangle<int> section) const
    {
        const bool on = teleportModeIndex() > 0;
        const bool rateActive = isTeleportRateActive();

        drawSectionShell (g, section, "MOTION", on ? style::oledCyan() : style::oledWhite().withAlpha (0.42f));

        auto inner = section.reduced (7, 15);
        drawSegmentControl (g, inner.removeFromTop (juce::jmax (20, inner.getHeight() / 3)),
                            "MODE", ParamID::teleportMode, style::oledCyan(), true);

        const auto grid = teleportGrid();
        drawBarControl (g, grid[0], "AMOUNT", ParamID::teleportAmount, style::oledCyan(), false, on);
        drawBarControl (g, grid[1], "RATE", ParamID::teleportRate, style::oledCyan(), false, rateActive);
        drawBarControl (g, grid[2], "MORPH", ParamID::teleportMorphDepth, style::oledBlue().brighter (0.35f), false, on);
        drawBarControl (g, grid[3], "Q AXIS", ParamID::teleportQDepth, style::oledBlue().brighter (0.35f), false, on);
    }

    void drawSectionShell (juce::Graphics& g, juce::Rectangle<int> section,
                           const juce::String& title, juce::Colour accent) const
    {
        const auto r = section.toFloat();
        g.setColour (juce::Colours::black.withAlpha (0.26f));
        g.fillRoundedRectangle (r, 4.0f);
        g.setColour (accent.withAlpha (0.38f));
        g.drawRoundedRectangle (r.reduced (0.5f), 4.0f, 1.0f);

        auto label = section.withHeight (14).reduced (6, 0);
        g.setColour (accent.withAlpha (0.9f));
        g.setFont (style::label (9.0f, true));
        g.drawText (title, label, juce::Justification::centredLeft, false);
    }

    void drawControlTitle (juce::Graphics& g, juce::Rectangle<int> area,
                           const juce::String& title, bool active) const
    {
        auto label = area.withHeight (juce::jmax (9, area.getHeight() / 3));
        g.setColour (style::oledWhite().withAlpha (active ? 0.74f : 0.34f));
        g.setFont (style::label (juce::jlimit (7.0f, 10.0f, (float) label.getHeight() * 0.78f), true));
        g.drawText (title, label, juce::Justification::centredLeft, false);
    }

    void drawSegmentControl (juce::Graphics& g, juce::Rectangle<int> area, const juce::String& title,
                             const char* id, juce::Colour accent, bool active) const
    {
        drawControlTitle (g, area, title, active);

        const auto strip = valueStrip (area);
        g.setColour (juce::Colours::black.withAlpha (0.48f));
        g.fillRect (strip);
        g.setColour (style::oledWhite().withAlpha (active ? 0.34f : 0.16f));
        g.drawRect (strip, 1);

        auto* p = apvts.getParameter (id);
        const int steps = p != nullptr ? juce::jmax (1, p->getNumSteps()) : 1;
        const int selected = choiceIndex (id);
        const int segW = juce::jmax (1, strip.getWidth() / steps);

        for (int i = 0; i < steps; ++i)
        {
            auto seg = strip.withX (strip.getX() + i * segW).withWidth (i == steps - 1 ? strip.getRight() - (strip.getX() + i * segW) : segW);
            const bool sel = i == selected;
            const auto text = p != nullptr ? p->getText ((float) i / (float) juce::jmax (1, steps - 1), 16) : juce::String();

            if (sel)
            {
                g.setColour (accent.withAlpha (active ? 0.26f : 0.14f));
                g.fillRect (seg.reduced (1));
            }

            if (i > 0)
            {
                g.setColour (style::oledWhite().withAlpha (0.18f));
                g.drawVerticalLine (seg.getX(), (float) strip.getY(), (float) strip.getBottom());
            }

            g.setColour (sel ? accent.withAlpha (active ? 0.96f : 0.46f)
                             : style::oledWhite().withAlpha (active ? 0.52f : 0.24f));
            g.setFont (style::label (juce::jlimit (6.5f, 9.0f, (float) strip.getHeight() * 0.58f), true));
            g.drawText (text, seg.reduced (2, 0), juce::Justification::centred, false);
        }
    }

    void drawBarControl (juce::Graphics& g, juce::Rectangle<int> area, const juce::String& title,
                         const char* id, juce::Colour accent, bool bipolar, bool active) const
    {
        drawControlTitle (g, area, title, active);

        const auto bar = valueStrip (area);
        g.setColour (juce::Colours::black.withAlpha (0.48f));
        g.fillRect (bar);
        g.setColour (style::oledWhite().withAlpha (active ? 0.34f : 0.16f));
        g.drawRect (bar, 1);

        float v01 = 0.0f;
        juce::String text;
        if (auto* p = apvts.getParameter (id))
        {
            v01 = p->getValue();
            text = p->getCurrentValueAsText();
        }

        if (bipolar)
        {
            const int mid = bar.getCentreX();
            const int x = bar.getX() + juce::roundToInt (v01 * (float) bar.getWidth());
            const auto fill = juce::Rectangle<int>::leftTopRightBottom (juce::jmin (mid, x), bar.getY() + 2,
                                                                        juce::jmax (mid, x), bar.getBottom() - 2);
            g.setColour (accent.withAlpha (active ? 0.78f : 0.25f));
            g.fillRect (fill);
            g.setColour (style::oledWhite().withAlpha (0.44f));
            g.drawVerticalLine (mid, (float) bar.getY(), (float) bar.getBottom());
        }
        else
        {
            const int w = juce::roundToInt (v01 * (float) bar.getWidth());
            g.setColour (accent.withAlpha (active ? 0.76f : 0.22f));
            g.fillRect (juce::Rectangle<int> (bar.getX(), bar.getY() + 2, w, bar.getHeight() - 4));
        }

        g.setColour (style::oledWhite().withAlpha (active ? 0.95f : 0.34f));
        g.setFont (style::label (juce::jlimit (6.5f, 9.0f, (float) bar.getHeight() * 0.58f), true));
        g.drawText (text, bar.reduced (4, 0), juce::Justification::centredRight, false);
    }

    int choiceIndex (const char* id) const
    {
        if (auto* p = apvts.getParameter (id))
            return juce::roundToInt (p->getValue() * (float) juce::jmax (1, p->getNumSteps() - 1));
        return 0;
    }

    bool setChoiceFromPoint (const char* id, juce::Rectangle<int> strip, juce::Point<int> p)
    {
        if (! strip.contains (p)) return false;
        auto* param = apvts.getParameter (id);
        if (param == nullptr) return true;

        const int steps = juce::jmax (1, param->getNumSteps());
        const float rel = (float) (p.x - strip.getX()) / (float) juce::jmax (1, strip.getWidth());
        const int idx = juce::jlimit (0, steps - 1, (int) std::floor (rel * (float) steps));

        param->beginChangeGesture();
        param->setValueNotifyingHost ((float) idx / (float) juce::jmax (1, steps - 1));
        param->endChangeGesture();
        repaint();
        return true;
    }

    int teleportModeIndex() const
    {
        return choiceIndex (ParamID::teleportMode);
    }

    bool isTeleportRateActive() const
    {
        const int idx = teleportModeIndex();
        return idx == 1 || idx == 2;
    }

    void beginDrag (const juce::MouseEvent& e)
    {
        if (auto* param = apvts.getParameter (dragging))
            param->beginChangeGesture();
        mouseDrag (e);
    }

    PluginProcessor& processor;
    juce::AudioProcessorValueTreeState& apvts;
    const char* dragging = nullptr;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchFxPane)
};
} // namespace trench
