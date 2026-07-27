#include "parameters/TrenchParameters.h"
#include "TrenchBodyRoster.h"
#include "dsp/FuncGenPatterns.h"
namespace TrenchParameters
{
juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout()
{
    juce::AudioProcessorValueTreeState::ParameterLayout layout;
    const auto pctAttribs = [] {
        return juce::AudioParameterFloatAttributes()
            .withLabel ("%")
            .withStringFromValueFunction ([] (float v, int) { return juce::String (v * 100.0f, 1); })
            .withValueFromStringFunction ([] (const juce::String& s) { return s.getFloatValue() / 100.0f; });
    };
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::morph, 1 },
        "Morph",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.5f, pctAttribs()));
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::q, 1 },
        "Q",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f, pctAttribs()));
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::chew, 1 },
        "CHEW",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f, pctAttribs()));
    layout.add (std::make_unique<juce::AudioParameterInt> (
        juce::ParameterID { ParamID::body, 1 },
        "Body",
        0,
        trench::kBodyParamMaxIndex,
        trench::kDefaultBodyIndex));
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::amount, 1 },
        "MIX",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        1.0f, pctAttribs()));
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::slamDrive, 1 },
        "Slam",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.1f));
    layout.add (std::make_unique<juce::AudioParameterBool> (
        juce::ParameterID { ParamID::modOn, 1 },
        "Mod",
        false));
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::modTrigger, 1 },
        "Mod Trigger",
        juce::StringArray { "ENV", "SYNC", "RISER" },
        0));
    juce::StringArray shapeNames { "SINE", "TRI", "RAMP", "STAIR", "SQUARE", "RANDOM" };
    for (int i = 0; i < trench::kNumFuncGenPatterns; ++i)
        shapeNames.add (trench::kFuncGenPatterns[i].name);
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::modShape, 1 },
        "Mod Shape",
        shapeNames,
        0));
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::modNote, 1 },
        "Mod Note",
        juce::StringArray { "4 BAR", "2 BAR", "1 BAR", "1/2", "1/4", "1/8", "1/16", "1/32",
                            "3/8", "3/16", "5/16", "1/6", "1/12", "5/8", "7/16" },
        5));
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::modFeel, 1 },
        "Mod Feel",
        juce::StringArray { "STRAIGHT", "TRIPLET", "DOTTED" },
        0));
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::modDepth, 1 },
        "Mod Depth",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.5f, pctAttribs()));
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::keySnap, 1 },
        "Key Snap",
        juce::StringArray {
            "Off",
            "C m", "C# m", "D m", "D# m", "E m", "F m",
            "F# m", "G m", "G# m", "A m", "A# m", "B m",
            "C M", "C# M", "D M", "D# M", "E M", "F M",
            "F# M", "G M", "G# M", "A M", "A# M", "B M"
        },
        0));
    return layout;
}
}
