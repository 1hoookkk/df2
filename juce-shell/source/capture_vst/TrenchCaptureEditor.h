#pragma once

#include "TrenchCaptureProcessor.h"

#include <juce_gui_basics/juce_gui_basics.h>

class TrenchCaptureEditor final : public juce::AudioProcessorEditor,
                                  private juce::Button::Listener,
                                  private juce::Timer
{
public:
    explicit TrenchCaptureEditor (TrenchCaptureProcessor&);
    ~TrenchCaptureEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    void buttonClicked (juce::Button* button) override;
    void timerCallback() override;

    TrenchCaptureProcessor& processorRef;

    juce::TextButton captureButton { "CAPTURE" };
    juce::TextButton slotButtons[4];
    juce::Label statusLabel;

    int selectedSlot = 0;
    float poles[6] {};

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchCaptureEditor)
};
