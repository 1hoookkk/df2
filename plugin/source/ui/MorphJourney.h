#pragma once
#include "Theme.h"
#include <cmath>
#include <utility>
namespace trench::ui
{
class MorphJourney final : public juce::Component
{
public:
    explicit MorphJourney (const Theme& theme) : t (theme)
    {
        setInterceptsMouseClicks (false, false);
        setOpaque (false);
    }
    void setBodyName (const juce::String& raw)
    {
        const auto source = splitBodyName (raw);
        if (source.first == leftName && source.second == rightName)
            return;
        leftName = source.first;
        rightName = source.second;
        repaint();
    }
    void setState (float morph, float q, bool moving)
    {
        morph = juce::jlimit (0.0f, 1.0f, morph);
        q = juce::jlimit (0.0f, 1.0f, q);
        if (juce::approximatelyEqual (morph, morphValue)
            && juce::approximatelyEqual (q, qValue)
            && moving == isMoving)
            return;
        morphValue = morph;
        qValue = q;
        isMoving = moving;
        repaint();
    }
    void setAnimationPhase (double seconds)
    {
        if (! isMoving)
            return;
        animationPhase = seconds;
        repaint();
    }
    void paint (juce::Graphics& g) override
    {
        const auto full = getLocalBounds().toFloat().reduced (30.0f, 22.0f);
        if (full.isEmpty())
            return;
        drawEndpointLabel (g, leftName,
                           { full.getX(), full.getY(), full.getWidth() * 0.5f, 24.0f },
                           juce::Justification::topLeft);
        drawEndpointLabel (g, rightName,
                           { full.getCentreX(), full.getY(), full.getWidth() * 0.5f, 24.0f },
                           juce::Justification::topRight);
        const float railH = 30.0f;
        const auto rail = juce::Rectangle<float> (full.getX(), 0.0f, full.getWidth(), railH)
                              .withCentre ({ full.getCentreX(),
                                             full.getY() + full.getHeight() * 0.62f });
        const float centreY = rail.getCentreY();
        const float endInset = juce::jmax (17.0f, rail.getWidth() * 0.075f);
        const float startX = rail.getX() + endInset;
        const float endX = rail.getRight() - endInset;
        const float markerX = juce::jmap (morphValue, startX, endX);
        juce::ColourGradient chamber (juce::Colour (0xff2c302f), rail.getX(), rail.getY(),
                                      juce::Colour (0xff151817), rail.getX(), rail.getBottom(), false);
        chamber.addColour (0.52, juce::Colour (0xff202423));
        g.setGradientFill (chamber);
        g.fillRoundedRectangle (rail, 7.0f);
        g.setColour (juce::Colour (0xff0c0e0e).withAlpha (0.74f));
        g.drawRoundedRectangle (rail.reduced (0.7f), 6.5f, 1.0f);
        g.setColour (juce::Colour (0xffb5a78d).withAlpha (0.30f));
        g.drawLine (rail.getX() + 7.0f, rail.getY() + 1.2f,
                    rail.getRight() - 7.0f, rail.getY() + 1.2f, 0.7f);
        g.setColour (juce::Colour (0xffb7aa91).withAlpha (0.34f));
        g.drawLine (startX, centreY, endX, centreY, 0.75f);
        for (int i = 0; i <= 4; ++i)
        {
            const float x = juce::jmap ((float) i / 4.0f, startX, endX);
            const float tick = i == 0 || i == 4 ? 8.0f : 4.0f;
            g.drawLine (x, centreY - tick * 0.5f, x, centreY + tick * 0.5f, 0.75f);
        }
        const float breath = isMoving
                                 ? 0.72f + 0.28f * std::sin ((float) (animationPhase * 5.6548668))
                                 : 0.68f;
        const auto amber = t.amber();
        g.setColour (amber.withAlpha (0.46f * breath));
        g.drawLine (startX, centreY, markerX, centreY, 1.55f);
        const float pressure = 0.45f + qValue * 0.55f;
        const float core = 4.2f + pressure * 2.6f;
        for (int ring = 2; ring >= 0; --ring)
        {
            const float radius = core + (float) ring * (1.6f + pressure * 0.8f);
            const float alpha = (ring == 0 ? 0.95f : 0.20f + 0.08f * pressure)
                                * breath;
            g.setColour (ring == 0 ? amber.withAlpha (alpha)
                                   : amber.withAlpha (alpha * 0.72f));
            g.drawEllipse (markerX - radius, centreY - radius,
                           radius * 2.0f, radius * 2.0f, ring == 0 ? 1.0f : 0.65f);
        }
        g.setColour (amber.withAlpha (0.22f * breath));
        g.fillEllipse (markerX - core * 0.58f, centreY - core * 0.58f,
                       core * 1.16f, core * 1.16f);
        drawMouth (g, startX, centreY);
        drawMouth (g, endX, centreY);
    }
private:
    static juce::String cleanPart (juce::String value)
    {
        value = value.replaceCharacter ('_', ' ').replaceCharacter ('-', ' ').trim();
        while (value.contains ("  "))
            value = value.replace ("  ", " ");
        return value.toUpperCase();
    }
    static std::pair<juce::String, juce::String> splitBodyName (juce::String raw)
    {
        raw = raw.trim();
        if (raw.startsWithIgnoreCase ("CAVL_"))
            raw = raw.substring (5);
        const auto lower = raw.toLowerCase();
        int separator = lower.indexOf ("_to_");
        int separatorLength = 4;
        if (separator < 0)
        {
            separator = lower.indexOf (" to ");
            separatorLength = 4;
        }
        if (separator >= 0)
        {
            auto left = cleanPart (raw.substring (0, separator));
            auto right = cleanPart (raw.substring (separator + separatorLength));
            if (left.isNotEmpty() && right.isNotEmpty())
                return { left, right };
        }
        const auto body = cleanPart (raw);
        return { juce::String ("HOME"), body.isEmpty() ? juce::String ("NO FILTER") : body };
    }
    void drawEndpointLabel (juce::Graphics& g, const juce::String& text,
                            juce::Rectangle<float> bounds, juce::Justification justification) const
    {
        g.setFont (displayFont (13.0f, false).withExtraKerningFactor (0.045f));
        g.setColour (t.telemetry().brighter (1.65f).withAlpha (0.92f));
        g.drawFittedText (text, bounds.toNearestInt(), justification, 1, 0.9f);
    }
    static void drawMouth (juce::Graphics& g, float x, float y)
    {
        g.setColour (juce::Colour (0xffc0b399).withAlpha (0.48f));
        g.drawEllipse (x - 3.6f, y - 6.5f, 7.2f, 13.0f, 0.75f);
        g.setColour (juce::Colour (0xff090b0b).withAlpha (0.72f));
        g.drawLine (x, y - 5.8f, x, y + 5.8f, 0.8f);
    }
    Theme t;
    juce::String leftName { "HOME" };
    juce::String rightName { "NO FILTER" };
    float morphValue = 0.5f;
    float qValue = 0.0f;
    bool isMoving = false;
    double animationPhase = 0.0;
};
}
