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

        // X3-style wheel contact shadows: small curved half-moons that attach
        // the roller tips to the faceplate.  They stay tight to the aperture
        // and never reach the labels, so they read as real cast light rather
        // than a separate black graphic object.
        drawWheelContactShadow (g, t.rect ("morphWheel"));
        drawWheelContactShadow (g, t.rect ("qWheel"));

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

        // The wheel's cast shadow: a SOFT elliptical falloff from the contact
        // point — dark under the drum's belly, fading smoothly down AND toward
        // the sides. No drawn outline anywhere (a hard-edged ellipse read as
        // "a black thing", Tyson 2026-07-11). Clipped short of the label text.
        const float castH = 12.0f;   // the machined layout leaves more plate below
        const float cx = well.getCentreX();
        const float cy = well.getBottom();
        const float rx = well.getWidth() * 0.40f;   // horizontal reach
        const float ry = castH + 2.0f;              // vertical reach

        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (juce::Rectangle<int> ((int) well.getX(), (int) well.getBottom(),
                                                  (int) well.getWidth(), (int) castH));
        // Squash the space so a circular radial gradient becomes the oval.
        g.addTransform (juce::AffineTransform::scale (1.0f, ry / rx, cx, cy));
        juce::ColourGradient sh (juce::Colours::black.withAlpha (0.62f), cx, cy,
                                 juce::Colours::transparentBlack, cx + rx, cy, true);
        sh.addColour (0.35, juce::Colours::black.withAlpha (0.40f));
        g.setGradientFill (sh);
        g.fillRect (juce::Rectangle<float> (cx - rx, cy - rx, rx * 2.0f, rx * 2.0f));
    }

    juce::Image panelImage;
    Theme t;
};

} // namespace trench::ui
