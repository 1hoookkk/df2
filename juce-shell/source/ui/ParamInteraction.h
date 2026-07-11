#pragma once

#include <juce_audio_processors/juce_audio_processors.h>
#include <memory>

namespace trench::ui
{

// Shared parameter interactions so every control behaves like a pro plugin:
//   • right-click  -> Reset + the HOST's own menu (MIDI learn / automation)
//   • fine drag    -> hold Shift for a slow, precise drag (Shift survives hosts; Alt doesn't)
// The host menu is surfaced through AudioProcessorEditor::getHostContext() — the
// modern JUCE way to expose the DAW's real MIDI-learn/automation menu rather than
// faking one. Any component can call these; the editor is found by walking up.

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

    // ONLY the DAW's own menu (MIDI learn / automation link). No JUCE-generic
    // items — reset is double-click, adjust is scroll/drag. If the host provides
    // no menu (e.g. standalone), right-click does nothing rather than show clutter.
    if (auto* ed = owner.findParentComponentOfClass<juce::AudioProcessorEditor>())
        if (auto* hc = ed->getHostContext())
            if (auto host = hc->getContextMenuForParameter (param))
            {
                std::shared_ptr<juce::HostProvidedContextMenu> keep = std::move (host);
                auto m = keep->getEquivalentPopupMenu();
                if (m.getNumItems() > 0)
                    m.showMenuAsync (juce::PopupMenu::Options().withTargetComponent (&owner),
                                     [keep] (int) {});   // keep host alive until the menu closes
            }
}

// Scale a normalised drag delta down when Shift is held, for fine adjustment.
inline float fineDragScale (const juce::MouseEvent& e)
{
    return e.mods.isShiftDown() ? 0.2f : 1.0f;
}

} // namespace trench::ui
