#pragma once

#include "SelectorLookAndFeel.h"
#include "Theme.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// A single small status chip that sits INSIDE the red screen (top-left,
// over the curve) — "OFF" or "RISER · 1/16". The screen is still not an
// editor: it draws only the curve (GraphDisplay) plus this one clickable
// chip. Left half of the chip's text = MOTION popup (Off/Riser/Breathe/
// Adlib Chop/Wobble), right half = TIME popup (musical division) — hidden
// entirely when there's no time to show (motion off, or Adlib Chop, which
// has no tempo division).
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
        motionCombo.addItem ("Chop", 4);
        motionCombo.addItem ("Wobble", 5);
        // "User" (an alt-drag-recorded custom motion) is not added here yet --
        // there is no recording mechanism behind it. Add it as item 6 once
        // that exists; until then this list only offers what's real.

        timeCombo.addItem ("1/4", 1);
        timeCombo.addItem ("1/8", 2);
        timeCombo.addItem ("1/8T", 3);
        timeCombo.addItem ("1/16", 4);
        timeCombo.addItem ("1/16T", 5);
        timeCombo.addItem ("1/32", 6);
        timeCombo.addItem ("1/2", 7);
        timeCombo.addItem ("1 BAR", 8);
        timeCombo.addItem ("2 BAR", 9);
        timeCombo.addItem ("4 BAR", 10);

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
        const auto chip = chipBounds();
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;
        const int tile = currentTile();
        const bool showTime = on && tile != 2; // Adlib Chop has no tempo division

        if (! showTime)
        {
            motionCombo.setBounds (chip);
            timeCombo.setBounds (0, 0, 0, 0);
            return;
        }

        const float splitFrac = juce::jlimit (0.25f, 0.75f, motionTextWidthFrac());
        const int splitX = chip.getX() + (int) ((float) chip.getWidth() * splitFrac);
        motionCombo.setBounds (chip.withRight (splitX));
        timeCombo.setBounds (chip.withLeft (splitX));
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
        const auto chip = chipBounds().toFloat();
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;
        const float radius = juce::jmin (5.0f, chip.getHeight() * 0.5f);

        // Small dark recessed badge on the glass -- quiet, not a card.
        g.setColour (juce::Colours::black.withAlpha (0.40f));
        g.fillRoundedRectangle (chip, radius);
        g.setColour (juce::Colours::black.withAlpha (0.55f));
        g.drawRoundedRectangle (chip.reduced (0.5f), radius, 1.0f);

        g.setFont (displayFont (11.0f, false).withStyle (juce::Font::italic));
        g.setColour ((on ? t.amber() : kQuietInk).withAlpha (hover ? 1.0f : (on ? 0.95f : 0.82f)));
        g.drawText (currentText(), chip.reduced (7.0f, 0.0f), juce::Justification::centredLeft, false);
    }

private:
    // The chip hugs its text content (padded), capped at this component's
    // assigned outer bounds -- it does not stretch to fill them.
    juce::Rectangle<int> chipBounds() const
    {
        const auto font = displayFont (11.0f, false).withStyle (juce::Font::italic);
        const float textW = juce::GlyphArrangement::getStringWidth (font, currentText());
        const int w = juce::jmin (getWidth(), (int) textW + 22);
        return { 0, 0, w, getHeight() };
    }

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

    // Fraction of the chip's width the motion word (+ separator) occupies,
    // so the two invisible combo hit-zones line up with the drawn text's
    // split.
    float motionTextWidthFrac() const
    {
        const auto font = displayFont (11.0f, false).withStyle (juce::Font::italic);
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

    static inline const juce::Colour kQuietInk { 0xffe9dfc6 };

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
