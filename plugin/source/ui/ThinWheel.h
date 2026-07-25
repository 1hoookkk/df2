#pragma once
#include "Theme.h"
#include "ParamInteraction.h"
#include "BinaryData.h"
#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>
namespace trench::ui
{
class ThinWheel : public juce::Component,
                  public juce::SettableTooltipClient
{
public:
    static constexpr int kFrameW = 12, kFrameH = 94, kNumFrames = 64;
    ThinWheel (juce::AudioProcessorValueTreeState& apvts, const juce::String& paramID)
    {
        strip = juce::ImageCache::getFromMemory (BinaryData::thin_wheel_strip_png,
                                                 BinaryData::thin_wheel_strip_pngSize);
        param = apvts.getParameter (paramID);
        jassert (param != nullptr);
        if (param != nullptr)
        {
            attachment = std::make_unique<juce::ParameterAttachment> (
                *param, [this] (float) { repaint(); });
            defaultDenorm = param->convertFrom0to1 (param->getDefaultValue());
            const auto name = param->getName (32);
            setTitle (name);
            setHelpText (name + " - drag to dial; Shift for fine; double-click to reset");
            setTooltip (name + ": drag to dial, Shift fine, double-click reset");
            attachment->sendInitialUpdate();
        }
        setMouseCursor (juce::MouseCursor::UpDownResizeCursor);
        setInterceptsMouseClicks (true, false);
    }
    void mouseDown (const juce::MouseEvent& e) override
    {
        if (e.mods.isPopupMenu())
        {
            showParamContextMenu (*this, param);
            return;
        }
        if (attachment != nullptr)
            attachment->beginGesture();
        dragStartY   = e.position.y;
        valueAtStart = currentNormalised();
        if (! e.mods.isShiftDown())
            dialAbsolute (e);
    }
    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (e.mods.isPopupMenu() || attachment == nullptr || param == nullptr)
            return;
        if (e.mods.isShiftDown())
        {
            const float h = juce::jmax (1.0f, (float) getHeight());
            const float next = juce::jlimit (0.0f, 1.0f,
                                             valueAtStart + (dragStartY - e.position.y) / h * 0.25f);
            attachment->setValueAsPartOfGesture (param->convertFrom0to1 (next));
            repaint();
        }
        else
        {
            dialAbsolute (e);
        }
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
    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w) override
    {
        if (attachment == nullptr || param == nullptr)
            return;
        const float next = juce::jlimit (0.0f, 1.0f, currentNormalised() + w.deltaY * 0.08f);
        attachment->setValueAsCompleteGesture (param->convertFrom0to1 (next));
        repaint();
    }
    void paint (juce::Graphics& g) override
    {
        if (! strip.isValid())
            return;
        // Integer scale only — the frame's 1px ribs must stay crisp.
        const int scale = juce::jmax (1, juce::jmin (getWidth() / kFrameW,
                                                     getHeight() / kFrameH));
        const int dw = kFrameW * scale;
        const int dh = kFrameH * scale;
        const int dx = (getWidth() - dw) / 2;
        const int dy = (getHeight() - dh) / 2;
        {
            const juce::Rectangle<float> sil ((float) dx + (float) dw * 0.5f,
                                              (float) dy + 1.5f,
                                              (float) dw * 0.85f,
                                              (float) dh - 3.0f);
            for (int i = 0; i < 4; ++i)
            {
                g.setColour (juce::Colours::black.withAlpha (0.085f - 0.018f * (float) i));
                g.fillRoundedRectangle (sil.translated (2.0f + 1.6f * (float) i, 0.7f * (float) i)
                                           .expanded (0.9f * (float) i),
                                        sil.getWidth() * 0.5f);
            }
        }
        const int frame = juce::jlimit (0, kNumFrames - 1,
                                        juce::roundToInt (currentNormalised() * (kNumFrames - 1)));
        g.setOpacity (1.0f);
        g.setImageResamplingQuality (juce::Graphics::highResamplingQuality);
        g.drawImage (strip, dx, dy, dw, dh, frame * kFrameW, 0, kFrameW, kFrameH);
    }
private:
    void dialAbsolute (const juce::MouseEvent& e)
    {
        if (attachment == nullptr || param == nullptr)
            return;
        const float h = juce::jmax (1.0f, (float) getHeight() - 6.0f);
        float next = juce::jlimit (0.0f, 1.0f, 1.0f - (e.position.y - 3.0f) / h);
        if (next > 0.965f)
            next = 1.0f;
        attachment->setValueAsPartOfGesture (param->convertFrom0to1 (next));
        if (onValueGesture)
            onValueGesture (next);
        repaint();
    }
public:
    std::function<void (float)> onValueGesture;
private:
    float currentNormalised() const
    {
        return param != nullptr ? juce::jlimit (0.0f, 1.0f, param->getValue()) : 0.0f;
    }
    juce::Image strip;
    juce::RangedAudioParameter* param = nullptr;
    std::unique_ptr<juce::ParameterAttachment> attachment;
    float defaultDenorm = 1.0f;
    float dragStartY = 0.0f;
    float valueAtStart = 0.0f;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ThinWheel)
};
}
