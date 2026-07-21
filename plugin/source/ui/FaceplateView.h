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
        drawReferenceAmountThumb (g, t.rect ("amountWheel"));

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
        // Thin, flat black contact crescent from the supplied reference — not
        // a round puddle. At 7 px it stops just clear of the following label.
        const float castH = 7.0f;
        const float cx = well.getCentreX();
        const float cy = well.getBottom();
        const float rx = well.getWidth() * 0.48f;   // broad half-ellipse edge

        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (juce::Rectangle<int> ((int) well.getX(), (int) well.getBottom(),
                                                  (int) well.getWidth(), (int) castH));
        // Squash a circular radial gradient into the short oval under the wheel.
        g.addTransform (juce::AffineTransform::scale (1.0f, castH / rx, cx, cy));
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

        // The thin amount roller has a small half-moon cast to its right edge.
        // It is a side contact shadow, not a second outline around the wheel.
        const float castW = 9.0f;
        const float cx = well.getRight() - 2.5f;
        const float cy = well.getCentreY();
        const float ry = well.getHeight() * 0.46f;

        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (juce::Rectangle<int> ((int) cx, (int) well.getY(),
                                                  (int) castW + 1, (int) well.getHeight()));
        g.addTransform (juce::AffineTransform::scale (castW / ry, 1.0f, cx, cy));
        juce::ColourGradient sh (juce::Colours::black.withAlpha (0.74f), cx, cy,
                                 juce::Colours::transparentBlack, cx, cy + ry, true);
        sh.addColour (0.50, juce::Colours::black.withAlpha (0.50f));
        sh.addColour (0.82, juce::Colours::black.withAlpha (0.18f));
        g.setGradientFill (sh);
        g.fillEllipse (cx - ry, cy - ry, ry * 2.0f, ry * 2.0f);
    }

    static void drawReferenceAmountThumb (juce::Graphics& g, juce::Rectangle<float> well)
    {
        if (well.isEmpty())
            return;

        // The reference face has a short blue-grey thumb at the far right of
        // the amount rail. It is a separate depth cue from the thin wheel:
        // keep the wheel artwork untouched and restore only this small thumb.
        const auto thumb = juce::Rectangle<float> (well.getRight() + 16.0f,
                                                   well.getY() + 12.0f,
                                                   12.0f, 41.0f);
        const float radius = 5.0f;

        juce::ColourGradient body (juce::Colour (0xff33464b), thumb.getX(), thumb.getY(),
                                   juce::Colour (0xff5d7479), thumb.getRight(), thumb.getCentreY(), true);
        body.addColour (0.42, juce::Colour (0xff26383d));
        body.addColour (0.76, juce::Colour (0xff52686e));
        g.setGradientFill (body);
        g.fillRoundedRectangle (thumb, radius);

        g.setColour (juce::Colours::black.withAlpha (0.34f));
        g.drawRoundedRectangle (thumb.reduced (0.55f), radius - 0.35f, 0.75f);

        // A restrained horizontal catch is visible in the photographed thumb;
        // it keeps the control from reading as a flat dark rectangle.
        g.setColour (juce::Colour (0xffb8c9ca).withAlpha (0.52f));
        const float catchY = thumb.getCentreY();
        g.drawLine (thumb.getX() + 3.0f, catchY, thumb.getRight() - 3.0f, catchY, 0.65f);
    }

    juce::Image panelImage;
    Theme t;
};

} // namespace trench::ui
