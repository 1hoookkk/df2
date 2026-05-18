#pragma once

#include "BinaryData.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace trench::style
{
    // =====================================================================
    // Two-tier palette. Single source of truth for every UI colour.
    //
    // Chassis tier (60 : 30 : 10) — applies to everything OUTSIDE the screen
    // (rollers, value cells, body strip, LookAndFeel for popups / combos).
    //   60%  Neutral  — the red-tinted chassis PNG + dark wells + dim warm
    //                   greys. Mostly the chassis itself.
    //   30%  primary  — bone / warm off-white. All resting text + labels +
    //                   structural surfaces.
    //   10%  accent   — E-mu phosphor green. *Active state only* (roller
    //                   indicator, value-cell digits during change, body-
    //                   strip flash on cycle, toggle-on in popups). Never
    //                   decoration.
    //   +    clip     — single red-orange used only for meter peak / warning.
    //
    // OLED tier (multi-colour, Morpheus-faithful) — applies INSIDE the
    // central screen only. Each colour has exactly one functional role.
    // =====================================================================

    // ----- Chassis tier --------------------------------------------------
    inline juce::Colour screen()       { return juce::Colour (0xff050505); }  // OLED background
    inline juce::Colour chassisInk()   { return juce::Colour (0xff141821); }  // dark recessed wells
    inline juce::Colour hairline()     { return juce::Colour (0xff2f5a6e); }  // structural borders
    inline juce::Colour primary()      { return juce::Colour (0xffe5dccb); }  // bone (the 30%)
    inline juce::Colour primaryDim()   { return juce::Colour (0xff9aa096); }  // dim bone
    inline juce::Colour primaryFaint() { return juce::Colour (0xff5a605c); }  // very dim
    inline juce::Colour accent()       { return juce::Colour (0xff9aef5a); }  // phosphor (the 10%)
    inline juce::Colour accentDim()    { return juce::Colour (0xff5da838); }
    inline juce::Colour clip()         { return juce::Colour (0xffff6a3a); }  // meter clip warning

    // ----- OLED tier (screen-internal) ----------------------------------
    inline juce::Colour oledBg()       { return screen(); }
    inline juce::Colour oledWhite()    { return juce::Colour (0xfff6f8ff); }  // primary data (trace, digits, bar fills)
    inline juce::Colour oledGreen()    { return accent(); }                   // state names (live waypoint, algo)
    inline juce::Colour oledAmber()    { return juce::Colour (0xffffa838); }  // header, bit toggle, meter clip
    inline juce::Colour oledCyan()     { return juce::Colour (0xff8fc8ff); }  // diagnostic labels (Mode:, Rate:)
    inline juce::Colour oledBlue()     { return juce::Colour (0xff3a5fe0); }  // major vertical gridlines
    inline juce::Colour oledGreenDim() { return juce::Colour (0xff2a6428); }  // 0 dB reference line
    inline juce::Colour oledRedDim()   { return juce::Colour (0xff8a2826); }  // dim amplitude rule lines
    inline juce::Colour oledMagenta()  { return juce::Colour (0xffff5fb5); }  // F-style bar, pad top edge, R-side numeric
    inline juce::Colour oledRed()      { return juce::Colour (0xffff5050); }  // T-style bar, pad right edge, R meter label
    inline juce::Colour oledYellow()   { return juce::Colour (0xffffec32); }  // F/M/T bar letters, pad bottom edge, meter mid

    // ----- Legacy aliases ------------------------------------------------
    // Kept so existing call sites compile during the migration. Slated for
    // removal once every consumer has moved to the semantic names above.
    inline juce::Colour bgVoid()        { return juce::Colour (0xff0a0e14); }
    inline juce::Colour bgPanel()       { return chassisInk(); }
    inline juce::Colour bone()          { return primary(); }
    inline juce::Colour boneDim()       { return primaryDim(); }
    inline juce::Colour boneVeryDim()   { return primaryFaint(); }
    inline juce::Colour traceCyan()     { return accent(); }
    inline juce::Colour wordmarkCyan()  { return accent(); }
    inline juce::Colour tracePhosphor() { return accent(); }
    inline juce::Colour traceBloom()    { return accentDim(); }
    inline juce::Colour meterGreen()    { return accent(); }
    inline juce::Colour bypassOrange()  { return clip(); }
    inline juce::Colour lcdScreen()     { return screen(); }
    inline juce::Colour lcdScreenEdge() { return juce::Colour (0xff010201); }
    inline juce::Colour gridDot()       { return chassisInk(); }
    inline juce::Colour markerNode()    { return primary(); }
    inline juce::Colour traceShadow()   { return juce::Colour (0xff041006); }
    inline juce::Colour traceFill()     { return chassisInk(); }

    // ----- Typeface helpers (unchanged) ----------------------------------
    inline juce::Typeface::Ptr commitMonoRegular()
    {
        static auto face = juce::Typeface::createSystemTypefaceFor (
            BinaryData::CommitMonoRegular_otf,
            (size_t) BinaryData::CommitMonoRegular_otfSize);
        return face;
    }

    inline juce::Typeface::Ptr commitMonoBold()
    {
        static auto face = juce::Typeface::createSystemTypefaceFor (
            BinaryData::CommitMonoBold_otf,
            (size_t) BinaryData::CommitMonoBold_otfSize);
        return face;
    }

    inline juce::Typeface::Ptr neueMachinaBold()
    {
        static auto face = juce::Typeface::createSystemTypefaceFor (
            BinaryData::NeueMachinaBold_otf,
            (size_t) BinaryData::NeueMachinaBold_otfSize);
        return face;
    }

    inline juce::Font embeddedFont (juce::Typeface::Ptr face, float size, const char* fallback, int fallbackStyle)
    {
        if (face != nullptr)
            return juce::Font (juce::FontOptions (face).withHeight (size));

        return juce::Font (juce::FontOptions (fallback, size, fallbackStyle));
    }

    inline juce::Font wordmark (float size)
    {
        return embeddedFont (neueMachinaBold(), size, "Verdana", juce::Font::bold);
    }

    inline juce::Font label (float size, bool bold = true)
    {
        return embeddedFont (bold ? commitMonoBold() : commitMonoRegular(),
                             size, "Consolas",
                             bold ? juce::Font::bold : juce::Font::plain);
    }

    inline juce::Font readout (float size, bool bold = true)
    {
        return label (size, bold);
    }

    inline juce::Font watermark (float size)
    {
        return juce::Font (juce::FontOptions ("Times New Roman", size, juce::Font::italic));
    }
}
