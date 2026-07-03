#pragma once

#include "ResponseCurve.h"
#include "Theme.h"
#include "../PluginProcessor.h"
#include "../dsp/GestureEngine.h"
#include "../dsp/MoveMatrix.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>

#include <array>
#include <cmath>
#include <vector>

namespace trench::ui
{

// Page 2 - MOVE. The UI shows the body moving: current packed response, nearby
// packed response ghosts, and an icon-only motion path. The matrix/gesture engine
// vocabulary stays internal.
class MoveView : public juce::Component
{
public:
    MoveView (PluginProcessor& proc, const Theme& theme, juce::Image grid)
        : processor (proc), apvts (proc.apvts), t (theme), gridImage (std::move (grid))
    {
        setInterceptsMouseClicks (true, false);
    }

    void updateFromCoeffs (const float coeffs[30], float boost, double sr)
    {
        if (coeffs == nullptr || sr <= 0.0)
            return;

        bool same = juce::approximatelyEqual (sr, lastSr) && juce::approximatelyEqual (boost, lastBoost);
        for (int i = 0; same && i < 30; ++i)
            same = juce::approximatelyEqual (coeffs[i], lastCoeffs[i]);
        if (same && haveCurrentResponse)
            return;

        for (int i = 0; i < 30; ++i)
            lastCoeffs[i] = coeffs[i];
        lastBoost = boost;
        lastSr = sr;
        haveCurrentResponse = true;
        currentResponsePath = makeResponsePath (coeffs, boost, 190);
        repaint();
    }

    void refresh()
    {
        shapeIdx = (int) get (ParamID::moveShape);
        timeIdx = juce::jlimit (0, trench::kNumGestureTimes - 1, (int) get (ParamID::moveTime));
        moveAmount = norm (ParamID::moveTension);
        phase = juce::jlimit (0.0f, 1.0f, processor.getMovePhaseForUi());
        baseMorph = get (ParamID::morph);
        baseQ = get (ParamID::q);
        baseSlam = get (ParamID::slamDrive);
        rebuildMotionPreview();
        repaint();
    }

    void mouseDown (const juce::MouseEvent& e) override
    {
        if (! shapeRow().contains (e.position))
            return;

        const int n = trench::kNumGestures;
        const int idx = juce::jlimit (0, n - 1,
                                      (int) ((e.position.x - shapeRow().getX()) /
                                             (shapeRow().getWidth() / (float) n)));
        setChoice (ParamID::moveShape, idx, n);
        setBool (ParamID::moveOn, true);
        refresh();
    }

    void paint (juce::Graphics& g) override
    {
        const float rad = 9.0f;
        const auto screen = getLocalBounds().toFloat();
        juce::Path face;
        face.addRoundedRectangle (screen, rad);
        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (face);

        // SAME glass law as Page 1 (GraphDisplay): NOTHING painted over the baked
        // burgundy glass — no fill, no grid image, no atmosphere, no drawn edge.
        // The panel art owns the material and the bezel; this view draws only ink.
        const auto plot = plotBounds();
        drawGhostResponses (g);
        drawMotionPath (g, plot);
        drawCurrentResponse (g);
        drawShapeSilhouettes (g, shapeRow());
        drawGuardDim (g, screen);
    }

private:
    struct Ghost
    {
        juce::Path response;
        float slam = 0.0f;
        float guard = 0.0f;
    };

    juce::Rectangle<float> shapeRow() const
    {
        // Trimmed on the right so the [1][2] page pad (a sibling overlay in the
        // display's top-right corner) never sits on the last gesture silhouette.
        return getLocalBounds().toFloat().removeFromTop (37.0f).reduced (8.0f, 5.0f)
                               .withTrimmedRight (66.0f);
    }

    juce::Rectangle<float> plotBounds() const
    {
        auto b = getLocalBounds().toFloat().reduced (7.0f, 6.0f);
        b.removeFromTop (33.0f);
        return b.reduced (0.0f, 2.0f);
    }

    bool freeTime() const noexcept { return trench::gestureTimeIsFree (timeIdx); }

    float frac (float x) const noexcept
    {
        x = std::fmod (x, 1.0f);
        return x < 0.0f ? x + 1.0f : x;
    }

    trench::MoveMatrix currentMatrix() const noexcept
    {
        trench::MoveMatrix mtx;
        for (int s = 0; s < trench::kNumSources; ++s)
            for (int tt = 0; tt < trench::kNumTargets; ++tt)
                mtx.w[s][tt] = processor.moveMatrixCell (shapeIdx, s, tt);
        return mtx;
    }

    trench::MoveContext currentContext() const noexcept
    {
        trench::MoveContext ctx;
        ctx.driftAmt = get (ParamID::moveDrift);
        ctx.swing = get (ParamID::moveSwing);
        ctx.phaseOffset = get (ParamID::movePhase);
        return ctx;
    }

    trench::MoveLanes lanesAt (float p) const noexcept
    {
        const float lanePhase = freeTime() ? juce::jlimit (0.0f, 1.0f, p) : frac (p);
        const float amount = freeTime() ? lanePhase : moveAmount;
        return trench::evaluateLanes ((trench::Gesture) juce::jlimit (0, trench::kNumGestures - 1, shapeIdx),
                                      lanePhase, amount, baseMorph, baseQ, baseSlam, 0.0f,
                                      currentMatrix(), {}, currentContext());
    }

    float currentControl() const noexcept
    {
        return freeTime() ? moveAmount : phase;
    }

    juce::Path makeResponsePath (const float coeffs[30], float boost, int n) const
    {
        juce::Path p;
        if (lastSr <= 0.0)
            return p;

        const auto pts = responseCurvePoints (coeffs, boost, lastSr, plotBounds(),
                                              t.curveDbTop(), t.curveDbBottom(), n);
        bool started = false;
        for (const auto& pt : pts)
        {
            // sub-pixel like Page 1 — snapping staircases slopes and breaks stroke AA
            if (! started) { p.startNewSubPath (pt.x, pt.y); started = true; }
            else           { p.lineTo (pt.x, pt.y); }
        }
        return p;
    }

    void rebuildMotionPreview()
    {
        const float c = currentControl();
        currentLanes = lanesAt (c);
        ghostResponses.clear();

        if (lastSr <= 0.0)
            return;

        const std::array<float, 5> offsets = freeTime()
            ? std::array<float, 5> { -0.40f, -0.22f, -0.10f, 0.18f, 0.36f }
            : std::array<float, 5> { -0.34f, -0.17f, 0.17f, 0.34f, 0.50f };

        for (float off : offsets)
        {
            const float sample = freeTime() ? juce::jlimit (0.0f, 1.0f, c + off) : frac (c + off);
            const auto lanes = lanesAt (sample);
            float coeffs[30] {};
            float boost = 1.0f;
            if (! processor.probeCurrentBodyForUi (lanes.morph, lanes.press, coeffs, boost))
                continue;

            Ghost ghost;
            ghost.response = makeResponsePath (coeffs, haveCurrentResponse ? lastBoost : boost, 112);
            ghost.slam = lanes.slam;
            ghost.guard = lanes.guard;
            if (! ghost.response.isEmpty())
                ghostResponses.push_back (std::move (ghost));
        }
    }

    void drawShapeSilhouettes (juce::Graphics& g, juce::Rectangle<float> row)
    {
        const int n = trench::kNumGestures;
        const float cw = row.getWidth() / (float) n;
        for (int i = 0; i < n; ++i)
        {
            const bool active = (i == shapeIdx);
            auto cell = row.withX (row.getX() + i * cw).withWidth (cw).reduced (3.0f, 0.0f);
            if (active)
            {
                g.setColour (t.curveColour().withAlpha (0.16f));
                g.fillRoundedRectangle (cell.expanded (1.0f), 3.0f);
                g.setColour (t.curveColour().withAlpha (0.34f));
                g.drawRoundedRectangle (cell.expanded (1.0f), 3.0f, 1.0f);
            }
            else
            {
                g.setColour (t.curveColour().withAlpha (0.055f));
                g.fillRoundedRectangle (cell, 3.0f);
            }
            drawGlyph (g, (trench::Gesture) i, cell.reduced (4.0f, 4.0f), active ? 1.0f : 0.30f);
        }
    }

    void drawGlyph (juce::Graphics& g, trench::Gesture gesture, juce::Rectangle<float> a, float alpha)
    {
        if (gesture == trench::Gesture::Orbit)
        {
            const auto size = juce::jmin (a.getWidth(), a.getHeight());
            auto e = a.withSizeKeepingCentre (size * 0.88f, size * 0.64f);
            g.setColour (t.curveColour().withAlpha (alpha));
            g.drawEllipse (e, alpha > 0.5f ? 1.7f : 1.0f);
            g.fillEllipse (e.getCentreX() - 1.7f, e.getY() - 1.7f, 3.4f, 3.4f);
            return;
        }

        juce::Path p;
        constexpr int N = 28;
        for (int i = 0; i < N; ++i)
        {
            const float tt = (float) i / (float) (N - 1);
            const auto r = trench::evaluateGesture (gesture, tt, 0.86f, 0.5f, 0.5f, 0.0f);
            const float x = a.getX() + tt * a.getWidth();
            const float y = a.getBottom() - r.morph * a.getHeight();
            if (i == 0) p.startNewSubPath (x, y); else p.lineTo (x, y);
        }
        g.setColour (t.curveColour().withAlpha (alpha));
        g.strokePath (p, juce::PathStrokeType (alpha > 0.5f ? 1.8f : 1.0f,
                                               juce::PathStrokeType::curved,
                                               juce::PathStrokeType::rounded));
    }

    void drawGhostResponses (juce::Graphics& g) const
    {
        constexpr auto joint = juce::PathStrokeType::curved;
        constexpr auto cap = juce::PathStrokeType::rounded;
        for (size_t i = 0; i < ghostResponses.size(); ++i)
        {
            const auto& ghost = ghostResponses[i];
            const float age = (float) i / (float) juce::jmax (1, (int) ghostResponses.size() - 1);
            const float a = 0.20f - age * 0.07f;
            const float w = 1.0f + ghost.slam * 1.1f;
            g.setColour (t.curveColour().withAlpha (a));
            g.strokePath (ghost.response, { w + 1.2f, joint, cap });
            g.setColour (t.curveColour().withAlpha (a + 0.05f));
            g.strokePath (ghost.response, { w, joint, cap });
        }
    }

    void drawMotionPath (juce::Graphics& g, juce::Rectangle<float> plot) const
    {
        juce::Path path;
        constexpr int N = 128;
        for (int i = 0; i < N; ++i)
        {
            const float p = (float) i / (float) (N - 1);
            const auto lanes = lanesAt (p);
            const float x = plot.getX() + lanes.morph * plot.getWidth();
            const float y = plot.getBottom() - lanes.press * plot.getHeight();
            if (i == 0) path.startNewSubPath (x, y); else path.lineTo (x, y);
        }

        g.setColour (t.amber().withAlpha (0.16f));
        g.strokePath (path, juce::PathStrokeType (1.2f,
                                                  juce::PathStrokeType::curved,
                                                  juce::PathStrokeType::rounded));

        const float c = currentControl();
        const auto lanes = lanesAt (c);
        const float x = plot.getX() + lanes.morph * plot.getWidth();
        const float y = plot.getBottom() - lanes.press * plot.getHeight();
        g.setColour (t.amber().withAlpha (0.20f));
        g.fillEllipse (x - 5.0f, y - 5.0f, 10.0f, 10.0f);
        g.setColour (t.amber().withAlpha (0.90f));
        g.fillEllipse (x - 2.4f, y - 2.4f, 4.8f, 4.8f);
    }

    void drawCurrentResponse (juce::Graphics& g) const
    {
        if (currentResponsePath.isEmpty())
            return;

        constexpr auto joint = juce::PathStrokeType::curved;
        constexpr auto cap = juce::PathStrokeType::rounded;
        const float intensity = juce::jlimit (0.0f, 1.0f, juce::jmax (currentLanes.slam, currentLanes.press * 0.65f));
        const float mainWidth = 2.0f + intensity * 1.35f;
        const auto phos = t.curveColour();

        g.setColour (phos.withAlpha (0.16f + intensity * 0.16f));
        g.strokePath (currentResponsePath, { mainWidth + 4.0f, joint, cap });
        g.setColour (phos.withAlpha (0.16f + intensity * 0.12f));
        g.strokePath (currentResponsePath, { mainWidth + 2.2f, joint, cap });
        g.setColour (kInk.withAlpha (0.50f));
        g.strokePath (currentResponsePath, { mainWidth + 0.8f, joint, cap });
        g.setColour (phos.withAlpha (1.0f));
        g.strokePath (currentResponsePath, { mainWidth, joint, cap });
        g.setColour (phos.brighter (0.5f).withAlpha (0.68f));
        g.strokePath (currentResponsePath, { juce::jmax (0.8f, mainWidth * 0.42f), joint, cap });
    }

    void drawGuardDim (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        const float guard = juce::jlimit (0.0f, 1.0f, currentLanes.guard);
        if (guard <= 0.0005f)
            return;

        juce::ColourGradient vig (juce::Colours::transparentBlack, screen.getCentreX(), screen.getCentreY(),
                                  juce::Colours::black.withAlpha (0.12f + guard * 0.24f),
                                  screen.getX(), screen.getY(), true);
        vig.addColour (0.58, juce::Colours::transparentBlack);
        g.setGradientFill (vig);
        g.fillRect (screen);
        g.setColour (juce::Colours::black.withAlpha (guard * 0.05f));
        g.fillRect (screen);
    }

    float get (const juce::String& id) const
    {
        auto* v = apvts.getRawParameterValue (id);
        return v ? v->load() : 0.0f;
    }

    float norm (const juce::String& id) const
    {
        auto* p = apvts.getParameter (id);
        return p ? p->getValue() : 0.0f;
    }

    void setChoice (const juce::String& id, int idx, int count)
    {
        if (auto* p = apvts.getParameter (id))
            p->setValueNotifyingHost (count > 1 ? (float) idx / (float) (count - 1) : 0.0f);
    }

    void setBool (const juce::String& id, bool on)
    {
        if (auto* p = apvts.getParameter (id))
            p->setValueNotifyingHost (on ? 1.0f : 0.0f);
    }

    inline static const juce::Colour kInk { 0xff0d100e };

    PluginProcessor& processor;
    juce::AudioProcessorValueTreeState& apvts;
    Theme t;
    juce::Image gridImage;

    juce::Path currentResponsePath;
    std::vector<Ghost> ghostResponses;
    trench::MoveLanes currentLanes;

    float lastCoeffs[30] {};
    float lastBoost = 1.0f;
    double lastSr = 0.0;
    bool haveCurrentResponse = false;

    int shapeIdx = 0;
    int timeIdx = 0;
    float moveAmount = 0.0f;
    float phase = 0.0f;
    float baseMorph = 0.0f;
    float baseQ = 0.0f;
    float baseSlam = 0.0f;
};

} // namespace trench::ui
