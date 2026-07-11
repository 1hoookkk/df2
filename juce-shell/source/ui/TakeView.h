#pragma once

#include "Theme.h"
#include "../PluginProcessor.h"

#include <juce_gui_basics/juce_gui_basics.h>
#include <functional>
#include <vector>

namespace trench::ui
{

// Page 2 — the VERSIONS tray, drawn as the second page of the same display.
// No capture bar, no toolbar: just a full LCD page with crude version cells.
//
//   press a slot  -> audition it live (installs the body + adopts its Morph/Q; persists)
//   release       -> back to the Player
//   drag a slot    -> keep it (renders the take WAV into the DAW)
//   press 2 again  -> reroll · press 1 -> Player
class TakeView : public juce::Component
{
public:
    explicit TakeView (const Theme& theme) : t (theme)
    {
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Versions");
        setHelpText ("12 takes of your sound - click to listen, drag to keep, press 2 to reroll");
    }

    std::function<void (int)> onAudition;
    std::function<void (int)> onConfirm;
    std::function<void (int, juce::Component* source)> onKeep;

    void setSlots (std::vector<PluginProcessor::VariantPreview> v)
    {
        slots = std::move (v);
        if (selected >= (int) slots.size())
            selected = slots.empty() ? -1 : 0;
        rebuildCells();
        repaint();
    }

    void setSelected (int i) { if (i != selected) { selected = i; repaint(); } }

    void resized() override { rebuildCells(); }

    void mouseMove (const juce::MouseEvent& e) override { setHover (cellAt (e.position)); }
    void mouseExit (const juce::MouseEvent&) override   { setHover (-1); }

    void mouseDown (const juce::MouseEvent& e) override
    {
        pressedCell = cellAt (e.position);
        armedForDrag = false;
        if (pressedCell >= 0)
        {
            setSelected (pressedCell);
            if (onAudition != nullptr)
                onAudition (pressedCell);
        }
    }

    void mouseUp (const juce::MouseEvent& e) override
    {
        if (! armedForDrag && pressedCell >= 0 && cellAt (e.position) == pressedCell)
            if (onConfirm != nullptr)
                onConfirm (pressedCell);
        pressedCell = -1;
        armedForDrag = false;
    }

    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (armedForDrag || pressedCell < 0)
            return;
        if (e.getDistanceFromDragStart() < 14)
            return;
        armedForDrag = true;
        if (onKeep != nullptr)
            onKeep (pressedCell, this);
    }

    void paint (juce::Graphics& g) override
    {
        const auto full = getLocalBounds();
        const float rad = 9.0f;

        juce::Path face;
        face.addRoundedRectangle (full.toFloat(), rad);
        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (face);

        paintPanel (g);

        g.setColour (juce::Colours::black.withAlpha (0.6f));
        g.drawRoundedRectangle (full.toFloat().reduced (0.5f), rad, 1.6f);
    }

private:
    void paintPanel (juce::Graphics& g)
    {
        auto full = getLocalBounds().toFloat();

        fillPhosphorGlass (g, full, t);

        // Screen marking, not a toolbar.
        auto mark = full.reduced (7.0f, 5.0f).removeFromTop (10.0f);
        g.setFont (displayFont (7.5f, true));
        g.setColour (t.curveColour().darker (0.45f).withAlpha (0.50f));
        g.drawText ("P2  VERSIONS", mark.toNearestInt(), juce::Justification::centredLeft);

        g.setColour (juce::Colours::black.withAlpha (0.10f));
        for (float y = full.getY() + 18.0f; y < full.getBottom(); y += 18.0f)
            g.drawLine (full.getX() + 5.0f, y, full.getRight() - 5.0f, y, 0.6f);

        for (size_t i = 0; i < cells.size(); ++i)
        {
            const auto cell = cells[i];
            const bool hot   = ((int) i == hover);
            const bool sel   = ((int) i == selected);
            const bool heard = i < slots.size() && slots[i].asHeard;
            paintCell (g, cell, (int) i, sel, hot, heard);
        }

        if (cells.empty())
        {
            g.setColour (t.curveColour().darker (0.25f).withAlpha (0.50f));
            g.setFont (displayFont (10.0f, true));
            g.drawText ("P2", getLocalBounds(), juce::Justification::centred);
        }
    }

    void paintCell (juce::Graphics& g, juce::Rectangle<float> cell, int idx,
                    bool sel, bool hot, bool heard) const
    {
        const auto frame = axisColour (((size_t) idx < slots.size()) ? slots[(size_t) idx].axis
                                                                     : (int) PluginProcessor::AxisFamily);
        g.setColour (juce::Colours::black.withAlpha (sel ? 0.18f : hot ? 0.12f : 0.075f));
        g.fillRect (cell);
        g.setColour (frame.withAlpha (sel ? 0.92f : hot ? 0.70f : 0.45f));
        g.drawRect (cell, sel ? 2.0f : 1.0f);

        // Index label, blocky. Selected = inverted chip (phosphor fill, black numerals).
        auto topRow = cell.removeFromTop (10.0f);
        const auto numBox = topRow.withWidth (16.0f).reduced (1.0f);
        const auto label = juce::String (idx + 1).paddedLeft ('0', 2);
        if (sel)
        {
            g.setColour (frame.withAlpha (0.86f));
            g.fillRect (numBox);
            g.setColour (juce::Colours::black.withAlpha (0.78f));
        }
        else
        {
            g.setColour (frame.withAlpha (hot ? 0.74f : 0.50f));
        }
        g.setFont (displayFont (8.5f, true));
        g.drawText (label, numBox.toNearestInt(), juce::Justification::centred);

        // Effect glyph, top-right — tells you what this variant is at a glance.
        const int axis = ((size_t) idx < slots.size()) ? slots[(size_t) idx].axis
                                                       : (int) PluginProcessor::AxisFamily;
        auto symBox = topRow.removeFromRight (11.0f).reduced (2.0f, 2.0f);
        if (heard)
        {
            g.setColour (frame.withAlpha (0.86f));
            g.fillEllipse (symBox.withSizeKeepingCentre (4.0f, 4.0f)); // the original
        }
        else
        {
            drawSymbol (g, symBox, axis, axisColour (axis));
        }

        drawWave (g, cell.reduced (3.0f, 2.0f), (size_t) idx, sel, hot);
    }

    // Crude vector effect glyphs (no font) — pixelate with the display.
    static void drawSymbol (juce::Graphics& g, juce::Rectangle<float> r, int axis, juce::Colour col)
    {
        g.setColour (col);
        const float cx = r.getCentreX(), cy = r.getCentreY();
        const float w = r.getWidth(), h = r.getHeight();
        switch (axis)
        {
            case PluginProcessor::AxisMorph: // sweep ~
            {
                juce::Path p;
                p.startNewSubPath (r.getX(), cy);
                p.quadraticTo (r.getX() + w * 0.25f, cy - h * 0.55f, cx, cy);
                p.quadraticTo (r.getX() + w * 0.75f, cy + h * 0.55f, r.getRight(), cy);
                g.strokePath (p, juce::PathStrokeType (1.3f));
                break;
            }
            case PluginProcessor::AxisQ: // resonance peak ^
            {
                juce::Path p;
                p.startNewSubPath (r.getX(), r.getBottom());
                p.lineTo (cx, r.getY());
                p.lineTo (r.getRight(), r.getBottom());
                g.strokePath (p, juce::PathStrokeType (1.3f));
                break;
            }
            case PluginProcessor::AxisQSound: // stereo dots
            {
                const float d = juce::jmin (w, h) * 0.5f;
                g.fillEllipse (cx - w * 0.26f - d * 0.5f, cy - d * 0.5f, d, d);
                g.fillEllipse (cx + w * 0.26f - d * 0.5f, cy - d * 0.5f, d, d);
                break;
            }
            case PluginProcessor::AxisSlam: // drive triangle
            {
                juce::Path p;
                p.startNewSubPath (cx, r.getY());
                p.lineTo (r.getRight(), r.getBottom());
                p.lineTo (r.getX(), r.getBottom());
                p.closeSubPath();
                g.fillPath (p);
                break;
            }
            default: // family / filter — small square
                g.fillRect (juce::Rectangle<float> (w * 0.62f, h * 0.62f).withCentre ({ cx, cy }));
                break;
        }
    }

    // Compact crude waveform of the take, coloured by the effect this variant
    // emphasises (Morph/Q/QSound/Slam/family) — you read the tray in colour.
    void drawWave (juce::Graphics& g, juce::Rectangle<float> plot, size_t idx, bool sel, bool hot) const
    {
        if (idx >= slots.size() || ! slots[idx].valid || plot.getHeight() < 4.0f)
            return;

        const auto& s = slots[idx];
        const auto col = axisColour (s.axis);
        const float midY = plot.getCentreY();
        const float half = plot.getHeight() * 0.5f;

        g.setColour (col.withMultipliedAlpha (0.18f));
        g.fillRect (plot.getX(), midY, plot.getWidth(), 1.0f); // baseline

        g.setColour (col.withMultipliedAlpha (sel ? 0.92f : hot ? 0.68f : 0.48f));
        const int N = PluginProcessor::kTakeWaveN;
        const float step = juce::jmax (2.0f, plot.getWidth() / (float) N); // chunky columns
        for (float x = plot.getX(); x < plot.getRight(); x += step)
        {
            const int b = juce::jlimit (0, N - 1, (int) ((x - plot.getX()) / plot.getWidth() * (N - 1)));
            float top = midY - juce::jlimit (-1.0f, 1.0f, s.wmax[b]) * half;
            float bot = midY - juce::jlimit (-1.0f, 1.0f, s.wmin[b]) * half;
            if (bot - top < 1.0f) { top -= 0.5f; bot += 0.5f; }
            g.fillRect (x, top, juce::jmax (1.0f, step - 1.0f), bot - top);
        }
    }

    static juce::Colour axisColour (int axis)
    {
        switch (axis)
        {
            case PluginProcessor::AxisMorph:  return juce::Colour (0xffbfd8ca); // pale sage phosphor
            case PluginProcessor::AxisQ:      return juce::Colour (0xffd6e66e); // caged phosphor
            case PluginProcessor::AxisQSound: return juce::Colour (0xff8fa89b); // smoky sage
            case PluginProcessor::AxisSlam:   return juce::Colour (0xffc8bda4); // worn bone
            default:                          return juce::Colour (0xffe8e3d5); // warm readout plastic
        }
    }

    void rebuildCells()
    {
        cells.clear();
        const int n = (int) slots.size();
        if (n == 0)
            return;

        constexpr int cols = 4, rows = 3;
        const auto area = getLocalBounds().toFloat().reduced (6.0f, 5.0f).withTrimmedTop (15.0f);
        const float cw = area.getWidth()  / (float) cols;
        const float ch = area.getHeight() / (float) rows;
        for (int i = 0; i < n && i < cols * rows; ++i)
        {
            const int cx = i % cols, cy = i / cols;
            cells.push_back (juce::Rectangle<float> (area.getX() + (float) cx * cw,
                                                     area.getY() + (float) cy * ch, cw, ch).reduced (1.5f));
        }
    }

    int cellAt (juce::Point<float> p) const
    {
        for (size_t i = 0; i < cells.size(); ++i)
            if (cells[i].contains (p)) return (int) i;
        return -1;
    }

    void setHover (int h) { if (h != hover) { hover = h; repaint(); } }

    static constexpr int kPixel = 2;   // display pixel size (low-res upscale factor)
    inline static const juce::Colour kBg       { 0xff0a0703 }; // warm near-black
    inline static const juce::Colour kAmber    { 0xffd6e66e }; // caged phosphor pixels
    inline static const juce::Colour kAmberMid { 0xff9aa84e };
    inline static const juce::Colour kAmberDim { 0xff4c5428 };

    Theme t;
    std::vector<PluginProcessor::VariantPreview> slots;
    std::vector<juce::Rectangle<float>> cells;
    int hover = -1;
    int selected = 0;
    int pressedCell = -1;
    bool armedForDrag = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TakeView)
};

} // namespace trench::ui
