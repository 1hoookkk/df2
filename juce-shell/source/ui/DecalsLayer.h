#pragma once

#include "Theme.h"

namespace trench::ui
{

// Draws the layout's free "decals" — text runs, rects and lines the layout
// INVENTS, anywhere on the panel. This is the bit that lets the See-Your-Plugin
// editor add brand-new elements instead of only restyling the fixed ones.
// Front-most and non-interactive.
class DecalsLayer : public juce::Component
{
public:
    explicit DecalsLayer (const Theme& theme) : t (theme)
    {
        setInterceptsMouseClicks (false, false);
    }

    void paint (juce::Graphics& g) override
    {
        for (const auto& d : t.decals())
        {
            g.setColour (d.colour);

            if (d.type == "rect")
            {
                if (d.fill) g.fillRect (d.rect);
                else        g.drawRect (d.rect, juce::jmax (1.0f, d.thickness));
            }
            else if (d.type == "line")
            {
                g.drawLine (d.rect.getX(), d.rect.getY(),
                            d.rect.getX() + d.rect.getWidth(),
                            d.rect.getY() + d.rect.getHeight(),
                            juce::jmax (1.0f, d.thickness));
            }
            else // "text" (default)
            {
                g.setFont (displayFont (juce::jmax (4.0f, d.fontSize), true));
                g.drawText (d.text, d.rect.toNearestInt(), juce::Justification::centred, false);
            }
        }
    }

private:
    Theme t;
};

} // namespace trench::ui
