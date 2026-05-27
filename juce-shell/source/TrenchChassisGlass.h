#pragma once

#include "TrenchChassisLayout.h"
#include "TrenchStyle.h"
#include <juce_gui_basics/juce_gui_basics.h>

namespace trench
{
// Transparent overlay painted ON TOP of the chassis image AND the live
// components (scope, shuttles, value boxes, type). It seats them into the
// chassis: an inner-shadow gasket at every slot lip kills the "pasted-on" seam,
// and the display gets a glass sheen + scanlines so it reads as a screen behind
// glass rather than a flat fill. Pure code reinforcement over the PNG chassis —
// it draws nothing opaque, only edge shadow + low-alpha glass.
class TrenchChassisGlass final : public juce::Component
{
public:
    TrenchChassisGlass()
    {
        setInterceptsMouseClicks (false, false); // clicks pass through to the controls beneath
        setOpaque (false);
    }

    void paint (juce::Graphics& g) override
    {
        const int w = getWidth(), h = getHeight();
        const auto scope = layout::displayBounds (w, h).toFloat();

        // Display: scanlines + top-down glass sheen, clipped to the screen.
        {
            juce::Graphics::ScopedSaveState save (g);
            juce::Path clip;
            clip.addRoundedRectangle (scope, 10.0f);
            g.reduceClipRegion (clip);

            g.setColour (juce::Colours::black.withAlpha (0.10f));
            for (float y = scope.getY() + 2.0f; y < scope.getBottom(); y += 3.0f)
                g.drawHorizontalLine ((int) y, scope.getX(), scope.getRight());

            juce::ColourGradient sheen (style::oledCyan().withAlpha (0.10f), scope.getX(), scope.getY(),
                                        juce::Colours::transparentBlack, scope.getX(), scope.getCentreY(), false);
            g.setGradientFill (sheen);
            g.fillRect (scope);
        }

        // Seat every slot with an inner-shadow gasket + a thin glass lip.
        for (auto* r : { &scope }) seatRecess (g, *r, 10.0f);
        seatRecess (g, layout::typeBounds   (w, h).toFloat(), 6.0f);
        seatRecess (g, layout::morphBounds  (w, h).toFloat(), 0.0f);
        seatRecess (g, layout::valueBounds  (w, h).toFloat(), 4.0f);
        seatRecess (g, layout::qBounds      (w, h).toFloat(), 0.0f);
        seatRecess (g, layout::qValueBounds (w, h).toFloat(), 4.0f);
    }

private:
    // Inner shadow fading inward from the slot edge = recessed/seated look.
    static void seatRecess (juce::Graphics& g, juce::Rectangle<float> r, float corner)
    {
        const float c = corner > 0.0f ? corner : r.getHeight() * 0.5f; // pill for the shuttle slots
        constexpr int rings = 7;
        for (int i = 0; i < rings; ++i)
        {
            const float a = 0.40f * (1.0f - (float) i / (float) rings);
            g.setColour (juce::Colours::black.withAlpha (a));
            g.drawRoundedRectangle (r.reduced ((float) i), juce::jmax (1.0f, c - (float) i), 1.0f);
        }
        // glass lip highlight along the top edge
        g.setColour (style::hairline().withAlpha (0.22f));
        g.drawLine (r.getX() + c, r.getY() + 1.0f, r.getRight() - c, r.getY() + 1.0f, 1.0f);
    }
};
} // namespace trench
