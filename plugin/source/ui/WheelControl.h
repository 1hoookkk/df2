#pragma once

#include "Theme.h"
#include "ParamInteraction.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <cmath>
#include <functional>
#include <memory>

namespace trench::ui
{

// One thumbwheel: the iron twin-row roller rendered at ACTUAL SIZE with the
// cobalt position glow BAKED into the filmstrip (X3 law — light through the fin
// gaps, trailing bar). Frames draw 1:1, centred, overhanging the plate's black
// opening (the recut wells are tighter than the wheel — the well edge crops it,
// like the hardware). Drag handling reaches the parameter directly through a
// ParameterAttachment (correct begin/end gestures, host-thread-safe value
// callbacks) — no hidden Slider, no SliderAttachment.
class WheelControl : public juce::Component,
                     public juce::SettableTooltipClient
{
public:
    static constexpr int kStripFrameWidth = 200;   // actual-size frame (drawn 1:1, never resampled)

    WheelControl (juce::AudioProcessorValueTreeState& apvts, juce::String paramID,
                  juce::Image filmstrip, const Theme& theme)
        : strip (std::move (filmstrip)), t (theme)
    {
        // The filmstrip is a horizontal row of fixed-width frames; derive the
        // count from the image so the art and the code can never drift apart.
        numFrames = juce::jmax (1, strip.getWidth() / kStripFrameWidth);
        jassert (! strip.isValid() || strip.getWidth() % kStripFrameWidth == 0);
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

    // Alt-drag recording (Morph only, wired externally -- see PluginEditor):
    // the wheel still moves/plays normally under Alt, this just additionally
    // reports the live value so a caller can teach a USER motion from it.
    std::function<void()> onAltDragStart;
    std::function<void (float)> onAltDragSample;
    std::function<void()> onAltDragEnd;

    void mouseDown (const juce::MouseEvent& e) override
    {
        if (e.mods.isPopupMenu())   // right-click -> Reset + host MIDI-learn/automation menu
        {
            showParamContextMenu (*this, param);
            return;
        }
        pressing = true;
        altRecording = e.mods.isAltDown() && onAltDragSample != nullptr;
        if (attachment != nullptr)
            attachment->beginGesture();
        dragStartX   = e.position.x;
        valueAtStart = currentNormalised();
        if (! e.mods.isShiftDown())   // Shift = fine drag from the press point, no jump
            dragAbsolute (e);
        if (altRecording)
        {
            if (onAltDragStart != nullptr) onAltDragStart();
            onAltDragSample (currentNormalised());
        }
    }
    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (e.mods.isPopupMenu())
            return;
        if (e.mods.isShiftDown() && attachment != nullptr && param != nullptr)
        {
            // Fine, precise drag: scaled delta from the press point.
            const float w    = juce::jmax (1.0f, (float) getWidth());
            const float next = juce::jlimit (0.0f, 1.0f,
                                             valueAtStart + (e.position.x - dragStartX) / w * 0.25f);
            attachment->setValueAsPartOfGesture (param->convertFrom0to1 (next));
            repaint();
        }
        else
        {
            dragAbsolute (e);
        }
        if (altRecording && onAltDragSample != nullptr)
            onAltDragSample (currentNormalised());
    }
    void mouseUp (const juce::MouseEvent&) override
    {
        pressing = false;
        if (attachment != nullptr)
            attachment->endGesture();
        if (altRecording)
        {
            altRecording = false;
            if (onAltDragEnd != nullptr) onAltDragEnd();
        }
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

        // ACTUAL-SIZE draw: frames are authored at display resolution and drawn
        // 1:1, centred — never resampled, never clipped. The frame's own alpha
        // is the silhouette; it overhangs the plate's black opening so only the
        // well edge frames it (the X3 sit). The cobalt position glow is BAKED
        // into the filmstrip — no code-drawn lamp. NOTHING is painted behind
        // the wheel: the panel art's baked recess IS the well (any code-drawn
        // cavity here reads as a fake rectangle; regressed twice, never again).
        const int dx = (getWidth()  - fw) / 2;
        const int dy = (getHeight() - fh) / 2;
        g.setOpacity (1.0f);
        g.drawImage (strip, dx, dy, fw, fh, frame * fw, 0, fw, fh);

        // Hover/drag feedback: the drum catches a touch more light under
        // the cursor — state feedback as light on the object, not a ring.
        if (hovering || pressing)
        {
            const auto drumF = juce::Rectangle<int> (dx, dy, fw, fh).toFloat();
            juce::ColourGradient lift (juce::Colours::white.withAlpha (pressing ? 0.10f : 0.06f),
                                       0.0f, drumF.getY() + drumF.getHeight() * 0.30f,
                                       juce::Colours::transparentBlack, 0.0f, drumF.getBottom(), false);
            g.setGradientFill (lift);
            g.fillRect (drumF);
        }

        // The faceplate art owns the well edge. Do not draw an extra software
        // border over the bitmap; it reads as a rectangular artifact.
    }

private:
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
    Theme t;
    bool hovering = false;
    bool pressing = false;
    bool altRecording = false;
    bool isQControl = false;
    bool displayOverrideActive = false;
    float displayOverrideValue = 0.0f;
    float defaultDenorm = 0.0f;
    float dragStartX = 0.0f;
    float valueAtStart = 0.0f;
};

} // namespace trench::ui
