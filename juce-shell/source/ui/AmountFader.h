#pragma once

#include "Theme.h"

namespace trench::ui
{

// DEPTH — the unified dose/depth control. A clean vertical fader for the right
// utility column (RC-20 "Magnitude" role, TRENCH's tall layout): a recessed black
// slot, a ruby fill rising to the value, a horizontal ribbed thumb you drag, a
// light DEPTH label above, a small cream value window below, and subtle ticks.
// Secondary to the Morph/Q wheels but clearly readable. Wraps an invisible
// LinearVertical slider bound to `amount` — scales BOTH the honest-dose filter
// blend and Motion's morph/Q sweep depth, one dial for the whole treated effect.
class AmountFader : public juce::Component
{
public:
    AmountFader (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        slider.setSliderStyle (juce::Slider::LinearVertical);
        slider.setTextBoxStyle (juce::Slider::NoTextBox, false, 0, 0);
        slider.setRange (0.0, 1.0, 0.0);
        slider.setDoubleClickReturnValue (true, 1.0);
        slider.setMouseCursor (juce::MouseCursor::UpDownResizeCursor);
        slider.setTooltip ("Depth - filter dose + modulation intensity (flat to full)");
        slider.setTitle ("Depth");
        slider.onValueChange = [this] { repaint(); };
        for (auto id : { juce::Slider::backgroundColourId, juce::Slider::trackColourId,
                         juce::Slider::thumbColourId })
            slider.setColour (id, juce::Colours::transparentBlack);
        addAndMakeVisible (slider);
        attachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment> (
            apvts, "amount", slider);
        setInterceptsMouseClicks (false, true);
    }

    juce::Slider& getSlider() { return slider; }

    void resized() override
    {
        auto b = getLocalBounds();
        labelArea = b.removeFromTop (13);
        lcdArea   = b.removeFromBottom (17);
        track     = b.reduced (0, 4);
        const int chW = juce::jlimit (10, 14, track.getWidth() / 3);
        slot = juce::Rectangle<int> (track.getCentreX() - chW / 2, track.getY(), chW, track.getHeight());
        slider.setBounds (track);
    }

    void paint (juce::Graphics& g) override
    {
        // ── AMOUNT label (light, tracked — the navy plate's label ink) ──
        drawEngravedTrackedText (g, "DEPTH", labelArea.toFloat(),
                                 displayFont (juce::jlimit (6.5f, 8.5f, getWidth() * 0.17f), false),
                                 panelInk, 0.7f, 0.0f);

        const auto sl = slot.toFloat();
        const float rad = 3.0f;

        // ── recessed black vertical slot ──
        g.setColour (juce::Colours::black.withAlpha (0.5f));
        g.drawRoundedRectangle (sl.expanded (1.0f), rad + 1.0f, 1.2f);          // contact shadow
        juce::ColourGradient floor (juce::Colour (0xff070708), sl.getX(), 0.0f,
                                    juce::Colour (0xff1a1a1e), sl.getRight(), 0.0f, false);
        g.setGradientFill (floor);
        g.fillRoundedRectangle (sl, rad);

        // value → thumb position (v=1 top, v=0 bottom)
        const float v = juce::jlimit (0.0f, 1.0f, (float) slider.getValue());
        const float capH = 11.0f;
        const float travel = juce::jmax (1.0f, sl.getHeight() - capH);
        const float capY = sl.getBottom() - capH * 0.5f - v * travel;   // thumb centre

        // ── ruby fill: from the bottom up to the thumb ──
        {
            const float top = juce::jlimit (sl.getY(), sl.getBottom(), capY);
            juce::Rectangle<float> fill (sl.getX() + 1.4f, top,
                                         sl.getWidth() - 2.8f, sl.getBottom() - top - 1.4f);
            if (fill.getHeight() > 0.5f)
            {
                juce::ColourGradient rg (ruby.darker (0.25f), 0.0f, fill.getBottom(),
                                         ruby.brighter (0.10f), 0.0f, fill.getY(), false);
                g.setGradientFill (rg);
                g.fillRoundedRectangle (fill, 1.8f);
                g.setColour (ruby.brighter (0.45f).withAlpha (0.9f));    // bright fill line at the top
                g.fillRect (fill.getX(), fill.getY(), fill.getWidth(), 1.4f);
            }
        }

        // inner top shadow of the slot (over the fill, so it reads recessed)
        g.setColour (juce::Colours::black.withAlpha (0.45f));
        g.fillRect (sl.getX(), sl.getY(), sl.getWidth(), 2.5f);
        g.setColour (t.rim().withAlpha (0.9f));
        g.drawRoundedRectangle (sl, rad, 1.0f);

        // ── subtle ticks beside the slot ──
        for (int pct = 0; pct <= 100; pct += 25)
        {
            const float yy = sl.getBottom() - (float) pct / 100.0f * sl.getHeight();
            g.setColour (panelInk.withAlpha (pct % 50 == 0 ? 0.5f : 0.28f));
            g.drawLine (sl.getRight() + 2.5f, yy, sl.getRight() + (pct % 50 == 0 ? 6.0f : 4.0f), yy, 0.9f);
        }

        // ── horizontal ribbed thumb handle ──
        {
            const float cw = juce::jmin (30.0f, getWidth() - 6.0f);
            juce::Rectangle<float> cap (sl.getCentreX() - cw / 2.0f, capY - capH / 2.0f, cw, capH);
            const bool hot = slider.isMouseOverOrDragging();
            juce::Colour hi (0xff777280), lo (0xff222029);
            if (hot) hi = hi.brighter (0.15f);
            juce::ColourGradient mg (hi, 0.0f, cap.getY(), lo, 0.0f, cap.getBottom(), false);
            mg.addColour (0.5, juce::Colour (0xff45414e));
            g.setGradientFill (mg);
            g.fillRoundedRectangle (cap, 2.0f);
            // horizontal grip ribs
            g.setColour (juce::Colours::black.withAlpha (0.4f));
            for (float ry = cap.getY() + 2.5f; ry < cap.getBottom() - 1.5f; ry += 2.6f)
                g.drawLine (cap.getX() + 2.5f, ry, cap.getRight() - 2.5f, ry, 0.7f);
            g.setColour (juce::Colours::white.withAlpha (0.22f));
            g.drawLine (cap.getX() + 2.0f, cap.getY() + 1.0f, cap.getRight() - 2.0f, cap.getY() + 1.0f, 0.8f);
            g.setColour (juce::Colour (0xff17141c).withAlpha (0.9f));
            g.drawRoundedRectangle (cap, 2.0f, 0.9f);
        }

        // ── small cream value window below (matches the Morph/Q readouts) ──
        {
            const float ww = juce::jmin (40.0f, (float) getWidth());
            juce::Rectangle<float> win (getWidth() * 0.5f - ww / 2.0f, lcdArea.getY() + 1.0f,
                                        ww, lcdArea.getHeight() - 1.0f);
            drawIvoryWell (g, win, 2.5f, false, t);
            g.setFont (displayFont (juce::jlimit (8.0f, 11.0f, win.getHeight() * 0.66f), false));
            g.setColour (t.labelInk());
            g.drawText (juce::String (v * 100.0f, 1), win.reduced (3.0f, 1.0f).toNearestInt(),
                        juce::Justification::centred);
        }
    }

private:
    Theme t;
    juce::Slider slider;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> attachment;
    juce::Rectangle<int> labelArea, lcdArea, track, slot;
    const juce::Colour panelInk { 0xffe2e9f2 };
    const juce::Colour ruby { 0xffcf2f24 };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AmountFader)
};

} // namespace trench::ui
