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
        // Clear software typography over the physical plate: direct dark text,
        // relaxed weight, no engraved catch-light or poster-headline treatment.
        const auto draw = [this, &g] (const juce::String& id, const juce::String& text, bool centred)
        {
            const auto r = t.rect (id);
            // A zero-size rect (or zero font) means "hidden" — the layout editor's
            // way to delete a label without a separate visibility flag.
            const float fs = t.fontSize (id, 11.0f);
            if (r.getWidth() < 1.0f || r.getHeight() < 1.0f || fs < 0.5f || text.isEmpty())
                return;
            g.setFont (displayFont (fs, false).withExtraKerningFactor (0.025f));
            g.setColour (t.textColour (id, t.labelInk()));
            g.drawFittedText (text.toUpperCase(), r.toNearestInt(),
                              centred ? juce::Justification::centred
                                       : juce::Justification::centredLeft,
                              1, 0.92f);
        };

        draw ("filterLabel", t.text ("filterLabel", ""), false);
        draw ("typeLabel",   t.text ("typeLabel",   "TYPE"), false);
        // SOUND draws the Q/SLAM mode as a real button component over qLabel, so
        // railLower is intentionally blank there. MOVE draws a normal TIME label.
        draw ("morphLabel",  railUpper, true);
        draw ("qLabel",      railLower, true);

        // Product name gets the one firmer face on the plate. No wide tracking
        // or deboss treatment; it remains a small nameplate, not a headline.
        {
            const auto br = t.rect ("brandLabel");
            const float bfs = t.fontSize ("brandLabel", 16.5f);
            if (br.getWidth() >= 1.0f && bfs >= 0.5f)
            {
                g.setFont (displayFont (bfs, true).withExtraKerningFactor (0.045f));
                g.setColour (t.textColour ("brandLabel", t.labelInk()));
                g.drawFittedText (t.text ("brandLabel", ""), br.toNearestInt(),
                                  juce::Justification::centredLeft, 1, 0.92f);
            }
            const auto sr = t.rect ("brandSub");
            const float sfs = t.fontSize ("brandSub", 9.0f);
            if (sr.getWidth() >= 1.0f && sfs >= 0.5f)
            {
                g.setFont (displayFont (sfs, true));
                g.setColour (t.textColour ("brandSub", t.labelInk()));
                g.drawFittedText (t.text ("brandSub", ""), sr.toNearestInt(),
                                  juce::Justification::centredLeft, 1, 0.92f);
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
