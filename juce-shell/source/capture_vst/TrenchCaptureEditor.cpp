#include "TrenchCaptureEditor.h"

namespace
{
    juce::Colour bg()      { return juce::Colour::fromRGB (8, 9, 8); }
    juce::Colour red()     { return juce::Colour::fromRGB (232, 42, 32); }
    juce::Colour ink()     { return juce::Colour::fromRGB (220, 230, 216); }
    juce::Colour dimInk()  { return juce::Colour::fromRGB (96, 112, 100); }
    juce::Colour green()   { return juce::Colour::fromRGB (84, 235, 110); }
}

TrenchCaptureEditor::TrenchCaptureEditor (TrenchCaptureProcessor& p)
    : AudioProcessorEditor (&p), processorRef (p)
{
    setOpaque (true);
    setResizable (false, false);
    setSize (420, 260);

    captureButton.setColour (juce::TextButton::buttonColourId, red());
    captureButton.setColour (juce::TextButton::buttonOnColourId, red().brighter());
    captureButton.setColour (juce::TextButton::textColourOffId, juce::Colours::white);
    captureButton.addListener (this);
    addAndMakeVisible (captureButton);

    for (int i = 0; i < 4; ++i)
    {
        static constexpr const char* labels[] = { "A", "B", "C", "D" };
        slotButtons[i].setButtonText (labels[i]);
        slotButtons[i].setClickingTogglesState (true);
        slotButtons[i].setRadioGroupId (1001);
        slotButtons[i].setToggleState (i == 0, juce::dontSendNotification);
        slotButtons[i].addListener (this);
        addAndMakeVisible (slotButtons[i]);
    }

    statusLabel.setJustificationType (juce::Justification::centred);
    statusLabel.setColour (juce::Label::textColourId, dimInk());
    statusLabel.setText ("insert on a track, choose slot, capture", juce::dontSendNotification);
    addAndMakeVisible (statusLabel);

    startTimerHz (20);
}

TrenchCaptureEditor::~TrenchCaptureEditor()
{
    stopTimer();
    captureButton.removeListener (this);
    for (auto& b : slotButtons)
        b.removeListener (this);
}

void TrenchCaptureEditor::paint (juce::Graphics& g)
{
    g.fillAll (bg());

    const auto bounds = getLocalBounds().toFloat();
    g.setColour (ink());
    g.setFont (juce::FontOptions (18.0f, juce::Font::bold));
    g.drawText ("TRENCH CAPTURE", getLocalBounds().removeFromTop (34), juce::Justification::centred);

    const auto meter = juce::jlimit (0.0f, 1.0f, processorRef.inputPeak());
    auto meterRect = bounds.withTrimmedLeft (28.0f).withTrimmedRight (28.0f).withY (186.0f).withHeight (8.0f);
    g.setColour (juce::Colour::fromRGB (26, 34, 28));
    g.fillRect (meterRect);
    g.setColour (green());
    g.fillRect (meterRect.withWidth (meterRect.getWidth() * meter));

    const auto progress = processorRef.progress01();
    if (progress > 0.0f && progress < 1.0f)
    {
        auto pRect = bounds.withTrimmedLeft (28.0f).withTrimmedRight (28.0f).withY (198.0f).withHeight (5.0f);
        g.setColour (juce::Colour::fromRGB (40, 20, 18));
        g.fillRect (pRect);
        g.setColour (red().brighter());
        g.fillRect (pRect.withWidth (pRect.getWidth() * progress));
    }

    processorRef.copyPolePreviewHz (poles, 6);
    auto poleArea = getLocalBounds().reduced (28, 0).removeFromBottom (42);
    g.setFont (juce::FontOptions (12.0f));
    for (int i = 0; i < 6; ++i)
    {
        const int w = poleArea.getWidth() / 6;
        auto cell = poleArea.removeFromLeft (w).reduced (3, 4);
        g.setColour (juce::Colour::fromRGB (18, 24, 20));
        g.fillRoundedRectangle (cell.toFloat(), 4.0f);
        g.setColour (poles[i] > 0.0f ? green() : dimInk());
        const auto text = poles[i] > 0.0f ? juce::String (juce::roundToInt (poles[i])) + " Hz" : "--";
        g.drawText (text, cell, juce::Justification::centred);
    }
}

void TrenchCaptureEditor::resized()
{
    auto r = getLocalBounds().reduced (28, 18);
    r.removeFromTop (28);

    auto slotRow = r.removeFromTop (34);
    for (auto& b : slotButtons)
        b.setBounds (slotRow.removeFromLeft (slotRow.getWidth() / 4).reduced (4, 2));

    r.removeFromTop (12);
    captureButton.setBounds (r.removeFromTop (94));
    statusLabel.setBounds (r.removeFromTop (34));
}

void TrenchCaptureEditor::buttonClicked (juce::Button* button)
{
    if (button == &captureButton)
    {
        processorRef.startCapture (selectedSlot);
        statusLabel.setText ("capturing", juce::dontSendNotification);
        return;
    }

    for (int i = 0; i < 4; ++i)
    {
        if (button == &slotButtons[i])
        {
            selectedSlot = i;
            return;
        }
    }
}

void TrenchCaptureEditor::timerCallback()
{
    statusLabel.setText (processorRef.statusText(), juce::dontSendNotification);
    repaint();
}
