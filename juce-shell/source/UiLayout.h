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
        // Wells measured from the recut BEIGE plate (df2_panel_beige.png,
        // 1010x1557 — connected-component bounds at lum<90, measured
        // 2026-07-11). GROUND TRUTH — each control fills its dark opening; the
        // art's bevel just outside stays as the edge. Do not hand-nudge;
        // re-measure if the art changes. Roller wells are TIGHT (X3 sit): the
        // wheel frame draws 1:1 and overhangs the black opening inside this rect.
        // Wheels: lum<90 rect (opening + lip) — the 1:1 frame overhangs the black
        // opening inside it. Window components (TYPE, readouts): the PURE-BLACK
        // opening (lum<12) — their faces fill the hole and the art's bevel frames
        // them; giving them the lip rect makes them paint OVER the bevel and float.
        layout.elements["morphWheel"]   = { { 114.0f, 684.0f, 434.0f, 98.0f }, {}, {} };
        layout.elements["qWheel"]       = { { 114.0f, 866.0f, 434.0f, 98.0f }, {}, {} };
        // Windows pin the PURE-BLACK openings exactly, and the views draw their
        // faces edge-to-edge (no internal insets) — the face IS the opening,
        // the art's bevel is the frame. (Third fit iteration: adjusting rects
        // around baked insets was the wrong method.)
        layout.elements["typeSelector"] = { { 226.0f, 139.0f, 663.0f, 66.0f },  {}, {} };
        layout.elements["morphReadout"] = { { 595.0f, 709.0f, 165.0f, 67.0f },  14.5f, juce::Colours::black };
        layout.elements["qReadout"]     = { { 593.0f, 891.0f, 166.0f, 64.0f },  14.5f, juce::Colours::black };
        layout.elements["spectrumGrid"] = { { 110.0f, 233.0f, 795.0f, 383.0f }, {}, {} }; // the screen opening
        layout.elements["slotPad"]      = { { 699.0f, 240.0f, 112.0f, 26.0f }, {}, {} }; // retired pager (hidden)
        layout.elements["modulateTag"]  = { { 149.0f, 456.0f, 430.0f, 56.0f }, {}, {} }; // clickable word on the glass
        layout.elements["fiveDTag"]     = { { 149.0f, 511.0f, 430.0f, 52.0f }, {}, {} }; // 5D switch (hidden in V1 face)
        layout.elements["filterLabel"]  = { { 0.0f, 0.0f, 0.0f, 0.0f },  11.5f, juce::Colour (0xff3a2f22) };
        layout.elements["filterLabel"].text = "TRENCH";   // hidden — the nameplate carries the identity
        // TYPE label rides close to the preset bar — near, not hugging.
        layout.elements["typeLabel"]    = { { 128.0f, 133.0f, 84.0f, 74.0f },  13.5f, juce::Colour (0xff21180f) };
        layout.elements["typeLabel"].text = "TYPE";
        layout.elements["typeName"]     = { { 244.0f, 127.0f, 530.0f, 79.0f },  12.5f, juce::Colours::black };
        layout.elements["typeArrow"]    = { { 838.0f, 127.0f, 56.0f,  79.0f },  {}, {} }; // dropdown arrow box (the bar's divided end segment)
        // Rail labels: the SAME measured vertical gap above each wheel well;
        // darker engraved ink, MORPH clear of the display bezel.
        layout.elements["morphLabel"]   = { { 114.0f, 640.0f, 434.0f, 38.0f },  14.0f, juce::Colour (0xff170f08) };
        layout.elements["morphLabel"].text = "MORPH";
        layout.elements["qLabel"]       = { { 114.0f, 822.0f, 434.0f, 38.0f },  14.0f, juce::Colour (0xff170f08) };
        layout.elements["qLabel"].text = "Q";
        // TRENCH alone in the top-left corner; MUSICAL FILTER is a real punched
        // Dymo tape label stuck on the bare lower body (Tyson's asset,
        // 2026-07-11) — drawn by FaceplateView, slightly crooked like real tape.
        layout.elements["brandLabel"]   = { { 114.0f, 58.0f, 230.0f, 40.0f }, 11.5f, juce::Colour (0xff41362a) };
        layout.elements["brandLabel"].text = "TRENCH";
        layout.elements["brandTape"]    = { { 330.0f, 1228.0f, 340.0f, 113.0f }, {}, {} };

        // COBALT scheme (2026-07-11, Tyson's call: "Try: cobalt"): SAND plate
        // (locked art) / cool GRAPHITE darks / ELECTRIC COBALT as the ONLY lit
        // family. Grid lines visible on the glass, never buried.
        layout.colours["accent"]      = juce::Colour (0xff7da4ff); // cobalt trace / active text
        layout.colours["curveColour"] = juce::Colour (0xff7da4ff);
        layout.colours["phosphor"]    = juce::Colour (0xff26262a); // cool dark glass base (graphite family)
        layout.colours["amber"]       = juce::Colour (0xff2a5cff); // legacy token name: the hot glow core
        layout.colours["dashed"]      = juce::Colour (0xff33333a); // cool graphite grid — VISIBLE
        layout.colours["screenEdge"]  = juce::Colour (0xff131318); // deep glass keyline
        layout.colours["labelInk"]    = juce::Colour (0xff29251f); // warm near-black charcoal ink (plate family)

        layout.params["wellRadius"]        = 9.0;
        layout.params["readoutAliasScale"] = 0.85; // crisper on the dark LED box
        layout.params["typeArrowExtra"]    = 6.0;
        layout.params["curveDbTop"]        = 40.0;   // keep high-Q bodies inside the hardware display
        layout.params["curveDbBottom"]     = -40.0;
        layout.params["fontBold"]          = 0.0;    // natural weight — synthetic bold smudges at label sizes (Tyson 2026-07-11: "too bold")

        // The whole-UI typeface. Hand-editable live from ui_layout.json
        // ("strings":{"fontFamily":"<any installed font>"}). Choose weight via a
        // weight-named family rather than synthetic bold.
        // Tahoma at natural weight — the face that never drew a complaint;
        // Bahnschrift read "typography sucks". Synthetic bold stays off.
        layout.strings["fontFamily"] = "Tahoma";
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
