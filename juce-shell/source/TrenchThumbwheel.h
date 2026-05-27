#pragma once

#include "BinaryData.h"
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>
#include <cmath>

namespace trench
{
// The bitmap thumbwheel roller for Morph / Q. Renders the 129-frame Blender
// filmstrip (native_strip_129_96x14.png, baked into BinaryData) — frame =
// round(value * 128) — and drives the parameter on vertical drag / wheel.
// This is the original bitmap roller, restored in place of the code-drawn drum.
class TrenchThumbwheel final : public juce::Component
{
public:
    explicit TrenchThumbwheel (juce::RangedAudioParameter& p)
        : parameter (p),
          attachment (p, [this] (float v)
                      {
                          norm = juce::jlimit (0.0f, 1.0f, parameter.convertTo0to1 (v));
                          repaint();
                      })
    {
        strip = juce::ImageCache::getFromMemory (BinaryData::native_strip_129_96x14_png,
                                                 BinaryData::native_strip_129_96x14_pngSize);
        setOpaque (false);
        attachment.sendInitialUpdate();
    }

    void paint (juce::Graphics& g) override
    {
        if (! strip.isValid())
            return;
        constexpr int numFrames = 129;
        const int fw    = strip.getWidth() / numFrames;
        const int fh    = strip.getHeight();
        const int frame = juce::jlimit (0, numFrames - 1, (int) std::lround (norm * (numFrames - 1)));
        const auto b    = getLocalBounds();
        g.drawImage (strip, b.getX(), b.getY(), b.getWidth(), b.getHeight(),
                     frame * fw, 0, fw, fh);
    }

    void mouseDown (const juce::MouseEvent&) override
    {
        dragStart = norm;
        attachment.beginGesture();
    }
    void mouseDrag (const juce::MouseEvent& e) override
    {
        const float delta = (float) -e.getDistanceFromDragStartY() / 220.0f; // drag up = increase
        setNormPart (dragStart + delta);
    }
    void mouseUp (const juce::MouseEvent&) override { attachment.endGesture(); }

    void mouseDoubleClick (const juce::MouseEvent&) override
    {
        setNormComplete (parameter.getDefaultValue());
    }
    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w) override
    {
        setNormComplete (norm + w.deltaY * 0.05f);
    }

private:
    void setNormPart (float n)
    {
        attachment.setValueAsPartOfGesture (parameter.convertFrom0to1 (juce::jlimit (0.0f, 1.0f, n)));
    }
    void setNormComplete (float n)
    {
        attachment.setValueAsCompleteGesture (parameter.convertFrom0to1 (juce::jlimit (0.0f, 1.0f, n)));
    }

    juce::RangedAudioParameter& parameter;
    juce::ParameterAttachment   attachment;
    juce::Image strip;
    float norm = 0.0f, dragStart = 0.0f;
};
} // namespace trench
