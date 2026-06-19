#pragma once

#include <juce_core/juce_core.h>
#include <juce_graphics/juce_graphics.h>

#include <cmath>
#include <map>
#include <optional>

namespace trench
{

struct UiElementLayout
{
    juce::Rectangle<float> sourceRect; // 1024x1591 source space
    std::optional<float> fontSize;
    std::optional<juce::Colour> textColour;
};

class UiLayout
{
public:
    // Mirrors the rects previously hardcoded in PluginEditor.cpp.
    static UiLayout defaults()
    {
        UiLayout layout;
        layout.elements["morphWheel"]   = { { 127.0f, 694.0f, 423.0f, 101.0f }, {}, {} };
        layout.elements["qWheel"]       = { { 127.0f, 871.0f, 423.0f, 101.0f }, {}, {} };
        layout.elements["typeSelector"] = { { 230.0f, 142.0f, 672.0f, 73.0f },  {}, {} };
        layout.elements["morphReadout"] = { { 603.0f, 712.0f, 168.0f, 77.0f },  {}, {} };
        layout.elements["qReadout"]     = { { 602.0f, 889.0f, 169.0f, 79.0f },  {}, {} };
        return layout;
    }

    juce::Rectangle<float> sourceRectFor (const juce::String& id,
                                          juce::Rectangle<float> fallback = {}) const
    {
        const auto it = elements.find (id);
        return it != elements.end() ? it->second.sourceRect : fallback;
    }

    std::optional<float> fontSizeFor (const juce::String& id) const
    {
        const auto it = elements.find (id);
        return it != elements.end() ? it->second.fontSize : std::nullopt;
    }

    std::optional<juce::Colour> textColourFor (const juce::String& id) const
    {
        const auto it = elements.find (id);
        return it != elements.end() ? it->second.textColour : std::nullopt;
    }

    // Starts from fallback and overrides only valid known element fields.
    static UiLayout fromJson (const juce::var& json, const UiLayout& fallback)
    {
        if (! json.isObject())
            return fallback;

        if ((int) json.getProperty ("version", juce::var()) != 1)
            return fallback;

        UiLayout result = fallback;
        const auto elementsVar = json.getProperty ("elements", juce::var());
        if (auto* obj = elementsVar.getDynamicObject())
        {
            for (const auto& [key, value] : obj->getProperties())
            {
                const juce::String id = key.toString();
                const auto it = result.elements.find (id);
                if (it == result.elements.end())
                    continue;

                applyElement (it->second, value);
            }
        }

        return result;
    }

    // Serialize to the ui_layout.json shape (rect always; style only when set).
    juce::String toJsonString() const
    {
        auto* root = new juce::DynamicObject();
        root->setProperty ("version", 1);

        juce::Array<juce::var> space;
        space.add (1024);
        space.add (1591);
        root->setProperty ("sourceSpace", space);

        auto* elementsObj = new juce::DynamicObject();
        for (const auto& [id, element] : elements)
        {
            auto* e = new juce::DynamicObject();

            juce::Array<juce::var> rect;
            rect.add (element.sourceRect.getX());
            rect.add (element.sourceRect.getY());
            rect.add (element.sourceRect.getWidth());
            rect.add (element.sourceRect.getHeight());
            e->setProperty ("rect", rect);

            if (element.fontSize)
                e->setProperty ("fontSize", *element.fontSize);
            if (element.textColour)
                e->setProperty ("textColor", element.textColour->toDisplayString (true));

            elementsObj->setProperty (id, juce::var (e));
        }
        root->setProperty ("elements", juce::var (elementsObj));

        return juce::JSON::toString (juce::var (root));
    }

    std::map<juce::String, UiElementLayout> elements;

private:
    static void applyElement (UiElementLayout& target, const juce::var& elementVar)
    {
        if (! elementVar.isObject())
            return;

        if (auto rect = parseRect (elementVar.getProperty ("rect", juce::var())))
            target.sourceRect = *rect;

        const auto fs = elementVar.getProperty ("fontSize", juce::var());
        if (fs.isDouble() || fs.isInt())
        {
            const auto value = (float) fs;
            if (std::isfinite (value) && value > 0.0f)
                target.fontSize = value;
        }

        const auto tc = elementVar.getProperty ("textColor", juce::var());
        if (tc.isString())
            if (auto colour = parseColour (tc.toString()))
                target.textColour = *colour;
    }

    static std::optional<juce::Rectangle<float>> parseRect (const juce::var& rectVar)
    {
        const auto* arr = rectVar.getArray();
        if (arr == nullptr || arr->size() != 4)
            return std::nullopt;

        float values[4] {};
        for (int i = 0; i < 4; ++i)
        {
            const auto& element = (*arr)[i];
            if (! (element.isDouble() || element.isInt()))
                return std::nullopt;

            values[i] = (float) element;
            if (! std::isfinite (values[i]))
                return std::nullopt;
        }

        if (values[2] <= 0.0f || values[3] <= 0.0f)
            return std::nullopt;

        return juce::Rectangle<float> { values[0], values[1], values[2], values[3] };
    }

    static std::optional<juce::Colour> parseColour (const juce::String& hex)
    {
        const auto trimmed = hex.trim();
        if (trimmed.isEmpty() || trimmed.length() > 8)
            return std::nullopt;

        if (! trimmed.containsOnly ("0123456789abcdefABCDEF"))
            return std::nullopt;

        return juce::Colour ((juce::uint32) trimmed.getHexValue64());
    }
};

inline juce::File uiLayoutFile()
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
               .getChildFile ("TRENCH")
               .getChildFile ("ui_layout.json");
}

inline UiLayout loadUiLayoutFromFile (const juce::File& file)
{
    const auto defaults = UiLayout::defaults();
    if (! file.existsAsFile())
        return defaults;

    return UiLayout::fromJson (juce::JSON::parse (file.loadFileAsString()), defaults);
}

inline UiLayout loadUiLayoutOrDefaults()
{
    return loadUiLayoutFromFile (uiLayoutFile());
}

// Writes a defaults layout file if none exists yet, so the user always has a
// file to edit. Best-effort: never overwrites an existing (edited) file, and a
// failed write (e.g. permissions) is silently tolerated — callers fall back to
// in-memory defaults via loadUiLayoutOrDefaults().
inline void ensureUiLayoutFileExists (const juce::File& file)
{
    if (file.existsAsFile())
        return;

    file.getParentDirectory().createDirectory();
    file.replaceWithText (UiLayout::defaults().toJsonString());
}

} // namespace trench
