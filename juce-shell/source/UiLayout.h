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
    juce::Rectangle<float> sourceRect; // 1024x1591 source space
    std::optional<float> fontSize;
    std::optional<juce::Colour> textColour;
    std::optional<juce::String> text;   // overrides a label's text string
    std::optional<float> opacity;       // 0..1 alpha multiplier on the element
};

// A free-form drawn element the layout can ADD (not just restyle existing ones):
// a text run, a filled/outlined rect, or a line — anywhere, any colour.
struct Decal
{
    juce::String type;                  // "text" | "rect" | "line"
    juce::Rectangle<float> sourceRect;  // x,y,w,h in source space (line: start->start+wh)
    juce::String text;
    juce::Colour colour { juce::Colours::white };
    float fontSize = 12.0f;
    float thickness = 1.5f;
    bool fill = false;
};

// Baked-in editor geometry / colour / scalar tokens. This was previously
// hot-reloaded from a ui_layout.json file to feed an external browser editor;
// that dev-tooling coupling has been removed. The values now live here as the
// single source of truth, read once when the editor is built.
class UiLayout
{
public:
    // Rects are in 1024x1591 panel-source space (mapped to 360x560 editor space
    // by Theme); scalars in `params` are editor-space; `colours` are AARRGGBB.
    static UiLayout defaults()
    {
        UiLayout layout;
        // ONE well law (2026-07-11, measured — the earlier floor/lip debates are
        // dead): every rect below is the recess MOUTH of the recut beige plate
        // (1010x1557), read as the contiguous lum<90 run through each well's
        // centre row/column. The art bakes floor + walls + bevel; components
        // mount their face AT the mouth (edge-to-edge, proportional corner
        // radius), wheels draw their 1:1 frame centred in it. Re-measure with
        // the same probe if the art ever changes; never hand-nudge.
        layout.elements["morphWheel"]   = { { 115.0f, 688.0f, 428.0f, 92.0f }, {}, {} };
        layout.elements["qWheel"]       = { { 114.0f, 869.0f, 429.0f, 93.0f }, {}, {} };
        // Window edges use the OUTERMOST wall extent (the recesses bow by a few
        // px along their length — a median rect leaves wall showing at the
        // bowed rows; "look at the preset on the right side").
        layout.elements["typeSelector"] = { { 218.0f, 129.0f, 676.0f, 77.0f },  {}, {} };
        layout.elements["morphReadout"] = { { 591.0f, 703.0f, 172.0f, 74.0f },  20.0f, juce::Colour (0xff2a2722) };
        layout.elements["qReadout"]     = { { 591.0f, 885.0f, 172.0f, 71.0f },  20.0f, juce::Colour (0xff2a2722) };
        layout.elements["spectrumGrid"] = { { 110.0f, 233.0f, 795.0f, 383.0f }, {}, {} }; // the screen opening
        layout.elements["slotPad"]      = { { 699.0f, 240.0f, 112.0f, 26.0f }, {}, {} }; // retired pager (hidden)
        layout.elements["modulateTag"]  = { { 149.0f, 456.0f, 430.0f, 56.0f }, {}, {} }; // clickable word on the glass
        layout.elements["fiveDTag"]     = { { 149.0f, 511.0f, 430.0f, 52.0f }, {}, {} }; // 5D switch (hidden in V1 face)
        layout.elements["filterLabel"]  = { { 0.0f, 0.0f, 0.0f, 0.0f },  11.5f, juce::Colour (0xff3a2f22) };
        layout.elements["filterLabel"].text = "TRENCH";   // hidden — the nameplate carries the identity
        // TYPE label rides close to the preset bar — near, not hugging.
        layout.elements["typeLabel"]    = { { 128.0f, 133.0f, 84.0f, 74.0f },  15.0f, juce::Colour (0xff2a2722) };
        layout.elements["typeLabel"].text = "TYPE";
        layout.elements["typeName"]     = { { 244.0f, 127.0f, 530.0f, 79.0f },  18.0f, juce::Colour (0xff2a2722) };
        layout.elements["typeArrow"]    = { { 838.0f, 127.0f, 56.0f,  79.0f },  {}, {} }; // dropdown arrow box (the bar's divided end segment)
        // Rail labels: the SAME measured vertical gap above each wheel well;
        // darker engraved ink, MORPH clear of the display bezel.
        layout.elements["morphLabel"]   = { { 114.0f, 640.0f, 434.0f, 38.0f },  15.5f, juce::Colour (0xff2a2722) };
        layout.elements["morphLabel"].text = "MORPH";
        layout.elements["qLabel"]       = { { 114.0f, 822.0f, 434.0f, 38.0f },  15.5f, juce::Colour (0xff2a2722) };
        layout.elements["qLabel"].text = "Q";
        // TRENCH top-left, seated just above the TYPE row like the X3's FILTER
        // badge — part of the content, not floating at the plate rim. No
        // sub-line anywhere ("MUSICAL FILTER" read as a second product name).
        layout.elements["brandLabel"]   = { { 114.0f, 84.0f, 230.0f, 40.0f }, 16.5f, juce::Colour (0xff2a2722) };
        layout.elements["brandLabel"].text = "TRENCH";

        // Grounded 60:30:10: WARM PUTTY / ESPRESSO CHARCOAL / MALACHITE.
        // Saturation supplies impact; nothing is neon or blue-lit.
        layout.colours["accent"]      = juce::Colour (0xff4f8f70); // oxidised malachite
        layout.colours["curveColour"] = juce::Colour (0xff79a98b); // faded green phosphor
        layout.colours["phosphor"]    = juce::Colour (0xff26231f); // espresso glass
        layout.colours["amber"]       = juce::Colour (0xff3e8060); // legacy token name: malachite core
        layout.colours["dashed"]      = juce::Colour (0xff4a4640); // warm charcoal grid
        layout.colours["screenEdge"]  = juce::Colour (0xff151311); // espresso keyline
        layout.colours["labelInk"]    = juce::Colour (0xff2a2722); // warm charcoal type

        layout.params["wellRadius"]        = 9.0;
        layout.params["readoutAliasScale"] = 0.85; // crisper on the dark LED box
        layout.params["typeArrowExtra"]    = 6.0;
        layout.params["curveDbTop"]        = 40.0;   // keep high-Q bodies inside the hardware display
        layout.params["curveDbBottom"]     = -40.0;
        layout.params["fontBold"]          = 0.0;    // named weights only; no synthetic Impact-like bold

        // Gill Sans is the strategic counterweight to the distressed machine:
        // humanist, editorial and readable, without poster-grotesk severity.
        layout.strings["fontFamily"] = "Gill Sans MT";
        layout.strings["fontFamilyEmphasis"] = "Gill Sans MT";
        return layout;
    }

    // Overlay a ui_layout.json document onto the baked defaults. Schema:
    //   {"elements":{"<id>":{"rect":[x,y,w,h],"fontSize":N?,"textColor":"AARRGGBB"?}},
    //    "colours":{"<name>":"AARRGGBB"}, "params":{"<name>":number}}
    // Missing keys keep their default. The "See Your Plugin" hot-reload bridge;
    // only read when TRENCH_PLAYER_DIAGNOSTICS is compiled in.
    static UiLayout fromJson (const juce::String& jsonText)
    {
        UiLayout layout = defaults();
        // Keep the parsed var alive for the whole function — getDynamicObject()
        // returns a pointer INTO it, so a temporary here would dangle and every
        // lookup below would read freed memory (silently falling back to defaults).
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

        // Free decals — the layout can add its own drawn elements.
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

    // Serialize the current layout to the ui_layout.json schema fromJson() reads, so
    // the editor can drop a hand-editable starting file (the See Your Plugin bridge).
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

} // namespace trench
