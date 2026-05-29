#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

namespace ParamID
{
    inline constexpr auto morph     = "morph";
    inline constexpr auto q         = "q";
    inline constexpr auto body      = "body";
    inline constexpr auto slamDrive = "slamDrive";
    inline constexpr auto inputMode = "inputMode";  // 0=OFF, 1=SLAM, 2=EOS (CVSD)
    inline constexpr auto fiveD     = "fiveD";       // 5D / QSound depth: 0=Off,1=Narrow,2=Wide,3=Full
    inline constexpr auto output    = "output";      // final makeup gain, dB

    // Teleport motion mode — shakes/snaps Morph/Q around the host center.
    inline constexpr auto teleportMode       = "teleportMode";       // 0=Off 1=Noise 2=Strobe 3=Deriv
    inline constexpr auto teleportAmount     = "teleportAmount";     // 0..1
    inline constexpr auto teleportRate       = "teleportRate";       // Hz (Noise/Strobe only)
    inline constexpr auto teleportMorphDepth = "teleportMorphDepth"; // 0..1 fraction of amount on Morph
    inline constexpr auto teleportQDepth     = "teleportQDepth";     // 0..1 fraction of amount on Q
}

namespace TrenchParameters
{
    juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
}
