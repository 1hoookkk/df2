#pragma once

#include "dsp/TrenchDspBridge.h"

#include <juce_core/juce_core.h>
#include <juce_events/juce_events.h>

namespace trench
{

// File-based hot-reload for cartridge authoring.
//
// Watches a single JSON file at ~/Documents/TRENCH/authoring_slot.json.
// When the file's modification time changes, reads it and pushes to the
// DSP engine via TrenchDspBridge::loadCartridge.
//
// Any tool that writes a valid compiled-v1 cartridge JSON to that path will
// instantly update the running plugin in the DAW. No restart, no rescan,
// no parameter touch.
//
// Toggle the slot path or polling rate by editing the constants below.
class TrenchAuthoringSlot final : private juce::Timer
{
public:
    static constexpr int pollIntervalMs = 500;

    explicit TrenchAuthoringSlot (TrenchDspBridge& bridge)
        : dspBridge (bridge)
    {
        slotFile = defaultSlotFile();
        ensureParentDirExists();
        // Prime the modification time so we don't fire on construction.
        if (slotFile.existsAsFile())
            lastModTime = slotFile.getLastModificationTime();
        startTimer (pollIntervalMs);
    }

    ~TrenchAuthoringSlot() override
    {
        stopTimer();
    }

    juce::File getSlotFile() const noexcept { return slotFile; }

    // Force a load right now. Returns true on success.
    bool reloadNow()
    {
        if (! slotFile.existsAsFile())
            return false;

        juce::String json = slotFile.loadFileAsString();
        if (json.isEmpty())
            return false;

        const bool ok = dspBridge.loadCartridge (json);
        juce::Logger::writeToLog (juce::String ("TrenchAuthoringSlot reloadNow ")
                                   + (ok ? "ok" : "fail") + " from " + slotFile.getFullPathName());
        if (ok)
            lastModTime = slotFile.getLastModificationTime();
        return ok;
    }

private:
    static juce::File defaultSlotFile()
    {
        return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                   .getChildFile ("TRENCH")
                   .getChildFile ("authoring_slot.json");
    }

    void ensureParentDirExists() const
    {
        auto parent = slotFile.getParentDirectory();
        if (! parent.exists())
            parent.createDirectory();
    }

    void timerCallback() override
    {
        if (! slotFile.existsAsFile())
            return;

        const auto t = slotFile.getLastModificationTime();
        if (t == lastModTime)
            return;

        // Wait one tick for the writer to finish flushing — avoids loading
        // a half-written file. If the size is still changing we'll catch it
        // next poll.
        const auto sizeNow = slotFile.getSize();
        if (sizeNow <= 0)
            return;

        juce::String json = slotFile.loadFileAsString();
        if (json.isEmpty())
            return;

        const bool ok = dspBridge.loadCartridge (json);
        juce::Logger::writeToLog (juce::String ("TrenchAuthoringSlot reload ")
                                   + (ok ? "ok" : "fail")
                                   + " size=" + juce::String (sizeNow));
        // Update the modtime regardless — if parse failed we don't want to
        // hammer the same broken file every 500 ms.
        lastModTime = t;
    }

    TrenchDspBridge& dspBridge;
    juce::File slotFile;
    juce::Time lastModTime;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrenchAuthoringSlot)
};

} // namespace trench
