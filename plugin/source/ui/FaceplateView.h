#pragma once

#include "Theme.h"

namespace trench::ui
{

// The faceplate: Tyson's beige plate art, drawn 1:1. The art's baked recesses
// ARE the wells.  The only code-painted addition is the tight contact shadow
// cast by each protruding wheel onto the plate immediately below its aperture.
// Static, opaque, behind all.
class FaceplateView : public juce::Component
{
public:
    FaceplateView (juce::Image panel, const Theme& theme)
        : panelImage (std::move (panel)), t (theme)
    {
        setOpaque (true);
        setBufferedToImage (true);
        setInterceptsMouseClicks (false, false);
    }

    void paint (juce::Graphics& g) override
    {
        g.fillAll (juce::Colour (0xff121110));
        if (panelImage.isValid())
        {
            g.setImageResamplingQuality (juce::Graphics::highResamplingQuality);
            g.drawImage (panelImage, getLocalBounds().toFloat(), juce::RectanglePlacement::stretchToFit);
        }

        // No code-drawn vignette or shadow bands over the art — they read as a
        // fake layer (Tyson 2026-07-11). The rack seating shadow is BAKED into
        // the plate asset itself (df2_panel_beige_shadow.png), so the grain
        // shades with it like the X3 reference.

        // X3-style wheel depth shadows: broad lower half-ellipses cast onto the
        // faceplate. They descend close to the following label without touching
        // it, making both thin wheels read as projecting from the same plate.
        drawWheelContactShadow (g, t.rect ("morphWheel"));
        drawWheelContactShadow (g, t.rect ("qWheel"));
        drawAmountSideShadow (g, t.rect ("amountWheel"));

        // restrained outer rim seats the panel
        const auto rb = getLocalBounds().toFloat();
        g.setColour (juce::Colours::black.withAlpha (0.55f));
        g.drawRect (rb, 1.5f);
    }

private:
    static void drawWheelContactShadow (juce::Graphics& g, juce::Rectangle<float> well)
    {
        if (well.isEmpty())
            return;

        // Reverted to original 7.0px broad half-ellipse contact shadow with 1.5px Y overlap
        const float castH = 7.0f;
        const float cx = well.getCentreX();
        const float overlap = 1.5f;
        const float cy = well.getBottom() - overlap;
        const float rx = well.getWidth() * 0.48f;   // broad half-ellipse edge

        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (juce::Rectangle<int> ((int) well.getX(), (int) std::floor (cy),
                                                  (int) well.getWidth(), (int) (castH + overlap)));
        // Squash a circular radial gradient into the short oval under the wheel.
        g.addTransform (juce::AffineTransform::scale (1.0f, (castH + overlap) / rx, cx, cy));
        juce::ColourGradient sh (juce::Colours::black.withAlpha (0.74f), cx, cy,
                                 juce::Colours::transparentBlack, cx + rx, cy, true);
        sh.addColour (0.50, juce::Colours::black.withAlpha (0.50f));
        sh.addColour (0.82, juce::Colours::black.withAlpha (0.18f));
        g.setGradientFill (sh);
        g.fillEllipse (cx - rx, cy - rx, rx * 2.0f, rx * 2.0f);
    }

    static void drawAmountSideShadow (juce::Graphics& g, juce::Rectangle<float> well)
    {
        if (well.isEmpty())
            return;

        // Circular radial side shadow cast to the right of the vertical MIX wheel
        // Tightened slightly to 6.5px width
        const float castW = 6.5f;
        const float cx = well.getRight() - 1.5f;
        const float cy = well.getCentreY();
        const float ry = well.getHeight() * 0.46f;

        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (juce::Rectangle<int> ((int) cx, (int) (cy - ry),
                                                  (int) (castW + 2.0f), (int) (ry * 2.0f)));
        g.addTransform (juce::AffineTransform::scale (castW / ry, 1.0f, cx, cy));
        juce::ColourGradient sh (juce::Colours::black.withAlpha (0.78f), cx, cy,
                                 juce::Colours::transparentBlack, cx + ry, cy, true);
        sh.addColour (0.45, juce::Colours::black.withAlpha (0.48f));
        sh.addColour (0.80, juce::Colours::black.withAlpha (0.16f));
        g.setGradientFill (sh);
        g.fillEllipse (cx - ry, cy - ry, ry * 2.0f, ry * 2.0f);
    }

    juce::Image panelImage;
    Theme t;
};

} // namespace trench::ui
