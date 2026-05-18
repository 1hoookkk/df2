#pragma once

#include "BinaryData.h"

#include <juce_gui_basics/juce_gui_basics.h>
#include <juce_data_structures/juce_data_structures.h>

// Runtime-mutable layout for the DF-II UI.
//
// Two-stage indirection:
//   1. assets/runtime_layout.json holds `{ "active": "<variant_name>" }`.
//   2. The active variant's coords come from
//      source/Assets/chassis_variants/<name>.layout.json, baked into BinaryData.
//      The locked v1 chassis is assets/images/chassis.png and uses the defaults
//      below when no chassis.layout.json exists.
//
// Switching chassis = editing the one-line `runtime_layout.json` in place.
// The file watcher in PluginEditor picks up the change within 200ms, re-loads
// the variant, re-reads its layout, re-locks aspect ratio, repaints.
//
// Each variant carries its own chassis.width/height and per-region coords in
// THAT chassis's source-pixel space. Different variants can be different
// sizes and still place their knobs/display correctly.

namespace trench::layout
{
    struct State
    {
        juce::String activeName  { "chassis" };
        int chassisW = 1037;
        int chassisH = 1517;
        // Rects in the active chassis's source-pixel space (locked chassis = 1037 x 1517).
        // Each rect covers the matching window in chassis.png (with ~2px bleed).
        juce::Rectangle<int> typeRect_    { 200,  157, 708,  55 };
        juce::Rectangle<int> displayRect_ {  89,  271, 846, 509 };
        juce::Rectangle<int> morphRect_   { 121,  950, 491,  64 };
        juce::Rectangle<int> valueRect_   { 692,  950, 152,  64 };
        juce::Rectangle<int> qRect_       { 121, 1109, 492,  62 };
        juce::Rectangle<int> qValueRect_  { 692, 1109, 152,  62 };
    };

    inline State& state()
    {
        static State s;
        return s;
    }

    inline void applyLockedChassisDefaults()
    {
        auto& s = state();
        s.chassisW = 1037;
        s.chassisH = 1517;
        s.typeRect_    = { 200,  157, 708,  55 };
        s.displayRect_ = {  89,  271, 846, 509 };
        s.morphRect_   = { 121,  950, 491,  64 };
        s.valueRect_   = { 692,  950, 152,  64 };
        s.qRect_       = { 121, 1109, 492,  62 };
        s.qValueRect_  = { 692, 1109, 152,  62 };
    }

    // Documents/TRENCH/ — user-local live override directory. Drop variants
    // here to test in any DAW without rebuilding. Auto-created on first launch.
    inline juce::File devUserDir()
    {
        return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
                          .getChildFile ("TRENCH");
    }

    inline juce::File devVariantsDir()
    {
        return devUserDir().getChildFile ("chassis_variants");
    }

    inline void ensureDevDirs()
    {
        devUserDir().createDirectory();
        devVariantsDir().createDirectory();
        // Seed Documents/TRENCH/runtime_layout.json on first launch so the
        // user has a known place to edit "active" without hunting for the
        // source tree. Only created if it doesn't already exist.
        const auto seed = devUserDir().getChildFile ("runtime_layout.json");
        if (! seed.existsAsFile())
            seed.replaceWithText ("{ \"active\": \"chassis\" }\n");

        const auto variantSeed = devVariantsDir().getChildFile ("df2_musical_filter.layout.json");
        if (! variantSeed.existsAsFile())
        {
            variantSeed.replaceWithText (R"json({
  "schema": 1,
  "chassis": { "width": 1037, "height": 1517 },
  "regions": {
    "type":   { "x": 209, "y": 161,  "w": 686, "h": 41 },
    "morph":  { "x": 123, "y": 948,  "w": 622, "h": 61 },
    "value":  { "x": 820, "y": 947,  "w": 103, "h": 62 },
    "q":      { "x": 123, "y": 1120, "w": 622, "h": 63 },
    "qValue": { "x": 820, "y": 1119, "w": 103, "h": 65 }
  }
}
)json");
        }
    }

    // Walk up from the executable looking for the source-tree's
    // assets/runtime_layout.json. Works for the dev standalone build (EXE is
    // inside juce-shell/build/...) but not for a VST3 hosted by a DAW.
    inline juce::File findSourceTreeRuntimeJson()
    {
        auto cur = juce::File::getSpecialLocation (juce::File::currentExecutableFile)
                              .getParentDirectory();
        for (int i = 0; i < 10 && cur.exists(); ++i)
        {
            auto candidate = cur.getChildFile ("assets").getChildFile ("runtime_layout.json");
            if (candidate.existsAsFile()) return candidate;
            cur = cur.getParentDirectory();
        }
        return {};
    }

    inline juce::File findSourceTreeVariantsDir()
    {
        auto cur = juce::File::getSpecialLocation (juce::File::currentExecutableFile)
                              .getParentDirectory();
        for (int i = 0; i < 10 && cur.exists(); ++i)
        {
            auto candidate = cur.getChildFile ("source").getChildFile ("Assets").getChildFile ("chassis_variants");
            if (candidate.isDirectory()) return candidate;
            cur = cur.getParentDirectory();
        }
        return {};
    }

    inline juce::File findSourceTreeImagesDir()
    {
        auto cur = juce::File::getSpecialLocation (juce::File::currentExecutableFile)
                              .getParentDirectory();
        for (int i = 0; i < 10 && cur.exists(); ++i)
        {
            auto candidate = cur.getChildFile ("assets").getChildFile ("images");
            if (candidate.isDirectory()) return candidate;
            cur = cur.getParentDirectory();
        }
        return {};
    }

    // Priority: Documents/TRENCH/runtime_layout.json (user override, works
    // anywhere) → source-tree assets/runtime_layout.json (dev standalone) →
    // empty (caller falls back to BinaryData baked default).
    inline juce::File findRuntimeJson()
    {
        const auto dev = devUserDir().getChildFile ("runtime_layout.json");
        if (dev.existsAsFile()) return dev;
        return findSourceTreeRuntimeJson();
    }

    // Resolve a variant file by name. Same priority chain as runtime_layout:
    // Documents override first, source tree second, empty if neither.
    inline juce::File findVariantFile (const juce::String& name, const juce::String& ext)
    {
        const auto fname = name + ext;
        const auto dev = devVariantsDir().getChildFile (fname);
        if (dev.existsAsFile()) return dev;
        const auto srcDir = findSourceTreeVariantsDir();
        if (srcDir.isDirectory())
        {
            auto candidate = srcDir.getChildFile (fname);
            if (candidate.existsAsFile()) return candidate;
        }
        if (ext == ".png")
        {
            const auto imgDir = findSourceTreeImagesDir();
            if (imgDir.isDirectory())
            {
                auto candidate = imgDir.getChildFile (fname);
                if (candidate.existsAsFile()) return candidate;
            }
        }
        return {};
    }

    // Look up a baked resource by its original filename (case-insensitive).
    inline const char* findBinaryResource (const juce::String& filename, int& dataSize)
    {
        for (int i = 0; i < BinaryData::namedResourceListSize; ++i)
        {
            if (juce::String (BinaryData::originalFilenames[i]).equalsIgnoreCase (filename))
                return BinaryData::getNamedResource (BinaryData::namedResourceList[i], dataSize);
        }
        dataSize = 0;
        return nullptr;
    }

    // Apply a variant layout JSON (chassis.width/height + regions). Returns
    // false on malformed input — state untouched in that case, defaults stay.
    inline bool applyVariantJson (const juce::var& json)
    {
        if (! json.isObject()) return false;
        auto& s = state();

        auto geti = [] (const juce::var& v, const char* key, int dflt)
        {
            if (! v.hasProperty (key)) return dflt;
            return (int) (double) v.getProperty (key, dflt);
        };

        if (auto chassis = json.getProperty ("chassis", juce::var()); chassis.isObject())
        {
            s.chassisW = geti (chassis, "width",  s.chassisW);
            s.chassisH = geti (chassis, "height", s.chassisH);
        }

        if (auto regions = json.getProperty ("regions", juce::var()); regions.isObject())
        {
            s.typeRect_ = {};
            s.displayRect_ = {};
            s.morphRect_ = {};
            s.valueRect_ = {};
            s.qRect_ = {};
            s.qValueRect_ = {};

            // Helper: accept either rect {x,y,w,h} or circle {cx,cy,r}.
            // Circles convert to bounding squares centered at (cx,cy).
            auto readRect = [&] (const juce::var& v, juce::Rectangle<int>& target)
            {
                if (! v.isObject()) return;
                if (v.hasProperty ("x"))
                {
                    target = juce::Rectangle<int> (
                        geti (v, "x", target.getX()),
                        geti (v, "y", target.getY()),
                        geti (v, "w", target.getWidth()),
                        geti (v, "h", target.getHeight()));
                }
                else if (v.hasProperty ("cx"))
                {
                    const int cx = geti (v, "cx", target.getCentreX());
                    const int cy = geti (v, "cy", target.getCentreY());
                    const int r  = geti (v, "r",  target.getWidth() / 2);
                    target = juce::Rectangle<int> (cx - r, cy - r, 2 * r, 2 * r);
                }
            };
            readRect (regions.getProperty ("morph",   juce::var()), s.morphRect_);
            readRect (regions.getProperty ("q",       juce::var()), s.qRect_);
            readRect (regions.getProperty ("type",    juce::var()), s.typeRect_);
            readRect (regions.getProperty ("display", juce::var()), s.displayRect_);
            readRect (regions.getProperty ("value",   juce::var()), s.valueRect_);
            readRect (regions.getProperty ("qValue",  juce::var()), s.qValueRect_);
        }
        return true;
    }

    inline juce::Image loadPngByName (const juce::String& name)
    {
        const auto diskPng = findVariantFile (name, ".png");
        if (diskPng.existsAsFile())
            return juce::ImageFileFormat::loadFrom (diskPng);

        int sz = 0;
        if (auto* data = findBinaryResource (name + ".png", sz))
            return juce::ImageFileFormat::loadFrom (data, (size_t) sz);

        return {};
    }

    // Returns true if a PNG exists for this variant name (any source).
    inline bool variantPngExists (const juce::String& name)
    {
        return loadPngByName (name).isValid();
    }

    // Load a variant's layout.json by name. Filesystem first (Documents →
    // source tree), BinaryData fallback.
    // If no layout.json exists but a PNG does, accepts the variant using the
    // current coords — drop any PNG in to preview it immediately.
    inline bool loadVariantByName (const juce::String& name)
    {
        // Filesystem-first
        const auto diskJson = findVariantFile (name, ".layout.json");
        if (diskJson.existsAsFile())
        {
            const auto json = juce::JSON::parse (diskJson);
            if (applyVariantJson (json))
            {
                state().activeName = name;
                return true;
            }
        }
        // BinaryData fallback
        int sz = 0;
        if (auto* data = findBinaryResource (name + ".layout.json", sz))
        {
            const auto json = juce::JSON::parse (juce::String::fromUTF8 (data, sz));
            if (applyVariantJson (json))
            {
                state().activeName = name;
                return true;
            }
        }
        // No layout.json — accept if PNG exists, keep current coords.
        if (auto img = loadPngByName (name); img.isValid())
        {
            if (name.equalsIgnoreCase ("chassis"))
                applyLockedChassisDefaults();

            state().activeName = name;
            state().chassisW = img.getWidth();
            state().chassisH = img.getHeight();
            return true;
        }
        return false;
    }

    // Read the runtime_layout.json (filesystem first, BinaryData fallback),
    // pull the "active" field, and swap to that variant. Returns true on
    // successful swap, false on parse failure or unknown variant.
    inline bool reloadActive (const juce::File& runtimeJsonFile)
    {
        juce::String text;
        if (runtimeJsonFile.existsAsFile())
        {
            text = runtimeJsonFile.loadFileAsString();
        }
        else
        {
            int sz = 0;
            if (auto* data = findBinaryResource ("runtime_layout.json", sz))
                text = juce::String::fromUTF8 (data, sz);
        }

        const auto json = juce::JSON::parse (text);
        if (! json.isObject()) return false;
        const auto name = json.getProperty ("active", state().activeName).toString();
        if (name.isEmpty()) return false;

        return loadVariantByName (name);
    }

    inline int   chassisWidth()  noexcept { return state().chassisW; }
    inline int   chassisHeight() noexcept { return state().chassisH; }
    inline float aspectRatio()   noexcept
    {
        return (float) state().chassisW / (float) state().chassisH;
    }
    inline const juce::String& activeName() noexcept { return state().activeName; }

    inline float scale (int editorW, int editorH) noexcept
    {
        const auto& s = state();
        const float sx = (float) editorW / (float) s.chassisW;
        const float sy = (float) editorH / (float) s.chassisH;
        return 0.5f * (sx + sy);
    }

    inline juce::Rectangle<int> rectBounds (const juce::Rectangle<int>& src, int editorW, int editorH)
    {
        const auto k = scale (editorW, editorH);
        const auto r = src.toFloat();
        return juce::Rectangle<float> (r.getX() * k, r.getY() * k,
                                       r.getWidth() * k, r.getHeight() * k)
                   .toNearestInt();
    }

    inline juce::Rectangle<int> morphBounds   (int editorW, int editorH) { return rectBounds (state().morphRect_,   editorW, editorH); }
    inline juce::Rectangle<int> qBounds       (int editorW, int editorH) { return rectBounds (state().qRect_,       editorW, editorH); }
    inline juce::Rectangle<int> typeBounds    (int editorW, int editorH) { return rectBounds (state().typeRect_,    editorW, editorH); }
    inline juce::Rectangle<int> displayBounds (int editorW, int editorH) { return rectBounds (state().displayRect_, editorW, editorH); }
    inline juce::Rectangle<int> valueBounds (int editorW, int editorH) { return rectBounds (state().valueRect_, editorW, editorH); }
    inline juce::Rectangle<int> qValueBounds (int editorW, int editorH) { return rectBounds (state().qValueRect_, editorW, editorH); }

    inline juce::Image flattenOnBlack (const juce::Image& image)
    {
        return image;
    }

    // Load the chassis PNG by active name. Filesystem first (Documents →
    // source tree), BinaryData fallback. Returns empty Image if not found.
    inline juce::Image loadActiveChassisImage()
    {
        return flattenOnBlack (loadPngByName (state().activeName));
    }

    // Enumerate every variant the plugin can load. Dedups across the three
    // sources (Documents → source tree → BinaryData) by name.
    // A variant only needs a PNG — no layout.json required to appear in the list.
    inline juce::StringArray listAvailableVariants()
    {
        juce::StringArray names;
        auto addFile = [&names] (const juce::String& filename)
        {
            juce::String name;
            if (filename.endsWithIgnoreCase (".layout.json"))
                name = filename.dropLastCharacters (juce::String (".layout.json").length());
            else if (filename.endsWithIgnoreCase (".png"))
                name = filename.dropLastCharacters (4);
            if (name.isNotEmpty()) names.addIfNotAlreadyThere (name);
        };

        for (auto& f : devVariantsDir().findChildFiles (juce::File::findFiles, false, "*"))
            addFile (f.getFileName());

        if (auto src = findSourceTreeVariantsDir(); src.isDirectory())
            for (auto& f : src.findChildFiles (juce::File::findFiles, false, "*"))
                addFile (f.getFileName());

        for (int i = 0; i < BinaryData::namedResourceListSize; ++i)
            addFile (juce::String (BinaryData::originalFilenames[i]));

        names.sortNatural();
        return names;
    }

    // Persist the active variant into Documents/TRENCH/runtime_layout.json so
    // it sticks across plugin instances and is what the file-watcher reads.
    inline juce::File writeActive (const juce::String& name)
    {
        ensureDevDirs();
        const auto target = devUserDir().getChildFile ("runtime_layout.json");
        target.replaceWithText ("{ \"active\": \"" + name + "\" }\n");
        return target;
    }
}
