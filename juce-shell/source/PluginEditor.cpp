#include "PluginEditor.h"
#include "BinaryData.h"

namespace
{
constexpr int kEditorWidth = 540;
constexpr int kEditorHeight = 839;
constexpr float kPanelSourceWidth = 1024.0f;
constexpr float kPanelSourceHeight = 1591.0f;

juce::Rectangle<float> sourceRectToEditor (juce::Rectangle<float> sourceRect)
{
    return {
        sourceRect.getX() * kEditorWidth / kPanelSourceWidth,
        sourceRect.getY() * kEditorHeight / kPanelSourceHeight,
        sourceRect.getWidth() * kEditorWidth / kPanelSourceWidth,
        sourceRect.getHeight() * kEditorHeight / kPanelSourceHeight
    };
}
}

PluginEditor::PluginEditor (PluginProcessor& p)
    : AudioProcessorEditor (&p)
{
    panelImage = juce::ImageCache::getFromMemory (BinaryData::df2_panel_shadow_png,
                                                  BinaryData::df2_panel_shadow_pngSize);
    setOpaque (true);
    setResizable (false, false);
    setSize (kEditorWidth, kEditorHeight);
}

PluginEditor::~PluginEditor() = default;

void PluginEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colours::black);

    if (panelImage.isValid())
        g.drawImage (panelImage, getLocalBounds().toFloat());

    drawFrequencyCurve (g);
}

void PluginEditor::resized()
{
}

void PluginEditor::drawFrequencyCurve (juce::Graphics& g)
{
    const auto display = sourceRectToEditor ({ 128.0f, 258.0f, 776.0f, 363.0f }).reduced (7.0f, 9.0f);

    juce::Graphics::ScopedSaveState saveState (g);
    g.reduceClipRegion (display.toNearestInt());

    const auto area = display.toNearestInt().reduced (5, 7);
    const auto left = area.getX();
    const auto top = area.getY();
    const auto width = area.getWidth();
    const auto height = area.getHeight();

    struct PointSpec
    {
        float x;
        float y;
    };

    // Hand-pinned to the FL/E-mu visual reference: crude frequency trace,
    // long flat floor, abrupt aliased peaks, steep dropouts, and hard tails.
    constexpr PointSpec points[] {
        { 0.000f, 0.610f }, { 0.075f, 0.610f }, { 0.155f, 0.610f },
        { 0.245f, 0.608f }, { 0.305f, 0.596f }, { 0.365f, 0.565f },
        { 0.420f, 0.505f }, { 0.455f, 0.410f }, { 0.482f, 0.245f },
        { 0.500f, 0.115f }, { 0.515f, 0.305f }, { 0.535f, 0.505f },
        { 0.565f, 0.602f }, { 0.605f, 0.630f }, { 0.650f, 0.560f },
        { 0.676f, 0.230f }, { 0.688f, 0.480f }, { 0.705f, 0.605f },
        { 0.725f, 0.615f }, { 0.742f, 0.300f }, { 0.755f, 0.470f },
        { 0.770f, 0.265f }, { 0.787f, 0.735f }, { 0.805f, 0.900f },
        { 0.842f, 0.900f }, { 0.872f, 0.800f }, { 0.895f, 0.650f },
        { 0.910f, 0.400f }, { 0.922f, 0.900f }, { 1.000f, 0.900f }
    };

    auto toPixel = [&] (PointSpec p)
    {
        return juce::Point<int> {
            left + juce::roundToInt (p.x * static_cast<float> (width - 1)),
            top + juce::roundToInt (p.y * static_cast<float> (height - 1))
        };
    };

    auto plot = [&] (int x, int y, juce::Colour colour)
    {
        g.setColour (colour);
        g.fillRect (x, y, 1, 1);
    };

    auto drawAliasedLine = [&] (juce::Point<int> a, juce::Point<int> b, juce::Colour colour)
    {
        auto x0 = a.x;
        auto y0 = a.y;
        const auto x1 = b.x;
        const auto y1 = b.y;
        const auto dx = std::abs (x1 - x0);
        const auto sx = x0 < x1 ? 1 : -1;
        const auto dy = -std::abs (y1 - y0);
        const auto sy = y0 < y1 ? 1 : -1;
        auto err = dx + dy;

        for (;;)
        {
            plot (x0, y0, colour);
            if (x0 == x1 && y0 == y1)
                break;

            const auto e2 = 2 * err;
            if (e2 >= dy)
            {
                err += dy;
                x0 += sx;
            }
            if (e2 <= dx)
            {
                err += dx;
                y0 += sy;
            }
        }
    };

    const auto dark = juce::Colour (0xff0b85a0);
    const auto core = juce::Colour (0xff65d8f5);
    const auto hot = juce::Colour (0xffd7fbff);

    constexpr auto numPoints = static_cast<int> (sizeof (points) / sizeof (points[0]));
    for (int i = 1; i < numPoints; ++i)
    {
        const auto a = toPixel (points[i - 1]);
        const auto b = toPixel (points[i]);
        drawAliasedLine ({ a.x, a.y + 1 }, { b.x, b.y + 1 }, dark);
        drawAliasedLine (a, b, core);
    }

    // A few crude bright pixels on high resonances, matching the reference's
    // old raster UI sparkle without adding separate marker glyphs.
    for (const auto peak : { points[9], points[15], points[19], points[21], points[27] })
    {
        const auto p = toPixel (peak);
        plot (p.x, p.y, hot);
        plot (p.x + 1, p.y, hot);
        plot (p.x, p.y - 1, hot);
    }
}
