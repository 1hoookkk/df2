#pragma once
// Split from WorkstationEditor.cpp 2026-07-25 — no logic changes.
// Shared workstation UI law: plot scale, palette, per-stage response math.
// Internal linkage on purpose: each TU gets its own copy of the constants.
#include "WorkstationEditor.h"
#include <cmath>

namespace
{
constexpr double kEvalSampleRate = 39062.5;
constexpr float kMinHz = 20.0f;
constexpr float kMaxHz = 19530.0f; // remain below the 39.0625 kHz runtime Nyquist
constexpr float kMinDb = -60.0f;
constexpr float kMaxDb = 30.0f;
constexpr int kBinRowH = 20;
constexpr int kLaneRowH = 32;
constexpr int kTrayH = 96;
constexpr int kLanesH = 20 + 6 * kLaneRowH + 4;
constexpr int kDragThreshold = 3;

const juce::Colour kBg (0xff0a0d14);
const juce::Colour kPanel (0xff121924);
const juce::Colour kPanelDeep (0xff07090e);
const juce::Colour kBorder (0xff1e2d3d);
const juce::Colour kCyan (0xff00f0ff);
const juce::Colour kAmber (0xffffb547);
const juce::Colour kGreen (0xff00ff9d);
const juce::Colour kRed (0xffff5d5d);
const juce::Colour kText (0xffc9d8e4);
const juce::Colour kTextDim (0xff7e9bb2);
const juce::Colour kGridLabel (0xff4a6378);

const juce::Colour kLaneColours[6] = {
    juce::Colour (0xff5dd0ff), juce::Colour (0xff7dff9a), juce::Colour (0xffffd75d),
    juce::Colour (0xffff9d5d), juce::Colour (0xffd98cff), juce::Colour (0xffff6da8),
};

float stageMagDb (const float* c, double cosw, double sinw, double cos2w, double sin2w)
{
    const double numReal = c[0] + c[1] * cosw + c[2] * cos2w;
    const double numImag = -c[1] * sinw - c[2] * sin2w;
    const double denReal = 1.0 + c[3] * cosw + c[4] * cos2w;
    const double denImag = -c[3] * sinw - c[4] * sin2w;
    const double numMagSq = numReal * numReal + numImag * numImag;
    const double denMagSq = std::max (1e-12, denReal * denReal + denImag * denImag);
    return (float) (10.0 * std::log10 (std::max (1e-12, numMagSq / denMagSq)));
}

juce::File trenchDocsDir()
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory).getChildFile ("TRENCH");
}

// Documents may be OneDrive-redirected; older tools wrote to the local profile Documents.
juce::File trenchLocalDocsDir()
{
    return juce::File ("C:/Users/hooki/Documents/TRENCH");
}

const char* kCornerNames[4] = { "M0 / Q0", "M100 / Q0", "M0 / Q100", "M100 / Q100" };
const char* kCornerLabels[4] = { "M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100" };

void wordsFromBytes240 (const std::array<juce::uint8, 240>& bytes, juce::uint16 (&w)[4][6][5])
{
    int i = 0;
    for (int c = 0; c < 4; ++c)
        for (int s = 0; s < 6; ++s)
            for (int k = 0; k < 5; ++k)
            {
                w[c][s][k] = (juce::uint16) (bytes[(size_t) i] | (bytes[(size_t) i + 1] << 8));
                i += 2;
            }
}


// --- Designer constants (shared with the wheel handler in the editor) ---
struct DesignerMotif { const char* label; double oct; double zeroR; };
// ROM zero-grammar census (sweet-spot atlas, 777 lanes / 33 ROM bodies):
// tooth n=164, trailing n=93, leading n=227, far rail n=238 (~3 oct measured),
// true notch n=153. Starting points only — every field stays editable.
const DesignerMotif kDesignerMotifs[5] = {
    { "TOOTH        0 oct   r .95", 0.0, 0.95 },
    { "TRAILING  -0.6 oct   r .97", -0.6, 0.97 },
    { "LEADING   +0.9 oct   r .94", 0.9, 0.94 },
    { "FAR RAIL    +3 oct   r .95", 3.0, 0.95 },
    { "TRUE NOTCH +1.7 oct  r 1.0", 1.7, 1.0 },
};
const char* kDesignerTypeNames[5] = { "OFF", "EQ", "LP", "HP", "FREE" };
constexpr int kDesignerTypeFree = 4;
// one MD ladder step = ~68.4 cents; FREE freq wheel travels this grid
const double kDesignerLadderRatio = std::pow (2.0, 68.4 / 1200.0);

static_assert (sizeof (TrenchDesignerRow) == 48, "FFI row layout drifted");
static_assert (sizeof (TrenchDesignerSection) == 104, "FFI section layout drifted");
}
