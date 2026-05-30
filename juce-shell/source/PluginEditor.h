#pragma once

#include "PluginProcessor.h"
#include "TrenchResponseDisplay.h"
#include "TrenchChassisGlass.h"
#include "TrenchValueBox.h"

#include <juce_gui_basics/juce_gui_basics.h>
#include <juce_audio_processors/juce_audio_processors.h>

class PluginEditor final : public juce::AudioProcessorEditor,
                           private juce::Timer
{
public:
    explicit PluginEditor (PluginProcessor&);
    ~PluginEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    void timerCallback() override; // file-watch tick
    void refreshVariantWatchFile();
    void makeWellSliderInvisible (juce::Slider&);

    PluginProcessor& processorRef;

    juce::Image chassisImage;

    std::unique_ptr<trench::TrenchResponseDisplay> responseDisplay;

    // The two left "wells" are invisible horizontal sliders dragged over the
    // chassis cutouts: Morph (upper) and Q (lower). The chassis PNG is the
    // visible identity; these add nothing visual of their own. A small bone /
    // phosphor readout sits in the cutout to the right of each well.
    juce::Slider                  morphWell;
    juce::Slider                  qWell;
    std::unique_ptr<trench::TrenchValueBox> morphReadout;
    std::unique_ptr<trench::TrenchValueBox> qReadout;

    using SliderAttachment = juce::AudioProcessorValueTreeState::SliderAttachment;
    std::unique_ptr<SliderAttachment> morphAttachment;
    std::unique_ptr<SliderAttachment> qAttachment;

    std::unique_ptr<trench::TrenchChassisGlass>    chassisGlass; // seating overlay (on top)

    juce::File   layoutFile;
    juce::Time   layoutFileMtime;
    juce::File   variantLayoutFile;
    juce::Time   variantLayoutFileMtime;

    // PL-3: track lastLoadOk so the timer can repaint the "BODY FAILED — bypass"
    // overlay only on state edges, not every tick.
    bool         lastKnownLoadOk { true };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginEditor)
};
