#pragma once

#include "Theme.h"
#include "../PluginProcessor.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// VOICING RIG — diagnostics builds only. Sliders wired straight to the spatial
// voicing levers so the levels can be chosen BY EAR on real material and written
// down (they then become baked per-preset voicing). Never compiled into the
// shipping face; deliberately utilitarian.
class RigPanel : public juce::Component
{
public:
    RigPanel (PluginProcessor& proc, const Theme& theme)
        : processor (proc), t (theme)
    {
        auto style = [] (juce::Slider& s)
        {
            s.setSliderStyle (juce::Slider::LinearHorizontal);
            s.setTextBoxStyle (juce::Slider::TextBoxRight, false, 58, 18);
            s.setColour (juce::Slider::textBoxTextColourId, juce::Colours::white);
            s.setColour (juce::Slider::textBoxOutlineColourId, juce::Colours::transparentBlack);
        };

        style (spaceSlider);
        spaceAttachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment> (
            processor.apvts, ParamID::fiveD, spaceSlider);
        addAndMakeVisible (spaceSlider);

        style (panSlider);
        panSlider.setRange (-1.0, 1.0, 0.001);
        panSlider.setValue (0.0, juce::dontSendNotification);
        panSlider.onValueChange = [this]
        {
            processor.rigPan.store ((float) panSlider.getValue(), std::memory_order_relaxed);
            repaint();
        };
        addAndMakeVisible (panSlider);

        spaceSlider.onValueChange = [this] { repaint(); };

        // Audition ANY canonical .body240: validate exactly 240 bytes, install
        // through the same path TakeView uses. TYPE presets cleanly replace it.
        loadButton.setButtonText ("LOAD BODY");
        loadButton.onClick = [this]
        {
            chooser = std::make_unique<juce::FileChooser> ("Load a canonical .body240",
                                                           juce::File(), "*.body240");
            chooser->launchAsync (juce::FileBrowserComponent::openMode
                                      | juce::FileBrowserComponent::canSelectFiles,
                                  [this] (const juce::FileChooser& fc)
            {
                const auto f = fc.getResult();
                if (f == juce::File())
                    return;
                juce::MemoryBlock bytes;
                if (! f.loadFileAsData (bytes) || bytes.getSize() != 240)
                {
                    loadedName = "REJECTED (" + juce::String ((juce::int64) bytes.getSize())
                               + "B != 240): " + f.getFileName();
                    repaint();
                    return;
                }
                processor.installBodyBytes (static_cast<const juce::uint8*> (bytes.getData()), 240);
                loadedName = f.getFileNameWithoutExtension();
                repaint();
            });
        };
        addAndMakeVisible (loadButton);

        labButton.setButtonText ("LAB");
        labButton.onClick = [this] { if (onToggleLab) onToggleLab(); };
        addAndMakeVisible (labButton);
    }

    // Editor wires this: toggles the authoring-lab side drawer.
    std::function<void()> onToggleLab;

    void resized() override
    {
        auto b = getLocalBounds().reduced (8, 4);
        auto title = b.removeFromTop (16);
        loadButton.setBounds (title.removeFromRight (86));
        title.removeFromRight (4);
        labButton.setBounds (title.removeFromRight (48));
        auto row1 = b.removeFromTop (24);
        row1.removeFromLeft (52);                   // label gutter
        spaceSlider.setBounds (row1);
        auto row2 = b.removeFromTop (24);
        row2.removeFromLeft (52);
        panSlider.setBounds (row2);
    }

    void paint (juce::Graphics& g) override
    {
        g.setColour (juce::Colours::black.withAlpha (0.72f));
        g.fillRoundedRectangle (getLocalBounds().toFloat(), 6.0f);
        g.setColour (juce::Colours::white.withAlpha (0.25f));
        g.drawRoundedRectangle (getLocalBounds().toFloat().reduced (0.5f), 6.0f, 1.0f);

        g.setFont (juce::Font (juce::FontOptions ("Consolas", 11.0f, juce::Font::plain)));
        g.setColour (juce::Colours::white.withAlpha (0.9f));
        auto vals = juce::String::formatted ("VOICING RIG   SPACE %.3f   PAN %+.3f",
                                             spaceSlider.getValue(), panSlider.getValue());
        if (loadedName.isNotEmpty())
            vals << "   [" << loadedName << "]";
        g.drawText (vals, getLocalBounds().reduced (10, 2).removeFromTop (16),
                    juce::Justification::centredLeft);

        g.setColour (juce::Colours::white.withAlpha (0.7f));
        auto b = getLocalBounds().reduced (8, 4);
        b.removeFromTop (14);
        g.drawText ("SPACE", b.removeFromTop (24).removeFromLeft (50), juce::Justification::centredLeft);
        g.drawText ("PAN",   b.removeFromTop (24).removeFromLeft (50), juce::Justification::centredLeft);
    }

private:
    PluginProcessor& processor;
    Theme t;
    juce::Slider spaceSlider, panSlider;
    juce::TextButton loadButton, labButton;
    juce::String loadedName;
    std::unique_ptr<juce::FileChooser> chooser;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> spaceAttachment;
};

} // namespace trench::ui
