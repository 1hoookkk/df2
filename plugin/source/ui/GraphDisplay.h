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

// Precision-fitted smoked glass plus the live cascade response. The electronics
// may still look tired; the glass itself is an optically bonded, machined part.
//
// SLAM is a SECONDARY on-screen control (not a rail): dragging the canvas vertically
// (or the mouse wheel over the graph) drives the Mackie desk stage.  In the shipped
// route that stage is last in the chain and adds 0..+12 dB before the measured desk
// curve.  The filter response therefore never bends or clamps when SLAM changes.
//
// Preview-only: curve, nothing else. MOTION/TIME are picked and shown in
// their own compact row below the screen (MotionTimeRow) — this view never
// draws text of its own for them.
class GraphDisplay : public juce::Component,
                     public juce::SettableTooltipClient,
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
        // The glass IS the SLAM control. Keep the face clean at rest, but make
        // the gesture explicit as soon as the pointer enters the display.
        setTitle ("SLAM");
        setDescription ("SLAM Mackie desk drive; drag up for more pressure");
        setTooltip ("SLAM — Mackie desk drive after the body; drag up for more, Shift-drag for fine adjustment, scroll to adjust, double-click to reset");
        setMouseCursor (juce::MouseCursor::UpDownResizeCursor);
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
        routeParam = apvts.getParameter (ParamID::inputMode);
        if (routeParam != nullptr)
            routeAtt = std::make_unique<juce::ParameterAttachment> (*routeParam,
                                                                    [this] (float) { repaint(); });
        // The screen takes mouse input to drive SLAM (children like the [1][2]
        // pad and MOD tag sit on top and still get their own clicks).
        setInterceptsMouseClicks (canvasParam != nullptr, false);
    }

    // AMOUNT drag telemetry: the screen announces the dose (SLAM-cue voice);
    // fades out once the wheel rests.
    void showAmountCue (float norm)
    {
        announce ("AMOUNT " + juce::String (juce::roundToInt (
                      juce::jlimit (0.0f, 1.0f, norm) * 100.0f)) + "%");
    }

    // The screen's one voice (2026-07-18): every gesture announces here in the
    // same corner, same ink, same fade — time picks, verbs, preset loads.
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

        // Sample at four points per native display pixel (with a 768-point
        // floor). Narrow packed-body resonances therefore survive the small
        // 350x540 editor without changing the runtime-authoritative response.
        const int N = juce::jmax (768, juce::roundToInt (plot.getWidth() * 4.0f));
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

    // --- SLAM: vertical drag + wheel drive the Mackie stage (up = harder) -----
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
        constexpr float reveal = 1.15f;   // wells do the depth; keep the reveal thin
        const auto glass = aperture.reduced (reveal);
        const float glassRad = rad - reveal;

        // 1.95 px blackened-nickel reveal. It exposes enough of the precision
        // backing plate to separate the glass without becoming a chunky bezel.
        // It is not a chrome border or an outer shadow.
        {
            // FLAT matte bezel (reference 2026-07-18: "the bezel isn't right")
            // — one plain dark frame, no nickel gradient, no warm catch light.
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

            // The authentic E-mu display plate (BITMAP4613, 156x69): teal
            // glass gradient plus the full logarithmic ruling, blitted as the
            // curated asset itself — bed and grid in one, never redrawn.
            if (displayPlate.isNull())
                displayPlate = juce::ImageCache::getFromMemory (BinaryData::display_bitmap4613_png,
                                                                BinaryData::display_bitmap4613_pngSize);
            g.setImageResamplingQuality (juce::Graphics::highResamplingQuality);
            g.drawImage (displayPlate, glass, juce::RectanglePlacement::stretchToFit, false);

            drawResponseTrace (g);
            drawSlamHoverCue (g, glass);
            if (amountCueAlpha > 0.01f)
            {
                g.setFont (telemetryFont (9.8f, false));
                g.setColour (juce::Colour (0xffcfe8de).withAlpha (0.94f * amountCueAlpha));
                g.drawText (amountCueText,
                            juce::Rectangle<float> (glass.getX() + 8.0f, glass.getY() + 4.0f, 190.0f, 14.0f),
                            juce::Justification::centredLeft, false);
            }

            // Subtle, curved, semi-transparent white gradient across the top half of the screen
            // to simulate a curved glass or plastic screen cover reflecting overhead studio lights.
            juce::Path glossPath;
            glossPath.startNewSubPath (glass.getX(), glass.getY());
            glossPath.lineTo (glass.getRight(), glass.getY());
            glossPath.lineTo (glass.getRight(), glass.getY() + glass.getHeight() * 0.45f);
            glossPath.quadraticTo (glass.getCentreX(), glass.getY() + glass.getHeight() * 0.54f,
                                   glass.getX(), glass.getY() + glass.getHeight() * 0.45f);
            glossPath.closeSubPath();

            juce::ColourGradient glossGrad (juce::Colours::white.withAlpha (0.12f), 0.0f, glass.getY(),
                                            juce::Colours::white.withAlpha (0.0f),  0.0f, glass.getY() + glass.getHeight() * 0.50f, false);
            g.setGradientFill (glossGrad);
            g.fillPath (glossPath);

            juce::ColourGradient vig (juce::Colours::transparentBlack,
                                      glass.getCentreX(), glass.getCentreY(),
                                      juce::Colours::black.withAlpha (0.13f),
                                      glass.getX(), glass.getY(), true);
            vig.addColour (0.73, juce::Colours::transparentBlack);
            g.setGradientFill (vig);
            g.fillRect (glass);

            // Pane thickness: the reveal casts a short shadow onto the recessed
            // glass from above — the depth cue the flat vignette can't give.
            juce::ColourGradient lip (juce::Colours::black.withAlpha (0.26f), 0.0f, glass.getY(),
                                      juce::Colours::transparentBlack, 0.0f, glass.getY() + 7.0f, false);
            g.setGradientFill (lip);
            g.fillRect (glass.getX(), glass.getY(), glass.getWidth(), 7.0f);
        }

        // Hairline inner seam: the glass meets the reveal with zero visible lift.
        g.setColour (juce::Colours::black.withAlpha (0.68f));
        g.drawRoundedRectangle (glass, glassRad, 0.75f);
    }

private:
    juce::Rectangle<float> plotBounds() const { return getLocalBounds().toFloat().reduced (6.0f, 5.0f); }

    void drawFailingGlassBed (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        // The glass bed derives from the phosphor token (sage LCD): slightly
        // lit at the crown, settling gently toward the floor. Opaque enough to
        // read as its own fitted material.
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

    // Ruled log grid: the REAL X3-era ruling, measured from the checked-in
    // display_log_grid.png (column/row delta peaks — 26 log-spaced frequency
    // rules in three decade clusters + 3 level rules, with per-rule ink
    // strength). Drawn as clean 1px ink at the measured fractions; per-pixel
    // extraction of the faint source read as scratches at 350px.
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

        const auto ink = t.dashed();
        for (size_t i = 0; i < std::size (rx); ++i)
        {
            const float x = screen.getX() + rx[i] * screen.getWidth();
            g.setColour (ink.withAlpha (0.12f + 0.30f * rs[i]));
            g.drawLine (x, screen.getY(), x, screen.getBottom(), 0.8f);
        }
        for (size_t i = 0; i < std::size (ry); ++i)
        {
            const float y = screen.getY() + ry[i] * screen.getHeight();
            g.setColour (ink.withAlpha (0.10f + 0.26f * ws[i]));
            g.drawLine (screen.getX(), y, screen.getRight(), y, 0.7f);
        }
    }

    float slamNorm() const noexcept
    {
        if (canvasParam == nullptr)
            return 0.0f;
        return juce::jlimit (0.0f, 1.0f, canvasParam->getValue());
    }

    // The trace is only the packed/runtime-decoded body response. SLAM is a
    // downstream nonlinear audio stage and must not alter this geometry.
    juce::Colour responseColour() const
    {
        return t.curveColour();
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

        // The curve is the true current six-stage body response. SLAM is a
        // separate nonlinear audio stage, so neither its parameter nor its
        // signal meter may reshape or relight the response plot.
        const auto phos = responseColour();

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

        // High-fidelity instrument trace. The path retains sub-pixel geometry;
        // material character comes from restrained optical passes, never by
        // quantising or falsifying the packed/runtime response.
        const double dbTop = t.curveDbTop(), dbBot = t.curveDbBottom();
        const size_t N = traceXs.size();
        auto yOf = [&] (size_t i)
        {
            const double yt = juce::jlimit (-0.06, 1.06, (dbTop - traceDbs[i]) / (dbTop - dbBot));
            return plot.getY() + (float) yt * plot.getHeight();
        };

        constexpr auto joint = juce::PathStrokeType::curved;
        constexpr auto cap   = juce::PathStrokeType::rounded;
        // CHUNKY instrument stroke (reference 2026-07-18): a heavy light line
        // with real presence — the curve IS the display's content. No fill.
        constexpr float lw = 2.6f;
        g.setColour (phos.withAlpha (0.22f));
        g.strokePath (responsePath, { lw + 1.6f, joint, cap });
        g.setColour (phos);
        g.strokePath (responsePath, { lw, joint, cap });

        // Peak crosses (the reference's + ticks): small markers on the mode
        // crests — light ink on the dark teal plate, clinical annotation not sparkle.
        {
            g.setColour (juce::Colour (0xffcfe8de).withAlpha (0.75f));
            int marks = 0;
            const size_t r = juce::jmax ((size_t) 2, N / (size_t) 95);
            for (size_t i = r; i + r < N && marks < 8; ++i)
            {
                const double d = traceDbs[i];
                if (d > traceDbs[i-1] && d >= traceDbs[i+1]
                    && d - juce::jmin (traceDbs[i-r], traceDbs[i+r]) > 2.5)
                {
                    const float x = traceXs[i], y = yOf (i) - 4.0f;
                    g.drawLine (x - 3.0f, y, x + 3.0f, y, 1.4f);
                    g.drawLine (x, y - 3.0f, x, y + 3.0f, 1.4f);
                    ++marks;
                    i += r * 2;                              // one cross per crest
                }
            }
        }
    }

    // (drawDisplayDropouts removed 2026-07-18: the deliberate dropout/failure
    // lines were a retro-crunch prop — banned with the aliased digits.)

    void drawSlamHoverCue (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        if ((! hovering && ! pressing) || canvasParam == nullptr)
            return;

        // This component is ~270 px wide in the native 350x540 editor.  The
        // previous 346 px reference width shrank an 8.5 px cue to ~6.7 px at
        // the size users actually see.  Author the affordance at true 1x and
        // only compact it if a future layout makes the screen genuinely smaller.
        const float compact = juce::jlimit (0.86f, 1.0f, getWidth() / 270.0f);
        const auto cue = juce::Rectangle<float> (screen.getRight() - 101.0f * compact,
                                                 screen.getY() + 4.0f * compact,
                                                 93.0f * compact, 16.0f * compact);
        const auto textArea = cue.withTrimmedRight (16.0f * compact);
        g.setFont (telemetryFont (9.8f * compact, false));
        g.setColour (juce::Colour (0xffcfe8de).withAlpha (0.94f));
        const bool intoFilter = routeParam != nullptr && routeParam->getValue() > 0.5f;
        const auto value = intoFilter
                             ? "SLAM IN " + juce::String (juce::roundToInt (slamNorm() * 100.0f)) + "%"
                             : "SLAM +" + juce::String (trench::slamOutputGainDb (slamNorm()), 1) + " dB";
        g.drawText (value, textArea, juce::Justification::centredRight, false);

        // SLAM is monotonic drive, not a bipolar modulation: one large upward
        // arrow says exactly what the gesture does. Its strength follows the
        // real post-SLAM output hotness meter; the filter curve stays untouched.
        const float cx = cue.getRight() - 6.0f * compact;
        const float cy = cue.getCentreY();
        const float d = 3.8f * compact;
        const float tipY = cy - 5.2f * compact;
        const float hot = juce::jlimit (0.0f, 1.0f, slamOutClip);
        g.setColour (t.curveColour().withAlpha (0.68f + 0.30f * hot));
        g.drawLine (cx, cy + 5.0f * compact, cx, tipY, 1.25f * compact);
        g.drawLine (cx - d, tipY + 3.5f * compact, cx, tipY, 1.25f * compact);
        g.drawLine (cx, tipY, cx + d, tipY + 3.5f * compact, 1.25f * compact);
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

    Theme t;
    mutable juce::Image displayPlate;
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
    juce::RangedAudioParameter* routeParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> routeAtt;
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

    juce::String amountCueText;
    float amountCueAlpha = 0.0f;

    void timerCallback() override
    {
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

        if (meterAlpha <= 0.01f && amountCueAlpha <= 0.01f && pulsePhase == PulseIdle)
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

} // namespace trench::ui
