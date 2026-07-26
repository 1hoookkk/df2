#pragma once

#include "Theme.h"
#include "ParamInteraction.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <cmath>
#include <functional>
#include <memory>

namespace trench::ui
{

class WheelControl : public juce::Component,
                     public juce::SettableTooltipClient
{
public:
    // The frame is authored supersampled (3x the logical aperture) and drawn
    // INTO the logical aperture — minifying a high-res source stays crisp.
    // Aperture aspect must match the frame aspect (139:31 == 417:93).
    // This is the SESSIONBAK_1784628088 disc-rolloff seating, restored verbatim.
    static constexpr int kApertureWidth   = 139;
    static constexpr int kApertureHeight  = 31;
    static constexpr int kStripFrameWidth = 417;

    // Operator live-tune ("just let me nudge it. and resize it"): Ctrl+drag
    // nudges the wheel in its well, Ctrl+mouse-wheel resizes (aspect-locked).
    // Values persist in Documents/TRENCH/wheel_tune.json and apply to both
    // wheels; the landed numbers get baked into the constants afterwards.
    struct Tune
    {
        int dx = 0, dy = 0, w = kApertureWidth;
        int height() const { return juce::roundToInt ((float) w * kApertureHeight / (float) kApertureWidth); }
    };
    static Tune& tune()
    {
        static Tune t = [] {
            Tune loaded;
            const auto f = tuneFile();
            if (const auto parsed = juce::JSON::parse (f); parsed.getDynamicObject() != nullptr)
            {
                loaded.dx = (int) parsed.getProperty ("dx", 0);
                loaded.dy = (int) parsed.getProperty ("dy", 0);
                loaded.w  = juce::jlimit (100, 220, (int) parsed.getProperty ("w", kApertureWidth));
            }
            return loaded;
        }();
        return t;
    }
    static juce::File tuneFile()
    {
        return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
            .getChildFile ("TRENCH").getChildFile ("wheel_tune.json");
    }
    static void saveTune()
    {
        auto* obj = new juce::DynamicObject();
        obj->setProperty ("dx", tune().dx);
        obj->setProperty ("dy", tune().dy);
        obj->setProperty ("w", tune().w);
        tuneFile().replaceWithText (juce::JSON::toString (juce::var (obj)));
    }

    WheelControl (juce::AudioProcessorValueTreeState& apvts, juce::String paramID,
                  juce::Image filmstrip, const Theme& theme)
        : strip (std::move (filmstrip)), t (theme)
    {
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
            const auto name = param->getName (32);
            setMouseCursor (juce::MouseCursor::LeftRightResizeCursor);
            setTitle (name);
            setHelpText (name + " - drag left/right or mouse-wheel; double-click to reset");
            setTooltip (name + ": drag/wheel, double-click reset");
            attachment->sendInitialUpdate();
        }
        setInterceptsMouseClicks (true, false);
    }

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

    std::function<void()> onGestureEnd;
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
        if (e.mods.isCtrlDown())
        {
            tuning = true;
            tuneStartDx = tune().dx;
            tuneStartDy = tune().dy;
            tuneStartPos = e.getPosition();
            repaint();
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
        if (tuning)
        {
            tune().dx = tuneStartDx + (e.getPosition().x - tuneStartPos.x);
            tune().dy = tuneStartDy + (e.getPosition().y - tuneStartPos.y);
            if (auto* parent = getParentComponent())
                parent->repaint();
            return;
        }
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
        if (tuning)
        {
            tuning = false;
            saveTune();
            repaint();
            return;
        }
        pressing = false;
        if (attachment != nullptr)
            attachment->endGesture();
        if (onGestureEnd != nullptr)
            onGestureEnd();
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

    void mouseWheelMove (const juce::MouseEvent& e, const juce::MouseWheelDetails& wheel) override
    {
        if (e.mods.isCtrlDown())
        {
            tune().w = juce::jlimit (100, 220, tune().w + (wheel.deltaY > 0 ? 2 : -2));
            saveTune();
            if (auto* parent = getParentComponent())
                parent->repaint();
            return;
        }
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

        // The frame is authored at the compact editor's true aperture size and
        // draws 1:1, centred — never resampled (runtime scaling is what made the
        // wheel mushy). FULL silhouette, never clipped: the frame fits inside the
        // component, rounded ends and well surround stay visible (WINE_WHEEL law;
        // cropped caps read as a drum, "the framing is not right at all"). The
        // frame's own alpha remains the silhouette. The position glow is baked
        // into the filmstrip as one smooth packet — no code-drawn lamp and no
        // segmented diode pass. NOTHING is painted behind the wheel: the panel art's
        // baked recess IS the well (any code-drawn cavity here reads as a fake
        // rectangle; regressed twice, never again).
        // Supersampled frame minified into the fixed logical aperture, centred.
        // NOT fit-to-component scaling (that un-seats it from the baked well).
        // SESSIONBAK_1784628088 seating (the approved 07-21 disc-rolloff
        // reference): supersampled frame minified into the logical aperture,
        // centred — plus the operator's live tune offsets (Ctrl+drag / Ctrl+wheel,
        // persisted in Documents/TRENCH/wheel_tune.json). Landed values get
        // baked back into the constants.
        const int dw = tune().w;
        const int dh = tune().height();
        const int dx = (getWidth()  - dw) / 2 + tune().dx;
        const int dy = (getHeight() - dh) / 2 + tune().dy;
        g.setOpacity (1.0f);
        g.setImageResamplingQuality (juce::Graphics::highResamplingQuality);
        g.drawImage (strip, dx, dy, dw, dh, frame * fw, 0, fw, fh);

        if (tuning)
        {
            g.setColour (juce::Colour (0xffffb547));
            g.setFont (juce::FontOptions (9.0f).withStyle ("Bold"));
            g.drawText ("x" + juce::String (tune().dx) + " y" + juce::String (tune().dy)
                            + " w" + juce::String (tune().w),
                        2, 1, getWidth() - 4, 10, juce::Justification::centredLeft);
        }

        // Crown band killed twice (operator: "grey line in the middle") and the
        // code sheen retired with the slate-charcoal strip trial — the ART owns
        // the wheel's light. If the wheel reads too black, fix the STRIP, not
        // paint over it here.

        // Hover/drag feedback: the drum catches a touch more light under
        // the cursor — state feedback as light on the object, not a ring.
        if (hovering || pressing)
        {
            const auto drumF = juce::Rectangle<int> (dx, dy, dw, dh).toFloat();
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
        // While the user is dragging, the glow tracks THEIR hand (the real
        // parameter), never the modulated display value — otherwise motion
        // yanks the packet away from the cursor mid-gesture.
        return (displayOverrideActive && ! pressing) ? displayOverrideValue : currentNormalised();
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
    bool tuning = false;
    int tuneStartDx = 0;
    int tuneStartDy = 0;
    juce::Point<int> tuneStartPos;
};

} // namespace trench::ui
