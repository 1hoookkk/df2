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

// The recessed screen: plain dark wine glass plus the live cascade response
// curve as a rose hairline that hardens toward a
// hotter rose-white output read as SLAM rises. The faceplate,
// rollers, readouts and TYPE selector are LOCKED — this view only owns the screen.
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
        motionOnParam = apvts.getParameter (ParamID::motionOn);
        if (motionOnParam != nullptr)
            motionOnAtt = std::make_unique<juce::ParameterAttachment> (*motionOnParam, [this] (float) { repaint(); });
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

        drawResponseTrace (g);
        drawSlamReadout (g, screen);
        // No drawn edge either — the art's own bezel carries the seating.
    }

private:
    juce::Rectangle<float> plotBounds() const { return getLocalBounds().toFloat().reduced (6.0f, 5.0f); }

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
        if (pulsePhase != PulseIdle)
        {
            drawSeedPulseTrace (g);
            return;
        }

        const auto path = displayPathForSlam();
        if (path.isEmpty())
            return;

        const float s = slamVisualAmount();
        const auto phos = responseColour();
        const float limit = juce::jlimit (0.0f, 1.0f, slamOutClip);
        constexpr auto joint = juce::PathStrokeType::curved;
        constexpr auto cap   = juce::PathStrokeType::rounded;

        // MOTION off -> a faint baseline, not the fully "live" trace: the
        // curve is still the true current response, just visually quiet
        // until there's actual motion to preview.
        const bool motionOn = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;
        const float dim = motionOn ? 1.0f : 0.4f;

        // One curve only, drawn like a measured trace on hardware glass:
        // a tiny two-pass phosphor glow, a dark bed for contrast against the
        // glass texture, then ONE consistent thin phosphor line with a fixed
        // hot centre. SLAM warms and thickens the same line slightly.
        g.setColour (phos.withAlpha ((0.045f + 0.05f * s) * dim));      // outer glow — soft, tiny
        g.strokePath (path, { 4.6f + 0.8f * s, joint, cap });
        g.setColour (phos.withAlpha ((0.10f + 0.08f * s) * dim));       // inner glow
        g.strokePath (path, { 2.4f + 0.5f * s, joint, cap });
        g.setColour (kInk.withAlpha (0.45f * dim));                     // dark bed under the line
        g.strokePath (path, { 1.9f, joint, cap });
        g.setColour (phos.withAlpha (0.98f * dim));                     // the phosphor line
        g.strokePath (path, { 1.15f + 0.20f * s, joint, cap });
        if (limit > 0.001f)
        {
            g.setColour (juce::Colour (0xfffff7fa).withAlpha ((0.18f + 0.36f * limit) * dim));
            g.strokePath (path, { 0.8f + 1.3f * limit, joint, cap });
        }
        g.setColour (juce::Colour (0xfffff7fa).withAlpha ((0.34f + 0.30f * s) * dim)); // constant hot centre
        g.strokePath (path, { 0.55f, joint, cap });
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
        const auto hot = juce::Colour (0xfffff7fa).interpolatedWith (juce::Colour (0xffff2f4a), 0.4f);
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

    // SLAM on-screen (canvas) control
    juce::RangedAudioParameter* canvasParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> canvasAtt;
    // Read live only to dim the curve when MOTION is off — never written here.
    juce::RangedAudioParameter* motionOnParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> motionOnAtt;
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

        if (meterAlpha <= 0.01f && pulsePhase == PulseIdle) stopTimer();
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
