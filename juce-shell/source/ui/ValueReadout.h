#pragma once

#include "Theme.h"

namespace trench::ui
{

// Numeric readout: a clean recessed inset (the cleaner reference look) — light plastic/LCD
// well with a crisp dark numeral, like the reference plate. A precise hardware readout.
class ValueReadout : public juce::Component
{
public:
    ValueReadout (juce::String elementId, const Theme& theme)
        : id (std::move (elementId)), t (theme)
    {
        setInterceptsMouseClicks (false, false);
    }

    void setNormalised (float v)
    {
        if (textOverride.isNotEmpty()) { textOverride.clear(); repaint(); }
        if (! juce::approximatelyEqual (v, value))
        {
            value = v;
            repaint();
        }
    }

    void setActive (bool active)
    {
        if (isActive != active)
        {
            isActive = active;
            repaint();
        }
    }

    // Show literal text instead of the % numeric (e.g. the TIME value "1 BAR").
    void setText (const juce::String& s)
    {
        if (s != textOverride) { textOverride = s; repaint(); }
    }

    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds().toFloat();

        // NO painted face — the shell art's baked cream window IS the part.
        // Only the digits are rendered (same law as the wheels/TYPE bar).
        const auto pct = juce::jlimit (0.0f, 1.0f, value) * 100.0f;
        const auto numeric = textOverride.isNotEmpty() ? textOverride : juce::String (pct, 1);

        // Counter digits: crisp DIN-flavoured hardware numerals at natural weight —
        // readable, never graphic (the machine's display face, not UI chrome).
        const float fs = t.fontSize (id, 18.0f) * 1.05f;
        g.setFont (displayFont (fs, false));
        g.setColour (t.labelInk());
        g.drawText (numeric, b.reduced (7.0f, 2.0f).toNearestInt(), juce::Justification::centred);

        // Aged glass: a whisper of static grain + edge dirt over the baked cream
        // window so the chip sits with the worn shell instead of reading factory-new.
        // Material aging on the existing part, not a new layer.
        if (aging.isNull() || aging.getWidth() != getWidth() || aging.getHeight() != getHeight())
            rebuildAging();
        g.drawImageAt (aging, 0, 0);
    }

private:
    void rebuildAging()
    {
        const int w = juce::jmax (1, getWidth()), h = juce::jmax (1, getHeight());
        aging = juce::Image (juce::Image::ARGB, w, h, true);
        juce::Image::BitmapData bd (aging, juce::Image::BitmapData::writeOnly);
        auto hash = [] (uint32_t v) { v ^= v >> 16; v *= 0x7feb352dU; v ^= v >> 15; v *= 0x846ca68bU; v ^= v >> 16; return v; };
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x)
            {
                const float n = (float) (hash ((uint32_t) (x * 73856093 ^ y * 19349663 ^ 0x9e37)) & 1023) / 1023.0f;
                // edge dirt: a soft darkening band hugging the window border
                const float d = (float) juce::jmin (juce::jmin (x, w - 1 - x), juce::jmin (y, h - 1 - y));
                const float edge = juce::jlimit (0.0f, 1.0f, 1.0f - d / 3.5f);
                const float dark = 0.030f * n + 0.085f * edge * (0.6f + 0.4f * n);
                const float light = 0.022f * juce::jmax (0.0f, n - 0.82f) / 0.18f;
                if (light > dark)
                    bd.setPixelColour (x, y, juce::Colours::white.withAlpha (light));
                else
                    bd.setPixelColour (x, y, juce::Colour (0xff2a1e14).withAlpha (dark));
            }
    }

    juce::Image aging;
    juce::String id;
    Theme t;
    float value = 0.0f;
    juce::String textOverride;
    bool isActive = false;
};

} // namespace trench::ui
