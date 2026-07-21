#pragma once

#include "SelectorLookAndFeel.h"
#include "Theme.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <cmath>
#include <functional>
#include <memory>

namespace trench::ui
{

// Four-state key listener hung from the display bezel: quiet, listening,
// suggesting, and locked. Nothing is applied until a candidate tab is chosen;
// the APVTS parameter remains the only source of truth.
class KeySnapBox final : public juce::Component,
                         public juce::SettableTooltipClient
{
public:
    KeySnapBox (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme), param (apvts.getParameter (ParamID::keySnap))
    {
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Key Snap");
        setHelpText ("Listens for the musical key and offers two likely choices.");
        setTooltip ("Detected key choices - click to use one; Off leaves the sound unchanged");
        if (param != nullptr)
            attachment = std::make_unique<juce::ParameterAttachment> (
                *param, [this] (float) { repaint(); });
    }

    void setSuggestionProviders (std::function<int()> primary, std::function<int()> secondary)
    {
        primarySuggestion = std::move (primary);
        secondarySuggestion = std::move (secondary);
    }

    void setListeningProvider (std::function<bool()> provider)
    {
        listeningProvider = std::move (provider);
    }

    void refreshSuggestion()
    {
        const int first = suggestion (primarySuggestion);
        const int second = suggestion (secondarySuggestion);
        const bool listeningNow = isListening();
        if (first != lastSuggestion || second != lastAltSuggestion)
        {
            lastSuggestion = first;
            lastAltSuggestion = second;
            if (currentChoice() == 0 && first >= 0)
            {
                arrivalStartedMs = juce::Time::getMillisecondCounterHiRes();
                arriving = true;
            }
            repaint();
        }
        else if (arriving || listeningNow)
        {
            if (juce::Time::getMillisecondCounterHiRes() - arrivalStartedMs >= kArrivalDurationMs)
                arriving = false;
            repaint();
        }
        else if (listeningNow != lastListening)
        {
            repaint();
        }
        lastListening = listeningNow;
    }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override
    {
        hover = false;
        hoveredCandidate = -1;
        repaint();
    }

    void mouseMove (const juce::MouseEvent& e) override
    {
        const int candidate = candidateAt (e.position);
        if (candidate != hoveredCandidate)
        {
            hoveredCandidate = candidate;
            repaint();
        }
    }

    void mouseDown (const juce::MouseEvent&) override
    {
        down = true;
        repaint();
    }

    void mouseUp (const juce::MouseEvent& e) override
    {
        down = false;
        repaint();
        if (param == nullptr || ! getLocalBounds().contains (e.position.toInt()))
            return;

        const int current = currentChoice();
        if (current == 0)
        {
            const int candidate = candidateAt (e.position);
            if (candidate == 0)
                applySuggestedChoice (suggestion (primarySuggestion));
            else if (candidate == 1)
                applySuggestedChoice (suggestion (secondarySuggestion));
            return;
        }

        juce::PopupMenu menu;
        juce::PopupMenu minor;
        juce::PopupMenu major;
        menu.addItem (kOffItem, "OFF", true, current == 0);
        for (int i = 1; i <= 12; ++i)
            minor.addItem (kMinorBase + i, choiceText (i), true, current == i);
        for (int i = 13; i <= 24; ++i)
            major.addItem (kMajorBase + i, choiceText (i), true, current == i);

        menu.addSeparator();
        menu.addSubMenu ("MINOR", minor, true, nullptr, current >= 1 && current <= 12);
        menu.addSubMenu ("MAJOR", major, true, nullptr, current >= 13 && current <= 24);
        menu.setLookAndFeel (&lookAndFeel);

        juce::Component::SafePointer<KeySnapBox> self (this);
        menu.showMenuAsync (juce::PopupMenu::Options().withTargetComponent (this),
                            [self] (int id)
                            {
                                if (self != nullptr)
                                    self->applyChoice (id);
                            });
    }

    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& wheel) override
    {
        if (param == nullptr || wheel.deltaY == 0.0f)
            return;
        const int last = juce::jmax (0, param->getNumSteps() - 1);
        const int current = juce::jlimit (
            0, last, juce::roundToInt (param->convertFrom0to1 (param->getValue())));
        const int direction = wheel.deltaY > 0.0f ? 1 : -1;
        const int next = (current + direction + last + 1) % (last + 1);
        param->beginChangeGesture();
        param->setValueNotifyingHost (param->convertTo0to1 ((float) next));
        param->endChangeGesture();
    }

    void paint (juce::Graphics& g) override
    {
        const int first = suggestion (primarySuggestion);
        const int second = suggestion (secondarySuggestion);
        const bool showingSuggestion = currentChoice() == 0 && first >= 0;
        const auto plateInk = juce::Colour (0xff28332f);

        // The only permanent element: a tiny engraved noun on the bezel. It
        // identifies every later state without adding a panel or instruction.
        g.setFont (displayFont (6.4f, true));
        g.setColour (plateInk.withAlpha (currentChoice() == 0 ? 0.62f : 0.76f));
        g.drawText ("KEY", 23, 0, 29, 10, juce::Justification::centred, false);

        if (showingSuggestion)
        {
            const float elapsed = (float) (juce::Time::getMillisecondCounterHiRes()
                                            - arrivalStartedMs);
            drawCandidate (g, first, 7.0f, 13.0f, arrivalProgress (elapsed, 0.0f),
                           0.94f, hoveredCandidate == 0);
            drawCandidate (g, second, 41.0f, 11.0f, arrivalProgress (elapsed, 85.0f),
                           0.72f, hoveredCandidate == 1);
        }
        else if (currentChoice() == 0)
        {
            if (isListening())
                drawListeningHairline (g);
        }
        else
        {
            drawSelected (g, shortChoiceText (currentChoice()));
        }
    }

private:
    static constexpr int kOffItem = 1;
    static constexpr int kMinorBase = 100;
    static constexpr int kMajorBase = 200;
    static constexpr double kArrivalDurationMs = 420.0;

    static float arrivalProgress (float elapsedMs, float delayMs)
    {
        const float linear = juce::jlimit (0.0f, 1.0f, (elapsedMs - delayMs) / 250.0f);
        const float remaining = 1.0f - linear;
        return 1.0f - remaining * remaining * remaining;
    }

    void drawCandidate (juce::Graphics& g, int label, float x, float targetY,
                        float progress, float strength, bool highlighted) const
    {
        const float y = targetY - (1.0f - progress) * 9.0f + (down ? 0.5f : 0.0f);
        const auto tile = juce::Rectangle<float> (x, y, 27.0f, 19.0f);
        const float alpha = 0.30f + progress * 0.70f;
        g.setColour (juce::Colours::black.withAlpha (alpha * 0.13f * strength));
        g.fillRoundedRectangle (tile.translated (0.0f, 1.0f), 2.0f);
        g.setColour (juce::Colour (0xffaebbb4).withAlpha (alpha * 0.19f * strength));
        g.fillRoundedRectangle (tile, 2.0f);
        if (highlighted)
        {
            g.setColour (juce::Colour (0xffd5dfd8).withAlpha (alpha * 0.10f));
            g.fillRoundedRectangle (tile, 3.0f);
        }
        g.setColour (juce::Colour (0xffc7d3cd).withAlpha (
            alpha * strength * (highlighted ? 0.94f : 0.68f)));
        g.drawRoundedRectangle (tile.reduced (0.5f), 1.8f, highlighted ? 0.9f : 0.65f);
        g.setFont (displayFont (9.1f, true));
        g.setColour (juce::Colour (0xffe3ebe6).withAlpha (alpha * strength));
        g.drawText (shortSuggestionText (label), tile.toNearestInt(),
                    juce::Justification::centred, false);
    }

    void drawListeningHairline (juce::Graphics& g) const
    {
        const double seconds = juce::Time::getMillisecondCounterHiRes() * 0.001;
        const float phase = (float) std::fmod (seconds, 1.25) / 1.25f;
        const float x = 25.0f + phase * 20.0f;
        juce::ColourGradient scan (juce::Colours::transparentBlack, x - 6.0f, 10.0f,
                                   juce::Colour (0xff46564f).withAlpha (0.58f), x, 10.0f, false);
        scan.addColour (0.78, juce::Colour (0xff46564f).withAlpha (0.25f));
        scan.addColour (1.0, juce::Colours::transparentBlack);
        g.setGradientFill (scan);
        g.fillRect (juce::Rectangle<float> (x - 6.0f, 9.2f, 12.0f, 0.8f));
    }

    int candidateAt (juce::Point<float> point) const
    {
        if (currentChoice() != 0 || suggestion (primarySuggestion) < 0)
            return -1;
        if (juce::Rectangle<float> (7.0f, 10.0f, 27.0f, 24.0f).contains (point))
            return 0;
        if (juce::Rectangle<float> (41.0f, 9.0f, 27.0f, 23.0f).contains (point))
            return 1;
        return -1;
    }

    void drawSelected (juce::Graphics& g, const juce::String& text) const
    {
        const auto tile = juce::Rectangle<float> (24.0f, 11.0f, 28.0f, 18.0f);
        g.setColour (juce::Colour (0xffaebbb4).withAlpha (hover ? 0.24f : 0.15f));
        g.fillRoundedRectangle (tile, 2.0f);
        g.setColour (juce::Colour (0xffc7d3cd).withAlpha (hover ? 0.82f : 0.60f));
        g.drawRoundedRectangle (tile.reduced (0.5f), 1.8f, 0.7f);
        g.setFont (displayFont (8.9f, true));
        g.setColour (juce::Colour (0xffe3ebe6).withAlpha (0.88f));
        g.drawText (text, tile.toNearestInt(), juce::Justification::centred, false);
    }

    bool isListening() const
    {
        return listeningProvider && listeningProvider();
    }

    static int suggestion (const std::function<int()>& provider)
    {
        return provider ? juce::jlimit (-1, 23, provider()) : -1;
    }

    static juce::String shortSuggestionText (int label)
    {
        if (label < 0 || label >= 24)
            return "--";
        static constexpr const char* notes[] = {
            "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"
        };
        return juce::String (notes[label % 12]) + (label >= 12 ? "m" : "");
    }

    static juce::String shortChoiceText (int choice)
    {
        if (choice >= 1 && choice <= 12)
            return shortSuggestionText (12 + choice - 1);
        if (choice >= 13 && choice <= 24)
            return shortSuggestionText (choice - 13);
        return "--";
    }

    static int snapChoiceForSuggestion (int label)
    {
        if (label < 0 || label >= 24)
            return -1;
        return label < 12 ? 13 + label : 1 + (label - 12);
    }

    int currentChoice() const
    {
        if (param == nullptr)
            return 0;
        const int last = juce::jmax (0, param->getNumSteps() - 1);
        return juce::jlimit (0, last,
                             juce::roundToInt (param->convertFrom0to1 (param->getValue())));
    }

    juce::String choiceText (int choice) const
    {
        return param != nullptr ? param->getText (param->convertTo0to1 ((float) choice), 8)
                                : juce::String();
    }

    void applyChoice (int id)
    {
        int choice = -1;
        if (id == kOffItem)
            choice = 0;
        else if (id >= kMinorBase + 1 && id <= kMinorBase + 12)
            choice = id - kMinorBase;
        else if (id >= kMajorBase + 13 && id <= kMajorBase + 24)
            choice = id - kMajorBase;

        if (choice < 0 || param == nullptr)
            return;
        param->beginChangeGesture();
        param->setValueNotifyingHost (param->convertTo0to1 ((float) choice));
        param->endChangeGesture();
    }

    void applySuggestedChoice (int label)
    {
        const int choice = snapChoiceForSuggestion (label);
        if (choice < 0 || param == nullptr)
            return;
        param->beginChangeGesture();
        param->setValueNotifyingHost (param->convertTo0to1 ((float) choice));
        param->endChangeGesture();
    }

    Theme t;
    SelectorLookAndFeel lookAndFeel;
    juce::RangedAudioParameter* param = nullptr;
    std::unique_ptr<juce::ParameterAttachment> attachment;
    std::function<int()> primarySuggestion;
    std::function<int()> secondarySuggestion;
    std::function<bool()> listeningProvider;
    int lastSuggestion = -2;
    int lastAltSuggestion = -2;
    double arrivalStartedMs = 0.0;
    bool arriving = false;
    bool hover = false;
    bool down = false;
    int hoveredCandidate = -1;
    bool lastListening = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (KeySnapBox)
};

} // namespace trench::ui
