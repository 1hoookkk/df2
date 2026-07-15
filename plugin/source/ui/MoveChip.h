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
        bool tgtM;   // the preset PACKS its target: morph always moves...
        bool tgtQ;   // ...Q rides along only on presets where it's musical
        float fiveD; // QSound SPACE depth 0..1 (0 = none). ORBIT sets it > 0.
    };

    // tile: 0=Riser 1=Breathe 2=Chop 3=Wobble 4=User (matches ParamID::motionTile).
    // divIdx: motionDiv choice list order -> 0=1/4 1=1/8 2=1/8T 3=1/16 4=1/16T
    //         5=1/32 6=1/2 7=1 BAR 8=2 BAR 9=4 BAR (TrenchParameters.cpp).
    // tgtM/tgtQ: which wheel(s) this preset sweeps (written to motionTargetM/Q).
    // One authored preset per rate up to 4 bars — the list IS the rate control.
    // Each verb gets its musical rate band; morph always moves, Q rides Wobble.
    // ONE modulation, selectable per TIME. tile is fixed to a smooth morph
    // sweep (1=Breathe) as the default shape; recording the Morph slider
    // overwrites that shape with your own gesture. TIME is the only dimension.
    static constexpr State kStates[] = {
        { "OFF",     -1, 0, false, false, 0.0f },
        { "1/32",     1, 5, true,  false, 0.0f },
        { "1/16",     1, 3, true,  false, 0.0f },
        { "1/8",      1, 1, true,  false, 0.0f },
        { "1/4",      1, 0, true,  false, 0.0f },
        { "1/2",      1, 6, true,  false, 0.0f },
        { "1 BAR",    1, 7, true,  false, 0.0f },
        { "2 BAR",    1, 8, true,  false, 0.0f },
        { "4 BAR",    1, 9, true,  false, 0.0f },
        // ORBIT — the QSound showcase: a 2-bar morph modulation that ALSO orbits
        // the head (fiveD engages QSound; pan is tempo-locked in the processor).
        // The one place QSound is used.
        { "ORBIT",    1, 8, true,  false, 0.7f },
    };

    MoveChip (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        motionOnParam   = apvts.getParameter (ParamID::motionOn);
        motionTileParam = apvts.getParameter (ParamID::motionTile);
        motionDivParam  = apvts.getParameter (ParamID::motionDiv);
        motionTgtMParam = apvts.getParameter (ParamID::motionTargetM);
        motionTgtQParam = apvts.getParameter (ParamID::motionTargetQ);
        fiveDParam      = apvts.getParameter (ParamID::fiveD);

        combo.setLookAndFeel (&lookAndFeel);
        combo.setInterceptsMouseClicks (false, false);
        combo.setWantsKeyboardFocus (false);   // don't steal keys from the host
        for (auto colourId : { juce::ComboBox::backgroundColourId, juce::ComboBox::outlineColourId,
                               juce::ComboBox::buttonColourId, juce::ComboBox::arrowColourId,
                               juce::ComboBox::textColourId })
            combo.setColour (colourId, juce::Colours::transparentBlack);
        combo.setTextWhenNothingSelected ({});
        addAndMakeVisible (combo);
        // Labels embed a UTF-8 middle dot (0xC2 0xB7); decode explicitly so it
        // renders as "·" and not the "Â·" mojibake of a raw-byte interpretation.
        for (int i = 0; i < (int) std::size (kStates); ++i)
            combo.addItem (juce::String (juce::CharPointer_UTF8 (kStates[(size_t) i].label)), i + 1);

        if (motionOnParam != nullptr)
            onAtt = std::make_unique<juce::ParameterAttachment> (*motionOnParam, [this] (float) { syncFromParams(); });
        if (motionTileParam != nullptr)
            tileAtt = std::make_unique<juce::ParameterAttachment> (*motionTileParam, [this] (float) { syncFromParams(); });
        if (motionDivParam != nullptr)
            divAtt = std::make_unique<juce::ParameterAttachment> (*motionDivParam, [this] (float) { syncFromParams(); });
        // Target attachments carry no display state — they only let the preset
        // WRITE the packed M/Q target with a proper gesture.
        if (motionTgtMParam != nullptr)
            tgtMAtt = std::make_unique<juce::ParameterAttachment> (*motionTgtMParam, [] (float) {});
        if (motionTgtQParam != nullptr)
            tgtQAtt = std::make_unique<juce::ParameterAttachment> (*motionTgtQParam, [] (float) {});
        // ORBIT selection engages QSound via SPACE; re-sync the chip if it changes.
        if (fiveDParam != nullptr)
            fiveDAtt = std::make_unique<juce::ParameterAttachment> (*fiveDParam, [this] (float) { syncFromParams(); });
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
            // Preset packs the M/Q target — write it alongside tile/div/on.
            if (tgtMAtt != nullptr) tgtMAtt->setValueAsCompleteGesture (s.tgtM ? 1.0f : 0.0f);
            if (tgtQAtt != nullptr) tgtQAtt->setValueAsCompleteGesture (s.tgtQ ? 1.0f : 0.0f);
            // ORBIT engages QSound (SPACE > 0); every other state clears it.
            if (fiveDAtt != nullptr && fiveDParam != nullptr)
                fiveDAtt->setValueAsCompleteGesture (fiveDParam->convertTo0to1 (s.fiveD));
            repaint();
        };

        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Modulation");
        setHelpText ("Pick a modulation time, or OFF");
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
        // The reference builds' "Modulation" tag (IMG_5895/5812): a small lamp
        // dot + one dim word printed on the glass. No pill, no switch graphic —
        // the popup still opens on click.
        const auto chip = chipBounds().toFloat();
        const bool on = motionOnParam != nullptr && motionOnParam->getValue() > 0.5f;

        const float lampD = 5.5f;
        const auto lamp = juce::Rectangle<float> (chip.getX(),
                                                   chip.getCentreY() - lampD * 0.5f,
                                                   lampD, lampD);
        // The active lamp uses the same malachite family as the trace/wheel.
        g.setColour (on ? t.amber() : t.accent().darker (0.72f).withAlpha (0.82f));
        g.fillEllipse (lamp);
        g.setColour (juce::Colours::black.withAlpha (0.45f));
        g.drawEllipse (lamp, 0.7f);

        // A live selection ON the glass: lamp + "MODULATION <choice>" + a chevron,
        // in bright phosphor so it reads as a clickable selector, not a faint label.
        auto textArea = chip.withTrimmedLeft (lampD + 7.0f);
        g.setFont (displayFont (12.5f, false));
        const juce::String label = "MODULATION  " + (showingSibling ? juce::String ("SIBLING") : displayText());
        g.setColour (t.curveColour().withAlpha (hover ? 1.0f : 0.9f));
        g.drawText (label, textArea, juce::Justification::centredLeft, false);

        // selection chevron so it reads as a dropdown you can change
        const float tw = juce::GlyphArrangement::getStringWidth (g.getCurrentFont(), label);
        const auto chev = juce::Rectangle<float> (textArea.getX() + tw + 6.0f,
                                                  chip.getCentreY() - 1.5f, 7.0f, 4.0f);
        if (chev.getRight() <= chip.getRight())
        {
            juce::Path p;
            p.startNewSubPath (chev.getX(), chev.getY());
            p.lineTo (chev.getCentreX(), chev.getBottom());
            p.lineTo (chev.getRight(), chev.getY());
            g.strokePath (p, juce::PathStrokeType (1.2f));
        }
    }

private:
    juce::String displayText() const { return showingSibling ? "SIBLING" : combo.getText(); }

    juce::Rectangle<int> chipBounds() const
    {
        return getLocalBounds();
    }

    void syncFromParams()
    {
        // ORBIT is the only state that engages QSound (SPACE > 0). Detect it first
        // so it isn't read as the time entry that shares its tile/div.
        if (fiveDParam != nullptr && fiveDParam->getValue() > 0.001f)
        {
            const int orbitId = (int) std::size (kStates); // ORBIT = last entry
            if (combo.getSelectedId() != orbitId)
                combo.setSelectedId (orbitId, juce::dontSendNotification);
            resized();
            repaint();
            return;
        }
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
    juce::RangedAudioParameter* motionTgtMParam = nullptr;
    juce::RangedAudioParameter* motionTgtQParam = nullptr;
    juce::RangedAudioParameter* fiveDParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> onAtt;
    std::unique_ptr<juce::ParameterAttachment> tileAtt;
    std::unique_ptr<juce::ParameterAttachment> divAtt;
    std::unique_ptr<juce::ParameterAttachment> tgtMAtt;
    std::unique_ptr<juce::ParameterAttachment> tgtQAtt;
    std::unique_ptr<juce::ParameterAttachment> fiveDAtt;
    bool hover = false;
    bool showingSibling = false;
    double siblingElapsedMs = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MoveChip)
};

} // namespace trench::ui
