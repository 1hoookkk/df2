#pragma once

#include "SelectorLookAndFeel.h"
#include "Theme.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// The MOVE chip: one small clickable status badge inside the red screen
// (top-left, over the curve). There is no free motion/time matrix -- this
// is ONE curated list of exactly 9 named states, each an atomic (tile,
// division) pair written together. Clicking the chip opens that list.
//
//   OFF
//   RISE · 1 BAR       RISE · 2 BAR
//   BREATHE · 2 BAR
//   CHOP · 1/16        CHOP · 1/32
//   WOBBLE · 1/8       WOBBLE · 1/16
//   USER · 1 BAR       (alt-drag Morph to teach it; silent until recorded)
//
// TIME is never independently adjustable and never baked per-gesture in the
// engine -- it's just part of which named state is selected here.
class MoveChip : public juce::Component,
                 private juce::Timer
{
public:
    struct State
    {
        const char* label;
        int tile;    // -1 = OFF (motionOn=0, tile untouched)
        int divIdx;  // ignored when tile == -1
    };

    // tile: 0=Riser 1=Breathe 2=Chop 3=Wobble 4=User (matches ParamID::motionTile).
    // divIdx: matches ParamID::motionDiv's choice list (TrenchParameters.cpp).
    static constexpr State kStates[9] = {
        { "OFF",              -1, 0 },
        { "RISE \xC2\xB7 1 BAR",     0, 7 },
        { "RISE \xC2\xB7 2 BAR",     0, 8 },
        { "BREATHE \xC2\xB7 2 BAR",  1, 8 },
        { "CHOP \xC2\xB7 1/16",      2, 3 },
        { "CHOP \xC2\xB7 1/32",      2, 5 },
        { "WOBBLE \xC2\xB7 1/8",     3, 1 },
        { "WOBBLE \xC2\xB7 1/16",    3, 3 },
        { "USER \xC2\xB7 1 BAR",     4, 7 },
    };

    MoveChip (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        motionOnParam   = apvts.getParameter (ParamID::motionOn);
        motionTileParam = apvts.getParameter (ParamID::motionTile);
        motionDivParam  = apvts.getParameter (ParamID::motionDiv);

        combo.setLookAndFeel (&lookAndFeel);
        combo.setInterceptsMouseClicks (false, false);
        for (auto colourId : { juce::ComboBox::backgroundColourId, juce::ComboBox::outlineColourId,
                               juce::ComboBox::buttonColourId, juce::ComboBox::arrowColourId,
                               juce::ComboBox::textColourId })
            combo.setColour (colourId, juce::Colours::transparentBlack);
        combo.setTextWhenNothingSelected ({});
        addAndMakeVisible (combo);
        for (int i = 0; i < (int) std::size (kStates); ++i)
            combo.addItem (kStates[(size_t) i].label, i + 1);

        if (motionOnParam != nullptr)
            onAtt = std::make_unique<juce::ParameterAttachment> (*motionOnParam, [this] (float) { syncFromParams(); });
        if (motionTileParam != nullptr)
            tileAtt = std::make_unique<juce::ParameterAttachment> (*motionTileParam, [this] (float) { syncFromParams(); });
        if (motionDivParam != nullptr)
            divAtt = std::make_unique<juce::ParameterAttachment> (*motionDivParam, [this] (float) { syncFromParams(); });
        syncFromParams();

        combo.onChange = [this]
        {
            const int id = combo.getSelectedId();
            if (id <= 0 || id > (int) std::size (kStates)) return;
            const auto& s = kStates[(size_t) (id - 1)];
            if (onAtt == nullptr || tileAtt == nullptr || divAtt == nullptr || motionTileParam == nullptr || motionDivParam == nullptr)
                return;
            if (s.tile < 0)
            {
                onAtt->setValueAsCompleteGesture (0.0f);
            }
            else
            {
                tileAtt->setValueAsCompleteGesture (motionTileParam->convertTo0to1 ((float) s.tile));
                divAtt->setValueAsCompleteGesture (motionDivParam->convertTo0to1 ((float) s.divIdx));
                onAtt->setValueAsCompleteGesture (1.0f);
            }
            repaint();
        };

        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Move");
        setHelpText ("Pick a curated motion + tempo, or OFF");
    }

    ~MoveChip() override { combo.setLookAndFeel (nullptr); }

    // SEED's screen feedback: replace this chip's own text with "SIBLING"
    // for ~500ms, then revert to whatever MOVE state was actually selected
    // (unchanged the whole time -- this only overrides the DISPLAYED text).
    void flashSiblingLabel()
    {
        showingSibling = true;
        siblingElapsedMs = 0.0;
        startTimer (30);
        repaint();
    }

    void resized() override { combo.setBounds (chipBounds()); }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }
    void mouseDown  (const juce::MouseEvent&) override { combo.showPopup(); repaint(); }

    void paint (juce::Graphics& g) override
    {
        const auto chip = chipBounds().toFloat();
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;
        const float radius = juce::jmin (5.0f, chip.getHeight() * 0.5f);

        g.setColour (juce::Colours::black.withAlpha (0.40f));
        g.fillRoundedRectangle (chip, radius);
        g.setColour (juce::Colours::black.withAlpha (0.55f));
        g.drawRoundedRectangle (chip.reduced (0.5f), radius, 1.0f);

        g.setFont (displayFont (11.0f, false).withStyle (juce::Font::italic));
        g.setColour ((on ? t.amber() : kQuietInk).withAlpha (hover ? 1.0f : (on ? 0.95f : 0.82f)));
        g.drawText (displayText(), chip.reduced (7.0f, 0.0f), juce::Justification::centredLeft, false);
    }

private:
    juce::String displayText() const { return showingSibling ? "SIBLING" : combo.getText(); }

    // The chip hugs its text content (padded), capped at this component's
    // assigned outer bounds -- it does not stretch to fill them.
    juce::Rectangle<int> chipBounds() const
    {
        const auto font = displayFont (11.0f, false).withStyle (juce::Font::italic);
        const float textW = juce::GlyphArrangement::getStringWidth (font, displayText());
        const int w = juce::jmin (getWidth(), (int) textW + 22);
        return { 0, 0, w, getHeight() };
    }

    void syncFromParams()
    {
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;
        int id = 1; // OFF
        if (on && motionTileParam != nullptr && motionDivParam != nullptr)
        {
            const int tile = juce::jlimit (0, 4, juce::roundToInt (motionTileParam->convertFrom0to1 (motionTileParam->getValue())));
            const int div  = juce::jlimit (0, 9, juce::roundToInt (motionDivParam->convertFrom0to1 (motionDivParam->getValue())));
            int tileOnlyFallback = -1;
            for (int i = 1; i < (int) std::size (kStates); ++i)
            {
                if (kStates[(size_t) i].tile != tile) continue;
                if (tileOnlyFallback < 0) tileOnlyFallback = i + 1;
                if (kStates[(size_t) i].divIdx == div) { id = i + 1; tileOnlyFallback = -1; break; }
            }
            // Live tile/div came from outside the curated list (old session
            // state, direct host automation) -- show the tile's first curated
            // time rather than falsely reading OFF while motion is armed.
            if (tileOnlyFallback > 0) id = tileOnlyFallback;
        }
        if (combo.getSelectedId() != id)
            combo.setSelectedId (id, juce::dontSendNotification);
        resized();
        repaint();
    }

    void timerCallback() override
    {
        siblingElapsedMs += 30.0;
        if (siblingElapsedMs >= kSiblingFlashMs)
        {
            showingSibling = false;
            stopTimer();
            resized();
        }
        repaint();
    }

    static inline const juce::Colour kQuietInk { 0xffe9dfc6 };
    static constexpr double kSiblingFlashMs = 500.0; // the direction's exact number

    Theme t;
    SelectorLookAndFeel lookAndFeel;
    juce::ComboBox combo;
    juce::RangedAudioParameter* motionOnParam = nullptr;
    juce::RangedAudioParameter* motionTileParam = nullptr;
    juce::RangedAudioParameter* motionDivParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> onAtt;
    std::unique_ptr<juce::ParameterAttachment> tileAtt;
    std::unique_ptr<juce::ParameterAttachment> divAtt;
    bool hover = false;
    bool showingSibling = false;
    double siblingElapsedMs = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MoveChip)
};

} // namespace trench::ui
