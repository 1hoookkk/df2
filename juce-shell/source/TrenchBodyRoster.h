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
        // Bypass = boot default. Pure-identity biquads (b0=1, all others 0)
        // across every stage of every corner. Silence in -> silence out by
        // construction, so a fresh plug-in does not amplify the host's noise
        // floor through Neon Vane's +20..+28 dB resonance into the AGC
        // engagement zone. Author a real body strip click to leave Bypass.
        { "Bypass",         "bypass"      },
        // Neon Vane = first character body. Was the boot default until the
        // AGC-engagement diagnosis above moved it down a slot.
        { "Neon Vane",      "neon_vane"   },
        // Razor Shell — first body from the filter-type-card system
        // (make_class_bodies, class EQ_CUT/PHASER). Generated, gate-clean.
        { "Razor Shell",    "razor_shell_v1" },
        // === V1 ORIGINALS (this session) ===
        // 7 generated originals spanning the design space. All structural intent
        // (no random pole placement). Clean-room: no legacy preset names copied.
        { "Voice Walk",     "voice_walk"  },   // Klatt vowel formant morph
        { "Mason Tube",     "mason_tube"  },   // physical Helmholtz cavity
        { "Knock Burst",    "knock_burst" },   // 808 knock + grit, sub-safe
        { "Metal Scream",   "metal_scream"},   // resonant modal cluster
        { "Phaser Slide",   "phaser_slide"},   // chambered phaser comb
        { "Cut Edge",       "cut_edge"    },   // single-tear razor
        { "Maul",           "maul"        },   // direct-biquad insane, AGC-driven
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
        // Keeper 04 — midpoint-search outlier Tyson kept (no-pedestal + stable
        // gated; renders peak 0.980 / 0 unstable rows). Placeholder name; wants a
        // material name (Glass Throat / Rust Choir style) when one's chosen.
        { "Keeper 04",      "keeper_04"   },
        // ROM audition set — the 33 stable-decoding E-mu P2K bodies (real, complex
        // tells). For auditioning by ear + reading their magnitude shape; cull to
        // keepers, not the final ship list.
        { "Ace Of Bass",    "P2k_000_ace_of_bass"     },
        { "Megasweepz",     "P2k_001_megasweepz"      },
        { "Early Rizer",    "P2k_002_early_rizer"     },
        { "Millennium",     "P2k_003_millennium"      },
        { "Meaty Gizmo",    "P2k_004_meaty_gizmo"     },
        { "Klub Klassik",   "P2k_005_klub_klassik"    },
        { "BassBox 303",    "P2k_006_bassbox_303"     },
        { "Fuzzi Face",     "P2k_007_fuzzi_face"      },
        { "Dead Ringer",    "P2k_008_dead_ringer"     },
        { "TB or Not TB",   "P2k_009_tb_or_not_tb"    },
        { "Ooh to Eee",     "P2k_010_ooh_to_eee"      },
        { "Boland Bass",    "P2k_011_boland_bass"     },
        { "Multi Q Vox",    "P2k_012_multi_q_vox"     },
        { "Talking Hedz",   "P2k_013_talking_hedz"    },
        { "Zoom Peaks",     "P2k_014_zoom_peaks"      },
        { "DJ Alkaline",    "P2k_015_dj_alkaline"     },
        { "Bass Tracer",    "P2k_016_bass_tracer"     },
        { "Rogue Hertz",    "P2k_017_rogue_hertz"     },
        { "Razor Blades",   "P2k_018_razor_blades"    },
        { "Radio Craze",    "P2k_019_radio_craze"     },
        { "Eeh to Aah",     "P2k_020_eeh_to_aah"      },
        { "Ubu Orator",     "P2k_021_ubu_orator"      },
        { "Deep Bouche",    "P2k_022_deep_bouche"     },
        { "Freak Shifta",   "P2k_023_freak_shifta"    },
        { "Cruz Pusher",    "P2k_024_cruz_pusher"     },
        { "Angelz Hairz",   "P2k_025_angelz_hairz"    },
        { "Dream Weava",    "P2k_026_dream_weava"     },
        { "Acid Ravage",    "P2k_027_acid_ravage"     },
        { "Bass-O-Matic",   "P2k_028_bass_o_matic"    },
        { "Lucifer's Q",    "P2k_029_lucifer_s_q"     },
        { "Tooth Comb",     "P2k_030_tooth_comb"      },
        { "Ear Bender",     "P2k_031_ear_bender"      },
        { "Klang Kling",    "P2k_032_klang_kling"     },
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
