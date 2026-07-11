#pragma once

#include "Theme.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// M/Q motion targets, shown as two small labelled indicator lights sitting just
// under the MOVE chip inside the screen: "M ·  Q ·". Each letter carries a teal
// lamp that lights when that wheel is a MOVE target and brightens while it is
// actually being swept. Small and quiet — screen furniture that defers to the
// wheels; click a letter/lamp to toggle its target.
class MotionTargetLights : public juce::Component
{
public:
    MotionTargetLights (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        mParam = apvts.getParameter (ParamID::motionTargetM);
        qParam = apvts.getParameter (ParamID::motionTargetQ);
        if (mParam != nullptr)
            mAtt = std::make_unique<juce::ParameterAttachment> (*mParam, [this] (float) { repaint(); });
        if (qParam != nullptr)
            qAtt = std::make_unique<juce::ParameterAttachment> (*qParam, [this] (float) { repaint(); });

        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Motion target");
        setHelpText ("Pick which wheel MOVE sweeps: M, Q, or both");
    }

    // Live glow: brighten a lamp while the motion is actually moving that wheel.
    void setActivity (bool mMoving, bool qMoving)
    {
        if (mMoving != mAct || qMoving != qAct) { mAct = mMoving; qAct = qMoving; repaint(); }
    }

    void resized() override
    {
        auto b = getLocalBounds();
        const int half = b.getWidth() / 2;
        mHit = { b.getX(), b.getY(), half, b.getHeight() };
        qHit = { b.getX() + half, b.getY(), b.getWidth() - half, b.getHeight() };
    }

    void mouseDown (const juce::MouseEvent& e) override
    {
        if (mHit.contains (e.getPosition()))      toggle (mParam, mAtt.get());
        else if (qHit.contains (e.getPosition())) toggle (qParam, qAtt.get());
    }

    void paint (juce::Graphics& g) override
    {
        drawUnit (g, mHit.toFloat(), "M", isOn (mParam), mAct, kLampM);
        drawUnit (g, qHit.toFloat(), "Q", isOn (qParam), qAct, kLampQ);
    }

private:
    static bool isOn (juce::RangedAudioParameter* p) { return p != nullptr && p->getValue() > 0.5f; }

    void toggle (juce::RangedAudioParameter* p, juce::ParameterAttachment* a)
    {
        if (p != nullptr && a != nullptr)
            a->setValueAsCompleteGesture (p->getValue() > 0.5f ? 0.0f : 1.0f);
    }

    // A small "letter + lamp" pair drawn inside its half of the bounds.
    void drawUnit (juce::Graphics& g, juce::Rectangle<float> r, const juce::String& label,
                   bool on, bool active, juce::Colour lamp)
    {
        const float ledS = juce::jlimit (4.0f, 7.0f, r.getHeight() * 0.52f);
        const auto textArea = r.withTrimmedRight (ledS + 5.0f);

        // Low-res pixel letter (render small, upscale nearest) — reads like an LED matrix.
        drawAliasedText (g, textArea, label, juce::jmax (8.0f, r.getHeight() * 0.72f),
                         kInk.withAlpha (on ? 0.95f : 0.5f), 0.5f);

        // Chunky SQUARE LED — hard pixel edges, magenta/cyan OLED colour, blocky bloom.
        const juce::Rectangle<float> led (textArea.getRight() + 4.0f, r.getCentreY() - ledS * 0.5f, ledS, ledS);
        const juce::Colour off (0xff1c2830);
        if (on)   // blocky colour bloom behind the lit pixel
        {
            g.setColour (lamp.withAlpha (active ? 0.45f : 0.24f));
            g.fillRect (led.expanded (active ? 2.5f : 1.5f));
        }
        g.setColour (on ? (active ? lamp.brighter (0.25f) : lamp) : off);
        g.fillRect (led);                                          // LED face
        if (on)                                                    // hot centre pixel
        {
            g.setColour (lamp.brighter (0.65f).withAlpha (active ? 1.0f : 0.85f));
            g.fillRect (led.reduced (led.getWidth() * 0.30f));
        }
        g.setColour (juce::Colours::black.withAlpha (0.35f));
        g.drawRect (led, 0.8f);                                    // crisp pixel edge
    }

    static inline const juce::Colour kInk   { 0xffe9dfc6 };
    static inline const juce::Colour kLampM { 0xffe85ba6 }; // magenta OLED — echoes the old M bar
    static inline const juce::Colour kLampQ { 0xff44c8e0 }; // cyan OLED — echoes the old Q bar

    Theme t;
    juce::RangedAudioParameter* mParam = nullptr;
    juce::RangedAudioParameter* qParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> mAtt, qAtt;
    juce::Rectangle<int> mHit, qHit;
    bool mAct = false, qAct = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MotionTargetLights)
};

} // namespace trench::ui
