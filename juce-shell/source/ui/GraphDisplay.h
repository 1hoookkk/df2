#pragma once

#include "Theme.h"
#include "../dsp/SlamStage.h"
#include "../parameters/TrenchParameters.h"
#include "../SmartMotion.h"

#include <juce_audio_processors/juce_audio_processors.h>

#include <cmath>
#include <complex>
#include <functional>
#include <memory>
#include <vector>

namespace trench::ui
{

// The recessed screen: plain dark wine glass plus the live cascade response
// curve as a rose hairline that hardens toward a
// hotter rose-white output read as SLAM rises. The faceplate,
// rollers, readouts and TYPE selector are LOCKED — this view only owns the screen.
//
// SLAM is a SECONDARY on-screen control (not a rail): dragging the canvas vertically
// (or the mouse wheel over the graph) drives SLAM/input-clip, with a transient
// "SLAM xx.x" overlay. Up = push harder into it. Default is the parameter's own.
class GraphDisplay : public juce::Component,
                     private juce::Timer
{
public:
    GraphDisplay (juce::Image grid, const Theme& theme,
                  juce::AudioProcessorValueTreeState& apvts, const juce::String& canvasParamId)
        : gridImage (std::move (grid)), t (theme)
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
        motionOnParamForTiles = apvts.getParameter (ParamID::motionOn);
        motionTileParamForTiles = apvts.getParameter (ParamID::motionTile);
        // The screen takes mouse input to drive SLAM (children like the [1][2]
        // pad and MOD tag sit on top and still get their own clicks).
        setInterceptsMouseClicks (canvasParam != nullptr, false);
    }

    // Set by PluginEditor: fires (true) the moment the screen leaves Curve
    // (so ModulateTag/FiveDTag can hide — they'd otherwise sit visually on
    // top of the grid) and (false) once it's back to Curve.
    std::function<void (bool)> onScreenModeChanged;

    // Called by ModulateTag::onRequestGrid. Starts the CRT-collapse; the
    // grid itself appears once the collapse finishes (see timerCallback).
    void openTileGrid()
    {
        if (screenMode != ScreenMode::Curve)
            return;
        screenMode = ScreenMode::Collapsing;
        transitionProgress = 0.0f;
        startTimer (16); // ~60 fps
        if (onScreenModeChanged) onScreenModeChanged (true);
    }

    void setMotionState (bool active, int step, float amount) noexcept
    {
        const int s = juce::jlimit (0, 15, step & 15);
        const float a = juce::jlimit (0.0f, 1.0f, amount);
        if (motionActive == active && motionStep == s && juce::approximatelyEqual (motionAmount, a))
            return;
        motionActive = active; motionStep = s; motionAmount = a;
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
            const double yt = juce::jlimit (-0.06, 1.06, (dbTop - db) / (dbTop - dbBot)); // clip off-edge, no flat-top clamp
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
        if (screenMode == ScreenMode::Grid)
        {
            tileTapped (tileIndexAt (e.position));
            return;
        }
        if (screenMode != ScreenMode::Curve)
            return; // mid-transition: ignore input
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
        if (screenMode != ScreenMode::Curve) return;
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
        if (screenMode != ScreenMode::Curve) return;
        if (canvasParam == nullptr) return;
        pressing = false;
        if (canvasAtt != nullptr) canvasAtt->endGesture();
        startTimer (30);   // let the meter fade out slowly
        repaint();
    }

    void mouseDoubleClick (const juce::MouseEvent&) override
    {
        if (screenMode != ScreenMode::Curve) return;
        if (canvasAtt != nullptr) canvasAtt->setValueAsCompleteGesture (canvasDefault);
    }

    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w) override
    {
        if (screenMode != ScreenMode::Curve) return;
        if (canvasParam == nullptr || canvasAtt == nullptr) return;
        const float next = juce::jlimit (0.0f, 1.0f, canvasParam->getValue() + w.deltaY * 0.08f);
        canvasAtt->setValueAsCompleteGesture (canvasParam->convertFrom0to1 (next));
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const float rad = 9.0f;
        const auto screen = getLocalBounds().toFloat();

        juce::Path face;
        face.addRoundedRectangle (screen, rad);
        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (face);

        // DO NOT paint any background over the baked burgundy glass of the faceplate!
        // The glass must stay quiet and show the panel art's own texture.
        armed = canvasParam != nullptr
                    ? juce::jlimit (0.0f, 1.0f, (canvasParam->getValue() - 0.15f) / 0.60f)
                    : 0.0f;

        if (screenMode == ScreenMode::Curve)
        {
            drawResponseTrace (g);
            // Motion status bar/LED RETIRED (Tyson: "what is that stupid bar and
            // dot") — the lit Modulation tag is the ON indicator; the glass stays quiet.
            drawSlamReadout (g, screen);
            // No drawn edge either — the art's own bezel carries the seating.
            return;
        }

        // Collapsing/Expanding: vertical squeeze toward a bright horizontal
        // line (classic CRT power-off/-on), then blank at zero height.
        const float collapse = (screenMode == ScreenMode::Collapsing)
            ? transitionProgress : (1.0f - transitionProgress);
        const float lineHeight = juce::jmax (1.0f, screen.getHeight() * (1.0f - collapse));
        const auto squeezed = screen.withSizeKeepingCentre (screen.getWidth(), lineHeight);

        juce::Graphics::ScopedSaveState squeezeSave (g);
        g.reduceClipRegion (squeezed.toNearestInt());

        if (screenMode == ScreenMode::Grid || collapse < 0.98f)
        {
            if (screenMode == ScreenMode::Grid)
                drawTileGrid (g, screen);
            else
                drawResponseTrace (g); // curve visible through the still-open slit
        }

        // Hot phosphor line at the collapsing edge.
        g.setColour (juce::Colour (0xfffff7fa).withAlpha (juce::jlimit (0.0f, 1.0f, collapse) * 0.9f));
        g.fillRect (squeezed.withHeight (juce::jmin (2.0f, squeezed.getHeight())).withCentre (squeezed.getCentre()));
    }

private:
    juce::Rectangle<float> plotBounds() const { return getLocalBounds().toFloat().reduced (6.0f, 5.0f); }

    // 2x2 grid: 0=Riser (top-left), 1=Breathe (top-right),
    //           2=Adlib Chop (bottom-left), 3=Wobble (bottom-right).
    int tileIndexAt (juce::Point<float> p) const
    {
        const auto plot = plotBounds();
        if (! plot.contains (p))
            return -1;
        const int col = (p.x < plot.getCentreX()) ? 0 : 1;
        const int row = (p.y < plot.getCentreY()) ? 0 : 1;
        return row * 2 + col;
    }

    juce::Rectangle<float> tileBounds (int index) const
    {
        const auto plot = plotBounds();
        const float w = plot.getWidth() * 0.5f;
        const float h = plot.getHeight() * 0.5f;
        const int col = index % 2;
        const int row = index / 2;
        return { plot.getX() + col * w, plot.getY() + row * h, w, h };
    }

    void tileTapped (int index)
    {
        if (index < 0 || index > 3 || motionOnParamForTiles == nullptr || motionTileParamForTiles == nullptr)
        {
            screenMode = ScreenMode::Expanding;
            transitionProgress = 0.0f;
            startTimer (16);
            return;
        }

        const bool alreadyArmed = motionOnParamForTiles->getValue() > 0.5f;
        const int currentTile = juce::roundToInt (motionTileParamForTiles->convertFrom0to1 (motionTileParamForTiles->getValue()));

        if (alreadyArmed && currentTile == index)
        {
            motionOnParamForTiles->setValueNotifyingHost (0.0f); // off
        }
        else
        {
            motionTileParamForTiles->setValueNotifyingHost (motionTileParamForTiles->convertTo0to1 ((float) index));
            motionOnParamForTiles->setValueNotifyingHost (1.0f); // on
        }

        screenMode = ScreenMode::Expanding;
        transitionProgress = 0.0f;
        startTimer (16);
    }

    // One glyph path per tile, drawn compact/centered so every trace has the
    // same visual mass regardless of shape.
    static juce::Path glyphPathFor (int index, juce::Rectangle<float> glyph)
    {
        juce::Path p;
        switch (index)
        {
            case 0: // Riser: ascending line
                p.startNewSubPath (glyph.getBottomLeft());
                p.lineTo (glyph.getTopRight());
                break;
            case 1: // Breathe: single hump
                p.startNewSubPath (glyph.getBottomLeft());
                p.quadraticTo (glyph.getCentreX(), glyph.getY(), glyph.getBottomRight().x, glyph.getBottomRight().y);
                break;
            case 2: // Adlib Chop: jagged pulse
                p.startNewSubPath (glyph.getX(), glyph.getBottom());
                p.lineTo (glyph.getX() + glyph.getWidth() * 0.25f, glyph.getY());
                p.lineTo (glyph.getX() + glyph.getWidth() * 0.5f, glyph.getBottom());
                p.lineTo (glyph.getX() + glyph.getWidth() * 0.75f, glyph.getY());
                p.lineTo (glyph.getRight(), glyph.getBottom());
                break;
            default: // Wobble: random zigzag
                p.startNewSubPath (glyph.getX(), glyph.getCentreY());
                p.lineTo (glyph.getX() + glyph.getWidth() * 0.3f, glyph.getY());
                p.lineTo (glyph.getX() + glyph.getWidth() * 0.6f, glyph.getBottom());
                p.lineTo (glyph.getRight(), glyph.getCentreY() - glyph.getHeight() * 0.2f);
                break;
        }
        return p;
    }

    // Four engraved traces on quiet glass — same phosphor family as the main
    // response curve (drawResponseTrace), not painted cards. A thin crosshair
    // divides the quadrants instead of four separate tile "boxes", so the
    // grid reads as one etched surface rather than stacked UI panels. The
    // selected tile switches to the same amber the Modulation lamp uses when
    // lit — one unmistakable "this is armed" cue instead of an alpha bump.
    void drawTileGrid (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        juce::ignoreUnused (screen);
        static constexpr const char* kNames[4] = { "RISER", "BREATHE", "ADLIB CHOP", "WOBBLE" };
        const int activeTile = (motionOnParamForTiles != nullptr && motionOnParamForTiles->getValue() > 0.5f
                                 && motionTileParamForTiles != nullptr)
            ? juce::roundToInt (motionTileParamForTiles->convertFrom0to1 (motionTileParamForTiles->getValue()))
            : -1;

        const auto plot = plotBounds();
        constexpr auto joint = juce::PathStrokeType::curved;
        constexpr auto cap   = juce::PathStrokeType::rounded;

        // Crosshair graticule — quiet divider, not a set of cards.
        g.setColour (kInk.withAlpha (0.55f));
        g.drawLine (plot.getCentreX(), plot.getY() + 4.0f, plot.getCentreX(), plot.getBottom() - 4.0f, 1.0f);
        g.drawLine (plot.getX() + 4.0f, plot.getCentreY(), plot.getRight() - 4.0f, plot.getCentreY(), 1.0f);
        g.setColour (t.curveColour().withAlpha (0.12f));
        g.drawLine (plot.getCentreX(), plot.getY() + 4.0f, plot.getCentreX(), plot.getBottom() - 4.0f, 0.6f);
        g.drawLine (plot.getX() + 4.0f, plot.getCentreY(), plot.getRight() - 4.0f, plot.getCentreY(), 0.6f);

        for (int i = 0; i < 4; ++i)
        {
            const auto r = tileBounds (i).reduced (10.0f);
            const bool lit = (i == activeTile);

            const auto glyphArea = r.withTrimmedBottom (18.0f)
                                    .reduced (r.getWidth() * 0.24f, r.getHeight() * 0.20f);
            const auto p = glyphPathFor (i, glyphArea);

            const auto phos = lit ? t.amber() : t.curveColour();
            const float glow = lit ? 1.0f : 0.4f;

            // Same multi-pass phosphor build as the main curve: outer glow,
            // inner glow, dark bed, hot line, hot centre — this is what makes
            // it read as an engraved trace instead of an SVG stroke.
            g.setColour (phos.withAlpha (0.10f * glow));
            g.strokePath (p, { 6.0f, joint, cap });
            g.setColour (phos.withAlpha (0.22f * glow));
            g.strokePath (p, { 3.2f, joint, cap });
            g.setColour (kInk.withAlpha (0.45f));
            g.strokePath (p, { 2.2f, joint, cap });
            g.setColour (phos.withAlpha (lit ? 0.98f : 0.62f));
            g.strokePath (p, { 1.7f, joint, cap });
            if (lit)
            {
                g.setColour (juce::Colour (0xfffff2d9).withAlpha (0.55f));
                g.strokePath (p, { 0.6f, joint, cap });
            }

            const auto labelArea = r.withTop (r.getBottom() - 15.0f);
            drawEngravedTrackedText (g, kNames[i], labelArea,
                                     displayFont (9.0f, false),
                                     lit ? t.amber().brighter (0.2f) : t.labelInk().withAlpha (0.6f),
                                     1.1f, lit ? 0.55f : 0.3f);
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

    // Phosphor for the trace: quiet rose at clean output, brighter rose-white
    // as SLAM pushes the output into gain and limiting. This is a visual output read,
    // not a claim that SLAM changes the filter body.
    juce::Colour responseColour() const
    {
        return t.curveColour().interpolatedWith (juce::Colour (0xfffff7fa), slamVisualAmount());
    }

    juce::Path displayPathForSlam() const
    {
        if (traceXs.empty() || traceXs.size() != traceDbs.size())
            return responsePath;

        const float s = slamNorm();
        if (s <= 0.001f)
            return responsePath;

        const auto plot = plotBounds();
        if (plot.isEmpty())
            return responsePath;

        const double dbTop = t.curveDbTop();
        const double dbBot = t.curveDbBottom();
        const double ceiling = dbTop - 2.0;
        const double knee = 12.0;
        const double kneeStart = ceiling - knee;
        const double outputGainDb = (double) trench::slamOutputGainDb (s);
        const double blend = (double) slamVisualAmount();

        auto softLimit = [=] (double db)
        {
            if (db <= kneeStart)
                return db;
            return kneeStart + knee * (1.0 - std::exp (-(db - kneeStart) / knee));
        };

        juce::Path p;
        bool started = false;
        for (size_t i = 0; i < traceDbs.size(); ++i)
        {
            const double cleanDb = (double) traceDbs[i];
            const double slammedDb = softLimit (cleanDb + outputGainDb);
            const double db = cleanDb + ((slammedDb - cleanDb) * blend);
            const double yt = juce::jlimit (-0.06, 1.06, (dbTop - db) / (dbTop - dbBot));
            const float x = traceXs[i];
            const float y = plot.getY() + (float) yt * plot.getHeight();
            if (! started)
            {
                p.startNewSubPath (x, y);
                started = true;
            }
            else
            {
                p.lineTo (x, y);
            }
        }
        return p;
    }

    // Etched phosphor trace, stroked from the live response Path. The wide pass is
    // only screen wetness; the curve itself stays thin and physical.
    void drawResponseTrace (juce::Graphics& g) const
    {
        const auto path = displayPathForSlam();
        if (path.isEmpty())
            return;

        const float s = slamVisualAmount();
        const auto phos = responseColour();
        const float limit = juce::jlimit (0.0f, 1.0f, slamOutClip);
        constexpr auto joint = juce::PathStrokeType::curved;
        constexpr auto cap   = juce::PathStrokeType::rounded;

        // One curve only, drawn like a measured trace on hardware glass:
        // a tiny two-pass phosphor glow, a dark bed for contrast against the
        // glass texture, then ONE consistent thin phosphor line with a fixed
        // hot centre. SLAM warms and thickens the same line slightly.
        g.setColour (phos.withAlpha (0.045f + 0.05f * s));      // outer glow — soft, tiny
        g.strokePath (path, { 4.6f + 0.8f * s, joint, cap });
        g.setColour (phos.withAlpha (0.10f + 0.08f * s));       // inner glow
        g.strokePath (path, { 2.4f + 0.5f * s, joint, cap });
        g.setColour (kInk.withAlpha (0.45f));                   // dark bed under the line
        g.strokePath (path, { 1.9f, joint, cap });
        g.setColour (phos.withAlpha (0.98f));                   // the phosphor line
        g.strokePath (path, { 1.15f + 0.20f * s, joint, cap });
        if (limit > 0.001f)
        {
            g.setColour (juce::Colour (0xfffff7fa).withAlpha (0.18f + 0.36f * limit));
            g.strokePath (path, { 0.8f + 1.3f * limit, joint, cap });
        }
        g.setColour (juce::Colour (0xfffff7fa).withAlpha (0.34f + 0.30f * s)); // constant hot centre
        g.strokePath (path, { 0.55f, joint, cap });
    }

    void drawSlamReadout (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        if (canvasParam == nullptr)
            return;

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

        g.setFont (displayFont (11.0f, false));
        g.setColour (juce::Colour (0xfffff7fa).withAlpha (0.95f * a));
        g.drawText (line1, r.removeFromTop (15.0f).reduced (6.0f, 1.0f),
                    juce::Justification::centredLeft, false);
        g.setFont (displayFont (8.8f, false));
        g.setColour (t.curveColour().withAlpha (0.86f * a));
        g.drawText (line2, r.reduced (6.0f, 0.0f), juce::Justification::centredLeft, false);
    }

    void drawMotionStatus (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        if (! motionActive) return;
        const auto led = screen.removeFromTop (10.0f).removeFromRight (10.0f).withSizeKeepingCentre (4.5f, 4.5f);
        g.setColour (juce::Colours::black.withAlpha (0.35f)); g.fillEllipse (led.expanded (1.4f));
        g.setColour (t.curveColour().withAlpha (0.9f)); g.fillEllipse (led);
        const auto rail = screen.withHeight (4.0f).withY (screen.getBottom() - 5.0f).reduced (3.0f, 0.0f);
        g.setColour (t.curveColour().withAlpha (0.14f)); g.fillRoundedRectangle (rail, 1.5f);
        g.setColour (t.curveColour().withAlpha (0.34f)); g.fillRoundedRectangle (rail.withWidth (rail.getWidth() * motionAmount), 1.5f);
        const float x = rail.getX() + ((float) motionStep / 15.0f) * rail.getWidth();
        g.setColour (t.curveColour()); g.fillEllipse (x - 2.0f, rail.getCentreY() - 2.0f, 4.0f, 4.0f);
    }

    inline static const juce::Colour kInk   { 0xff160710 }; // dark wine under-trace

    juce::Image gridImage;
    Theme t;
    juce::Path responsePath;
    std::vector<float> traceXs;
    std::vector<float> traceDbs;
    float lastCoeffs[30] = {};
    float lastBoost = -1.0f;
    double lastSr = 0.0;
    bool haveCurve = false;
    bool motionActive = false;
    int motionStep = 0;
    float motionAmount = 0.0f;

    // SLAM on-screen (canvas) control
    juce::RangedAudioParameter* canvasParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> canvasAtt;
    float canvasDefault = 0.0f;

    enum class ScreenMode { Curve, Collapsing, Grid, Expanding };
    ScreenMode screenMode = ScreenMode::Curve;
    float transitionProgress = 0.0f; // 0..1 within the current Collapsing/Expanding phase
    static constexpr float kTransitionSeconds = 0.18f;

    juce::RangedAudioParameter* motionOnParamForTiles = nullptr;
    juce::RangedAudioParameter* motionTileParamForTiles = nullptr;

    void timerCallback() override
    {
        if (screenMode == ScreenMode::Collapsing || screenMode == ScreenMode::Expanding)
        {
            transitionProgress += (float) (16.0 / 1000.0) / kTransitionSeconds;
            if (transitionProgress >= 1.0f)
            {
                transitionProgress = 1.0f;
                if (screenMode == ScreenMode::Collapsing)
                {
                    screenMode = ScreenMode::Grid;
                }
                else // Expanding finished
                {
                    screenMode = ScreenMode::Curve;
                    stopTimer();
                    if (onScreenModeChanged) onScreenModeChanged (false);
                }
            }
            repaint();
            return;
        }

        meterAlpha = juce::jmax (0.0f, meterAlpha - 0.05f);
        if (meterAlpha <= 0.01f) stopTimer();
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
