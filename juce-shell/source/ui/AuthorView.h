#pragma once

#include "Theme.h"
#include "../PluginProcessor.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// AUTHORING LAB — diagnostics builds only, in its OWN floating window (toggled
// by the rig's LAB button). The one surface where a preset's shipped numbers
// are defined BY EAR: the motion numbers, QSound SPACE/PAN, ARMED, LOAD BODY,
// and PRINT (voicing block -> clipboard + log). Never ships.
class AuthorView : public juce::Component
{
public:
    AuthorView (PluginProcessor& proc, const Theme& theme)
        : processor (proc), t (theme)
    {
        auto addF = [this] (juce::Slider& s, const char* pid)
        {
            s.setSliderStyle (juce::Slider::LinearHorizontal);
            s.setTextBoxStyle (juce::Slider::TextBoxRight, false, 44, 15);
            s.setColour (juce::Slider::textBoxTextColourId, juce::Colours::white);
            s.setColour (juce::Slider::textBoxOutlineColourId, juce::Colours::transparentBlack);
            fAtts.push_back (std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment> (
                processor.apvts, pid, s));
            addAndMakeVisible (s);
        };
        addF (amount, ParamID::motionAmount);
        addF (react,  ParamID::motionReact);
        addF (drift,  ParamID::moveDrift);
        addF (space,  ParamID::fiveD);

        pan.setSliderStyle (juce::Slider::LinearHorizontal);
        pan.setTextBoxStyle (juce::Slider::TextBoxRight, false, 44, 15);
        pan.setColour (juce::Slider::textBoxTextColourId, juce::Colours::white);
        pan.setColour (juce::Slider::textBoxOutlineColourId, juce::Colours::transparentBlack);
        pan.setRange (-1.0, 1.0, 0.001);
        pan.setValue (processor.rigPan.load(), juce::dontSendNotification);
        pan.onValueChange = [this] { processor.rigPan.store ((float) pan.getValue(), std::memory_order_relaxed); };
        addAndMakeVisible (pan);

        auto addC = [this] (juce::ComboBox& c, const char* pid, const juce::StringArray& items)
        {
            c.addItemList (items, 1);
            cAtts.push_back (std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment> (
                processor.apvts, pid, c));
            addAndMakeVisible (c);
        };
        addC (shape, ParamID::motionShape, { "Sine", "Ramp", "Square", "Random" });
        addC (div,   ParamID::motionDiv,   { "1/4", "1/8", "1/8T", "1/16", "1/16T", "1/32" });

        armed.setButtonText ("ARMED");
        armed.setClickingTogglesState (true);
        bAtts.push_back (std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment> (
            processor.apvts, ParamID::motionOn, armed));
        addAndMakeVisible (armed);

        loadBtn.setButtonText ("LOAD BODY");
        loadBtn.onClick = [this]
        {
            chooser = std::make_unique<juce::FileChooser> ("Load a canonical .body240",
                                                           juce::File(), "*.body240");
            chooser->launchAsync (juce::FileBrowserComponent::openMode
                                      | juce::FileBrowserComponent::canSelectFiles,
                                  [this] (const juce::FileChooser& fc)
            {
                const auto f = fc.getResult();
                if (f == juce::File()) return;
                juce::MemoryBlock bytes;
                if (! f.loadFileAsData (bytes) || bytes.getSize() != 240)
                {
                    status = "REJECTED (" + juce::String ((juce::int64) bytes.getSize()) + "B)";
                    repaint();
                    return;
                }
                processor.installBodyBytes (bytes.getData(), 240);
                loadedName = f.getFileNameWithoutExtension();
                status = "loaded " + loadedName;
                repaint();
            });
        };
        addAndMakeVisible (loadBtn);

        printBtn.setButtonText ("PRINT");
        printBtn.onClick = [this] { printNumbers(); };
        addAndMakeVisible (printBtn);
    }

    void resized() override
    {
        auto b = getLocalBounds().reduced (14, 10);
        b.removeFromTop (26);                                    // title
        auto row = [&b] (int h) { auto r = b.removeFromTop (h); b.removeFromTop (6); return r; };

        { auto r = row (24); r.removeFromLeft (54); shape.setBounds (r); }
        { auto r = row (24); r.removeFromLeft (54); div.setBounds (r); }
        { auto r = row (24); r.removeFromLeft (54); amount.setBounds (r); }
        { auto r = row (24); r.removeFromLeft (54); react.setBounds (r); }
        { auto r = row (24); r.removeFromLeft (54); drift.setBounds (r); }
        b.removeFromTop (10);
        { auto r = row (24); r.removeFromLeft (54); space.setBounds (r); }
        { auto r = row (24); r.removeFromLeft (54); pan.setBounds (r); }
        b.removeFromTop (12);
        { auto r = row (26); armed.setBounds (r.removeFromLeft (70)); r.removeFromLeft (6);
          loadBtn.setBounds (r.removeFromLeft (98)); }
        { auto r = row (26); printBtn.setBounds (r.removeFromLeft (70)); }
    }

    void paint (juce::Graphics& g) override
    {
        g.setColour (juce::Colours::black.withAlpha (0.78f));
        g.fillRoundedRectangle (getLocalBounds().toFloat(), 8.0f);

        g.setFont (juce::Font (juce::FontOptions ("Consolas", 11.0f, juce::Font::plain)));
        g.setColour (juce::Colours::white.withAlpha (0.92f));
        juce::String title ("AUTHORING LAB");
        if (status.isNotEmpty()) title << "   " << status;
        g.drawText (title, getLocalBounds().reduced (12, 4).removeFromTop (14),
                    juce::Justification::centredLeft);

        g.setColour (juce::Colours::white.withAlpha (0.65f));
        auto b = getLocalBounds().reduced (14, 10);
        b.removeFromTop (26);
        const char* names[] = { "WAVE", "SPEED", "MOVE", "REACT", "DRIFT" };
        for (auto* n : names)
        {
            g.drawText (n, b.removeFromTop (24).removeFromLeft (52), juce::Justification::centredLeft);
            b.removeFromTop (6);
        }
        b.removeFromTop (10);
        g.drawText ("SPACE", b.removeFromTop (24).removeFromLeft (52), juce::Justification::centredLeft);
        b.removeFromTop (6);
        g.drawText ("PAN",   b.removeFromTop (24).removeFromLeft (52), juce::Justification::centredLeft);

        // legend — what each number means, always visible at the drawer's foot
        g.setColour (juce::Colours::white.withAlpha (0.50f));
        g.setFont (juce::Font (juce::FontOptions ("Consolas", 10.0f, juce::Font::plain)));
        auto leg = getLocalBounds().reduced (14, 10).removeFromBottom (100);
        const char* lines[] = { "WAVE   how the morph moves",
                                "SPEED  locked to your beat",
                                "MOVE   how far morph travels",
                                "REACT  your audio pushes Q",
                                "DRIFT  humanize, never loops",
                                "PRINT  numbers -> clipboard" };
        for (auto* ln : lines)
            g.drawText (ln, leg.removeFromTop (16), juce::Justification::centredLeft);
    }

private:
    void printNumbers()
    {
        auto raw = [this] (const char* id) -> float
        {
            if (auto* v = processor.apvts.getRawParameterValue (id)) return v->load();
            return 0.0f;
        };
        juce::String j;
        j << "{\n"
          << "  \"body\": \"" << (loadedName.isNotEmpty() ? loadedName : juce::String ("(roster)")) << "\",\n"
          << "  \"motion\": { \"on\": " << (raw (ParamID::motionOn) > 0.5f ? "true" : "false")
          << ", \"shape\": " << (int) raw (ParamID::motionShape)
          << ", \"div\": " << (int) raw (ParamID::motionDiv)
          << ", \"react\": " << juce::String (raw (ParamID::motionReact), 3)
          << ", \"amount\": " << juce::String (raw (ParamID::motionAmount), 3)
          << ", \"drift\": " << juce::String (raw (ParamID::moveDrift), 3)
          << ", \"morphDepth\": " << juce::String (raw (ParamID::motionMorphDepth), 3)
          << ", \"qDepth\": " << juce::String (raw (ParamID::motionQDepth), 3) << " },\n"
          << "  \"space\": " << juce::String (raw (ParamID::fiveD), 3)
          << ", \"pan\": " << juce::String (processor.rigPan.load(), 3)
          << ", \"slam\": " << juce::String (raw (ParamID::slamDrive), 3) << "\n}\n";

        juce::SystemClipboard::copyTextToClipboard (j);
        auto log = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                       .getChildFile ("TRENCH").getChildFile ("preset_voicing_log.json");
        log.getParentDirectory().createDirectory();
        log.appendText (j + ",\n");
        status = "printed -> clipboard + log";
        repaint();
    }

    PluginProcessor& processor;
    Theme t;
    juce::Slider react, amount, drift, space, pan;
    juce::ComboBox shape, div;
    juce::TextButton armed, loadBtn, printBtn;
    juce::String loadedName, status;
    std::unique_ptr<juce::FileChooser> chooser;
    std::vector<std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment>> fAtts;
    std::vector<std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment>> cAtts;
    std::vector<std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment>> bAtts;
};

// The lab's floating shell: native title bar, close = hide, always-on-top so
// it rides beside the plugin/DAW while voicing.
class LabWindow : public juce::DocumentWindow
{
public:
    explicit LabWindow (juce::Component* content)
        : juce::DocumentWindow ("AUTHORING LAB", juce::Colours::black,
                                juce::DocumentWindow::closeButton)
    {
        setUsingNativeTitleBar (true);
        setAlwaysOnTop (true);
        setContentNonOwned (content, false);
        centreWithSize (290, 640);
    }

    void closeButtonPressed() override { setVisible (false); }
};

} // namespace trench::ui
