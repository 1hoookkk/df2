#pragma once

#include "SelectorLookAndFeel.h"
#include "Theme.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// The Modulation chip: one small clickable tag on the glass (bottom-left,
// over the curve). The locked UX (2026-07-17): the menu picks a TIME only —
// the MORPH wheel steers the sound, modulation is additive around it — plus
// one ORBIT toggle (the signature 2D move: morph on sin, press on cos).
// There is no character/verb list: the old RISE/BREATHE/CHOP names claimed
// personalities the engine ran under a different vocabulary.
//
// Honesty rule: everything this chip displays is DERIVED from the live
// parameters at paint time. No widget state, no invented fallbacks.
class MoveChip : public juce::Component,
                 private juce::Timer
{
public:
    // motionDiv choice order (TrenchParameters.cpp):
    // 0=1/4 1=1/8 2=1/8T 3=1/16 4=1/16T 5=1/32 6=1/2 7=1 BAR 8=2 BAR 9=4 BAR.
    // The menu lists every division, fast to slow, so the shown time is always
    // the REAL live one.
    struct TimeItem { const char* label; int divIdx; };
    // SIMPLIFIED (Tyson 2026-07-18, "simplify it make it fun"): the seven
    // musical core times only. The exotic divisions (1/32, triplets, 1/6,
    // 3/16, 5/16 — divIdx 2,4,5,10,11,12) stay reachable as host params and
    // still DISPLAY correctly if set there; the menu just stops listing them.
    static constexpr TimeItem kTimes[] = {
        { "1/16", 3 }, { "1/8", 1 }, { "1/4", 0 }, { "1/2", 6 },
        { "1 BAR", 7 }, { "2 BAR", 8 }, { "4 BAR", 9 },
    };

    MoveChip (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        motionOnParam   = apvts.getParameter (ParamID::motionOn);
        motionTileParam = apvts.getParameter (ParamID::motionTile);
        motionDivParam  = apvts.getParameter (ParamID::motionDiv);
        motionTgtMParam = apvts.getParameter (ParamID::motionTargetM);
        motionTgtQParam = apvts.getParameter (ParamID::motionTargetQ);
        moveOnParam     = apvts.getParameter (ParamID::moveOn);
        moveShapeParam  = apvts.getParameter (ParamID::moveShape);
        moveTimeParam   = apvts.getParameter (ParamID::moveTime);
        moveTensionParam = apvts.getParameter (ParamID::moveTension);
        moveRateParam   = apvts.getParameter (ParamID::moveRate);
        moveRiseParam   = apvts.getParameter (ParamID::moveRise);
        motionReactParam = apvts.getParameter (ParamID::motionReact);

        auto repaintOnChange = [this] (float) { repaint(); };
        for (auto* p : { motionOnParam, motionTileParam, motionDivParam,
                         moveOnParam, moveShapeParam, moveTimeParam })
            if (p != nullptr)
                atts.push_back (std::make_unique<juce::ParameterAttachment> (*p, repaintOnChange));

        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Modulation");
        setHelpText ("Pick a modulation time (the Morph wheel steers the sound), toggle ORBIT, or OFF");
    }

    ~MoveChip() override = default;

    // SEED's screen feedback: replace this chip's own text with "SIBLING"
    // for ~500ms, then revert to the real derived state (unchanged the whole
    // time -- this only overrides the DISPLAYED text).
    void flashSiblingLabel()
    {
        showingSibling = true;
        siblingElapsedMs = 0.0;
        startTimer (30);
        repaint();
    }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }

    void mouseDown (const juce::MouseEvent&) override
    {
        juce::PopupMenu m;
        m.setLookAndFeel (&lookAndFeel);
        const bool on = paramBool (motionOnParam);
        const int liveDiv = paramChoice (motionDivParam, 12);
        m.addItem (kIdOff, "OFF", true, ! on && ! orbitActive());
        m.addSeparator();
        for (int i = 0; i < (int) std::size (kTimes); ++i)
            m.addItem (kIdTimeBase + i, kTimes[(size_t) i].label, true,
                       on && kTimes[(size_t) i].divIdx == liveDiv);
        m.addSeparator();
        m.addItem (kIdOrbit, "ORBIT", moveShapeParam != nullptr, orbitActive());
        // RISE: arming a synced MOVE ramps depth 0->full over one TIME cycle,
        // then holds — the performed riser. Ignored in FREE (no clock to ride).
        m.addItem (kIdRise, "RISE", moveRiseParam != nullptr, paramBool (moveRiseParam));
        // FOLLOW (2026-07-18): env follow — the input's own level opens the
        // filter (react push, no clock). The third verb: times dance, RISE
        // builds, FOLLOW breathes.
        m.addItem (kIdFollow, "FOLLOW", motionReactParam != nullptr, followActive());
        // RATE rows retired from the menu (2026-07-18): AUTO derives the morph
        // approach time from the chosen division. The host param remains the
        // expert override.

        juce::Component::SafePointer<MoveChip> self (this);
        m.showMenuAsync (juce::PopupMenu::Options().withTargetComponent (this),
                         [self] (int id) { if (self != nullptr && id != 0) self->apply (id); });
    }

    void paint (juce::Graphics& g) override
    {
        const auto chip = getLocalBounds().toFloat();
        const bool on = paramBool (motionOnParam) || orbitActive();

        const float lampD = 5.5f;
        const auto lamp = juce::Rectangle<float> (chip.getX(),
                                                   chip.getCentreY() - lampD * 0.5f,
                                                   lampD, lampD);
        // The lamp is lit exactly when something is actually modulating.
        g.setColour (on ? t.rollerIllumination()
                        : t.rollerIllumination().darker (0.72f).withAlpha (0.82f));
        g.fillEllipse (lamp);
        g.setColour (juce::Colours::black.withAlpha (0.45f));
        g.drawEllipse (lamp, 0.7f);

        g.setFont (displayFont (9.6f, false).withExtraKerningFactor (0.018f));
        const auto area = chip.withTrimmedLeft (lampD + 6.0f);
        // Light ink: the tag prints on the dark teal display plate.
        g.setColour (juce::Colour (0xffe4f2ec).withAlpha ((hover || on) ? 1.0f : 0.92f));
        g.drawText (displayText(), area, juce::Justification::centredLeft, false);
    }

private:
    static constexpr int kIdOff = 1, kIdTimeBase = 100, kIdOrbit = 999, kIdRateBase = 1200, kIdRise = 1300, kIdFollow = 1400;
    static constexpr const char* kRateLabels[4] = { "RATE  AUTO", "RATE  SNAP", "RATE  TIGHT", "RATE  GLIDE" };

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

    bool orbitActive() const noexcept
    {
        return paramBool (moveOnParam) && paramChoice (moveShapeParam, 6) == kOrbitShape;
    }

    bool followActive() const noexcept
    {
        return motionReactParam != nullptr && motionReactParam->getValue() > 0.0005f;
    }

    juce::String liveTimeLabel() const
    {
        // Full division vocabulary — host-set exotics still display truthfully
        // even though the menu only lists the core seven.
        static constexpr const char* kDivLabels[13] = {
            "1/4", "1/8", "1/8T", "1/16", "1/16T", "1/32", "1/2",
            "1 BAR", "2 BAR", "4 BAR", "3/16", "5/16", "1/6" };
        return kDivLabels[paramChoice (motionDivParam, 12)];
    }

    void apply (int id)
    {
        auto write = [] (juce::RangedAudioParameter* p, float denorm)
        {
            if (p == nullptr) return;
            p->beginChangeGesture();
            p->setValueNotifyingHost (p->convertTo0to1 (denorm));
            p->endChangeGesture();
        };

        if (id == kIdOff)
        {
            write (motionOnParam, 0.0f);
            write (moveOnParam, 0.0f);
            write (motionReactParam, 0.0f);   // OFF means everything, FOLLOW included
            followArmedMotion = false;
        }
        else if (id == kIdOrbit)
        {
            const bool enable = ! orbitActive();
            if (enable)
            {
                write (moveShapeParam, (float) kOrbitShape);
                write (moveTimeParam, (float) moveTimeForDiv (paramChoice (motionDivParam, 12)));
                // ORBIT is a toggle, not a fader: the gesture engine scales by
                // moveTension, and nothing else sets it now that Page 2 is
                // retired — without this the toggle ran at depth 0 (silent).
                write (moveTensionParam, 1.0f);
            }
            write (moveOnParam, enable ? 1.0f : 0.0f);
        }
        else if (id >= kIdRateBase && id < kIdRateBase + 4)
        {
            write (moveRateParam, (float) (id - kIdRateBase));
        }
        else if (id == kIdRise)
        {
            write (moveRiseParam, paramBool (moveRiseParam) ? 0.0f : 1.0f);
        }
        else if (id == kIdFollow)
        {
            const bool enable = ! followActive();
            write (motionReactParam, enable ? 1.0f : 0.0f);
            if (enable && ! paramBool (motionOnParam))
            {
                // arm the motion path with a NEUTRAL pattern so only the
                // react push moves — pure env follow, no clocked dance.
                write (motionTileParam, (float) kBreatheTile);
                write (motionTgtMParam, 0.0f);
                write (motionTgtQParam, 0.0f);
                write (motionOnParam, 1.0f);
                followArmedMotion = true;
            }
            else if (! enable && followArmedMotion)
            {
                write (motionOnParam, 0.0f);   // we armed it only for FOLLOW
                followArmedMotion = false;
            }
        }
        else if (id >= kIdTimeBase && id < kIdTimeBase + (int) std::size (kTimes))
        {
            const int div = kTimes[(size_t) (id - kIdTimeBase)].divIdx;
            // Time is the menu's whole job: a neutral additive cycle around
            // the wheels' base values (Breathe carrier, morph target). The
            // character comes from where the MORPH wheel sits, not a verb.
            write (motionTileParam, (float) kBreatheTile);
            write (motionDivParam, (float) div);
            write (motionTgtMParam, 1.0f);
            write (motionTgtQParam, 0.0f);
            write (motionOnParam, 1.0f);
            write (moveRateParam, 0.0f);   // RATE AUTO — the menu no longer offers overrides
            if (orbitActive())
                write (moveTimeParam, (float) moveTimeForDiv (div)); // orbit follows the clock
        }
        repaint();
    }

    // moveTime choices: 0=FREE 1=1/4 2=1/2 3=1 BAR 4=2 BAR 5=4 BAR 6=8 BAR.
    // Divisions faster than 1/4 clamp to 1/4 — the gesture engine's floor.
    static int moveTimeForDiv (int div) noexcept
    {
        switch (div)
        {
            case 6:  return 2;   // 1/2
            case 7:  return 3;   // 1 BAR
            case 8:  return 4;   // 2 BAR
            case 9:  return 5;   // 4 BAR
            default: return 1;   // 1/4 and everything faster
        }
    }

    juce::String displayText() const
    {
        if (showingSibling)
            return "Modulation  SIBLING";
        juce::String s ("Modulation");
        if (paramBool (motionOnParam))
            s << "  " << liveTimeLabel();
        if (orbitActive())
            s << "  \xC2\xB7 ORBIT";
        if (followActive())
            s << "  \xC2\xB7 FOLLOW";
        return juce::String (juce::CharPointer_UTF8 (s.toRawUTF8()));
    }

    void timerCallback() override
    {
        siblingElapsedMs += 30.0;
        if (siblingElapsedMs >= kSiblingFlashMs)
        {
            showingSibling = false;
            stopTimer();
        }
        repaint();
    }

    static constexpr int kBreatheTile = 1;   // motionTile choice: Riser,Breathe,Chop,Wobble,User
    static constexpr int kOrbitShape  = 3;   // moveShape choice: Rise,Fall,Pulse,Orbit,...
    static constexpr double kSiblingFlashMs = 500.0; // the direction's exact number

    Theme t;
    SelectorLookAndFeel lookAndFeel;
    juce::RangedAudioParameter* motionOnParam = nullptr;
    juce::RangedAudioParameter* motionTileParam = nullptr;
    juce::RangedAudioParameter* motionDivParam = nullptr;
    juce::RangedAudioParameter* motionTgtMParam = nullptr;
    juce::RangedAudioParameter* motionTgtQParam = nullptr;
    juce::RangedAudioParameter* moveOnParam = nullptr;
    juce::RangedAudioParameter* moveShapeParam = nullptr;
    juce::RangedAudioParameter* moveTimeParam = nullptr;
    juce::RangedAudioParameter* moveTensionParam = nullptr;
    juce::RangedAudioParameter* moveRateParam = nullptr;
    juce::RangedAudioParameter* moveRiseParam = nullptr;
    std::vector<std::unique_ptr<juce::ParameterAttachment>> atts;
    juce::RangedAudioParameter* motionReactParam = nullptr;
    bool followArmedMotion = false;
    bool hover = false;
    bool showingSibling = false;
    double siblingElapsedMs = 0.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MoveChip)
};

} // namespace trench::ui
