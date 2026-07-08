#pragma once

#include "SelectorLookAndFeel.h"
#include "Theme.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// MOTION: OFF / RISER / BREATHE / ADLIB CHOP / WOBBLE — five fixed musical
// gestures, one selector. Maps onto two existing params (motionOn + tile
// index) since there's no single APVTS choice covering "off + 4 named
// gestures"; the ComboBox itself is the only thing that knows the mapping.
// No rate/depth here — TIME and DEPTH are their own controls.
class MotionSelector : public juce::Component
{
public:
    MotionSelector (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        selector.setLookAndFeel (&lookAndFeel);
        selector.setInterceptsMouseClicks (false, false);
        for (auto colourId : { juce::ComboBox::backgroundColourId, juce::ComboBox::outlineColourId,
                               juce::ComboBox::buttonColourId, juce::ComboBox::arrowColourId,
                               juce::ComboBox::textColourId })
            selector.setColour (colourId, juce::Colours::transparentBlack);
        selector.setTextWhenNothingSelected ({});
        selector.addItem ("Off", 1);
        selector.addItem ("Riser", 2);
        selector.addItem ("Breathe", 3);
        selector.addItem ("Adlib Chop", 4);
        selector.addItem ("Wobble", 5);
        addAndMakeVisible (selector);

        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Motion");
        setHelpText ("Pick a modulation gesture, or turn it off");

        motionOnParam = apvts.getParameter (ParamID::motionOn);
        motionTileParam = apvts.getParameter (ParamID::motionTile);

        if (motionOnParam != nullptr)
            onAtt = std::make_unique<juce::ParameterAttachment> (*motionOnParam, [this] (float) { syncFromParams(); });
        if (motionTileParam != nullptr)
            tileAtt = std::make_unique<juce::ParameterAttachment> (*motionTileParam, [this] (float) { syncFromParams(); });
        syncFromParams();

        selector.onChange = [this]
        {
            const int id = selector.getSelectedId();
            if (id <= 0 || onAtt == nullptr || tileAtt == nullptr) return;
            if (id == 1)
            {
                onAtt->setValueAsCompleteGesture (0.0f);
            }
            else if (motionTileParam != nullptr)
            {
                tileAtt->setValueAsCompleteGesture (motionTileParam->convertTo0to1 ((float) (id - 2)));
                onAtt->setValueAsCompleteGesture (1.0f);
            }
            repaint();
        };
    }

    ~MotionSelector() override { selector.setLookAndFeel (nullptr); }

    void resized() override { selector.setBounds (getLocalBounds()); }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }
    void mouseDown  (const juce::MouseEvent&) override { selector.showPopup(); repaint(); }

    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds().toFloat();
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;

        g.setFont (displayFont (11.5f, false).withStyle (juce::Font::italic));
        g.setColour ((on ? t.amber() : kQuietInk).withAlpha (hover ? 1.0f : (on ? 0.95f : 0.88f)));
        g.drawText ("MOTION  " + selector.getText().toUpperCase(), b, juce::Justification::centredLeft, false);
    }

private:
    void syncFromParams()
    {
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;
        int id = 1;
        if (on && motionTileParam != nullptr)
        {
            const int tile = juce::jlimit (0, 3, juce::roundToInt (
                motionTileParam->convertFrom0to1 (motionTileParam->getValue())));
            id = tile + 2;
        }
        if (selector.getSelectedId() != id)
            selector.setSelectedId (id, juce::dontSendNotification);
        repaint();
    }

    static inline const juce::Colour kQuietInk { 0xffd9bcc4 };

    Theme t;
    SelectorLookAndFeel lookAndFeel;
    juce::ComboBox selector;
    juce::RangedAudioParameter* motionOnParam = nullptr;
    juce::RangedAudioParameter* motionTileParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> onAtt;
    std::unique_ptr<juce::ParameterAttachment> tileAtt;
    bool hover = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MotionSelector)
};

} // namespace trench::ui
