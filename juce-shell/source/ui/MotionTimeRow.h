#pragma once

#include "SelectorLookAndFeel.h"
#include "Theme.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// One compact clickable row under the screen: "RISER · 1/16" or just "OFF".
// Left word = MOTION (Off/Riser/Breathe/Adlib Chop/Wobble), right word =
// TIME (musical division) — two independent popups sharing one line, no
// "MOTION"/"TIME" labels, no duplicate state shown anywhere else.
class MotionTimeRow : public juce::Component
{
public:
    MotionTimeRow (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        motionOnParam   = apvts.getParameter (ParamID::motionOn);
        motionTileParam = apvts.getParameter (ParamID::motionTile);

        for (auto* combo : { &motionCombo, &timeCombo })
        {
            combo->setLookAndFeel (&lookAndFeel);
            combo->setInterceptsMouseClicks (false, false);
            for (auto colourId : { juce::ComboBox::backgroundColourId, juce::ComboBox::outlineColourId,
                                   juce::ComboBox::buttonColourId, juce::ComboBox::arrowColourId,
                                   juce::ComboBox::textColourId })
                combo->setColour (colourId, juce::Colours::transparentBlack);
            combo->setTextWhenNothingSelected ({});
            addAndMakeVisible (*combo);
        }

        motionCombo.addItem ("Off", 1);
        motionCombo.addItem ("Riser", 2);
        motionCombo.addItem ("Breathe", 3);
        motionCombo.addItem ("Adlib Chop", 4);
        motionCombo.addItem ("Wobble", 5);

        timeCombo.addItem ("1/4", 1);
        timeCombo.addItem ("1/8", 2);
        timeCombo.addItem ("1/8T", 3);
        timeCombo.addItem ("1/16", 4);
        timeCombo.addItem ("1/16T", 5);
        timeCombo.addItem ("1/32", 6);

        motionDivParam = apvts.getParameter (ParamID::motionDiv);
        if (motionOnParam != nullptr)
            onAtt = std::make_unique<juce::ParameterAttachment> (*motionOnParam, [this] (float) { syncFromParams(); });
        if (motionTileParam != nullptr)
            tileAtt = std::make_unique<juce::ParameterAttachment> (*motionTileParam, [this] (float) { syncFromParams(); });
        if (motionDivParam != nullptr)
            divAtt = std::make_unique<juce::ParameterAttachment> (*motionDivParam, [this] (float) { syncFromParams(); });
        syncFromParams();

        motionCombo.onChange = [this]
        {
            const int id = motionCombo.getSelectedId();
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
            resized();
            repaint();
        };

        // NOTE: do not use AudioProcessorValueTreeState::ComboBoxAttachment
        // here -- its constructor claims timeCombo.onChange internally, and
        // setting onChange afterward (as this used to) silently overwrites
        // that write-back, so picking a new item never reached the param.
        // Same manual pattern as motionCombo above instead.
        timeCombo.onChange = [this]
        {
            const int id = timeCombo.getSelectedId();
            if (id <= 0 || divAtt == nullptr || motionDivParam == nullptr) return;
            divAtt->setValueAsCompleteGesture (motionDivParam->convertTo0to1 ((float) (id - 1)));
            resized();
            repaint();
        };

        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Motion / Time");
        setHelpText ("Pick a modulation gesture and its tempo division");
    }

    ~MotionTimeRow() override
    {
        motionCombo.setLookAndFeel (nullptr);
        timeCombo.setLookAndFeel (nullptr);
    }

    void resized() override
    {
        const auto b = getLocalBounds();
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;
        const int tile = currentTile();
        const bool showTime = on && tile != 2; // Adlib Chop has no tempo division

        if (! showTime)
        {
            motionCombo.setBounds (b);
            timeCombo.setBounds (0, 0, 0, 0);
            return;
        }

        const float splitFrac = juce::jlimit (0.25f, 0.75f, motionTextWidthFrac());
        const int splitX = (int) ((float) b.getWidth() * splitFrac);
        motionCombo.setBounds (b.withWidth (splitX));
        timeCombo.setBounds (b.withX (splitX).withWidth (b.getWidth() - splitX));
    }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }

    void mouseDown (const juce::MouseEvent& e) override
    {
        if (timeCombo.getWidth() > 0 && e.position.x >= (float) timeCombo.getX())
            timeCombo.showPopup();
        else
            motionCombo.showPopup();
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds().toFloat();
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;

        g.setFont (displayFont (12.0f, false).withStyle (juce::Font::italic));
        g.setColour ((on ? t.amber() : kQuietInk).withAlpha (hover ? 1.0f : (on ? 0.95f : 0.88f)));
        g.drawText (currentText(), b, juce::Justification::centredLeft, false);
    }

private:
    int currentTile() const
    {
        if (motionTileParam == nullptr) return 0;
        return juce::jlimit (0, 3, juce::roundToInt (motionTileParam->convertFrom0to1 (motionTileParam->getValue())));
    }

    juce::String currentText() const
    {
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;
        if (! on) return "OFF";
        const auto motionWord = motionCombo.getText().toUpperCase();
        const int tile = currentTile();
        if (tile == 2) return motionWord; // Adlib Chop: no time suffix
        return motionWord + "  \xC2\xB7  " + timeCombo.getText().toUpperCase();
    }

    // Fraction of the row's width the motion word (+ separator) occupies, so
    // the two invisible combo hit-zones line up with the drawn text's split.
    float motionTextWidthFrac() const
    {
        const auto font = displayFont (12.0f, false).withStyle (juce::Font::italic);
        const auto motionWord = motionCombo.getText().toUpperCase() + "  \xC2\xB7  ";
        const float mw = juce::GlyphArrangement::getStringWidth (font, motionWord);
        const float full = juce::GlyphArrangement::getStringWidth (font, currentText());
        if (full < 1.0f) return 0.5f;
        return mw / full;
    }

    void syncFromParams()
    {
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;
        int id = 1;
        if (on && motionTileParam != nullptr)
            id = currentTile() + 2;
        if (motionCombo.getSelectedId() != id)
            motionCombo.setSelectedId (id, juce::dontSendNotification);
        resized();
        repaint();
    }

    static inline const juce::Colour kQuietInk { 0xffd9bcc4 };

    Theme t;
    SelectorLookAndFeel lookAndFeel;
    juce::ComboBox motionCombo;
    juce::ComboBox timeCombo;
    juce::RangedAudioParameter* motionOnParam = nullptr;
    juce::RangedAudioParameter* motionTileParam = nullptr;
    juce::RangedAudioParameter* motionDivParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> onAtt;
    std::unique_ptr<juce::ParameterAttachment> tileAtt;
    std::unique_ptr<juce::ParameterAttachment> divAtt;
    bool hover = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MotionTimeRow)
};

} // namespace trench::ui
