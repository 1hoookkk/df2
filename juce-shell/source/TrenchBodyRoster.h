#pragma once

#include "BinaryData.h"

#include <algorithm>
#include <cmath>
#include <string>
#include <vector>
#include <juce_core/juce_core.h>

namespace trench
{
// Canonical body roster: the single source of truth for selectable runtime
// bodies. The processor reads from here when loading cartridge JSON.
//
// To ship a new body: bake its <base>.body240 into Assets (BinaryData symbol
// <base>_body240) and add a row below. Diagnostics builds may also scan
// Documents/TRENCH/bodies; product builds expose only this curated roster.
struct BodyEntry
{
    const char* displayName;
    const char* base; // e.g. "speaker_knockerz" -> resource "speaker_knockerz_json"
    const char* category;
    int behavior; // TypeBehavior as int: sound body + visible behavior name.
};

enum class TypeBehavior : int
{
    Static = 0,
    Dynamic,     // Adlib Chop — envelope-follower reactive
    AutoQuarter, // Breathe — pendulum, tempo-synced
    AutoHalf,    // Riser — forward, tempo-synced
    Wobble,      // Random/Brownian step, tempo-synced
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

// Sentinel base for the live Forge-audition entry. When selected, the body
// loads (and hot-reloads) from Documents/TRENCH/authoring_slot.json. It only
// reloads while it is the selected body, so it can never hijack the others.
inline constexpr const char* kAuditionBase = "@audition";
inline constexpr int kDefaultBodyIndex = 0;
inline constexpr int kNoFilterIndex = -1;
inline constexpr const char* kNoFilterName = "No Filter";

// The baked, shipping roster. These stay at the front so shipping indices never move.
inline const BodyEntry* bakedRoster (int& countOut) noexcept
{
    static const BodyEntry entries[] = {
        { "Meaty Gizmo",   "P2k_004_meaty_gizmo",   "DEMO", (int) TypeBehavior::Static },
        { "Talking Hedz",  "P2k_013_talking_hedz",  "DEMO", (int) TypeBehavior::Static },
        { "Lucifers Q",    "P2k_029_lucifer_s_q",   "DEMO", (int) TypeBehavior::Static },
#ifdef TRENCH_PLAYER_DIAGNOSTICS
        { "@ Audition (live)", "@audition", "LIVE", (int) TypeBehavior::Static },
#endif
    };
    countOut = (int) (sizeof (entries) / sizeof (entries[0]));
    return entries;
}

namespace detail
{
// Owns the dynamic roster strings so BodyEntry's const char* stay valid for the process.
struct RosterStore
{
    std::vector<std::string> names, bases, cats;
    std::vector<BodyEntry> entries;
};

// Diagnostics only. Built once per process: baked roster first, then every body
// file dropped under Documents/TRENCH/bodies/ (raw .body240 or .cart.json/.json).
// Reload the plugin / restart the host to re-scan after adding files.
inline RosterStore& rosterStore()
{
    static RosterStore s;
    static bool built = false;
    if (! built)
    {
        built = true;
        // `s` has static storage duration, so it is usable inside the lambda without a
        // capture (a by-ref capture of a static is ill-formed: C3495).
        auto add = [] (std::string n, std::string b, std::string c)
        {
            s.names.push_back (std::move (n));
            s.bases.push_back (std::move (b));
            s.cats.push_back (std::move (c));
        };

        int bn = 0;
        const auto* baked = bakedRoster (bn);
        for (int i = 0; i < bn; ++i)
            add (baked[i].displayName, baked[i].base, baked[i].category);

        auto dir = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                       .getChildFile ("TRENCH").getChildFile ("bodies");
        if (dir.isDirectory())
        {
            auto found = dir.findChildFiles (juce::File::findFiles, false,
                                             "*.body240;*.cart.json;*.json");
            std::vector<juce::File> files (found.begin(), found.end());
            std::sort (files.begin(), files.end(), [] (const juce::File& a, const juce::File& b)
                       { return a.getFullPathName() < b.getFullPathName(); });
            for (const auto& f : files)
            {
                const auto stem = f.getFileNameWithoutExtension();
                // A .json/.cart.json whose stem matches a baked base is a per-entry
                // override (handled by bodyCartridgeJson) — don't add a duplicate row.
                bool overridesBaked = false;
                for (int i = 0; i < bn; ++i)
                    if (stem == juce::String (baked[i].base)) { overridesBaked = true; break; }
                if (overridesBaked && ! f.hasFileExtension ("body240"))
                    continue;

                add (stem.toStdString(),
                     f.getFullPathName().toStdString(),
                     f.hasFileExtension ("body240") ? "LIBRARY" : "LIBRARY-J");
            }
        }

        s.entries.reserve (s.names.size());
        for (size_t i = 0; i < s.names.size(); ++i)
            s.entries.push_back ({ s.names[i].c_str(), s.bases[i].c_str(), s.cats[i].c_str(),
                                   (int) TypeBehavior::Static });
    }
    return s;
}
} // namespace detail

inline const BodyEntry* bodyRoster (int& countOut) noexcept
{
#ifndef TRENCH_PLAYER_DIAGNOSTICS
    return bakedRoster (countOut);
#else
    auto& s = detail::rosterStore();
    countOut = (int) s.entries.size();
    return s.entries.data();
#endif
}

// The live Forge-authoring slot the audition body reads.
inline juce::File auditionSlotFile() noexcept
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
               .getChildFile ("TRENCH")
               .getChildFile ("authoring_slot.json");
}

// The live UI-layout override the "See Your Plugin" editor writes; the editor
// hot-reloads it (diagnostics build only).
inline juce::File uiLayoutFile() noexcept
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
               .getChildFile ("TRENCH")
               .getChildFile ("ui_layout.json");
}

inline bool bodyIsAudition (int index) noexcept
{
#ifndef TRENCH_PLAYER_DIAGNOSTICS
    juce::ignoreUnused (index);
    return false;
#else
    int n = 0;
    const auto* r = bodyRoster (n);
    if (n <= 0) return false;
    return juce::String (r[((index % n) + n) % n].base) == kAuditionBase;
#endif
}

inline int bodyCount() noexcept
{
    int n = 0;
    bodyRoster (n);
    return n;
}

inline int wrapBodyIndex (int index) noexcept
{
    const int n = bodyCount();
    if (n <= 0)
        return 0;
    index %= n;
    if (index < 0)
        index += n;
    return index;
}

inline bool bodyIsNoFilter (int index) noexcept
{
    return index == kNoFilterIndex;
}

inline bool bodyUsesLogMorph (int index) noexcept
{
    int n = 0;
    const auto* r = bodyRoster (n);
    if (n <= 0)
        return false;

    return juce::String (r[wrapBodyIndex (index)].base) == "v1_bass_sharpener";
}

inline bool bodySecondaryDrivesSlam (int index) noexcept
{
    int n = 0;
    const auto* r = bodyRoster (n);
    if (n <= 0)
        return false;

    return juce::String (r[wrapBodyIndex (index)].base) == "v1_bass_sharpener";
}

inline BodyBehavior fallbackBodyBehavior (int index) noexcept
{
    BodyBehavior behavior;
    if (bodyUsesLogMorph (index))
        behavior.morphTaper = MorphTaper::log1p45;
    if (bodySecondaryDrivesSlam (index))
        behavior.secondaryTarget = SecondaryTarget::slam;
    return behavior;
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
    if (value == "log_1p45" || value == "fixed_axis_log_1p45" || value == "log")
        return MorphTaper::log1p45;
    return MorphTaper::linear;
}

inline BodyBehavior bodyBehaviorFromCartridgeJson (int index, const juce::String& json)
{
    auto behavior = fallbackBodyBehavior (index);
    if (json.isEmpty())
        return behavior;

    const auto root = juce::JSON::parse (json);
    const auto* obj = root.getDynamicObject();
    if (obj == nullptr)
        return behavior;

    const auto secondary = obj->getProperty ("secondary_target");
    if (! secondary.isVoid())
        behavior.secondaryTarget = secondaryTargetFromString (secondary.toString());

    const auto taper = obj->getProperty ("morph_taper");
    if (! taper.isVoid())
        behavior.morphTaper = morphTaperFromString (taper.toString());

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
    const auto x = juce::jlimit (0.0f, 1.0f, morph);
    if (taper != MorphTaper::log1p45)
        return x;

    // Bass Sharpener is a fixed-axis bass-frequency move. Keep the sweep
    // logarithmic-feeling without hiding the center of the original move.
    return std::pow (x, 1.45f);
}

inline float bodyMorphForEngine (int index, float morph) noexcept
{
    return applyMorphTaper (fallbackBodyBehavior (index).morphTaper, morph);
}

inline juce::String bodyDisplayName (int index) noexcept
{
    if (bodyIsNoFilter (index))
        return kNoFilterName;
    int n = 0;
    const auto* r = bodyRoster (n);
    if (n <= 0)
        return {};
    return r[wrapBodyIndex (index)].displayName;
}

inline TypeBehavior bodyTypeBehavior (int index) noexcept
{
    if (bodyIsNoFilter (index))
        return TypeBehavior::Static;
    int n = 0;
    const auto* r = bodyRoster (n);
    if (n <= 0)
        return TypeBehavior::Static;
    return (TypeBehavior) r[wrapBodyIndex (index)].behavior;
}

inline bool bodyTypeHasMotion (int index) noexcept
{
    return bodyTypeBehavior (index) != TypeBehavior::Static;
}

// True + fills `out` (240 bytes) if this index is a raw .body240 library file.
inline bool bodyRawBytes (int index, juce::MemoryBlock& out) noexcept
{
    int n = 0;
    const auto* r = bodyRoster (n);
    if (n <= 0)
        return false;

    const auto& entry = r[wrapBodyIndex (index)];
    if (juce::File::isAbsolutePath (entry.base))
    {
        juce::File f (entry.base);
        if (f.existsAsFile() && f.hasFileExtension ("body240")
            && f.loadFileAsData (out) && out.getSize() == 240)
            return true;
    }
    else
    {
        // Baked shipping body: raw 240 bytes embedded as BinaryData "<base>_body240".
        int size = 0;
        const char* data = BinaryData::getNamedResource (
            (juce::String (entry.base) + "_body240").toRawUTF8(), size);
        if (data != nullptr && size == 240)
        {
            out.setSize (240);
            out.copyFrom (data, 0, 240);
            return true;
        }
    }
    out.setSize (0);
    return false;
}

// Returns the cartridge JSON for the given body index. Prefers a user override
// under Documents/TRENCH/bodies/; falls back to the baked BinaryData copy.
inline juce::String bodyCartridgeJson (int index) noexcept
{
    int n = 0;
    const auto* r = bodyRoster (n);
    if (n <= 0)
        return {};

    const auto& entry = r[wrapBodyIndex (index)];

    // Live Forge audition: read the authoring slot straight off disk.
#ifdef TRENCH_PLAYER_DIAGNOSTICS
    if (juce::String (entry.base) == kAuditionBase)
    {
        auto f = auditionSlotFile();
        return f.existsAsFile() ? f.loadFileAsString() : juce::String();
    }

    // Library entry: base is an absolute file path under Documents/TRENCH/bodies/.
    if (juce::File::isAbsolutePath (entry.base))
    {
        juce::File f (entry.base);
        if (f.existsAsFile() && ! f.hasFileExtension ("body240"))
            return f.loadFileAsString();   // .json / .cart.json
        return {};                          // .body240 -> loaded via bodyRawBytes()
    }

    auto bodiesDir = juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                         .getChildFile ("TRENCH")
                         .getChildFile ("bodies");
    for (const auto* suffix : { ".cart.json", ".json" })
    {
        auto override = bodiesDir.getChildFile (juce::String (entry.base) + suffix);
        if (override.existsAsFile())
        {
            auto s = override.loadFileAsString();
            if (s.isNotEmpty())
                return s;
        }
    }
#endif

    int size = 0;
    const char* data = BinaryData::getNamedResource ((juce::String (entry.base) + "_json").toRawUTF8(), size);
    if (data != nullptr && size > 0)
        return juce::String::createStringFromData (data, size);

    return {};
}
} // namespace trench
