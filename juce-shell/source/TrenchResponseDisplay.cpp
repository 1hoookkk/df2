#include "TrenchResponseDisplay.h"

#include "dsp/TrenchCleanBody.h"
#include "parameters/TrenchParameters.h"
#include "TrenchBodyRoster.h"

#include <algorithm>
#include <cmath>
#include <utility>

namespace trench
{

namespace
{
    // PL-4: kBodyNames[4] + kBodyCount=4 was a leftover from when the roster
    // had four entries — it cycled through four placeholder names regardless
    // of how many real bodies were loaded. Now the diagnostic readout reads
    // the live roster directly (`trench::bodyDisplayName`, `bodyCount`).

    juce::Colour mix (juce::Colour a, juce::Colour b, float t) noexcept
    {
        return a.interpolatedWith (b, juce::jlimit (0.0f, 1.0f, t));
    }

    // Morpheus-style meter ramp: green low → yellow ~70% → red top.
    juce::Colour meterColourFor (float t) noexcept
    {
        t = juce::jlimit (0.0f, 1.0f, t);
        if (t < 0.72f) return mix (juce::Colour (0xff36c828), juce::Colour (0xff64ff32), t / 0.72f);
        if (t < 0.88f) return mix (juce::Colour (0xff64ff32), style::oledYellow(), (t - 0.72f) / 0.16f);
        return mix (style::oledYellow(), style::oledRed(), (t - 0.88f) / 0.12f);
    }

    void drawSegmentedBar (juce::Graphics& g, juce::Rectangle<int> area, float v01,
                           int segments, juce::Colour litColour, juce::Colour dimColour)
    {
        if (area.isEmpty()) return;
        v01 = juce::jlimit (0.0f, 1.0f, v01);
        const int gap = 1;
        const int segW = juce::jmax (1, (area.getWidth() - gap * (segments - 1)) / segments);
        const int n    = juce::roundToInt (v01 * (float) segments);
        const bool ramp = (litColour == juce::Colours::transparentBlack);
        for (int i = 0; i < segments; ++i)
        {
            const auto seg = juce::Rectangle<int> (area.getX() + i * (segW + gap), area.getY(), segW, area.getHeight());
            const float t = (float) i / (float) juce::jmax (1, segments - 1);
            if (i < n) g.setColour (ramp ? meterColourFor (t) : litColour);
            else       g.setColour (dimColour);
            g.fillRect (seg);
        }
    }
}

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
    setInterceptsMouseClicks (false, false); // display-only; controls live on chassis/FX
    vBlank = juce::VBlankAttachment (this, [this] (double t) { onVBlankTick (t); });
}

void TrenchResponseDisplay::resized()
{
    rebuildGridImage();
    tracePathValid = false;
}

float TrenchResponseDisplay::param01 (const char* id) const noexcept
{
    if (auto* v = parameters.getRawParameterValue (id))
        return juce::jlimit (0.0f, 1.0f, v->load (std::memory_order_relaxed));
    return 0.0f;
}

int TrenchResponseDisplay::paramInt (const char* id) const noexcept
{
    if (auto* v = parameters.getRawParameterValue (id))
        return (int) std::round (v->load (std::memory_order_relaxed));
    return 0;
}

int TrenchResponseDisplay::bodyIndex() const noexcept
{
    return trench::wrapBodyIndex (paramInt (ParamID::body));
}

// ---- layout — 1.66:1 landscape, no in-screen cartridge name --------------
// The chassis TYPE strip above the screen already shows the cartridge name,
// so the screen does NOT repeat it. Top→bottom:
//   meters       : chunky L/R input bars, full width
//   sub-line     : tiny state readout (M / Q + input + 5D + body number)
//   hero row     : M / Q / S bars on the left, 2-D corner-bank pad on the right
//   output scope : amplitude-first post-filter stereo waveform
juce::Rectangle<int> TrenchResponseDisplay::meterBounds() const
{
    const auto b = getLocalBounds().reduced (6, 5);
    return { b.getX(), b.getY(), b.getWidth(), juce::jmax (22, juce::roundToInt ((float) b.getHeight() * 0.13f)) };
}

juce::Rectangle<int> TrenchResponseDisplay::subLineBounds() const
{
    const auto b = getLocalBounds().reduced (6, 5);
    const int top = meterBounds().getBottom() + 3;
    return { b.getX(), top, b.getWidth(), juce::jmax (10, juce::roundToInt ((float) b.getHeight() * 0.055f)) };
}

juce::Rectangle<int> TrenchResponseDisplay::spectrumBounds() const
{
    const auto b = getLocalBounds().reduced (6, 5);
    const int top = b.getY() + juce::roundToInt ((float) b.getHeight() * 0.55f);
    return { b.getX(), top, b.getWidth(), b.getBottom() - top };
}

juce::Rectangle<int> TrenchResponseDisplay::cornerBankPadBounds() const
{
    const auto b = getLocalBounds().reduced (6, 5);
    const int rowTop = subLineBounds().getBottom() + 3;
    const int rowBot = spectrumBounds().getY() - 3;
    const int rowH   = juce::jmax (40, rowBot - rowTop);
    const int side   = juce::jlimit (54, 150, juce::jmin (rowH, juce::roundToInt ((float) b.getWidth() * 0.34f)));
    // pad sits in the right column, vertically centred in the hero row
    return { b.getRight() - side, rowTop + (rowH - side) / 2, side, side };
}

juce::Rectangle<int> TrenchResponseDisplay::identityBounds() const
{
    // Retained for ABI; the cartridge name is on the chassis strip above and
    // is NOT drawn inside the screen. Returns an empty rect so drawIdentity
    // is a no-op without churning the header.
    return {};
}

juce::Rectangle<int> TrenchResponseDisplay::barsBounds() const
{
    const auto b = getLocalBounds().reduced (6, 5);
    const auto pad = cornerBankPadBounds();
    const int top  = subLineBounds().getBottom() + 3;
    const int bot  = spectrumBounds().getY() - 3;
    return { b.getX(), top, pad.getX() - b.getX() - 6, juce::jmax (16, bot - top) };
}

juce::Rectangle<int> TrenchResponseDisplay::paramBarFrame (int rowIndex) const
{
    const auto area = barsBounds();
    if (area.isEmpty()) return {};

    const int rowGap = 2;
    const int rowH = juce::jmax (6, (area.getHeight() - rowGap * 2) / 3);
    const int labelW = juce::jmax (12, rowH);
    const auto row = juce::Rectangle<int> (area.getX(),
                                           area.getY() + rowIndex * (rowH + rowGap),
                                           area.getWidth(),
                                           rowH);
    return row.withTrimmedLeft (labelW + 2);
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

void TrenchResponseDisplay::rebuildGridImage()
{
    const int w = getWidth(), h = getHeight();
    if (w <= 0 || h <= 0) { gridImage = {}; return; }

    gridImage = juce::Image (juce::Image::ARGB, w, h, true);
    juce::Graphics g (gridImage);

    const auto spectrum = spectrumBounds().reduced (2, 2);
    if (spectrum.isEmpty()) return;

    const int minor = juce::jmax (8, juce::roundToInt ((float) spectrum.getWidth() / 32.0f));
    const int major = minor * 4;

    // Major vertical gridlines — saturated blue, the Morpheus's primary grid color.
    g.setColour (style::oledBlue().withAlpha (0.65f));
    for (int x = spectrum.getX(); x <= spectrum.getRight(); x += major)
        g.drawVerticalLine (x, (float) spectrum.getY(), (float) spectrum.getBottom());

    // Horizontal amplitude rules — saturated red, multiple bands like Morpheus.
    g.setColour (style::oledRed().withAlpha (0.55f));
    for (float db : { 12.0f, -12.0f, -24.0f, -36.0f })
    {
        const int y = juce::roundToInt (juce::jmap (db, kDbFloor, kDbCeil,
                                                    (float) spectrum.getBottom(), (float) spectrum.getY()));
        if (y > spectrum.getY() && y < spectrum.getBottom())
            g.drawHorizontalLine (y, (float) spectrum.getX(), (float) spectrum.getRight());
    }

    // 0 dB reference line — green.
    {
        const int y = juce::roundToInt (juce::jmap (0.0f, kDbFloor, kDbCeil,
                                                    (float) spectrum.getBottom(), (float) spectrum.getY()));
        g.setColour (juce::Colour (0xff36c828).withAlpha (0.7f));
        g.drawHorizontalLine (y, (float) spectrum.getX(), (float) spectrum.getRight());
    }

    // Top + bottom border rules — magenta accent on the spectrum frame.
    g.setColour (style::oledMagenta().withAlpha (0.55f));
    g.drawHorizontalLine (spectrum.getY(),     (float) spectrum.getX(), (float) spectrum.getRight());
    g.drawHorizontalLine (spectrum.getBottom(), (float) spectrum.getX(), (float) spectrum.getRight());
}

void TrenchResponseDisplay::rebuildTraceFromCoeffs (const CoeffSet& coeffs, float boost)
{
    const auto bounds = spectrumBounds().reduced (4, 4);
    if (bounds.isEmpty()) { traceSampleCount = 0; tracePathValid = false; return; }

    const int width      = juce::jmin ((int) traceY.size(), juce::jmax (2, bounds.getWidth()));
    const int plotLeft   = bounds.getX();
    const int plotRight  = bounds.getRight();
    const int plotTop    = bounds.getY();
    const int plotBottom = bounds.getBottom();
    const int pixelStep  = 1;

    traceSampleCount = width;
    traceFloorY = plotBottom - 1;

    const float sampleRate = static_cast<float> (TrenchRates::emuInternalRate);
    // Never plot past Nyquist (fs/2 = 19531.25 Hz at 39062.5). Above it the
    // magnitude is just the aliased mirror — fiction. Stopping here shows the
    // HF/Nyquist edge (the near-wall pole tricks) truthfully.
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
        int yi = juce::jlimit (plotTop, traceFloorY, juce::roundToInt (yf));
        yi = juce::jlimit (plotTop, traceFloorY, pixelStep * juce::roundToInt ((float) yi / (float) pixelStep));
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
    const float corner = juce::jmin (10.0f, bounds.getHeight() * 0.045f);

    g.setColour (style::oledBg());
    g.fillRoundedRectangle (bounds, corner);

    juce::Path screenPath;
    screenPath.addRoundedRectangle (bounds, corner);
    juce::Graphics::ScopedSaveState clip (g);
    g.reduceClipRegion (screenPath);

    if (gridImage.getWidth() != getWidth() || gridImage.getHeight() != getHeight())
        rebuildGridImage();
    g.drawImageAt (gridImage, 0, 0);

    // The magnitude tell (the body's shape) is the hero — ALWAYS draw it. The live
    // output waveform overlays faintly on top when there's signal; it no longer
    // replaces the tell (which left the scope blank while audio played).
    if (tracePathValid)
        drawTrace (g);
    if (! cleanMode)
        drawOutputScope (g);

    drawSlamMeters (g);
    drawSubLine (g);
    drawParamBars (g);
    drawCornerBankPad (g);

    // Vignette.
    {
        const auto vb = getLocalBounds().toFloat();
        juce::ColourGradient vig (juce::Colours::transparentBlack, vb.getCentreX(), vb.getCentreY(),
                                  juce::Colours::black.withAlpha (0.28f), vb.getX(), vb.getY(), true);
        vig.addColour (0.66, juce::Colours::transparentBlack);
        g.setGradientFill (vig);
        g.fillRect (vb);
    }

    if (lastTickSec < flickerUntilSec)
    {
        g.setColour (style::oledWhite().withAlpha (0.12f));
        g.fillRect (getLocalBounds());
    }
}

void TrenchResponseDisplay::drawSlamMeters (juce::Graphics& g) const
{
    const auto area = meterBounds();
    const int labelW = juce::jmax (12, juce::roundToInt ((float) area.getHeight() * 0.42f));
    const int rowGap = 2;
    const int rowH = juce::jmax (5, (area.getHeight() - rowGap) / 2);
    const auto barL = juce::Rectangle<int> (area.getX() + labelW + 4, area.getY(), area.getWidth() - labelW - 4, rowH);
    const auto barR = barL.translated (0, rowH + rowGap);

    const float drive = param01 (ParamID::slamDrive);
    const float lv = juce::jlimit (0.0f, 1.0f, std::max (inputMeterL.load (std::memory_order_relaxed) * (0.65f + drive * 1.4f), drive * 0.10f));
    const float rv = juce::jlimit (0.0f, 1.0f, std::max (inputMeterR.load (std::memory_order_relaxed) * (0.65f + drive * 1.4f), drive * 0.10f));

    const float fs = juce::jlimit (10.0f, 18.0f, (float) rowH * 0.85f);
    g.setFont (style::label (fs, true));
    g.setColour (juce::Colour (0xff36c828));   // L label = green
    g.drawText ("L", area.getX(), barL.getY() - 1, labelW, rowH + 2, juce::Justification::centred);
    g.setColour (style::oledRed());            // R label = red
    g.drawText ("R", area.getX(), barR.getY() - 1, labelW, rowH + 2, juce::Justification::centred);

    drawSegmentedBar (g, barL, lv, 48, juce::Colours::transparentBlack, style::primary().withAlpha (0.12f));
    drawSegmentedBar (g, barR, rv, 48, juce::Colours::transparentBlack, style::primary().withAlpha (0.12f));
}

void TrenchResponseDisplay::drawIdentity (juce::Graphics& g) const
{
    const auto area = identityBounds();
    const float bigFs   = juce::jlimit (16.0f, 30.0f, (float) area.getHeight() * 0.86f);
    const float smallFs = bigFs * 0.40f;
    const auto bigFont   = style::label (bigFs, true);
    const auto smallFont = style::label (smallFs, true);

    const int body = bodyIndex();
    const auto num  = juce::String::formatted ("%03d", body + 1);
    const auto name = trench::bodyDisplayName (body).toUpperCase();

    const int numW = (int) std::ceil (juce::GlyphArrangement::getStringWidth (smallFont, num)) + 6;

    g.setColour (style::oledWhite().withAlpha (0.85f));
    g.setFont (smallFont);
    g.drawText (num, juce::Rectangle<int> (area.getX(), area.getY(), numW, area.getHeight()),
                juce::Justification::bottomLeft, false);

    g.setColour (style::oledWhite());
    g.setFont (bigFont);
    g.drawFittedText (name,
                      juce::Rectangle<int> (area.getX() + numW, area.getY(),
                                            area.getWidth() - numW, area.getHeight()),
                      juce::Justification::centredLeft, 1, 0.85f);
}

void TrenchResponseDisplay::drawSubLine (juce::Graphics& g) const
{
    const auto area = subLineBounds();
    const float fs = juce::jlimit (8.0f, 12.0f, (float) area.getHeight() * 0.85f);
    g.setFont (style::label (fs, true));

    const int mPct = juce::roundToInt (param01 (ParamID::morph) * 100.0f);
    const int qPct = juce::roundToInt (param01 (ParamID::q)     * 100.0f);

    if (cleanMode)
    {
        g.setColour (style::oledCyan());
        g.drawText (juce::String::formatted ("M %3d  Q %3d  IN OFF  SPACE OFF", mPct, qPct),
                    area, juce::Justification::centredLeft, false);

        g.setColour (style::oledMagenta());
        g.drawText (juce::String ("BODY240  ") + trench::clean_audio::kBodyName,
                    area, juce::Justification::centredRight, false);
        return;
    }

    const int inputIdx = juce::jlimit (0, 2, paramInt (ParamID::inputMode));
    const char* inputLbl = inputIdx == 0 ? "OFF" : (inputIdx == 1 ? "SLAM" : "EOS");
    const int fiveDIdx = juce::jlimit (0, 3, paramInt (ParamID::fiveD));
    const char* fiveDLbl = fiveDIdx == 0 ? "OFF" : (fiveDIdx == 1 ? "NAR" : (fiveDIdx == 2 ? "WIDE" : "FULL"));

    g.setColour (style::oledCyan());
    g.drawText (juce::String::formatted ("M %3d  Q %3d  IN %s  5D %s", mPct, qPct, inputLbl, fiveDLbl),
                area, juce::Justification::centredLeft, false);

    g.setColour (style::oledMagenta());
    g.drawText (juce::String::formatted ("BODY %03d", bodyIndex() + 1),
                area, juce::Justification::centredRight, false);
}

void TrenchResponseDisplay::drawParamBars (juce::Graphics& g) const
{
    const auto area = barsBounds();
    if (area.isEmpty()) return;

    const int rowGap = 2;
    const int rowH = juce::jmax (6, (area.getHeight() - rowGap * 2) / 3);
    const int labelW = juce::jmax (12, rowH);
    const float fs = juce::jlimit (9.0f, 14.0f, (float) rowH * 0.78f);
    g.setFont (style::label (fs, true));

    struct Row {
        const char* letter;
        juce::Colour letterCol;
        juce::Colour fillCol;
        float value;
    };
    const bool slamActive = paramInt (ParamID::inputMode) == 1;
    const Row rows[3] = {
        { "M", style::oledMagenta(), style::oledMagenta(), param01 (ParamID::morph)     },
        { "Q", style::oledYellow(),  style::oledBlue(),    param01 (ParamID::q)         },
        { "S", slamActive ? style::oledYellow() : style::oledWhite().withAlpha (0.32f),
               slamActive ? style::oledRed()    : style::oledWhite().withAlpha (0.18f),
               slamActive ? param01 (ParamID::slamDrive) : 0.0f },
    };

    for (int i = 0; i < 3; ++i)
    {
        const auto row = juce::Rectangle<int> (area.getX(), area.getY() + i * (rowH + rowGap), area.getWidth(), rowH);
        // letter
        g.setColour (rows[i].letterCol);
        g.drawText (rows[i].letter, row.withWidth (labelW), juce::Justification::centred, false);
        // white frame
        const auto frame = paramBarFrame (i);
        g.setColour (style::oledWhite().withAlpha (0.85f));
        g.drawRect (frame, 1);
        // fill
        drawSegmentedBar (g, frame.reduced (2, 2), rows[i].value, 14,
                          rows[i].fillCol, juce::Colours::transparentBlack.withAlpha (0.0f));
    }
}

void TrenchResponseDisplay::drawCornerBankPad (juce::Graphics& g) const
{
    const auto box = cornerBankPadBounds();
    if (box.isEmpty()) return;

    // Dim recessed plate so the trace doesn't fight the pad.
    g.setColour (juce::Colours::black.withAlpha (0.55f));
    g.fillRect (box);

    // White outline + the four Morpheus per-edge accents.
    const auto bf = box.toFloat().reduced (0.5f);
    g.setColour (style::oledWhite());
    g.drawRect (bf, 1.0f);
    g.setColour (style::oledMagenta());                         // top
    g.drawLine (bf.getX(),    bf.getY(),    bf.getRight(), bf.getY(), 1.5f);
    g.setColour (style::oledBlue());                            // left
    g.drawLine (bf.getX(),    bf.getY(),    bf.getX(),     bf.getBottom(), 1.5f);
    g.setColour (style::oledRed());                             // right
    g.drawLine (bf.getRight(), bf.getY(),   bf.getRight(), bf.getBottom(), 1.5f);
    g.setColour (style::oledYellow());                          // bottom
    g.drawLine (bf.getX(),    bf.getBottom(), bf.getRight(), bf.getBottom(), 1.5f);

    // Centre crosshairs in white.
    g.setColour (style::oledWhite().withAlpha (0.32f));
    g.drawVerticalLine (box.getCentreX(),   (float) box.getY() + 4.0f, (float) box.getBottom() - 4.0f);
    g.drawHorizontalLine (box.getCentreY(), (float) box.getX() + 4.0f, (float) box.getRight() - 4.0f);

    // The (Morph, Q) marker — white `+`, big and crisp like the Morpheus dot.
    const auto inner = box.reduced (juce::jmax (5, box.getWidth() / 8));
    const float mx = param01 (ParamID::morph);
    const float qv = param01 (ParamID::q);
    const float px = (float) inner.getX() + mx * (float) inner.getWidth();
    const float py = (float) inner.getBottom() - qv * (float) inner.getHeight();
    const float k = juce::jlimit (4.0f, 8.0f, (float) box.getWidth() * 0.10f);
    g.setColour (style::oledWhite());
    g.fillRect (juce::Rectangle<float> (px - k, py - 1.0f, k * 2.0f, 2.0f));
    g.fillRect (juce::Rectangle<float> (px - 1.0f, py - k, 2.0f, k * 2.0f));
}

bool TrenchResponseDisplay::drawOutputScope (juce::Graphics& g) const
{
    const auto area = spectrumBounds().reduced (4, 4);
    if (area.isEmpty() || ! scopeReader)
        return false;

    std::array<float, 512> l {};
    std::array<float, 512> r {};
    const int n = juce::jlimit (0, (int) l.size(), scopeReader (l.data(), r.data(), (int) l.size()));
    if (n < 2)
        return false;

    auto makePath = [&] (auto sampleAt)
    {
        juce::Path p;
        const float cy = (float) area.getCentreY();
        const float sy = (float) area.getHeight() * 0.42f;
        for (int i = 0; i < n; ++i)
        {
            const float x = juce::jmap ((float) i, 0.0f, (float) (n - 1),
                                        (float) area.getX(), (float) area.getRight());
            const float y = cy - juce::jlimit (-1.0f, 1.0f, sampleAt (i)) * sy;
            if (i == 0) p.startNewSubPath (x, y);
            else        p.lineTo (x, y);
        }
        return p;
    };

    g.setColour (juce::Colours::black.withAlpha (0.35f));
    g.fillRect (area);

    const float cy = (float) area.getCentreY();
    g.setColour (style::oledWhite().withAlpha (0.24f));
    g.drawHorizontalLine ((int) cy, (float) area.getX(), (float) area.getRight());

    const auto left  = makePath ([&] (int i) { return l[(size_t) i]; });
    const auto right = makePath ([&] (int i) { return r[(size_t) i]; });
    const auto mono  = makePath ([&] (int i) { return 0.5f * (l[(size_t) i] + r[(size_t) i]); });

    g.setColour (juce::Colour (0xff36c828).withAlpha (0.55f));
    g.strokePath (left, juce::PathStrokeType (1.2f));
    g.setColour (style::oledRed().withAlpha (0.48f));
    g.strokePath (right, juce::PathStrokeType (1.2f));
    g.setColour (style::oledWhite().withAlpha (0.85f));
    g.strokePath (mono, juce::PathStrokeType (1.6f));
    return true;
}

void TrenchResponseDisplay::drawTrace (juce::Graphics& g) const
{
    if (traceSampleCount < 2) return;

    const int thickness = 2;

    g.setColour (style::oledWhite());
    for (int i = 1; i < traceSampleCount; ++i)
    {
        const int x0 = traceX[(std::size_t) i - 1];
        const int y0 = traceY[(std::size_t) i - 1];
        const int x1 = traceX[(std::size_t) i];
        const int y1 = traceY[(std::size_t) i];
        const int hx = juce::jmin (x0, x1);
        const int hw = juce::jmax (1, std::abs (x1 - x0) + thickness);
        g.fillRect (hx, y0 - thickness / 2, hw, thickness);
        if (y0 != y1)
        {
            const int vy = juce::jmin (y0, y1);
            const int vh = std::abs (y1 - y0) + thickness;
            g.fillRect (x1 - thickness / 2, vy, thickness, vh);
        }
    }
}

} // namespace trench
