#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

namespace ParamID
{
    inline constexpr auto morph     = "morph";
    inline constexpr auto q         = "q";
    inline constexpr auto body      = "body";
    inline constexpr auto slamDrive = "slamDrive";
    inline constexpr auto inputMode = "inputMode";  // 0=OFF, 1=SLAM, 2=EOS (CVSD)
    inline constexpr auto bitDepth  = "bitDepth";   // 0=24-bit, 1=20-bit, 2=16-bit
}

namespace TrenchParameters
{
    juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
}
