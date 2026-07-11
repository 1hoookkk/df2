#pragma once

#include "PluginProcessor.h"
#include "UiLayout.h"
#include "ui/Theme.h"
#include "ui/FaceplateView.h"
#include "ui/GraphDisplay.h"
#include "ui/SlotPad.h"
#include "ui/MoveChip.h"
#include "ui/TakeView.h"
#include "ui/MoveView.h"
// RouteView.h is shelved for V1 (ROUTE matrix editor not wired) — kept on disk for later.
#include "ui/WheelControl.h"
#include "ui/ValueReadout.h"
#include "ui/AmountFader.h"
#include "ui/SeedButton.h"
#include "ui/TakeButton.h"
#include "ui/FiveDButton.h"
#include "ui/TypeSelectorView.h"
#include "ui/LabelsLayer.h"
#include "ui/DecalsLayer.h"
#include "ui/RigPanel.h"
#include "ui/AuthorView.h"
#include "ui/ForgeView.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>
#include <memory>
#include <vector>

// Composition root: owns the baked layout/theme state, builds the child views,
// lays them out from UiLayout, and feeds them live data on the display refresh.
// It does not draw anything itself — every visual lives in its own component.
class PluginEditor final : public juce::AudioProcessorEditor,
                           private juce::Timer
{
public:
    explicit PluginEditor (PluginProcessor&);
    ~PluginEditor() override;

    void resized() override;
    void paintOverChildren (juce::Graphics&) override;   // the one pane of glass

private:
    void timerCallback() override;     // poll ui_layout.json for hand-edits
    void reloadLayoutFromDisk();       // overlay the live file + re-layout
    juce::Time layoutMtime;

    void layoutComponents();
    void onFrame();            // per-vblank: feed live data to the views
    void setPage (int page);   // 0 = SOUND curve, 1 = MOVE (PLAY only in V1)
    void refreshTake();        // pull the latest smart-take preview onto the Take page

    PluginProcessor& processor;
    trench::UiLayout currentLayout { trench::UiLayout::defaults() };
    trench::ui::Theme theme { currentLayout };
    std::unique_ptr<juce::VBlankAttachment> vblank;
    // One instance makes every setTooltip() across the UI actually appear on hover.
    juce::TooltipWindow tooltipWindow { this, 650 };

    std::unique_ptr<trench::ui::FaceplateView>    faceplate;
    std::unique_ptr<trench::ui::GraphDisplay>     graph;
    std::unique_ptr<trench::ui::SlotPad>          slotPad;
    std::unique_ptr<trench::ui::MoveChip>         moveChip; // curated MOVE status chip, inside the screen
    std::unique_ptr<trench::ui::TakeView>         takeView;
    std::unique_ptr<trench::ui::MoveView>         moveView;   // Page 2 — MOVE / PLAY (V1)
   #ifdef TRENCH_PLAYER_DIAGNOSTICS
    std::unique_ptr<trench::ui::RigPanel>         rigPanel;   // dev-only voicing rig (QSound SPACE/PAN)
    std::unique_ptr<trench::ui::AuthorView>       authorView; // dev-only authoring lab (floating window)
    std::unique_ptr<trench::ui::LabWindow>        labWindow;  // its own panel, toggled by the rig
   #endif
    int currentPage = 0;
    std::vector<PluginProcessor::VariantPreview>  tray;   // the 12 versions on Page 2
    std::unique_ptr<trench::ui::TypeSelectorView> typeSelector;
    std::unique_ptr<trench::ui::WheelControl>     morphWheel;
    std::unique_ptr<trench::ui::WheelControl>     secondaryWheel;
    std::unique_ptr<trench::ui::ValueReadout>     morphReadout;
    std::unique_ptr<trench::ui::ValueReadout>     secondaryReadout;
    std::unique_ptr<trench::ui::AmountFader>      amountFader;   // honest-dose fader, left of the screen
    std::unique_ptr<trench::ui::SeedButton>       seedButton;    // SEED: one tap, one related sibling
    std::unique_ptr<trench::ui::TakeButton>       takeButton;    // TAKE: drag the last few seconds into the DAW
    std::unique_ptr<trench::ui::FiveDButton>      fiveDButton;   // 5D: latch the extreme spatial orbit
    std::unique_ptr<trench::ui::LabelsLayer>      labels;
    std::unique_ptr<trench::ui::DecalsLayer>      decalsLayer;

    // FORGE dev panel (diagnostics builds only): null in release. forgeBtn toggles it.
    std::unique_ptr<trench::ui::ForgeView>        forge;
    std::unique_ptr<juce::TextButton>             forgeBtn;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PluginEditor)
};
