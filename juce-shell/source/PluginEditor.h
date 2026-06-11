#pragma once

#include "PluginProcessor.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>
#include <memory>

class PluginEditor final : public juce::AudioProcessorEditor,
                           private juce::Timer
{
public:
    explicit PluginEditor (PluginProcessor&);
    ~PluginEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;
    void mouseDown (const juce::MouseEvent&) override;
    void mouseDrag (const juce::MouseEvent&) override;
    void mouseUp (const juce::MouseEvent&) override;

private:
    void drawThumbwheels (juce::Graphics&);
    void drawThumbwheelFrame (juce::Graphics&, juce::Rectangle<float>, float);
    void drawSelectorAndReadouts (juce::Graphics&);
    void drawDisplayWell (juce::Graphics&, juce::Rectangle<float>);
    void drawReadout (juce::Graphics&, juce::Rectangle<float>, const juce::String&, float);
    void populateBodySelector();
    void syncBodySelectorToParameter();
    void timerCallback() override;

    PluginProcessor& processor;
    juce::ComboBox bodySelector;
    juce::Slider morphSlider;
    juce::Slider qSlider;
    juce::Component morphHitTarget;
    juce::Component qHitTarget;
    const char* activeThumbwheelParameter = nullptr;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> morphSliderAttachment;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> qSliderAttachment;
    bool syncingBodySelector = false;
    juce::Image panelImage;
    juce::Image thumbwheelStrip;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginEditor)
};
