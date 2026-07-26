#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
namespace ParamID
{
    inline constexpr auto morph     = "morph";
    inline constexpr auto q         = "q";
    inline constexpr auto body      = "body";
    inline constexpr auto slamDrive = "slamDrive";
    inline constexpr auto fiveD     = "fiveD";
    inline constexpr auto output    = "output";
    inline constexpr auto amount    = "amount";
    inline constexpr auto keySnap     = "keySnap";
    inline constexpr auto hdMode      = "hdMode";   // 78125 vs 39062.5 Hz island — a sound choice, kept by Tyson's verdict
    // MOD — the one modulation engine (trench::MorphMod). Produces an
    // additive morph/Q offset around the wheel positions each block.
    inline constexpr auto modOn      = "modOn";
    inline constexpr auto modTrigger = "modTrigger"; // choice: ENV,SYNC,RISER (index order != trench::ModTrigger enum order)
    inline constexpr auto modShape   = "modShape";   // choice: Sine,Tri,Ramp,Stair,Square,Random (Sync only)
    inline constexpr auto modNote    = "modNote";    // choice: 4bar,2bar,1bar,1/2,1/4,1/8,1/16,1/32
    inline constexpr auto modFeel    = "modFeel";    // choice: Straight,Triplet,Dotted
    inline constexpr auto modSync    = "modSync";    // choice: Sync,Free
    inline constexpr auto modRate    = "modRate";    // 0.05..20 Hz, free mode
    inline constexpr auto modDepth   = "modDepth";   // 0..1 morph travel
}
namespace TrenchParameters
{
    juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
}
