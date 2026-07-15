#pragma once

#include "Theme.h"
#include "../dsp/SlamStage.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>

#include <cmath>
#include <complex>
#include <memory>
#include <vector>

namespace trench::ui
{

// Precision-fitted smoked glass plus the live cascade response. The electronics
// may still look tired; the glass itself is an optically bonded, machined part.
//
// SLAM is a SECONDARY on-screen control (not a rail): dragging the canvas vertically
// (or the mouse wheel over the graph) drives SLAM/input-clip, with a transient
// "SLAM xx.x" overlay. Up = push harder into it. Default is the parameter's own.
//
// Preview-only: curve, nothing else. MOTION/TIME are picked and shown in
// their own compact row below the screen (MotionTimeRow) — this view never
// draws text of its own for them.
class GraphDisplay : public juce::Component,
                     private juce::Timer
{
public:
    // SEED's on-screen feedback: a controlled sibling-mutation pulse, not a
    // randomize/loading animation. Compress -> brief static tear -> redraw
    // into the new (post-seed) curve. No seed numbers, no spinner, no
    // warning colour -- see playSeedPulse().
    void playSeedPulse()
    {
        if (traceXs.empty() || traceDbs.size() != traceXs.size())
            return; // no curve to animate from yet
        pulseOldDbs = traceDbs;
        pulsePhase = PulseCompress;
        pulseElapsedMs = 0.0;
        startTimer (30);
        repaint();
    }


    GraphDisplay (const Theme& theme,
                  juce::AudioProcessorValueTreeState& apvts, const juce::String& canvasParamId)
        : t (theme)
    {
        canvasParam = apvts.getParameter (canvasParamId);
        if (canvasParam != nullptr)
        {
            canvasAtt = std::make_unique<juce::ParameterAttachment> (*canvasParam, [this] (float)
            {
                meterAlpha = 1.0f;            // any SLAM change breathes the meter in...
                if (! pressing) startTimer (30);   // ...and it fades once the value rests
                repaint();
            });
            canvasDefault = canvasParam->getDefaultValue();
            setMouseCursor (juce::MouseCursor::UpDownResizeCursor);
        }
        // The screen takes mouse input to drive SLAM (children like the [1][2]
        // pad and MOD tag sit on top and still get their own clicks).
        setInterceptsMouseClicks (canvasParam != nullptr, false);
    }

    void setSlamMeter (float outClipFrac) noexcept
    {
        const float v = juce::jlimit (0.0f, 1.0f, outClipFrac);
        if (juce::approximatelyEqual (slamOutClip, v))
        {
            if (v > 0.001f && meterAlpha < 0.72f)
            {
                meterAlpha = 0.72f;
                if (! pressing)
                    startTimer (30);
                repaint();
            }
            return;
        }

        slamOutClip = v;
        if (v > 0.001f)
        {
            meterAlpha = juce::jmax (meterAlpha, 0.72f);
            if (! pressing)
                startTimer (30);
        }
        repaint();
    }

    // Rebuild the response Path from the engine's live biquad coefficients. No-op
    // when nothing changed, so an idle UI does no work.
    void updateFromCoeffs (const float coeffs[30], float boost, double sr)
    {
        bool same = juce::approximatelyEqual (sr, lastSr) && juce::approximatelyEqual (boost, lastBoost);
        for (int i = 0; same && i < 30; ++i)
            same = juce::approximatelyEqual (coeffs[i], lastCoeffs[i]);
        if (same && haveCurve)
            return;

        for (int i = 0; i < 30; ++i) lastCoeffs[i] = coeffs[i];
        lastBoost = boost; lastSr = sr; haveCurve = true;

        const auto plot = plotBounds();
        if (plot.isEmpty())
            return;

        const double dbTop = t.curveDbTop(), dbBot = t.curveDbBottom();
        const double fLo = 20.0, fHi = juce::jmin (20000.0, sr * 0.5 - 1.0);

        // Pixel-snapped sampling: enough points to resolve resonances, but still
        // crude like an old utility display rather than a smooth DAW graph.
        constexpr int N = 190;
        juce::Path path;
        bool started = false;
        traceXs.clear();
        traceDbs.clear();
        traceXs.reserve (N);
        traceDbs.reserve (N);
        for (int i = 0; i < N; ++i)
        {
            const double frac = (double) i / (double) (N - 1);
            const double f = fLo * std::pow (fHi / fLo, frac);
            const double w = 2.0 * juce::MathConstants<double>::pi * f / sr;
            const std::complex<double> zinv = std::exp (std::complex<double> (0.0, -w));

            double mag = (double) boost; bool ok = true;
            for (int s = 0; s < 6; ++s)
            {
                const double b0 = coeffs[s*5+0], b1 = coeffs[s*5+1], b2 = coeffs[s*5+2];
                const double a1 = coeffs[s*5+3], a2 = coeffs[s*5+4];
                const auto num = b0 + b1*zinv + b2*zinv*zinv;
                const auto den = 1.0 + a1*zinv + a2*zinv*zinv;
                const double da = std::abs (den);
                if (! std::isfinite (da) || da < 1.0e-9) { ok = false; break; }
                mag *= std::abs (num) / da;
            }
            if (! ok || ! std::isfinite (mag)) continue;

            const double db = 20.0 * std::log10 (juce::jmax (mag, 1.0e-6));
            // Internal safe area: the trace saturates just INSIDE the plot so a
            // deep notch or hot peak never collides with the glass edge.
            const double yt = juce::jlimit (0.015, 0.985, (dbTop - db) / (dbTop - dbBot));
            // Sub-pixel positions: pixel-snapping staircased every slope and broke the
            // stroke's anti-aliasing. The path keeps float precision; the stroke AA's.
            const float x = plot.getX() + (float) frac * plot.getWidth();
            const float y = plot.getY() + (float) yt * plot.getHeight();
            if (! started)
            {
                path.startNewSubPath (x, y);
                started = true;
            }
            else
            {
                path.lineTo (x, y);   // smooth segments — cleaner/more authoritative than the old staircase
            }
            traceXs.push_back (x);
            traceDbs.push_back ((float) db);
        }

        responsePath = std::move (path);
        repaint();
    }

    // --- SLAM: vertical drag + wheel drive input-clip/SLAM (up = harder) ------
    void mouseDown (const juce::MouseEvent& e) override
    {
        if (canvasParam == nullptr) return;
        pressing = true;
        stopTimer();
        meterAlpha = 1.0f;
        dragStartY = e.position.y;
        dragPos = e.position;
        canvasAtStart = canvasParam->getValue();
        if (canvasAtt != nullptr) canvasAtt->beginGesture();
        repaint();
    }

    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (canvasParam == nullptr || canvasAtt == nullptr) return;
        dragPos = e.position;
        const float h = juce::jmax (1.0f, (float) getHeight());
        const float scale = e.mods.isShiftDown() ? 0.25f : 1.0f;       // fine adjust
        const float next = juce::jlimit (0.0f, 1.0f,
                                         canvasAtStart - ((e.position.y - dragStartY) / h) * scale); // up = more
        canvasAtt->setValueAsPartOfGesture (canvasParam->convertFrom0to1 (next));
        repaint();
    }

    void mouseUp (const juce::MouseEvent&) override
    {
        if (canvasParam == nullptr) return;
        pressing = false;
        if (canvasAtt != nullptr) canvasAtt->endGesture();
        startTimer (30);   // let the meter fade out slowly
        repaint();
    }

    void mouseDoubleClick (const juce::MouseEvent&) override
    {
        if (canvasAtt != nullptr) canvasAtt->setValueAsCompleteGesture (canvasDefault);
    }

    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w) override
    {
        if (canvasParam == nullptr || canvasAtt == nullptr) return;
        const float next = juce::jlimit (0.0f, 1.0f, canvasParam->getValue() + w.deltaY * 0.08f);
        canvasAtt->setValueAsCompleteGesture (canvasParam->convertFrom0to1 (next));
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const float rad = 9.0f;
        const auto aperture = getLocalBounds().toFloat();
        constexpr float reveal = 1.95f;
        const auto glass = aperture.reduced (reveal);
        const float glassRad = rad - reveal;

        // 1.95 px blackened-nickel reveal. It exposes enough of the precision
        // backing plate to separate the glass without becoming a chunky bezel.
        // It is not a chrome border or an outer shadow.
        {
            juce::ColourGradient nickel (juce::Colour (0xff24211d), aperture.getX(), aperture.getY(),
                                         juce::Colour (0xff080a0c), aperture.getRight(), aperture.getBottom(), false);
            nickel.addColour (0.38, juce::Colour (0xff111316));
            g.setGradientFill (nickel);
            g.fillRoundedRectangle (aperture, rad);

            g.setColour (juce::Colours::black.withAlpha (0.72f));
            g.drawRoundedRectangle (aperture.reduced (0.35f), rad - 0.25f, 0.75f);

            // Warm nickel responds only along the lit half of the top edge.
            juce::ColourGradient catchLight (juce::Colour (0xffb69a70).withAlpha (0.16f),
                                             aperture.getX() + rad, 0.0f,
                                             juce::Colours::transparentBlack,
                                             aperture.getX() + aperture.getWidth() * 0.72f, 0.0f, false);
            g.setGradientFill (catchLight);
            g.fillRect (aperture.getX() + rad, aperture.getY() + 0.45f,
                        aperture.getWidth() - 2.0f * rad, 0.70f);
        }

        {
            juce::Path face;
            face.addRoundedRectangle (glass, glassRad);
            juce::Graphics::ScopedSaveState save (g);
            g.reduceClipRegion (face);

            drawFailingGlassBed (g, glass);
            drawLogGrid (g, glass);

            armed = canvasParam != nullptr
                        ? juce::jlimit (0.0f, 1.0f, (canvasParam->getValue() - 0.15f) / 0.60f)
                        : 0.0f;

            drawResponseTrace (g);
            drawSlamReadout (g, glass);
            drawDisplayDropouts (g, glass);

            // One faint, broad reflection inside the glass. No stripe, glare
            // decal or perspective trick: just the pane catching room light.
            juce::ColourGradient reflection (juce::Colour (0xfffff1d8).withAlpha (0.036f),
                                                 glass.getX() + glass.getWidth() * 0.16f, glass.getY(),
                                                 juce::Colours::transparentBlack,
                                                 glass.getX() + glass.getWidth() * 0.72f,
                                                 glass.getY() + glass.getHeight() * 0.55f, false);
            reflection.addColour (0.46, juce::Colour (0xfffff1d8).withAlpha (0.014f));
            g.setGradientFill (reflection);
            g.fillRect (glass.getX(), glass.getY(), glass.getWidth(), glass.getHeight() * 0.58f);

            juce::ColourGradient vig (juce::Colours::transparentBlack,
                                      glass.getCentreX(), glass.getCentreY(),
                                      juce::Colours::black.withAlpha (0.13f),
                                      glass.getX(), glass.getY(), true);
            vig.addColour (0.73, juce::Colours::transparentBlack);
            g.setGradientFill (vig);
            g.fillRect (glass);
        }

        // Hairline inner seam: the glass meets the reveal with zero visible lift.
        g.setColour (juce::Colours::black.withAlpha (0.68f));
        g.drawRoundedRectangle (glass, glassRad, 0.75f);
    }

private:
    juce::Rectangle<float> plotBounds() const { return getLocalBounds().toFloat().reduced (6.0f, 5.0f); }

    void drawFailingGlassBed (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        // Dense neutral smoke: slightly reflective at the crown, optically deep
        // at the floor. Opaque enough to read as its own fitted material.
        juce::ColourGradient smoke (juce::Colour (0xff24272a), 0.0f, screen.getY(),
                                    juce::Colour (0xff0e1012), 0.0f, screen.getBottom(), false);
        smoke.addColour (0.46, juce::Colour (0xff181b1e));
        g.setGradientFill (smoke);
        g.fillRect (screen);

        juce::ColourGradient dead (juce::Colours::black.withAlpha (0.18f),
                                   screen.getX(), screen.getY(),
                                    juce::Colours::transparentBlack,
                                    screen.getRight(), screen.getBottom(), false);
        dead.addColour (0.58, juce::Colour (0xff302a23).withAlpha (0.08f));
        g.setGradientFill (dead);
        g.fillRect (screen);

        // Uneven LCD ageing, deterministic and clipped to the aperture.
        for (int i = 0; i < 18; ++i)
        {
            const float x = screen.getX() + std::fmod (19.0f + (float) i * 47.0f, screen.getWidth());
            const float a = (i % 4 == 0) ? 0.072f : 0.030f;
            g.setColour (juce::Colours::black.withAlpha (a));
            g.drawLine (x, screen.getY(), x - 7.0f, screen.getBottom(), (i % 3 == 0) ? 1.2f : 0.7f);
        }

        g.setColour (juce::Colours::black.withAlpha (0.075f));
        for (float y = screen.getY() + 9.0f; y < screen.getBottom(); y += 13.0f)
            g.drawLine (screen.getX(), y, screen.getRight(), y, 0.55f);
    }

    // Ruled log-frequency grid on dying glass: still readable, but not married
    // to the fresh plate typography.
    void drawLogGrid (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        const auto plot = plotBounds();
        if (plot.isEmpty())
            return;
        const auto ink = t.dashed();
        const double fLo = 20.0, fHi = 20000.0;
        const auto xOf = [&] (double f)
        { return plot.getX() + (float) (std::log (f / fLo) / std::log (fHi / fLo)) * plot.getWidth(); };
        for (double decade = 10.0; decade < fHi; decade *= 10.0)
            for (int m = 2; m <= 10; ++m)
            {
                const double f = decade * m;
                if (f <= fLo || f >= fHi)
                    continue;
                const bool major = (m == 10);
                g.setColour (ink.withAlpha (major ? 0.36f : 0.17f));
                g.drawLine (xOf (f), screen.getY(), xOf (f), screen.getBottom(), major ? 0.95f : 0.55f);
            }
        const double dbTop = t.curveDbTop(), dbBot = t.curveDbBottom();
        for (double db = std::ceil (dbBot / 10.0) * 10.0; db <= dbTop; db += 10.0)
        {
            const float y = plot.getY() + (float) ((dbTop - db) / (dbTop - dbBot)) * plot.getHeight();
            g.setColour (ink.withAlpha (juce::approximatelyEqual (db, 0.0) ? 0.34f : 0.15f));
            g.drawLine (screen.getX(), y, screen.getRight(), y, 0.55f);
        }
    }

    float slamVisualAmount() const noexcept
    {
        const float x = slamNorm();
        return x * x * (3.0f - 2.0f * x);
    }

    float slamNorm() const noexcept
    {
        if (canvasParam == nullptr)
            return 0.0f;
        return juce::jlimit (0.0f, 1.0f, canvasParam->getValue());
    }

    // Phosphor for the trace: faded cobalt at clean output, lifting toward a worn
    // phosphor white as SLAM pushes the output into gain and limiting. This is a
    // visual output read, not a claim that SLAM changes the filter body.
    juce::Colour responseColour() const
    {
        return t.curveColour().interpolatedWith (juce::Colour (0xffe7e1d3), slamVisualAmount());
    }

    // Etched phosphor trace, stroked from the live response Path. The wide pass is
    // only screen wetness; the curve itself stays thin and physical.
    void drawResponseTrace (juce::Graphics& g) const
    {
        if (pulsePhase != PulseIdle)
        {
            drawSeedPulseTrace (g);
            return;
        }

        // The curve is the true current six-stage body response.  SLAM is
        // post-filter output pressure, so it may light the trace but must
        // never reshape it.  MOTION state likewise does not change visibility
        // of the filter that is actually sounding.
        const float s = slamVisualAmount();
        const auto phos = responseColour();
        const float limit = juce::jlimit (0.0f, 1.0f, slamOutClip);

        const auto plot = plotBounds();
        if (traceXs.empty() || traceXs.size() != traceDbs.size() || plot.isEmpty())
        {
            if (! responsePath.isEmpty())                 // fallback: smooth stroke
            {
                g.setColour (phos.withAlpha (0.98f));
                g.strokePath (responsePath, { 2.5f, juce::PathStrokeType::curved,
                                              juce::PathStrokeType::rounded });
            }
            return;
        }

        // Bitmap-crunch trace (the X3-family reference): the response drawn as a
        // 2px-quantised STAIRCASE, butt caps — a hand-pixelled hardware curve,
        // not an antialiased vector.
        const double dbTop = t.curveDbTop(), dbBot = t.curveDbBottom();
        const float q = 2.0f;                              // pixel-crunch quantum
        const size_t N = traceXs.size();
        auto yOf = [&] (size_t i)
        {
            const double yt = juce::jlimit (-0.06, 1.06, (dbTop - traceDbs[i]) / (dbTop - dbBot));
            const float y = plot.getY() + (float) yt * plot.getHeight();
            return q * std::round (y / q);                 // snap to the crunch grid
        };

        juce::Path stair;
        juce::Path edgeCatch;
        float px = traceXs[0];
        float py = yOf (0);
        stair.startNewSubPath (px, py);

        bool catchPenDown = false;
        juce::Point<float> catchEnd;
        const auto appendEdgeCatch = [&] (float x0, float y0, float x1, float y1)
        {
            if (std::abs (x1 - x0) + std::abs (y1 - y0) < 0.1f)
                return;

            // Fixed, irregular 10px bands: enough interruption to feel like a
            // dry phosphor/print catch, never a regular dashed software line.
            const int band = juce::jmax (0, (int) std::floor ((0.5f * (x0 + x1) - plot.getX()) / 10.0f));
            const int signature = (band * 7 + 5) % 19;
            const bool visible = signature != 0 && signature != 4 && signature != 11;
            if (! visible)
            {
                catchPenDown = false;
                return;
            }

            const juce::Point<float> start { x0, y0 };
            if (! catchPenDown || catchEnd.getDistanceFrom (start) > 0.1f)
                edgeCatch.startNewSubPath (start);
            edgeCatch.lineTo (x1, y1);
            catchEnd = { x1, y1 };
            catchPenDown = true;
        };

        for (size_t i = 1; i < N; ++i)
        {
            const float x = traceXs[i];
            const float y = yOf (i);
            if (! juce::approximatelyEqual (y, py))
            {
                stair.lineTo (x, py);                      // run, then rise: the staircase
                appendEdgeCatch (px, py, x, py);
                stair.lineTo (x, y);
                appendEdgeCatch (x, py, x, y);
            }
            else
            {
                stair.lineTo (x, y);
                appendEdgeCatch (px, py, x, y);
            }
            px = x;
            py = y;
        }

        // SLAM lives ON the trace: no fill, no bars — the line itself heats,
        // thickens, and carries a glow halo that swells with drive.
        if (s > 0.01f)
        {
            g.setColour (t.amber().withAlpha (0.12f + 0.30f * s));
            g.strokePath (stair, { 4.0f + 6.0f * s, juce::PathStrokeType::mitered,
                                   juce::PathStrokeType::butt });
        }

        // LOW SIGNAL by design: a slightly starved beam — dimmer, thinner,
        // the analog read of a weak trace on old glass.
        constexpr auto joint = juce::PathStrokeType::mitered;
        constexpr auto cap   = juce::PathStrokeType::butt;
        const float lw = 2.0f + 0.7f * s;
        g.setColour (juce::Colour (0xff15151a).withAlpha (0.55f));      // soft offset bed (dark glass)
        g.strokePath (stair, { lw + 0.7f, joint, cap },
                      juce::AffineTransform::translation (1.2f, 1.8f));
        g.setColour (phos.withAlpha (0.66f));                           // the starved signal
        g.strokePath (stair, { lw, joint, cap });

        // Broken warm-bone edge catch: a fractional-pixel registration lift on
        // the upper-left edge of the crude staircase. It replaces the old full
        // centre highlight, so it reads as material finesse rather than glow.
        g.setColour (juce::Colour (0xffe2d6c0).withAlpha (0.12f + 0.04f * s));
        g.strokePath (edgeCatch, { 0.65f, joint, cap },
                      juce::AffineTransform::translation (-0.25f, -0.75f));
        if (limit > 0.001f)
        {
            g.setColour (juce::Colour (0xffeee7d7).withAlpha (0.12f + 0.28f * limit));
            g.strokePath (stair, { 0.8f + 1.0f * limit, joint, cap });
        }

        // Peak crosses (the reference's + ticks): small markers on the mode
        // crests — the anatomy made visible, not decoration.
        {
            g.setColour (juce::Colour (0xfffff0e8).withAlpha (0.58f));
            int marks = 0;
            for (size_t i = 2; i + 2 < N && marks < 8; ++i)
            {
                const double d = traceDbs[i];
                if (d > traceDbs[i-1] && d >= traceDbs[i+1]
                    && d - juce::jmin (traceDbs[i-2], traceDbs[i+2]) > 2.5)
                {
                    const float x = q * std::round (traceXs[i] / q), y = yOf (i) - 4.0f;
                    g.drawLine (x - 3.0f, y, x + 3.0f, y, 1.4f);
                    g.drawLine (x, y - 3.0f, x, y + 3.0f, 1.4f);
                    ++marks;
                    i += 4;                                 // one cross per crest
                }
            }
        }
    }

    void drawDisplayDropouts (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        g.setColour (juce::Colours::black.withAlpha (0.28f));
        g.fillRect (screen.getX(), screen.getY(), screen.getWidth(), 1.0f);
        g.fillRect (screen.getX(), screen.getBottom() - 1.4f, screen.getWidth(), 1.4f);

        const float ys[] = { 31.0f, 74.0f, 126.0f, 211.0f, 287.0f };
        for (float off : ys)
        {
            const float y = screen.getY() + std::fmod (off, screen.getHeight() - 4.0f);
            const float x0 = screen.getX() + 18.0f + std::fmod (off * 3.7f, screen.getWidth() * 0.28f);
            const float x1 = screen.getRight() - 24.0f - std::fmod (off * 2.1f, screen.getWidth() * 0.22f);
            g.setColour (juce::Colours::black.withAlpha (0.16f));
            g.drawLine (x0, y, x1, y, 0.9f);
        }

        // Two weak vertical failures at the edges, as if the panel is losing
        // contact rather than glowing as one clean DAW widget.
        g.setColour (juce::Colours::black.withAlpha (0.18f));
        g.fillRect (screen.getX() + screen.getWidth() * 0.055f, screen.getY(), 1.0f, screen.getHeight());
        g.fillRect (screen.getRight() - screen.getWidth() * 0.082f, screen.getY(), 1.0f, screen.getHeight());
    }

    // SEED's screen feedback: the OLD curve compresses toward a hot ruby
    // scanline, tears with a few frames of quiet static, then the same
    // scanline unfurls into the NEW (already-seeded) curve. No slam-warp
    // during the pulse -- it is a brief, self-contained transition.
    void drawSeedPulseTrace (juce::Graphics& g) const
    {
        if (traceXs.empty() || traceXs.size() != traceDbs.size() || traceXs.size() != pulseOldDbs.size())
            return;

        const auto plot = plotBounds();
        if (plot.isEmpty())
            return;

        const double dbTop = t.curveDbTop(), dbBot = t.curveDbBottom();
        const float centreY = plot.getY() + plot.getHeight() * 0.5f;
        const size_t N = traceXs.size();

        float squash = 1.0f;         // 1 = normal shape, ~0.06 = collapsed scanline
        float progress = 0.0f;       // 0..1 within the current phase
        bool jitter = false;

        if (pulsePhase == PulseCompress)
        {
            progress = (float) juce::jlimit (0.0, 1.0, pulseElapsedMs / kPulseCompressMs);
            squash = juce::jmap (progress, 1.0f, 0.06f);
        }
        else if (pulsePhase == PulseStatic)
        {
            squash = 0.06f;
            jitter = true;
        }
        else // PulseRedraw
        {
            progress = (float) juce::jlimit (0.0, 1.0, pulseElapsedMs / kPulseRedrawMs);
            squash = juce::jmap (progress, 0.06f, 1.0f);
        }

        juce::Path path;
        for (size_t i = 0; i < N; ++i)
        {
            double db = pulseOldDbs[i];
            if (pulsePhase == PulseRedraw)
                db = pulseOldDbs[i] + (traceDbs[i] - pulseOldDbs[i]) * progress;

            double yt = juce::jlimit (-0.06, 1.06, (dbTop - db) / (dbTop - dbBot));
            float y = plot.getY() + (float) yt * plot.getHeight();
            y = centreY + (y - centreY) * squash;
            if (jitter)
                y += pulseRng.nextFloat() * 3.0f - 1.5f; // quiet tear, not a chaotic glitch

            if (i == 0) path.startNewSubPath (traceXs[i], y);
            else        path.lineTo (traceXs[i], y);
        }

        // Hot ruby during compress/static (the "compressed scanline"); cools
        // back toward the normal phosphor colour as the redraw completes.
        const float heat = pulsePhase == PulseRedraw ? (1.0f - progress) : 1.0f;
        const auto hot = juce::Colour (0xffe9dfc7).interpolatedWith (juce::Colour (0xffc9853f), 0.38f);
        const auto col = t.curveColour().interpolatedWith (hot, heat);
        constexpr auto joint = juce::PathStrokeType::curved;
        constexpr auto cap   = juce::PathStrokeType::rounded;

        g.setColour (col.withAlpha (0.10f));
        g.strokePath (path, { 3.2f, joint, cap });
        g.setColour (col.withAlpha (0.95f));
        g.strokePath (path, { 1.2f, joint, cap });
    }

    void drawSlamReadout (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        if (canvasParam == nullptr)
            return;

        // No permanent riser/meter on the glass — SLAM's visual home is the
        // phosphor lift under the curve (drawResponseTrace). Only the
        // transient value text appears, while interacting. (Tyson 2026-07-11:
        // "the bar on the right is clutter".)
        const float s = slamNorm();
        const float a = pressing ? 1.0f : juce::jlimit (0.0f, 1.0f, meterAlpha);
        if (a <= 0.02f && s <= 0.001f)
            return;

        const float outDb = trench::slamOutputGainDb (s);
        const float limitPct = slamOutClip * 100.0f;
        const auto line1 = "SLAM " + juce::String (s * 100.0f, 1);
        const auto line2 = "OUT +" + juce::String (outDb, 1) + " dB  LIMIT " + juce::String (limitPct, 0) + "%";

        const float boxW = 132.0f;
        const float boxH = 30.0f;
        const float x = pressing
            ? juce::jlimit (screen.getX() + 5.0f, screen.getRight() - boxW - 5.0f, dragPos.x + 14.0f)
            : screen.getRight() - boxW - 8.0f;
        const float y = pressing
            ? juce::jlimit (screen.getY() + 5.0f, screen.getBottom() - boxH - 5.0f, dragPos.y - boxH - 8.0f)
            : screen.getY() + 8.0f;

        auto r = juce::Rectangle<float> (x, y, boxW, boxH);

        // Remove the background box and border drawing to avoid fake overlays!
        // We only draw the text on the glass.

        g.setFont (displayFont (12.5f, true));
        g.setColour (juce::Colour (0xffe7e1d3).withAlpha (0.95f * a));
        g.drawText (line1, r.removeFromTop (15.0f).reduced (6.0f, 1.0f),
                    juce::Justification::centredLeft, false);
        g.setFont (displayFont (10.5f, false));
        g.setColour (t.curveColour().withAlpha (0.86f * a));
        g.drawText (line2, r.reduced (6.0f, 0.0f), juce::Justification::centredLeft, false);
    }

    Theme t;
    juce::Path responsePath;
    std::vector<float> traceXs;
    std::vector<float> traceDbs;
    float lastCoeffs[30] = {};
    float lastBoost = -1.0f;
    double lastSr = 0.0;
    bool haveCurve = false;

    // SLAM on-screen (canvas) control
    juce::RangedAudioParameter* canvasParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> canvasAtt;
    float canvasDefault = 0.0f;

    // SEED pulse state. Static/Redraw durations are the direction's exact
    // numbers (~80ms/~100ms); Compress has no given duration, 60ms is a
    // reasonable choice, not a measured constant.
    enum PulsePhase { PulseIdle, PulseCompress, PulseStatic, PulseRedraw };
    PulsePhase pulsePhase = PulseIdle;
    double pulseElapsedMs = 0.0;
    std::vector<float> pulseOldDbs;
    mutable juce::Random pulseRng;
    static constexpr double kPulseCompressMs = 60.0;
    static constexpr double kPulseStaticMs   = 80.0;
    static constexpr double kPulseRedrawMs   = 100.0;

    void timerCallback() override
    {
        meterAlpha = juce::jmax (0.0f, meterAlpha - 0.05f);


        if (pulsePhase != PulseIdle)
        {
            pulseElapsedMs += 30.0;
            if (pulsePhase == PulseCompress && pulseElapsedMs >= kPulseCompressMs)
            {
                pulsePhase = PulseStatic;
                pulseElapsedMs = 0.0;
            }
            else if (pulsePhase == PulseStatic && pulseElapsedMs >= kPulseStaticMs)
            {
                pulsePhase = PulseRedraw;
                pulseElapsedMs = 0.0;
            }
            else if (pulsePhase == PulseRedraw && pulseElapsedMs >= kPulseRedrawMs)
            {
                pulsePhase = PulseIdle;
                pulseOldDbs.clear();
            }
        }

        if (meterAlpha <= 0.01f && pulsePhase == PulseIdle)
            stopTimer();
        repaint();
    }

    bool pressing = false;
    float dragStartY = 0.0f;
    float armed = 0.0f;
    float meterAlpha = 0.0f;
    float slamOutClip = 0.0f;
    juce::Point<float> dragPos;
    float canvasAtStart = 0.0f;
};

} // namespace trench::ui
