#pragma once
#include "Theme.h"
namespace trench::ui
{
class LabelsLayer : public juce::Component
{
public:
    explicit LabelsLayer (const Theme& theme) : t (theme)
    {
        setInterceptsMouseClicks (false, false);
    }
    void setRailLabels (juce::String upper, juce::String lower)
    {
        if (upper != railUpper || lower != railLower)
        {
            railUpper = std::move (upper); railLower = std::move (lower); repaint();
        }
    }
    void setFooter (juce::String right)
    {
        if (right != footerRight) { footerRight = std::move (right); repaint(); }
    }
    void paint (juce::Graphics& g) override
    {
        const auto draw = [this, &g] (const juce::String& id, const juce::String& text,
                                      bool centred, bool strong = false)
        {
            const auto r = t.rect (id);
            const float fs = t.fontSize (id, 11.0f);
            if (r.getWidth() < 1.0f || r.getHeight() < 1.0f || fs < 0.5f || text.isEmpty())
                return;
            g.setFont (displayFont (fs, strong).withExtraKerningFactor (0.025f));
            g.setColour (t.textColour (id, t.labelInk()));
            g.drawFittedText (text.toUpperCase(), r.toNearestInt(),
                              centred ? juce::Justification::centred
                                       : juce::Justification::centredLeft, 1);
        };
        draw ("filterLabel", t.text ("filterLabel", ""), false);
        draw ("typeLabel",   t.text ("typeLabel",   "BODY"), true, true);
        draw ("amountLabel", t.text ("amountLabel", "AMOUNT"), true, true);
        draw ("morphLabel",  railUpper, true, true);
        draw ("qLabel",      railLower, true, true);
        {
            const auto br = t.rect ("brandLabel");
            const float bfs = t.fontSize ("brandLabel", 16.5f);
            if (br.getWidth() >= 1.0f && bfs >= 0.5f)
            {
                // Original engraved treatment, just set tighter (X3 logos sit almost
                // touching) with a slightly deeper catch for polish.
                g.setFont (juce::Font (juce::FontOptions ("Arial", bfs, juce::Font::bold))
                               .withExtraKerningFactor (-0.012f));
                drawEngravedText (g, t.text ("brandLabel", ""), br.toNearestInt(),
                                  juce::Justification::centredLeft,
                                  t.textColour ("brandLabel", t.labelInk()), 0.72f);
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
}
