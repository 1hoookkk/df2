#pragma once

#include "BinaryData.h"

#include <juce_core/juce_core.h>

#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

namespace trench
{

struct BodyEntry
{
    const char* displayName;
    const char* base;
    const char* category;
    int behavior;
};

enum class TypeBehavior : int
{
    Static = 0,
    Dynamic,
    AutoQuarter,
    AutoHalf,
    Wobble,
    User,
};

enum class SecondaryTarget : int
{
    packed = 0,
    slam,
    packedAndSlam,
};

enum class MorphTaper : int
{
    linear = 0,
    log1p45,
};

struct BodyBehavior
{
    SecondaryTarget secondaryTarget = SecondaryTarget::packed;
    MorphTaper morphTaper = MorphTaper::linear;
};

inline constexpr const char* kAuditionBase = "@audition";

// NO FILTER is roster slot 0, backed by the baked `identity.body240`. That body
// is an EXACT identity cascade (nulls at -240 dBFS), so this is a real bypass,
// not a nearly-flat body — and it is the default the plug-in opens on.
//
// It used to also exist as a phantom index -1. That never worked: `wrapBodyIndex(-1)`
// wraps to `count - 1`, so "No Filter" silently loaded the LAST body in the
// library, and `forceCleanAudioUiState()` did the same. One concept now, and it
// is the one that is actually flat.
inline constexpr int kNoFilterIndex = 0;
inline constexpr int kDefaultBodyIndex = kNoFilterIndex;
inline constexpr const char* kNoFilterName = "NO FILTER";

inline const BodyEntry* bakedRoster (int& countOut) noexcept;

inline juce::File auditionSlotFile() noexcept
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
               .getChildFile ("TRENCH")
               .getChildFile ("authoring_slot.json");
}

inline juce::File uiLayoutFile() noexcept
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
               .getChildFile ("TRENCH")
               .getChildFile ("ui_layout.json");
}

namespace detail
{
struct RosterStore
{
    std::vector<std::string> names;
    std::vector<std::string> bases;
    std::vector<std::string> categories;
    std::vector<BodyEntry> entries;
};

// Product-face name from a raw body stem: drop the leading ALL-CAPS family
// tag ("CAVL_"), turn underscores into spaces, and title-case the words —
// "CAVL_beer_bottle_to_plastic_jug" reads "Beer Bottle to Plastic Jug".
// Display only; resource stems and file lookups keep the raw name.
inline std::string prettyBodyName (const std::string& stem)
{
    juce::String s (stem);
    const int us = s.indexOfChar ('_');
    if (us > 0 && s.substring (0, us) == s.substring (0, us).toUpperCase())
        s = s.substring (us + 1);
    s = s.replaceCharacter ('_', ' ');
    juce::String out;
    for (const auto& word : juce::StringArray::fromTokens (s, " ", {}))
    {
        if (out.isNotEmpty())
            out << ' ';
        out << (word == "to" ? word : word.substring (0, 1).toUpperCase() + word.substring (1));
    }
    return out.toStdString();
}

inline std::string bodyStem (const juce::File& file)
{
    auto name = file.getFileName();
    if (name.endsWithIgnoreCase (".cart.json"))
        return name.dropLastCharacters (10).toStdString();
    return file.getFileNameWithoutExtension().toStdString();
}

inline RosterStore& rosterStore()
{
    static RosterStore store;
    static bool built = false;
    if (! built)
    {
        built = true;
        int bakedCount = 0;
        const auto* baked = bakedRoster (bakedCount);
        for (int index = 0; index < bakedCount; ++index)
        {
            store.names.emplace_back (index == kNoFilterIndex
                                          ? std::string (baked[index].displayName)
                                          : prettyBodyName (baked[index].displayName));
            store.bases.emplace_back (baked[index].base);
            store.categories.emplace_back (baked[index].category);
        }

        const auto dir = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                             .getChildFile ("TRENCH")
                             .getChildFile ("bodies");
        if (dir.isDirectory())
        {
            auto files = dir.findChildFiles (juce::File::findFiles, false, "*.body240;*.cart.json;*.json");
            std::sort (files.begin(), files.end(), [] (const juce::File& a, const juce::File& b)
            {
                return a.getFullPathName() < b.getFullPathName();
            });
            for (const auto& file : files)
            {
                const auto stem = bodyStem (file);
                const auto pretty = prettyBodyName (stem);
                if (stem.empty() || std::find (store.names.begin(), store.names.end(), pretty) != store.names.end())
                    continue;
                store.names.push_back (pretty);
                store.bases.push_back (file.getFullPathName().toStdString());
                store.categories.push_back ("LIBRARY");
            }
        }

        store.entries.reserve (store.names.size());
        for (size_t i = 0; i < store.names.size(); ++i)
            store.entries.push_back ({ store.names[i].c_str(), store.bases[i].c_str(),
                                       store.categories[i].c_str(), (int) TypeBehavior::Static });
    }
    return store;
}
} // namespace detail

inline const BodyEntry* bakedRoster (int& countOut) noexcept
{
    static const BodyEntry entries[] = {
        { kNoFilterName, "identity", "SYSTEM", (int) TypeBehavior::Static },
#define TRENCH_PRESET(displayName, resourceStem, categoryName) \
        { displayName, resourceStem, categoryName, (int) TypeBehavior::Static },
#include "../presets/PresetRoster.inc"
#undef TRENCH_PRESET
    };
    countOut = (int) (sizeof (entries) / sizeof (entries[0]));
    return entries;
}

inline const BodyEntry* bodyRoster (int& countOut) noexcept
{
    auto& store = detail::rosterStore();
    countOut = (int) store.entries.size();
    return store.entries.data();
}

inline int bodyCount() noexcept
{
    int count = 0;
    bodyRoster (count);
    return count;
}

inline int wrapBodyIndex (int index) noexcept
{
    const auto count = bodyCount();
    if (count <= 0)
        return 0;
    index %= count;
    return index < 0 ? index + count : index;
}

inline bool bodyIsNoFilter (int index) noexcept { return wrapBodyIndex (index) == kNoFilterIndex; }

// Bodies whose reaction (input level -> Q push) is baked into the preset:
// the processor floors Motion React at CHOP's constant while one is loaded,
// no tile arming required. `mode` tunes WHAT the detector hears:
//   0 = not a baked-react body   1 = broadband (full input)
//   2 = highpassed at cutoffHz   3 = lowpassed at cutoffHz
struct BakedReactSpec { int mode; float cutoffHz; };

inline BakedReactSpec bodyBakedReactSpec (int index)
{
    auto& store = detail::rosterStore();
    const auto& name = store.names[(size_t) wrapBodyIndex (index)];
    if (name == "De-Esser")  return { 2, 4000.0f };
    if (name == "De-Mudder") return { 3, 700.0f };
    return { 0, 0.0f };
}

inline bool bodyIsAudition (int) noexcept { return false; }

inline bool bodyRawBytes (int index, juce::MemoryBlock& out) noexcept
{
    int count = 0;
    const auto* roster = bodyRoster (count);
    if (count <= 0)
        return false;

    const auto& entry = roster[wrapBodyIndex (index)];
    if (juce::File::isAbsolutePath (entry.base))
    {
        const juce::File file (entry.base);
        if (file.existsAsFile() && file.hasFileExtension ("body240")
            && file.loadFileAsData (out) && out.getSize() == 240)
            return true;
        return false;
    }

    const auto wantedFilename = juce::String (entry.base) + ".body240";
    for (int resource = 0; resource < BinaryData::namedResourceListSize; ++resource)
    {
        if (wantedFilename != BinaryData::originalFilenames[resource])
            continue;
        int size = 0;
        const auto* data = BinaryData::getNamedResource (BinaryData::namedResourceList[resource], size);
        if (data == nullptr || size != 240)
            return false;
        out.setSize (240);
        out.copyFrom (data, 0, 240);
        return true;
    }
    return false;
}

inline juce::String bodyCartridgeJson (int index) noexcept
{
    int count = 0;
    const auto* roster = bodyRoster (count);
    if (count <= 0)
        return {};

    const auto& entry = roster[wrapBodyIndex (index)];
    if (juce::File::isAbsolutePath (entry.base))
    {
        const juce::File file (entry.base);
        return file.hasFileExtension ("body240") ? juce::String() : file.loadFileAsString();
    }

    int size = 0;
    const auto* data = BinaryData::getNamedResource ((juce::String (entry.base) + "_json").toRawUTF8(), size);
    return data != nullptr && size > 0 ? juce::String::createStringFromData (data, size) : juce::String();
}

inline juce::String bodyDisplayName (int index) noexcept
{
    if (bodyIsNoFilter (index))
        return kNoFilterName;
    int count = 0;
    const auto* roster = bodyRoster (count);
    return count > 0 ? roster[wrapBodyIndex (index)].displayName : juce::String();
}

inline TypeBehavior bodyTypeBehavior (int index) noexcept
{
    if (bodyIsNoFilter (index))
        return TypeBehavior::Static;
    int count = 0;
    const auto* roster = bodyRoster (count);
    return count > 0 ? (TypeBehavior) roster[wrapBodyIndex (index)].behavior : TypeBehavior::Static;
}

inline bool bodyTypeHasMotion (int index) noexcept
{
    return bodyTypeBehavior (index) != TypeBehavior::Static;
}

inline bool bodyUsesLogMorph (int) noexcept { return false; }
inline bool bodySecondaryDrivesSlam (int) noexcept { return false; }

inline BodyBehavior fallbackBodyBehavior (int index) noexcept
{
    juce::ignoreUnused (index);
    return {};
}

inline SecondaryTarget secondaryTargetFromString (juce::String value) noexcept
{
    value = value.trim().toLowerCase();
    if (value == "slam" || value == "drive")
        return SecondaryTarget::slam;
    if (value == "packed+slam" || value == "packed_secondary_plus_slam" || value == "both")
        return SecondaryTarget::packedAndSlam;
    return SecondaryTarget::packed;
}

inline MorphTaper morphTaperFromString (juce::String value) noexcept
{
    value = value.trim().toLowerCase();
    return value == "log" || value == "log_1p45" ? MorphTaper::log1p45 : MorphTaper::linear;
}

inline BodyBehavior bodyBehaviorFromCartridgeJson (int index, const juce::String& json)
{
    auto behavior = fallbackBodyBehavior (index);
    const auto root = juce::JSON::parse (json);
    if (const auto* object = root.getDynamicObject())
    {
        const auto secondary = object->getProperty ("secondary_target");
        if (! secondary.isVoid())
            behavior.secondaryTarget = secondaryTargetFromString (secondary.toString());
        const auto taper = object->getProperty ("morph_taper");
        if (! taper.isVoid())
            behavior.morphTaper = morphTaperFromString (taper.toString());
    }
    return behavior;
}

inline bool secondaryTargetUsesPacked (SecondaryTarget target) noexcept
{
    return target == SecondaryTarget::packed || target == SecondaryTarget::packedAndSlam;
}

inline bool secondaryTargetUsesSlam (SecondaryTarget target) noexcept
{
    return target == SecondaryTarget::slam || target == SecondaryTarget::packedAndSlam;
}

inline float applyMorphTaper (MorphTaper taper, float morph) noexcept
{
    const auto value = juce::jlimit (0.0f, 1.0f, morph);
    return taper == MorphTaper::log1p45 ? std::pow (value, 1.45f) : value;
}

inline float bodyMorphForEngine (int index, float morph) noexcept
{
    return applyMorphTaper (fallbackBodyBehavior (index).morphTaper, morph);
}

inline bool bodyRawBytesFromCurrentPath (const juce::String& path, juce::MemoryBlock& out) noexcept
{
    const juce::File file (path);
    return file.existsAsFile() && file.hasFileExtension ("body240")
        && file.loadFileAsData (out) && out.getSize() == 240;
}

} // namespace trench
