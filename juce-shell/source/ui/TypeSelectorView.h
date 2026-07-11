#pragma once

#include "Theme.h"
#include "../PluginProcessor.h"   // ParamID
#include "../TrenchBodyRoster.h"  // bodyRoster / bodyDisplayName

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// The TYPE dropdown: warm plastic bar + body name + dashed-box arrow, with a
// transparent ComboBox child bound to the body parameter by the standard
// APVTS ComboBoxAttachment. We listen only to repaint our custom face when
// the selection changes (from the user or from host automation).
class TypeSelectorView : public juce::Component,
                         private juce::ComboBox::Listener
{
public:
    TypeSelectorView (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme), menuLookAndFeel (t)
    {
        setInterceptsMouseClicks (true, true);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        selector.setLookAndFeel (&menuLookAndFeel);
        selector.setInterceptsMouseClicks (false, false);
        selector.setWantsKeyboardFocus (false);   // let keystrokes pass to the host (play notes without clicking out)
        for (auto colourId : { juce::ComboBox::backgroundColourId, juce::ComboBox::outlineColourId,
                               juce::ComboBox::buttonColourId, juce::ComboBox::arrowColourId,
                               juce::ComboBox::textColourId })
            selector.setColour (colourId, juce::Colours::transparentBlack);
        selector.setTextWhenNothingSelected ({});
        populate();

        // Standard APVTS binding (items must exist first). Handles user picks
        // and host automation in both directions — no manual sync poll.
        attachment = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment> (
            apvts, ParamID::body, selector);

        selector.addListener (this);
        addAndMakeVisible (selector);

        // The TYPE dropdown is the PRESET/body picker only — no action items.
        // Seed is its own mode and Capture/Take is its own control (see the
        // Player/Seed/Capture spec); neither belongs in the preset list.
    }

    ~TypeSelectorView() override
    {
        selector.setLookAndFeel (nullptr);
        selector.removeListener (this);
    }

    // Action callbacks for the dropdown's non-body items (wired by the editor).
    // Currently unused — the dropdown is body-picker only. Kept for future expansion.
    std::function<void()> onSeed;
    std::function<void()> onExportBody;

    void resized() override { selector.setBounds (getLocalBounds().reduced (3, 2)); }

    void mouseEnter (const juce::MouseEvent&) override { repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { repaint(); }
    void mouseDown  (const juce::MouseEvent&) override
    {
        selector.showPopup();
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const auto recess = getLocalBounds().toFloat();
        // Edge-to-edge: the component rect IS the black opening; insets here
        // read as a dark ring around the bar (Tyson 2026-07-11).
        const auto bar = recess;
        const bool hot = isMouseOverOrDragging (true) || selector.isPopupActive();

        // Smoked bone selector bar painted into the machined plate's slot.
        drawIvoryWell (g, bar, 3.0f, hot, t);
        auto inner = bar.reduced (13.0f, 2.0f);

        // The dropdown arrow box is its OWN layout rect, converted to this
        // component's local coords. Falls back to a computed box if absent.
        juce::Rectangle<float> box;
        const auto arrowSrc = t.layout.sourceRectFor ("typeArrow");
        if (arrowSrc.getWidth() > 1.0f)
            box = sourceRectToEditor (arrowSrc).translated (-(float) getX(), -(float) getY());
        else
        {
            const float w = bar.getHeight() + t.typeArrowExtra();
            box = inner.removeFromRight (w).withSizeKeepingCentre (w - 8.0f, bar.getHeight() - 8.0f);
        }

        // body name fills from the left up to the arrow box, with clear right breathing
        // room before the divider so it never crowds the chevron.
        const auto textArea = juce::Rectangle<float> (inner.getX(), inner.getY(),
                                                      juce::jmax (10.0f, box.getX() - inner.getX() - 16.0f),
                                                      inner.getHeight());
        const auto selectedIndex = selector.getSelectedId() - 1;
        const auto typeText = selectedIndex >= 0 ? trench::bodyDisplayName (selectedIndex) : juce::String();
        
        // Render name: quiet engineered weight, warm charcoal ink; a touch
        // darker when hot (the only hover feedback — no painted face).
        drawTrackedText (g, typeText, textArea, displayFont (t.fontSize ("typeName", 14.0f), false),
                         hot ? juce::Colour (0xff141210) : t.labelInk(), 0.0f);

        // Engraved divider seam before the arrow segment: a dark cut with a
        // light catch beside it — a machined groove, not a combo-box border.
        g.setColour (juce::Colour (0xff2a2419).withAlpha (0.55f));
        g.drawLine (box.getX() - 4.0f, bar.getY() + 4.0f, box.getX() - 4.0f, bar.getBottom() - 4.0f, 1.0f);
        g.setColour (juce::Colours::white.withAlpha (0.35f));
        g.drawLine (box.getX() - 3.0f, bar.getY() + 4.0f, box.getX() - 3.0f, bar.getBottom() - 4.0f, 0.8f);

        // Engraved chevron: light catch below the cut, ink on top — the same
        // physical depth as the readout digits.
        const auto arrow = box.withSizeKeepingCentre (11.0f, 7.0f).translated (0.0f, 0.5f);
        juce::Path arrowPath;
        arrowPath.startNewSubPath (arrow.getX(), arrow.getY());
        arrowPath.lineTo (arrow.getCentreX(), arrow.getBottom());
        arrowPath.lineTo (arrow.getRight(), arrow.getY());
        g.setColour (juce::Colours::white.withAlpha (0.40f));
        g.strokePath (arrowPath, juce::PathStrokeType (1.5f, juce::PathStrokeType::mitered, juce::PathStrokeType::butt),
                      juce::AffineTransform::translation (0.0f, 1.0f));
        g.setColour (t.arrow());
        g.strokePath (arrowPath, juce::PathStrokeType (1.5f, juce::PathStrokeType::mitered, juce::PathStrokeType::butt));
    }

private:
    class MenuLookAndFeel final : public juce::LookAndFeel_V4
    {
    public:
        explicit MenuLookAndFeel (const Theme& theme) : t (theme) {}

        void drawComboBox (juce::Graphics&, int, int, bool, int, int, int, int,
                           juce::ComboBox&) override
        {
        }

        juce::Font getComboBoxFont (juce::ComboBox&) override
        {
            return displayFont (13.0f, false);
        }

        juce::Font getPopupMenuFont() override
        {
            return displayFont (13.0f, false);
        }

        void drawPopupMenuBackground (juce::Graphics& g, int width, int height) override
        {
            const auto area = juce::Rectangle<float> (0.0f, 0.0f, (float) width, (float) height);

            // A small hardware cartridge panel opening from the TYPE chip: deep
            // navy-charcoal body with a subtle vertical falloff and an inset
            // machined bevel — the same shell material, never a system menu.
            juce::ColourGradient body (juce::Colour (0xff1d2437), 0.0f, 0.0f,
                                       juce::Colour (0xff141a2a), 0.0f, (float) height, false);
            g.setGradientFill (body);
            g.fillRect (area);

            // inset bevel: light catches the top/left lip, shadow settles bottom/right
            g.setColour (juce::Colour (0xff3a4560).withAlpha (0.85f));
            g.drawLine (1.5f, 1.5f, (float) width - 1.5f, 1.5f, 1.0f);
            g.drawLine (1.5f, 1.5f, 1.5f, (float) height - 1.5f, 1.0f);
            g.setColour (juce::Colours::black.withAlpha (0.55f));
            g.drawLine (1.5f, (float) height - 1.5f, (float) width - 1.5f, (float) height - 1.5f, 1.0f);
            g.drawLine ((float) width - 1.5f, 1.5f, (float) width - 1.5f, (float) height - 1.5f, 1.0f);

            // outer keyline seats the panel against whatever it opens over
            g.setColour (juce::Colour (0xff0a0d16));
            g.drawRect (area.reduced (0.5f), 1.0f);
        }

        void drawPopupMenuItem (juce::Graphics& g, const juce::Rectangle<int>& area,
                                bool isSeparator, bool isActive, bool isHighlighted,
                                bool isTicked, bool hasSubMenu, const juce::String& text,
                                const juce::String&, const juce::Drawable*,
                                const juce::Colour*) override
        {
            auto r = area.toFloat();
            if (isSeparator)
            {
                // engraved groove: dark cut with a light lip below
                r = r.reduced (9.0f, 0.0f).withHeight (1.0f).withCentre ({ r.getCentreX(), r.getCentreY() });
                g.setColour (juce::Colours::black.withAlpha (0.50f));
                g.fillRect (r);
                g.setColour (juce::Colour (0xff3a4560).withAlpha (0.40f));
                g.fillRect (r.translated (0.0f, 1.0f));
                return;
            }

            const bool action = text.startsWithIgnoreCase ("seed") || text.startsWithIgnoreCase ("export");
            if (isHighlighted && isActive)
            {
                // warm cream wash + wine rail — the shell's own lamp family
                g.setColour (juce::Colour (0xffe9dfc6).withAlpha (0.10f));
                g.fillRect (r.reduced (2.0f, 1.0f));

                auto rail = r.reduced (2.0f, 1.0f);
                rail.setWidth (2.0f);
                g.setColour (juce::Colour (0xffa4263c).withAlpha (0.85f));   // wine
                g.fillRect (rail);
            }

            if (isTicked)
            {
                // current body: small aged-cream chip, like a lit legend
                g.setColour (juce::Colour (0xffe9dfc6).withAlpha (0.85f));
                float leftOffset = isHighlighted ? 6.0f : 2.0f;
                g.fillRoundedRectangle (r.removeFromLeft (4.0f).translated (leftOffset, 0.0f).reduced (1.0f, 4.0f), 1.0f);
            }

            const auto textArea = area.reduced (action ? 10 : 12, 0);
            g.setFont (displayFont (action ? 11.5f : 13.0f, action));

            // aged cream ink on the dark panel; disabled rows sink into the navy
            juce::Colour textCol = isActive ? juce::Colour (0xffe9dfc6)
                                            : juce::Colour (0xff5d6478);
            if (isTicked)
                textCol = juce::Colour (0xfff4ecd8);
            g.setColour (textCol);

            // Mixed case display
            g.drawFittedText (text, textArea, juce::Justification::centredLeft, 1);

            if (hasSubMenu)
            {
                const auto arrow = area.toFloat().removeFromRight (14.0f).withSizeKeepingCentre (5.0f, 8.0f);
                juce::Path p;
                p.startNewSubPath (arrow.getX(), arrow.getY());
                p.lineTo (arrow.getRight(), arrow.getCentreY());
                p.lineTo (arrow.getX(), arrow.getBottom());
                g.setColour (juce::Colour (0xffe9dfc6).withAlpha (0.8f));
                g.strokePath (p, juce::PathStrokeType (1.2f));
            }
        }

        void getIdealPopupMenuItemSize (const juce::String& text, bool isSeparator,
                                        int standardMenuItemHeight,
                                        int& idealWidth, int& idealHeight) override
        {
            if (isSeparator)
            {
                idealWidth = 150;
                idealHeight = 9;
                return;
            }

            idealHeight = juce::jmax (standardMenuItemHeight, text.startsWithIgnoreCase ("seed") ? 24 : 27);
            idealWidth = juce::jmax (165, text.length() * 8 + 34);
        }

    private:
        Theme t;
    };

    static void drawTrackedText (juce::Graphics& g, const juce::String& text,
                                 juce::Rectangle<float> area, juce::Font font,
                                 juce::Colour colour, float tracking)
    {
        if (text.isEmpty())
            return;

        g.setFont (font);
        g.setColour (colour);

        const int n = text.length();
        const float rawWidth = juce::GlyphArrangement::getStringWidth (font, text);
        if (n > 1)
            tracking = juce::jlimit (0.0f, tracking,
                                     (area.getWidth() - rawWidth) / (float) (n - 1));
        else
            tracking = 0.0f;

        float x = area.getX();
        const float y = area.getCentreY() - font.getHeight() * 0.48f;
        for (int i = 0; i < n; ++i)
        {
            const auto glyph = text.substring (i, i + 1);
            const float w = juce::GlyphArrangement::getStringWidth (font, glyph);
            g.drawText (glyph, juce::Rectangle<float> (x, y, w + 2.0f, font.getHeight()),
                        juce::Justification::centredLeft, false);
            x += w + tracking;
            if (x > area.getRight())
                break;
        }
    }

    void comboBoxChanged (juce::ComboBox*) override { repaint(); }

    void populate()
    {
        selector.clear (juce::dontSendNotification);
        int count = 0;
        const auto* entries = trench::bodyRoster (count);
        for (int i = 0; i < count; ++i)
            selector.addItem (entries[i].displayName, i + 1);
    }

    Theme t;
    MenuLookAndFeel menuLookAndFeel;
    juce::ComboBox selector;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> attachment;
};

} // namespace trench::ui
