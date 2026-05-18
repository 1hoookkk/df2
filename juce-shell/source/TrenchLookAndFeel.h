#pragma once

#include "TrenchStyle.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace trench
{

class TrenchLookAndFeel : public juce::LookAndFeel_V4
{
public:
    TrenchLookAndFeel()
    {
        using namespace style;
        setColour (juce::ResizableWindow::backgroundColourId, bgVoid());
        setColour (juce::Label::textColourId, bone());
        setColour (juce::Label::backgroundColourId, juce::Colours::transparentBlack);
        setColour (juce::TextButton::buttonColourId, bgPanel());
        setColour (juce::TextButton::buttonOnColourId, accent().withAlpha (0.18f));
        setColour (juce::TextButton::textColourOnId, accent());
        setColour (juce::TextButton::textColourOffId, bone());
        setColour (juce::ComboBox::backgroundColourId, bgPanel());
        setColour (juce::ComboBox::outlineColourId, boneVeryDim());
        setColour (juce::ComboBox::textColourId, bone());
        setColour (juce::ComboBox::arrowColourId, boneDim());
        setColour (juce::ComboBox::buttonColourId, bgPanel());
        setColour (juce::PopupMenu::backgroundColourId, bgPanel());
        setColour (juce::PopupMenu::textColourId, bone());
        setColour (juce::PopupMenu::highlightedBackgroundColourId, accent().withAlpha (0.22f));
        setColour (juce::PopupMenu::highlightedTextColourId, accent());
    }

    juce::Font getLabelFont (juce::Label& l) override
    {
        return style::label (juce::jmax (9.0f, static_cast<float> (l.getHeight()) * 0.58f), false);
    }

    juce::Font getComboBoxFont (juce::ComboBox& box) override
    {
        return style::label (juce::jmax (10.0f, static_cast<float> (box.getHeight()) * 0.55f), true);
    }

    juce::Font getPopupMenuFont() override
    {
        return style::label (12.0f, false);
    }

    juce::Font getTextButtonFont (juce::TextButton&, int buttonHeight) override
    {
        return style::label (juce::jmax (10.0f, static_cast<float> (buttonHeight) * 0.42f), true);
    }

    void drawButtonBackground (juce::Graphics& g, juce::Button& b,
                               const juce::Colour& /*backgroundColour*/,
                               bool over, bool down) override
    {
        const auto bounds = b.getLocalBounds().toFloat().reduced (0.5f);
        const float radius = juce::jmin (bounds.getHeight() * 0.5f, 6.0f);
        g.setColour (down ? style::accent().withAlpha (0.18f)
                          : (over ? style::bgPanel().brighter (0.10f) : style::bgPanel()));
        g.fillRoundedRectangle (bounds, radius);
        g.setColour (down ? style::accent()
                          : (over ? style::accent().withAlpha (0.55f) : style::boneVeryDim()));
        g.drawRoundedRectangle (bounds, radius, 1.0f);
    }

    void drawButtonText (juce::Graphics& g, juce::TextButton& b,
                         bool over, bool down) override
    {
        g.setFont (getTextButtonFont (b, b.getHeight()));
        g.setColour (down ? style::accent()
                          : (over ? style::bone() : b.findColour (juce::TextButton::textColourOffId)));
        g.drawText (b.getButtonText(), b.getLocalBounds(), juce::Justification::centred, false);
    }

    void drawComboBox (juce::Graphics& g, int width, int height,
                       bool /*isButtonDown*/, int /*buttonX*/, int /*buttonY*/,
                       int /*buttonW*/, int /*buttonH*/, juce::ComboBox& box) override
    {
        const auto bounds = juce::Rectangle<float> (0, 0, (float) width, (float) height).reduced (0.5f);
        g.setColour (box.findColour (juce::ComboBox::backgroundColourId));
        g.fillRect (bounds);
        g.setColour (box.isMouseOver (true) ? style::accent().withAlpha (0.55f)
                                            : box.findColour (juce::ComboBox::outlineColourId));
        g.drawRect (bounds, 1.0f);

        const float caretX = bounds.getRight() - height * 0.55f;
        const float caretY = bounds.getCentreY();
        const float s = height * 0.18f;
        juce::Path caret;
        caret.addTriangle (caretX - s, caretY - s * 0.5f,
                           caretX + s, caretY - s * 0.5f,
                           caretX,     caretY + s * 0.6f);
        g.setColour (box.findColour (juce::ComboBox::arrowColourId));
        g.fillPath (caret);
    }

    void drawPopupMenuBackground (juce::Graphics& g, int width, int height) override
    {
        g.fillAll (style::bgPanel());
        g.setColour (style::boneVeryDim());
        g.drawRect (0, 0, width, height, 1);
    }

    void drawPopupMenuItem (juce::Graphics& g, const juce::Rectangle<int>& area,
                            bool isSeparator, bool isActive, bool isHighlighted,
                            bool isTicked, bool /*hasSubMenu*/, const juce::String& text,
                            const juce::String& /*shortcut*/, const juce::Drawable* /*icon*/,
                            const juce::Colour* /*textColourToUse*/) override
    {
        if (isSeparator)
        {
            g.setColour (style::boneVeryDim());
            g.drawHorizontalLine (area.getCentreY(), (float) area.getX() + 4, (float) area.getRight() - 4);
            return;
        }
        if (isHighlighted && isActive)
        {
            g.setColour (style::accent().withAlpha (0.20f));
            g.fillRect (area);
        }
        g.setColour (! isActive ? style::boneDim().withAlpha (0.5f)
                                : (isHighlighted ? style::accent() : style::bone()));
        g.setFont (getPopupMenuFont());
        const auto textArea = area.reduced (10, 0);
        g.drawText (text, textArea, juce::Justification::centredLeft, true);
        if (isTicked)
        {
            g.setColour (style::accent());
            g.fillRect (area.getX() + 4, area.getCentreY() - 1, 4, 2);
        }
    }

    void drawLabel (juce::Graphics& g, juce::Label& label) override
    {
        g.fillAll (label.findColour (juce::Label::backgroundColourId));
        if (! label.isBeingEdited())
        {
            g.setColour (label.findColour (juce::Label::textColourId));
            g.setFont (getLabelFont (label));
            const auto area = label.getLocalBounds().reduced (label.getBorderSize().getLeft(), 0);
            g.drawFittedText (label.getText(), area, label.getJustificationType(),
                              juce::jmax (1, (int) (label.getHeight() / getLabelFont (label).getHeight())));
        }
    }

private:
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchLookAndFeel)
};

} // namespace trench
