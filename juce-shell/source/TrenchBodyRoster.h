#pragma once

#include "BinaryData.h"

#include <cmath>
#include <juce_core/juce_core.h>

namespace trench
{
// Canonical body roster: the single source of truth for selectable runtime
// bodies. The processor reads from here when loading cartridge JSON.
//
// To ship a new body: bake its <base>.json into Assets (BinaryData symbol
// <base>_json) and add a row below. A user can also drop a
// Documents/TRENCH/bodies/<base>.cart.json (or <base>.json) to override or
// extend at runtime with no rebuild.
struct BodyEntry
{
    const char* displayName;
    const char* base; // e.g. "speaker_knockerz" -> resource "speaker_knockerz_json"
    const char* category;
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
inline constexpr int kNoFilterIndex = 0;
inline constexpr const char* kNoFilterName = "No Filter";

inline const BodyEntry* bodyRoster (int& countOut) noexcept
{
    static const BodyEntry entries[] = {
        // No Filter = filter 00 and boot default. It remains a normal
        // compiled-v1 packed-word cartridge so every roster row has the same
        // load contract. PluginProcessor bypasses the DSP island while this
        // row is selected, making the resting plug-in explicitly transparent.
        { kNoFilterName,        "bypass",             "SYSTEM" },

        // Keep the faceplate audition-first until a body earns a product slot
        // by ear. Stable/valid is not enough.
        { "Forge Audition",     kAuditionBase,        "SYSTEM" },

        { "Talking Mouth",      "v1_talking_mouth",   "VOWELS" },
        { "Vowel Shift",        "vowelshift",         "VOWELS" },
        { "Voice Walk",         "voice_walk",         "VOWELS" },
        { "Talkbox",            "talkbox",            "VOWELS" },

        { "Razor Shell",        "razor_shell_v1",     "CUTTERS" },
        { "Metal Scream",       "metal_scream",       "CUTTERS" },
        { "Needle Comb",        "v1_needle_comb",     "CUTTERS" },

        { "Hollow Chamber",     "hollow_chamber",     "SPACE" },
        { "Phaser Slide",       "phaser_slide",       "MOTION" },

        { "Knock Burst",        "knock_burst",        "IMPACT" },
        { "808 Tear",           "v1_808_tear",        "IMPACT" },
        { "Bass Sharpener",     "v1_bass_sharpener",  "IMPACT" },
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

inline bool bodyIsNoFilter (int index) noexcept
{
    return wrapBodyIndex (index) == kNoFilterIndex;
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
