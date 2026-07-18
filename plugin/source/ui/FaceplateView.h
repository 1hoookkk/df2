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

        // Hairline shadow bezel wrapping each raised insert — very small, all
        // around, nothing spreading onto the plate.
        drawHairlineBezel (g, t.rect ("typeSelector"));
        drawHairlineBezel (g, t.rect ("morphReadout"));
        drawHairlineBezel (g, t.rect ("qReadout"));

        // X3 faceplate shadows (close-up reference 2026-07-17): a broad, SOFT
        // half-ellipse on the plate under each wheel capsule — visibly lighter
        // than a contact shadow, nearly the capsule's full width.
        drawWheelContactShadow (g, t.rect ("morphWheel"));
        drawWheelContactShadow (g, t.rect ("qWheel"));

        // AMOUNT: the half-ellipse cast to the RIGHT of the column (Tyson:
        // "the shadow to the right the half elipse"), on top of ThinWheel's
        // own soft silhouette — the pairing he approved.
        drawAmountSideShadow (g, t.rect ("amountWheel"));

        // restrained outer rim seats the panel
        const auto rb = getLocalBounds().toFloat();
        g.setColour (juce::Colours::black.withAlpha (0.55f));
        g.drawRect (rb, 1.5f);
    }

private:
    // A 1px-scale soft dark ring hugging the control's edge on ALL sides.
    static void drawHairlineBezel (juce::Graphics& g, juce::Rectangle<float> r)
    {
        if (r.isEmpty())
            return;
        const float rad = 5.0f;
        g.setColour (juce::Colours::black.withAlpha (0.10f));
        g.drawRoundedRectangle (r.expanded (0.6f), rad + 0.6f, 1.0f);
    }

    static void drawWheelContactShadow (juce::Graphics& g, juce::Rectangle<float> well,
                                        float castH = 9.0f, float strength = 1.0f)
    {
        if (well.isEmpty())
            return;

        // The wheel's cast shadow: a SOFT elliptical falloff from the contact
        // point — dark under the drum's belly, fading smoothly down AND toward
        // the sides. No drawn outline anywhere (a hard-edged ellipse read as
        // "a black thing", Tyson 2026-07-11). Clipped short of the label text.
        // The X3's broad soft half-ellipse: nearly the capsule's full width,
        // clearly LIGHTER than a contact shadow (the plugin's were too dark).
        // A THIN, defined half-oval: an actual ellipse under the capsule,
        // dark at the contact line, softening just enough not to be a decal.
        const float cx = well.getCentreX();
        const float cy = well.getBottom();
        const float rx = well.getWidth() * 0.46f;

        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (juce::Rectangle<int> ((int) well.getX(), (int) well.getBottom(),
                                                  (int) well.getWidth(), (int) castH));
        g.addTransform (juce::AffineTransform::scale (1.0f, castH / rx, cx, cy));
        juce::ColourGradient sh (juce::Colours::black.withAlpha (0.74f * strength), cx, cy,
                                 juce::Colours::transparentBlack, cx + rx, cy, true);
        sh.addColour (0.50, juce::Colours::black.withAlpha (0.50f * strength));   // filled body...
        sh.addColour (0.82, juce::Colours::black.withAlpha (0.18f * strength));   // ...short soft edge
        g.setGradientFill (sh);
        g.fillEllipse (cx - rx, cy - rx, rx * 2.0f, rx * 2.0f);
    }

    // drawWheelContactShadow rotated 90°: the AMOUNT column's contact line is
    // its right edge — same alphas/stops as the wheels, one shadow law.
    static void drawAmountSideShadow (juce::Graphics& g, juce::Rectangle<float> well)
    {
        if (well.isEmpty())
            return;

        const float castW = 9.0f;                    // thin horizontal reach
        // Start at the strip's REAL edge (the drawn frame sits a hair inside
        // its layout well) so the cast touches the contact line.
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

    juce::Image panelImage;
    Theme t;
};

} // namespace trench::ui
