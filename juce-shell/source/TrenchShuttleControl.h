#pragma once

#include "TrenchStyle.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>

namespace trench
{

class TrenchShuttleControl final : public juce::Component
{
public:
    explicit TrenchShuttleControl (juce::RangedAudioParameter& param);
    ~TrenchShuttleControl() override;

    void paint (juce::Graphics&) override;

    void mouseDown (const juce::MouseEvent&) override;
    void mouseDrag (const juce::MouseEvent&) override;
    void mouseUp (const juce::MouseEvent&) override;
    void mouseDoubleClick (const juce::MouseEvent&) override;
    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails&) override;

private:
    void onParameterChanged (float newDenormValue);
    void commitValue (float normalised);

    float toDenorm (float v01) const noexcept;
    float toNorm (float denorm) const noexcept;
    static float clamp01 (float v) noexcept;

    juce::RangedAudioParameter& parameter;
    juce::ParameterAttachment attachment;

    float currentValue01 = 0.0f;
    float defaultValue01 = 0.5f;

    bool dragging = false;
    int dragStartX = 0;
    float dragStartValue01 = 0.0f;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchShuttleControl)
};

}
