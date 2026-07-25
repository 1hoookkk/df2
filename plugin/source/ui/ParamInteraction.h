#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>
namespace trench::ui
{
inline void resetParamToDefault (juce::RangedAudioParameter* p)
{
    if (p == nullptr) return;
    p->beginChangeGesture();
    p->setValueNotifyingHost (p->getDefaultValue());
    p->endChangeGesture();
}
inline void showParamContextMenu (juce::Component& owner, juce::RangedAudioParameter* param)
{
    if (param == nullptr) return;
    if (auto* ed = owner.findParentComponentOfClass<juce::AudioProcessorEditor>())
        if (auto* hc = ed->getHostContext())
            if (auto host = hc->getContextMenuForParameter (param))
            {
                std::shared_ptr<juce::HostProvidedContextMenu> keep = std::move (host);
                auto m = keep->getEquivalentPopupMenu();
                
                juce::PopupMenu filtered;
                juce::PopupMenu::MenuItemIterator it (m);
                while (it.next())
                {
                    auto& item = it.getItem();
                    // Filter out JUCE's default parameter context menu items
                    if (item.text.containsIgnoreCase ("Value") || 
                        item.text.containsIgnoreCase ("Set..."))
                        continue;
                    // Filter out trailing/double separators caused by the above
                    if (item.isSeparator && filtered.getNumItems() > 0)
                    {
                        // Check if last item was a separator (or maybe don't bother for now)
                        filtered.addItem (item);
                    }
                    else if (!item.isSeparator)
                    {
                        filtered.addItem (item);
                    }
                }

                if (filtered.getNumItems() > 0)
                    filtered.showMenuAsync (juce::PopupMenu::Options().withTargetComponent (&owner),
                                     [keep] (int) {});
            }
}
inline float fineDragScale (const juce::MouseEvent& e)
{
    return e.mods.isShiftDown() ? 0.2f : 1.0f;
}
}
