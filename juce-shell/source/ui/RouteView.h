#pragma once

#include "Theme.h"
#include "../PluginProcessor.h"
#include "../dsp/GestureEngine.h"
#include "../dsp/MoveMatrix.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <functional>

namespace trench::ui
{

// Page 2 — MOVE / ROUTE view. The hidden machine, exposed as a compact 4x4 patch:
//   rows = PATH, ACC, FOL, DRFT   (sources)
//   cols = M, P, S, B             (MORPH, PRESS, SLAM, BITE targets)
// Tap a node to cycle off/low/mid/high. Drag a node up/down to fine-adjust. Double-tap
// resets that node to the gesture's factory value. RESTORE resets the whole gesture.
// Reads as a machine diagnostic (wired nodes on a dark bus), not a spreadsheet.
class RouteView : public juce::Component
{
public:
    RouteView (PluginProcessor& proc, const Theme& theme)
        : processor (proc), apvts (proc.apvts), t (theme)
    {
        setInterceptsMouseClicks (true, false);
    }

    std::function<void()> onClosePlay;   // editor switches back to the PLAY sub-page

    void refresh()
    {
        const int s = (int) get (ParamID::moveShape);
        if (s != shapeIdx) { shapeIdx = s; repaint(); }
    }

    void mouseDown (const juce::MouseEvent& e) override
    {
        if (playTab().contains (e.position))    { if (onClosePlay) onClosePlay(); return; }
        if (restoreTab().contains (e.position)) { processor.restoreMoveMatrix (shapeIdx); repaint(); return; }
        dragCell = cellAt (e.position);
        dragged = false;
        if (dragCell.first >= 0)
            dragStartVal = processor.moveMatrixCell (shapeIdx, dragCell.first, dragCell.second);
    }

    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (dragCell.first < 0) return;
        if (std::abs (e.getDistanceFromDragStartY()) > 3) dragged = true;
        if (! dragged) return;
        const float dv = -e.getDistanceFromDragStartY() / 120.0f;   // up = more
        processor.setMoveMatrixCell (shapeIdx, dragCell.first, dragCell.second,
                                     juce::jlimit (0.0f, 1.0f, dragStartVal + dv));
        repaint();
    }

    void mouseUp (const juce::MouseEvent&) override
    {
        if (dragCell.first >= 0 && ! dragged)   // a tap: cycle off/low/mid/high
        {
            const float cur = processor.moveMatrixCell (shapeIdx, dragCell.first, dragCell.second);
            const int next = (trench::moveWeightToStep (cur) + 1) & 3;
            processor.setMoveMatrixCell (shapeIdx, dragCell.first, dragCell.second, trench::moveWeightLevel (next));
            repaint();
        }
        dragCell = { -1, -1 };
    }

    void mouseDoubleClick (const juce::MouseEvent& e) override
    {
        const auto c = cellAt (e.position);
        if (c.first < 0) return;
        const float fv = trench::factoryMatrix (shapeIdx).get (c.first, c.second);
        processor.setMoveMatrixCell (shapeIdx, c.first, c.second, fv);   // reset node to factory
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const float rad = 9.0f;
        const auto screen = getLocalBounds().toFloat();
        juce::Path face; face.addRoundedRectangle (screen, rad);
        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (face);

        g.fillAll (t.phosphor());

        // header
        g.setColour (t.curveColour().withAlpha (0.85f));
        g.setFont (displayFont (11.0f, false));
        g.drawText ("ROUTE \xc2\xb7 " + juce::String (trench::gestureName ((trench::Gesture) shapeIdx)),
                    header().toNearestInt(), juce::Justification::centredLeft);
        drawTab (g, playTab(), juce::String (juce::CharPointer_UTF8 ("\xe2\x97\x82")) + " PLAY");
        drawTab (g, restoreTab(), "RESTORE");

        const auto grid = gridArea();
        // column headers (targets)
        g.setFont (displayFont (9.5f, false));
        g.setColour (t.curveColour().withAlpha (0.6f));
        for (int c = 0; c < trench::kNumTargets; ++c)
            g.drawText (trench::moveTargetShort (c), colHeader (grid, c).toNearestInt(), juce::Justification::centred);
        // row headers (sources)
        for (int r = 0; r < trench::kNumSources; ++r)
            g.drawText (trench::moveSourceName (r), rowHeader (grid, r).toNearestInt(), juce::Justification::centredLeft);

        // faint bus lines (the diagnostic wiring)
        g.setColour (t.curveColour().withAlpha (0.10f));
        for (int r = 0; r < trench::kNumSources; ++r)
        {
            const auto a = nodeCentre (grid, r, 0), b = nodeCentre (grid, r, trench::kNumTargets - 1);
            g.drawLine (a.x, a.y, b.x, b.y, 1.0f);
        }
        for (int c = 0; c < trench::kNumTargets; ++c)
        {
            const auto a = nodeCentre (grid, 0, c), b = nodeCentre (grid, trench::kNumSources - 1, c);
            g.drawLine (a.x, a.y, b.x, b.y, 1.0f);
        }

        // nodes
        for (int r = 0; r < trench::kNumSources; ++r)
            for (int c = 0; c < trench::kNumTargets; ++c)
            {
                const float w = processor.moveMatrixCell (shapeIdx, r, c);
                const auto ctr = nodeCentre (grid, r, c);
                const float maxR = nodeRadius (grid);
                // socket
                g.setColour (t.curveColour().withAlpha (0.16f));
                g.drawEllipse (ctr.x - maxR, ctr.y - maxR, maxR * 2.0f, maxR * 2.0f, 1.0f);
                if (w > 0.02f)
                {
                    const float rr = juce::jmax (2.0f, maxR * (0.35f + 0.65f * w));
                    g.setColour (t.curveColour().withAlpha (0.20f));
                    g.fillEllipse (ctr.x - rr - 2.0f, ctr.y - rr - 2.0f, (rr + 2.0f) * 2.0f, (rr + 2.0f) * 2.0f);
                    g.setColour (t.curveColour().withAlpha (0.55f + 0.45f * w));
                    g.fillEllipse (ctr.x - rr, ctr.y - rr, rr * 2.0f, rr * 2.0f);
                }
            }

        g.setColour (t.curveColour().withAlpha (0.22f));
        g.drawRoundedRectangle (screen.reduced (1.5f), rad - 1.0f, 1.0f);
    }

private:
    juce::Rectangle<float> header() const
    {
        return getLocalBounds().toFloat().removeFromTop (22.0f).reduced (8.0f, 3.0f).withTrimmedRight (132.0f);
    }
    juce::Rectangle<float> playTab() const
    {
        return getLocalBounds().toFloat().removeFromTop (22.0f).removeFromRight (132.0f)
                   .removeFromLeft (62.0f).reduced (3.0f, 3.0f);
    }
    juce::Rectangle<float> restoreTab() const
    {
        return getLocalBounds().toFloat().removeFromTop (22.0f).removeFromRight (66.0f).reduced (3.0f, 3.0f);
    }
    juce::Rectangle<float> gridArea() const
    {
        auto b = getLocalBounds().toFloat();
        b.removeFromTop (24.0f);
        return b.reduced (8.0f, 6.0f);
    }
    // the grid: a left label gutter + top header strip, then a 4x4 node field.
    juce::Rectangle<float> field (juce::Rectangle<float> grid) const
    {
        auto f = grid; f.removeFromLeft (40.0f); f.removeFromTop (16.0f); return f;
    }
    juce::Rectangle<float> colHeader (juce::Rectangle<float> grid, int c) const
    {
        const auto f = field (grid);
        const float cw = f.getWidth() / (float) trench::kNumTargets;
        return { f.getX() + c * cw, grid.getY(), cw, 16.0f };
    }
    juce::Rectangle<float> rowHeader (juce::Rectangle<float> grid, int r) const
    {
        const auto f = field (grid);
        const float rh = f.getHeight() / (float) trench::kNumSources;
        return { grid.getX(), f.getY() + r * rh, 38.0f, rh };
    }
    juce::Point<float> nodeCentre (juce::Rectangle<float> grid, int r, int c) const
    {
        const auto f = field (grid);
        const float cw = f.getWidth() / (float) trench::kNumTargets;
        const float rh = f.getHeight() / (float) trench::kNumSources;
        return { f.getX() + (c + 0.5f) * cw, f.getY() + (r + 0.5f) * rh };
    }
    float nodeRadius (juce::Rectangle<float> grid) const
    {
        const auto f = field (grid);
        const float cw = f.getWidth() / (float) trench::kNumTargets;
        const float rh = f.getHeight() / (float) trench::kNumSources;
        return juce::jmin (cw, rh) * 0.32f;
    }
    std::pair<int,int> cellAt (juce::Point<float> p) const
    {
        const auto grid = gridArea();
        const float maxR = nodeRadius (grid) + 6.0f;
        for (int r = 0; r < trench::kNumSources; ++r)
            for (int c = 0; c < trench::kNumTargets; ++c)
                if (nodeCentre (grid, r, c).getDistanceFrom (p) <= maxR)
                    return { r, c };
        return { -1, -1 };
    }

    void drawTab (juce::Graphics& g, juce::Rectangle<float> r, const juce::String& label)
    {
        g.setColour (t.curveColour().withAlpha (0.10f));
        g.fillRoundedRectangle (r, 3.0f);
        g.setColour (t.curveColour().withAlpha (0.65f));
        g.setFont (displayFont (9.5f, false));
        g.drawText (label, r.toNearestInt(), juce::Justification::centred);
    }

    float get (const juce::String& id) const
    {
        if (auto* v = apvts.getRawParameterValue (id)) return v->load();
        return 0.0f;
    }

    PluginProcessor& processor;
    juce::AudioProcessorValueTreeState& apvts;
    Theme t;
    int shapeIdx = 0;
    std::pair<int,int> dragCell { -1, -1 };
    bool dragged = false;
    float dragStartVal = 0.0f;
};

} // namespace trench::ui
