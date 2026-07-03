#pragma once

#include "Theme.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// One thumbwheel: filmstrip frame for the bound parameter + contact shadow, with
// its own drag handling. The parameter is reached directly through a
// ParameterAttachment (correct begin/end gestures, host-thread-safe value
// callbacks) — no hidden Slider, no SliderAttachment.
class WheelControl : public juce::Component,
                     public juce::SettableTooltipClient
{
public:
    WheelControl (juce::AudioProcessorValueTreeState& apvts, juce::String paramID,
                  juce::Image filmstrip, const Theme& theme)
        : strip (std::move (filmstrip)), t (theme)
    {
        // The filmstrip is a horizontal row of kFrameWidth-wide frames; derive the
        // count from the image so the art and the code can never drift apart.
        numFrames = juce::jmax (1, strip.getWidth() / kFrameWidth);
        jassert (! strip.isValid() || strip.getWidth() % kFrameWidth == 0);
        isQControl = paramID.containsIgnoreCase ("q") || paramID.containsIgnoreCase ("slam");

        param = apvts.getParameter (paramID);
        jassert (param != nullptr);

        if (param != nullptr)
        {
            attachment = std::make_unique<juce::ParameterAttachment> (
                *param, [this] (float) { repaint(); });
            defaultDenorm = param->convertFrom0to1 (param->getDefaultValue());

            // Affordance + feedback: this wheel spins left<->right, so use the
            // matching cursor; name it for tooltips, screen readers and host
            // automation.
            const auto name = param->getName (32);
            setMouseCursor (juce::MouseCursor::LeftRightResizeCursor);
            setTitle (name);
            setHelpText (name + " - drag left/right or mouse-wheel; double-click to reset");
            setTooltip (name + ": drag/wheel, double-click reset");
            attachment->sendInitialUpdate();
        }

        setInterceptsMouseClicks (true, false);
    }

    // Re-bind this wheel to a different parameter at runtime (e.g. switching the
    // second wheel between Q and SLAM). Rebuilds the ParameterAttachment so begin/end
    // gestures and double-click-to-default track the new parameter.
    void setParameter (juce::AudioProcessorValueTreeState& apvts, const juce::String& paramID)
    {
        attachment.reset();
        param = apvts.getParameter (paramID);
        isQControl = paramID.containsIgnoreCase ("q") || paramID.containsIgnoreCase ("slam");
        if (param != nullptr)
        {
            attachment = std::make_unique<juce::ParameterAttachment> (
                *param, [this] (float) { repaint(); });
            defaultDenorm = param->convertFrom0to1 (param->getDefaultValue());
            const auto name = param->getName (32);
            setTitle (name);
            setHelpText (name + " - drag left/right or mouse-wheel; double-click to reset");
            setTooltip (name + ": drag/wheel, double-click reset");
            attachment->sendInitialUpdate();
        }
        repaint();
    }

    void setDisplayOverride (bool active, float normalised)
    {
        normalised = juce::jlimit (0.0f, 1.0f, normalised);
        if (displayOverrideActive != active || ! juce::approximatelyEqual (displayOverrideValue, normalised))
        {
            displayOverrideActive = active;
            displayOverrideValue = normalised;
            repaint();
        }
    }

    void mouseEnter (const juce::MouseEvent&) override { hovering = true;  repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hovering = false; repaint(); }

    void mouseDown (const juce::MouseEvent& e) override
    {
        pressing = true;
        if (attachment != nullptr)
            attachment->beginGesture();
        dragAbsolute (e);
    }
    void mouseDrag (const juce::MouseEvent& e) override { dragAbsolute (e); }
    void mouseUp (const juce::MouseEvent&) override
    {
        pressing = false;
        if (attachment != nullptr)
            attachment->endGesture();
        repaint();
    }

    void mouseDoubleClick (const juce::MouseEvent&) override
    {
        if (attachment != nullptr)
            attachment->setValueAsCompleteGesture (defaultDenorm);
    }

    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& wheel) override
    {
        if (attachment == nullptr || param == nullptr)
            return;

        const float next = juce::jlimit (0.0f, 1.0f, currentNormalised() + wheel.deltaY * 0.08f);
        attachment->setValueAsCompleteGesture (param->convertFrom0to1 (next));
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        if (! strip.isValid())
            return;

        const int fw = strip.getWidth() / numFrames;
        const int fh = strip.getHeight();
        if (fw <= 0 || fh <= 0)
            return;

        const int last = numFrames - 1;
        const int frame = juce::jlimit (0, last, juce::roundToInt (displayNormalised() * (float) last));

        // SEATED drum (Tyson 2026-07-02: "the way the wheel sits"): the drum
        // draws at ~90% of the well so the art's dark socket shows around it —
        // it sits IN the opening, not on top of it. The wine shell's well
        // floors are dark, so the margin reads as recess depth. A soft lip
        // shadow on the drum's crown lets the well's top edge overhang it.
        measureContentBox (fw, fh);
        const auto well = getLocalBounds().toFloat();
        constexpr float kSeat   = 0.95f;   // rounded caps float INSIDE the opening with a
                                           // visible gap (per Tyson's reference shots), not flush
        constexpr float kSeatCY = 0.50f;   // centered vertically
        const float scaleX = kSeat * well.getWidth() / (float) contentW;
        const float scale = scaleX;
        const float drawW = scale * (float) fw;
        const float drawH = scale * (float) fh;
        const float cx = well.getCentreX() - scale * ((float) contentX0 + (float) contentW * 0.5f);
        const auto dst = juce::Rectangle<float> (cx, well.getY() + well.getHeight() * kSeatCY - drawH * 0.5f,
                                                 drawW, drawH).toNearestInt();

        {
            juce::Graphics::ScopedSaveState save (g);
            juce::Path wellShape;
            // Corner radius must match the ART's well opening (its corners are much
            // rounder than 13%) or the drum's square ends show outside the curve
            // and read as hanging out of the slot.
            wellShape.addRoundedRectangle (well, well.getHeight() * 0.20f);
            g.reduceClipRegion (wellShape);
            // NOTHING is painted behind the wheel. The panel art's baked recess
            // IS the well — any code-drawn cavity/seat/trough here reads as a
            // fake rectangle box over the real recess (regressed twice; never again).
            g.setImageResamplingQuality (juce::Graphics::mediumResamplingQuality);
            g.setOpacity (1.0f);
            g.drawImage (strip, dst.getX(), dst.getY(), dst.getWidth(), dst.getHeight(),
                         frame * fw, 0, fw, fh);

            // Light-on-object only: the well's top lip shades the drum's crown,
            // and the drum melts into the socket floor at the bottom.
            const auto drumF = dst.toFloat();
            juce::ColourGradient lip (juce::Colours::black.withAlpha (0.42f), 0.0f, drumF.getY(),
                                      juce::Colours::transparentBlack, 0.0f, drumF.getY() + drumF.getHeight() * 0.24f, false);
            g.setGradientFill (lip);
            g.fillRect (drumF.withHeight (drumF.getHeight() * 0.24f));
            juce::ColourGradient contact (juce::Colours::transparentBlack, 0.0f, drumF.getBottom() - drumF.getHeight() * 0.16f,
                                          juce::Colours::black.withAlpha (0.34f), 0.0f, drumF.getBottom(), false);
            g.setGradientFill (contact);
            g.fillRect (drumF.withTop (drumF.getBottom() - drumF.getHeight() * 0.16f));
        }

        // The faceplate art owns the well edge. Do not draw an extra software
        // border over the bitmap; it reads as a rectangular artifact.
    }

private:
    // The drum's opaque horizontal span inside one frame, measured ONCE from the
    // strip's own alpha (frame 0) — adapts to the frozen art, no hardcoded box.
    void measureContentBox (int fw, int fh)
    {
        if (contentW > 0)
            return;
        int lo = fw, hi = -1;
        const juce::Image::BitmapData bd (strip, juce::Image::BitmapData::readOnly);
        for (int x = 0; x < fw; ++x)
            for (int y = 0; y < fh; ++y)
                if (bd.getPixelColour (x, y).getAlpha() > 8)
                {
                    lo = juce::jmin (lo, x);
                    hi = juce::jmax (hi, x);
                    break;
                }
        contentX0 = lo <= hi ? lo : 0;
        contentW  = lo <= hi ? hi - lo + 1 : fw;
    }

    float currentNormalised() const
    {
        return param != nullptr ? juce::jlimit (0.0f, 1.0f, param->getValue()) : 0.0f;
    }

    float displayNormalised() const
    {
        return displayOverrideActive ? displayOverrideValue : currentNormalised();
    }

    void dragAbsolute (const juce::MouseEvent& e)
    {
        if (attachment == nullptr || param == nullptr)
            return;

        const float w = juce::jmax (1.0f, (float) getWidth());
        const float next = juce::jlimit (0.0f, 1.0f, e.position.x / w);
        attachment->setValueAsPartOfGesture (param->convertFrom0to1 (next));
        repaint();
    }

    juce::RangedAudioParameter* param = nullptr;
    std::unique_ptr<juce::ParameterAttachment> attachment;
    juce::Image strip;
    int numFrames = 1;
    int contentX0 = 0, contentW = 0;   // frame 0's opaque drum span (lazy-measured)
    Theme t;
    bool hovering = false;
    bool pressing = false;
    bool isQControl = false;
    bool displayOverrideActive = false;
    float displayOverrideValue = 0.0f;
    float defaultDenorm = 0.0f;
    float dragStartX = 0.0f;
    float valueAtStart = 0.0f;
};

} // namespace trench::ui
