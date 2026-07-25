#pragma once
#include "ParamInteraction.h"
#include "Theme.h"
#include "../parameters/TrenchParameters.h"
#include <juce_audio_processors/juce_audio_processors.h>
#include <cmath>
#include <memory>
namespace trench::ui
{
class MixKnob final : public juce::Component,
                      public juce::SettableTooltipClient
{
public:
    MixKnob (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme), param (apvts.getParameter (ParamID::amount))
    {
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::UpDownResizeCursor);
        setTitle ("Mix");
        setHelpText ("Mix - dry to full body; drag up, Shift for fine");
        setTooltip ("Mix: dry to full body, drag up for more, double-click to reset");
        if (param != nullptr)
        {
            attachment = std::make_unique<juce::ParameterAttachment> (
                *param, [this] (float) { repaint(); });
            attachment->sendInitialUpdate();
            defaultDenorm = param->convertFrom0to1 (param->getDefaultValue());
        }
    }
    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }
    void mouseDown (const juce::MouseEvent& e) override
    {
        if (e.mods.isPopupMenu())
        {
            showParamContextMenu (*this, param);
            return;
        }
        if (attachment != nullptr)
            attachment->beginGesture();
        dragStartY = e.position.y;
        valueAtStart = currentNormalised();
    }
    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (attachment == nullptr || param == nullptr || e.mods.isPopupMenu())
            return;
        const float travel = 72.0f;
        const float scale = e.mods.isShiftDown() ? 0.25f : 1.0f;
        const float next = juce::jlimit (0.0f, 1.0f,
                                         valueAtStart + (dragStartY - e.position.y) / travel * scale);
        attachment->setValueAsPartOfGesture (param->convertFrom0to1 (next));
        repaint();
    }
    void mouseUp (const juce::MouseEvent&) override
    {
        if (attachment != nullptr)
            attachment->endGesture();
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
        const float next = juce::jlimit (0.0f, 1.0f,
                                         currentNormalised() + wheel.deltaY * 0.08f);
        attachment->setValueAsCompleteGesture (param->convertFrom0to1 (next));
        repaint();
    }
    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds().toFloat();
        const float cx = b.getCentreX();
        const float cy = 10.5f;
        const float r = juce::jmin (8.5f, b.getWidth() * 0.32f);
        g.setColour (juce::Colours::black.withAlpha (0.22f));
        g.fillEllipse (cx - r - 1.0f, cy - r + 1.5f, (r + 1.0f) * 2.0f, (r + 1.0f) * 2.0f);
        juce::ColourGradient cap (juce::Colour (0xff607074), cx, cy - r,
                                   juce::Colour (0xff252d2f), cx, cy + r, false);
        g.setGradientFill (cap);
        g.fillEllipse (cx - r, cy - r, r * 2.0f, r * 2.0f);
        g.setColour (juce::Colour (0xff152022).withAlpha (0.90f));
        g.drawEllipse (cx - r, cy - r, r * 2.0f, r * 2.0f, 0.75f);
        const float value = currentNormalised();
        const float angle = juce::MathConstants<float>::pi * (-0.72f + value * 1.44f);
        g.setColour (juce::Colour (0xffd9e1dd).withAlpha (hover ? 0.92f : 0.72f));
        g.drawLine (cx, cy, cx + std::sin (angle) * (r - 2.0f),
                    cy - std::cos (angle) * (r - 2.0f), 0.8f);
        g.setFont (displayFont (7.4f, false));
        g.setColour (juce::Colour (0xff28231f).withAlpha (0.88f));
        g.drawText ("MIX", b.withY (20.0f).withHeight (8.0f).toNearestInt(),
                    juce::Justification::centred, false);
    }
private:
    float currentNormalised() const noexcept
    {
        return param != nullptr ? param->getValue() : 0.0f;
    }
    Theme t;
    juce::RangedAudioParameter* param = nullptr;
    std::unique_ptr<juce::ParameterAttachment> attachment;
    float defaultDenorm = 0.0f;
    float dragStartY = 0.0f;
    float valueAtStart = 0.0f;
    bool hover = false;
};
}
