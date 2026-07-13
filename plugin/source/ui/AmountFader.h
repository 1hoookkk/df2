#pragma once

#include "Theme.h"
#include "ParamInteraction.h"

namespace trench::ui
{

// AMOUNT — the single macro dose, as a QUIET horizontal fader. Deliberately subtle:
// a thin slot recessed into the navy plate, a low-chroma slate fill (NOT a bright
// wine/accent bar), a small gunmetal thumb — tonal with the faceplate so it recedes
// and defers to the wheels instead of pasting on. Engraved AMOUNT legend, small
// value at the right. A real control: drag or scroll to set, double-click to type,
// right-click for the host's MIDI-learn/automation menu. Bound to `amount` (scales
// the whole recipe incl. modulation depth).
class AmountFader : public juce::Component,
                    public juce::SettableTooltipClient
{
public:
    AmountFader (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme)
    {
        param = apvts.getParameter ("amount");
        setMouseCursor (juce::MouseCursor::LeftRightResizeCursor);
        setTooltip ("Amount - scales the whole recipe, including modulation intensity."
                    " Drag / scroll to set, double-click to type.");
        setWantsKeyboardFocus (false);      // don't steal keys from the host
        setInterceptsMouseClicks (true, true);
        if (param != nullptr)               // repaint when the host automates it
            listen = std::make_unique<juce::ParameterAttachment> (
                *param, [this] (float) { repaint(); }, nullptr);
    }

    void resized() override
    {
        auto b = getLocalBounds();
        labelArea = b.removeFromLeft  (juce::jlimit (34, 58, b.getWidth() / 4));
        valueArea = b.removeFromRight (juce::jlimit (22, 32, b.getWidth() / 5));
        track     = b.reduced (2, 0);
    }

    void paint (juce::Graphics& g) override
    {
        // ── engraved AMOUNT legend (espresso plate ink), left ──
        drawEngravedTrackedText (g, "AMOUNT", labelArea.toFloat(),
                                 displayFont (juce::jlimit (7.0f, 8.5f, labelArea.getHeight() * 0.5f), false),
                                 panelInk.withAlpha (0.82f), 0.6f, 0.35f);

        // ── thin recessed slot, carved into the sand plate ──
        const auto sl = track.toFloat().withSizeKeepingCentre ((float) track.getWidth(),
                                                               juce::jmin (6.0f, track.getHeight() * 0.42f));
        const float rad = sl.getHeight() * 0.5f;
        juce::ColourGradient floor (juce::Colour (0xff241f18), 0.0f, sl.getY(),
                                    juce::Colour (0xff383126), 0.0f, sl.getBottom(), false);
        g.setGradientFill (floor);
        g.fillRoundedRectangle (sl, rad);

        const float v      = param != nullptr ? juce::jlimit (0.0f, 1.0f, param->getValue()) : 0.0f;
        const float capW   = 6.0f;
        const float travel = juce::jmax (1.0f, sl.getWidth() - capW);
        const float capX   = sl.getX() + capW * 0.5f + v * travel;

        // ── low-chroma warm-taupe fill (quiet, not an accent bar) ──
        {
            juce::Rectangle<float> fill (sl.getX() + 1.0f, sl.getY() + 1.0f,
                                         capX - sl.getX() - 1.0f, sl.getHeight() - 2.0f);
            if (fill.getWidth() > 0.5f)
            {
                g.setColour (juce::Colour (0xff6b5f48));
                g.fillRoundedRectangle (fill, rad * 0.8f);
            }
        }

        // faint recess: top inner shadow + a light catch below the cut (carved)
        g.setColour (juce::Colours::black.withAlpha (0.34f));
        g.fillRect (sl.getX(), sl.getY(), sl.getWidth(), 1.0f);
        g.setColour (juce::Colour (0xff1a150e).withAlpha (0.9f));
        g.drawRoundedRectangle (sl, rad, 0.8f);
        g.setColour (juce::Colours::white.withAlpha (0.30f));
        g.drawLine (sl.getX() + 2.0f, sl.getBottom() + 1.0f, sl.getRight() - 2.0f, sl.getBottom() + 1.0f, 0.8f);

        // ── small quiet dark-brass thumb ──
        {
            juce::Rectangle<float> cap (capX - capW * 0.5f, sl.getY() - 2.0f, capW, sl.getHeight() + 4.0f);
            const bool hot = isMouseOverOrDragging();
            juce::ColourGradient mg (juce::Colour (hot ? 0xff8a7a58 : 0xff6f6248), 0.0f, cap.getY(),
                                     juce::Colour (0xff2b2418), 0.0f, cap.getBottom(), false);
            g.setGradientFill (mg);
            g.fillRoundedRectangle (cap, 1.6f);
            g.setColour (juce::Colours::white.withAlpha (0.18f));
            g.drawLine (cap.getX() + 0.8f, cap.getY() + 1.2f, cap.getRight() - 0.8f, cap.getY() + 1.2f, 0.7f);
            g.setColour (juce::Colour (0xff17120b).withAlpha (0.85f));
            g.drawRoundedRectangle (cap, 1.6f, 0.7f);
        }

        // ── small value, right (quiet plate ink, no LCD) ──
        g.setFont (displayFont (juce::jlimit (8.0f, 10.0f, valueArea.getHeight() * 0.55f), false));
        g.setColour (panelInk.withAlpha (0.72f));
        g.drawText (juce::String (v * 100.0f, 0), valueArea.reduced (2, 0),
                    juce::Justification::centredLeft);
    }

    void mouseDown (const juce::MouseEvent& e) override
    {
        if (param == nullptr) return;
        if (e.mods.isPopupMenu()) { showParamContextMenu (*this, param); return; }
        dragStart = param->getValue();
        dragging  = true;
        param->beginChangeGesture();
        repaint();
    }

    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (param == nullptr || ! dragging) return;
        const float w = juce::jmax (1.0f, (float) track.getWidth() - 6.0f);
        const float delta = (float) e.getDistanceFromDragStartX() / w * fineDragScale (e);
        param->setValueNotifyingHost (juce::jlimit (0.0f, 1.0f, dragStart + delta));
    }

    void mouseUp (const juce::MouseEvent&) override
    {
        if (param != nullptr && dragging) param->endChangeGesture();
        dragging = false;
        repaint();
    }

    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w) override
    {
        if (param == nullptr) return;
        param->beginChangeGesture();
        param->setValueNotifyingHost (juce::jlimit (0.0f, 1.0f, param->getValue() + w.deltaY * 0.05f));
        param->endChangeGesture();
        repaint();
    }

    void mouseDoubleClick (const juce::MouseEvent&) override
    {
        if (param == nullptr || editor != nullptr) return;
        editor = std::make_unique<juce::TextEditor>();
        editor->setBounds (valueArea.expanded (6, 1));
        editor->setJustification (juce::Justification::centred);
        editor->setFont (displayFont (juce::jlimit (8.0f, 11.0f, valueArea.getHeight() * 0.6f), false));
        editor->setColour (juce::TextEditor::backgroundColourId, juce::Colour (0xff11151f));
        editor->setColour (juce::TextEditor::textColourId, panelInk);
        editor->setColour (juce::TextEditor::highlightColourId, panelInk.withAlpha (0.2f));
        editor->setWantsKeyboardFocus (true);   // this one DOES need keys, briefly
        editor->setText (juce::String (juce::jlimit (0.0f, 1.0f, param->getValue()) * 100.0f, 0), false);
        editor->onReturnKey  = [this] { commitEditor(); };
        editor->onEscapeKey  = [this] { editor.reset(); };
        editor->onFocusLost  = [this] { commitEditor(); };
        addAndMakeVisible (*editor);
        editor->selectAll();
        editor->grabKeyboardFocus();
    }

private:
    void commitEditor()
    {
        if (editor == nullptr) return;
        if (param != nullptr)
        {
            param->beginChangeGesture();
            param->setValueNotifyingHost (juce::jlimit (0.0f, 1.0f, editor->getText().getFloatValue() / 100.0f));
            param->endChangeGesture();
        }
        editor.reset();
        repaint();
    }

    Theme t;
    juce::RangedAudioParameter* param = nullptr;
    juce::Rectangle<int> labelArea, valueArea, track;
    std::unique_ptr<juce::ParameterAttachment> listen;   // repaint on host automation
    std::unique_ptr<juce::TextEditor> editor;
    bool dragging = false;
    float dragStart = 0.0f;
    const juce::Colour panelInk { 0xff35291d };   // espresso ink on the sand plate

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AmountFader)
};

} // namespace trench::ui
