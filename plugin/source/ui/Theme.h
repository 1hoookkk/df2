#pragma once

#include "../UiLayout.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace trench::ui
{

// --- fixed geometry constants (editor + panel source space) ---
// Source space = the BEIGE plate (df2_panel_beige.png), 1010x1557 (2026-07-11 recut).
inline constexpr int   kEditorWidth        = 350;
inline constexpr int   kEditorHeight       = 540;   // requested compact DAW footprint; plate aspect retained
inline constexpr float kPanelSourceWidth   = 1010.0f;   // layout rects' source space
inline constexpr float kPanelSourceHeight  = 1557.0f;

// Map a panel-source rect into editor space.
inline juce::Rectangle<float> sourceRectToEditor (juce::Rectangle<float> s)
{
    return { s.getX() * kEditorWidth  / kPanelSourceWidth,
             s.getY() * kEditorHeight / kPanelSourceHeight,
             s.getWidth()  * kEditorWidth  / kPanelSourceWidth,
             s.getHeight() * kEditorHeight / kPanelSourceHeight };
}

// Sweet-spot typography: neutral regular copy with selective commercial weight.
inline const char* const kUiFontName = "Arial";
inline const char* const kUiEmphasisFontName = "Arial";

inline juce::String& uiFontFamily()
{
    static juce::String family { kUiFontName };
    return family;
}

inline juce::String& uiEmphasisFontFamily()
{
    static juce::String family { kUiEmphasisFontName };
    return family;
}

// Whether an emphasis face is additionally synthetic-bolded. Default OFF: the
// named Semibold display face already provides enough hierarchy.
inline bool& uiBoldEnabled()
{
    static bool enabled = false;
    return enabled;
}

inline juce::Font displayFont (float height, bool emphasis = false)
{
    const bool useSyntheticBold = emphasis && uiBoldEnabled();
    const auto& family = emphasis ? uiEmphasisFontFamily() : uiFontFamily();
    return juce::Font (juce::FontOptions (family, height,
                                          useSyntheticBold ? juce::Font::bold : juce::Font::plain));
}

inline juce::Font telemetryFont (float height, bool emphasis = false)
{
    return juce::Font (juce::FontOptions (juce::Font::getDefaultMonospacedFontName(), height,
                                          emphasis ? juce::Font::bold : juce::Font::plain));
}

// Named token accessors over the baked UiLayout — the Theme layer.
struct Theme
{
    const trench::UiLayout& layout;

    // 60:30:10: WARM PUTTY 60 (the plate, locked) / BLACKENED GRAPHITE 30
    // (wheels, type, glass) / MUTED EMBER 10 (trace, lamp, active state).
    // Values live in UiLayout::defaults() — change them there, not here.
    juce::Colour accent()      const { return layout.colour ("accent",      juce::Colour (0xff9b4f4a)); }
    juce::Colour curveColour() const { return layout.colour ("curveColour", accent()); }
    // Compatibility tokens retained by the workstation shell. The recovered
    // sweet-spot snapshot predates their named accessors, so they resolve into
    // the same cobalt family without altering the photographed display paint.
    juce::Colour curveHighlight() const { return layout.colour ("curveHighlight", juce::Colour (0xffe9a39b)); }
    juce::Colour telemetry() const { return layout.colour ("telemetry", accent()); }
    juce::Colour rollerIllumination() const { return layout.colour ("rollerIllumination", juce::Colour (0xff9b4f4a)); }
    juce::Colour amber()       const { return layout.colour ("amber",       juce::Colour (0xffa9554e)); } // legacy name: active glow
    juce::Colour wellTop()     const { return layout.colour ("wellTop",     juce::Colour (0xffe7dec9)); }
    juce::Colour wellBottom()  const { return layout.colour ("wellBottom",  juce::Colour (0xffc9c0a8)); }
    juce::Colour wellKeyline() const { return layout.colour ("wellKeyline", juce::Colour (0xff5c4f3a)); }
    juce::Colour bevelHi()     const { return layout.colour ("bevelHi",     juce::Colour (0x88e7dec9)); }
    juce::Colour bevelLo()     const { return layout.colour ("bevelLo",     juce::Colour (0x3d000000)); }
    juce::Colour arrow()       const { return layout.colour ("arrow",       juce::Colour (0xff241e15)); }
    juce::Colour rim()         const { return layout.colour ("rim",         juce::Colour (0xff241e15)); }
    juce::Colour dashed()      const { return layout.colour ("dashed",      juce::Colour (0xff4a4640)); }
    juce::Colour screenEdge()  const { return layout.colour ("screenEdge",  juce::Colour (0xff100d0c)); }
    juce::Colour labelInk()    const { return layout.colour ("labelInk",    juce::Colour (0xff24231f)); }
    juce::Colour phosphor()    const { return layout.colour ("phosphor",    juce::Colour (0xff1b1715)); }

    float  wellRadius()        const { return (float) layout.param ("wellRadius", 9.0); }
    float  componentRadius()   const { return (float) layout.param ("componentRadius", 2.5); }
    float  readoutAliasScale() const { return (float) juce::jlimit (0.3, 1.0, layout.param ("readoutAliasScale", 0.72)); }
    float  typeArrowExtra()    const { return (float) layout.param ("typeArrowExtra", 6.0); }
    double curveDbTop()        const { return layout.param ("curveDbTop", 18.0); }
    double curveDbBottom()     const { return layout.param ("curveDbBottom", -30.0); }

    juce::Rectangle<float> rect (const juce::String& id) const
    {
        return sourceRectToEditor (layout.sourceRectFor (id));
    }
    float    fontSize (const juce::String& id, float fb) const
    {
        // Layout typography was authored at the accepted 440 px face. Scale it
        // with the compact editor instead of leaving oversized type in 350 px controls.
        constexpr float fontReferenceWidth = 440.0f;
        return layout.fontSizeFor (id).value_or (fb) * (float) kEditorWidth / fontReferenceWidth;
    }
    juce::Colour textColour (const juce::String& id, juce::Colour fb) const { return layout.textColourFor (id).value_or (fb); }
    juce::String text (const juce::String& id, const juce::String& fb) const { return layout.textFor (id, fb); }
    float    opacity (const juce::String& id) const { return layout.opacityFor (id); }

    // Free decals, mapped into editor space and ready to draw. fontSize/thickness
    // are authored in source units (like rects), so scale them the same way.
    struct EditorDecal
    {
        juce::String type, text;
        juce::Rectangle<float> rect;
        juce::Colour colour;
        float fontSize, thickness;
        bool fill;
    };
    std::vector<EditorDecal> decals() const
    {
        constexpr float s = (float) kEditorHeight / kPanelSourceHeight;
        std::vector<EditorDecal> out;
        out.reserve (layout.decals.size());
        for (const auto& d : layout.decals)
            out.push_back ({ d.type, d.text, sourceRectToEditor (d.sourceRect), d.colour,
                             d.fontSize * s, d.thickness * s, d.fill });
        return out;
    }
};

// ONE recessed inset well — shared by the TYPE bar, numeric readouts, and page chip.
// It reads as dull plastic/LCD, not a white web input: muted floor, shallow lip,
// tiny scanline dirt, and a crisp keyline.
inline void drawWell (juce::Graphics& g, juce::Rectangle<float> b, const Theme& t)
{
    const auto r = b.reduced (0.75f);
    const auto radius = juce::jmax (3.0f, t.wellRadius() - 4.0f);

    // Outer contact shadow: the plate sits inside the dark cutout, it does not float.
    g.setColour (juce::Colours::black.withAlpha (0.46f));
    g.drawRoundedRectangle (r.expanded (0.85f), radius + 1.0f, 1.2f);

    // Dull aged-plastic floor.
    {
        juce::ColourGradient floor (t.wellTop().darker (0.03f), 0.0f, r.getY(),
                                    t.wellBottom().darker (0.20f), 0.0f, r.getBottom(), false);
        floor.addColour (0.48, t.wellTop().interpolatedWith (t.wellBottom(), 0.62f));
        g.setGradientFill (floor);
        g.fillRoundedRectangle (r, radius);
    }

    // Old LCD/plastic surface noise. Kept barely visible at runtime scale.
    g.setColour (juce::Colours::black.withAlpha (0.030f));
    for (float y = r.getY() + 2.0f; y < r.getBottom() - 1.0f; y += 3.0f)
        g.drawLine (r.getX() + 2.0f, y, r.getRight() - 2.0f, y, 0.5f);

    // Inset lip: darker top/left contact, small worn catch on the bottom.
    {
        juce::Graphics::ScopedSaveState save (g);
        juce::Path clip;
        clip.addRoundedRectangle (r, radius);
        g.reduceClipRegion (clip);

        juce::ColourGradient top (juce::Colours::black.withAlpha (0.38f), 0.0f, r.getY(),
                                  juce::Colours::transparentBlack,        0.0f, r.getY() + 6.0f, false);
        g.setGradientFill (top);
        g.fillRect (r.getX(), r.getY(), r.getWidth(), 6.5f);

        juce::ColourGradient left (juce::Colours::black.withAlpha (0.18f), r.getX(), 0.0f,
                                   juce::Colours::transparentBlack,        r.getX() + 4.0f, 0.0f, false);
        g.setGradientFill (left);
        g.fillRect (r.getX(), r.getY(), 4.0f, r.getHeight());

        juce::ColourGradient bot (juce::Colours::transparentBlack,         0.0f, r.getBottom() - 5.0f,
                                  juce::Colours::white.withAlpha (0.24f),  0.0f, r.getBottom(), false);
        g.setGradientFill (bot);
        g.fillRect (r.getX(), r.getBottom() - 5.0f, r.getWidth(), 5.0f);

        juce::ColourGradient right (juce::Colours::transparentBlack,        r.getRight() - 4.0f, 0.0f,
                                    juce::Colours::black.withAlpha (0.16f), r.getRight(),        0.0f, false);
        g.setGradientFill (right);
        g.fillRect (r.getRight() - 4.0f, r.getY(), 4.0f, r.getHeight());
    }

    g.setColour (t.wellKeyline().darker (0.28f).withAlpha (0.92f));
    g.drawRoundedRectangle (r, radius, 1.0f);
    g.setColour (juce::Colours::white.withAlpha (0.18f));
    g.drawRoundedRectangle (r.reduced (1.0f), juce::jmax (2.0f, radius - 1.0f), 0.7f);
}

// A small SEATED hardware push-key (SEED / TAKE): a dark machined cap sunk into a
// milled recess ring, with an engraved aged-brass legend. Deliberately dark and
// quiet so it DEFERS to the wheels — the soft brass catch is its only bright note;
// it must never read as a light utility pill. Light + material only (No-Fake-Layers):
// the ring is real contact shadow, the cap is a real domed key, nothing floats.
inline void drawHardwareKey (juce::Graphics& g, juce::Rectangle<float> b,
                             const juce::String& label, bool hover, bool down, const Theme& t)
{
    const float radius = juce::jmax (3.0f, t.wellRadius() - 3.0f);
    const auto cap = b.reduced (1.5f);

    // Milled recess ring: the key sits DOWN in a pocket in the sand plate.
    g.setColour (juce::Colours::black.withAlpha (0.45f));
    g.drawRoundedRectangle (b.reduced (0.5f), radius + 1.0f, 1.4f);

    // Dark machined cap — warm espresso charcoal so it recedes on the sand
    // plate; the brass legend is its only bright note.
    const float lift = down ? -0.07f : (hover ? 0.06f : 0.0f);
    juce::ColourGradient face (juce::Colour (0xff332c24).brighter (lift), 0.0f, cap.getY(),
                               juce::Colour (0xff1a1610).brighter (lift * 0.5f), 0.0f, cap.getBottom(), false);
    g.setGradientFill (face);
    g.fillRoundedRectangle (cap, radius);

    // Top bevel highlight + bottom contact shade = seated depth without a fake layer.
    g.setColour (juce::Colours::white.withAlpha (down ? 0.05f : 0.11f));
    g.drawLine (cap.getX() + 3.0f, cap.getY() + 1.0f, cap.getRight() - 3.0f, cap.getY() + 1.0f, 1.0f);
    g.setColour (juce::Colours::black.withAlpha (0.42f));
    g.drawLine (cap.getX() + 3.0f, cap.getBottom() - 0.8f, cap.getRight() - 3.0f, cap.getBottom() - 0.8f, 1.0f);

    // Dark keyline seam.
    g.setColour (juce::Colour (0xff0b0d13).withAlpha (0.9f));
    g.drawRoundedRectangle (cap, radius, 1.0f);

    // Engraved aged-brass legend — ties to the selector/labels, brighter on hover.
    const auto area = cap.toNearestInt();
    g.setFont (displayFont (juce::jmax (8.5f, cap.getHeight() * 0.40f), false));
    g.setColour (juce::Colours::black.withAlpha (0.55f));
    g.drawFittedText (label, area.translated (0, 1), juce::Justification::centred, 1);   // deboss shadow
    g.setColour (juce::Colour (0xffcbb488).withAlpha (down ? 0.75f : (hover ? 1.0f : 0.9f)));
    g.drawFittedText (label, area, juce::Justification::centred, 1);
}

// Moulded control seated in a machined pocket. The dark upper cut and pale lower
// lip make the surround belong to the plate; the quieter convex insert then reads
// as fitted hardware instead of a bright rectangle pasted over the faceplate.
inline void drawRaisedBoneControl (juce::Graphics& g, juce::Rectangle<float> r,
                                   float radius, bool isActive, const Theme& t,
                                   bool brighterFace)
{
    const auto pocket = r.reduced (0.35f);

    // Recess first: dark at the upper wall, plate-lit at the lower wall. There
    // is deliberately no exterior drop shadow, so the control cannot float.
    juce::ColourGradient recess (juce::Colour (0xff413c35), 0.0f, pocket.getY(),
                                 juce::Colour (0xffb4aa9a), 0.0f, pocket.getBottom(), false);
    recess.addColour (0.36, juce::Colour (0xff696157));
    g.setGradientFill (recess);
    g.fillRoundedRectangle (pocket, radius + 0.35f);

    g.setColour (juce::Colours::black.withAlpha (0.76f));
    g.drawRoundedRectangle (pocket, radius + 0.35f, 1.0f);

    const auto face = r.reduced (2.15f).translated (0.0f, 0.35f);
    const auto top = brighterFace ? juce::Colour (0xffedeae3)
                                  : juce::Colour (0xffddd8ce);
    const auto middle = brighterFace ? juce::Colour (0xffd9d4ca)
                                     : juce::Colour (0xffcdc6ba);
    const auto bottom = brighterFace ? juce::Colour (0xffbdb6aa)
                                     : juce::Colour (0xffb4ac9f);

    juce::ColourGradient faceFill (top, 0.0f, face.getY(),
                                    bottom, 0.0f, face.getBottom(), false);
    faceFill.addColour (0.43, middle);
    g.setGradientFill (faceFill);
    g.fillRoundedRectangle (face, juce::jmax (2.0f, radius - 1.3f));

    // The insert retains a controlled convex roll, but its highlights stop well
    // inside the cut so it feels fitted rather than outlined in white.
    {
        juce::Graphics::ScopedSaveState save (g);
        juce::Path clip;
        clip.addRoundedRectangle (face, juce::jmax (2.0f, radius - 1.3f));
        g.reduceClipRegion (clip);

        g.setColour (juce::Colours::white.withAlpha (brighterFace ? 0.54f : 0.38f));
        g.fillRect (face.getX() + 2.0f, face.getY() + 0.7f,
                    face.getWidth() - 4.0f, 0.85f);
        g.setColour (juce::Colour (0xff3e3932).withAlpha (0.32f));
        g.fillRect (face.getX() + 2.0f, face.getBottom() - 1.25f,
                    face.getWidth() - 4.0f, 1.0f);
    }

    // One decisive seam, plus an almost invisible state tint. Avoid the stacked
    // white outlines that made the previous boxes look like pasted stickers.
    g.setColour (juce::Colour (0xff514c44).withAlpha (0.88f));
    g.drawRoundedRectangle (face.reduced (0.35f),
                            juce::jmax (2.0f, radius - 1.5f), 0.9f);
    g.setColour (isActive ? t.accent().withAlpha (0.36f)
                          : juce::Colours::white.withAlpha (0.12f));
    g.drawRoundedRectangle (face.reduced (1.05f),
                            juce::jmax (1.6f, radius - 2.1f), 0.55f);
}

inline void drawIvoryWell (juce::Graphics& g, juce::Rectangle<float> r,
                           float radius, bool isActive, const Theme& t)
{
    drawRaisedBoneControl (g, r, radius, isActive, t, true);
}

// Numeric readouts use the same bevel, one brightness step below TYPE. The face
// remains neutral bone, not the rejected white-lamp or gold-cream treatment.
inline void drawMutedBoneReadout (juce::Graphics& g, juce::Rectangle<float> r,
                                  float radius, bool isActive, const Theme& t)
{
    drawRaisedBoneControl (g, r, radius, isActive, t, false);
}

// The dark screen glass (t.phosphor() = the iron glass base) — the SAME base treatment the hero GraphDisplay
// uses (oil-sage base + worn top sheen + settled lower third), factored out so
// secondary screen surfaces (the variant-bank page) read as the same display rather
// than a flat green panel. Caller sets/uses its own rounded clip.
inline void fillPhosphorGlass (juce::Graphics& g, juce::Rectangle<float> screen, const Theme& t)
{
    g.setColour (t.phosphor());
    g.fillRect (screen);
    g.setColour (juce::Colour (0xfff0e3cc).withAlpha (0.045f)); // warm reflection on charcoal glass
    g.fillRect (screen);
    g.setColour (juce::Colour (0xff171411).withAlpha (0.34f)); // espresso lower depth
    auto lower = screen;
    g.fillRect (lower.removeFromBottom (lower.getHeight() * 0.34f));
}

// AESTHETIC-ONLY, code-drawn screen atmosphere — a "painter canvas" layer drawn INSIDE the
// existing screen aperture so the phosphor reads as one piece of lit, slightly-curved glass
// seated in the panel. Restrained per the No-Fake-Layers rule: only light + material (a soft
// edge vignette and a top sheen), never a separate overlay object. Caller clips to the screen.
inline void paintScreenAtmosphere (juce::Graphics& g, juce::Rectangle<float> screen, const Theme& t)
{
    juce::ignoreUnused (t);
    // 1) edge vignette — darkens gently toward the aperture edges (curved-glass read).
    juce::ColourGradient vig (juce::Colours::transparentBlack, screen.getCentreX(), screen.getCentreY(),
                              juce::Colours::black.withAlpha (0.22f), screen.getX(), screen.getY(), true);
    vig.addColour (0.62, juce::Colours::transparentBlack);
    g.setGradientFill (vig);
    g.fillRect (screen);

    // 2) top sheen — a soft light fall-off over the upper third (glass catching light).
    juce::ColourGradient sheen (juce::Colours::white.withAlpha (0.055f), 0.0f, screen.getY(),
                                juce::Colours::transparentBlack,         0.0f, screen.getY() + screen.getHeight() * 0.42f, false);
    g.setGradientFill (sheen);
    g.fillRect (screen.getX(), screen.getY(), screen.getWidth(), screen.getHeight() * 0.42f);

    // 2b) under-bezel shadow — the faceplate lip shades the glass it overhangs
    // (the recessed-screen read of the reference plates: IMG_5855/5812 both
    // seat the glass visibly DOWN into the plate, so the lip is real depth,
    // with soft side falloff too).
    juce::ColourGradient lip (juce::Colours::black.withAlpha (0.36f), 0.0f, screen.getY(),
                              juce::Colours::transparentBlack,        0.0f, screen.getY() + 11.0f, false);
    g.setGradientFill (lip);
    g.fillRect (screen.getX(), screen.getY(), screen.getWidth(), 12.0f);

    juce::ColourGradient lipL (juce::Colours::black.withAlpha (0.20f), screen.getX(), 0.0f,
                               juce::Colours::transparentBlack,        screen.getX() + 6.0f, 0.0f, false);
    g.setGradientFill (lipL);
    g.fillRect (screen.getX(), screen.getY(), 6.0f, screen.getHeight());

    juce::ColourGradient lipR (juce::Colours::transparentBlack,        screen.getRight() - 6.0f, 0.0f,
                               juce::Colours::black.withAlpha (0.20f), screen.getRight(), 0.0f, false);
    g.setGradientFill (lipR);
    g.fillRect (screen.getRight() - 6.0f, screen.getY(), 6.0f, screen.getHeight());

    // 3) settled lower edge — a touch darker at the very bottom (the screen sits down into the well).
    juce::ColourGradient floorShade (juce::Colours::transparentBlack,         0.0f, screen.getBottom() - screen.getHeight() * 0.18f,
                                     juce::Colours::black.withAlpha (0.16f),   0.0f, screen.getBottom(), false);
    g.setGradientFill (floorShade);
    g.fillRect (screen.getX(), screen.getBottom() - screen.getHeight() * 0.18f, screen.getWidth(), screen.getHeight() * 0.18f);
}

// A small SEATED phosphor LCD window for the numeric readouts. Same screen material as
// the hero GraphDisplay (so the readouts read as the unit's displays, NOT light plastic
// wells that blend into the sand faceplate). Real recess depth — settled glass, scanlines,
// inner top-shadow + bottom-glow, dark keyline — so it seats into the panel, never a flat
// green overlay.
inline void drawReadoutGlass (juce::Graphics& g, juce::Rectangle<float> b, const Theme& t)
{
    const auto r = b.reduced (1.0f);
    const auto radius = t.wellRadius();
    {
        juce::Graphics::ScopedSaveState save (g);
        juce::Path clip;
        clip.addRoundedRectangle (r, radius);
        g.reduceClipRegion (clip);

        fillPhosphorGlass (g, r, t);                          // same glass as the hero screen
        g.setColour (juce::Colours::black.withAlpha (0.34f)); // settle darker so digits glow
        g.fillRect (r);

        g.setColour (juce::Colours::black.withAlpha (0.06f)); // LCD scanline dirt
        for (float y = r.getY() + 2.0f; y < r.getBottom() - 1.0f; y += 3.0f)
            g.drawLine (r.getX() + 2.0f, y, r.getRight() - 2.0f, y, 0.5f);

        juce::ColourGradient top (juce::Colours::black.withAlpha (0.52f), 0.0f, r.getY(),
                                  juce::Colours::transparentBlack,        0.0f, r.getY() + 5.0f, false);
        g.setGradientFill (top);                              // recessed top inner shadow
        g.fillRect (r.getX(), r.getY(), r.getWidth(), 5.0f);

        g.setColour (t.curveColour().withAlpha (0.16f)); // faint accent bottom inner glow
        g.fillRect (r.getX(), r.getBottom() - 1.5f, r.getWidth(), 1.5f);
    }
    g.setColour (t.screenEdge());                             // dark keyline = inset into panel
    g.drawRoundedRectangle (r, radius, 1.2f);
}

// Engraved faceplate text: the label reads as STAMPED into the sand plate rather
// than printed on top. On a light surface an engraved groove is in shadow with a
// thin light catch on the lower raised edge, so we lay a low-alpha warm-white catch
// one pixel below, then the dark ink on top. Light + material only (No-Fake-Layers):
// no drop-shadow object, just the deboss read. Caller sets the font first.
inline void drawEngravedText (juce::Graphics& g, const juce::String& text,
                              juce::Rectangle<int> area, juce::Justification just,
                              juce::Colour ink, float catchAlpha = 0.45f)
{
    g.setColour (juce::Colours::white.withAlpha (catchAlpha));
    g.drawFittedText (text, area.translated (0, 1), just, 1);
    g.setColour (ink);
    g.drawFittedText (text, area, just, 1);
}

// Engraved + letter-spaced (for the brand wordmark): machined-silk tracking,
// centred in `area`, deboss light-catch like drawEngravedText. Caller sets font.
inline void drawEngravedTrackedText (juce::Graphics& g, const juce::String& text,
                                     juce::Rectangle<float> area, const juce::Font& font,
                                     juce::Colour ink, float tracking,
                                     float catchAlpha = 0.45f)
{
    if (text.isEmpty())
        return;
    g.setFont (font);
    const int n = text.length();
    float total = tracking * (float) (n - 1);
    for (int i = 0; i < n; ++i)
        total += juce::GlyphArrangement::getStringWidth (font, text.substring (i, i + 1));

    const float y = area.getCentreY() - font.getHeight() * 0.5f;
    const auto drawRun = [&] (juce::Colour c, float dy)
    {
        g.setColour (c);
        float x = area.getCentreX() - total * 0.5f;
        for (int i = 0; i < n; ++i)
        {
            const auto glyph = text.substring (i, i + 1);
            const float w = juce::GlyphArrangement::getStringWidth (font, glyph);
            g.drawText (glyph, juce::Rectangle<float> (x, y + dy, w + 2.0f, font.getHeight()),
                        juce::Justification::centredLeft, false);
            x += w + tracking;
        }
    };
    drawRun (juce::Colours::white.withAlpha (catchAlpha), 1.0f);   // light catch below
    drawRun (ink, 0.0f);                                          // ink on top
}

// Slightly-aliased LCD numeral: render small, upscale nearest. `b` is local bounds.
inline void drawAliasedText (juce::Graphics& g, juce::Rectangle<float> b, const juce::String& text,
                             float fontSize, juce::Colour colour, float scale)
{
    const auto r = b.toNearestInt();
    const int iw = juce::jmax (1, juce::roundToInt (r.getWidth()  * scale));
    const int ih = juce::jmax (1, juce::roundToInt (r.getHeight() * scale));
    juce::Image img (juce::Image::ARGB, iw, ih, true);
    {
        juce::Graphics tg (img);
        tg.setFont (displayFont (fontSize * scale, false));
        tg.setColour (colour);
        tg.drawFittedText (text, img.getBounds(), juce::Justification::centred, 1);
    }
    g.setImageResamplingQuality (juce::Graphics::lowResamplingQuality);
    g.drawImage (img, b, juce::RectanglePlacement::stretchToFit);
}

} // namespace trench::ui
