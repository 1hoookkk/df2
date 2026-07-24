#pragma once
#include "SelectorLookAndFeel.h"
#include "Theme.h"
#include "../parameters/TrenchParameters.h"
#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>
namespace trench::ui
{
// The "Modulation" chip: arms trench::MorphMod. One familiar control — click
// opens a rate dropdown. AUTO (the input plays the wheel) sits first, then
// synced note rates (no 1/32: too jarring to hand a user), RISE, and OFF.
class MoveChip : public juce::Component,
                 private juce::Timer
{
public:
    struct TimeItem { const char* label; int noteIdx; };
    // Menu order fast -> slow. modNote index order is
    // {4bar,2bar,1bar,1/2,1/4,1/8,1/16,1/32}.
    // fast -> slow, odd rhythmic values included (1/32 stays banned)
    static constexpr TimeItem kTimes[] = {
        { "1/16", 6 }, { "1/12", 12 }, { "1/8", 5 }, { "1/6", 11 },
        { "3/16", 9 }, { "1/4", 4 }, { "5/16", 10 }, { "3/8", 8 },
        { "7/16", 14 }, { "1/2", 3 }, { "5/8", 13 },
        { "1 BAR", 2 }, { "2 BAR", 1 }, { "4 BAR", 0 },
    };
    MoveChip (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        modOnParam      = apvts.getParameter (ParamID::modOn);
        modTriggerParam = apvts.getParameter (ParamID::modTrigger);
        modNoteParam    = apvts.getParameter (ParamID::modNote);
        modSyncParam    = apvts.getParameter (ParamID::modSync);
        modFeelParam    = apvts.getParameter (ParamID::modFeel);
        auto repaintOnChange = [this] (float) { repaint(); };
        for (auto* p : { modOnParam, modTriggerParam, modNoteParam, modFeelParam })
            if (p != nullptr)
                atts.push_back (std::make_unique<juce::ParameterAttachment> (*p, repaintOnChange));
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Modulation");
        setHelpText ("Pick a modulation rate - AUTO follows the input, note values sync, RISE climbs once");
    }
    ~MoveChip() override = default;
    std::function<void (const juce::String&)> onAnnounce;
    void flashSiblingLabel()
    {
        showingSibling = true;
        siblingElapsedMs = 0.0;
        startTimer (30);
        repaint();
    }
    // Only the readout is the control; the rest of the row stays glass (SLAM).
    bool hitTest (int x, int y) override
    {
        juce::ignoreUnused (y);
        return x < kCollapsedWidth;
    }
    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }
    void mouseUp (const juce::MouseEvent&) override
    {
        juce::PopupMenu m;
        lookAndFeel.itemFontSize = 11.5f;
        lookAndFeel.itemHeight = 19;
        m.setLookAndFeel (&lookAndFeel);
        m.addItem (kIdAuto, "AUTO", true, followActive());
        m.addSeparator();
        for (int i = 0; i < (int) std::size (kTimes); ++i)
            m.addItem (kIdTimeBase + i, kTimes[(size_t) i].label, true,
                       syncActive() && kTimes[(size_t) i].noteIdx == paramChoice (modNoteParam, 7));
        m.addSeparator();
        m.addItem (kIdRise, "RISE", true, riserActive());
        m.addItem (kIdOff, "OFF", true, ! paramBool (modOnParam));
        juce::Component::SafePointer<MoveChip> self (this);
        m.showMenuAsync (juce::PopupMenu::Options().withTargetComponent (this),
                         [self] (int id)
                         {
                             if (self == nullptr || id == 0)
                                 return;
                             self->apply (id);
                             if (self->onAnnounce)
                                 self->onAnnounce (self->announceLabel (id));
                         });
    }
    void paint (juce::Graphics& g) override
    {
        const bool on = paramBool (modOnParam);
        const auto b = getLocalBounds().toFloat();
        const auto lampBase = t.modulationLamp();
        const auto ink = juce::Colour (0xffe4f2ec);
        const float lampD = 4.5f;
        const auto lamp = juce::Rectangle<float> (b.getX(), b.getCentreY() - lampD * 0.5f,
                                                  lampD, lampD);
        if (on)
        {
            // Lit lamp gets a tight halo — on/off reads at a glance, quietly.
            g.setColour (lampBase.withAlpha (0.20f));
            g.fillEllipse (lamp.expanded (1.8f));
        }
        g.setColour (on ? lampBase : lampBase.darker (0.72f).withAlpha (0.82f));
        g.fillEllipse (lamp);
        g.setColour (juce::Colours::black.withAlpha (0.45f));
        g.drawEllipse (lamp, 0.7f);
        const auto font = displayFont (9.8f, false).withExtraKerningFactor (0.018f);
        g.setFont (font);
        const auto area = b.withTrimmedLeft (lampD + 6.0f);
        if (showingSibling)
        {
            g.setColour (ink.withAlpha (0.85f));
            g.drawText ("Modulation  SIBLING", area.toNearestInt(),
                        juce::Justification::centredLeft, false);
            return;
        }
        // "Modulation" in ink; the STATE word carries the on/off truth —
        // lamp-teal when armed, an explicit dim OFF when not.
        const juce::String label ("Modulation");
        g.setColour (ink.withAlpha (hover ? 0.80f : (on ? 0.58f : 0.42f)));
        g.drawText (label, area.toNearestInt(), juce::Justification::centredLeft, false);
        const float lw = juce::GlyphArrangement::getStringWidth (font, label) + 8.0f;
        const juce::String state = on ? (syncActive() ? liveTimeLabel()
                                       : riserActive() ? "RISE " + liveTimeLabel()
                                       : "AUTO")
                                      : juce::String ("OFF");
        g.setColour (on ? lampBase.withAlpha (0.80f) : ink.withAlpha (0.32f));
        g.drawText (state, area.withTrimmedLeft (lw).toNearestInt(),
                    juce::Justification::centredLeft, false);
    }
private:
    static constexpr int kIdOff = 1, kIdAuto = 2, kIdRise = 3, kIdTimeBase = 100;
    static bool paramBool (const juce::RangedAudioParameter* p) noexcept
    {
        return p != nullptr && p->getValue() > 0.5f;
    }
    static int paramChoice (const juce::RangedAudioParameter* p, int maxIdx) noexcept
    {
        if (p == nullptr) return 0;
        return juce::jlimit (0, maxIdx,
                             juce::roundToInt (p->convertFrom0to1 (p->getValue())));
    }
    // Face param index order is ENV,SYNC,RISER (0,1,2) — not trench::ModTrigger's.
    int triggerIdx() const noexcept { return paramChoice (modTriggerParam, 2); }
    bool syncActive()   const noexcept { return paramBool (modOnParam) && triggerIdx() == 1; }
    bool riserActive()  const noexcept { return paramBool (modOnParam) && triggerIdx() == 2; }
    bool followActive() const noexcept { return paramBool (modOnParam) && triggerIdx() == 0; }
    void write (juce::RangedAudioParameter* p, float denorm)
    {
        if (p == nullptr) return;
        p->beginChangeGesture();
        p->setValueNotifyingHost (p->convertTo0to1 (denorm));
        p->endChangeGesture();
    }
    void apply (int id)
    {
        if (id == kIdOff)
        {
            write (modOnParam, 0.0f);
        }
        else if (id == kIdAuto)
        {
            write (modOnParam, 1.0f);
            write (modTriggerParam, 0.0f);   // ENV
        }
        else if (id == kIdRise)
        {
            write (modOnParam, 1.0f);
            write (modTriggerParam, 2.0f);   // RISER
        }
        else if (id >= kIdTimeBase && id < kIdTimeBase + (int) std::size (kTimes))
        {
            write (modOnParam, 1.0f);
            write (modTriggerParam, 1.0f);   // SYNC
            write (modSyncParam, 0.0f);      // host-locked
            write (modNoteParam, (float) kTimes[(size_t) (id - kIdTimeBase)].noteIdx);
        }
        repaint();
    }
    juce::String feelSuffix() const
    {
        const int feel = paramChoice (modFeelParam, 2);
        if (paramChoice (modNoteParam, 7) < 3)   // bars ignore feel
            return {};
        if (feel == 1) return "T";
        if (feel == 2) return juce::String::fromUTF8 ("\xc2\xb7");
        return {};
    }
    juce::String liveTimeLabel() const
    {
        const int note = paramChoice (modNoteParam, 7);
        if (note == 7) return "1/32" + feelSuffix();   // host-automated only
        for (const auto& item : kTimes)
            if (item.noteIdx == note)
                return item.label + feelSuffix();
        return {};
    }
    juce::String announceLabel (int id) const
    {
        if (id == kIdOff)  return "MODULATION OFF";
        if (id == kIdAuto) return "AUTO";
        if (id == kIdRise) return "RISE " + liveTimeLabel();
        if (id >= kIdTimeBase && id < kIdTimeBase + (int) std::size (kTimes))
            return "MODULATION " + liveTimeLabel();
        return {};
    }
    void timerCallback() override
    {
        if (showingSibling)
        {
            siblingElapsedMs += 30.0;
            if (siblingElapsedMs >= kSiblingFlashMs)
                showingSibling = false;
            repaint();
        }
        else
        {
            stopTimer();
        }
    }
    static constexpr int kCollapsedWidth = 178;
    static constexpr double kSiblingFlashMs = 500.0;
    Theme t;
    SelectorLookAndFeel lookAndFeel;
    juce::RangedAudioParameter* modOnParam = nullptr;
    juce::RangedAudioParameter* modTriggerParam = nullptr;
    juce::RangedAudioParameter* modNoteParam = nullptr;
    juce::RangedAudioParameter* modSyncParam = nullptr;
    juce::RangedAudioParameter* modFeelParam = nullptr;
    std::vector<std::unique_ptr<juce::ParameterAttachment>> atts;
    bool hover = false;
    bool showingSibling = false;
    double siblingElapsedMs = 0.0;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MoveChip)
};
}
