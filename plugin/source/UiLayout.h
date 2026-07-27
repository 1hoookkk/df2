#pragma once
#include <juce_core/juce_core.h>
#include <juce_graphics/juce_graphics.h>
#include <map>
#include <optional>
#include <vector>
namespace trench
{
struct UiElementLayout
{
    juce::Rectangle<float> sourceRect;
    std::optional<float> fontSize;
    std::optional<juce::Colour> textColour;
    std::optional<juce::String> text;
    std::optional<float> opacity;
};
struct Decal
{
    juce::String type;
    juce::Rectangle<float> sourceRect;
    juce::String text;
    juce::Colour colour { juce::Colours::white };
    float fontSize = 12.0f;
    float thickness = 1.5f;
    bool fill = false;
};
class UiLayout
{
public:
    static UiLayout defaults()
    {
        UiLayout layout;
        layout.elements["morphWheel"]   = { { 115.0f, 680.0f, 428.0f, 92.0f }, {}, {} };
        layout.elements["qWheel"]       = { { 114.0f, 848.0f, 429.0f, 93.0f }, {}, {} };
        layout.elements["typeSelector"] = { { 230.0f, 139.0f, 675.0f, 68.0f },  {}, {} };
        layout.elements["morphReadout"] = { { 582.0f, 697.0f, 190.0f, 77.0f },  20.0f, juce::Colour (0xff2a2722) };
        layout.elements["qReadout"]     = { { 582.0f, 858.0f, 190.0f, 77.0f },  20.0f, juce::Colour (0xff2a2722) };
        layout.elements["spectrumGrid"] = { { 110.0f, 233.0f, 795.0f, 383.0f }, {}, {} };
        layout.elements["slotPad"]      = { { 699.0f, 240.0f, 112.0f, 26.0f }, {}, {} };
        layout.elements["modulateTag"]  = { { 149.0f, 456.0f, 430.0f, 56.0f }, {}, {} };
        layout.elements["fiveDTag"]     = { { 149.0f, 511.0f, 430.0f, 52.0f }, {}, {} };
        layout.elements["filterLabel"]  = { { 0.0f, 0.0f, 0.0f, 0.0f },  11.5f, juce::Colour (0xff3a2f22) };
        layout.elements["filterLabel"].text = "TRENCH";
        layout.elements["typeLabel"]    = { { 110.0f, 139.0f, 100.0f, 68.0f },  15.0f, juce::Colour (0xff2a2722) };
        layout.elements["typeLabel"].text = "BODY";
        layout.elements["typeName"]     = { { 244.0f, 143.0f, 530.0f, 64.0f },  18.0f, juce::Colour (0xff2a2722) };
        layout.elements["typeArrow"]    = { { 850.0f, 143.0f, 52.0f,  64.0f },  {}, {} };
        layout.elements["morphLabel"]   = { { 114.0f, 640.0f, 434.0f, 38.0f },  17.0f, juce::Colour (0xff2a2722) };
        layout.elements["morphLabel"].text = "MORPH";
        layout.elements["qLabel"]       = { { 114.0f, 798.0f, 434.0f, 38.0f },  17.0f, juce::Colour (0xff2a2722) };
        layout.elements["qLabel"].text = "Q";
        layout.elements["brandLabel"]   = { { 100.0f, 73.0f, 230.0f, 44.0f }, 18.5f, juce::Colour (0xff0f0c09) };
        layout.elements["brandLabel"].text = "TRENCH";
        layout.elements["amountLabel"] = { { 830.0f, 656.0f, 110.0f, 30.0f },
                                             16.0f, juce::Colour (0xff17130e) };
        layout.elements["amountLabel"].text = "MIX";
        layout.elements["amountWheel"] = { { 872.0f, 700.0f, 26.0f, 214.0f }, {}, {} };
        layout.colours["phosphor"]           = juce::Colour (0xff1b1715);
        layout.colours["labelInk"]    = juce::Colour (0xff24231f);
        applySkin (layout, 0);
        layout.params["wellRadius"]        = 9.0;
        layout.params["readoutAliasScale"] = 0.95;
        layout.params["typeArrowExtra"]    = 6.0;
        layout.params["curveDbTop"]        = 40.0;
        layout.params["curveDbBottom"]     = -40.0;
        layout.params["fontBold"]          = 1.0;
        layout.strings["fontFamily"] = "Arial";
        layout.strings["fontFamilyEmphasis"] = "Arial";
        return layout;
    }
    /// The two shipped faces. Skin 0 CORAL BOUTIQUE ships; skin 1 SAGE LCD
    /// rides along on the TRENCH badge. The signal family and the two baked
    /// bitmaps move together — nothing else on the face changes.
    static constexpr int kNumSkins = 2;
    static void applySkin (UiLayout& layout, int skin)
    {
        const bool sage = skin == 1;
        const auto trace     = sage ? juce::Colour (0xff1B4A5A) : juce::Colour (0xffFFB491);
        const auto highlight = sage ? juce::Colour (0xff2A5E6E) : juce::Colour (0xffFFD2BA);
        const auto lamp      = sage ? juce::Colour (0xff4a8f6a) : juce::Colour (0xffc96a54);
        const auto grid      = sage ? juce::Colour (0xffffffff) : juce::Colour (0xff4a6b69);
        layout.colours["accent"]             = trace;
        layout.colours["curveColour"]        = trace;
        layout.colours["amber"]              = trace;
        layout.colours["curveHighlight"]     = highlight;
        layout.colours["rollerIllumination"] = lamp;
        layout.colours["modulationLamp"]     = lamp;
        layout.colours["telemetry"]          = grid;
        layout.colours["dashed"]             = grid;
        layout.colours["screenEdge"]         = sage ? juce::Colour (0xff414c37)
                                                    : juce::Colour (0xff0a1c1e);
    }
    static UiLayout fromJson (const juce::String& jsonText)
    {
        UiLayout layout = defaults();
        const juce::var root = juce::JSON::parse (jsonText);
        auto* obj = root.getDynamicObject();
        if (obj == nullptr)
            return layout;
        auto hex = [] (const juce::var& v)
        { return juce::Colour ((juce::uint32) v.toString().getHexValue32()); };
        if (auto* els = obj->getProperty ("elements").getDynamicObject())
            for (auto& p : els->getProperties())
            {
                auto& el = layout.elements[p.name.toString()];
                if (auto* eo = p.value.getDynamicObject())
                {
                    if (auto* r = eo->getProperty ("rect").getArray(); r != nullptr && r->size() == 4)
                        el.sourceRect = { (float) (double) (*r)[0], (float) (double) (*r)[1],
                                          (float) (double) (*r)[2], (float) (double) (*r)[3] };
                    if (eo->hasProperty ("fontSize"))
                        el.fontSize = (float) (double) eo->getProperty ("fontSize");
                    if (eo->hasProperty ("textColor"))
                        el.textColour = hex (eo->getProperty ("textColor"));
                    if (eo->hasProperty ("text"))
                        el.text = eo->getProperty ("text").toString();
                    if (eo->hasProperty ("opacity"))
                        el.opacity = (float) (double) eo->getProperty ("opacity");
                }
            }
        if (auto* cols = obj->getProperty ("colours").getDynamicObject())
            for (auto& p : cols->getProperties())
                layout.colours[p.name.toString()] = hex (p.value);
        if (auto* pars = obj->getProperty ("params").getDynamicObject())
            for (auto& p : pars->getProperties())
                layout.params[p.name.toString()] = (double) p.value;
        if (auto* strs = obj->getProperty ("strings").getDynamicObject())
            for (auto& p : strs->getProperties())
                layout.strings[p.name.toString()] = p.value.toString();
        if (auto* arr = obj->getProperty ("decals").getArray())
        {
            layout.decals.clear();
            for (auto& dv : *arr)
                if (auto* d = dv.getDynamicObject())
                {
                    Decal dec;
                    dec.type = d->getProperty ("type").toString();
                    if (auto* r = d->getProperty ("rect").getArray(); r != nullptr && r->size() == 4)
                        dec.sourceRect = { (float) (double) (*r)[0], (float) (double) (*r)[1],
                                           (float) (double) (*r)[2], (float) (double) (*r)[3] };
                    dec.text = d->getProperty ("text").toString();
                    if (d->hasProperty ("color"))     dec.colour = hex (d->getProperty ("color"));
                    if (d->hasProperty ("colour"))    dec.colour = hex (d->getProperty ("colour"));
                    if (d->hasProperty ("fontSize"))  dec.fontSize  = (float) (double) d->getProperty ("fontSize");
                    if (d->hasProperty ("thickness")) dec.thickness = (float) (double) d->getProperty ("thickness");
                    if (d->hasProperty ("fill"))      dec.fill = (bool) d->getProperty ("fill");
                    layout.decals.push_back (dec);
                }
        }
        return layout;
    }
    juce::String toJson() const
    {
        auto* root = new juce::DynamicObject();
        auto* els = new juce::DynamicObject();
        for (const auto& e : elements)
        {
            auto* eo = new juce::DynamicObject();
            juce::Array<juce::var> rect;
            rect.add (e.second.sourceRect.getX());     rect.add (e.second.sourceRect.getY());
            rect.add (e.second.sourceRect.getWidth()); rect.add (e.second.sourceRect.getHeight());
            eo->setProperty ("rect", rect);
            if (e.second.fontSize)   eo->setProperty ("fontSize", *e.second.fontSize);
            if (e.second.textColour) eo->setProperty ("textColor", juce::String::toHexString ((int) e.second.textColour->getARGB()));
            if (e.second.text)       eo->setProperty ("text", *e.second.text);
            if (e.second.opacity)    eo->setProperty ("opacity", *e.second.opacity);
            els->setProperty (e.first, juce::var (eo));
        }
        root->setProperty ("elements", juce::var (els));
        auto* cols = new juce::DynamicObject();
        for (const auto& c : colours)
            cols->setProperty (c.first, juce::String::toHexString ((int) c.second.getARGB()));
        root->setProperty ("colours", juce::var (cols));
        auto* pars = new juce::DynamicObject();
        for (const auto& p : params)
            pars->setProperty (p.first, p.second);
        root->setProperty ("params", juce::var (pars));
        auto* strs = new juce::DynamicObject();
        for (const auto& s : strings)
            strs->setProperty (s.first, s.second);
        root->setProperty ("strings", juce::var (strs));
        return juce::JSON::toString (juce::var (root), false);
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
    juce::String textFor (const juce::String& id, const juce::String& fallback) const
    {
        const auto it = elements.find (id);
        return it != elements.end() && it->second.text ? *it->second.text : fallback;
    }
    float opacityFor (const juce::String& id) const
    {
        const auto it = elements.find (id);
        return it != elements.end() && it->second.opacity
                   ? juce::jlimit (0.0f, 1.0f, *it->second.opacity) : 1.0f;
    }
    juce::Colour colour (const juce::String& id, juce::Colour fallback) const
    {
        const auto it = colours.find (id);
        return it != colours.end() ? it->second : fallback;
    }
    double param (const juce::String& id, double fallback) const
    {
        const auto it = params.find (id);
        return it != params.end() ? it->second : fallback;
    }
    juce::String string (const juce::String& id, const juce::String& fallback) const
    {
        const auto it = strings.find (id);
        return it != strings.end() && it->second.isNotEmpty() ? it->second : fallback;
    }
    std::map<juce::String, UiElementLayout> elements;
    std::map<juce::String, juce::Colour> colours;
    std::map<juce::String, double> params;
    std::map<juce::String, juce::String> strings;
    std::vector<Decal> decals;
};
}
