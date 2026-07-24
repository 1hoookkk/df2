#pragma once
#include "Theme.h"
#include "../parameters/TrenchParameters.h"
#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>
namespace trench::ui
{
class FiveDButton : public juce::Component
{
public:
    FiveDButton (juce::AudioProcessorValueTreeState& apvts, const Theme& theme) : t (theme)
    {
        param = apvts.getParameter (ParamID::fiveD);
        if (param != nullptr)
            att = std::make_unique<juce::ParameterAttachment> (*param, [this] (float) { repaint(); });
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("5D");
        setHelpText ("5D spatial — the sound orbits your head");
    }
    void mouseEnter (const juce::MouseEvent&) override { hover = true;  repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }
    void mouseDown  (const juce::MouseEvent&) override { down = true;   repaint(); }
    void mouseUp (const juce::MouseEvent& e) override
    {
        down = false;
        if (getLocalBounds().toFloat().contains (e.position) && param != nullptr && att != nullptr)
            att->setValueAsCompleteGesture (param->getValue() > 0.5f ? 0.0f : 1.0f);
        repaint();
    }
    void paint (juce::Graphics& g) override
    {
        const bool on = param != nullptr && param->getValue() > 0.5f;
        const auto b = getLocalBounds().toFloat();
        const float d = juce::jlimit (5.0f, 9.0f, b.getHeight() * 0.55f);
        const juce::Rectangle<float> lamp (b.getX() + 1.0f, b.getCentreY() - d * 0.5f, d, d);
        const juce::Colour amber (0xffefa63c), dim (0xff4f4a40);
        if (on)
        {
            g.setColour (amber.withAlpha (0.30f));
            g.fillEllipse (lamp.expanded (2.2f));
        }
        juce::ColourGradient lg (on ? amber.brighter (0.20f) : dim, lamp.getCentreX(), lamp.getY(),
                                 on ? amber.darker (0.30f) : dim.darker (0.30f), lamp.getCentreX(), lamp.getBottom(), false);
        g.setGradientFill (lg);
        g.fillEllipse (lamp);
        g.setColour (juce::Colours::white.withAlpha (on ? 0.5f : 0.15f));
        g.fillEllipse (lamp.getX() + lamp.getWidth() * 0.28f, lamp.getY() + lamp.getHeight() * 0.16f,
                       lamp.getWidth() * 0.30f, lamp.getHeight() * 0.28f);
        g.setColour (juce::Colours::black.withAlpha (0.4f));
        g.drawEllipse (lamp, 0.7f);
        g.setFont (displayFont (11.0f, false).withStyle (juce::Font::italic));
        g.setColour (juce::Colour (0xfff2ead6).withAlpha (on ? 1.0f : (hover ? 1.0f : 0.94f)));
        g.drawText ("5D", b.withTrimmedLeft (d + 5.0f).toNearestInt(), juce::Justification::centredLeft, false);
    }
private:
    Theme t;
    juce::RangedAudioParameter* param = nullptr;
    std::unique_ptr<juce::ParameterAttachment> att;
    bool hover = false;
    bool down = false;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (FiveDButton)
};
}
