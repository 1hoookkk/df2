#pragma once

#include "TrenchStyle.h"
#include "PluginProcessor.h"
#include "parameters/TrenchParameters.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace trench
{
// The FX face of the central screen — shown when the view switch is on FX.
// Screen-styled (same OLED idiom as the response display) so the chassis reads
// as one instrument with a switchable window. Holds player controls:
// SLAM / 5D / OUTPUT + Teleport motion mode (Off/Noise/Strobe/Deriv).
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

        auto pad = getLocalBounds().reduced (10, 9);

        // Header — "FX" on the left; top-right clear for the MAIN/FX view switch.
        auto header = pad.removeFromTop (headerHeight());
        g.setColour (style::oledAmber());
        g.setFont (style::label (juce::jlimit (11.0f, 18.0f, (float) header.getHeight() * 0.9f), true));
        g.drawText ("FX", header, juce::Justification::centredLeft, false);

        // Status strip — body name + last cartridge load.
        auto status = pad.removeFromBottom (statusHeight());
        const bool ok = processor.getLastLoadOk();
        g.setColour (ok ? style::oledCyan() : style::oledRed());
        g.setFont (style::label (juce::jlimit (8.0f, 12.0f, (float) status.getHeight() * 0.72f), true));
        g.drawText (juce::String ("BODY: ") + trench::bodyDisplayName (processor.getLoadedBodyIndex())
                        + (ok ? juce::String() : juce::String ("  [load fail]")),
                    status, juce::Justification::centredLeft, false);

        // ── Main rows (INPUT / SLAM / 5D / OUTPUT) ───────────────────────────
        drawChoiceRow (g, rowBounds (0), "INPUT",  ParamID::inputMode, style::oledAmber());
        drawBarRow    (g, rowBounds (1), "SLAM",   ParamID::slamDrive, style::oledRed(),     false);
        drawChoiceRow (g, rowBounds (2), "5D",     ParamID::fiveD,     style::oledGreen());
        drawBarRow    (g, rowBounds (3), "OUTPUT", ParamID::output,    style::oledMagenta(), true);

        // ── Teleport section divider ──────────────────────────────────────────
        const auto divider = dividerBounds();
        g.setColour (style::oledCyan().withAlpha (0.35f));
        g.drawHorizontalLine (divider.getCentreY(), (float) divider.getX(), (float) divider.getRight());
        g.setColour (style::oledCyan().withAlpha (0.6f));
        g.setFont (style::label (juce::jlimit (7.0f, 10.0f, (float) divider.getHeight() * 0.7f), true));
        g.drawText ("TELEPORT", divider, juce::Justification::centred, false);

        // ── Teleport rows ─────────────────────────────────────────────────────
        const bool tportOn = teleportModeIndex() > 0;
        const bool rateActive = isTeleportRateActive();

        drawChoiceRow (g, rowBounds (4), "TPORT",  ParamID::teleportMode,  style::oledCyan());
        drawBarRow    (g, rowBounds (5), "AMOUNT", ParamID::teleportAmount,
                       tportOn ? style::oledCyan() : style::oledWhite().withAlpha (0.3f), false);
        drawBarRow    (g, rowBounds (6), "RATE",   ParamID::teleportRate,
                       rateActive ? style::oledCyan() : style::oledWhite().withAlpha (0.2f), false);
        drawDepthRow  (g, rowBounds (7));
    }

    void mouseDown (const juce::MouseEvent& e) override
    {
        const auto p = e.getPosition();

        // Choice rows — click to cycle.
        if (rowBounds (0).contains (p)) { cycleChoice (ParamID::inputMode);   return; }
        if (rowBounds (2).contains (p)) { cycleChoice (ParamID::fiveD);       return; }
        if (rowBounds (4).contains (p)) { cycleChoice (ParamID::teleportMode); return; }

        // Bar rows — drag.
        if (barBounds (rowBounds (1)).contains (p)) { dragging = ParamID::slamDrive;      beginDrag (e); return; }
        if (barBounds (rowBounds (3)).contains (p)) { dragging = ParamID::output;          beginDrag (e); return; }
        if (barBounds (rowBounds (5)).contains (p)) { dragging = ParamID::teleportAmount;  beginDrag (e); return; }
        if (barBounds (rowBounds (6)).contains (p)) { dragging = ParamID::teleportRate;    beginDrag (e); return; }

        // Depth row — left half = M, right half = Q.
        const auto depth = rowBounds (7);
        const auto [mBar, qBar] = splitDepthBars (depth);
        if (mBar.contains (p)) { dragging = ParamID::teleportMorphDepth; beginDrag (e); return; }
        if (qBar.contains (p)) { dragging = ParamID::teleportQDepth;     beginDrag (e); return; }
    }

    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (dragging == nullptr) return;

        juce::Rectangle<int> bar;
        if      (dragging == ParamID::slamDrive)          bar = barBounds (rowBounds (1));
        else if (dragging == ParamID::output)              bar = barBounds (rowBounds (3));
        else if (dragging == ParamID::teleportAmount)      bar = barBounds (rowBounds (5));
        else if (dragging == ParamID::teleportRate)        bar = barBounds (rowBounds (6));
        else if (dragging == ParamID::teleportMorphDepth)  bar = splitDepthBars (rowBounds (7)).first;
        else if (dragging == ParamID::teleportQDepth)      bar = splitDepthBars (rowBounds (7)).second;

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

    int headerHeight() const { return juce::jmax (14, juce::roundToInt ((float) getHeight() * 0.10f)); }
    int statusHeight() const { return juce::jmax (12, juce::roundToInt ((float) getHeight() * 0.08f)); }
    int dividerH()     const { return juce::jmax (12, juce::roundToInt ((float) getHeight() * 0.065f)); }

    // Body area after removing header, status, and the teleport divider strip.
    // Splits into 4 main rows + divider + 4 teleport rows.
    juce::Rectangle<int> bodyArea() const
    {
        auto pad = getLocalBounds().reduced (10, 9);
        pad.removeFromTop (headerHeight() + 3);
        pad.removeFromBottom (statusHeight() + 3);
        return pad;
    }

    // Row layout: 4 main rows, 1 divider, 4 teleport rows — 9 slots total.
    // Each slot gets an equal share of the body height.
    static constexpr int kNumSlots = 9;

    juce::Rectangle<int> slot (int i) const
    {
        const auto area = bodyArea();
        const int gap = 3;
        const int h = juce::jmax (14, (area.getHeight() - gap * (kNumSlots - 1)) / kNumSlots);
        return { area.getX(), area.getY() + i * (h + gap), area.getWidth(), h };
    }

    // Main rows occupy slots 0-3, divider = slot 4, teleport rows = slots 5-8.
    juce::Rectangle<int> rowBounds (int row) const
    {
        // rows 0-3 → slots 0-3; rows 4-7 → slots 5-8 (divider is slot 4).
        return slot (row < 4 ? row : row + 1);
    }

    juce::Rectangle<int> dividerBounds() const { return slot (4); }

    // ── helpers ───────────────────────────────────────────────────────────────

    int labelWidth (juce::Rectangle<int> row) const { return juce::jmax (48, row.getWidth() / 4); }

    juce::Rectangle<int> barBounds (juce::Rectangle<int> row) const
    {
        return row.withTrimmedLeft (labelWidth (row) + 5).reduced (0, juce::jmax (2, row.getHeight() / 4));
    }

    // Depth row: "M" label + bar on left half, "Q" label + bar on right half.
    std::pair<juce::Rectangle<int>, juce::Rectangle<int>>
    splitDepthBars (juce::Rectangle<int> row) const
    {
        const int lw = labelWidth (row) / 2 + 2; // compact label for M / Q
        const int halfW = (row.getWidth() - lw * 2 - 8) / 2;
        const int barH = juce::jmax (4, row.getHeight() - row.getHeight() / 2);
        const int barY = row.getY() + (row.getHeight() - barH) / 2;

        const int mX = row.getX() + lw;
        const int qX = mX + halfW + 8 + lw;

        return {
            { mX, barY, halfW, barH },
            { qX, barY, halfW, barH },
        };
    }

    // ── draw helpers ──────────────────────────────────────────────────────────

    void drawLabel (juce::Graphics& g, juce::Rectangle<int> row, const juce::String& text,
                    juce::Colour col = juce::Colour()) const
    {
        g.setColour (col.isTransparent() ? style::oledCyan().withAlpha (0.9f) : col);
        g.setFont (style::label (juce::jlimit (8.0f, 13.0f, (float) row.getHeight() * 0.52f), true));
        g.drawText (text, row.withWidth (labelWidth (row)), juce::Justification::centredLeft, false);
    }

    void drawChoiceRow (juce::Graphics& g, juce::Rectangle<int> row, const juce::String& label,
                        const char* id, juce::Colour valueCol) const
    {
        drawLabel (g, row, label);
        const auto cell = barBounds (row);
        g.setColour (juce::Colours::black.withAlpha (0.45f));
        g.fillRect (cell);
        g.setColour (style::oledWhite().withAlpha (0.4f));
        g.drawRect (cell, 1);

        juce::String value;
        if (auto* p = apvts.getParameter (id))
            value = p->getCurrentValueAsText();
        const bool off = value.equalsIgnoreCase ("Off") || value.equalsIgnoreCase ("OFF");
        g.setColour (off ? style::oledWhite().withAlpha (0.5f) : valueCol);
        g.setFont (style::label (juce::jlimit (8.0f, 13.0f, (float) cell.getHeight() * 0.62f), true));
        g.drawText (value, cell.reduced (5, 0), juce::Justification::centred, false);
    }

    void drawBarRow (juce::Graphics& g, juce::Rectangle<int> row, const juce::String& label,
                     const char* id, juce::Colour fillCol, bool bipolar) const
    {
        drawLabel (g, row, label);
        const auto bar = barBounds (row);
        g.setColour (juce::Colours::black.withAlpha (0.45f));
        g.fillRect (bar);
        g.setColour (style::oledWhite().withAlpha (0.4f));
        g.drawRect (bar, 1);

        float v01 = 0.0f;
        juce::String text;
        if (auto* p = apvts.getParameter (id))
        {
            v01  = p->getValue();
            text = p->getCurrentValueAsText();
        }

        if (bipolar)
        {
            const int mid = bar.getCentreX();
            const int x   = bar.getX() + juce::roundToInt (v01 * (float) bar.getWidth());
            const auto fill = juce::Rectangle<int>::leftTopRightBottom (juce::jmin (mid, x), bar.getY() + 2,
                                                                        juce::jmax (mid, x), bar.getBottom() - 2);
            g.setColour (fillCol.withAlpha (0.8f));
            g.fillRect (fill);
            g.setColour (style::oledWhite().withAlpha (0.5f));
            g.drawVerticalLine (mid, (float) bar.getY(), (float) bar.getBottom());
        }
        else
        {
            const int w = juce::roundToInt (v01 * (float) bar.getWidth());
            g.setColour (fillCol.withAlpha (0.8f));
            g.fillRect (juce::Rectangle<int> (bar.getX(), bar.getY() + 2, w, bar.getHeight() - 4));
        }

        g.setColour (style::oledWhite());
        g.setFont (style::label (juce::jlimit (7.0f, 11.0f, (float) bar.getHeight() * 0.6f), true));
        g.drawText (text, bar.reduced (4, 0), juce::Justification::centredRight, false);
    }

    void drawDepthRow (juce::Graphics& g, juce::Rectangle<int> row) const
    {
        // "DEPTH" label on far left.
        drawLabel (g, row, "DEPTH");

        const auto [mBar, qBar] = splitDepthBars (row);
        const int lw = labelWidth (row) / 2 + 2;

        // M label
        g.setColour (style::oledCyan().withAlpha (0.7f));
        g.setFont (style::label (juce::jlimit (7.0f, 11.0f, (float) row.getHeight() * 0.5f), true));
        g.drawText ("M", juce::Rectangle<int> (mBar.getX() - lw, row.getY(), lw, row.getHeight()),
                    juce::Justification::centredRight, false);

        // Q label
        g.drawText ("Q", juce::Rectangle<int> (qBar.getX() - lw, row.getY(), lw, row.getHeight()),
                    juce::Justification::centredRight, false);

        // M bar
        drawMiniBar (g, mBar, ParamID::teleportMorphDepth, style::oledCyan());
        // Q bar
        drawMiniBar (g, qBar, ParamID::teleportQDepth,     style::oledCyan());
    }

    void drawMiniBar (juce::Graphics& g, juce::Rectangle<int> bar,
                      const char* id, juce::Colour fillCol) const
    {
        g.setColour (juce::Colours::black.withAlpha (0.45f));
        g.fillRect (bar);
        g.setColour (style::oledWhite().withAlpha (0.4f));
        g.drawRect (bar, 1);

        float v01 = 0.0f;
        if (auto* p = apvts.getParameter (id))
            v01 = p->getValue();

        const int w = juce::roundToInt (v01 * (float) bar.getWidth());
        g.setColour (fillCol.withAlpha (0.75f));
        g.fillRect (juce::Rectangle<int> (bar.getX(), bar.getY() + 1, w, bar.getHeight() - 2));
    }

    // ── interaction helpers ───────────────────────────────────────────────────

    int teleportModeIndex() const
    {
        if (auto* p = apvts.getParameter (ParamID::teleportMode))
            return juce::roundToInt (p->getValue() * (float) juce::jmax (1, p->getNumSteps() - 1));
        return 0;
    }

    bool isTeleportRateActive() const
    {
        const int idx = teleportModeIndex();
        return idx == 1 || idx == 2; // Noise or Strobe
    }

    void cycleChoice (const char* id)
    {
        auto* p = apvts.getParameter (id);
        if (p == nullptr) return;
        const int numSteps = juce::jmax (1, p->getNumSteps());
        const int curIndex = juce::roundToInt (p->getValue() * (float) (numSteps - 1));
        const int nextIdx  = (curIndex + 1) % numSteps;
        p->beginChangeGesture();
        p->setValueNotifyingHost ((float) nextIdx / (float) juce::jmax (1, numSteps - 1));
        p->endChangeGesture();
        repaint();
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
