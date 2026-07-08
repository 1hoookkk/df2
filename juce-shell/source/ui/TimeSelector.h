#pragma once

#include "SelectorLookAndFeel.h"
#include "Theme.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// TIME: a musical division selector (1/4..1/32) for the three tempo-synced
// gestures (Riser/Breathe/Wobble). Binds directly to the existing motionDiv
// parameter via the standard APVTS attachment -- no custom mapping needed,
// unlike MOTION. Adlib Chop ignores it (envelope-driven, not clocked); the
// control stays interactive regardless, it's just inaudible on that gesture.
class TimeSelector : public juce::Component
{
public:
    TimeSelector (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        selector.setLookAndFeel (&lookAndFeel);
        selector.setInterceptsMouseClicks (false, false);
        for (auto colourId : { juce::ComboBox::backgroundColourId, juce::ComboBox::outlineColourId,
                               juce::ComboBox::buttonColourId, juce::ComboBox::arrowColourId,
                               juce::ComboBox::textColourId })
            selector.setColour (colourId, juce::Colours::transparentBlack);
        selector.setTextWhenNothingSelected ({});
        selector.addItem ("1/4", 1);
        selector.addItem ("1/8", 2);
        selector.addItem ("1/8T", 3);
        selector.addItem ("1/16", 4);
        selector.addItem ("1/16T", 5);
        selector.addItem ("1/32", 6);
        addAndMakeVisible (selector);

        attachment = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment> (
            apvts, ParamID::motionDiv, selector);

        selector.onChange = [this] { repaint(); };

        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Time");
        setHelpText ("Tempo division for the synced gestures");
    }

    ~TimeSelector() override { selector.setLookAndFeel (nullptr); }

    void resized() override { selector.setBounds (getLocalBounds()); }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }
    void mouseDown  (const juce::MouseEvent&) override { selector.showPopup(); repaint(); }

    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds().toFloat();
        g.setFont (displayFont (11.5f, false).withStyle (juce::Font::italic));
        g.setColour (kQuietInk.withAlpha (hover ? 1.0f : 0.88f));
        g.drawText ("TIME  " + selector.getText().toUpperCase(), b, juce::Justification::centredLeft, false);
    }

private:
    static inline const juce::Colour kQuietInk { 0xffd9bcc4 };

    Theme t;
    SelectorLookAndFeel lookAndFeel;
    juce::ComboBox selector;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> attachment;
    bool hover = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TimeSelector)
};

} // namespace trench::ui
