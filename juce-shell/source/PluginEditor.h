#pragma once

#include "PluginProcessor.h"
#include "TrenchShuttleControl.h"
#include "TrenchValueBox.h"
#include "TrenchBodyStrip.h"
#include "TrenchResponseDisplay.h"
#include "TrenchFxPane.h"
#include "TrenchViewSwitch.h"
#include "TrenchChassisGlass.h"
#include "TrenchThumbwheel.h"

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

    PluginProcessor& processorRef;

    juce::Image chassisImage;

    std::unique_ptr<trench::TrenchResponseDisplay> responseDisplay;
    std::unique_ptr<trench::TrenchFxPane>          fxPane;       // alternate screen face
    std::unique_ptr<trench::TrenchViewSwitch>      viewSwitch;   // MAIN | FX tab
    std::unique_ptr<trench::TrenchThumbwheel>     morphBand, qBand; // bitmap rollers
    std::unique_ptr<trench::TrenchValueBox>       morphValue, qValue;
    std::unique_ptr<trench::TrenchBodyStrip>      bodyStrip;
    std::unique_ptr<trench::TrenchChassisGlass>   chassisGlass; // seating overlay (on top)

    juce::File   layoutFile;
    juce::Time   layoutFileMtime;
    juce::File   variantLayoutFile;
    juce::Time   variantLayoutFileMtime;

    // PL-3: track lastLoadOk so the timer can repaint the "BODY FAILED — bypass"
    // overlay only on state edges, not every tick.
    bool         lastKnownLoadOk { true };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginEditor)
};
