#include "parameters/TrenchParameters.h"

namespace TrenchParameters
{

juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout()
{
    juce::AudioProcessorValueTreeState::ParameterLayout layout;

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::morph, 1 },
        "Morph",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.729f));

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::q, 1 },
        "Q",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));

    layout.add (std::make_unique<juce::AudioParameterInt> (
        juce::ParameterID { ParamID::body, 1 },
        "Body",
        0,
        127,
        0));

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::slamDrive, 1 },
        "Slam",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.35f));

    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::inputMode, 1 },
        "Input",
        juce::StringArray { "OFF", "SLAM", "EOS" },
        0));  // default = OFF — input character must be opt-in, not on-by-default

    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::bitDepth, 1 },
        "Bit Depth",
        juce::StringArray { "24", "20", "16" },
        0));  // default = 24-bit

    return layout;
}

} // namespace TrenchParameters
