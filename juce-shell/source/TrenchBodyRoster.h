#pragma once

#include "BinaryData.h"

#include <juce_core/juce_core.h>

namespace trench
{
// Canonical body roster — the single source of truth for the player's
// selectable bodies. Both the chassis Body strip (display) and the processor
// (cartridge load) read from here, so names and loaded sound can never drift
// apart.
//
// To ship a new body: bake its <base>.json into Assets (BinaryData symbol
// <base>_json) and add a row below. A user can also drop a
// Documents/TRENCH/bodies/<base>.cart.json (or <base>.json) to override or
// extend at runtime with no rebuild — mirroring the chassis_variants path.
struct BodyEntry
{
    const char* displayName;
    const char* base; // e.g. "speaker_knockerz" -> resource "speaker_knockerz_json"
};

// Sentinel base for the live Forge-audition entry. When selected, the body
// loads (and hot-reloads) from Documents/TRENCH/authoring_slot.json. It only
// reloads while it is the selected body, so it can never hijack the others.
inline constexpr const char* kAuditionBase = "@audition";

inline const BodyEntry* bodyRoster (int& countOut) noexcept
{
    static const BodyEntry entries[] = {
        // Neon Vane = clean boot default. Then the ten factory bodies authored
        // via the forge-corners skill (traveling band-peaks, no pedestal, near-
        // Nyquist edge). The old low-end-pedestal four (speaker_knockerz etc.)
        // are dropped from the roster pending re-authoring with the same skill.
        { "Neon Vane",      "neon_vane"   },
        { "Gong",           "gong"        },
        { "Anvil",          "anvil"       },
        { "Razor",          "razor"       },
        { "Scream",         "scream"      },
        { "Bloom",          "bloom"       },
        { "Ascension",      "ascension"   },
        { "Talkbox",        "talkbox"     },
        { "Vowelshift",     "vowelshift"  },
        { "Siphon",         "siphon"      },
        { "Spectre",        "spectre"     },
        { "Forge Audition", kAuditionBase },
    };
    countOut = (int) (sizeof (entries) / sizeof (entries[0]));
    return entries;
}

// The live Forge-authoring slot the audition body reads.
inline juce::File auditionSlotFile() noexcept
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
               .getChildFile ("TRENCH")
               .getChildFile ("authoring_slot.json");
}

inline bool bodyIsAudition (int index) noexcept
{
    int n = 0;
    const auto* r = bodyRoster (n);
    if (n <= 0) return false;
    return juce::String (r[((index % n) + n) % n].base) == kAuditionBase;
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

inline juce::String bodyDisplayName (int index) noexcept
{
    int n = 0;
    const auto* r = bodyRoster (n);
    if (n <= 0)
        return {};
    return r[wrapBodyIndex (index)].displayName;
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
    if (juce::String (entry.base) == kAuditionBase)
    {
        auto f = auditionSlotFile();
        return f.existsAsFile() ? f.loadFileAsString() : juce::String();
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

    int size = 0;
    const char* data = BinaryData::getNamedResource ((juce::String (entry.base) + "_json").toRawUTF8(), size);
    if (data != nullptr && size > 0)
        return juce::String::createStringFromData (data, size);

    return {};
}
} // namespace trench
