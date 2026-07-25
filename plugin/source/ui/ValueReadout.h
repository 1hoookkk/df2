#pragma once
#include "Theme.h"
#include "ParamInteraction.h"
namespace trench::ui
{
class ValueReadout : public juce::Component,
                     public juce::SettableTooltipClient
{
public:
    ValueReadout (juce::String elementId, const Theme& theme)
        : id (std::move (elementId)), t (theme)
    {
        setInterceptsMouseClicks (true, true);
    }
    void bindParameter (juce::RangedAudioParameter* p)
    {
        param = p;
        setMouseCursor (p != nullptr ? juce::MouseCursor::UpDownResizeCursor
                                     : juce::MouseCursor::NormalCursor);
        if (p != nullptr)
        {
            const auto name = p->getName (24);
            setTitle (name);
            setHelpText (name + " - scroll to adjust; double-click to type an exact value; right-click for parameter options.");
            setTooltip (p->getName (24) + " - scroll to adjust, double-click to type, right-click for menu");
        }
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
    void showAdjustCue (bool show)
    {
        if (adjustCue != show) { adjustCue = show; repaint(); }
    }
    void setDecimals (int d)
    {
        if (decimals != d) { decimals = d; repaint(); }
    }
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
        if (editor != nullptr)
        {
            if (e.eventComponent != editor.get() && ! editor->isParentOf (e.eventComponent))
                commitEditor();
            return;
        }
        if (e.mods.isPopupMenu())
        {
            showParamContextMenu (*this, param);
            return;
        }
        dragStartY = e.position.y;
        dragStartValue = param != nullptr ? param->getValue() : 0.0f;
        dragging = false;
    }
    void mouseDrag (const juce::MouseEvent& e) override
    {
        if (param == nullptr || editor != nullptr || e.mods.isPopupMenu())
            return;
        if (! dragging)
        {
            if (std::abs (e.position.y - dragStartY) < 3.0f)
                return;
            dragging = true;
            param->beginChangeGesture();
        }
        const float scale = e.mods.isShiftDown() ? 0.25f : 1.0f;
        const float travel = 140.0f;
        const float next = juce::jlimit (0.0f, 1.0f,
                                         dragStartValue - (e.position.y - dragStartY) / travel * scale);
        param->setValueNotifyingHost (next);
    }
    void mouseUp (const juce::MouseEvent&) override
    {
        if (dragging && param != nullptr)
            param->endChangeGesture();
        dragging = false;
    }
    void mouseDoubleClick (const juce::MouseEvent&) override
    {
        if (param == nullptr || textOverride.isNotEmpty() || editor != nullptr) return;
        editor = std::make_unique<juce::TextEditor>();
        editor->setBounds (getLocalBounds().reduced (5, 2));
        editor->setJustification (juce::Justification::centred);
        editor->setFont (displayFont (t.fontSize (id, 20.0f), true));
        editor->setColour (juce::TextEditor::backgroundColourId, juce::Colour (0xffdcd6ca));
        editor->setColour (juce::TextEditor::textColourId, t.labelInk());
        editor->setColour (juce::TextEditor::highlightColourId, t.labelInk().withAlpha (0.25f));
        editor->setWantsKeyboardFocus (true);
        {
            const float pct = juce::jlimit (0.0f, 1.0f, value) * 100.0f;
            editor->setText (decimals <= 0 ? juce::String (juce::roundToInt (pct))
                                           : juce::String (pct, decimals), false);
        }
        editor->onReturnKey  = [this] { commitEditor(); };
        editor->onEscapeKey  = [this] { closeEditor(); };
        editor->onFocusLost  = [this] { commitEditor(); };
        addAndMakeVisible (*editor);
        editor->selectAll();
        editor->grabKeyboardFocus();
        if (auto* top = getTopLevelComponent())
            top->addMouseListener (this, true);
    }
    ~ValueReadout() override { detachOutsideClickListener(); }
    void paint (juce::Graphics& g) override
    {
        const auto b = getLocalBounds().toFloat();
        drawMutedBoneReadout (g, b, b.getHeight() * 0.17f, isActive, t);
        const auto pct = juce::jlimit (0.0f, 1.0f, value) * 100.0f;
        const auto numeric = textOverride.isNotEmpty()
                               ? textOverride
                               : (decimals <= 0 ? juce::String (juce::roundToInt (pct))
                                                : juce::String (pct, decimals));
        const float fs = t.fontSize (id, 20.0f);
        auto textArea = b.reduced (4.0f, 1.0f);
        if (adjustCue)
            textArea = textArea.withTrimmedRight (7.0f);
        drawCrispText (g, textArea, numeric, fs,
                       t.textColour (id, juce::Colour (0xff2a2722)), true);
        if (adjustCue && param != nullptr)
        {
            const float cxr = b.getRight() - 7.5f;
            const float cy = b.getCentreY();
            g.setColour (t.textColour (id, juce::Colour (0xff2a2722)).withAlpha (0.55f));
            juce::Path up, dn;
            up.addTriangle (cxr - 2.6f, cy - 2.2f, cxr + 2.6f, cy - 2.2f, cxr, cy - 5.6f);
            dn.addTriangle (cxr - 2.6f, cy + 2.2f, cxr + 2.6f, cy + 2.2f, cxr, cy + 5.6f);
            g.fillPath (up);
            g.fillPath (dn);
        }
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
    float dragStartY = 0.0f;
    float dragStartValue = 0.0f;
    bool dragging = false;
    bool adjustCue = false;
    int decimals = 1;
};
}
