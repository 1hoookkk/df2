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
        // Rects measured from the real panel cutouts in df2_panel_shadow.png
        // (connected-component bounds), inset ~3px so imperfect cut edges hide
        // behind each control's own bevel.
        // Wells measured to-the-edge from the baked dark cutouts in df2_panel_shadow.png
        // (connected-component bounds at lum<70). GROUND TRUTH — the control fills the
        // dark recess; the faceplate's bevel/shadow just outside it stays as the edge.
        // Re-measured 2026-07-03: lum<70 caught the outer bezel ring, not the slot —
        // these are the INNER dark openings (longest lum<30 run at well mid-height),
        // so the drum seats inside the slot instead of riding the bezel.
        layout.elements["morphWheel"]   = { { 120.0f, 691.0f, 422.0f, 98.0f },  {}, {} };
        layout.elements["qWheel"]       = { { 119.0f, 873.0f, 424.0f, 106.0f }, {}, {} };
        // FLUSH in the measured wells (Tyson 2026-07-02: "have everything sit flush
        // in the wells with no huge gaps"). Rects = the panel art's cut-out openings,
        // auto-detected from df2_panel_shadow.png (gray<70 floors, scipy label) and
        // overlay-verified. Do not hand-nudge; re-measure if the art changes.
        layout.elements["typeSelector"] = { { 226.0f, 129.0f, 682.0f, 67.0f },  {}, {} };
        layout.elements["morphReadout"] = { { 589.0f, 714.0f, 178.0f, 63.0f },  18.0f, juce::Colours::black };
        layout.elements["qReadout"]     = { { 589.0f, 903.0f, 178.0f, 63.0f },  18.0f, juce::Colours::black };
        layout.elements["spectrumGrid"] = { { 118.0f, 222.0f, 790.0f, 389.0f }, {}, {} }; // the wine shell's glass opening (overlay-verified)
        layout.elements["slotPad"]      = { { 780.0f, 234.0f, 112.0f, 26.0f }, {}, {} }; // thin 1/2 selector tucked flush into the display's top-right
        layout.elements["modulateTag"]  = { { 150.0f, 452.0f, 430.0f, 56.0f }, {}, {} }; // clickable word on the glass; hit-test is the visible "Modulation" text only
        layout.elements["filterLabel"]  = { { 135.0f, 44.0f, 220.0f, 72.0f },  11.5f, juce::Colour (0xffe2e9f2) };
        layout.elements["filterLabel"].text = "TRENCH";
        layout.elements["typeLabel"]    = { { 108.0f, 129.0f, 148.0f, 67.0f },  11.5f, juce::Colour (0xffe2e9f2) };
        layout.elements["typeLabel"].text = "TYPE";
        layout.elements["typeName"]     = { { 252.0f, 130.0f, 530.0f, 65.0f },  12.5f, juce::Colours::black };
        layout.elements["typeArrow"]    = { { 855.0f, 136.0f, 53.0f,  54.0f },  {}, {} }; // dropdown arrow box (the bar's divided end segment)
        layout.elements["morphLabel"]   = { { 111.0f, 636.0f, 443.0f, 42.0f },  11.5f, juce::Colour (0xffe2e9f2) };
        layout.elements["morphLabel"].text = "MORPH (%)";  // upper rail = MORPH on Page 1 (target refs' wording)
        layout.elements["qLabel"]       = { { 111.0f, 824.0f, 444.0f, 42.0f },  11.0f, juce::Colour (0xffe2e9f2) };
        layout.elements["qLabel"].text = "Q (%)";          // lower rail = Q on Page 1 (SLAM is the canvas drag)
        // Faceplate nameplate — REMOVED (Tyson 2026-07-02: "Remove the text at
        // the top"). Zero rects = hidden; the bare plate carries the identity.
        layout.elements["brandLabel"]   = { { 0.0f, 0.0f, 0.0f, 0.0f }, 13.0f, juce::Colour (0xff2c2418) };
        layout.elements["brandLabel"].text = "TRENCH";
        layout.elements["brandSub"]     = { { 0.0f, 0.0f, 0.0f, 0.0f }, 7.5f, juce::Colour (0xff574a35) };
        layout.elements["brandSub"].text = "MUSICAL FILTER";

        // Dark navy panel + wine glass palette (Tyson 2026-07-02 correction brief):
        // pale rose-white curve, muted amber for the Modulation lamp only, no cyan.
        layout.colours["wellTop"]     = juce::Colour (0xff9aa2b4); // navy-steel light
        layout.colours["wellBottom"]  = juce::Colour (0xff6b7386); // navy-steel, darker
        layout.colours["wellKeyline"] = juce::Colour (0xff3a4152); // navy-steel keyline
        layout.colours["bevelHi"]     = juce::Colour (0x88e3dcc9);
        layout.colours["bevelLo"]     = juce::Colour (0x28000000);
        layout.colours["arrow"]       = juce::Colour (0xff2b2620); // warm dark charcoal
        layout.colours["rim"]         = juce::Colour (0xff2b2620);
        layout.colours["accent"]      = juce::Colour (0xffe8ccd5); // dusty rose-white active state
        layout.colours["curveColour"] = juce::Colour (0xffe8ccd5); // quiet response; SLAM pushes it hotter in GraphDisplay
        layout.colours["phosphor"]    = juce::Colour (0xff1e0a14); // deep blue-black wine fallback if bitmap is missing
        layout.colours["amber"]       = juce::Colour (0xffc98a3c); // muted orange — Modulation active lamp only
        layout.colours["dashed"]      = juce::Colour (0xff2b1321); // low-contrast wine grid tone
        layout.colours["screenEdge"]  = juce::Colour (0xff0c1018); // blue-black aperture wash, not a red rectangle
        layout.colours["labelInk"]    = juce::Colour (0xff16130f); // compact black-brown hardware ink

        layout.params["wellRadius"]        = 9.0;
        layout.params["readoutAliasScale"] = 0.85; // crisper on the dark LED box
        layout.params["typeArrowExtra"]    = 6.0;
        layout.params["curveDbTop"]        = 40.0;   // keep high-Q bodies inside the hardware display
        layout.params["curveDbBottom"]     = -40.0;
        layout.params["fontBold"]          = 0.0;    // 0 = natural weight (no synthetic bold), 1 = emphasis on

        // The whole-UI typeface. Hand-editable live from ui_layout.json
        // ("strings":{"fontFamily":"<any installed font>"}). Choose weight via a
        // weight-named family rather than synthetic bold.
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
