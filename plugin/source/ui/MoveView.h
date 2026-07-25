#pragma once
#include "Theme.h"
#include "../PluginProcessor.h"
#include "../dsp/MorphMod.h"
#include "../parameters/TrenchParameters.h"
#include <juce_audio_processors/juce_audio_processors.h>
#include <cmath>
namespace trench::ui
{
// Page-2 modulation preview: the currently selected trench::ModShape plotted
// over exactly one cycle, with a playhead dot at the live mod phase.
class MoveView : public juce::Component
{
public:
    MoveView (PluginProcessor& proc, const Theme& theme)
        : processor (proc), apvts (proc.apvts), t (theme)
    {
        setInterceptsMouseClicks (true, false);
    }
    void refresh()
    {
        shapeIdx = juce::jlimit (0, 5, (int) get (ParamID::modShape));
        on = get (ParamID::modOn) > 0.5f;
        phase = juce::jlimit (0.0f, 1.0f, processor.getModPhaseForUi());
        repaint();
    }
    void mouseDown (const juce::MouseEvent& e) override
    {
        if (! shapeRow().contains (e.position))
            return;
        const int n = 6; // Sine,Tri,Ramp,Stair,Square,Random
        const int idx = juce::jlimit (0, n - 1,
                                      (int) ((e.position.x - shapeRow().getX()) /
                                             (shapeRow().getWidth() / (float) n)));
        setChoice (ParamID::modShape, idx, n);
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
        drawShapeCurve (g, plotBounds());
        drawShapeSilhouettes (g, shapeRow());
    }
private:
    juce::Rectangle<float> shapeRow() const
    {
        return getLocalBounds().toFloat().removeFromTop (37.0f).reduced (8.0f, 5.0f);
    }
    juce::Rectangle<float> plotBounds() const
    {
        auto b = getLocalBounds().toFloat().reduced (7.0f, 6.0f);
        b.removeFromTop (33.0f);
        return b.reduced (0.0f, 2.0f);
    }
    // Deterministic shapes match trench::MorphMod::shapeValue exactly. Random
    // has no fixed cycle in the engine (it's a live held sample); this preview
    // shows a representative stepped pattern only.
    // ponytail: fixed-seed visual stand-in for Random, not a live RNG readout.
    static float shapeValue (int shape, float phase) noexcept
    {
        constexpr float kTwoPi = 6.28318530718f;
        switch ((trench::ModShape) shape)
        {
            case trench::ModShape::Sine:   return std::sin (kTwoPi * phase);
            case trench::ModShape::Tri:    return 1.0f - 4.0f * std::abs (phase - 0.5f);
            case trench::ModShape::Ramp:   return 2.0f * phase - 1.0f;
            case trench::ModShape::Stair:
            {
                const int st = (int) (phase * (float) trench::kStairSteps);
                return 2.0f * ((float) st / (float) (trench::kStairSteps - 1)) - 1.0f;
            }
            case trench::ModShape::Square: return phase < 0.5f ? 1.0f : -1.0f;
            case trench::ModShape::Random:
            {
                static constexpr float held[8] = { 0.4f, -0.7f, 0.9f, -0.2f, 0.1f, -0.9f, 0.6f, -0.4f };
                return held[(int) (phase * 8.0f) & 7];
            }
        }
        return 0.0f;
    }
    void drawShapeCurve (juce::Graphics& g, juce::Rectangle<float> plot) const
    {
        juce::Path path;
        constexpr int N = 128;
        for (int i = 0; i < N; ++i)
        {
            const float p = (float) i / (float) (N - 1);
            const float v = shapeValue (shapeIdx, p);
            const float x = plot.getX() + p * plot.getWidth();
            const float y = plot.getCentreY() - v * plot.getHeight() * 0.5f;
            if (i == 0) path.startNewSubPath (x, y); else path.lineTo (x, y);
        }
        const auto phos = t.curveColour();
        g.setColour (phos.withAlpha (0.18f));
        g.strokePath (path, { 4.5f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded });
        g.setColour (phos.withAlpha (on ? 1.0f : 0.35f));
        g.strokePath (path, { 2.0f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded });
        if (on)
        {
            const float v = shapeValue (shapeIdx, phase);
            const float x = plot.getX() + phase * plot.getWidth();
            const float y = plot.getCentreY() - v * plot.getHeight() * 0.5f;
            g.setColour (t.amber().withAlpha (0.20f));
            g.fillEllipse (x - 5.0f, y - 5.0f, 10.0f, 10.0f);
            g.setColour (t.amber().withAlpha (0.90f));
            g.fillEllipse (x - 2.4f, y - 2.4f, 4.8f, 4.8f);
        }
    }
    void drawShapeSilhouettes (juce::Graphics& g, juce::Rectangle<float> row)
    {
        const int n = 6; // Sine,Tri,Ramp,Stair,Square,Random
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
            juce::Path p;
            constexpr int N = 24;
            for (int s = 0; s < N; ++s)
            {
                const float ph = (float) s / (float) (N - 1);
                const float v = shapeValue (i, ph);
                const float x = cell.getX() + ph * cell.getWidth();
                const float y = cell.getCentreY() - v * cell.getHeight() * 0.42f;
                if (s == 0) p.startNewSubPath (x, y); else p.lineTo (x, y);
            }
            g.setColour (t.curveColour().withAlpha (active ? 1.0f : 0.30f));
            g.strokePath (p, juce::PathStrokeType (active ? 1.6f : 1.0f,
                                                   juce::PathStrokeType::curved,
                                                   juce::PathStrokeType::rounded));
        }
    }
    float get (const juce::String& id) const
    {
        auto* v = apvts.getRawParameterValue (id);
        return v ? v->load() : 0.0f;
    }
    void setChoice (const juce::String& id, int idx, int count)
    {
        if (auto* p = apvts.getParameter (id))
            p->setValueNotifyingHost (count > 1 ? (float) idx / (float) (count - 1) : 0.0f);
    }
    PluginProcessor& processor;
    juce::AudioProcessorValueTreeState& apvts;
    Theme t;
    int shapeIdx = 0;
    bool on = false;
    float phase = 0.0f;
};
}
