#pragma once

#include "Theme.h"

namespace trench::ui
{

// Transparent, non-interactive overlay drawing the fixed engraved faceplate
// labels.
class LabelsLayer : public juce::Component
{
public:
    explicit LabelsLayer (const Theme& theme) : t (theme)
    {
        setInterceptsMouseClicks (false, false);
    }

    // The two rails are page-specific (SOUND = MORPH + Q/SLAM toggle, MOVE = MOVE/TIME).
    void setRailLabels (juce::String upper, juce::String lower)
    {
        if (upper != railUpper || lower != railLower)
        {
            railUpper = std::move (upper); railLower = std::move (lower); repaint();
        }
    }

    // Footer status line — the found-machine engineering silk ("6xDF2T" left,
    // live sample rate right, from the reference plate). Editor feeds the rate.
    void setFooter (juce::String right)
    {
        if (right != footerRight) { footerRight = std::move (right); repaint(); }
    }

    void paint (juce::Graphics& g) override
    {
        // Fixed labels are stamped into the sand plate: a restrained warm-white
        // catch on the lower edge keeps the lettering from reading as flat ink.
        const auto draw = [this, &g] (const juce::String& id, const juce::String& text,
                                      bool centred, bool strong = false)
        {
            const auto r = t.rect (id);
            // A zero-size rect (or zero font) means "hidden" — the layout editor's
            // way to delete a label without a separate visibility flag.
            const float fs = t.fontSize (id, 11.0f);
            if (r.getWidth() < 1.0f || r.getHeight() < 1.0f || fs < 0.5f || text.isEmpty())
                return;
            g.setFont (displayFont (fs, strong).withExtraKerningFactor (0.025f));
            // Only the product logo gets the pale engraved catch. Ordinary
            // faceplate labels are plain dark silk; applying the deboss helper
            // here makes every glyph grow a distracting white outline.
            g.setColour (t.textColour (id, t.labelInk()));
            g.drawFittedText (text.toUpperCase(), r.toNearestInt(),
                              centred ? juce::Justification::centred
                                       : juce::Justification::centredLeft, 1);
        };

        draw ("filterLabel", t.text ("filterLabel", ""), false);
        draw ("typeLabel",   t.text ("typeLabel",   "BODY"), true, true);
        draw ("amountLabel", t.text ("amountLabel", "AMOUNT"), true, true);
        // SOUND draws the Q/SLAM mode as a real button component over qLabel, so
        // railLower is intentionally blank there. MOVE draws a normal TIME label.
        draw ("morphLabel",  railUpper, true, true);
        draw ("qLabel",      railLower, true, true);

        // Product name is left-seated in its small nameplate, with the same
        // shallow engraved edge/catch as the rail labels.
        {
            const auto br = t.rect ("brandLabel");
            const float bfs = t.fontSize ("brandLabel", 16.5f);
            if (br.getWidth() >= 1.0f && bfs >= 0.5f)
            {
                g.setFont (juce::Font (juce::FontOptions ("Arial", bfs, juce::Font::bold))
                               .withExtraKerningFactor (0.035f));
                drawEngravedText (g, t.text ("brandLabel", ""), br.toNearestInt(),
                                  juce::Justification::centredLeft,
                                  t.textColour ("brandLabel", t.labelInk()), 0.65f);
            }
            const auto sr = t.rect ("brandSub");
            const float sfs = t.fontSize ("brandSub", 9.0f);
            if (sr.getWidth() >= 1.0f && sfs >= 0.5f)
            {
                g.setFont (displayFont (sfs, true));
                g.setColour (t.textColour ("brandSub", t.labelInk()));
                g.drawText (t.text ("brandSub", ""), sr.toNearestInt(),
                            juce::Justification::centredLeft, false);
            }
        }
    }

private:
    Theme t;
    juce::String railUpper { "MORPH" };
    juce::String railLower {};
    juce::String footerRight;
};

} // namespace trench::ui
