#pragma once
#include "Theme.h"
#include <juce_gui_basics/juce_gui_basics.h>
#include <functional>

namespace trench::ui
{
/// First-run guided tour across the WHOLE face.
///
/// The panel is deliberately sparse and its screen-UP SLAM gesture is invisible.
/// Painting instructions onto the artwork fought the trace; stock JUCE tooltips
/// are host-dependent and off-brand. So the face is dimmed, one control is
/// spotlit per step, and the card sits clear of it. NEXT to advance, SKIP to
/// leave, never shown again.
class Onboarding final : public juce::Component,
                         private juce::Timer
{
public:
    explicit Onboarding (const Theme& theme) : t (theme)
    {
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Getting started");
        setAlwaysOnTop (true);
    }

    static bool shouldShow() { return ! stateFile().existsAsFile(); }
    static void markDone()
    {
        auto f = stateFile();
        f.getParentDirectory().createDirectory();
        f.replaceWithText ("done");
    }

    std::function<void()> onDismiss;
    /// Demo hooks: during the MORPH step the tour sweeps the wheel itself so the
    /// user SEES the travel instead of reading about it. The editor owns the
    /// parameter gesture; the tour only reports sweep phase 0..1 and completion.
    std::function<void (float)> onDemoMorph;
    std::function<void()> onDemoEnd;

    /// Re-run the tour (logo click). Does not touch the done-file.
    void replay (int startStep = 0)
    {
        endDemo();
        dismissing = false;
        alpha = 1.0f;
        step = juce::jlimit (0, numSteps() - 1, startStep);
        setVisible (true);
        toFront (false);
        if (step == kDemoStep) beginDemo();
        repaint();
    }

    /// Invisible click target the editor places over the TRENCH badge.
    struct ReplayHotspot final : juce::Component
    {
        ReplayHotspot() { setMouseCursor (juce::MouseCursor::PointingHandCursor); }
        std::function<void()> onClick;
        void mouseDown (const juce::MouseEvent&) override { if (onClick) onClick(); }
    };

    void mouseMove (const juce::MouseEvent& e) override
    {
        const bool n = nextBounds().contains (e.position);
        const bool s = skipBounds().contains (e.position);
        if (n != hoverNext || s != hoverSkip) { hoverNext = n; hoverSkip = s; repaint(); }
    }
    void mouseExit (const juce::MouseEvent&) override
    {
        if (hoverNext || hoverSkip) { hoverNext = hoverSkip = false; repaint(); }
    }
    void mouseDown (const juce::MouseEvent& e) override
    {
        if (skipBounds().contains (e.position)) { finish(); return; }
        if (step + 1 >= numSteps()) { finish(); return; }
        endDemo();
        ++step;
        if (step == kDemoStep) beginDemo();
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const auto full = getLocalBounds().toFloat();
        const auto spot = spotlight().expanded (4.0f, 4.0f);

        // Scrim over the whole face with the spotlit control punched out, so the
        // user's eye goes to the one thing the step is talking about. Warm and
        // half-strength: the panel should read as hardware with the room lights
        // down, not as a software modal — the beige plate stays recognisable.
        {
            juce::Path scrim;
            scrim.setUsingNonZeroWinding (false);
            scrim.addRectangle (full);
            scrim.addRoundedRectangle (spot, 5.0f);
            g.setColour (juce::Colour (0xff1c130a).withAlpha (0.42f * alpha));
            g.fillPath (scrim);
        }
        g.setColour (t.curveColour().withAlpha (0.55f * alpha));
        g.drawRoundedRectangle (spot, 5.0f, 1.1f);
        paintGestureHint (g, spot);

        // Tooltip card, anchored to the spotlit control.
        const auto card = cardBounds();
        paintTail (g, alpha);
        g.setColour (juce::Colour (0xff0b0d10).withAlpha (juce::jmin (1.0f, 1.06f * alpha)));
        g.fillRoundedRectangle (card, 5.0f);
        g.setColour (t.curveColour().withAlpha (0.30f * alpha));
        g.drawRoundedRectangle (card.reduced (0.5f), 5.0f, 0.8f);

        const auto ink = t.curveColour();
        const auto& s = steps()[(size_t) step];
        auto content = card.reduced (9.0f, 6.0f);
        auto footer = content.removeFromBottom (13.0f);
        auto title = content.removeFromTop (14.0f);

        // Whole-pixel font sizes and no horizontal squeeze: fitted text at this
        // size condenses the glyphs into artifacts. Wrap, never squash.
        g.setFont (telemetryFont (11.0f, false));
        g.setColour (ink.withAlpha (0.95f * alpha));
        g.drawText (s.title, title.toNearestInt(),
                    juce::Justification::centredLeft, false);

        g.setFont (telemetryFont (9.0f, false));
        g.setColour (ink.withAlpha (0.72f * alpha));
        g.drawFittedText (s.body, content.toNearestInt(),
                          juce::Justification::centredLeft, 4, 1.0f);

        for (int i = 0; i < numSteps(); ++i)
        {
            const float cx = footer.getX() + 3.0f + (float) i * 7.0f;
            const float r  = (i == step) ? 2.2f : 1.4f;
            g.setColour (ink.withAlpha ((i == step ? 0.90f : 0.30f) * alpha));
            g.fillEllipse (cx - r, footer.getCentreY() - r, r * 2.0f, r * 2.0f);
        }

        g.setFont (telemetryFont (9.0f, false));
        const bool last = (step + 1 >= numSteps());
        g.setColour (ink.withAlpha ((hoverNext ? 1.0f : 0.82f) * alpha));
        g.drawText (last ? "START" : "NEXT", nextBounds().toNearestInt(),
                    juce::Justification::centredRight, false);
        if (! last)
        {
            g.setColour (ink.withAlpha ((hoverSkip ? 0.70f : 0.32f) * alpha));
            g.drawText ("SKIP", skipBounds().toNearestInt(),
                        juce::Justification::centredRight, false);
        }
    }

private:
    enum Anim { animNone, animWheel, animUp };
    struct Step { const char* rectId; const char* title; const char* body; Anim anim; };
    static const Step* steps()
    {
        static const Step s[] = {
            { "typeSelector", "THE FILTERS",
              "One roars, one talks, one bites. NO FILTER is a choice too: "
              "nothing but the distortion.",
              animNone },
            { "morphWheel", "MORPH",
              "The wheel morphs one filter into another. Every point in "
              "between is a real filter. This is where you build the instrument.",
              animWheel },
            { "qWheel", "Q",
              "Q travels the body's authored second axis. Push it to sharpen or "
              "transform the response.",
              animWheel },
            { "spectrumGrid", "SLAM",
              "Drag up on the screen to give your sound massive density and balls.",
              animUp },
        };
        return s;
    }
    static int numSteps() { return 4; }

    juce::Rectangle<float> spotlight() const
    {
        auto r = t.rect (steps()[(size_t) step].rectId);
        return r.isEmpty() ? getLocalBounds().toFloat().reduced (40.0f) : r;
    }
    /// The card is a TOOLTIP on the spotlit control: it sits immediately beside
    /// it, aligned to it, not floating in the middle of the face. Below where
    /// there is room, above otherwise, clamped inside the panel.
    juce::Rectangle<float> cardBounds() const
    {
        const auto full = getLocalBounds().toFloat();
        const auto spot = spotlight().expanded (4.0f, 4.0f);
        const float w = juce::jmin (full.getWidth() - 12.0f, 222.0f);
        const float h = 74.0f;
        float x = spot.getCentreX() - w * 0.5f;
        x = juce::jlimit (full.getX() + 6.0f, full.getRight() - w - 6.0f, x);
        const bool below = (spot.getBottom() + 7.0f + h) <= (full.getBottom() - 6.0f);
        const float y = below ? spot.getBottom() + 7.0f
                              : juce::jmax (full.getY() + 6.0f, spot.getY() - h - 7.0f);
        return { x, y, w, h };
    }
    /// Crude little arrows showing which way the gesture goes: wheels get a
    /// chevron ping-ponging along the roller; SLAM gets chevrons drifting up.
    void paintGestureHint (juce::Graphics& g, juce::Rectangle<float> spot) const
    {
        const auto anim = steps()[(size_t) step].anim;
        if (anim == animNone)
            return;
        const auto ink = t.curveColour();
        const auto chevron = [&] (juce::Point<float> tip, float dx, float dy, float a)
        {
            // Two strokes meeting at the tip, opening opposite the direction.
            const float s = 5.0f;
            const juce::Point<float> back { tip.x - dx * s, tip.y - dy * s };
            juce::Path p;
            p.startNewSubPath (back.x - dy * s, back.y + dx * s);
            p.lineTo (tip.x, tip.y);
            p.lineTo (back.x + dy * s, back.y - dx * s);
            g.setColour (ink.withAlpha (juce::jlimit (0.0f, 1.0f, a) * alpha));
            g.strokePath (p, juce::PathStrokeType (1.6f, juce::PathStrokeType::curved,
                                                   juce::PathStrokeType::rounded));
        };
        if (anim == animWheel)
        {
            // One chevron sliding left-right along the roller, nose leading.
            const float sway = std::sin (juce::MathConstants<float>::twoPi * animPhase);
            const float dir  = std::cos (juce::MathConstants<float>::twoPi * animPhase) >= 0.0f ? 1.0f : -1.0f;
            chevron ({ spot.getCentreX() + sway * spot.getWidth() * 0.30f,
                       spot.getY() - 7.0f }, dir, 0.0f, 0.85f);
            return;
        }
        for (int i = 0; i < 3; ++i)
        {
            const float ph = std::fmod (animPhase + (float) i / 3.0f, 1.0f);
            const float fade = std::sin (juce::MathConstants<float>::pi * ph) * 0.85f;
            chevron ({ spot.getCentreX(),
                       spot.getBottom() - 14.0f - ph * (spot.getHeight() - 28.0f) },
                     0.0f, -1.0f, fade);
        }
    }
    /// Little pointer from the card back to the control it describes.
    void paintTail (juce::Graphics& g, float a) const
    {
        const auto spot = spotlight().expanded (4.0f, 4.0f);
        const auto c = cardBounds();
        const bool below = c.getY() > spot.getCentreY();
        const float tx = juce::jlimit (c.getX() + 14.0f, c.getRight() - 14.0f, spot.getCentreX());
        const float ty = below ? c.getY() : c.getBottom();
        const float dir = below ? -1.0f : 1.0f;
        juce::Path p;
        p.startNewSubPath (tx - 5.0f, ty);
        p.lineTo (tx, ty + dir * 6.0f);
        p.lineTo (tx + 5.0f, ty);
        p.closeSubPath();
        g.setColour (juce::Colour (0xff0b0d10).withAlpha (juce::jmin (1.0f, 1.06f * a)));
        g.fillPath (p);
    }
    juce::Rectangle<float> nextBounds() const
    {
        const auto c = cardBounds();
        return { c.getRight() - 53.0f, c.getBottom() - 17.0f, 44.0f, 13.0f };
    }
    juce::Rectangle<float> skipBounds() const
    {
        const auto c = cardBounds();
        return { c.getRight() - 98.0f, c.getBottom() - 17.0f, 38.0f, 13.0f };
    }
    static constexpr int kDemoStep = 1;   // MORPH
    void beginDemo()
    {
        if (onDemoMorph == nullptr) return;
        demoActive = true;
        demoPhase = 0.0f;
    }
    void endDemo()
    {
        if (! demoActive) return;
        demoActive = false;
        if (onDemoEnd) onDemoEnd();
    }
    void visibilityChanged() override
    {
        // The gesture hints animate for as long as the tour is up.
        if (isVisible()) startTimerHz (60);
        else stopTimer();
    }
    void finish()
    {
        if (dismissing) return;
        endDemo();
        dismissing = true;
        markDone();
        startTimerHz (60);
    }
    static juce::File stateFile()
    {
        return juce::File::getSpecialLocation (juce::File::userApplicationDataDirectory)
                   .getChildFile ("TRENCH")
                   .getChildFile ("onboarding.txt");
    }
    void timerCallback() override
    {
        if (! dismissing)
        {
            animPhase = std::fmod (animPhase + 1.0f / 90.0f, 1.0f);   // 1.5 s loop
            if (demoActive)
            {
                // Demo sweep: ~2.4 s out to the far pose and back, then hand over.
                demoPhase += 1.0f / 144.0f;
                if (demoPhase >= 1.0f) endDemo();
                else if (onDemoMorph) onDemoMorph (demoPhase);
            }
            repaint();
            return;
        }
        alpha -= 0.10f;
        if (alpha <= 0.0f)
        {
            alpha = 0.0f;
            setVisible (false);
            if (onDismiss) onDismiss();
        }
        repaint();
    }

    Theme t;
    int step = 0;
    float alpha = 1.0f;
    bool dismissing = false;
    bool demoActive = false;
    float demoPhase = 0.0f;
    float animPhase = 0.0f;
    bool hoverNext = false, hoverSkip = false;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (Onboarding)
};
}
