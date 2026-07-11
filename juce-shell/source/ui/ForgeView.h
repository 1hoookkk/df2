#pragma once

#include "ForgeTables.h"

#include <juce_gui_basics/juce_gui_basics.h>
#include <array>
#include <cmath>
#include <functional>
#include <vector>

namespace trench::ui
{
// In-plugin FORGE (diagnostics-only): build a 6-biquad body from the evidence tables,
// compile via the typed compiler, audition it live, save it as .body240. Each lane is
// one biquad (one stage). Frequencies are chosen from the table-derived menu only
// (provenance law: no invented frequencies). Talks back via std::function callbacks.
class ForgeView : public juce::Component
{
public:
    static constexpr int kLanes = 6;

    std::function<void (std::vector<double>)> onAudition; // 42 typed-card values
    std::function<void (juce::String)>        onSave;
    std::function<void ()>                    onClose;

    ForgeView()
    {
        setOpaque (true);   // docked side drawer fully covers its strip
        addAndMakeVisible (title);
        title.setText ("FORGE - build a filter from the tables", juce::dontSendNotification);
        title.setColour (juce::Label::textColourId, juce::Colour (0xff60c8e0));
        title.setFont (juce::Font (juce::FontOptions (13.0f, juce::Font::bold)));

        addAndMakeVisible (hint);
        hint.setText ("each row = one biquad (stage)   |   LOW to HIGH = the morph   |   freqs are table-gated",
                      juce::dontSendNotification);
        hint.setColour (juce::Label::textColourId, juce::Colour (0xff7a8699));
        hint.setFont (juce::Font (juce::FontOptions (10.5f)));

        static const char* typeNames[] = { "Peak", "LoShelf", "Notch", "LowPass", "HiPass", "BandPass", "HiShelf" };
        const int n = (int) kTableFreqs.size();
        for (int L = 0; L < kLanes; ++L)
        {
            auto& ln = lanes[(size_t) L];
            addAndMakeVisible (ln.num);
            ln.num.setText (juce::String (L + 1), juce::dontSendNotification);
            ln.num.setColour (juce::Label::textColourId, juce::Colour (0xff9aa6b6));
            ln.num.setFont (juce::Font (juce::FontOptions (11.0f, juce::Font::bold)));

            addAndMakeVisible (ln.type);
            for (int i = 0; i < 7; ++i) ln.type.addItem (typeNames[i], i + 1);
            ln.type.setSelectedId (1, juce::dontSendNotification); // Peak

            addAndMakeVisible (ln.low);  fillFreq (ln.low);
            addAndMakeVisible (ln.high); fillFreq (ln.high);
            const int li = juce::jlimit (0, n - 1, (int) ((L + 0.5) / kLanes * n));
            const int hi = juce::jlimit (0, n - 1, li + juce::jmax (1, n / 12));
            ln.low.setSelectedId  (li + 1, juce::dontSendNotification);
            ln.high.setSelectedId (hi + 1, juce::dontSendNotification);

            addAndMakeVisible (ln.q);
            ln.q.setSliderStyle (juce::Slider::LinearHorizontal);
            ln.q.setTextBoxStyle (juce::Slider::TextBoxRight, false, 30, 15);
            ln.q.setRange (0.3, 12.0, 0.01); ln.q.setValue (1.5, juce::dontSendNotification);

            addAndMakeVisible (ln.gain);
            ln.gain.setSliderStyle (juce::Slider::LinearHorizontal);
            ln.gain.setTextBoxStyle (juce::Slider::TextBoxRight, false, 30, 15);
            ln.gain.setRange (-18.0, 18.0, 0.1); ln.gain.setValue (6.0, juce::dontSendNotification);
        }

        addAndMakeVisible (nameBox);
        nameBox.setText ("forge_body", juce::dontSendNotification);

        addAndMakeVisible (auditionBtn);
        auditionBtn.setButtonText ("AUDITION");
        auditionBtn.onClick = [this] { if (onAudition) onAudition (buildCards()); };

        addAndMakeVisible (saveBtn);
        saveBtn.setButtonText ("SAVE .body240");
        saveBtn.onClick = [this] { if (onSave) onSave (nameBox.getText()); };

        addAndMakeVisible (closeBtn);
        closeBtn.setButtonText ("X");
        closeBtn.onClick = [this] { if (onClose) onClose(); };
    }

    // The 42 typed-card values: 6 x [type_id, fc_low, fc_high, q_lo, q_hi, gain_db, on].
    std::vector<double> buildCards() const
    {
        std::vector<double> c;
        c.reserve (42);
        for (int L = 0; L < kLanes; ++L)
        {
            const auto& ln = lanes[(size_t) L];
            const double type = (double) (ln.type.getSelectedId() - 1);
            const double q = ln.q.getValue();
            c.push_back (type);
            c.push_back (freqOf (ln.low));
            c.push_back (freqOf (ln.high));
            c.push_back (q);
            c.push_back (q);
            c.push_back (ln.gain.getValue());
            c.push_back (1.0);
        }
        return c;
    }

    void paint (juce::Graphics& g) override
    {
        g.fillAll (juce::Colour (0xff0a0d12));            // opaque: docked drawer, not an overlay
        g.setColour (juce::Colour (0xff60c8e0).withAlpha (0.5f));
        g.fillRect (0, 0, 1, getHeight());               // accent seam against the main UI
        g.setColour (juce::Colour (0xff243140));
        g.drawRect (getLocalBounds(), 1);
    }

    void resized() override
    {
        auto r = getLocalBounds().reduced (8);
        auto top = r.removeFromTop (20);
        closeBtn.setBounds (top.removeFromRight (22));
        title.setBounds (top);
        hint.setBounds (r.removeFromTop (15));
        r.removeFromTop (4);

        for (int L = 0; L < kLanes; ++L)
        {
            auto row = r.removeFromTop (32);
            row.removeFromBottom (5);
            auto& ln = lanes[(size_t) L];
            ln.num.setBounds  (row.removeFromLeft (14));
            ln.type.setBounds (row.removeFromLeft (62)); row.removeFromLeft (3);
            ln.low.setBounds  (row.removeFromLeft (60)); row.removeFromLeft (2);
            ln.high.setBounds (row.removeFromLeft (60)); row.removeFromLeft (3);
            const int w = row.getWidth();
            ln.q.setBounds (row.removeFromLeft (w / 2));
            ln.gain.setBounds (row);
        }

        r.removeFromTop (6);
        auto br = r.removeFromTop (26);
        nameBox.setBounds    (br.removeFromLeft (100)); br.removeFromLeft (6);
        auditionBtn.setBounds (br.removeFromLeft (84)); br.removeFromLeft (6);
        saveBtn.setBounds    (br.removeFromLeft (110));
    }

private:
    struct Lane
    {
        juce::Label num;
        juce::ComboBox type, low, high;
        juce::Slider q, gain;
    };

    juce::Label title, hint;
    std::array<Lane, kLanes> lanes;
    juce::TextEditor nameBox;
    juce::TextButton auditionBtn, saveBtn, closeBtn;

    static void fillFreq (juce::ComboBox& cb)
    {
        for (int i = 0; i < (int) kTableFreqs.size(); ++i)
            cb.addItem (juce::String ((int) std::lround ((double) kTableFreqs[(size_t) i])) + " Hz", i + 1);
    }
    static double freqOf (const juce::ComboBox& cb)
    {
        const int id = cb.getSelectedId();
        if (id < 1 || id > (int) kTableFreqs.size()) return 1000.0;
        return (double) kTableFreqs[(size_t) (id - 1)];
    }

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ForgeView)
};

} // namespace trench::ui
