#pragma once
#include "Theme.h"
#include "SelectorLookAndFeel.h"
#include "../PluginProcessor.h"
#include "../TrenchBodyRoster.h"
#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>
#include <vector>
namespace trench::ui
{
class TypeSelectorView : public juce::Component,
                         public juce::SettableTooltipClient,
                         private juce::ComboBox::Listener
{
public:
    TypeSelectorView (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : t (theme), menuLookAndFeel (t)
    {
        setInterceptsMouseClicks (true, true);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Type");
        setHelpText ("Type - choose the filter body.");
        setTooltip ("TYPE: choose the filter body");
        selector.setLookAndFeel (&menuLookAndFeel);
        selector.setInterceptsMouseClicks (false, false);
        selector.setWantsKeyboardFocus (false);
        for (auto colourId : { juce::ComboBox::backgroundColourId, juce::ComboBox::outlineColourId,
                               juce::ComboBox::buttonColourId, juce::ComboBox::arrowColourId,
                               juce::ComboBox::textColourId })
            selector.setColour (colourId, juce::Colours::transparentBlack);
        selector.setTextWhenNothingSelected ({});
        populate();
        attachment = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment> (
            apvts, ParamID::body, selector);
        selector.addListener (this);
        addAndMakeVisible (selector);
    }
    ~TypeSelectorView() override
    {
        selector.setLookAndFeel (nullptr);
        selector.removeListener (this);
    }
    std::function<void()> onSeed;
    std::function<void()> onExportBody;
    void resized() override { selector.setBounds (getLocalBounds().reduced (3, 2)); }
    void mouseEnter (const juce::MouseEvent&) override { repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { repaint(); }
    void mouseDown  (const juce::MouseEvent&) override
    {
        refreshFromDisk();
        showGroupedMenu();
        repaint();
    }
    void refreshFromDisk()
    {
        const int keep = selector.getSelectedId();
        trench::rescanBodyRoster();
        populate();
        if (keep > 0)
            selector.setSelectedId (keep, juce::dontSendNotification);
    }
    class AuditionItem : public juce::PopupMenu::CustomComponent
    {
    public:
        AuditionItem (TypeSelectorView& owner, int bodyIdx, juce::String name, bool ticked)
            : juce::PopupMenu::CustomComponent (true),
              o (owner), idx (bodyIdx), label (std::move (name)), isTicked (ticked) {}
        void getIdealSize (int& w, int& h) override
        {
            w = juce::jmax (150, label.length() * 8 + 40); h = 22;
        }
        void paint (juce::Graphics& g) override
        {
            const bool hot = isItemHighlighted();
            if (hot && ! wasHot)
            {
                auto safeOwner = juce::Component::SafePointer<TypeSelectorView> (&o);
                const int i = idx;
                juce::MessageManager::callAsync ([safeOwner, i]
                {
                    if (safeOwner != nullptr)
                        safeOwner->previewBody (i);
                });
            }
            wasHot = hot;
            auto r = getLocalBounds().toFloat();
            if (hot)
            {
                g.setColour (juce::Colour (0xffcfe8de).withAlpha (0.10f));
                g.fillRect (r.reduced (2.0f, 1.0f));
                auto rail = r.reduced (2.0f, 1.0f); rail.setWidth (2.0f);
                g.setColour (juce::Colour (0xff2bd8c3).withAlpha (0.85f));
                g.fillRect (rail);
            }
            if (isTicked)
            {
                g.setColour (juce::Colour (0xffcfe8de).withAlpha (0.85f));
                g.fillRoundedRectangle (juce::Rectangle<float> (hot ? 6.0f : 2.0f, 4.0f, 3.0f, r.getHeight() - 8.0f), 1.0f);
            }
            g.setFont (displayFont (14.5f, false));
            g.setColour (isTicked ? juce::Colour (0xffe4f2ec) : juce::Colour (0xffcfe8de));
            g.drawFittedText (label, getLocalBounds().reduced (12, 0),
                              juce::Justification::centredLeft, 1);
        }
    private:
        TypeSelectorView& o;
        int idx;
        juce::String label;
        bool isTicked, wasHot = false;
    };
    void previewBody (int idx)
    {
        selector.setSelectedItemIndex (idx, juce::sendNotificationSync);
    }
    void showGroupedMenu()
    {
        int count = 0;
        const auto* entries = trench::bodyRoster (count);
        const int current = selector.getSelectedId() - 1;
        struct Fam { const char* prefix; const char* label; };
        static constexpr Fam kFams[] = {
            { "VOWL_", "VOWELS" }, { "RISERL_", "RISERS" }, { "CAVL_", "CAVES" },
            { "X_", "CROSSES" }, { "three_layer", "LAYERS" }, { "FUZZ_", "FUZZ" },
            { "METALL_", "METAL" }, { "M0_", "HYBRIDS" },
        };
        juce::PopupMenu m;
        m.setLookAndFeel (&menuLookAndFeel);
        juce::PopupMenu fams[std::size (kFams)];
        struct FolderMenu
        {
            juce::String label;
            std::unique_ptr<juce::PopupMenu> menu = std::make_unique<juce::PopupMenu>();
            std::vector<std::pair<juce::String, std::unique_ptr<juce::PopupMenu>>> children;
            int itemCount = 0;
        };
        std::vector<FolderMenu> folders;
        auto isUser = [] (const char* base) { return juce::String (base).containsChar (':'); };
        auto famIndex = [&] (const char* base) -> int
        {
            if (isUser (base))
                return -2;
            const juce::String b (base);
            for (int f = 0; f < (int) std::size (kFams); ++f)
                if (b.startsWith (kFams[(size_t) f].prefix))
                    return f;
            return -1;
        };
        auto folderFor = [&folders] (const juce::String& label) -> FolderMenu&
        {
            for (auto& folder : folders)
                if (folder.label == label)
                    return folder;
            folders.push_back ({ label });
            return folders.back();
        };
        auto addToFolder = [&] (int index)
        {
            juce::String category (entries[index].category);
            if (category.isEmpty())
                category = "USER";
            category = category.replaceCharacter ('\\', '/');
            const int slash = category.indexOfChar ('/');
            const auto top = slash >= 0 ? category.substring (0, slash) : category;
            const auto leaf = slash >= 0 ? category.substring (slash + 1) : juce::String();
            auto& folder = folderFor (top.isEmpty() ? juce::String ("USER") : top);
            juce::PopupMenu* destination = folder.menu.get();
            if (leaf.isNotEmpty())
            {
                for (auto& child : folder.children)
                    if (child.first == leaf)
                    {
                        destination = child.second.get();
                        break;
                    }
                if (destination == folder.menu.get())
                {
                    folder.children.emplace_back (leaf, std::make_unique<juce::PopupMenu>());
                    destination = folder.children.back().second.get();
                }
            }
            destination->addCustomItem (index + 1,
                                        std::make_unique<AuditionItem> (*this, index,
                                                                         entries[index].displayName,
                                                                         index == current));
            ++folder.itemCount;
        };
        for (int i = 0; i < count; ++i)
            if (famIndex (entries[i].base) == -1)
                m.addCustomItem (i + 1, std::make_unique<AuditionItem> (*this, i, entries[i].displayName, i == current));
        m.addSeparator();
        for (int i = 0; i < count; ++i)
        {
            const int f = famIndex (entries[i].base);
            if (f >= 0)
                fams[f].addCustomItem (i + 1, std::make_unique<AuditionItem> (*this, i, entries[i].displayName, i == current));
            else if (f == -2)
                addToFolder (i);
        }
        for (auto& folder : folders)
        {
            for (auto& child : folder.children)
                folder.menu->addSubMenu (child.first, *child.second, true, nullptr,
                                         current >= 0 && isUser (entries[current].base)
                                             && juce::String (entries[current].category).startsWithIgnoreCase (folder.label + "/" + child.first));
            if (folder.itemCount > 0)
                m.addSubMenu (folder.label, *folder.menu, true, nullptr,
                              current >= 0 && isUser (entries[current].base)
                                  && juce::String (entries[current].category).startsWithIgnoreCase (folder.label));
        }
        for (int f = 0; f < (int) std::size (kFams); ++f)
            if (fams[f].getNumItems() > 0)
                m.addSubMenu (kFams[(size_t) f].label, fams[f], true, nullptr,
                              current >= 0 && famIndex (entries[current].base) == f);
        juce::Component::SafePointer<TypeSelectorView> self (this);
        m.showMenuAsync (juce::PopupMenu::Options().withTargetComponent (this),
                         [self, current] (int id)
                         {
                             if (self == nullptr)
                                 return;
                             if (id > 0)
                                 self->selector.setSelectedItemIndex (id - 1, juce::sendNotificationSync);
                             else if (current >= 0)
                                 self->selector.setSelectedItemIndex (current, juce::sendNotificationSync);
                         });
    }
    void paint (juce::Graphics& g) override
    {
        const auto recess = getLocalBounds().toFloat();
        const auto bar = recess;
        const bool hot = isMouseOverOrDragging (true) || selector.isPopupActive();
        drawIvoryWell (g, bar, bar.getHeight() * 0.18f, hot, t);
        auto inner = bar.reduced (13.0f, 2.0f);
        juce::Rectangle<float> box;
        const auto arrowSrc = t.layout.sourceRectFor ("typeArrow");
        if (arrowSrc.getWidth() > 1.0f)
            box = sourceRectToEditor (arrowSrc).translated (-(float) getX(), -(float) getY());
        else
        {
            const float w = bar.getHeight() + t.typeArrowExtra();
            box = inner.removeFromRight (w).withSizeKeepingCentre (w - 8.0f, bar.getHeight() - 8.0f);
        }
        const auto textArea = juce::Rectangle<float> (inner.getX(), inner.getY(),
                                                      juce::jmax (10.0f, box.getX() - inner.getX() - 16.0f),
                                                      inner.getHeight());
        const auto selectedIndex = selector.getSelectedId() - 1;
        const auto typeText = selectedIndex >= 0 ? trench::bodyDisplayName (selectedIndex) : juce::String();
        g.setFont (displayFont (t.fontSize ("typeName", 17.0f), true));
        g.setColour (hot ? juce::Colours::black : t.textColour ("typeName", juce::Colour (0xff0b0b0b)));
        g.drawText (typeText, textArea.toNearestInt(),
                    juce::Justification::centredLeft, false);
        g.setColour (juce::Colour (0xff6a6256).withAlpha (0.52f));
        g.drawLine (box.getX() - 3.5f, bar.getY() + 5.0f,
                    box.getX() - 3.5f, bar.getBottom() - 5.0f, 1.0f);
        const auto arrow = box.withSizeKeepingCentre (11.0f, 7.0f).translated (0.0f, 0.5f);
        juce::Path arrowPath;
        arrowPath.startNewSubPath (arrow.getX(), arrow.getY());
        arrowPath.lineTo (arrow.getCentreX(), arrow.getBottom());
        arrowPath.lineTo (arrow.getRight(), arrow.getY());
        g.setColour (juce::Colours::white.withAlpha (0.40f));
        g.strokePath (arrowPath, juce::PathStrokeType (1.5f, juce::PathStrokeType::mitered, juce::PathStrokeType::butt),
                      juce::AffineTransform::translation (0.0f, 1.0f));
        g.setColour (t.arrow());
        g.strokePath (arrowPath, juce::PathStrokeType (1.5f, juce::PathStrokeType::mitered, juce::PathStrokeType::butt));
    }
private:
    // one dropdown theme across the face: the shared teal-glass selector
    class MenuLookAndFeel final : public SelectorLookAndFeel
    {
    public:
        explicit MenuLookAndFeel (const Theme&) {}
        juce::Font getComboBoxFont (juce::ComboBox&) override { return displayFont (14.5f, false); }
    };
    static void drawTrackedText (juce::Graphics& g, const juce::String& text,
                                 juce::Rectangle<float> area, juce::Font font,
                                 juce::Colour colour, float tracking)
    {
        if (text.isEmpty())
            return;
        g.setFont (font);
        g.setColour (colour);
        const int n = text.length();
        const float rawWidth = juce::GlyphArrangement::getStringWidth (font, text);
        if (n > 1)
            tracking = juce::jlimit (0.0f, tracking,
                                     (area.getWidth() - rawWidth) / (float) (n - 1));
        else
            tracking = 0.0f;
        float x = area.getX();
        const float y = area.getCentreY() - font.getHeight() * 0.48f;
        for (int i = 0; i < n; ++i)
        {
            const auto glyph = text.substring (i, i + 1);
            const float w = juce::GlyphArrangement::getStringWidth (font, glyph);
            g.drawText (glyph, juce::Rectangle<float> (x, y, w + 2.0f, font.getHeight()),
                        juce::Justification::centredLeft, false);
            x += w + tracking;
            if (x > area.getRight())
                break;
        }
    }
    void comboBoxChanged (juce::ComboBox*) override
    {
        if (onAnnounce)
            onAnnounce (selector.getText());
        repaint();
    }
    void mouseWheelMove (const juce::MouseEvent&, const juce::MouseWheelDetails& w) override
    {
        const int n = selector.getNumItems();
        if (n == 0 || w.deltaY == 0.0f)
            return;
        const int step = w.deltaY > 0.0f ? -1 : 1;
        const int idx = juce::jlimit (0, n - 1, selector.getSelectedItemIndex() + step);
        selector.setSelectedItemIndex (idx, juce::sendNotificationSync);
    }
public:
    std::function<void (const juce::String&)> onAnnounce;
private:
    void populate()
    {
        selector.clear (juce::dontSendNotification);
        int count = 0;
        const auto* entries = trench::bodyRoster (count);
        for (int i = 0; i < count; ++i)
            selector.addItem (entries[i].displayName, i + 1);
    }
    Theme t;
    MenuLookAndFeel menuLookAndFeel;
    juce::ComboBox selector;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> attachment;
};
}
