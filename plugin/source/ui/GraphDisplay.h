#pragma once
#include "Theme.h"
#include "../dsp/SlamStage.h"
#include "../parameters/TrenchParameters.h"
#include "BinaryData.h"
#include <juce_audio_processors/juce_audio_processors.h>
#include <cmath>
#include <complex>
#include <memory>
#include <vector>
namespace trench::ui
{
class GraphDisplay : public juce::Component,
                     public juce::SettableTooltipClient,
                     private juce::Timer
{
public:
    void playSeedPulse()
    {
        if (traceXs.empty() || traceDbs.size() != traceXs.size())
            return;
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
        setTitle ("SLAM");
        setDescription ("SLAM Mackie desk drive; drag up for more pressure. Drag sideways to resample into the host.");
        setTooltip ("SLAM — Mackie desk drive after the body; drag UP for more, "
                    "Shift-drag for fine, scroll to adjust, double-click to reset.  "
                    "Drag SIDEWAYS to resample what you just heard into your DAW.");
        setMouseCursor (juce::MouseCursor::UpDownResizeCursor);
        canvasParam = apvts.getParameter (canvasParamId);
        if (canvasParam != nullptr)
        {
            canvasAtt = std::make_unique<juce::ParameterAttachment> (*canvasParam, [this] (float)
            {
                meterAlpha = 1.0f;
                if (! pressing) startTimer (30);
                repaint();
            });
            canvasDefault = canvasParam->getDefaultValue();
            setMouseCursor (juce::MouseCursor::UpDownResizeCursor);
        }
        qParam     = apvts.getParameter (ParamID::q);
        chewParam  = apvts.getParameter (ParamID::chew);
        if (chewParam != nullptr)
        {
            chewAtt = std::make_unique<juce::ParameterAttachment> (*chewParam, [this] (float)
            {
                startTimer (30);
                repaint();
            });
        }
        setInterceptsMouseClicks (canvasParam != nullptr, false);
    }
    void showAmountCue (float norm)
    {
        announce ("MIX " + juce::String (juce::roundToInt (
                      juce::jlimit (0.0f, 1.0f, norm) * 100.0f)) + "%");
    }
    void announce (const juce::String& text)
    {
        amountCueText = text;
        amountCueAlpha = 1.0f;
        startTimer (30);
        repaint();
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
    void updateFromCoeffs (const float coeffs[30], float boost, double sr)
    {
        const float qNow = qParam != nullptr ? qParam->getValue() : 0.0f;
        bool same = juce::approximatelyEqual (sr, lastSr) && juce::approximatelyEqual (boost, lastBoost)
                    && juce::approximatelyEqual (qNow, lastQ);
        lastQ = qNow;
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
        const int N = juce::jmax (768, juce::roundToInt (plot.getWidth() * 4.0f));
        juce::Path path;
        bool started = false;
        float prevX = 0.0f, prevY = 0.0f;
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

            const double yt = juce::jlimit (0.015, 0.985, (dbTop - db) / (dbTop - dbBot));
            const float x = plot.getX() + (float) frac * plot.getWidth();
            const float y = plot.getY() + (float) yt * plot.getHeight();
            if (! started)
            {
                path.startNewSubPath (x, y);
                started = true;
            }
            else
            {
                // smooth spline through midpoints — continuous laser trace, no segment kinks
                path.quadraticTo (prevX, prevY, (prevX + x) * 0.5f, (prevY + y) * 0.5f);
            }
            prevX = x;
            prevY = y;
            traceXs.push_back (x);
            traceDbs.push_back ((float) db);
        }
        responsePath = std::move (path);
        if (! isTimerRunning()) startTimer (30);
        repaint();
    }
    void mouseEnter (const juce::MouseEvent&) override
    {
        hovering = true;
        repaint();
    }
    void mouseExit (const juce::MouseEvent&) override
    {
        hovering = false;
        repaint();
    }
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
        const float scale = e.mods.isShiftDown() ? 0.25f : 1.0f;
        const float next = juce::jlimit (0.0f, 1.0f,
                                         canvasAtStart - ((e.position.y - dragStartY) / h) * scale);
        canvasAtt->setValueAsPartOfGesture (canvasParam->convertFrom0to1 (next));
        repaint();
    }
    void mouseUp (const juce::MouseEvent&) override
    {
        if (canvasParam == nullptr) return;
        pressing = false;
        if (canvasAtt != nullptr) canvasAtt->endGesture();
        startTimer (30);
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
        constexpr float reveal = 1.15f;
        const auto glass = aperture.reduced (reveal);
        const float glassRad = rad - reveal;
        {
            g.setColour (juce::Colour (0xff14171a));
            g.fillRoundedRectangle (aperture, rad);
            g.setColour (juce::Colours::black.withAlpha (0.72f));
            g.drawRoundedRectangle (aperture.reduced (0.35f), rad - 0.25f, 0.75f);
        }
        {
            juce::Path face;
            face.addRoundedRectangle (glass, glassRad);
            juce::Graphics::ScopedSaveState save (g);
            g.reduceClipRegion (face);
            if (displayPlate.isNull())
                displayPlate = juce::ImageCache::getFromMemory (BinaryData::display_bitmap4613_png,
                                                                BinaryData::display_bitmap4613_pngSize);
            g.setImageResamplingQuality (juce::Graphics::highResamplingQuality);
            g.drawImage (displayPlate, glass, juce::RectanglePlacement::stretchToFit, false);
            drawResponseTrace (g);
            drawSlamCeiling (g, glass);
            drawSlamHoverCue (g, glass);
            if (amountCueAlpha > 0.01f)
            {
                g.setFont (telemetryFont (9.8f, false));
                g.setColour (juce::Colour (0xffcfe8de).withAlpha (0.94f * amountCueAlpha));
                g.drawText (amountCueText,
                            juce::Rectangle<float> (glass.getX() + 8.0f, glass.getY() + 4.0f, 190.0f, 14.0f),
                            juce::Justification::centredLeft, false);
            }
            juce::Path glossPath;
            glossPath.startNewSubPath (glass.getX(), glass.getY());
            glossPath.lineTo (glass.getRight(), glass.getY());
            glossPath.lineTo (glass.getRight(), glass.getY() + glass.getHeight() * 0.45f);
            glossPath.quadraticTo (glass.getCentreX(), glass.getY() + glass.getHeight() * 0.54f,
                                   glass.getX(), glass.getY() + glass.getHeight() * 0.45f);
            glossPath.closeSubPath();
            // MATTE ink-black glass: only a whisper of sheen. A glossy pane fights
            // the "deep, non-reflective" read and puts a bright wash where the
            // curve needs maximum contrast.
            juce::ColourGradient glossGrad (juce::Colours::white.withAlpha (0.0f), 0.0f, glass.getY(),
                                            juce::Colours::white.withAlpha (0.0f),  0.0f, glass.getY() + glass.getHeight() * 0.50f, false);
            g.setGradientFill (glossGrad);
            g.fillPath (glossPath);
            // Darker screen corners - the pane reads as curved glass, not a flat card.
            juce::ColourGradient vig (juce::Colours::transparentBlack,
                                      glass.getCentreX(), glass.getCentreY(),
                                      juce::Colours::black.withAlpha (0.0f),
                                      glass.getX(), glass.getY(), true);
            vig.addColour (0.58, juce::Colours::transparentBlack);
            g.setGradientFill (vig);
            g.fillRect (glass);
            // Stronger inner shadow around the bezel: deeper at the top lip, plus
            // returns down the sides and along the floor so the screen sits IN the plate.
            juce::ColourGradient lip (juce::Colours::black.withAlpha (0.16f), 0.0f, glass.getY(),
                                      juce::Colours::transparentBlack, 0.0f, glass.getY() + 4.0f, false);
            g.setGradientFill (lip);
            g.fillRect (glass.getX(), glass.getY(), glass.getWidth(), 4.0f);
            juce::ColourGradient sideL (juce::Colours::black.withAlpha (0.10f), glass.getX(), 0.0f,
                                        juce::Colours::transparentBlack, glass.getX() + 7.0f, 0.0f, false);
            g.setGradientFill (sideL);
            g.fillRect (glass.getX(), glass.getY(), 7.0f, glass.getHeight());
            juce::ColourGradient sideR (juce::Colours::transparentBlack, glass.getRight() - 7.0f, 0.0f,
                                        juce::Colours::black.withAlpha (0.30f), glass.getRight(), 0.0f, false);
            g.setGradientFill (sideR);
            g.fillRect (glass.getRight() - 7.0f, glass.getY(), 7.0f, glass.getHeight());
            juce::ColourGradient floorSh (juce::Colours::transparentBlack, 0.0f, glass.getBottom() - 8.0f,
                                          juce::Colours::black.withAlpha (0.10f), 0.0f, glass.getBottom(), false);
            g.setGradientFill (floorSh);
            g.fillRect (glass.getX(), glass.getBottom() - 8.0f, glass.getWidth(), 8.0f);
        }
        if (hovering && ! pressing)
        {
            // Discoverability cue: the screen quietly advertises that it can be
            // dragged out. Costs no permanent pixels.
            g.setColour (t.curveColour().withAlpha (0.20f));
            g.drawRoundedRectangle (glass.reduced (0.6f), glassRad, 0.9f);
            // No instruction text painted on the artwork - it collided with the
            // trace and clipped at the edge. The edge highlight says "interactive";
            // the tooltip says what it does. That is what tooltips are for, and it
            // costs no permanent real estate.
        }
        g.setColour (juce::Colours::black.withAlpha (0.80f));
        g.drawRoundedRectangle (glass, glassRad, 1.1f);
    }
private:
    juce::Rectangle<float> plotBounds() const { return getLocalBounds().toFloat().reduced (6.0f, 5.0f); }
    void drawFailingGlassBed (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        const auto glassBase = t.phosphor();
        juce::ColourGradient smoke (glassBase.brighter (0.06f), 0.0f, screen.getY(),
                                    glassBase.darker (0.16f), 0.0f, screen.getBottom(), false);
        smoke.addColour (0.46, glassBase.darker (0.04f));
        g.setGradientFill (smoke);
        g.fillRect (screen);
        juce::ColourGradient dead (juce::Colours::black.withAlpha (0.18f),
                                   screen.getX(), screen.getY(),
                                    juce::Colours::transparentBlack,
                                    screen.getRight(), screen.getBottom(), false);
        dead.addColour (0.58, juce::Colour (0xff302a23).withAlpha (0.08f));
        g.setGradientFill (dead);
        g.fillRect (screen);
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
    void drawLogGrid (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        static constexpr float rx[] = { 0.0258f, 0.0710f, 0.1097f, 0.1355f, 0.1613f, 0.1806f,
                                        0.2000f, 0.2194f, 0.3290f, 0.3935f, 0.4387f, 0.4774f,
                                        0.5032f, 0.5290f, 0.5484f, 0.5677f, 0.5871f, 0.6968f,
                                        0.7613f, 0.8065f, 0.8452f, 0.8710f, 0.8968f, 0.9226f,
                                        0.9419f, 0.9613f };
        static constexpr float rs[] = { 0.98f, 0.99f, 1.0f, 1.0f, 1.0f, 1.0f,
                                        1.0f,  0.99f, 0.98f, 0.95f, 0.84f, 0.95f,
                                        0.89f, 0.84f, 0.79f, 0.71f, 0.71f, 0.80f,
                                        0.71f, 0.77f, 0.67f, 0.67f, 0.68f, 0.68f,
                                        0.69f, 0.68f };
        static constexpr float ry[] = { 0.2206f, 0.4853f, 0.7500f };
        static constexpr float ws[] = { 1.0f, 0.96f, 0.74f };
        // Grid is its own token (Dusty Blue Grey), not the highlight - it belongs
        // to the UI/telemetry family, not the signal family.
        const auto ink = t.dashed();
        for (size_t i = 0; i < std::size (rx); ++i)
        {
            const float x = screen.getX() + rx[i] * screen.getWidth();
            g.setColour (ink.withAlpha (0.26f + 0.40f * rs[i]));
            g.drawLine (x, screen.getY(), x, screen.getBottom(), 0.8f);
        }
        for (size_t i = 0; i < std::size (ry); ++i)
        {
            const float y = screen.getY() + ry[i] * screen.getHeight();
            g.setColour (ink.withAlpha (0.24f + 0.36f * ws[i]));
            g.drawLine (screen.getX(), y, screen.getRight(), y, 0.7f);
        }
    }
    float slamNorm() const noexcept
    {
        if (canvasParam == nullptr)
            return 0.0f;
        return juce::jlimit (0.0f, 1.0f, canvasParam->getValue());
    }
    juce::Colour responseColour() const
    {
        return t.curveColour();
    }
    void drawResponseTrace (juce::Graphics& g) const
    {
        if (pulsePhase != PulseIdle)
        {
            drawSeedPulseTrace (g);
            return;
        }
        const auto phos = responseColour();
        const auto plot = plotBounds();
        if (traceXs.empty() || traceXs.size() != traceDbs.size() || plot.isEmpty())
        {
            if (! responsePath.isEmpty())
            {
                g.setColour (phos.withAlpha (0.15f));
                g.strokePath (responsePath, { 3.5f, juce::PathStrokeType::curved,
                                              juce::PathStrokeType::rounded });
                g.setColour (phos);
                g.strokePath (responsePath, { 1.5f, juce::PathStrokeType::curved,
                                              juce::PathStrokeType::rounded });
            }
            return;
        }
        constexpr auto joint = juce::PathStrokeType::curved;
        constexpr auto cap   = juce::PathStrokeType::rounded;
        // laser trace: soft aura pass behind a sharp 1.5f line, full-res AA
        // (the half-res render-and-stretch pass is what made it fuzzy).
        // Peaks stay natural needle points — no crosshair marks.
        g.setOpacity (1.0f);
        // NO bloom. The curve is a solid line on matte ink-black glass - any glow
        // reads as a screen effect and breaks the "clean, contained" read.
        const float chew = chewAmount();
        if (chew > 0.004f)
        {
            // CHEW does not flatten the resonance: the dynamic pole radius makes
            // the peak bloom and wander. The visual perturbation is weighted by
            // how far above unity the response is, so
            // the passband stays glass-smooth and only the poles misbehave.
            const double dbTop = t.curveDbTop(), dbBot = t.curveDbBottom();
            const auto plotR = plotBounds();
            const size_t N = traceXs.size();
            juce::Path dirty;
            bool started = false;
            float px = 0.0f, py = 0.0f;
            for (size_t i = 0; i < N; ++i)
            {
                const double db = traceDbs[i];
                const float heat = juce::jlimit (0.0f, 1.0f, (float) (db - 2.0) / 20.0f);
                float dev = 0.0f;
                if (heat > 0.0f)
                {
                    const float ph = (float) i * 0.9f + shakePhase;
                    // two incommensurate rates = aliasing chatter, not a clean wobble
                    dev = (std::sin (ph) * 0.6f + std::sin (ph * 2.37f + 1.7f) * 0.4f)
                          * heat * heat * chew * 26.0f;
                }
                const double yt = juce::jlimit (0.015, 0.985, (dbTop - (db + dev)) / (dbTop - dbBot));
                const float x = plotR.getX() + ((float) i / (float) juce::jmax<size_t> (1, N - 1)) * plotR.getWidth();
                const float y = plotR.getY() + (float) yt * plotR.getHeight();
                if (! started) { dirty.startNewSubPath (x, y); started = true; }
                else dirty.quadraticTo (px, py, (px + x) * 0.5f, (py + y) * 0.5f);
                px = x; py = y;
            }
            g.setColour (phos.withAlpha (0.15f));
            g.strokePath (dirty, { 4.2f, joint, cap });
            g.setColour (phos);
            g.strokePath (dirty, { 2.2f, joint, cap });
            return;
        }
        g.setColour (phos.withAlpha (0.15f));
        g.strokePath (responsePath, { 4.2f, joint, cap });
        g.setColour (phos);
        g.strokePath (responsePath, { 2.2f, joint, cap });
    }
    float chewAmount() const noexcept
    {
        return chewParam != nullptr ? juce::jlimit (0.0f, 1.0f, chewParam->getValue()) : 0.0f;
    }
    void drawSlamHoverCue (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        const float chew = chewAmount();
        const bool chewLive = chew > 0.012f;
        const bool slamShown = hovering || pressing;
        if ((! slamShown && ! chewLive) || canvasParam == nullptr)
            return;
        const float compact = juce::jlimit (0.86f, 1.0f, getWidth() / 270.0f);
        const auto slot = [&] (int row)
        {
            return juce::Rectangle<float> (screen.getRight() - 101.0f * compact,
                                           screen.getY() + (4.0f + 12.0f * (float) row) * compact,
                                           93.0f * compact, 16.0f * compact)
                       .withTrimmedRight (16.0f * compact);
        };
        const auto slamText = "SLAM +" + juce::String (trench::slamOutputGainDb (slamNorm()), 1) + " dB";
        const auto chewText = "CHEW " + juce::String (juce::roundToInt (chew * 100.0f)) + "%";
        // CHEW takes the prime slot whenever it is doing something - it is the
        // thing changing the sound. SLAM drops to second. They swap back when
        // CHEW is idle.
        const int chewRow = chewLive ? 0 : 1;
        const int slamRow = chewLive ? 1 : 0;
        g.setFont (telemetryFont (9.8f * compact, false));
        if (slamShown)
        {
            g.setColour (juce::Colour (0xffcfe8de).withAlpha (chewLive ? 0.62f : 0.94f));
            g.drawText (slamText, slot (slamRow), juce::Justification::centredRight, false);
        }
        if (chewLive)
        {
            g.setColour (t.curveColour().withAlpha (0.55f + 0.42f * juce::jlimit (0.0f, 1.0f, chew / 0.30f)));
            g.drawText (chewText, slot (chewRow), juce::Justification::centredRight, false);
        }
    }
    // SLAM is GLOBAL and terminal - an output ceiling everything presses against.
    // Drawn as a horizontal limit line, deliberately unlike CHEW's local pole shake.
    void drawSlamCeiling (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        const float s = slamNorm();
        if (s <= 0.02f)
            return;
        const auto plot = plotBounds();
        const double dbTop = t.curveDbTop(), dbBot = t.curveDbBottom();
        const double ceilDb = (double) trench::slamOutputGainDb (s);
        const double yt = juce::jlimit (0.02, 0.98, (dbTop - ceilDb) / (dbTop - dbBot));
        const float y = plot.getY() + (float) yt * plot.getHeight();
        const float a = 0.10f + 0.34f * s;
        g.setColour (t.curveColour().withAlpha (a * 0.35f));
        g.fillRect (screen.getX(), y - 1.5f, screen.getWidth(), 3.0f);
        g.setColour (t.curveColour().withAlpha (a));
        g.drawLine (screen.getX(), y, screen.getRight(), y, 0.9f);
    }

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
        float squash = 1.0f;
        float progress = 0.0f;
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
        else
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
                y += pulseRng.nextFloat() * 3.0f - 1.5f;
            if (i == 0) path.startNewSubPath (traceXs[i], y);
            else        path.lineTo (traceXs[i], y);
        }
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
    Theme t;
    mutable juce::Image displayPlate;
    juce::Path responsePath;
    std::vector<float> traceXs;
    std::vector<float> traceDbs;
    float lastCoeffs[30] = {};
    float lastBoost = -1.0f;
    double lastSr = 0.0;
    bool haveCurve = false;
    juce::RangedAudioParameter* canvasParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> canvasAtt;
    juce::RangedAudioParameter* qParam     = nullptr;
    juce::RangedAudioParameter* chewParam  = nullptr;
    std::unique_ptr<juce::ParameterAttachment> chewAtt;
    float lastQ = -1.0f;
    float canvasDefault = 0.0f;
    enum PulsePhase { PulseIdle, PulseCompress, PulseStatic, PulseRedraw };
    PulsePhase pulsePhase = PulseIdle;
    double pulseElapsedMs = 0.0;
    std::vector<float> pulseOldDbs;
    mutable juce::Random pulseRng;
    static constexpr double kPulseCompressMs = 60.0;
    static constexpr double kPulseStaticMs   = 80.0;
    static constexpr double kPulseRedrawMs   = 100.0;
    juce::String amountCueText;
    float amountCueAlpha = 0.0f;
    float shakePhase = 0.0f;
    void timerCallback() override
    {
        shakePhase += 0.55f;
        meterAlpha = juce::jmax (0.0f, meterAlpha - 0.05f);
        amountCueAlpha = juce::jmax (0.0f, amountCueAlpha - 0.04f);
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
        const bool chewing = chewAmount() > 0.004f;
        if (! chewing && meterAlpha <= 0.01f && amountCueAlpha <= 0.01f && pulsePhase == PulseIdle)
            stopTimer();
        repaint();
    }
    bool pressing = false;
    bool hovering = false;
    float dragStartY = 0.0f;
    float meterAlpha = 0.0f;
    float slamOutClip = 0.0f;
    juce::Point<float> dragPos;
    float canvasAtStart = 0.0f;
};
}
