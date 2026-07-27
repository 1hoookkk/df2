#pragma once
#include "PluginProcessor.h"
#include "UiLayout.h"
#include "ui/Theme.h"
#include "ui/FaceplateView.h"
#include "ui/GraphDisplay.h"
#include "ui/MoveChip.h"
#include "ui/KeySnapBox.h"
#include "ui/Onboarding.h"
#include "ui/WheelControl.h"
#include "ui/ValueReadout.h"
#include "ui/ThinWheel.h"
#include "ui/TypeSelectorView.h"
#include "ui/LabelsLayer.h"
#include "ui/DecalsLayer.h"
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>
#include <memory>
#include <vector>
class PluginEditor final : public juce::AudioProcessorEditor,
                           private juce::Timer
{
public:
    explicit PluginEditor (PluginProcessor&);
    ~PluginEditor() override;
    void resized() override;
    /// FaceShot hook: force the tour visible at a given step for judging.
    void showOnboardingStep (int step);
private:
    void timerCallback() override;
    void reloadLayoutFromDisk();
    juce::Time layoutMtime;
    void layoutComponents();
    void onFrame();
    PluginProcessor& processor;
    trench::UiLayout currentLayout { trench::UiLayout::defaults() };
    trench::ui::Theme theme { currentLayout };
    std::unique_ptr<juce::VBlankAttachment> vblank;
    juce::TooltipWindow tooltipWindow { this, 650 };
    std::unique_ptr<trench::ui::FaceplateView>    faceplate;
    std::unique_ptr<trench::ui::GraphDisplay>     graph;
    std::unique_ptr<trench::ui::MoveChip>         moveChip;
    std::unique_ptr<trench::ui::KeySnapBox>       keySnapBox;
    std::unique_ptr<trench::ui::TypeSelectorView> typeSelector;
    std::unique_ptr<trench::ui::WheelControl>     morphWheel;
    std::unique_ptr<trench::ui::WheelControl>     secondaryWheel;
    std::unique_ptr<trench::ui::ValueReadout>     morphReadout;
    std::unique_ptr<trench::ui::ValueReadout>     secondaryReadout;
    std::unique_ptr<trench::ui::ThinWheel>        amountWheel;
    std::unique_ptr<trench::ui::Onboarding>       onboarding;
    trench::ui::Onboarding::ReplayHotspot         onboardingReplayHotspot;
    float onboardingDemoStart = -1.0f;
    std::unique_ptr<trench::ui::LabelsLayer>      labels;
#if TRENCH_TABLE_STITCH_PANEL
    void openTableStitcher();
    std::unique_ptr<juce::TextButton>                  tableStitchButton;
    std::unique_ptr<juce::ChildProcess>                tableStitchProcess;
#endif
    std::unique_ptr<trench::ui::DecalsLayer>      decalsLayer;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginEditor)
};
