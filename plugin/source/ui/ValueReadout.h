#pragma once

#include "Theme.h"
#include "ParamInteraction.h"

namespace trench::ui
{

// Numeric readout: a clean recessed inset — the machine's display face. When
// bound to a parameter it is also a real control: scroll to nudge, right-click
// for Reset + the host's MIDI-learn/automation menu, and double-click to TYPE
// an exact value. Display-only (unbound) when it shows literal text (e.g. TIME).
class ValueReadout : public juce::Component,
                     public juce::SettableTooltipClient
{
public:
    ValueReadout (juce::String elementId, const Theme& theme)
        : id (std::move (elementId)), t (theme)
    {
        setInterceptsMouseClicks (true, true);
    }

    // Bind so the readout can also drive the parameter (scroll / type / menu).
    void bindParameter (juce::RangedAudioParameter* p)
    {
        param = p;
        setMouseCursor (p != nullptr ? juce::MouseCursor::UpDownResizeCursor
                                     : juce::MouseCursor::NormalCursor);
        if (p != nullptr)
            setTooltip (p->getName (24) + " - scroll to adjust, double-click to type, right-click for menu");
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
        if (isActive != active) { isActive = active; repaint(); }
    }

    // Show literal text instead of the % numeric (e.g. the TIME value "1 BAR").
    void setText (const juce::String& s)
    {
        if (s != textOverride) { textOverride = s; repaint(); }
    }

    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w) override
    {
        if (param == nullptr) return;
        const float next = juce::jlimit (0.0f, 1.0f, param->getValue() + w.deltaY * 0.05f);
        param->beginChangeGesture();
        param->setValueNotifyingHost (next);
        param->endChangeGesture();
    }

    void mouseDown (const juce::MouseEvent& e) override
    {
        // While the type-in editor is open we listen to the WHOLE window:
        // any click outside the editor commits and closes it.
        if (editor != nullptr)
        {
            if (e.eventComponent != editor.get() && ! editor->isParentOf (e.eventComponent))
                commitEditor();
            return;
        }
        if (e.mods.isPopupMenu())
            showParamContextMenu (*this, param);
    }

    void mouseDoubleClick (const juce::MouseEvent&) override
    {
        if (param == nullptr || textOverride.isNotEmpty() || editor != nullptr) return;
        editor = std::make_unique<juce::TextEditor>();
        editor->setBounds (getLocalBounds().reduced (5, 2));
        editor->setJustification (juce::Justification::centred);
        editor->setFont (displayFont (t.fontSize (id, 20.0f), false));
        editor->setColour (juce::TextEditor::backgroundColourId, juce::Colour (0xfff0e4cc));
        editor->setColour (juce::TextEditor::textColourId, t.labelInk());
        editor->setColour (juce::TextEditor::highlightColourId, t.labelInk().withAlpha (0.25f));
        editor->setWantsKeyboardFocus (true);   // this one DOES need keys, briefly
        editor->setText (juce::String (juce::jlimit (0.0f, 1.0f, value) * 100.0f, 1), false);
        editor->onReturnKey  = [this] { commitEditor(); };
        editor->onEscapeKey  = [this] { closeEditor(); };
        editor->onFocusLost  = [this] { commitEditor(); };
        addAndMakeVisible (*editor);
        editor->selectAll();
        editor->grabKeyboardFocus();
        // Nothing else on the plate takes keyboard focus, so focus-lost never
        // fires on its own — ANY click outside the editor must commit, or the
        // edit is a trap ("once you click the text you cant get out").
        if (auto* top = getTopLevelComponent())
            top->addMouseListener (this, true);
    }

    ~ValueReadout() override { detachOutsideClickListener(); }

    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds().toFloat();

        // Smoked bone display window painted into the machined plate's well.
        // Edge-to-edge: the component rect IS the black opening; any inset here
        // shows as a dark ring around the face ("you see too much of the inner
        // well", Tyson 2026-07-11).
        drawIvoryWell (g, b, b.getHeight() * 0.17f, isActive, t);
        const auto pct = juce::jlimit (0.0f, 1.0f, value) * 100.0f;
        const auto numeric = textOverride.isNotEmpty() ? textOverride : juce::String (pct, 1);

        const float fs = t.fontSize (id, 20.0f);
        g.setFont (displayFont (fs, false));
        g.setColour (t.textColour (id, juce::Colour (0xff0b0b0b)));
        g.drawFittedText (numeric, b.reduced (4.0f, 1.0f).toNearestInt(),
                          juce::Justification::centred, 1, 0.92f);
    }

private:
    void commitEditor()
    {
        if (editor == nullptr) return;
        const float pct  = editor->getText().getFloatValue();
        if (param != nullptr)
        {
            param->beginChangeGesture();
            param->setValueNotifyingHost (juce::jlimit (0.0f, 1.0f, pct / 100.0f));
            param->endChangeGesture();
        }
        closeEditor();
    }

    void closeEditor()
    {
        // The close is triggered from INSIDE the editor's own callbacks
        // (escape/return/focus-lost) — deleting it there is a crash. Release
        // and delete on the next message-loop tick instead.
        detachOutsideClickListener();
        if (auto* ed = editor.release())
        {
            removeChildComponent (ed);
            juce::MessageManager::callAsync ([ed] { delete ed; });
        }
        repaint();
    }

    void detachOutsideClickListener()
    {
        if (auto* top = getTopLevelComponent())
            top->removeMouseListener (this);
    }

    juce::String id;
    Theme t;
    float value = 0.0f;
    juce::String textOverride;
    bool isActive = false;
    juce::RangedAudioParameter* param = nullptr;
    std::unique_ptr<juce::TextEditor> editor;
};

} // namespace trench::ui
