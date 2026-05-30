#include "TrenchResponseDisplay.h"

#include <algorithm>
#include <cmath>
#include <utility>

namespace trench
{

TrenchResponseDisplay::TrenchResponseDisplay (TrenchDspBridge& bridge,
                                              juce::AudioProcessorValueTreeState& state,
                                              const std::atomic<float>& inputL,
                                              const std::atomic<float>& inputR,
                                              ScopeReader reader,
                                              bool cleanModeIn)
    : dspBridge (bridge),
      parameters (state),
      inputMeterL (inputL),
      inputMeterR (inputR),
      scopeReader (std::move (reader)),
      cleanMode (cleanModeIn)
{
    setOpaque (false);
    setInterceptsMouseClicks (false, false); // display-only; controls live on the chassis
    vBlank = juce::VBlankAttachment (this, [this] (double t) { onVBlankTick (t); });
}

void TrenchResponseDisplay::resized()
{
    tracePathValid = false;
}

// The curve owns the whole screen now — no meters, sub-line, bars, or pad to
// share with. Small inset so the glow doesn't clip the rounded screen edge.
juce::Rectangle<int> TrenchResponseDisplay::screenBounds() const
{
    return getLocalBounds().reduced (12, 12);
}

float TrenchResponseDisplay::coeffDistance (const CoeffSet& a, const CoeffSet& b) noexcept
{
    float acc = 0.0f;
    for (std::size_t i = 0; i < a.size(); ++i) { const float d = a[i] - b[i]; acc += d * d; }
    return std::sqrt (acc);
}

float TrenchResponseDisplay::easeInOutCubic (float t) noexcept
{
    t = juce::jlimit (0.0f, 1.0f, t);
    return t < 0.5f ? 4.0f * t * t * t : 1.0f - std::pow (-2.0f * t + 2.0f, 3.0f) * 0.5f;
}

TrenchResponseDisplay::CoeffSet TrenchResponseDisplay::lerpCoeffs (const CoeffSet& a, const CoeffSet& b, float t) noexcept
{
    CoeffSet out{};
    const float u = juce::jlimit (0.0f, 1.0f, t);
    for (std::size_t i = 0; i < a.size(); ++i) out[i] = a[i] + (b[i] - a[i]) * u;
    return out;
}

// Pull the live smoothed coefficients each vblank and ease the drawn curve
// toward them. Hands off the knobs ⇒ target stops changing ⇒ curve goes still.
void TrenchResponseDisplay::onVBlankTick (double timestampSec)
{
    lastTickSec = timestampSec;

    CoeffSet target{};
    float targetBoost = 1.0f;
    dspBridge.getSmoothedCoeffsForUI (target.data(), targetBoost);

    if (! haveTarget)
    {
        animFromCoeffs = target; animToCoeffs = target;
        animFromBoost = targetBoost; animToBoost = targetBoost;
        animStartSec = timestampSec; animDurationSec = 0.0;
        haveTarget = true;
        rebuildTraceFromCoeffs (target, targetBoost);
        repaint();
        return;
    }

    if (target != animToCoeffs || targetBoost != animToBoost)
    {
        const float remaining = animDurationSec > 0.0
            ? (float) juce::jlimit (0.0, 1.0, (timestampSec - animStartSec) / animDurationSec) : 1.0f;
        const float eased = easeInOutCubic (remaining);
        animFromCoeffs = lerpCoeffs (animFromCoeffs, animToCoeffs, eased);
        animFromBoost  = animFromBoost + (animToBoost - animFromBoost) * eased;
        animToCoeffs = target; animToBoost = targetBoost; animStartSec = timestampSec;
        const float dist = coeffDistance (animFromCoeffs, animToCoeffs);
        const float t = juce::jlimit (0.0f, 1.0f, dist / kBigChangeL2);
        animDurationSec = juce::jmap ((double) t, 0.0, 1.0, kAnimMinMs / 1000.0, kAnimMaxMs / 1000.0);
    }

    const double elapsed = timestampSec - animStartSec;
    const float u = animDurationSec > 0.0 ? (float) juce::jlimit (0.0, 1.0, elapsed / animDurationSec) : 1.0f;
    const float eased = easeInOutCubic (u);
    const auto current = lerpCoeffs (animFromCoeffs, animToCoeffs, eased);
    const float currentBoost = animFromBoost + (animToBoost - animFromBoost) * eased;
    rebuildTraceFromCoeffs (current, currentBoost);
    repaint();
}

void TrenchResponseDisplay::rebuildTraceFromCoeffs (const CoeffSet& coeffs, float boost)
{
    const auto bounds = screenBounds().reduced (4, 4);
    if (bounds.isEmpty()) { traceSampleCount = 0; tracePathValid = false; return; }

    const int width      = juce::jmin ((int) traceY.size(), juce::jmax (2, bounds.getWidth()));
    const int plotLeft   = bounds.getX();
    const int plotRight  = bounds.getRight();
    const int plotTop    = bounds.getY();
    const int plotBottom = bounds.getBottom();

    traceSampleCount = width;
    traceFloorY = plotBottom - 1;

    const float sampleRate = static_cast<float> (TrenchRates::emuInternalRate);
    // Never plot past Nyquist (fs/2). Above it the magnitude is just the aliased
    // mirror — fiction. Stopping here shows the HF/Nyquist edge truthfully.
    const float freqHi   = juce::jmin (kFreqHi, sampleRate * 0.5f);
    const float logRatio = freqHi / kFreqLo;

    for (int i = 0; i < width; ++i)
    {
        const float t    = static_cast<float> (i) / static_cast<float> (juce::jmax (1, width - 1));
        const float freq = kFreqLo * std::pow (logRatio, t);
        const float omega = juce::MathConstants<float>::twoPi * freq / sampleRate;
        const float cosW = std::cos (omega), sinW = std::sin (omega);
        const float cos2W = std::cos (2.0f * omega), sin2W = std::sin (2.0f * omega);

        float mag = juce::jmax (1.0e-12f, boost);
        for (int s = 0; s < 6; ++s)
        {
            const float* c = &coeffs[(std::size_t) s * 5];
            const float numR = c[0] + c[1] * cosW + c[2] * cos2W;
            const float numI = -(c[1] * sinW + c[2] * sin2W);
            const float denR = 1.0f + c[3] * cosW + c[4] * cos2W;
            const float denI = -(c[3] * sinW + c[4] * sin2W);
            const float dm2 = denR * denR + denI * denI;
            if (dm2 > 1.0e-18f) mag *= std::sqrt ((numR * numR + numI * numI) / dm2);
        }

        const float db = juce::jlimit (kDbFloor, kDbCeil, 20.0f * std::log10 (juce::jmax (1.0e-12f, mag)));
        const float yf = juce::jmap (db, kDbFloor, kDbCeil, (float) plotBottom, (float) plotTop);
        const int yi = juce::jlimit (plotTop, traceFloorY, juce::roundToInt (yf));
        const int xi = juce::roundToInt (juce::jmap ((float) i, 0.0f, (float) (width - 1),
                                                     (float) plotLeft, (float) (plotRight - 1)));
        traceX[(std::size_t) i] = xi;
        traceY[(std::size_t) i] = yi;
    }

    tracePathValid = true;
}

void TrenchResponseDisplay::paint (juce::Graphics& g)
{
    const auto bounds = getLocalBounds().toFloat();
    const float corner = juce::jmin (12.0f, bounds.getHeight() * 0.05f);

    // Near-black screen.
    g.setColour (style::oledBg());
    g.fillRoundedRectangle (bounds, corner);

    juce::Path screenPath;
    screenPath.addRoundedRectangle (bounds, corner);
    juce::Graphics::ScopedSaveState clip (g);
    g.reduceClipRegion (screenPath);

    if (tracePathValid)
        drawTrace (g);

    // Soft inner vignette so the curve sits in the glass.
    {
        const auto vb = getLocalBounds().toFloat();
        juce::ColourGradient vig (juce::Colours::transparentBlack, vb.getCentreX(), vb.getCentreY(),
                                  juce::Colours::black.withAlpha (0.30f), vb.getX(), vb.getY(), true);
        vig.addColour (0.70, juce::Colours::transparentBlack);
        g.setGradientFill (vig);
        g.fillRect (vb);
    }
}

// The shape: one bright response line. No fill, grid, labels, or selection UI.
// Identity/bypass is 0 dB, centered vertically by the -30..+30 dB display range.
void TrenchResponseDisplay::drawTrace (juce::Graphics& g) const
{
    if (traceSampleCount < 2) return;

    juce::Path curve;
    curve.startNewSubPath ((float) traceX[0], (float) traceY[0]);
    for (int i = 1; i < traceSampleCount; ++i)
        curve.lineTo ((float) traceX[(std::size_t) i], (float) traceY[(std::size_t) i]);

    const juce::PathStrokeType glow (4.0f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded);
    const juce::PathStrokeType core (2.2f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded);
    g.setColour (style::oledBlue().withAlpha (0.24f));
    g.strokePath (curve, glow);
    g.setColour (style::oledWhite());
    g.strokePath (curve, core);
}

} // namespace trench
