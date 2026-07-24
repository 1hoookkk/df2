#pragma once
#include "Theme.h"
#include "../parameters/TrenchParameters.h"
#include <juce_audio_processors/juce_audio_processors.h>
namespace trench::ui
{
class KeyframeButton : public juce::Component,
                       public juce::SettableTooltipClient
{
public:
    KeyframeButton (juce::AudioProcessorValueTreeState& state,
                    juce::String wheelParamId,
                    juce::String onId, juce::String aId, juce::String bId,
                    juce::String barsId, juce::String modeId,
                    const Theme& theme)
        : apvts (state), wheelParam (std::move (wheelParamId)),
          onP (std::move (onId)), aP (std::move (aId)), bP (std::move (bId)),
          barsP (std::move (barsId)), modeP (std::move (modeId)), t (theme)
    {
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        if (getBool (onP)) state_ = State::looping;
        refreshTooltip();
    }
    void paint (juce::Graphics& g) override
    {
        auto r = getLocalBounds().toFloat().reduced (0.5f);
        const float rad = 3.5f;
        g.setColour (juce::Colour (0xff211c16));
        g.fillRoundedRectangle (r, rad);
        g.setColour (juce::Colour (0xff5a4f3d).withAlpha (0.75f));
        g.drawRoundedRectangle (r.reduced (0.5f), rad, 1.0f);
        const juce::Colour amber { 0xffe7a53a };
        const juce::Colour rec   { 0xffcf4436 };
        auto lamp = juce::Rectangle<float> (7.0f, 7.0f)
                        .withCentre ({ r.getX() + 9.0f, r.getCentreY() });
        juce::Colour lampC = state_ == State::looping ? rec
                           : state_ == State::armed   ? amber
                           : juce::Colour (0xff7d6e52).withAlpha (hover ? 0.8f : 0.45f);
        g.setColour (lampC);
        g.fillEllipse (lamp);
        if (state_ != State::idle)
        {
            g.setColour (lampC.withAlpha (0.25f));
            g.fillEllipse (lamp.expanded (2.5f));
        }
        auto textArea = r.withTrimmedLeft (18.0f).reduced (2.0f, 0.0f);
        const juce::String head = state_ == State::armed ? "SET B"
                                : state_ == State::looping ? "REC" : "KEY";
        const juce::String info = choice (barsP) + " " + shapeShort();
        g.setFont (juce::Font (juce::FontOptions (9.5f, juce::Font::bold)));
        g.setColour (state_ == State::idle ? amber.withAlpha (0.55f) : amber);
        g.drawText (head, textArea.removeFromTop (textArea.getHeight() * 0.52f),
                    juce::Justification::centredLeft, false);
        g.setFont (juce::Font (juce::FontOptions (8.5f)));
        g.setColour (amber.withAlpha (0.7f));
        g.drawText (info, textArea, juce::Justification::centredLeft, false);
    }
    juce::String choice (const juce::String& id) const
    {
        if (auto* p = dynamic_cast<juce::AudioParameterChoice*> (apvts.getParameter (id)))
            return p->getCurrentChoiceName();
        return {};
    }
    juce::String shapeShort() const
    {
        auto s = choice (modeP);
        return s.isEmpty() ? juce::String() : s.substring (0, 4).toUpperCase();
    }
    void mouseEnter (const juce::MouseEvent&) override { hover = true;  repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }
    void mouseDown (const juce::MouseEvent& e) override
    {
        if (e.mods.isPopupMenu()) { cycleMode(); return; }
        switch (state_)
        {
            case State::idle:
                setFloat (aP, wheelValue());
                state_ = State::armed;
                break;
            case State::armed:
                setFloat (bP, wheelValue());
                setBool (onP, true);
                state_ = State::looping;
                break;
            case State::looping:
                setBool (onP, false);
                state_ = State::idle;
                break;
        }
        refreshTooltip();
        repaint();
    }
    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w) override
    {
        if (auto* p = apvts.getParameter (barsP))
        {
            const int n = p->getNumSteps();
            int idx = (int) std::lround (p->convertFrom0to1 (p->getValue()));
            idx = juce::jlimit (0, n - 1, idx + (w.deltaY > 0 ? 1 : -1));
            p->setValueNotifyingHost (p->convertTo0to1 ((float) idx));
            refreshTooltip();
            repaint();
        }
    }
    void tick() noexcept
    {
        if (state_ != State::armed) return;
        phase += 0.13f;
        pulse = 0.45f + 0.45f * (0.5f + 0.5f * std::sin (phase));
        repaint();
    }
private:
    enum class State { idle, armed, looping };
    float wheelValue() const
    {
        if (auto* v = apvts.getRawParameterValue (wheelParam)) return v->load();
        return 0.0f;
    }
    bool getBool (const juce::String& id) const
    {
        auto* v = apvts.getRawParameterValue (id); return v && v->load() > 0.5f;
    }
    void setBool (const juce::String& id, bool on)
    {
        if (auto* p = apvts.getParameter (id)) p->setValueNotifyingHost (on ? 1.0f : 0.0f);
    }
    void setFloat (const juce::String& id, float denorm)
    {
        if (auto* p = apvts.getParameter (id))
            p->setValueNotifyingHost (p->convertTo0to1 (juce::jlimit (0.0f, 1.0f, denorm)));
    }
    void cycleMode()
    {
        if (auto* p = apvts.getParameter (modeP))
        {
            const int n = p->getNumSteps();
            int idx = (int) std::lround (p->convertFrom0to1 (p->getValue()));
            idx = (idx + 1) % juce::jmax (1, n);
            p->setValueNotifyingHost (p->convertTo0to1 ((float) idx));
            refreshTooltip();
            repaint();
        }
    }
    void refreshTooltip()
    {
        auto choiceText = [this] (const juce::String& id) -> juce::String {
            if (auto* p = dynamic_cast<juce::AudioParameterChoice*> (apvts.getParameter (id)))
                return p->getCurrentChoiceName();
            return {};
        };
        const char* s = state_ == State::idle ? "record: click to set start"
                      : state_ == State::armed ? "turn the wheel, click to set target"
                      : "recording — click to clear";
        setTooltip (juce::String (s) + "  |  " + choiceText (barsP)
                    + " · " + choiceText (modeP) + "  (scroll = rate, right-click = shape)");
    }
    juce::AudioProcessorValueTreeState& apvts;
    juce::String wheelParam, onP, aP, bP, barsP, modeP;
    const Theme& t;
    State state_ = State::idle;
    bool  hover = false;
    float phase = 0.0f, pulse = 0.6f;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (KeyframeButton)
};
}
